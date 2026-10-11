from rest_framework import generics, serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.views import APIView
import hashlib
import logging
import secrets
import pyotp
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from redis.exceptions import RedisError
from django.db.models import Prefetch, Q
from django.utils.text import slugify
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage
from django.utils import timezone
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from . import mfa, mfa_crypto, notifications
from config.safe_format import render_with_fallback
from config.cache import delete_if_value
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
    AdminUserSerializer, SelfUserSerializer, UserSerializer, UserCreateSerializer, ChangePasswordSerializer, CustomTokenObtainPairSerializer,
    ApiKeySerializer, ApiKeyCreateSerializer, AdminApiKeySerializer,
    AppSettingsSerializer,
    PublicAppSettingsSerializer,
    FeatureFlagSerializer,
    TotpDeviceSerializer,
    VatRateSerializer,
    WebAuthnCredentialSerializer,
)
from .authentication import enforce_csrf
from .jwt_utils import make_jwt_for_user, record_login
from .session_revocation import (
    is_session_current,
    keep_current_session,
    lock_current_session,
    revoke_sessions,
    validate_refresh_token,
)
from .cookies import (
    ACCESS_COOKIE,
    ADMIN_ACCESS_COOKIE,
    ADMIN_REFRESH_COOKIE,
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)
from .permissions import IsAdmin
from .throttling import AuthLoginThrottle, AuthMfaThrottle, AuthRefreshThrottle, AuthRegisterThrottle, AuthVerifyThrottle, RegistrationUnavailable
from audit.models import AuditActionCategory, AuditEventStatus
from audit.mixins import AuditedUpdateMixin
from audit.services import build_diff, record_audit_event
from zev import access as zev_access
from zev import onboarding as zev_onboarding
from zev.models import Participant
from invoices.email_context import build_verification_email_context

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
        if mfa.requires_challenge(user):
            # Password verified, but this account has a second factor — proof
            # of it is required before a session is minted. Not itself an
            # audit event: this is neither a completed login nor a failure —
            # the eventual auth.login (success) or auth.mfa.challenge_failed
            # (failure) on /token/mfa/ covers both outcomes. See spec
            # 2026-09-two-factor-authentication.md §5.1.
            return Response({
                "mfa_required": True,
                "mfa_token": mfa.issue_challenge(user),
                "methods": mfa.challenge_methods(user),
            })

        response = Response({"detail": "Login successful."})
        set_auth_cookies(
            request, response,
            access=serializer.validated_data["access"],
            refresh=serializer.validated_data["refresh"],
        )
        record_login(user)
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
        record_login(user)

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
            validate_refresh_token(refresh_token)
            serializer.is_valid(raise_exception=True)
        except (TokenError, ValidationError, AuthenticationFailed, User.DoesNotExist):
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
    """Clear auth cookies and sign the account out everywhere.

    Unauthenticated so expired access still clears cookies; the user is
    resolved from the refresh cookie first, then access. During impersonation
    the main cookies hold the impersonated user's tokens, so they are
    revoked — never the admin in the backup cookies.
    """
    enforce_csrf(request)
    user = _user_for_logout(request)
    if user is not None:
        revoke_sessions(user)
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.AUTH,
            action_type="auth.logout",
            target_type="accounts.User",
            target=user,
            target_id=str(user.pk),
            target_display=user.email or user.username,
            summary=f"Logged out {user.email or user.username} everywhere.",
            user=user,
            metadata={"scope": "all"},
        )
    response = Response({"detail": "Logged out."})
    clear_auth_cookies(response)
    # Also clear any active impersonation cookies
    clear_auth_cookies(response, access_cookie=ADMIN_ACCESS_COOKIE, refresh_cookie=ADMIN_REFRESH_COOKIE)
    return response


