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


class InvoiceLinkThrottle(SimpleRateThrottle):
    """Rate-limit the unauthenticated invoice-link endpoints, by IP.

    The prefix is 16 hex characters guarding a 256-bit secret, so enumeration
    is already hopeless on entropy alone. This exists so it is also cheap to
    refuse, and so one leaked link cannot be used to hammer the endpoint.
    """

    scope = "invoice_link"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class MagicLinkRequestThrottle(SimpleRateThrottle):
    """Bound magic-link requests **per invoice link**, not per IP.

    A leaked invoice is the realistic abuse here: whoever holds it can ask for
    a link to the participant's mailbox over and over. Keying on the invoice
    prefix caps that at a handful an hour no matter where the requests come
    from, which keying on IP would not.

    ``InvoiceLinkThrottle`` still applies the per-IP ceiling on the same view.
    """

    scope = "magic_link_request"

    def get_cache_key(self, request, view):
        prefix = (request.data or {}).get("prefix") or ""
        if not prefix:
            return None
        return self.cache_format % {"scope": self.scope, "ident": prefix}
