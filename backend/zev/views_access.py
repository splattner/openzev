"""Who may manage or view a ZEV: the grant API (#761, SPEC-2026-10-zev-access-grants §7.1, §8).

Admins and the ZEV's own managers give, change and take away ``manager`` and
``viewer`` access. Access is given to an email address: an existing account
gets the grant and a notice; an address with no account gets an inactive
account, the grant, and an invitation whose link activates it (the same
email-verification flow self-registration uses, with a 7-day link). A ZEV
always keeps at least one manager.
"""

from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import EmailVerificationToken, User, UserRole
from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import record_audit_event

from . import access
from .models import Participant, Zev, ZevAccessGrant, ZevAccessRole
from .services import build_unique_username

logger = logging.getLogger(__name__)

LAST_MANAGER_MESSAGE = "A ZEV needs at least one manager."
DISABLED_MESSAGE = "This ZEV is disabled. Ask an admin to re-enable it first."


# ── serializers ──────────────────────────────────────────────────────────────


def is_pending_invitation(user) -> bool:
    """An account created by an invitation that has not been accepted yet."""
    return not user.is_active and user.email_verification_tokens.filter(
        purpose=EmailVerificationToken.Purpose.INVITATION, consumed_at__isnull=True
    ).exists()


class ZevAccessGrantSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    granted_by = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = ZevAccessGrant
        fields = ["id", "zev", "role", "valid_from", "valid_to", "is_active", "granted_by", "created_at", "user"]
        read_only_fields = fields

    def get_user(self, grant):
        user = grant.user
        return {
            "id": user.pk,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "pending_invitation": is_pending_invitation(user),
        }

    def get_granted_by(self, grant):
        by = grant.granted_by
        return None if by is None else {"id": by.pk, "full_name": by.get_full_name() or by.email or by.username}

    def get_is_active(self, grant):
        today = timezone.localdate()
        return grant.valid_from <= today and (grant.valid_to is None or grant.valid_to >= today)


class ZevAccessCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=ZevAccessRole.choices)
    valid_to = serializers.DateField(required=False, allow_null=True)

    def validate_valid_to(self, value):
        if value is not None and value < timezone.localdate():
            raise serializers.ValidationError("The end date cannot be in the past.")
        return value


class ZevAccessUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ZevAccessRole.choices, required=False)
    valid_to = serializers.DateField(required=False, allow_null=True)

    def validate_valid_to(self, value):
        if value is not None and value < timezone.localdate():
            raise serializers.ValidationError("The end date cannot be in the past.")
        return value


# ── emails ───────────────────────────────────────────────────────────────────


def _send_access_email(
    *, template_key: str, defaults_by_language: dict, zev, grant, to: str, link_url: str, valid_days=None
) -> None:
    """Render and send one of the two access emails; raises on a send failure.

    Same policy as the magic-link mail (``invoices.emails``): the ZEV's invoice
    language unless an operator saved a custom template, and the shipped default
    when a custom template has an unusable placeholder.
    """
    from invoices.email_context import build_zev_access_email_context
    from invoices.models import ZEV_ACCESS_ROLE_NAMES_BY_LANGUAGE, EmailTemplate

    language = zev.invoice_language if zev.invoice_language in defaults_by_language else "en"
    defaults = defaults_by_language[language]
    override = EmailTemplate.objects.filter(template_key=template_key).first()
    inviter = grant.granted_by
    context = build_zev_access_email_context(
        zev_name=zev.name,
        role_name=ZEV_ACCESS_ROLE_NAMES_BY_LANGUAGE[language][grant.role],
        inviter_name=(inviter.get_full_name() or inviter.email) if inviter else "OpenZEV",
        link_url=link_url,
        valid_days=valid_days,
    )

    def render(template: str, fallback: str) -> str:
        try:
            return template.format(**context)
        except (KeyError, IndexError, ValueError):
            logger.warning("%s template has an unusable placeholder; sending the default instead.", template_key)
            return fallback.format(**context)

    EmailMessage(
        subject=render(override.subject if override else defaults["subject"], defaults["subject"]),
        body=render(override.body if override else defaults["body"], defaults["body"]),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
    ).send(fail_silently=False)