def _user_for_logout(request):
    """The user behind a currently valid cookie token, if any.

    Refresh first, then access. Stale tokens resolve to ``None``: logout
    still clears cookies, it just revokes nothing.
    """
    for raw, token_cls in (
        (request.COOKIES.get(REFRESH_COOKIE), RefreshToken),
        (request.COOKIES.get(ACCESS_COOKIE), AccessToken),
    ):
        if not raw:
            continue
        try:
            token = token_cls(raw)
            user_id = token[jwt_settings.USER_ID_CLAIM]
        except (TokenError, KeyError):
            continue
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is not None and is_session_current(token, user):
            return user
    return None


class UserListCreateView(generics.ListCreateAPIView):
    """Admin: list and create users."""
    permission_classes = [IsAdmin]

    def get_queryset(self):
        # Everything AdminUserSerializer reads is prefetched, so the list costs
        # the same handful of queries for ten accounts or ten thousand.
        return (
            User.objects.all()
            .select_related("totp_device")
            .prefetch_related(
                zev_access.active_grants_prefetch(),
                Prefetch(
                    "participations",
                    queryset=Participant.objects.select_related(None).select_related("zev")
                    .only("id", "user_id", "zev_id", "valid_from", "valid_to", "zev__name", "zev__disabled_at", "zev__billing_interval")
                    .order_by("valid_from", "id"),
                ),
                "webauthn_credentials",
            )
            .order_by("username")
        )

    def get_serializer_class(self):
        return UserCreateSerializer if self.request.method == "POST" else AdminUserSerializer

    def create(self, request, *args, **kwargs):
        # Not the default CreateModelMixin.create(): the response also needs
        # generated_password, which lives on the serializer instance
        # (UserCreateSerializer.validate), not in its declared output fields.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        data = dict(serializer.data)
        if getattr(serializer, "generated_password", None):
            data["generated_password"] = serializer.generated_password
        headers = self.get_success_headers(serializer.data)
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)

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

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.method in ("PUT", "PATCH"):
            return queryset.select_for_update()
        return queryset

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        was_active = serializer.instance.is_active
        super().perform_update(serializer)
        # Deactivation also ends the sessions: otherwise reactivating the account
        # later would bring back whatever tokens were still unexpired.
        if was_active and not serializer.instance.is_active:
            revoke_sessions(serializer.instance)
        # An explicit cancellation also invalidates a still-inactive signup.
        if serializer.validated_data.get("is_active") is False:
            serializer.instance.email_verification_tokens.filter(consumed_at__isnull=True).delete()

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
        try:
            # Its manager grants and its party's login go with the account; a
            # ZEV it alone manages would be left without a manager.
            with zev_access.keeping_a_manager(*zev_access.managed_zev_ids(instance)):
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
        except zev_access.NoManagerLeft:
            record_audit_event(
                request=self.request,
                action_category=AuditActionCategory.AUTH,
                action_type="user.delete",
                target_type="accounts.User",
                target_id=user_id,
                target_display=user_display,
                summary=f"Denied deletion of {user_display}, the last manager of a ZEV.",
                status=AuditEventStatus.DENIED,
            )
            raise PermissionDenied(zev_access.NO_MANAGER_LEFT)


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
    """Serialize the current user with what the shell needs: every community
    it relates to (``memberships``) and whether it may set up a ZEV."""
    data = UserSerializer(user).data
    # Whether this account can re-authenticate with a password, which is what
    # the email-change form needs. Participants and OAuth-only accounts cannot.
    data["has_usable_password"] = user.has_usable_password()
    # Every ZEV the account relates to, with its grant and participant rows
    # there — what the frontend's community switcher lists (#761).
    data["memberships"] = zev_access.memberships_for(user)
    data["may_create_zev"] = user.may_create_zev
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
    # Self-service edits only what the person owns: their name and default
    # community. Everything else in the payload — email, username, role,
    # must_change_password, is_active — is read-only here and ignored. The email
    # has its own verified flow (views_security.EmailChangeRequestView).
    serializer = SelfUserSerializer(request.user, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(_serialize_me(serializer.instance))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    with transaction.atomic():
        request.user = lock_current_session(request)
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Password changes retire other sessions; this authenticated caller keeps theirs.
        revoke_sessions(request.user)
        links_revoked = zev_onboarding.revoke_active_for_user(request.user)
        response = Response({"detail": "Password updated successfully."})
        keep_current_session(request, response, request.user)
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.AUTH,
        action_type="password.change",
        target_type="accounts.User",
        target=request.user,
        target_id=str(request.user.pk),
        target_display=request.user.email or request.user.username,
        summary="Changed account password.",
        metadata={"onboarding_links_revoked": links_revoked},
    )
    notifications.notify(request.user, "password_changed", request=request)
    return response


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def app_settings(request):
    """Everyone reads the date formats; only admins read or write the MFA policy."""
    settings_instance = AppSettings.load()

    if request.method == "GET":
        serializer_class = AppSettingsSerializer if request.user.is_admin else PublicAppSettingsSerializer
        return Response(serializer_class(settings_instance).data)

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
        "mfa_required",
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
    tracked = ["enabled", "follows_default"]
    before = {"enabled": flag.effective_enabled, "follows_default": flag.follows_default}
    # A chosen value ends "follow the default": from here on an explicit off is an off.
    updated = serializer.save(follows_default=False) if "enabled" in serializer.validated_data else serializer.save()
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.GOVERNANCE,
        action_type="feature_flag.update",
        target_type="accounts.FeatureFlag",
        target=updated,
        target_id=str(updated.pk),
        target_display=updated.name,
        summary=f"Updated feature flag {updated.name}.",
        changes=build_diff(
            before, {"enabled": updated.effective_enabled, "follows_default": updated.follows_default}, tracked,
        ),
    )
    return Response(serializer.data)


