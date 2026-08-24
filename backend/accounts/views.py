from rest_framework import generics, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView
import logging
import secrets
from django.conf import settings
from django.utils.text import slugify
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from .api_keys import default_api_key_expiry, generate_key
from .models import (
    ApiKey,
    AppSettings,
    EmailVerificationToken,
    FeatureFlag,
    User,
    UserRole,
    VatRate,
)
from .serializers import (
    UserSerializer, UserCreateSerializer,
    ChangePasswordSerializer, CustomTokenObtainPairSerializer,
    ApiKeySerializer, ApiKeyCreateSerializer, AdminApiKeySerializer,
    AppSettingsSerializer,
    FeatureFlagSerializer,
    VatRateSerializer,
)
from .authentication import enforce_csrf
from .jwt_utils import make_jwt_for_user
from .cookies import (
    ADMIN_ACCESS_COOKIE,
    ADMIN_REFRESH_COOKIE,
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)
from .permissions import IsAdmin
from .throttling import AuthLoginThrottle, AuthRefreshThrottle, AuthRegisterThrottle, AuthVerifyThrottle
from audit.models import AuditActionCategory, AuditEventStatus
from audit.mixins import AuditedUpdateMixin
from audit.services import build_diff, record_audit_event

logger = logging.getLogger(__name__)



class CustomTokenObtainPairView(TokenObtainPairView):
    """JWT login — sets httpOnly cookies and returns a minimal JSON body."""
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [AuthLoginThrottle]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            set_auth_cookies(request, response, access=response.data["access"], refresh=response.data["refresh"])
            response.data = {"detail": "Login successful."}
        return response