def _issue_invitation(user) -> EmailVerificationToken:
    """A fresh invitation link; earlier unused ones stop working."""
    user.email_verification_tokens.filter(
        purpose=EmailVerificationToken.Purpose.INVITATION, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())
    return EmailVerificationToken.objects.create(
        user=user, token=secrets.token_urlsafe(48), purpose=EmailVerificationToken.Purpose.INVITATION
    )


def send_invitation(zev, grant, token) -> None:
    from invoices.models import ZEV_ACCESS_INVITATION_EMAIL_DEFAULTS_BY_LANGUAGE

    _send_access_email(
        template_key="zev_access_invitation",
        defaults_by_language=ZEV_ACCESS_INVITATION_EMAIL_DEFAULTS_BY_LANGUAGE,
        zev=zev,
        grant=grant,
        to=grant.user.email,
        link_url=f"{settings.FRONTEND_URL.rstrip('/')}/verify-email?token={token.token}",
        valid_days=EmailVerificationToken.LIFETIMES[EmailVerificationToken.Purpose.INVITATION].days,
    )


def send_granted_notice(zev, grant) -> None:
    from invoices.models import ZEV_ACCESS_GRANTED_EMAIL_DEFAULTS_BY_LANGUAGE

    _send_access_email(
        template_key="zev_access_granted",
        defaults_by_language=ZEV_ACCESS_GRANTED_EMAIL_DEFAULTS_BY_LANGUAGE,
        zev=zev,
        grant=grant,
        to=grant.user.email,
        link_url=f"{settings.FRONTEND_URL.rstrip('/')}/login",
    )


# ── views ────────────────────────────────────────────────────────────────────


def _audit(request, zev, *, action_type, summary, grant=None, user=None, event_status=AuditEventStatus.SUCCESS,
           metadata=None, changes=None):
    target_user = user or (grant.user if grant else None)
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.GOVERNANCE,
        action_type=action_type,
        target_type="zev.ZevAccessGrant",
        target=grant,
        target_id=str(grant.pk) if grant else "",
        target_display=(target_user.email or target_user.username) if target_user else "",
        summary=summary,
        status=event_status,
        zev=zev,
        metadata={"user_id": target_user.pk if target_user else None, **(metadata or {})},
        changes=changes,
    )


class _ZevAccessBase(APIView):
    permission_classes = [IsAuthenticated]

    def visible_zev(self, request, zev_id) -> Zev:
        """The ZEV, or 404 for anyone who cannot see it (never confirm it exists)."""
        zev = get_object_or_404(Zev, pk=zev_id)
        if not access.can_view(request.user, zev):
            raise Http404
        return zev

    def refuse_write(self, request, zev, *, action_type):
        """A response refusing a write, or ``None`` when the caller may write."""
        if not access.can_manage(request.user, zev):
            _audit(request, zev, action_type=action_type, summary=f"Denied access change on {zev.name}: not a manager.",
                   event_status=AuditEventStatus.DENIED)
            return Response({"detail": "Only a manager of this ZEV can change who has access."},
                            status=status.HTTP_403_FORBIDDEN)
        if zev.disabled_at is not None and not request.user.is_admin:
            return Response({"detail": DISABLED_MESSAGE}, status=status.HTTP_400_BAD_REQUEST)
        return None

    def grant_in(self, zev, pk) -> ZevAccessGrant:
        """A grant of this ZEV that is in effect or yet to start (ended ones are history)."""
        today = timezone.localdate()
        grants = ZevAccessGrant.objects.select_related("user", "granted_by").filter(zev=zev)
        grants = grants.exclude(valid_to__lt=today)
        return get_object_or_404(grants, pk=pk)


