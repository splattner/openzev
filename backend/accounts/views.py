from rest_framework import generics, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView
import json
import logging
import re
import secrets
import urllib.request
from urllib.parse import urlencode
from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils.text import slugify
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import OAuthExchangeCode, OAuthProvider, OAuthState, SocialAccount, User, UserRole, EmailVerificationToken
from .serializers import (
    UserSerializer, UserCreateSerializer,
    ChangePasswordSerializer, CustomTokenObtainPairSerializer,
    AppSettingsSerializer,
    FeatureFlagSerializer,
    OAuthProviderSerializer, OAuthProviderPublicSerializer,
    SocialAccountSerializer,
    VatRateSerializer,
)
from .models import AppSettings, FeatureFlag, VatRate
from .permissions import IsAdmin
from audit.models import AuditActionCategory, AuditEventStatus
from audit.mixins import AuditedUpdateMixin
from audit.services import build_diff, record_audit_event

logger = logging.getLogger(__name__)

# ── Auth cookie helpers ───────────────────────────────────────────────────────

_ACCESS_COOKIE = "openzev_access"
_REFRESH_COOKIE = "openzev_refresh"
_ADMIN_ACCESS_COOKIE = "openzev_admin_access"
_ADMIN_REFRESH_COOKIE = "openzev_admin_refresh"


def _cookie_kwargs() -> dict:
    """Shared kwargs for all auth cookies: httpOnly, Secure in prod, SameSite=Lax."""
    return {
        "httponly": True,
        "samesite": "Lax",
        "secure": not settings.DEBUG,
        "path": "/",
    }


def _set_auth_cookies(
    response,
    *,
    access: str,
    refresh: str,
    access_cookie: str = _ACCESS_COOKIE,
    refresh_cookie: str = _REFRESH_COOKIE,
) -> None:
    from datetime import timedelta
    jwt_settings = settings.SIMPLE_JWT
    access_max_age = int(jwt_settings.get("ACCESS_TOKEN_LIFETIME", timedelta(minutes=60)).total_seconds())
    refresh_max_age = int(jwt_settings.get("REFRESH_TOKEN_LIFETIME", timedelta(days=7)).total_seconds())
    kw = _cookie_kwargs()
    response.set_cookie(access_cookie, access, max_age=access_max_age, **kw)
    response.set_cookie(refresh_cookie, refresh, max_age=refresh_max_age, **kw)


def _clear_auth_cookies(
    response,
    access_cookie: str = _ACCESS_COOKIE,
    refresh_cookie: str = _REFRESH_COOKIE,
) -> None:
    response.delete_cookie(access_cookie, path="/")
    response.delete_cookie(refresh_cookie, path="/")


class CustomTokenObtainPairView(TokenObtainPairView):
    """JWT login — sets httpOnly cookies and returns a minimal JSON body."""
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            _set_auth_cookies(response, access=response.data["access"], refresh=response.data["refresh"])
            response.data = {"detail": "Login successful."}
        return response