class CookieTokenRefreshView(APIView):
    """Token refresh that reads the refresh token from the httpOnly cookie
    and writes the new access (and rotated refresh) token back as cookies."""
    permission_classes = [AllowAny]
    throttle_classes = [AuthRefreshThrottle]

    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get(REFRESH_COOKIE)
        if not refresh_token:
            return Response({"detail": "Refresh token not found."}, status=status.HTTP_401_UNAUTHORIZED)

        enforce_csrf(request)

        serializer = TokenRefreshSerializer(data={"refresh": refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except (TokenError, ValidationError):
            response = Response({"detail": "Token is invalid or expired."}, status=status.HTTP_401_UNAUTHORIZED)
            clear_auth_cookies(response)
            return response

        new_access = serializer.validated_data["access"]
        new_refresh = serializer.validated_data.get("refresh", refresh_token)
        response = Response({"detail": "Token refreshed."})
        set_auth_cookies(request, response, access=new_access, refresh=new_refresh)
        return response


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
def logout_view(request):
    """Clear auth cookies and end the session, even if the access cookie is expired."""
    response = Response({"detail": "Logged out."})
    clear_auth_cookies(response)
    # Also clear any active impersonation cookies
    clear_auth_cookies(response, access_cookie=ADMIN_ACCESS_COOKIE, refresh_cookie=ADMIN_REFRESH_COOKIE)
    return response


class UserListCreateView(generics.ListCreateAPIView):
    """Admin: list and create users."""
    permission_classes = [IsAdmin]

    def get_queryset(self):
        return User.objects.all().order_by("username")

    def get_serializer_class(self):
        return UserCreateSerializer if self.request.method == "POST" else UserSerializer

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
        user_display = instance.email or instance.username
        if instance.is_admin and not User.objects.filter(role=UserRole.ADMIN).exclude(pk=instance.pk).exists():
            record_audit_event(
                request=self.request,
                action_category=AuditActionCategory.AUTH,
                action_type="user.delete",
                target_type="accounts.User",
                target=instance,
                target_id=str(instance.pk),
                target_display=user_display,
                summary=f"Denied deletion of last admin {user_display}.",
                status=AuditEventStatus.DENIED,
            )
            raise PermissionDenied("Cannot delete the last admin account.")
        if instance.participations.exists():
            record_audit_event(
                request=self.request,
                action_category=AuditActionCategory.AUTH,
                action_type="user.delete",
                target_type="accounts.User",
                target=instance,
                target_id=str(instance.pk),
                target_display=user_display,
                summary=f"Denied deletion of linked user {user_display}.",
                status=AuditEventStatus.DENIED,
            )
            raise PermissionDenied("Linked participant accounts cannot be deleted.")
        user_id = str(instance.pk)
        # Record before delete so the actor FK is valid;
        # on_delete=SET_NULL nullifies it when the user row goes.
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.AUTH,
            action_type="user.delete",
            target_type="accounts.User",
            target_id=user_id,
            target_display=user_display,
            summary=f"Deleted user {user_display}.",
        )
        instance.delete()


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
        # An API key authenticates as exactly one user and carries no
        # impersonation state, so only JWTs are inspected for the claim.
        if token is not None and (hasattr(token, "get") or hasattr(token, "payload")):
            impersonator_id = token.get("impersonated_by") if hasattr(token, "get") else token.payload.get("impersonated_by")
            if impersonator_id:
                try:
                    impersonator = User.objects.get(pk=impersonator_id)
                    data["impersonated_by"] = UserSerializer(impersonator).data
                except User.DoesNotExist:
                    logger.warning(
                        "impersonation claim references deleted user %s", impersonator_id
                    )
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
@permission_classes([IsAuthenticated, IsAdmin])
def feature_flags_list(request):
    """Return all feature flags. Admin-only.

    Anonymous callers must not be able to enumerate internal flags; the
    login page uses the dedicated ``registration-enabled`` endpoint instead.
    Syncing defaults here is safe because only admins reach this view, so the
    unauthenticated write-amplification concern no longer applies.
    """
    FeatureFlag.sync_defaults()
    flags = FeatureFlag.objects.all()
    return Response(FeatureFlagSerializer(flags, many=True).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def registration_enabled(request):
    """Public, minimal endpoint exposing only whether self-registration is on.

    Returns a single boolean so the login page can decide whether to show the
    registration link, without enumerating the feature-flag table.
    """
    return Response(
        {"enabled": FeatureFlag.is_enabled(FeatureFlag.ZEV_SELF_REGISTRATION_ENABLED)}
    )


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
@permission_classes([AllowAny])
@throttle_classes([AuthRegisterThrottle])
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
@throttle_classes([AuthVerifyThrottle])
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

    tokens = make_jwt_for_user(user)
    response = Response({"detail": "Email verified."})
    set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])
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
    tokens = make_jwt_for_user(user)
    response = Response({"detail": "Password set successfully."})
    set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])
    return response


class ApiKeyListCreateView(generics.ListCreateAPIView):
    """A user's own API keys.

    Scoped to ``request.user`` with no way to widen it — not even for an admin.
    An admin can already act as anybody through the existing endpoints; being
    able to *read another person's credentials list* is a different power, and
    one nothing here needs.
    """

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return ApiKeyCreateSerializer if self.request.method == "POST" else ApiKeySerializer

    def get_queryset(self):
        # Revoked keys stay in the table so audit events can still resolve
        # api_key_id to a name; they just leave the list.
        return ApiKey.objects.filter(user=self.request.user, revoked_at__isnull=True)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        full_key, prefix, hashed_key = generate_key()
        expires_at = serializer.validated_data.get("expires_at") or default_api_key_expiry()

        api_key = ApiKey.objects.create(
            user=request.user,
            name=serializer.validated_data["name"],
            read_only=serializer.validated_data.get("read_only", False),
            prefix=prefix,
            hashed_key=hashed_key,
            expires_at=expires_at,
        )

        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="api_key.create",
            target_type="accounts.ApiKey",
            target=api_key,
            target_id=str(api_key.pk),
            target_display=api_key.name,
            summary=f"Created API key '{api_key.name}'.",
            metadata={
                "prefix": api_key.prefix,
                "read_only": api_key.read_only,
                "expires_at": api_key.expires_at,
            },
        )

        # The only response that carries the secret. It is not stored anywhere
        # and cannot be retrieved again.
        data = ApiKeySerializer(api_key).data
        data["key"] = full_key
        return Response(data, status=status.HTTP_201_CREATED)


