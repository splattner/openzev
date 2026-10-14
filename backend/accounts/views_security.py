"""Account-security endpoints: changing the sign-in address and signing sessions
out. Spec: docs/specs/2026-03-community-and-access.md §5.6a and §5.6b; ADR 0022.
"""

import hashlib
import logging

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from redis.exceptions import RedisError
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import build_diff, record_audit_event

from zev import onboarding as zev_onboarding

from . import email_change, emails, notifications, password_reset
from .jwt_utils import impersonator_of
from .models import User
from .permissions import IsAdmin
from .session_revocation import keep_current_session, lock_current_session, revoke_sessions
from .throttling import AuthEmailChangeThrottle, AuthPasswordResetThrottle, AuthVerifyThrottle
from .views import _release_mail_slot, _reserve_mail_slot

logger = logging.getLogger(__name__)

NOT_WHILE_IMPERSONATING = {"detail": "This is not available while impersonating another account."}


def _audit(request, action_type, target, summary, *, actor=None, status_=AuditEventStatus.SUCCESS, **extra):
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.AUTH,
        action_type=action_type,
        target_type="accounts.User",
        target=target,
        target_id=str(target.pk) if target else "",
        target_display=(target.email or target.username) if target else "",
        summary=summary,
        user=actor,
        status=status_,
        **extra,
    )


