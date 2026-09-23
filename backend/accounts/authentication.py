from django.conf import settings
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, SessionAuthentication, get_authorization_header
from rest_framework.permissions import SAFE_METHODS
from rest_framework_simplejwt.authentication import JWTAuthentication

from .api_keys import split_key, verify_secret
from .jwt_utils import IMPERSONATOR_CLAIM
from .session_revocation import is_session_current

ACCESS_COOKIE = "openzev_access"


def enforce_csrf(request) -> None:
    SessionAuthentication().enforce_csrf(request)


class CookieJWTAuthentication(JWTAuthentication):
    """JWT authentication that prefers the Authorization header and falls back to the httpOnly cookie."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        # A token issued before the account was last signed out everywhere.
        # Tokens minted before the claim existed carry none, which reads as 0 —
        # the value every account starts at, so they stay valid until the first
        # revocation and never after it.
        if not is_session_current(validated_token, user):
            raise exceptions.AuthenticationFailed("This session has been signed out.", code="session_revoked")
        return user

    def authenticate(self, request):
        # Prefer the Authorization header (API clients / backward-compat)
        header = self.get_header(request)
        if header:
            # Leave ``Api-Key`` credentials to ApiKeyAuthentication rather than
            # failing the request with "token not valid".
            parts = header.split()
            if parts and parts[0].lower() == b"api-key":
                return None
            result = super().authenticate(request)
        else:
            # Fall back to the httpOnly cookie set by the login endpoint
            raw_token = request.COOKIES.get(ACCESS_COOKIE)
            if raw_token is None:
                return None

            # A cookie the browser sends on its own is not a credential the
            # caller chose to present. Expired, signed-out or otherwise stale,
            # it must read as "no credentials" — raising here would turn the
            # public login-page endpoints (AllowAny) into 401s for anyone
            # holding a dead cookie, and the client cannot refresh its way out
            # once the refresh cookie is gone too. Protected views still answer
            # 401 (NotAuthenticated), so the refresh flow is unchanged.
            try:
                validated_token = self.get_validated_token(raw_token)
                user = self.get_user(validated_token)
            except exceptions.AuthenticationFailed:
                return None

            if request.method not in SAFE_METHODS:
                enforce_csrf(request)

            result = (user, validated_token)

        if result is not None:
            enforce_mfa_enrolment(request, *result)
        return result


# ── MFA policy enforcement ────────────────────────────────────────────────────
#
# ``AppSettings.mfa_required_roles`` (spec 2026-09-two-factor-authentication.md
# §7.3) is otherwise a UI-only nag: ``MfaEnrolmentGate`` withholds the app shell
# in the browser once an account's grace period ends, but nothing stops a
# script from carrying on regardless, past its own grace period, forever. This
# closes that gap for interactive (cookie or bearer JWT) sessions, without
# reaching API keys — see the docstring on ``enforce_mfa_enrolment`` for why.
#
# Deliberately narrow in a second way too: only *unsafe* methods are refused.
# Reading data was never gated by having a second factor, only by being signed
# in at all, and this feature does not change that — it only forecloses acting
# further until the account is protected the way its role requires.
#
# URL name -> methods exempt even while overdue, or ``None`` for all methods.
# Two kinds of entry: the enrolment ceremony itself (a script cannot complete
# it, but the person reaching it through the browser must be able to), and
# self-protective actions with no capability to grant (revoking a key,
# changing your own password, signing yourself out). Deliberately absent:
# ``api-key-list-create`` (minting a *fresh* key would otherwise be the
# obvious way around this — API keys themselves are exempt from this check
# entirely, so a new one would work for everything else), ``app-settings``
# (an overdue admin must not be able to edit the very policy blocking them —
# enrolling is the only way out, by design), and every admin action that
# targets *another* account (``admin-mfa-reset``, ``admin-sessions-revoke``,
# ``impersonate-participant``, ``user-detail``, ...): those are not this
# account protecting itself, and the calling admin being out of policy is
# reason enough to refuse them.
MFA_ENROLMENT_EXEMPT_URL_NAMES: dict[str, frozenset[str] | None] = {
    # Refreshing a still-live session must never depend on the very policy
    # that session might be blocked by.
    "token_refresh": None,
    "token-mfa": None,
    # Self-service profile — email/role/must_change_password/is_active are
    # already read-only here (SelfUserSerializer); nothing left to abuse.
    "me": None,
    "change-password": None,
    "set-initial-password": None,
    "email-change-request": None,
    "email-change-confirm": None,
    "sessions-revoke-own": None,
    # The enrolment ceremony itself.
    "mfa-totp-device": None,
    "mfa-totp-confirm": None,
    "mfa-recovery-codes": None,
    "passkey-register-begin": None,
    "passkey-register-complete": None,
    "passkey-detail": None,
    "passkey-authenticate-begin": None,
    "passkey-authenticate-complete": None,
    "oauth-link-initiate": None,
    "social-account-delete": None,
    # Revoking a key removes capability; renaming or minting one does not,
    # so only DELETE is exempt.
    "api-key-detail": frozenset({"DELETE"}),
}


def enforce_mfa_enrolment(request, user, token) -> None:
    """Refuse a write from a session whose role requires two-factor
    authentication and whose account is past its grace period without one.

    API keys never reach this: it runs inside ``CookieJWTAuthentication``
    only, which ``ApiKeyAuthentication`` does not share. That is deliberate,
    not an oversight — the policy is about proving a second factor at the
    *login* moment, and a key has none to prove; every login door already
    demands one when a factor exists (``mfa.requires_challenge``), and a key
    is barred from ever touching the MFA/login/key-management surface at all
    (``ACCOUNTS_API_KEY_ALLOWLIST``, default-deny). Blocking key traffic here
    too would only remove the one credential that keeps working when a human
    cannot immediately get to a browser, for no security gained: a key cannot
    complete the enrolment ceremony this check exists to push someone toward.

    Also skipped for an active impersonation session (an admin cannot enrol a
    factor on someone else's behalf, so their compliance state is not this
    request's to answer for — the same exemption ``MfaEnrolmentGate`` makes in
    the browser) and for safe methods (reading was never gated by this).
    """
    if request.method in SAFE_METHODS or token.get(IMPERSONATOR_CLAIM):
        return

    url_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
    exempt_methods = MFA_ENROLMENT_EXEMPT_URL_NAMES.get(url_name, frozenset())
    if exempt_methods is None or request.method in exempt_methods:
        return

    from .models import AppSettings

    app_settings = AppSettings.load()
    if user.role not in app_settings.mfa_required_roles:
        return

    from . import mfa

    status = mfa.compliance_status(user, app_settings=app_settings, has_factor=mfa.has_any_factor(user))
    if status is None or status["status"] != "overdue":
        return

    _audit_enrolment_required(request, user)
    raise exceptions.PermissionDenied({
        "detail": "Set up two-factor authentication to continue.",
        "code": "mfa_enrolment_required",
    })


def _audit_enrolment_required(request, user) -> None:
    from audit.models import AuditActionCategory, AuditEventStatus
    from audit.services import record_audit_event

    url_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.AUTH,
        action_type="auth.mfa.enrolment_required",
        target_type="accounts.User",
        target=user,
        target_id=str(user.pk),
        target_display=user.email or user.username,
        summary=f"Refused {request.method} {url_name or request.path} for "
                f"{user.email or user.username}: two-factor authentication is overdue.",
        user=user,
        status=AuditEventStatus.DENIED,
        metadata={"method": request.method, "url_name": url_name},
    )


# ── API key scope rules ───────────────────────────────────────────────────────
#
# The ``accounts`` app is default-deny for API keys: it holds every endpoint
# that mints a session, changes how the owner authenticates, or manages keys
# themselves. A key that can reach those is not a revocable credential — it is a
# permanent account takeover, because the holder can mint a browser session,
# change the password, impersonate somebody, or issue fresh keys so revoking the
# leaked one achieves nothing.
#
# Default-deny rather than a deny-list: a new endpoint added to ``accounts``
# tomorrow is closed until somebody deliberately opens it. A deny-list would
# have to be remembered, and forgetting it fails silently.
#
# Maps URL name → allowed methods, or ``None`` for "all methods".
ACCOUNTS_API_KEY_ALLOWLIST: dict[str, frozenset[str] | None] = {
    "me": SAFE_METHODS,
    "app-settings": SAFE_METHODS,
    "feature-flags-list": SAFE_METHODS,
    "registration-enabled": SAFE_METHODS,
    "user-list-create": SAFE_METHODS,
    "user-detail": SAFE_METHODS,
    # Billing configuration, not a credential surface — admin automation is a
    # plausible use, so writes are allowed subject to the view's own permissions.
    "vat-rate-list-create": None,
    "vat-rate-detail": None,
}


def _view_is_in_accounts_app(request) -> bool:
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match is None:
        # No resolved view means we cannot prove the request is safe. Closed.
        return True
    module = getattr(resolver_match.func, "__module__", "") or ""
    return module == "accounts" or module.startswith("accounts.")


def check_api_key_scope(request) -> None:
    """Raise ``PermissionDenied`` if this request is out of scope for a key.

    Enforced here rather than in ``DEFAULT_PERMISSION_CLASSES`` because DRF
    *replaces* the default permissions when a view declares its own, and nearly
    every view in this project does — a default permission would be silently
    skipped on exactly the endpoints that matter. An authentication class runs
    for every request that uses it, and a view can only escape it by dropping
    key authentication altogether, which fails closed.
    """
    if not _view_is_in_accounts_app(request):
        return

    denied = exceptions.PermissionDenied(
        "This endpoint cannot be used with an API key. Sign in instead."
    )

    url_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
    if url_name not in ACCOUNTS_API_KEY_ALLOWLIST:
        raise denied

    allowed_methods = ACCOUNTS_API_KEY_ALLOWLIST[url_name]
    if allowed_methods is not None and request.method not in allowed_methods:
        raise denied


class ApiKeyAuthentication(BaseAuthentication):
    """``Authorization: Api-Key ozv_<prefix>_<secret>``.

    Returns ``(user, api_key)`` so ``request.auth`` carries the credential and
    downstream code can tell a script apart from a browser session.
    """

    keyword = b"Api-Key"

    def authenticate(self, request):
        auth_header = get_authorization_header(request).split()
        if not auth_header or auth_header[0].lower() != self.keyword.lower():
            return None
        if len(auth_header) != 2:
            raise exceptions.AuthenticationFailed(
                "Invalid Api-Key header. Expected 'Api-Key <key>'."
            )

        try:
            raw_key = auth_header[1].decode("utf-8")
        except UnicodeError:
            raise exceptions.AuthenticationFailed("Invalid Api-Key header encoding.")

        api_key = self._resolve_key(raw_key)
        user = api_key.user

        if not user.is_active:
            raise exceptions.AuthenticationFailed("User inactive or deleted.")

        self._enforce_scope(request, api_key)
        self._touch(api_key)
        return user, api_key

    def authenticate_header(self, request):
        # Drives the WWW-Authenticate header, which is what makes DRF answer
        # 401 rather than 403 for an unauthenticated request.
        return "Api-Key"

    # ── internals ────────────────────────────────────────────────────────────

    def _resolve_key(self, raw_key: str):
        from .models import ApiKey

        # One generic message for every failure mode: a caller learns whether
        # their key works, not whether a prefix exists.
        invalid = exceptions.AuthenticationFailed("Invalid or expired API key.")

        split = split_key(raw_key)
        if split is None:
            raise invalid
        prefix, secret = split

        try:
            api_key = ApiKey.objects.select_related("user").get(prefix=prefix)
        except ApiKey.DoesNotExist:
            raise invalid

        if not verify_secret(secret, api_key.hashed_key):
            raise invalid
        if not api_key.is_active:
            raise invalid

        return api_key

    def _enforce_scope(self, request, api_key) -> None:
        if api_key.read_only and request.method not in SAFE_METHODS:
            raise exceptions.PermissionDenied("This API key is read-only.")

        check_api_key_scope(request)

        # Mark the request so audit events can name the credential. Set on both
        # the DRF request and the underlying HttpRequest: views pass either.
        request.audit_source = "api_key"
        request.api_key = api_key
        underlying = getattr(request, "_request", None)
        if underlying is not None:
            underlying.audit_source = "api_key"
            underlying.api_key = api_key

    def _touch(self, api_key) -> None:
        """Record use, at most once per resolution window.

        Writing ``last_used_at`` on every request would turn every read into a
        write. The field exists to find abandoned keys, not to be an access log,
        so a few minutes of staleness costs nothing.
        """
        from .models import ApiKey

        now = timezone.now()
        resolution = settings.API_KEY_LAST_USED_RESOLUTION
        if api_key.last_used_at is not None and now - api_key.last_used_at < resolution:
            return

        ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=now)
        api_key.last_used_at = now
