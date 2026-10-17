"""OAuth 2.0 / OIDC: provider configuration, login, account linking, unlinking.

Split out of ``accounts.views`` because it is both the largest single concern in
that module and the one with its own threat model — it validates CSRF state,
talks to third-party HTTP endpoints, auto-provisions local accounts, and builds
redirects back to the frontend (see the CWE-601 note in ``oauth_callback``).
"""

import json
import logging
import re
import secrets
import urllib.error
import urllib.request
from urllib.parse import urlencode

from django.conf import settings
from django.core.validators import validate_email
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from config.net import check_public_host
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import build_diff, record_audit_event

from . import mfa
from .cookies import set_auth_cookies
from .jwt_utils import is_participant_link_session, make_jwt_for_user, record_login
from .session_revocation import lock_current_session
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
MAX_OAUTH_RESPONSE_BYTES = 1024 * 1024

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
    "require_mfa_claim",
    "trust_missing_email_verified",
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


def _claim_for_audit(value):
    """Keep the audit trail small: a provider can send any JSON in ``email_verified``."""
    return value if value is None or isinstance(value, bool) else str(value)[:32]


class _NoOAuthRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(newurl or req.full_url, code, msg, headers, fp)


def _open_oauth_json(req: urllib.request.Request) -> dict:
    """Validate the endpoint, refuse redirects, and read a bounded JSON object."""
    check_public_host(
        req.full_url,
        allowed_schemes={"https", "http"} if settings.DEBUG else {"https"},
        allow_private=settings.OAUTH_ALLOW_PRIVATE_HOSTS,
    )
    opener = urllib.request.build_opener(_NoOAuthRedirects)
    with opener.open(req, timeout=10) as resp:
        payload = resp.read(MAX_OAUTH_RESPONSE_BYTES + 1)
    if len(payload) > MAX_OAUTH_RESPONSE_BYTES:
        raise ValueError("OAuth response exceeds the size limit.")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("OAuth response must be a JSON object.")
    return data


def _exchange_code_for_tokens(provider: OAuthProvider, code: str, redirect_uri: str) -> dict:
    """Call the provider's token endpoint and return the parsed JSON response."""
    body = urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
    }).encode()
    return _open_oauth_json(urllib.request.Request(
        provider.token_url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    ))


def _fetch_user_info(provider: OAuthProvider, access_token: str) -> dict:
    """Fetch user profile from the provider's userinfo endpoint."""
    return _open_oauth_json(urllib.request.Request(
        provider.userinfo_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    ))


def _parse_user_info(data: dict) -> tuple[str, str, str, str]:
    """Validate the identity and profile fields used locally; retain raw extra_data."""
    uid = data.get("sub")
    if uid is None or uid == "":
        uid = data.get("id")
        if uid is not None and not isinstance(uid, str) and type(uid) is not int:
            raise ValueError("OAuth id must be a string or integer.")
    elif not isinstance(uid, str):
        raise ValueError("OAuth sub must be a string.")
    uid = "" if uid is None else str(uid)
    if len(uid) > SocialAccount._meta.get_field("uid").max_length or (uid and not uid.strip()):
        raise ValueError("Invalid OAuth identifier length.")

    profile = []
    for claim, field in (("email", "email"), ("given_name", "first_name"), ("family_name", "last_name")):
        value = data.get(claim)
        value = "" if value is None else value
        if not isinstance(value, str) or len(value) > User._meta.get_field(field).max_length:
            raise ValueError(f"Invalid OAuth {claim} type or length.")
        if claim == "email":
            value = value.strip().lower()
            if len(value) > User._meta.get_field(field).max_length:
                raise ValueError("Invalid OAuth email length.")
            if value:
                validate_email(value)
        profile.append(value)
    return uid, *profile


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
@transaction.atomic
def oauth_link_initiate(request, provider_slug: str):
    """Return the linking URL after locking and rechecking the requesting session."""
    provider = get_object_or_404(OAuthProvider, name=provider_slug, enabled=True)
    state_token = secrets.token_urlsafe(32)
    user = lock_current_session(request)
    OAuthState.objects.create(
        state=state_token, provider=provider, user=user,
        session_version=user.session_version,
        from_participant_link=is_participant_link_session(request.auth),
    )
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

