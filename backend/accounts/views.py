from rest_framework import generics, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.views import APIView
import logging
import secrets
import pyotp
from django.conf import settings
from django.db import transaction
from django.utils.text import slugify
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage
from django.utils import timezone
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from . import mfa, mfa_crypto
from .api_keys import default_api_key_expiry, generate_key
from .models import (
    ApiKey,
    AppSettings,
    EmailVerificationToken,
    FeatureFlag,
    MfaRecoveryCode,
    TotpDevice,
    User,
    UserRole,
    VatRate,
)
from .serializers import (
    UserSerializer, UserCreateSerializer, ChangePasswordSerializer, CustomTokenObtainPairSerializer,
    ApiKeySerializer, ApiKeyCreateSerializer, AdminApiKeySerializer,
    AppSettingsSerializer,
    FeatureFlagSerializer,
    TotpDeviceSerializer,
    VatRateSerializer,
    WebAuthnCredentialSerializer,
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
from .throttling import AuthLoginThrottle, AuthMfaThrottle, AuthRefreshThrottle, AuthRegisterThrottle, AuthVerifyThrottle
from audit.models import AuditActionCategory, AuditEventStatus
from audit.mixins import AuditedUpdateMixin
from audit.services import build_diff, record_audit_event

logger = logging.getLogger(__name__)



class CustomTokenObtainPairView(TokenObtainPairView):
    """JWT login — sets httpOnly cookies and returns a minimal JSON body."""
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [AuthLoginThrottle]

    def post(self, request, *args, **kwargs):
        # Reimplements TokenObtainPairView.post rather than wrapping it: the
        # serializer instance is the only place the attempted username lives
        # (on failure) or the authenticated user lives (on success,
        # ``serializer.user``), and both are needed for the audit event below.
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            self._record_login_failed(request)
            raise InvalidToken(exc.args[0]) from exc
        except (AuthenticationFailed, ValidationError):
            self._record_login_failed(request)
            raise

        user = serializer.user
        if mfa.has_active_factor(user):
            # Password verified, but this account has a second factor — proof
            # of it is required before a session is minted. Not itself an
            # audit event: this is neither a completed login nor a failure —
            # the eventual auth.login (success) or auth.mfa.challenge_failed
            # (failure) on /token/mfa/ covers both outcomes. See spec
            # 2026-09-two-factor-authentication.md §5.1.
            return Response({
                "mfa_required": True,
                "mfa_token": mfa.issue_challenge(user),
                "methods": ["totp"],
            })

        response = Response({"detail": "Login successful."})
        set_auth_cookies(
            request, response,
            access=serializer.validated_data["access"],
            refresh=serializer.validated_data["refresh"],
        )
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="auth.login",
            target_type="accounts.User",
            target=user,
            target_id=str(user.pk),
            target_display=user.email or user.username,
            summary=f"Password login succeeded for {user.email or user.username}.",
            user=user,
            metadata={"method": "password"},
        )
        return response

    def _record_login_failed(self, request):
        # Wrong password, unknown user, and inactive user all surface as the
        # same generic failure to the caller (see CustomTokenObtainPairSerializer's
        # own "no_active_account" fallback) so an attacker cannot distinguish
        # them — but internally the audit trail keeps the attempted identifier
        # for anyone reviewing a credential-stuffing pattern.
        identifier = str((request.data or {}).get("email") or (request.data or {}).get("username") or "").strip()
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="auth.login_failed",
            target_type="accounts.User",
            target_display=identifier,
            summary=f"Password login failed for {identifier or '(no identifier supplied)'}.",
            status=AuditEventStatus.FAILED,
        )


