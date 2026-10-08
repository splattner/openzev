"""Authentication of the push endpoint: ``Authorization: Bearer ozs_<prefix>_<secret>``.

The token identifies exactly one source and nothing else: it is not a user, it
cannot reach any other endpoint, and it is stored hashed (one SHA-256 pass, for
the reason in ``accounts.api_keys.hash_secret``). ``request.user`` is anonymous
and ``request.auth`` is the source.
"""

from __future__ import annotations

from django.contrib.auth.models import AnonymousUser
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.permissions import BasePermission
from rest_framework.throttling import SimpleRateThrottle

from accounts.api_keys import split_key, verify_secret

from ..models import PUSH_TOKEN_NAMESPACE, SupplementarySource


class SupplementaryPushAuthentication(BaseAuthentication):
    keyword = b"bearer"

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword:
            return None
        invalid = exceptions.AuthenticationFailed("Invalid or revoked push token.")
        if len(header) != 2:
            raise invalid
        try:
            raw = header[1].decode("utf-8")
        except UnicodeError:
            raise invalid from None

        split = split_key(raw, PUSH_TOKEN_NAMESPACE)
        if split is None:
            raise invalid
        prefix, secret = split
        source = SupplementarySource.objects.select_related("metering_point", "participant").filter(
            push_token_prefix=prefix
        ).first()
        # One message for every failure: a caller learns whether their token works,
        # not whether a prefix exists.
        if source is None or not source.push_token_hash or not verify_secret(secret, source.push_token_hash):
            raise invalid
        return AnonymousUser(), source

    def authenticate_header(self, request):
        return "Bearer"


class IsPushSource(BasePermission):
    """The request carries a valid push token of an enabled source."""

    message = "Source is disabled."

    def has_permission(self, request, view):
        source = request.auth
        return isinstance(source, SupplementarySource) and source.enabled


class SupplementaryPushThrottle(SimpleRateThrottle):
    """Per push token, so one noisy client cannot spend another source's budget."""

    scope = "supplementary_push"

    def get_cache_key(self, request, view):
        source = request.auth
        if not isinstance(source, SupplementarySource):
            return None
        return self.cache_format % {"scope": self.scope, "ident": str(source.pk)}


class SupplementaryPushAuthenticationScheme(OpenApiAuthenticationExtension):
    """Documents the push token in the OpenAPI schema (see ``accounts/schema.py``)."""

    target_class = "metering.supplementary.authentication.SupplementaryPushAuthentication"
    name = "SupplementaryPushToken"

    def get_security_definition(self, _auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "description": (
                "A push token of one energy data source, shown once when the source is created "
                "(`ozs_<prefix>_<secret>`). It can only deliver readings for that source."
            ),
        }
