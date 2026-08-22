from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class ApiKeyRateThrottle(SimpleRateThrottle):
    """Rate-limit requests authenticated with an API key.

    Scoped to the key rather than the user or the IP: a standing credential in a
    loop is the case worth bounding, and a user's browser session should not be
    slowed down because one of their scripts is busy.

    Returns ``None`` for anything that is not key-authenticated, which leaves
    cookie sessions untouched — nothing is throttled today, and tuning limits
    for the interactive UI is a separate decision.
    """

    scope = "api_key"

    def get_cache_key(self, request, view):
        from .models import ApiKey

        api_key = getattr(request, "auth", None)
        if not isinstance(api_key, ApiKey):
            return None
        return self.cache_format % {"scope": self.scope, "ident": str(api_key.pk)}


class AuthRateThrottle(SimpleRateThrottle):
    """Per-IP rate limit for public auth endpoints.

    Login, refresh, registration and email verification are the only endpoints
    a stranger can hit without any credential, so each gets its own budget
    keyed by client IP. Each endpoint uses a dedicated subclass so budgets
    never share a counter.
    """

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class AuthLoginThrottle(AuthRateThrottle):
    scope = "auth_login"


class AuthRefreshThrottle(AuthRateThrottle):
    scope = "auth_refresh"


class AuthRegisterThrottle(AuthRateThrottle):
    scope = "auth_register"


class AuthVerifyThrottle(AuthRateThrottle):
    scope = "auth_verify"


class AuthOAuthInitiateThrottle(AuthRateThrottle):
    scope = "auth_oauth_initiate"


class AuthOAuthExchangeThrottle(AuthRateThrottle):
    scope = "auth_oauth_exchange"


class ImportThrottle(UserRateThrottle):
    """Per-user budget for metering imports."""

    scope = "import"


class TransferArchiveThrottle(UserRateThrottle):
    """Per-user budget for whole-ZEV transfer archive import/inspect."""

    scope = "transfer_import"