class EmailChangeRequestView(APIView):
    """POST /me/email-change/ — ``{new_email, current_password}``.

    Sends a confirmation link to the *new* address; nothing changes until it is
    opened. The current password is required so a stolen session cannot
    re-point the account at an attacker's mailbox and keep it (the session alone
    proves nothing about the person holding it).

    Accounts with no usable password — participants, who sign in by emailed
    link, and OAuth-only accounts — cannot do this themselves: there is nothing
    to re-authenticate with, and for participants the address is the community
    owner's to maintain on the participant record. An admin can still edit it.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthEmailChangeThrottle]

    def post(self, request, *args, **kwargs):
        user = request.user
        if impersonator_of(request.auth):
            return Response(NOT_WHILE_IMPERSONATING, status=status.HTTP_403_FORBIDDEN)
        if not user.has_usable_password():
            return Response(
                {"detail": "Your email address is managed by your administrator.", "code": "no_password"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            new_email = serializers.EmailField().run_validation(str(request.data.get("new_email") or "").strip())
        except serializers.ValidationError:
            return Response({"detail": "Enter a valid email address."}, status=status.HTTP_400_BAD_REQUEST)

        if not user.check_password(str(request.data.get("current_password") or "")):
            _audit(
                request, "auth.email_change.failed", user,
                f"Refused an email change for {user.email or user.username}: wrong password.",
                actor=user, status_=AuditEventStatus.FAILED, metadata={"reason": "bad_password"},
            )
            return Response({"detail": "The password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)

        if new_email.lower() == user.email.lower():
            return Response({"detail": "That is already your email address."}, status=status.HTTP_400_BAD_REQUEST)

        generic = Response(
            {"detail": "If the address can be used, a confirmation link has been sent to it."},
            status=status.HTTP_202_ACCEPTED,
        )
        if email_change.address_in_use(new_email, excluding=user):
            # Indistinguishable from success, so this cannot be used to find out
            # which addresses have accounts. Audited so it is not invisible.
            _audit(
                request, "auth.email_change.failed", user,
                f"Refused an email change for {user.email or user.username}: address unavailable.",
                actor=user, status_=AuditEventStatus.DENIED, metadata={"reason": "address_in_use"},
            )
            return generic

        token = email_change.issue_token(user, new_email)
        confirm_url = f"{settings.FRONTEND_URL.rstrip('/')}/confirm-email-change?token={token}"
        try:
            emails.send_email_change_confirmation(new_email, confirm_url)
        except Exception:
            logger.exception("Could not send the email-change confirmation for user %s", user.pk)
            _audit(
                request, "auth.email_change.failed", user,
                "Could not send an email-change confirmation.",
                actor=user, status_=AuditEventStatus.FAILED, metadata={"reason": "mail_failed"},
            )
            return generic

        _audit(
            request, "auth.email_change.requested", user,
            f"Requested an email change for {user.email or user.username}.",
            actor=user, metadata={"new_email": new_email},
        )
        return generic


class EmailChangeConfirmView(APIView):
    """POST /confirm-email-change/ — ``{token}``.

    Unauthenticated by design: the link is opened from a mailbox, possibly on
    another device, and the token is the authority. Applying it signs the
    account out everywhere (the address is the credential's anchor) and mints no
    session — the person signs in again with the new address.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthVerifyThrottle]

    def post(self, request, *args, **kwargs):
        invalid = Response({"detail": "This link is invalid or has expired."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user, new_email = email_change.resolve_token(str(request.data.get("token") or "").strip())
        except email_change.EmailChangeError:
            return invalid

        with transaction.atomic():
            # Re-check under a row lock: two opens of the same link must not both
            # apply, and the address may have changed since resolve_token read it.
            locked = User.objects.select_for_update().get(pk=user.pk)
            if locked.email != user.email or email_change.address_in_use(new_email, excluding=locked):
                return invalid
            old_email = locked.email
            locked.email = new_email
            try:
                with transaction.atomic():
                    locked.save(update_fields=["email"])
            except IntegrityError:
                # Someone else took the address between the check and the write.
                return invalid
            revoke_sessions(locked)

        emails.send_email_change_notice(old_email, new_email)
        _audit(
            request, "auth.email_change.confirmed", locked,
            f"Changed the email address of {old_email} to {new_email}.",
            actor=locked, changes=build_diff({"email": old_email}, {"email": new_email}, ["email"]),
        )
        return Response({"detail": "Email address updated. Sign in again with the new address."})


PASSWORD_RESET_REQUEST_DETAIL = "If that address belongs to an account with a password, a reset link has been sent."


class PasswordResetRequestView(APIView):
    """POST /password-reset/ — ``{email}``.

    Always the same 202 and body, whether or not the address has an account that
    can be reset (see ``password_reset.can_reset``), a mail was sent, or sending
    failed: the answer must not tell a stranger which addresses are registered.
    The per-address cooldown is taken before the account is looked up, so it
    behaves the same for every address too. Mints no session.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthPasswordResetThrottle]

    def post(self, request, *args, **kwargs):
        if not isinstance(request.data, dict):
            return Response({"detail": "Expected an object."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            email = serializers.EmailField(max_length=User._meta.get_field("email").max_length).run_validation(
                str(request.data.get("email") or "").strip()
            )
        except serializers.ValidationError as exc:
            return Response({"email": exc.detail}, status=status.HTTP_400_BAD_REQUEST)

        accepted = Response({"detail": PASSWORD_RESET_REQUEST_DETAIL}, status=status.HTTP_202_ACCEPTED)
        key = "password-reset-mail:" + hashlib.sha256(email.lower().encode()).hexdigest()
        try:
            nonce = _reserve_mail_slot(key)
        except (RedisError, OSError):
            logger.exception("Could not reserve a password-reset mail slot")
            return accepted
        if nonce is None:
            return accepted

        user = User.objects.filter(email__iexact=email).first()
        if not password_reset.can_reset(user):
            return accepted

        reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={password_reset.issue_token(user)}"
        try:
            emails.send_password_reset_link(user.email, reset_url)
        except Exception:
            logger.exception("Could not send the password-reset link for user %s", user.pk)
            _release_mail_slot(key, nonce)
            return accepted

        # Nobody is signed in here, so no actor: the event is about the account.
        _audit(
            request, "password.reset_requested", user,
            f"Password reset link sent to {user.email}.",
        )
        return accepted


class PasswordResetConfirmView(APIView):
    """POST /password-reset/confirm/ — ``{token, new_password}``.

    Unauthenticated by design, like the email-change link: it is opened from a
    mailbox, possibly on another device, and the token is the authority. Sets the
    password and signs the account out everywhere, but mints **no** session: the
    person signs in again and meets their second factor like anyone else. Nothing
    here touches TOTP, passkeys or recovery codes.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthVerifyThrottle]

    def post(self, request, *args, **kwargs):
        invalid = Response({"detail": "This link is invalid or has expired."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(request.data, dict):
            return Response({"detail": "Expected an object."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = password_reset.resolve_token(str(request.data.get("token") or "").strip())
        except password_reset.PasswordResetError:
            return invalid

        new_password = request.data.get("new_password")
        if not isinstance(new_password, str) or not new_password:
            return Response({"detail": "A new password is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            # The token is untouched: the password hash it is bound to is unchanged.
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Re-check under a row lock: two opens of the same link must not both
            # apply, and the account may have changed since resolve_token read it.
            locked = User.objects.select_for_update().get(pk=user.pk)
            if locked.password != user.password or locked.email != user.email or not password_reset.can_reset(locked):
                return invalid
            locked.set_password(new_password)
            locked.must_change_password = False
            locked.save(update_fields=["password", "must_change_password"])
            revoke_sessions(locked)
            links_revoked = zev_onboarding.revoke_active_for_user(locked)

        _audit(
            request, "password.reset", locked,
            f"Reset the password of {locked.email or locked.username} with an emailed link.",
            actor=locked, metadata={"onboarding_links_revoked": links_revoked},
        )
        notifications.notify(locked, "password_reset", request=request)
        return Response({"detail": "Password updated. Sign in with the new password."})


class RevokeOwnSessionsView(APIView):
    """POST /me/sessions/revoke/ — sign out every *other* session.

    The caller keeps the one they are using: the response carries a fresh token
    pair under the new session version.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        user = lock_current_session(request)
        if impersonator_of(request.auth):
            return Response(NOT_WHILE_IMPERSONATING, status=status.HTTP_403_FORBIDDEN)
        revoke_sessions(user)
        response = Response({"detail": "All other sessions were signed out."})
        keep_current_session(request, response, user)
        _audit(
            request, "auth.sessions.revoked", user,
            f"Signed out all other sessions of {user.email or user.username}.",
            actor=user, metadata={"scope": "others"},
        )
        return response


class AdminRevokeSessionsView(APIView):
    """POST /users/<pk>/revoke-sessions/ — an admin signs an account out
    everywhere, for a suspected compromise. Not for the admin's own account:
    that would sign them out too, and the self-service action already exists."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, pk, *args, **kwargs):
        target = User.objects.filter(pk=pk).first()
        if target is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if target.pk == request.user.pk:
            return Response(
                {"detail": "Use “Sign out other devices” on your own account page."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        revoke_sessions(target)
        _audit(
            request, "auth.sessions.revoked", target,
            f"Signed out every session of {target.email or target.username}.",
            actor=request.user, metadata={"scope": "all"},
        )
        notifications.notify(target, "sessions_revoked_by_admin", request=request)
        return Response({"detail": "All sessions were signed out."})
