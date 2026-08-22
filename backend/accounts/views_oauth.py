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
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import build_diff, record_audit_event

from .cookies import set_auth_cookies
from .jwt_utils import make_jwt_for_user as _make_jwt_for_user
from .throttling import AuthOAuthExchangeThrottle, AuthOAuthInitiateThrottle
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

#: Provider config fields worth diffing on update. ``client_secret`` is
#: deliberately absent — ``redact_metadata`` would strip it from the diff
#: anyway, so a rotation is reported as a boolean instead of a redacted key
#: that silently vanishes.
PROVIDER_TRACKED_FIELDS = (
    "name",
    "client_id",
    "authorization_url",
    "token_url",
    "userinfo_url",
    "redirect_url",
    "scope",
    "enabled",
)


def _provider_snapshot(provider: OAuthProvider) -> dict:
    return {field: getattr(provider, field) for field in PROVIDER_TRACKED_FIELDS}


def _record_auth_event(request, *, action_type, summary, event_status=AuditEventStatus.SUCCESS,
                       user=None, metadata=None):
    """Record an OAuth flow event.

    The callback is an unauthenticated view, so ``request.user`` is anonymous
    for most of these; the account the flow concerns is passed explicitly and
    becomes the target rather than the actor.
    """
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.AUTH,
        action_type=action_type,
        target_type="accounts.User",
        target=user,
        target_id=str(user.pk) if user else "",
        target_display=(user.email or user.username) if user else "",
        summary=summary,
        status=event_status,
        metadata=metadata,
    )


def _record_login_failure(request, provider_slug: str, reason: str) -> None:
    """Record a callback that could not be resolved to a session.

    Only failures that carry signal are recorded. A ``provider_error`` (the
    user declined consent at the provider) and ``missing_params`` (a bare GET
    at the callback URL, which any crawler produces) are normal traffic and
    would drown the AUTH trail; everything else here means a replayed or forged
    state, a misconfigured provider, or a provider returning an unusable
    profile.
    """
    _record_auth_event(
        request,
        action_type="oauth.login_failed",
        summary=f"OAuth login via {provider_slug} failed: {reason}.",
        event_status=AuditEventStatus.FAILED,
        metadata={"provider": provider_slug, "reason": reason},
    )


def _record_provider_event(request, *, action_type, provider, summary, changes=None, metadata=None):
    """Record a change to an identity provider's configuration.

    GOVERNANCE rather than AUTH, matching how the other admin-only
    configuration endpoints are audited: repointing ``token_url`` or rotating
    ``client_secret`` redirects authentication itself, so it belongs in the
    same trail as the other privileged config changes.
    """
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.GOVERNANCE,
        action_type=action_type,
        target_type="accounts.OAuthProvider",
        target=provider,
        target_id=str(provider.pk),
        target_display=provider.name,
        summary=summary,
        changes=changes,
        metadata=metadata,
    )


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

    def perform_create(self, serializer):
        provider = serializer.save()
        _record_provider_event(
            self.request,
            action_type="oauth_provider.create",
            provider=provider,
            summary=f"Created OAuth provider {provider.name}.",
            changes=build_diff({}, _provider_snapshot(provider), PROVIDER_TRACKED_FIELDS),
        )


class OAuthProviderDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Admin: retrieve, update or delete an OAuth provider configuration."""
    queryset = OAuthProvider.objects.all()
    serializer_class = OAuthProviderSerializer
    permission_classes = [IsAdmin]

    def perform_update(self, serializer):
        before = _provider_snapshot(self.get_object())
        old_secret = self.get_object().client_secret
        provider = serializer.save()
        _record_provider_event(
            self.request,
            action_type="oauth_provider.update",
            provider=provider,
            summary=f"Updated OAuth provider {provider.name}.",
            changes=build_diff(before, _provider_snapshot(provider), PROVIDER_TRACKED_FIELDS),
            metadata={"client_secret_rotated": provider.client_secret != old_secret},
        )

    def perform_destroy(self, instance):
        provider_id = str(instance.pk)
        name = instance.name
        linked_accounts = instance.social_accounts.count()
        instance.delete()
        record_audit_event(
            request=self.request,
            action_category=AuditActionCategory.GOVERNANCE,
            action_type="oauth_provider.delete",
            target_type="accounts.OAuthProvider",
            target_id=provider_id,
            target_display=name,
            summary=f"Deleted OAuth provider {name}.",
            metadata={"unlinked_social_accounts": linked_accounts},
        )


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
@throttle_classes([AuthOAuthInitiateThrottle])
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
        # No matching in-flight request: a replayed, forged or cross-provider
        # state. The clearest CSRF signal this flow produces.
        _record_login_failure(request, provider_slug, "invalid_state")
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=invalid_state")

    if not state_obj.is_valid():
        state_obj.delete()
        _record_login_failure(request, provider_slug, "state_expired")
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
        _record_login_failure(request, provider_slug, "token_exchange_failed")
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=token_exchange_failed")

    # Derive a stable identifier for the provider account
    provider_uid = str(user_info.get("sub") or user_info.get("id") or "")
    if not provider_uid:
        _record_login_failure(request, provider_slug, "missing_uid")
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=missing_uid")

    email = (user_info.get("email") or "").strip().lower()

    if linking_user is not None:
        # ── Link flow: attach to the (already authenticated) user ────────
        if SocialAccount.objects.filter(provider=provider, uid=provider_uid).exclude(user=linking_user).exists():
            # The provider account is already linked to a different user
            _record_auth_event(
                request,
                action_type="oauth.link_refused",
                summary=f"Refused to link an OAuth identity to {linking_user.email or linking_user.username}: already linked to another account.",
                event_status=AuditEventStatus.DENIED,
                user=linking_user,
                metadata={"provider": provider_slug, "reason": "already_linked_other"},
            )
            return HttpResponseRedirect(
                f"{frontend_url}/account?oauth_error=already_linked_other"
            )
        _social, created = SocialAccount.objects.get_or_create(
            provider=provider,
            uid=provider_uid,
            defaults={"user": linking_user, "extra_data": user_info},
        )
        if created:
            _record_auth_event(
                request,
                action_type="oauth.link",
                summary=f"Linked OAuth identity from {provider_slug} to {linking_user.email or linking_user.username}.",
                user=linking_user,
                metadata={"provider": provider_slug},
            )
        return HttpResponseRedirect(f"{frontend_url}/account?oauth_linked=true")

    # ── Login flow: find or create the local user ─────────────────────────
    try:
        social = SocialAccount.objects.select_related("user").get(
            provider=provider, uid=provider_uid
        )
        user = social.user
    except SocialAccount.DoesNotExist:
        provisioned = False
        if not email:
            _record_login_failure(request, provider_slug, "no_email")
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
            provisioned = True
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
                _record_auth_event(
                    request,
                    action_type="oauth.link_refused",
                    summary="Refused to link an OAuth identity to an existing account: email not verified by the provider.",
                    event_status=AuditEventStatus.DENIED,
                    user=user,
                    metadata={
                        "provider": provider_slug,
                        "reason": "email_not_verified",
                        "email_verified": user_info.get("email_verified"),
                    },
                )
                return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=email_not_verified")

        SocialAccount.objects.create(
            provider=provider,
            uid=provider_uid,
            user=user,
            extra_data=user_info,
        )
        if provisioned:
            _record_auth_event(
                request,
                action_type="oauth.provision",
                summary=f"Provisioned a new account for {user.email} from {provider_slug}.",
                user=user,
                metadata={"provider": provider_slug, "role": user.role},
            )
        else:
            _record_auth_event(
                request,
                action_type="oauth.link",
                summary=f"Linked OAuth identity from {provider_slug} to existing account {user.email or user.username}.",
                user=user,
                metadata={"provider": provider_slug, "matched_by": "verified_email"},
            )

    if not user.is_active:
        # Valid provider credentials presented for a disabled account.
        _record_auth_event(
            request,
            action_type="oauth.login_failed",
            summary=f"OAuth login refused for {user.email or user.username}: account is inactive.",
            event_status=AuditEventStatus.DENIED,
            user=user,
            metadata={"provider": provider_slug, "reason": "account_inactive"},
        )
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=account_inactive")

    # Issue a short-lived exchange code for the frontend to convert to JWT
    exchange_code = secrets.token_urlsafe(32)
    OAuthExchangeCode.objects.create(code=exchange_code, user=user)
    _record_auth_event(
        request,
        action_type="oauth.login",
        summary=f"OAuth login succeeded for {user.email or user.username} via {provider_slug}.",
        user=user,
        metadata={"provider": provider_slug},
    )
    return HttpResponseRedirect(f"{frontend_url}/oauth/callback?code={exchange_code}")


# ── token exchange ────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthOAuthExchangeThrottle])
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
    set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])
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
    provider_name = account.provider.name
    account.delete()
    _record_auth_event(
        request,
        action_type="oauth.unlink",
        summary=f"Unlinked OAuth identity from {provider_name} for {request.user.email or request.user.username}.",
        user=request.user,
        metadata={"provider": provider_name},
    )
    return Response(status=status.HTTP_204_NO_CONTENT)
