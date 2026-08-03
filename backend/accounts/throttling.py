from rest_framework.throttling import SimpleRateThrottle


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