class ZevAccessListView(_ZevAccessBase):
    """``GET`` the ZEV's grants; ``POST {email, role, valid_to?}`` gives access."""

    def get(self, request, zev_id):
        zev = self.visible_zev(request, zev_id)
        grants = ZevAccessGrant.objects.filter(zev=zev).select_related("user", "granted_by")
        if request.query_params.get("include_ended") not in ("true", "1"):
            grants = grants.exclude(valid_to__lt=timezone.localdate())
        grants = grants.order_by("role", "user__email", "valid_from", "id")
        return Response(ZevAccessGrantSerializer(grants, many=True).data)

    def post(self, request, zev_id):
        zev = self.visible_zev(request, zev_id)
        refusal = self.refuse_write(request, zev, action_type="zev_access.grant")
        if refusal is not None:
            return refusal
        payload = ZevAccessCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        email = payload.validated_data["email"].strip()
        role = payload.validated_data["role"]
        valid_to = payload.validated_data.get("valid_to")

        account = User.objects.filter(email__iexact=email).order_by("pk").first()
        if account is not None and account.is_admin:
            return Response({"email": ["Admins already have access to every ZEV."]}, status=status.HTTP_400_BAD_REQUEST)
        if account is not None and ZevAccessGrant.objects.filter(
            zev=zev, user=account, valid_to__isnull=True
        ).exists():
            return Response(
                {"email": ["This account already has access to this ZEV. Change its role instead."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invited = account is None
        with transaction.atomic():
            if invited:
                account = User.objects.create_user(
                    username=build_unique_username(first_name="", last_name="", email=email, fallback="user"),
                    email=email,
                    # The lowest of the old roles; what the account may do comes
                    # from its grants. The role collapses later (#761 step 7).
                    role=UserRole.PARTICIPANT,
                    is_active=False,
                )
                account.set_unusable_password()
                account.save(update_fields=["password"])
            grant = ZevAccessGrant.objects.create(
                zev=zev, user=account, role=role, valid_from=timezone.localdate(), valid_to=valid_to,
                granted_by=request.user,
            )
            token = _issue_invitation(account) if invited else None
        access.invalidate(account)

        email_sent = True
        try:
            if invited:
                send_invitation(zev, grant, token)
            else:
                send_granted_notice(zev, grant)
        except Exception:  # noqa: BLE001 - the grant stands; the response and the trail say the mail did not go
            logger.exception("Could not send the ZEV access email for grant %s", grant.pk)
            email_sent = False

        action_type = "zev_access.invite" if invited else "zev_access.grant"
        verb = "Invited" if invited else "Gave"
        _audit(
            request, zev, action_type=action_type, grant=grant,
            summary=f"{verb} {email} {role} access to {zev.name}.",
            event_status=AuditEventStatus.SUCCESS if email_sent else AuditEventStatus.FAILED,
            metadata={"role": role, "email_sent": email_sent, "valid_to": valid_to.isoformat() if valid_to else None},
        )
        data = ZevAccessGrantSerializer(grant).data
        data["email_sent"] = email_sent
        return Response(data, status=status.HTTP_201_CREATED)


class ZevAccessDetailView(_ZevAccessBase):
    """``PATCH {role?, valid_to?}`` changes a grant; ``DELETE`` revokes it."""

    def patch(self, request, zev_id, pk):
        zev = self.visible_zev(request, zev_id)
        refusal = self.refuse_write(request, zev, action_type="zev_access.change")
        if refusal is not None:
            return refusal
        grant = self.grant_in(zev, pk)
        payload = ZevAccessUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        role = data.get("role", grant.role)
        losing_manager = grant.role == ZevAccessRole.MANAGER and (
            role != ZevAccessRole.MANAGER or data.get("valid_to") is not None
        )
        if losing_manager and access.is_last_manager(grant):
            return Response({"detail": LAST_MANAGER_MESSAGE}, status=status.HTTP_400_BAD_REQUEST)

        # A role change opens a new grant from today; the end date must not
        # precede whichever start applies. Checked before anything is written.
        starts = timezone.localdate() if role != grant.role else grant.valid_from
        if data.get("valid_to") is not None and data["valid_to"] < starts:
            return Response({"valid_to": ["The end date cannot be before the start."]},
                            status=status.HTTP_400_BAD_REQUEST)

        before = {"role": grant.role, "valid_to": grant.valid_to.isoformat() if grant.valid_to else None}
        with transaction.atomic():
            if role != grant.role:
                grant = access.change_role(grant, role, by=request.user)
                grant = ZevAccessGrant.objects.select_related("user", "granted_by").get(pk=grant.pk)
            if "valid_to" in data:
                grant.valid_to = data["valid_to"]
                grant.save(update_fields=["valid_to", "updated_at"])
        access.invalidate(grant.user)
        after = {"role": grant.role, "valid_to": grant.valid_to.isoformat() if grant.valid_to else None}
        _audit(
            request, zev, action_type="zev_access.change", grant=grant,
            summary=f"Changed {grant.user.email or grant.user.username}'s access to {zev.name}.",
            changes={key: {"before": before[key], "after": after[key]} for key in before if before[key] != after[key]},
        )
        return Response(ZevAccessGrantSerializer(grant).data)

    def delete(self, request, zev_id, pk):
        zev = self.visible_zev(request, zev_id)
        refusal = self.refuse_write(request, zev, action_type="zev_access.revoke")
        if refusal is not None:
            return refusal
        grant = self.grant_in(zev, pk)
        if grant.role == ZevAccessRole.MANAGER and access.is_last_manager(grant):
            return Response({"detail": LAST_MANAGER_MESSAGE}, status=status.HTTP_400_BAD_REQUEST)

        user = grant.user
        display = user.email or user.username
        with transaction.atomic():
            access.revoke(grant)
            # An invitation nobody accepted leaves an account that never signed
            # in; once it has nothing left, it goes too.
            removed_account = False
            if (
                is_pending_invitation(user)
                and not ZevAccessGrant.objects.filter(user=user).exclude(valid_to__lt=timezone.localdate()).exists()
                and not Participant.objects.filter(user=user).exists()
            ):
                user.delete()
                removed_account = True
        if not removed_account:
            access.invalidate(user)
        _audit(
            request, zev, action_type="zev_access.revoke", user=user if not removed_account else None,
            summary=f"Revoked {display}'s access to {zev.name}.",
            metadata={"email": display, "removed_unaccepted_account": removed_account},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ZevAccessResendInvitationView(_ZevAccessBase):
    """``POST``: send a fresh invitation link to an account that has not accepted yet."""

    def post(self, request, zev_id, pk):
        zev = self.visible_zev(request, zev_id)
        refusal = self.refuse_write(request, zev, action_type="zev_access.resend_invitation")
        if refusal is not None:
            return refusal
        grant = self.grant_in(zev, pk)
        # Never activated: the invitation was not accepted (or its link expired).
        if grant.user.is_active:
            return Response({"detail": "This account has already accepted its invitation."},
                            status=status.HTTP_400_BAD_REQUEST)
        token = _issue_invitation(grant.user)
        email_sent = True
        try:
            send_invitation(zev, grant, token)
        except Exception:  # noqa: BLE001
            logger.exception("Could not resend the ZEV access invitation for grant %s", grant.pk)
            email_sent = False
        _audit(
            request, zev, action_type="zev_access.resend_invitation", grant=grant,
            summary=f"Resent the invitation to {grant.user.email} for {zev.name}.",
            event_status=AuditEventStatus.SUCCESS if email_sent else AuditEventStatus.FAILED,
            metadata={"email_sent": email_sent},
        )
        return Response({"email_sent": email_sent}, status=status.HTTP_202_ACCEPTED)
