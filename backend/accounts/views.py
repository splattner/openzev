from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
import json
import logging
import secrets
import urllib.parse
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

logger = logging.getLogger(__name__)


class CustomTokenObtainPairView(TokenObtainPairView):
    """JWT login — includes role, email and full_name in the token."""
    serializer_class = CustomTokenObtainPairSerializer


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
            raise PermissionDenied("Only admins can create users.")
        return super().create(request, *args, **kwargs)


class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Admin: retrieve / update / delete a user."""
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]

    def perform_update(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        if instance.participations.exists():
            raise PermissionDenied("Linked participant accounts cannot be deleted.")
        instance.delete()


class VatRateListCreateView(generics.ListCreateAPIView):
    queryset = VatRate.objects.all().order_by("-valid_from", "-created_at")
    permission_classes = [IsAdmin]

    serializer_class = VatRateSerializer

    def perform_create(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", {"non_field_errors": exc.messages}))


class VatRateDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = VatRate.objects.all()
    permission_classes = [IsAdmin]
    serializer_class = VatRateSerializer

    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", {"non_field_errors": exc.messages}))


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me(request):
    """Current user: retrieve or partial-update own profile."""
    if request.method == "GET":
        return Response(UserSerializer(request.user).data)
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
    return Response({"detail": "Password updated successfully."})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def app_settings(request):
    settings_instance = AppSettings.load()

    if request.method == "GET":
        return Response(AppSettingsSerializer(settings_instance).data)

    if not request.user.is_admin:
        raise PermissionDenied("Only admins can update application settings.")

    serializer = AppSettingsSerializer(settings_instance, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
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
        raise PermissionDenied("Only admins can update feature flags.")

    try:
        flag = FeatureFlag.objects.get(pk=pk)
    except FeatureFlag.DoesNotExist:
        return Response({"detail": "Feature flag not found."}, status=status.HTTP_404_NOT_FOUND)

    serializer = FeatureFlagSerializer(flag, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def impersonate_participant(request, user_id: int):
    if not request.user.is_admin:
        raise PermissionDenied("Only admins can impersonate participants.")

    try:
        target_user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

    if target_user.role not in (UserRole.PARTICIPANT, UserRole.ZEV_OWNER):
        return Response({"detail": "Only participant or ZEV owner users can be impersonated."}, status=status.HTTP_400_BAD_REQUEST)

    refresh = RefreshToken.for_user(target_user)
    refresh["role"] = target_user.role
    refresh["email"] = target_user.email
    refresh["full_name"] = target_user.get_full_name()
    refresh["must_change_password"] = target_user.must_change_password
    refresh["impersonated_by"] = request.user.id

    return Response(
        {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "impersonated_user": UserSerializer(target_user).data,
            "impersonator": UserSerializer(request.user).data,
        },
        status=status.HTTP_200_OK,
    )


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

    refresh = RefreshToken.for_user(user)
    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_initial_password(request):
    """Set a password for a freshly verified account that has no usable password yet."""
    new_password = request.data.get("new_password", "")
    if not new_password:
        return Response({"detail": "new_password is required."}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    if not (user.must_change_password or not user.has_usable_password()):
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

    # Return fresh tokens so the frontend can stay logged in
    refresh = RefreshToken.for_user(user)
    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    })


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
        return HttpResponseRedirect(
            f"{frontend_url}/login?oauth_error={urllib.parse.quote(error)}"
        )

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

    try:
        exchange = OAuthExchangeCode.objects.select_related("user").get(code=code)
    except OAuthExchangeCode.DoesNotExist:
        return Response({"detail": "Invalid or expired code."}, status=status.HTTP_400_BAD_REQUEST)

    if not exchange.is_valid():
        exchange.delete()
        return Response({"detail": "Code has expired."}, status=status.HTTP_400_BAD_REQUEST)

    user = exchange.user
    exchange.delete()

    return Response(_make_jwt_for_user(user))


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