class ApiKeyDetailView(generics.DestroyAPIView):
    """Revoke a key.

    DELETE revokes rather than deleting: the row is what lets an audit event's
    ``api_key_id`` still resolve to a name months later, which is the whole
    point of recording it. Revocation takes effect on the next request — the
    authentication path reads the row every time and nothing is cached.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ApiKeySerializer

    def get_queryset(self):
        return ApiKey.objects.filter(user=self.request.user, revoked_at__isnull=True)

    def perform_destroy(self, instance):
        instance.revoked_at = timezone.now()
        instance.save(update_fields=["revoked_at"])

        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.AUTH,
            action_type="api_key.revoke",
            target_type="accounts.ApiKey",
            target=instance,
            target_id=str(instance.pk),
            target_display=instance.name,
            summary=f"Revoked API key '{instance.name}'.",
            metadata={"prefix": instance.prefix},
        )


class AdminApiKeyListView(generics.ListAPIView):
    """Every API key in the system, for the admin console.

    Deliberately read-and-revoke only: there is no admin path that *creates* a
    key for somebody else. Minting a durable credential in another person's
    name is a strictly larger power than impersonation — impersonation is
    session-scoped and visible in the audit log as impersonation, whereas a key
    keeps working after the admin walks away, and every action it takes is
    attributed to its owner.

    Unlike the per-user list, revoked keys are included: the reason an admin
    opens this page is usually an incident, and "was this key revoked, and
    when?" is the question being asked.
    """

    permission_classes = [IsAdmin]
    serializer_class = AdminApiKeySerializer
    _VALID_STATUSES = ("active", "revoked")

    def get_queryset(self):
        queryset = ApiKey.objects.select_related("user").order_by("-created_at")

        user_id = self.request.query_params.get("user")
        if user_id:
            if not (user_id.isascii() and user_id.isdigit()):
                raise ValidationError({"user": ["Not a valid user id."]})
            queryset = queryset.filter(user_id=user_id)

        status_filter = self.request.query_params.get("status")
        if status_filter not in (None, *self._VALID_STATUSES):
            raise ValidationError(
                {"status": [f"Unknown status '{status_filter}'. Expected one of: {', '.join(self._VALID_STATUSES)}."]}
            )
        if status_filter == "active":
            queryset = queryset.filter(revoked_at__isnull=True)
        elif status_filter == "revoked":
            queryset = queryset.filter(revoked_at__isnull=False)

        return queryset


class AdminApiKeyDetailView(generics.DestroyAPIView):
    """Revoke any user's key.

    Revokes rather than deletes, matching the owner-facing endpoint: the row is
    what lets the admin console answer "when was this revoked, and by whom"
    afterwards. Takes effect on the next request — the authentication path
    reads the row every time and nothing is cached.
    """

    permission_classes = [IsAdmin]
    serializer_class = AdminApiKeySerializer
    queryset = ApiKey.objects.select_related("user")

    def perform_destroy(self, instance):
        if instance.revoked_at is not None:
            raise ValidationError({"detail": "This API key is already revoked."})

        instance.revoked_at = timezone.now()
        instance.save(update_fields=["revoked_at"])

        owner = instance.user
        acting_on_own_key = owner.pk == self.request.user.pk
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.AUTH,
            action_type="api_key.revoke",
            target_type="accounts.ApiKey",
            target=instance,
            target_id=str(instance.pk),
            target_display=instance.name,
            summary=(
                f"Revoked API key '{instance.name}'."
                if acting_on_own_key
                else f"Admin revoked API key '{instance.name}' owned by {owner.email or owner.username}."
            ),
            metadata={
                "prefix": instance.prefix,
                "owner_user_id": str(owner.pk),
                "owner_username": owner.username,
                # The distinguishing fact for anyone auditing later: this was
                # somebody else's credential, revoked by an administrator.
                "revoked_by_admin": not acting_on_own_key,
            },
        )