class TokenMfaView(APIView):
    """Second step of a two-step login: exchanges a challenge token plus a
    TOTP or recovery code for a session.

    ``AllowAny`` like ``CustomTokenObtainPairView`` — the caller has proven a
    password moments ago, not a bearer credential this request carries.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthMfaThrottle]

    def post(self, request, *args, **kwargs):
        mfa_token = str(request.data.get("mfa_token") or "")
        code = str(request.data.get("code") or "")

        try:
            user = mfa.resolve_challenge(mfa_token)
        except mfa.MfaChallengeError as exc:
            self._record_challenge_failed(request, reason=exc.reason)
            return Response({"detail": "Invalid or expired code."}, status=status.HTTP_400_BAD_REQUEST)

        ok, method, reason = mfa.verify_mfa_code(user, code)
        if not ok:
            self._record_challenge_failed(request, reason=reason, user=user)
            return Response({"detail": "Invalid or expired code."}, status=status.HTTP_400_BAD_REQUEST)

        tokens = make_jwt_for_user(user)
        response = Response({"detail": "Login successful."})
        set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])

        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="auth.login",
            target_type="accounts.User",
            target=user,
            target_id=str(user.pk),
            target_display=user.email or user.username,
            summary=f"Password login succeeded for {user.email or user.username}.",
            user=user,
            metadata={"method": "password+totp" if method == "totp" else "recovery_code"},
        )
        if method == "recovery_code":
            remaining = user.mfa_recovery_codes.filter(used_at__isnull=True).count()
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.AUTH,
                action_type="auth.mfa.recovery_used",
                target_type="accounts.User",
                target=user,
                target_id=str(user.pk),
                target_display=user.email or user.username,
                summary=f"Recovery code used to sign in as {user.email or user.username}.",
                user=user,
                metadata={"remaining": remaining},
            )
        return response

    def _record_challenge_failed(self, request, *, reason, user=None):
        # Same undifferentiated-to-the-caller philosophy as
        # CustomTokenObtainPairView._record_login_failed: the response never
        # says which part was wrong, only the audit reason does.
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="auth.mfa.challenge_failed",
            target_type="accounts.User",
            target=user,
            target_id=str(user.pk) if user else "",
            target_display=(user.email or user.username) if user else "",
            summary="MFA challenge failed" + (f" for {user.email or user.username}" if user else "") + ".",
            status=AuditEventStatus.FAILED,
            metadata={"reason": reason},
        )


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
    # Trailing "id": an .order_by() replaces Meta.ordering outright, so the
    # model-level tiebreaker does not reach this paginated list. Without it two
    # rates sharing valid_from and created_at can straddle a page boundary and
    # come back twice, or not at all.
    queryset = VatRate.objects.all().order_by("-valid_from", "-created_at", "id")
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


def _serialize_me(user):
    """Serialize the current user, adding the participant's community name.

    Participants have no managed-ZEV selection, so their community comes from
    their membership here (``zev.services.own_participant_for_user``, shared
    with the statement downloads).
    """
    data = UserSerializer(user).data
    if user.role == UserRole.PARTICIPANT:
        from zev.services import own_participant_for_user

        participant = own_participant_for_user(user)
        if participant is not None:
            data["zev_name"] = participant.zev.name
        data["zev_count"] = user.participations.count()
    return data


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me(request):
    """Current user: retrieve or partial-update own profile.

    When a token carries an ``impersonated_by`` claim the response also
    includes a nested ``impersonated_by`` object so the frontend can render
    the impersonation banner without reading any token from storage.
    """
    if request.method == "GET":
        data = _serialize_me(request.user)
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
    return Response(_serialize_me(serializer.instance))


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

    settings_fields = [
        "date_format_short",
        "date_format_long",
        "date_time_format",
        "mfa_required_roles",
        "mfa_grace_period_days",
    ]
    before = {field: getattr(settings_instance, field) for field in settings_fields}
    serializer = AppSettingsSerializer(settings_instance, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    updated = serializer.save()
    after = {field: getattr(updated, field) for field in settings_fields}
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.GOVERNANCE,
        action_type="app_settings.update",
        target_type="accounts.AppSettings",
        target=updated,
        target_id="singleton",
        target_display="AppSettings",
        summary="Updated application settings.",
        changes=build_diff(before, after, settings_fields),
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

    # Verification itself is final regardless of what happens next — only
    # whether it also delivers a session depends on the account's MFA state.
    # In practice an account reaching this line cannot yet have a factor (it
    # was inactive until the lines above), but the code must not assume
    # that — see spec 2026-09-two-factor-authentication.md §5.4 door 2.
    if mfa.has_active_factor(user):
        return Response({
            "mfa_required": True,
            "mfa_token": mfa.issue_challenge(user),
            "methods": ["totp"],
        })

    tokens = make_jwt_for_user(user)
    response = Response({"detail": "Email verified."})
    set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_initial_password(request):
    """Set a password for a freshly verified account that has no usable password yet.

    Spec 2026-09-two-factor-authentication.md's door table lists this as
    door 3, "unaffected — same as email verification". It genuinely needs no
    MFA check, but for a different reason than that entry implies: unlike
    ``verify_email``, this is ``IsAuthenticated`` — the caller already holds
    a valid session (minted by ``verify_email`` or a magic/onboarding link
    moments earlier). There is no unauthenticated session-minting moment
    here to challenge; this only refreshes an already-authenticated
    session's JWT claims after the password write.
    """
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


# ── Two-factor authentication (TOTP) ───────────────────────────────────────────
# Spec: docs/specs/2026-09-two-factor-authentication.md §5.2. Passkey
# registration and sign-in live in views_passkeys.py.


class MfaStatusView(APIView):
    """GET /me/mfa/ — the current user's second-factor status."""

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        device = getattr(user, "totp_device", None)
        passkeys = user.webauthn_credentials.all()
        protected = mfa.has_any_factor(user)
        deadline = mfa.grace_deadline(user)
        return Response({
            "totp": TotpDeviceSerializer(device).data if device is not None else None,
            "passkeys": WebAuthnCredentialSerializer(passkeys, many=True).data,
            "recovery_codes_remaining": (
                user.mfa_recovery_codes.filter(used_at__isnull=True).count() if protected else 0
            ),
            # Whether the policy names this user's role. The frontend's
            # enrolment gate acts on ``required`` with no factor registered.
            "required": deadline is not None,
            # An ISO datetime rather than a bare date: the deadline is a
            # moment, and the gate compares it with now. Null once enrolled —
            # there is nothing left to enforce.
            "grace_until": deadline.isoformat() if deadline is not None and not protected else None,
        })