REGISTER_RESPONSE_DETAIL = "If that address can be used, check your inbox."
# Per-address mail cooldown, independent of caller IP.
REGISTER_MAIL_INTERVAL_SECONDS = 15 * 60


def _reserve_mail_slot(key: str) -> str | None:
    """Return a reservation nonce, or None if reserved."""
    nonce = secrets.token_hex(8)
    return nonce if cache.add(key, nonce, REGISTER_MAIL_INTERVAL_SECONDS) else None


def _release_mail_slot(key: str, nonce: str) -> None:
    """Release only the matching reservation."""
    try:
        delete_if_value(key, nonce)
    except (RedisError, OSError):
        logger.exception("Could not release a registration mail reservation")


def _send_verification_email(user, token) -> None:
    from invoices.models import EmailTemplate, EMAIL_TEMPLATE_DEFAULTS

    defaults = EMAIL_TEMPLATE_DEFAULTS["email_verification"]
    override = EmailTemplate.objects.filter(template_key="email_verification").first()
    verify_url = f"{settings.FRONTEND_URL.rstrip('/')}/verify-email?token={token.token}"
    context = build_verification_email_context(verify_url=verify_url)

    def render(field):
        return render_with_fallback(
            getattr(override, field) if override else defaults[field],
            defaults[field],
            context,
            on_error=lambda exc: logger.warning("Invalid email template; using default: %s", exc),
        )

    EmailMessage(
        subject=render("subject"),
        body=render("body"),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    ).send(fail_silently=False)


def _is_pending_self_registration(user) -> bool:
    """Pending signup: inactive, no password, signup history only. Call under the user lock."""
    tokens = user.email_verification_tokens
    Purpose = EmailVerificationToken.Purpose
    return (
        not user.is_active
        and not user.has_usable_password()
        and tokens.filter(purpose=Purpose.SIGNUP).exists()
        and not tokens.filter(Q(purpose=Purpose.INVITATION) | Q(consumed_at__isnull=False)).exists()
    )


