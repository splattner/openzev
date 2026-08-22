"""Admin impersonation: issue a token as another user, and hand it back.

Split out of ``accounts.views`` because this is the most security-sensitive
surface in that module — it mints a JWT *as somebody else* — and it was the
only concern in there whose admin check was hand-written inside the handler
while ``IsAdmin`` sat unused two imports away.

Admin-ness is now declarative, and the DENIED audit event that the hand-written
check used to write is emitted from ``permission_denied`` so it cannot be
forgotten. Impersonation is also deliberately *not* self-service: the guard
that only participants and ZEV owners may be impersonated is what stops an
admin minting a token for another admin.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import record_audit_event

from .cookies import (
    ACCESS_COOKIE,
    ADMIN_ACCESS_COOKIE,
    ADMIN_REFRESH_COOKIE,
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)
from .models import User, UserRole
from .permissions import IsAdmin
from .serializers import UserSerializer

#: Only these roles may be impersonated. Admins are excluded on purpose — an
#: admin minting a token for another admin would be a privilege transfer with
#: no trace of which human was behind it.
IMPERSONATABLE_ROLES = (UserRole.PARTICIPANT, UserRole.ZEV_OWNER)

ACTION_TYPE = "impersonation.issue_token"


def _record(request, *, summary, event_status=AuditEventStatus.SUCCESS, target=None,
            target_id="", target_display="", metadata=None):
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.AUTH,
        action_type=ACTION_TYPE,
        target_type="accounts.User",
        target=target,
        target_id=target_id,
        target_display=target_display,
        summary=summary,
        status=event_status,
        metadata=metadata,
    )


class ImpersonateParticipantView(APIView):
    """Issue tokens as ``user_id`` while parking the caller's own tokens."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def permission_denied(self, request, message=None, code=None):
        # Matches the event the hand-written admin check used to write. Only an
        # authenticated non-admin is recorded; an anonymous caller gets a 401
        # and is not a governance event.
        if request.user.is_authenticated:
            user_id = self.kwargs.get("user_id")
            _record(
                request,
                summary="Denied impersonation token issuance by non-admin.",
                event_status=AuditEventStatus.DENIED,
                target_id=str(user_id),
                target_display=str(user_id),
            )
        super().permission_denied(request, message=message, code=code)

    def post(self, request, user_id: int, *args, **kwargs):
        try:
            target_user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            _record(
                request,
                summary=f"Impersonation target user {user_id} not found.",
                event_status=AuditEventStatus.FAILED,
                target_id=str(user_id),
                target_display=str(user_id),
            )
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        display = target_user.email or target_user.username

        if target_user.role not in IMPERSONATABLE_ROLES:
            _record(
                request,
                summary=f"Denied impersonation for {display} due to role guard.",
                event_status=AuditEventStatus.DENIED,
                target=target_user,
                target_id=str(target_user.pk),
                target_display=display,
                metadata={"role": target_user.role},
            )
            return Response(
                {"detail": "Only participant or ZEV owner users can be impersonated."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refresh = RefreshToken.for_user(target_user)
        refresh["role"] = target_user.role
        refresh["email"] = target_user.email
        refresh["full_name"] = target_user.get_full_name()
        refresh["must_change_password"] = target_user.must_change_password
        refresh["impersonated_by"] = request.user.id

        _record(
            request,
            summary=f"Issued impersonation token for {display}.",
            target=target_user,
            target_id=str(target_user.pk),
            target_display=display,
            metadata={"impersonated_by": request.user.id},
        )

        response = Response(
            {
                "impersonated_user": UserSerializer(target_user).data,
                "impersonator": UserSerializer(request.user).data,
            },
            status=status.HTTP_200_OK,
        )
        # Park the caller's current tokens in the backup cookies so
        # stop-impersonation can restore them, then overwrite the main pair.
        current_access = request.COOKIES.get(ACCESS_COOKIE, "")
        current_refresh = request.COOKIES.get(REFRESH_COOKIE, "")
        if current_access and current_refresh:
            set_auth_cookies(
                request,
                response,
                access=current_access,
                refresh=current_refresh,
                access_cookie=ADMIN_ACCESS_COOKIE,
                refresh_cookie=ADMIN_REFRESH_COOKIE,
            )
        set_auth_cookies(request, response, access=str(refresh.access_token), refresh=str(refresh))
        return response


class StopImpersonationView(APIView):
    """Restore the original admin tokens after ending an impersonation session.

    Deliberately only ``IsAuthenticated``: the caller here is holding the
    *impersonated* user's token, so requiring admin would make it impossible to
    get back. The authority comes from the backup cookies, which are httpOnly
    and only ever written by :class:`ImpersonateParticipantView`.

    Ending a session is audited so the impersonation window can be bounded; a
    no-op call with no backup pair is not, since it changes nothing.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        admin_access = request.COOKIES.get(ADMIN_ACCESS_COOKIE)
        admin_refresh = request.COOKIES.get(ADMIN_REFRESH_COOKIE)
        if not admin_access or not admin_refresh:
            return Response(
                {"detail": "No active impersonation session."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # request.user here is the *impersonated* user; the admin behind the
        # session is only recoverable from the claim the issuing view stamped
        # on the token.
        impersonated = request.user
        display = impersonated.email or impersonated.username
        impersonator_id = request.auth.get("impersonated_by") if request.auth is not None else None

        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="impersonation.end",
            target_type="accounts.User",
            target=impersonated,
            target_id=str(impersonated.pk),
            target_display=display,
            summary=f"Ended impersonation of {display}.",
            metadata={"impersonated_by": impersonator_id} if impersonator_id else None,
        )

        response = Response({"detail": "Impersonation ended."})
        set_auth_cookies(request, response, access=admin_access, refresh=admin_refresh)
        clear_auth_cookies(response, access_cookie=ADMIN_ACCESS_COOKIE, refresh_cookie=ADMIN_REFRESH_COOKIE)
        return response