class TotpDeviceView(APIView):
    """POST begins enrolment (or replaces an abandoned attempt); DELETE
    removes an active device. No GET here — MfaStatusView is the one place a
    client reads current state from."""

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        existing = getattr(request.user, "totp_device", None)
        if existing is not None:
            if existing.is_active:
                return Response(
                    {"detail": "Two-factor authentication is already enabled. Remove it before setting up a new device."},
                    status=status.HTTP_409_CONFLICT,
                )
            # An abandoned enrolment attempt (closed the tab before
            # confirming) must not accumulate rows or block starting over.
            existing.delete()

        secret = pyotp.random_base32()
        device = TotpDevice(user=request.user)
        try:
            device.set_secret(secret)
        except mfa_crypto.MfaNotConfigured:
            return Response(
                {"detail": "Two-factor authentication is not available on this instance: MFA_ENCRYPTION_KEYS is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        device.save()

        provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
            name=request.user.email or request.user.username, issuer_name="OpenZEV"
        )
        return Response({
            "provisioning_uri": provisioning_uri,
            "secret": secret,
            "qr_svg": mfa.totp_qr_svg(provisioning_uri),
        })

    def delete(self, request, *args, **kwargs):
        device = getattr(request.user, "totp_device", None)
        if device is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Refused when the policy requires a factor from this user and this
        # is the last one — a passkey elsewhere on the account still counts.
        if mfa.removal_blocked(request.user, leaving=mfa.factor_count(request.user) - int(device.is_active)):
            return Response(
                {"detail": "Two-factor authentication is required for your role; add a passkey before removing this one."},
                status=status.HTTP_409_CONFLICT,
            )

        device.delete()
        mfa.drop_recovery_codes_if_unprotected(request.user)

        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="auth.mfa.removed",
            target_type="accounts.User",
            target=request.user,
            target_id=str(request.user.pk),
            target_display=request.user.email or request.user.username,
            summary=f"Removed two-factor authentication for {request.user.email or request.user.username}.",
            user=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class TotpEnrolConfirmView(APIView):
    """POST /me/mfa/totp/confirm/ — activates a pending device and issues
    recovery codes, returned once."""

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        device = getattr(request.user, "totp_device", None)
        if device is None or device.is_active:
            return Response({"detail": "No pending two-factor setup to confirm."}, status=status.HTTP_400_BAD_REQUEST)

        code = str(request.data.get("code") or "").strip()
        ok, _reason = device.check_code(code)
        if not ok:
            return Response({"detail": "Invalid code."}, status=status.HTTP_400_BAD_REQUEST)

        # Recovery codes belong to the account, not to one factor: if a
        # passkey already earned this user a set, confirming TOTP must not
        # kill the printout they are holding. Only a first factor issues.
        first_factor = not mfa.has_any_factor(request.user)
        device.confirmed_at = timezone.now()
        device.save(update_fields=["confirmed_at"])
        recovery_codes = mfa.issue_recovery_codes(request.user) if first_factor else []

        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="auth.mfa.enrolled",
            target_type="accounts.User",
            target=request.user,
            target_id=str(request.user.pk),
            target_display=request.user.email or request.user.username,
            summary=f"Enabled two-factor authentication for {request.user.email or request.user.username}.",
            user=request.user,
            metadata={"method": "totp"},
        )
        return Response({"recovery_codes": recovery_codes})