def _create_pending_user(email: str):
    """Create the inactive account; retries a username taken by a concurrent registration."""
    local = slugify(email.split("@", 1)[0]).replace("-", ".") if "@" in email else ""
    base = local or "owner"
    for _ in range(3):
        username, suffix = base, 1
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f"{base}{suffix}"
        try:
            with transaction.atomic():
                return User.objects.create_user(
                    username=username,
                    email=email,
                    role=UserRole.USER,
                    may_create_zev=True,
                    is_active=False,
                    must_change_password=True,
                )
        except IntegrityError:
            if not User.objects.filter(username=username).exists():
                raise
    raise IntegrityError(f"Could not find a free username for a new registration ({base!r})")


def _prepare_signup_link(email: str):
    """Create a signup credential atomically, serialized with verification and cancellation."""
    with transaction.atomic():
        user = User.objects.select_for_update().filter(email__iexact=email).first()
        if user is None:
            user = _create_pending_user(email)
        elif not _is_pending_self_registration(user):
            return None
        previous_ids = list(user.email_verification_tokens.filter(
            purpose=EmailVerificationToken.Purpose.SIGNUP, consumed_at__isnull=True,
        ).values_list("pk", flat=True))
        token = EmailVerificationToken.objects.create(user=user, token=secrets.token_urlsafe(48))
    return user, token, previous_ids


