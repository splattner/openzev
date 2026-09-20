"""Passkey (WebAuthn) endpoints: self-service registration and management, and
the passwordless sign-in ceremony.

Spec: docs/specs/2026-09-two-factor-authentication.md §5.1 and §5.2;
ADR 0020 for why a user-verified passkey replaces the password.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import record_audit_event

from . import mfa, notifications, passkeys
from .cookies import set_auth_cookies
from .jwt_utils import make_jwt_for_user, record_login
from .models import User, WebAuthnCredential
from .serializers import WebAuthnCredentialSerializer
from .throttling import AuthPasskeyThrottle

GENERIC_FAILURE = {"detail": "Passkey verification failed."}


def _audit(request, action_type, user, summary, *, actor=None, status_=AuditEventStatus.SUCCESS, metadata=None):
    """The ``auth.*`` events all share the same target shape — the account."""
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.AUTH,
        action_type=action_type,
        target_type="accounts.User",
        target=user,
        target_id=str(user.pk) if user else "",
        target_display=(user.email or user.username) if user else "",
        summary=summary,
        user=actor,
        status=status_,
        metadata=metadata or {},
    )


def _format_aaguid(raw: str) -> str:
    """py_webauthn reports the AAGUID as a dashed UUID string already; keep
    it that way, and never let an odd value overflow the 36-char column."""
    return (raw or "")[:36]


class PasskeyListView(APIView):
    """GET /me/passkeys/ — the current user's own passkeys."""

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response(WebAuthnCredentialSerializer(request.user.webauthn_credentials.all(), many=True).data)


class PasskeyRegisterBeginView(APIView):
    """POST /me/passkeys/register/begin/ — options for
    ``navigator.credentials.create()``."""

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        return Response(passkeys.begin_registration(request.user))


class PasskeyRegisterCompleteView(APIView):
    """POST /me/passkeys/register/complete/ — ``{credential, name}``.

    Returns the stored passkey and, when this is the user's *first* factor,
    ten recovery codes, once — a passkey-only user needs the same escape hatch
    a TOTP user has (ADR 0020: recovery codes are the escape from both).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        credential = request.data.get("credential")
        if not isinstance(credential, dict):
            return Response({"detail": "A credential is required."}, status=status.HTTP_400_BAD_REQUEST)
        name = str(request.data.get("name") or "").strip()[:100] or "Passkey"

        try:
            verified = passkeys.complete_registration(user, credential)
        except passkeys.PasskeyCeremonyError as exc:
            return Response({"detail": f"Passkey registration failed ({exc.reason})."}, status=status.HTTP_400_BAD_REQUEST)

        first_factor = not mfa.has_any_factor(user)
        raw_transports = credential.get("response", {}).get("transports") if isinstance(credential.get("response"), dict) else None
        transports = [str(t) for t in raw_transports] if isinstance(raw_transports, list) else []

        try:
            with transaction.atomic():
                stored = WebAuthnCredential.objects.create(
                    user=user,
                    credential_id=verified.credential_id,
                    public_key=verified.credential_public_key,
                    sign_count=verified.sign_count,
                    transports=transports,
                    aaguid=_format_aaguid(str(verified.aaguid)),
                    name=name,
                )
        except IntegrityError:
            # credential_id is globally unique: this authenticator is already
            # registered (to this or another account).
            return Response({"detail": "This passkey is already registered."}, status=status.HTTP_409_CONFLICT)

        recovery_codes = mfa.issue_recovery_codes(user) if first_factor else []

        _audit(
            request, "auth.passkey.registered", user,
            f"Registered passkey '{name}' for {user.email or user.username}.",
            actor=user, metadata={"aaguid": stored.aaguid, "name": name},
        )
        _audit(
            request, "auth.mfa.enrolled", user,
            f"Enabled a passkey for {user.email or user.username}.",
            actor=user, metadata={"method": "passkey"},
        )
        notifications.notify(user, "passkey_added", request=request, detail=name)
        return Response(
            {"passkey": WebAuthnCredentialSerializer(stored).data, "recovery_codes": recovery_codes},
            status=status.HTTP_201_CREATED,
        )


class PasskeyDetailView(APIView):
    """PATCH renames, DELETE removes — always the caller's own credential."""

    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        return request.user.webauthn_credentials.filter(pk=pk).first()

    def patch(self, request, pk, *args, **kwargs):
        stored = self._get(request, pk)
        if stored is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = WebAuthnCredentialSerializer(stored, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk, *args, **kwargs):
        user = request.user
        stored = self._get(request, pk)
        if stored is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if mfa.removal_blocked(user, leaving=mfa.factor_count(user) - 1):
            return Response(
                {"detail": "Two-factor authentication is required for your role; add another factor before removing this one."},
                status=status.HTTP_409_CONFLICT,
            )

        name = stored.name
        stored.delete()
        mfa.drop_recovery_codes_if_unprotected(user)
        _audit(
            request, "auth.passkey.removed", user,
            f"Removed passkey '{name}' for {user.email or user.username}.",
            actor=user, metadata={"name": name},
        )
        notifications.notify(user, "passkey_removed", request=request, detail=name)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasskeyAuthenticateBeginView(APIView):
    """POST /passkeys/authenticate/begin/ — ``{email?}``. Options for
    ``navigator.credentials.get()`` with ``userVerification: "required"``."""

    permission_classes = [AllowAny]
    throttle_classes = [AuthPasskeyThrottle]

    def post(self, request, *args, **kwargs):
        return Response(passkeys.begin_authentication(str(request.data.get("email") or "")))