class MfaRecoveryCodesView(APIView):
    """POST /me/mfa/recovery-codes/ — regenerates all ten, returned once.
    Invalidates any codes issued at confirmation or a previous regeneration."""

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        if not mfa.has_any_factor(request.user):
            return Response({"detail": "Two-factor authentication is not enabled."}, status=status.HTTP_400_BAD_REQUEST)

        recovery_codes = mfa.issue_recovery_codes(request.user)

        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="auth.mfa.recovery_regenerated",
            target_type="accounts.User",
            target=request.user,
            target_id=str(request.user.pk),
            target_display=request.user.email or request.user.username,
            summary=f"Regenerated recovery codes for {request.user.email or request.user.username}.",
            user=request.user,
        )
        return Response({"recovery_codes": recovery_codes})


class AdminMfaResetView(APIView):
    """DELETE /users/<pk>/mfa/ — an admin removes *all* of a user's second
    factors and recovery codes (D3: the way out for someone locked out).

    A removal, never a creation: an admin cannot enrol a factor on someone
    else's behalf and cannot read any secret, mirroring the API-key rule that
    an admin may revoke but not mint for another user. Audited with the admin
    as actor and the affected user as target.
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def delete(self, request, pk, *args, **kwargs):
        target = User.objects.filter(pk=pk).first()
        if target is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            totp_removed = TotpDevice.objects.filter(user=target).delete()[0]
            passkeys_removed = target.webauthn_credentials.all().delete()[0]
            codes_removed = MfaRecoveryCode.objects.filter(user=target).delete()[0]

        removed = {"totp": totp_removed, "passkeys": passkeys_removed, "recovery_codes": codes_removed}
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="auth.mfa.reset",
            target_type="accounts.User",
            target=target,
            target_id=str(target.pk),
            target_display=target.email or target.username,
            summary=f"Reset two-factor authentication for {target.email or target.username}.",
            user=request.user,
            metadata={"removed": removed},
        )
        return Response({"removed": removed})


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
        # Trailing "id" for the same reason as VatRateListCreateView: this
        # .order_by() replaces Meta.ordering, and created_at alone is not
        # unique, so a paginated walk could drop or duplicate a key.
        queryset = ApiKey.objects.select_related("user").order_by("-created_at", "id")

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