def _retire_previous_signup_links(user, token, previous_ids) -> None:
    """Retire earlier links after delivery; preserve later issuances and completed transitions."""
    if not previous_ids:
        return
    with transaction.atomic():
        locked = User.objects.select_for_update().filter(pk=user.pk).first()
        if locked is None or locked.is_active:
            return
        if locked.email_verification_tokens.filter(pk=token.pk, consumed_at__isnull=True).exists():
            locked.email_verification_tokens.filter(pk__in=previous_ids, consumed_at__isnull=True).delete()


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthRegisterThrottle])
def register(request):
    """Create a pending account, or resend a pending signup link, with a uniform status and body."""
    if not FeatureFlag.is_enabled(FeatureFlag.ZEV_SELF_REGISTRATION_ENABLED):
        return Response(
            {"detail": "Self-registration is currently disabled."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if not isinstance(request.data, dict):
        return Response({"detail": "Expected an object."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        email = serializers.EmailField(
            max_length=User._meta.get_field("email").max_length,
        ).run_validation(request.data.get("email", ""))
    except serializers.ValidationError as exc:
        return Response({"email": exc.detail}, status=status.HTTP_400_BAD_REQUEST)

    response = Response({"detail": REGISTER_RESPONSE_DETAIL}, status=status.HTTP_201_CREATED)
    key = "register-mail:" + hashlib.sha256(email.lower().encode()).hexdigest()
    try:
        nonce = _reserve_mail_slot(key)
    except (RedisError, OSError):
        logger.exception("Could not reserve a registration mail slot")
        raise RegistrationUnavailable from None
    if nonce is None:
        return response

    try:
        prepared = _prepare_signup_link(email)
    except Exception:
        logger.exception("Could not issue a registration link")
        _release_mail_slot(key, nonce)
        return response
    if prepared is None:
        return response

    user, token, previous_ids = prepared
    try:
        # The token remains on failure so the signup can be retried immediately.
        _send_verification_email(user, token)
    except Exception:
        logger.exception("Could not send a registration link")
        _release_mail_slot(key, nonce)
        return response
    try:
        _retire_previous_signup_links(user, token, previous_ids)
    except Exception:
        # Delivery already happened: retain its cooldown even if cleanup fails.
        logger.exception("Registration link sent, but earlier links could not be retired")
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthVerifyThrottle])
def verify_email(request):
    """Consume a one-time verification token and return JWT tokens to auto-login the user.

    Serves both self-registration and ZEV-access invitations (#761); the
    response's ``purpose`` tells the frontend which, so an invitee is not
    walked into setting up a ZEV of their own.
    """
    if not isinstance(request.data, dict):
        return Response({"detail": "Expected an object."}, status=status.HTTP_400_BAD_REQUEST)
    token_value = request.data.get("token", "")
    if not isinstance(token_value, str):
        return Response({"detail": "Token must be a string."}, status=status.HTTP_400_BAD_REQUEST)
    token_value = token_value.strip()
    if not token_value:
        return Response({"detail": "Token is required."}, status=status.HTTP_400_BAD_REQUEST)
    if len(token_value) > EmailVerificationToken._meta.get_field("token").max_length:
        return Response({"detail": "Invalid or expired verification link."}, status=status.HTTP_400_BAD_REQUEST)

    user_id = EmailVerificationToken.objects.filter(token=token_value).values_list("user_id", flat=True).first()
    if user_id is None:
        return Response({"detail": "Invalid or expired verification link."}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        # Use the same user-first lock order as signup and cancellation.
        user = User.objects.select_for_update().filter(pk=user_id).first()
        token = EmailVerificationToken.objects.filter(token=token_value, user_id=user_id).first()
        if user is None or user.is_active or token is None or not token.is_valid():
            return Response(
                {"detail": "This verification link has expired or already been used."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        token.consumed_at = timezone.now()
        token.save(update_fields=["consumed_at"])
        user.email_verification_tokens.filter(consumed_at__isnull=True).delete()
        user.is_active = True
        update_fields = ["is_active"]
        if token.purpose == EmailVerificationToken.Purpose.INVITATION:
            user.independent_login_required = True
            update_fields.append("independent_login_required")
        user.save(update_fields=update_fields)

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
    if mfa.requires_challenge(user):
        return Response({
            "mfa_required": True,
            "mfa_token": mfa.issue_challenge(user),
            "methods": mfa.challenge_methods(user),
            "purpose": token.purpose,
        })

    tokens = make_jwt_for_user(user)
    response = Response({"detail": "Email verified.", "purpose": token.purpose})
    set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])
    record_login(user)
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
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

    user = lock_current_session(request)
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
    revoke_sessions(user)

    # The link's purpose is fulfilled once a password exists.
    links_revoked = zev_onboarding.revoke_active_for_user(user)

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
        metadata={"onboarding_links_revoked": links_revoked},
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
            # Whether the policy applies to this account; the enrolment gate
            # acts on it.
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

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        request.user = lock_current_session(request)
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

    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        request.user = lock_current_session(request)
        device = getattr(request.user, "totp_device", None)
        if device is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Refused when the policy requires a factor from this user and this
        # is the last one — a passkey elsewhere on the account still counts.
        if mfa.removal_blocked(request.user, leaving=mfa.factor_count(request.user) - int(device.is_active)):
            return Response(
                {"detail": "Two-factor authentication is required; add a passkey before removing this one."},
                status=status.HTTP_409_CONFLICT,
            )

        was_active = device.is_active
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
        # Discarding an enrolment that was never confirmed changes nothing about
        # how the account is secured, so it is not worth a notice.
        if was_active:
            notifications.notify(request.user, "totp_removed", request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TotpEnrolConfirmView(APIView):
    """POST /me/mfa/totp/confirm/ — activates a pending device and issues
    recovery codes, returned once."""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        request.user = lock_current_session(request)
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
        notifications.notify(request.user, "totp_enabled", request=request)
        return Response({"recovery_codes": recovery_codes})


class MfaRecoveryCodesView(APIView):
    """POST /me/mfa/recovery-codes/ — regenerates all ten, returned once.
    Invalidates any codes issued at confirmation or a previous regeneration."""

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        request.user = lock_current_session(request)
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
        notifications.notify(request.user, "recovery_codes_regenerated", request=request)
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

        # Whoever was inside the account may have been let in by the factors that
        # were just removed; end their sessions too.
        revoke_sessions(target)
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
        # Only when there was something to remove: resetting an account with no
        # factors changes nothing the person could act on.
        if any(removed.values()):
            notifications.notify(target, "mfa_reset_by_admin", request=request)
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

        with transaction.atomic():
            user = lock_current_session(request)
            api_key = ApiKey.objects.create(
                user=user,
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
