"""OAuth 2.0 / OIDC: provider configuration, login, account linking, unlinking.

Split out of ``accounts.views`` because it is both the largest single concern in
that module and the one with its own threat model — it validates CSRF state,
talks to third-party HTTP endpoints, auto-provisions local accounts, and builds
redirects back to the frontend (see the CWE-601 note in ``oauth_callback``).

The permission classes here were already declarative, so this is a move rather
than a rewrite: no handler logic changed.
"""

import json
import logging
import re
import secrets
import urllib.request
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import record_audit_event

from .cookies import set_auth_cookies
from .models import (
    OAuthExchangeCode,
    OAuthProvider,
    OAuthState,
    SocialAccount,
    User,
    UserRole,
)
from .permissions import IsAdmin
from .serializers import (
    OAuthProviderPublicSerializer,
    OAuthProviderSerializer,
    SocialAccountSerializer,
)

logger = logging.getLogger(__name__)


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
        if not email:
            return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=no_email")

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Auto-provision a new account for this OAuth identity. This grants
            # nothing that did not already exist, and lands on the lowest role.
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
            # A provider identity we have never seen is claiming an account
            # that already exists — and inheriting it means inheriting its
            # role. Only proceed if the provider vouches for the address;
            # otherwise anyone able to register that email at a configured
            # provider could take the account over.
            if user_info.get("email_verified") is not True:
                logger.warning(
                    "Refused OAuth account takeover: provider %s asserted unverified email for an existing user",
                    provider_slug,
                )
                record_audit_event(
                    action_category=AuditActionCategory.AUTH,
                    action_type="oauth.link_refused",
                    target_type="accounts.User",
                    target=user,
                    target_id=str(user.pk),
                    target_display=user.email or user.username,
                    summary="Refused to link an OAuth identity to an existing account: email not verified by the provider.",
                    status=AuditEventStatus.DENIED,
                    metadata={"provider": provider_slug, "email_verified": user_info.get("email_verified")},
                )
                return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=email_not_verified")

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
    set_auth_cookies(response, access=tokens["access"], refresh=tokens["refresh"])
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