class PasskeyAuthenticateCompleteView(APIView):
    """POST /passkeys/authenticate/complete/ — ``{credential}`` → session.

    **No password is involved** (ADR 0020). ``AllowAny`` by necessity: the
    caller is not authenticated yet, and the verified assertion is what
    authenticates them.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthPasskeyThrottle]

    def post(self, request, *args, **kwargs):
        credential = request.data.get("credential")
        if not isinstance(credential, dict):
            return Response(GENERIC_FAILURE, status=status.HTTP_400_BAD_REQUEST)

        try:
            stored, verified = passkeys.complete_authentication(credential)
        except passkeys.PasskeyCeremonyError as exc:
            self._failed(request, exc.reason)
            return Response(GENERIC_FAILURE, status=status.HTTP_400_BAD_REQUEST)

        user = stored.user
        if not user.is_active:
            self._failed(request, "inactive_user", user)
            return Response(GENERIC_FAILURE, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            locked = WebAuthnCredential.objects.select_for_update().get(pk=stored.pk)
            if passkeys.is_sign_count_regression(locked.sign_count, verified.new_sign_count):
                regression = True
            else:
                regression = False
                locked.sign_count = verified.new_sign_count
                locked.last_used_at = timezone.now()
                locked.save(update_fields=["sign_count", "last_used_at"])
        if regression:
            _audit(
                request, "auth.passkey.sign_count_regression", user,
                f"Passkey '{stored.name}' reported a signature counter that went backwards for "
                f"{user.email or user.username}; possible cloned authenticator.",
                status_=AuditEventStatus.DENIED,
                metadata={"passkey": str(stored.pk), "stored": locked.sign_count, "reported": verified.new_sign_count},
            )
            return Response(GENERIC_FAILURE, status=status.HTTP_400_BAD_REQUEST)

        tokens = make_jwt_for_user(user)
        response = Response({"detail": "Login successful."})
        set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])
        record_login(user)
        _audit(
            request, "auth.login", user,
            f"Passkey login succeeded for {user.email or user.username}.",
            actor=user, metadata={"method": "passkey"},
        )
        return response

    def _failed(self, request, reason, user: User | None = None):
        _audit(
            request, "auth.mfa.challenge_failed", user,
            "Passkey verification failed" + (f" for {user.email or user.username}" if user else "") + ".",
            status_=AuditEventStatus.FAILED, metadata={"reason": reason, "method": "passkey"},
        )