class CookieTokenRefreshView(APIView):
    """Token refresh that reads the refresh token from the httpOnly cookie
    and writes the new access (and rotated refresh) token back as cookies."""
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get(_REFRESH_COOKIE)
        if not refresh_token:
            return Response({"detail": "Refresh token not found."}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = TokenRefreshSerializer(data={"refresh": refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except (TokenError, ValidationError):
            response = Response({"detail": "Token is invalid or expired."}, status=status.HTTP_401_UNAUTHORIZED)
            _clear_auth_cookies(response)
            return response

        new_access = serializer.validated_data["access"]
        new_refresh = serializer.validated_data.get("refresh", refresh_token)
        response = Response({"detail": "Token refreshed."})
        _set_auth_cookies(response, access=new_access, refresh=new_refresh)
        return response


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
def logout_view(request):
    """Clear auth cookies and end the session, even if the access cookie is expired."""
    response = Response({"detail": "Logged out."})
    _clear_auth_cookies(response)
    # Also clear any active impersonation cookies
    _clear_auth_cookies(response, access_cookie=_ADMIN_ACCESS_COOKIE, refresh_cookie=_ADMIN_REFRESH_COOKIE)
    return response


class UserListCreateView(generics.ListCreateAPIView):
    """Admin: create users. Admin/ZEV owner: list participant accounts for linking."""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return User.objects.all().order_by("username")
        if user.is_zev_owner:
            return User.objects.filter(role=UserRole.PARTICIPANT, is_active=True).order_by("username")
        raise PermissionDenied("Permission denied.")

    def get_serializer_class(self):
        return UserCreateSerializer if self.request.method == "POST" else UserSerializer

    def create(self, request, *args, **kwargs):
        if not request.user.is_admin:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.AUTH,
                action_type="user.create",
                target_type="accounts.User",
                summary="Denied user creation attempt by non-admin.",
                status=AuditEventStatus.DENIED,
            )
            raise PermissionDenied("Only admins can create users.")
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        user = serializer.save()
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.AUTH,
            action_type="user.create",
            target_type="accounts.User",
            target=user,
            target_id=str(user.pk),
            target_display=user.email or user.username,
            summary=f"Created user {user.email or user.username}.",
            metadata={"role": user.role, "is_active": user.is_active},
        )


class UserDetailView(AuditedUpdateMixin, generics.RetrieveUpdateDestroyAPIView):
    """Admin: retrieve / update / delete a user."""
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]

    audit_action_category = AuditActionCategory.AUTH
    audit_action_type = "user.update"
    audit_target_type = "accounts.User"
    audit_target_label = "user"

    def get_audit_target_display(self, instance):
        return instance.email or instance.username

    def perform_destroy(self, instance):
        if instance.participations.exists():
            record_audit_event(
                request=self.request,
                action_category=AuditActionCategory.AUTH,
                action_type="user.delete",
                target_type="accounts.User",
                target=instance,
                target_id=str(instance.pk),
                target_display=instance.email or instance.username,
                summary=f"Denied deletion of linked user {instance.email or instance.username}.",
                status=AuditEventStatus.DENIED,
            )
            raise PermissionDenied("Linked participant accounts cannot be deleted.")
        user_display = instance.email or instance.username
        user_id = str(instance.pk)
        instance.delete()
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.AUTH,
            action_type="user.delete",
            target_type="accounts.User",
            target_id=user_id,
            target_display=user_display,
            summary=f"Deleted user {user_display}.",
        )


class VatRateListCreateView(generics.ListCreateAPIView):
    queryset = VatRate.objects.all().order_by("-valid_from", "-created_at")
    permission_classes = [IsAdmin]

    serializer_class = VatRateSerializer

    def perform_create(self, serializer):
        try:
            vat_rate = serializer.save()
            record_audit_event(
                request=self.request,
                action_category=AuditActionCategory.GOVERNANCE,
                action_type="vat_rate.create",
                target_type="accounts.VatRate",
                target=vat_rate,
                target_id=str(vat_rate.pk),
                target_display=f"VAT {vat_rate.rate}%",
                summary=f"Created VAT rate {vat_rate.rate}%.",
                metadata={"valid_from": vat_rate.valid_from, "valid_to": vat_rate.valid_to},
            )
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", {"non_field_errors": exc.messages}))


class VatRateDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = VatRate.objects.all()
    permission_classes = [IsAdmin]
    serializer_class = VatRateSerializer

    def perform_update(self, serializer):
        instance = self.get_object()
        before = {
            "rate": str(instance.rate),
            "valid_from": instance.valid_from,
            "valid_to": instance.valid_to,
        }
        try:
            vat_rate = serializer.save()
            after = {
                "rate": str(vat_rate.rate),
                "valid_from": vat_rate.valid_from,
                "valid_to": vat_rate.valid_to,
            }
            record_audit_event(
                request=self.request,
                action_category=AuditActionCategory.GOVERNANCE,
                action_type="vat_rate.update",
                target_type="accounts.VatRate",
                target=vat_rate,
                target_id=str(vat_rate.pk),
                target_display=f"VAT {vat_rate.rate}%",
                summary=f"Updated VAT rate {vat_rate.rate}%.",
                changes=build_diff(before, after, ["rate", "valid_from", "valid_to"]),
            )
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", {"non_field_errors": exc.messages}))

    def perform_destroy(self, instance):
        vat_id = str(instance.pk)
        vat_display = f"VAT {instance.rate}%"
        instance.delete()
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type="vat_rate.delete",
            target_type="accounts.VatRate",
            target_id=vat_id,
            target_display=vat_display,
            summary=f"Deleted VAT rate {vat_display}.",
        )


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me(request):
    """Current user: retrieve or partial-update own profile.

    When a token carries an ``impersonated_by`` claim the response also
    includes a nested ``impersonated_by`` object so the frontend can render
    the impersonation banner without reading any token from storage.
    """
    if request.method == "GET":
        data = UserSerializer(request.user).data
        token = request.auth
        if token is not None:
            impersonator_id = token.get("impersonated_by") if hasattr(token, "get") else token.payload.get("impersonated_by")
            if impersonator_id:
                try:
                    impersonator = User.objects.get(pk=impersonator_id)
                    data["impersonated_by"] = UserSerializer(impersonator).data
                except User.DoesNotExist:
                    pass
        return Response(data)
    serializer = UserSerializer(request.user, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    serializer.save()
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.AUTH,
        action_type="password.change",
        target_type="accounts.User",
        target=request.user,
        target_id=str(request.user.pk),
        target_display=request.user.email or request.user.username,
        summary="Changed account password.",
    )
    return Response({"detail": "Password updated successfully."})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def app_settings(request):
    settings_instance = AppSettings.load()

    if request.method == "GET":
        return Response(AppSettingsSerializer(settings_instance).data)

    if not request.user.is_admin:
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type="app_settings.update",
            target_type="accounts.AppSettings",
            summary="Denied app settings update by non-admin.",
            status=AuditEventStatus.DENIED,
        )
        raise PermissionDenied("Only admins can update application settings.")

    before = {
        "date_format_short": settings_instance.date_format_short,
        "date_format_long": settings_instance.date_format_long,
        "date_time_format": settings_instance.date_time_format,
    }
    serializer = AppSettingsSerializer(settings_instance, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    updated = serializer.save()
    after = {
        "date_format_short": updated.date_format_short,
        "date_format_long": updated.date_format_long,
        "date_time_format": updated.date_time_format,
    }
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.GOVERNANCE,
        action_type="app_settings.update",
        target_type="accounts.AppSettings",
        target=updated,
        target_id="singleton",
        target_display="AppSettings",
        summary="Updated application settings.",
        changes=build_diff(
            before,
            after,
            ["date_format_short", "date_format_long", "date_time_format"],
        ),
    )
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([AllowAny])
def feature_flags_list(request):
    """Return all feature flags. Public read access is allowed."""
    FeatureFlag.sync_defaults()
    flags = FeatureFlag.objects.all()
    return Response(FeatureFlagSerializer(flags, many=True).data)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def feature_flag_update(request, pk: int):
    """Toggle a feature flag. Admin-only."""
    if not request.user.is_admin:
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type="feature_flag.update",
            target_type="accounts.FeatureFlag",
            target_id=str(pk),
            target_display=str(pk),
            summary="Denied feature flag update by non-admin.",
            status=AuditEventStatus.DENIED,
        )
        raise PermissionDenied("Only admins can update feature flags.")

    try:
        flag = FeatureFlag.objects.get(pk=pk)
    except FeatureFlag.DoesNotExist:
        return Response({"detail": "Feature flag not found."}, status=status.HTTP_404_NOT_FOUND)

    serializer = FeatureFlagSerializer(flag, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    before = {"enabled": flag.enabled}
    updated = serializer.save()
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.GOVERNANCE,
        action_type="feature_flag.update",
        target_type="accounts.FeatureFlag",
        target=updated,
        target_id=str(updated.pk),
        target_display=updated.name,
        summary=f"Updated feature flag {updated.name}.",
        changes=build_diff(before, {"enabled": updated.enabled}, ["enabled"]),
    )
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def impersonate_participant(request, user_id: int):
    if not request.user.is_admin:
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="impersonation.issue_token",
            target_type="accounts.User",
            target_id=str(user_id),
            target_display=str(user_id),
            summary="Denied impersonation token issuance by non-admin.",
            status=AuditEventStatus.DENIED,
        )
        raise PermissionDenied("Only admins can impersonate participants.")

    try:
        target_user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="impersonation.issue_token",
            target_type="accounts.User",
            target_id=str(user_id),
            target_display=str(user_id),
            summary=f"Impersonation target user {user_id} not found.",
            status=AuditEventStatus.FAILED,
        )
        return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

    if target_user.role not in (UserRole.PARTICIPANT, UserRole.ZEV_OWNER):
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="impersonation.issue_token",
            target_type="accounts.User",
            target=target_user,
            target_id=str(target_user.pk),
            target_display=target_user.email or target_user.username,
            summary=f"Denied impersonation for {target_user.email or target_user.username} due to role guard.",
            status=AuditEventStatus.DENIED,
            metadata={"role": target_user.role},
        )
        return Response({"detail": "Only participant or ZEV owner users can be impersonated."}, status=status.HTTP_400_BAD_REQUEST)

    refresh = RefreshToken.for_user(target_user)
    refresh["role"] = target_user.role
    refresh["email"] = target_user.email
    refresh["full_name"] = target_user.get_full_name()
    refresh["must_change_password"] = target_user.must_change_password
    refresh["impersonated_by"] = request.user.id

    record_audit_event(
        request=request,
        action_category=AuditActionCategory.AUTH,
        action_type="impersonation.issue_token",
        target_type="accounts.User",
        target=target_user,
        target_id=str(target_user.pk),
        target_display=target_user.email or target_user.username,
        summary=f"Issued impersonation token for {target_user.email or target_user.username}.",
        metadata={"impersonated_by": request.user.id},
    )

    response = Response(
        {
            "impersonated_user": UserSerializer(target_user).data,
            "impersonator": UserSerializer(request.user).data,
        },
        status=status.HTTP_200_OK,
    )
    # Preserve the current admin tokens in backup cookies so they can be
    # restored when impersonation ends, then overwrite main cookies with the
    # impersonation tokens.
    current_access = request.COOKIES.get(_ACCESS_COOKIE, "")
    current_refresh = request.COOKIES.get(_REFRESH_COOKIE, "")
    if current_access and current_refresh:
        _set_auth_cookies(
            response,
            access=current_access,
            refresh=current_refresh,
            access_cookie=_ADMIN_ACCESS_COOKIE,
            refresh_cookie=_ADMIN_REFRESH_COOKIE,
        )
    _set_auth_cookies(response, access=str(refresh.access_token), refresh=str(refresh))
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def stop_impersonation(request):
    """Restore the original admin tokens after ending an impersonation session."""
    admin_access = request.COOKIES.get(_ADMIN_ACCESS_COOKIE)
    admin_refresh = request.COOKIES.get(_ADMIN_REFRESH_COOKIE)
    if not admin_access or not admin_refresh:
        return Response({"detail": "No active impersonation session."}, status=status.HTTP_400_BAD_REQUEST)

    response = Response({"detail": "Impersonation ended."})
    _set_auth_cookies(response, access=admin_access, refresh=admin_refresh)
    _clear_auth_cookies(response, access_cookie=_ADMIN_ACCESS_COOKIE, refresh_cookie=_ADMIN_REFRESH_COOKIE)
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    """Self-registration: create a pending zev_owner account and send a verification email."""
    if not FeatureFlag.is_enabled(FeatureFlag.ZEV_SELF_REGISTRATION_ENABLED):
        return Response(
            {"detail": "Self-registration is currently disabled."},
            status=status.HTTP_403_FORBIDDEN,
        )

    email = request.data.get("email", "").strip()

    errors = {}
    if not email:
        errors["email"] = "Email is required."
    if errors:
        return Response(errors, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email__iexact=email).exists():
        return Response({"email": "An account with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

    email_local = slugify(email.split("@", 1)[0]).replace("-", ".") if "@" in email else ""
    base_username = email_local or "owner"
    username = base_username
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base_username}{suffix}"

    user = User.objects.create_user(
        username=username,
        email=email,
        role=UserRole.ZEV_OWNER,
        is_active=False,
        must_change_password=True,
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])

    token = EmailVerificationToken.objects.create(
        user=user,
        token=secrets.token_urlsafe(48),
    )

    frontend_url = settings.FRONTEND_URL.rstrip("/")
    verify_url = f"{frontend_url}/verify-email?token={token.token}"

    from invoices.models import EmailTemplate, EMAIL_TEMPLATE_DEFAULTS

    defaults = EMAIL_TEMPLATE_DEFAULTS["email_verification"]
    override = EmailTemplate.objects.filter(template_key="email_verification").first()
    subject_tpl = override.subject if override else defaults["subject"]
    body_tpl = override.body if override else defaults["body"]

    template_ctx = {"verify_url": verify_url}

    try:
        subject = subject_tpl.format_map(template_ctx)
        body = body_tpl.format_map(template_ctx)
    except (KeyError, ValueError):
        subject = defaults["subject"].format_map(template_ctx)
        body = defaults["body"].format_map(template_ctx)

    EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
    ).send(fail_silently=False)

    return Response({"detail": "Verification email sent. Please check your inbox."}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
def verify_email(request):
    """Consume a one-time verification token and return JWT tokens to auto-login the user."""
    token_value = request.data.get("token", "").strip()
    if not token_value:
        return Response({"detail": "Token is required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        token = EmailVerificationToken.objects.select_related("user").get(token=token_value)
    except EmailVerificationToken.DoesNotExist:
        return Response({"detail": "Invalid or expired verification link."}, status=status.HTTP_400_BAD_REQUEST)

    if not token.is_valid():
        return Response(
            {"detail": "This verification link has expired or already been used."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    token.consumed_at = timezone.now()
    token.save(update_fields=["consumed_at"])

    user = token.user
    user.is_active = True
    user.save(update_fields=["is_active"])

    record_audit_event(
        action_category=AuditActionCategory.AUTH,
        action_type="email.verify",
        target_type="accounts.User",
        target=user,
        target_id=str(user.pk),
        target_display=user.email or user.username,
        summary=f"Verified email for {user.email or user.username}.",
        user=user,
        changes=build_diff({"is_active": False}, {"is_active": user.is_active}, ["is_active"]),
    )

    refresh = RefreshToken.for_user(user)
    response = Response({"detail": "Email verified."})
    _set_auth_cookies(response, access=str(refresh.access_token), refresh=str(refresh))
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_initial_password(request):
    """Set a password for a freshly verified account that has no usable password yet."""
    new_password = request.data.get("new_password", "")
    if not new_password:
        return Response({"detail": "new_password is required."}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    if not (user.must_change_password or not user.has_usable_password()):
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="password.set_initial",
            target_type="accounts.User",
            target=user,
            target_id=str(user.pk),
            target_display=user.email or user.username,
            summary="Denied initial password set because account is already initialized.",
            status=AuditEventStatus.DENIED,
        )
        return Response(
            {"detail": "Use the change-password endpoint instead."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_password)
    user.must_change_password = False
    user.save(update_fields=["password", "must_change_password"])

    record_audit_event(
        request=request,
        action_category=AuditActionCategory.AUTH,
        action_type="password.set_initial",
        target_type="accounts.User",
        target=user,
        target_id=str(user.pk),
        target_display=user.email or user.username,
        summary="Set initial password and completed first-login requirement.",
        changes=build_diff({"must_change_password": True}, {"must_change_password": False}, ["must_change_password"]),
    )

    # Issue fresh tokens so the updated claims (must_change_password=False) take effect
    refresh = RefreshToken.for_user(user)
    response = Response({"detail": "Password set successfully."})
    _set_auth_cookies(response, access=str(refresh.access_token), refresh=str(refresh))
    return response


# ─────────────────────────────────────────────────────────────────────────────
# OAuth 2.0 / OIDC
# ─────────────────────────────────────────────────────────────────────────────

def _make_jwt_for_user(user: User) -> dict:
    """Mint a JWT pair (access + refresh) for *user*, matching the custom claims."""
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    refresh["email"] = user.email
    refresh["full_name"] = user.get_full_name()
    refresh["must_change_password"] = user.must_change_password
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _generate_username_from_email(email: str) -> str:
    """Derive a unique, safe username from an email address."""
    base = slugify(email.split("@")[0])[:30] or "user"
    candidate = base
    counter = 1
    while User.objects.filter(username=candidate).exists():
        candidate = f"{base}{counter}"
        counter += 1
    return candidate


def _exchange_code_for_tokens(provider: OAuthProvider, code: str, redirect_uri: str) -> dict:
    """Call the provider's token endpoint and return the parsed JSON response."""
    body = urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
    }).encode()
    req = urllib.request.Request(
        provider.token_url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read())


def _fetch_user_info(provider: OAuthProvider, access_token: str) -> dict:
    """Fetch user profile from the provider's userinfo endpoint."""
    req = urllib.request.Request(
        provider.userinfo_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read())


# ── admin CRUD ────────────────────────────────────────────────────────────────

class OAuthProviderListCreateView(generics.ListCreateAPIView):
    """Admin: list and create OAuth provider configurations."""
    queryset = OAuthProvider.objects.all().order_by("name")
    serializer_class = OAuthProviderSerializer
    permission_classes = [IsAdmin]


class OAuthProviderDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Admin: retrieve, update or delete an OAuth provider configuration."""
    queryset = OAuthProvider.objects.all()
    serializer_class = OAuthProviderSerializer
    permission_classes = [IsAdmin]


# ── public provider list ──────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([AllowAny])
def oauth_providers_public(request):
    """Return enabled OAuth providers (no secrets). Used by the login page."""
    providers = OAuthProvider.objects.filter(enabled=True)
    return Response(OAuthProviderPublicSerializer(providers, many=True).data)


# ── initiate login / link ─────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def oauth_login_initiate(request, provider_slug: str):
    """Return the provider authorization URL for a login flow."""
    provider = get_object_or_404(OAuthProvider, name=provider_slug, enabled=True)
    state_token = secrets.token_urlsafe(32)
    OAuthState.objects.create(state=state_token, provider=provider)
    redirect_uri = provider.redirect_url
    params = {
        "client_id": provider.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": provider.scope,
        "state": state_token,
    }
    return Response({"redirect_url": f"{provider.authorization_url}?{urlencode(params)}"})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def oauth_link_initiate(request, provider_slug: str):
    """Return the provider authorization URL for an account-linking flow."""
    provider = get_object_or_404(OAuthProvider, name=provider_slug, enabled=True)
    state_token = secrets.token_urlsafe(32)
    OAuthState.objects.create(state=state_token, provider=provider, user=request.user)
    redirect_uri = provider.redirect_url
    params = {
        "client_id": provider.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": provider.scope,
        "state": state_token,
    }
    return Response({"redirect_url": f"{provider.authorization_url}?{urlencode(params)}"})


# ── callback (browser-facing, redirects back to frontend) ────────────────────

def oauth_callback(request, provider_slug: str):
    """
    Handle the redirect from an OAuth provider.

    This is a plain Django view (not DRF) because it returns an HTTP redirect
    that the browser follows, not a JSON response.
    """
    frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173").rstrip("/")
    error = request.GET.get("error")
    if error:
        # Never embed the provider-supplied error value in the redirect URL.
        # Any error from the provider results in a fixed slug so there is no
        # user-controlled content in the redirect target (CWE-601).
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=provider_error")

    code = request.GET.get("code")
    state_value = request.GET.get("state")
    if not code or not state_value:
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=missing_params")

    # Validate state (CSRF protection)
    try:
        state_obj = OAuthState.objects.select_related("provider", "user").get(
            state=state_value, provider__name=provider_slug
        )
    except OAuthState.DoesNotExist:
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=invalid_state")

    if not state_obj.is_valid():
        state_obj.delete()
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=state_expired")

    linking_user = state_obj.user
    provider = state_obj.provider
    state_obj.delete()

    # Exchange authorisation code for tokens and fetch user profile
    redirect_uri = provider.redirect_url
    try:
        token_data = _exchange_code_for_tokens(provider, code, redirect_uri)
        user_info = _fetch_user_info(provider, token_data["access_token"])
    except Exception:
        logger.exception("OAuth token exchange failed for provider %s", provider_slug)
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=token_exchange_failed")

    # Derive a stable identifier for the provider account
    provider_uid = str(user_info.get("sub") or user_info.get("id") or "")
    if not provider_uid:
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=missing_uid")

    email = (user_info.get("email") or "").strip().lower()

    if linking_user is not None:
        # ── Link flow: attach to the (already authenticated) user ────────
        if SocialAccount.objects.filter(provider=provider, uid=provider_uid).exclude(user=linking_user).exists():
            # The provider account is already linked to a different user
            return HttpResponseRedirect(
                f"{frontend_url}/account?oauth_error=already_linked_other"
            )
        SocialAccount.objects.get_or_create(
            provider=provider,
            uid=provider_uid,
            defaults={"user": linking_user, "extra_data": user_info},
        )
        return HttpResponseRedirect(f"{frontend_url}/account?oauth_linked=true")

    # ── Login flow: find or create the local user ─────────────────────────
    try:
        social = SocialAccount.objects.select_related("user").get(
            provider=provider, uid=provider_uid
        )
        user = social.user
    except SocialAccount.DoesNotExist:
        if email:
            try:
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                # Auto-provision a new account for this OAuth identity
                username = _generate_username_from_email(email)
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=user_info.get("given_name", ""),
                    last_name=user_info.get("family_name", ""),
                    password=None,
                    is_active=True,
                    role=UserRole.PARTICIPANT,
                )
        else:
            return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=no_email")

        SocialAccount.objects.create(
            provider=provider,
            uid=provider_uid,
            user=user,
            extra_data=user_info,
        )

    if not user.is_active:
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=account_inactive")

    # Issue a short-lived exchange code for the frontend to convert to JWT
    exchange_code = secrets.token_urlsafe(32)
    OAuthExchangeCode.objects.create(code=exchange_code, user=user)
    return HttpResponseRedirect(f"{frontend_url}/oauth/callback?code={exchange_code}")


# ── token exchange ────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def oauth_token_exchange(request):
    """
    Exchange a short-lived OAuth exchange code for JWT tokens.

    The frontend calls this after being redirected back from the OAuth callback.
    """
    code = request.data.get("code", "").strip()
    if not code:
        return Response({"detail": "code is required."}, status=status.HTTP_400_BAD_REQUEST)

    # Validate format before touching the DB: exchange codes are
    # URL-safe base64 tokens (alphanumeric + - and _), max 64 chars.
    if not re.fullmatch(r'[A-Za-z0-9_\-]{10,64}', code):
        return Response({"detail": "Invalid or expired code."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        exchange = OAuthExchangeCode.objects.select_related("user").get(code=code)
    except OAuthExchangeCode.DoesNotExist:
        return Response({"detail": "Invalid or expired code."}, status=status.HTTP_400_BAD_REQUEST)

    if not exchange.is_valid():
        exchange.delete()
        return Response({"detail": "Code has expired."}, status=status.HTTP_400_BAD_REQUEST)

    user = exchange.user
    exchange.delete()

    tokens = _make_jwt_for_user(user)
    response = Response({"detail": "Login successful."})
    _set_auth_cookies(response, access=tokens["access"], refresh=tokens["refresh"])
    return response


# ── social accounts (current user) ───────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def social_accounts_list(request):
    """List the OAuth social accounts linked to the current user."""
    accounts = SocialAccount.objects.filter(user=request.user).select_related("provider")
    return Response(SocialAccountSerializer(accounts, many=True).data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def social_account_delete(request, pk: int):
    """Unlink a social account from the current user."""
    account = get_object_or_404(SocialAccount, pk=pk, user=request.user)
    account.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