def _provider_proves_account_email(user_info, account_email):
    email = user_info.get("email")
    return (
        isinstance(email, str) and bool(email.strip())
        and user_info.get("email_verified") is True
        and email.strip().casefold() == account_email.strip().casefold()
    )


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
    link_session_version = state_obj.session_version
    participant_link = state_obj.from_participant_link
    provider = state_obj.provider
    state_obj.delete()

    # Exchange authorisation code for tokens and fetch user profile
    redirect_uri = provider.redirect_url
    try:
        token_data = _exchange_code_for_tokens(provider, code, redirect_uri)
        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("OAuth access_token must be a nonempty string.")
        user_info = _fetch_user_info(provider, access_token)
        provider_uid, email, first_name, last_name = _parse_user_info(user_info)
    except Exception:
        logger.exception("OAuth token exchange failed for provider %s", provider_slug)
        _record_login_failure(request, provider_slug, "token_exchange_failed")
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=token_exchange_failed")

    if not provider_uid:
        _record_login_failure(request, provider_slug, "missing_uid")
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=missing_uid")

    if linking_user is not None or link_session_version is not None:
        with transaction.atomic():
            linking_user = User.objects.locked().filter(
                pk=linking_user.pk if linking_user else None, is_active=True,
            ).first()
            if linking_user is None:
                return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=account_inactive")
            if link_session_version is None or link_session_version != linking_user.session_version:
                _record_auth_event(
                    request, action_type="oauth.link_refused", user=linking_user,
                    summary="Refused OAuth linking: authorizing session revoked.",
                    event_status=AuditEventStatus.DENIED,
                    metadata={"provider": provider_slug, "reason": "session_revoked"},
                )
                return HttpResponseRedirect(f"{frontend_url}/account?oauth_error=session_revoked")
            # ── Link flow: attach to the (already authenticated) user ────────
            if participant_link and not _provider_proves_account_email(user_info, linking_user.email):
                _record_auth_event(
                    request, action_type="oauth.link_refused", user=linking_user,
                    summary="Refused participant-session OAuth linking: account email not verified.",
                    event_status=AuditEventStatus.DENIED,
                    metadata={"provider": provider_slug, "reason": "email_not_verified"},
                )
                return HttpResponseRedirect(f"{frontend_url}/account?oauth_error=email_not_verified")
            social, created = SocialAccount.objects.get_or_create(
                provider=provider,
                uid=provider_uid,
                defaults={"user": linking_user, "extra_data": user_info},
            )
            if social.user_id != linking_user.pk:
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
            if social.from_participant_link:
                social.from_participant_link = False
                social.save(update_fields=["from_participant_link"])
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
        if social.from_participant_link:
            with transaction.atomic():
                user = User.objects.locked().filter(pk=user.pk, is_active=True).first()
                if user is None:
                    return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=account_inactive")
                social = SocialAccount.objects.select_for_update().filter(pk=social.pk).first()
                if social is None:
                    _record_login_failure(request, provider_slug, "identity_removed")
                    return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=identity_removed")
                if not _provider_proves_account_email(user_info, user.email):
                    _record_login_failure(request, provider_slug, "email_not_verified")
                    return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=email_not_verified")
                social.from_participant_link = False
                social.save(update_fields=["from_participant_link"])
    except SocialAccount.DoesNotExist:
        provisioned = False
        if not email:
            _record_login_failure(request, provider_slug, "no_email")
            return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=no_email")

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            trusted_missing_claim = provider.trust_missing_email_verified and "email_verified" not in user_info
            if not trusted_missing_claim and user_info.get("email_verified") is not True:
                _record_auth_event(
                    request,
                    action_type="oauth.provision_refused",
                    summary="Refused to provision an OAuth account because the provider did not verify the email.",
                    event_status=AuditEventStatus.DENIED,
                    metadata={"provider": provider_slug, "reason": "email_not_verified", "email_verified": _claim_for_audit(user_info.get("email_verified"))},
                )
                return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=email_not_verified")
            # Verified or explicitly trusted new accounts land on the lowest role.
            username = _generate_username_from_email(email)
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=None,
                is_active=True,
                role=UserRole.USER,
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
                        "email_verified": _claim_for_audit(user_info.get("email_verified")),
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

    if provider.require_mfa_claim and not mfa.amr_satisfies_mfa(user_info.get("amr")):
        # Spec 2026-09-two-factor-authentication.md §5.4 (door 4): the IdP
        # owns authentication and this login is never challenged for a local
        # TOTP factor — but an admin can opt this provider into requiring the
        # IdP's own assertion that it verified a second factor.
        _record_auth_event(
            request,
            action_type="oauth.login_failed",
            summary=f"OAuth login refused for {user.email or user.username}: provider {provider_slug} did not assert a second factor.",
            event_status=AuditEventStatus.DENIED,
            user=user,
            metadata={"provider": provider_slug, "reason": "mfa_claim_missing"},
        )
        return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=mfa_claim_missing")

    # Issue a short-lived exchange code for the frontend to convert to JWT
    exchange_code = secrets.token_urlsafe(32)
    with transaction.atomic():
        current = User.objects.locked().filter(pk=user.pk, is_active=True).first()
        if current is None or current.session_version != user.session_version:
            return HttpResponseRedirect(f"{frontend_url}/login?oauth_error=account_inactive")
        OAuthExchangeCode.objects.create(code=exchange_code, user=current)
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

    invalid = Response({"detail": "Invalid or expired code."}, status=status.HTTP_400_BAD_REQUEST)
    owner = OAuthExchangeCode.objects.filter(code=code).values("user_id").first()
    if owner is None:
        return invalid

    # Match revocation's user-first lock order; consume and mint in one transaction.
    with transaction.atomic():
        user = User.objects.locked().filter(pk=owner["user_id"], is_active=True).first()
        if user is None:
            return invalid
        exchange = OAuthExchangeCode.objects.select_for_update().filter(code=code, user=user).first()
        if exchange is None:
            return invalid
        expired = not exchange.is_valid()
        exchange.delete()
        if expired:
            return Response({"detail": "Code has expired."}, status=status.HTTP_400_BAD_REQUEST)
        tokens = make_jwt_for_user(user)
        response = Response({"detail": "Login successful."})
        set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])
        record_login(user)
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
