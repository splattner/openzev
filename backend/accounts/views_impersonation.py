"""Admin impersonation for active non-admin accounts.

Issue target-user tokens, preserve the original session, and audit start and end.
"""

from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
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
from .jwt_utils import IMPERSONATOR_CLAIM, add_custom_claims, impersonator_of
from .models import User
from .permissions import IsAdmin
from .serializers import UserSerializer
from .session_revocation import validate_refresh_token

# Impersonation covers the account's full access.
# Admin and inactive accounts are excluded.

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

        if target_user.is_admin or not target_user.is_active:
            _record(
                request,
                summary=f"Denied impersonation for {display}: admin or inactive account.",
                event_status=AuditEventStatus.DENIED,
                target=target_user,
                target_id=str(target_user.pk),
                target_display=display,
                metadata={"is_admin": target_user.is_admin, "is_active": target_user.is_active},
            )
            return Response(
                {"detail": "Admin and inactive accounts cannot be impersonated."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refresh = RefreshToken.for_user(target_user)
        add_custom_claims(refresh, target_user)
        refresh[IMPERSONATOR_CLAIM] = request.user.id

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
    """End impersonation and refresh the original session.

    Requires the impersonated user's authentication, not admin permissions.
    The parked refresh must belong to the impersonator's ordinary session.
    If restoration fails, clear browser auth cookies without revoking sessions.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        impersonator_id = impersonator_of(request.auth)
        if not impersonator_id:
            return Response(
                {"detail": "No active impersonation session."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        admin_refresh = request.COOKIES.get(ADMIN_REFRESH_COOKIE, "")
        try:
            token = validate_refresh_token(admin_refresh)
            if str(token[jwt_settings.USER_ID_CLAIM]) != str(impersonator_id) or impersonator_of(token):
                raise TokenError("The parked session does not belong to this impersonation.")
            serializer = TokenRefreshSerializer(data={"refresh": admin_refresh})
            serializer.is_valid(raise_exception=True)
        except (TokenError, ValidationError, AuthenticationFailed, User.DoesNotExist):
            response = Response(
                {
                    "detail": "Your admin session expired. Sign in again.",
                    "code": "impersonation_session_expired",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
            clear_auth_cookies(response)
        else:
            response = Response({"detail": "Impersonation ended."})
            set_auth_cookies(
                request,
                response,
                access=serializer.validated_data["access"],
                refresh=serializer.validated_data.get("refresh", admin_refresh),
            )

        impersonated = request.user
        display = impersonated.email or impersonated.username

        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="impersonation.end",
            target_type="accounts.User",
            target=impersonated,
            target_id=str(impersonated.pk),
            target_display=display,
            summary=f"Ended impersonation of {display}.",
            metadata={"impersonated_by": impersonator_id},
        )

        clear_auth_cookies(response, access_cookie=ADMIN_ACCESS_COOKIE, refresh_cookie=ADMIN_REFRESH_COOKIE)
        return response
