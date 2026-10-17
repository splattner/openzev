"""Authentication of the analytics endpoint: ``Authorization: Bearer oza_<prefix>_<secret>``.

The token is not a user: ``request.user`` stays anonymous and ``request.auth`` is
the :class:`~analytics.models.AnalyticsToken`. It is listed first on the one view
that accepts it, ahead of the JWT class, and passes on anything that is not shaped
like one of its own tokens so that a session JWT still reaches ``CookieJWTAuthentication``.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.throttling import SimpleRateThrottle

from accounts.api_keys import split_key, verify_secret

from .models import TOKEN_NAMESPACE, AnalyticsToken


def tokens_enabled() -> bool:
    from accounts.models import FeatureFlag

    return FeatureFlag.is_enabled(FeatureFlag.ANALYTICS_TOKENS_ENABLED)


class AnalyticsTokenAuthentication(BaseAuthentication):
    keyword = b"bearer"

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if len(header) != 2 or header[0].lower() != self.keyword:
            return None
        try:
            raw = header[1].decode("utf-8")
        except UnicodeError:
            return None
        split = split_key(raw, TOKEN_NAMESPACE)
        if split is None:
            return None

        # One message for every failure: a caller learns whether their token
        # works, not whether a prefix exists or why it stopped.
        invalid = exceptions.AuthenticationFailed("Invalid or revoked analytics token.")
        prefix, secret = split
        token = AnalyticsToken.objects.select_related("created_by", "zev", "participant").filter(prefix=prefix).first()
        if token is None or not verify_secret(secret, token.hashed_key) or not token.is_active:
            raise invalid
        if not tokens_enabled() or not token.created_by.is_active:
            raise invalid

        self._touch(token)
        return AnonymousUser(), token

    def authenticate_header(self, request):
        return "Bearer"

    @staticmethod
    def _touch(token: AnalyticsToken) -> None:
        """Record use at most once per resolution window, as ``ApiKeyAuthentication`` does."""
        now = timezone.now()
        if token.last_used_at is not None and now - token.last_used_at < settings.API_KEY_LAST_USED_RESOLUTION:
            return
        AnalyticsToken.objects.filter(pk=token.pk).update(last_used_at=now)
        token.last_used_at = now


class AnalyticsTokenThrottle(SimpleRateThrottle):
    """Per token, so one busy dashboard cannot spend another token's budget."""

    scope = "analytics_token"

    def get_cache_key(self, request, view):
        token = getattr(request, "auth", None)
        if not isinstance(token, AnalyticsToken):
            return None
        return self.cache_format % {"scope": self.scope, "ident": str(token.pk)}


class AnalyticsTokenAuthenticationScheme(OpenApiAuthenticationExtension):
    """Documents the token in the OpenAPI schema (see ``accounts/schema.py``)."""

    target_class = "analytics.authentication.AnalyticsTokenAuthentication"
    name = "AnalyticsToken"

    def get_security_definition(self, _auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "description": (
                "A read-only analytics token (`oza_<prefix>_<secret>`) shown once when it is created. "
                "It can only read `/analytics/series/`, for the ZEV (or participant) it was created for."
            ),
        }
