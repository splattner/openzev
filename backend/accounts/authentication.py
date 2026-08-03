from django.conf import settings
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.permissions import SAFE_METHODS
from rest_framework_simplejwt.authentication import JWTAuthentication

from .api_keys import split_key, verify_secret

ACCESS_COOKIE = "openzev_access"


class CookieJWTAuthentication(JWTAuthentication):
    """JWT authentication that reads the access token from an httpOnly cookie.

    Falls back to the standard Authorization header so API clients and existing
    tooling (e.g. drf-spectacular, curl) continue to work without changes.
    """

    def authenticate(self, request):
        # Prefer the Authorization header (API clients / backward-compat)
        header = self.get_header(request)
        if header:
            # Leave ``Api-Key`` credentials to ApiKeyAuthentication rather than
            # failing the request with "token not valid".
            if header.split()[0:1] == [b"Api-Key"]:
                return None
            return super().authenticate(request)

        # Fall back to the httpOnly cookie set by the login endpoint
        raw_token = request.COOKIES.get(ACCESS_COOKIE)
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token


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
