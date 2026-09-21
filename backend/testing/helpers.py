"""User creation and authentication helpers shared across the test suite.

The project authenticates with JWT delivered via httpOnly cookies, but
``CookieJWTAuthentication`` also accepts a standard ``Authorization: Bearer``
header. For tests we mint a token directly and set the header on the client,
which avoids an extra HTTP round-trip through the login endpoint.
"""

from __future__ import annotations

from contextlib import contextmanager

from django.conf import settings as dj_settings
from django.test import override_settings
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.jwt_utils import SESSION_CLAIM
from accounts.models import User, VatRate
from zev.models import Participant


def make_user(username: str, role: str, password: str = "pass1234") -> User:
    """Create a bare user with a role and a conventional ``@example.com`` email.

    Seven test modules each defined their own copy of this exact function
    (two near-identical variants) before it was consolidated here. Prefer the
    factory_boy factories in ``testing.factories`` for anything that needs a
    fuller object graph (a Zev, a Participant, ...); reach for this when a
    test genuinely only needs a user.
    """
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password=password, role=role
    )


def make_named_participant(zev, name, valid_from, valid_to=None) -> Participant:
    """Create a participant, splitting ``name`` like ``"Alice Muster"``.

    The email is derived from the full name, matching the fixture builder that
    was previously duplicated across the allocation and invoice test modules.
    """
    first, last = name.split(" ", 1)
    return Participant.objects.create(
        zev=zev,
        first_name=first,
        last_name=last,
        email=f"{name.replace(' ', '').lower()}@example.com",
        valid_from=valid_from,
        valid_to=valid_to,
    )


def authenticate(client, user) -> None:
    """Authenticate ``client`` as ``user`` via a Bearer token.

    Mirrors the production ``CookieJWTAuthentication`` header fallback so test
    clients can authenticate without driving the full cookie-based login flow.
    """
    refresh = RefreshToken.for_user(user)
    # As production issuance does (accounts.jwt_utils.add_custom_claims), so a
    # test that signs the account out and authenticates again gets a token that
    # is valid under the new session version.
    refresh[SESSION_CLAIM] = user.session_version
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


def clear_vat_rates() -> None:
    """Start from an empty VAT table.

    Migration 0015 installs an open-ended 8.1% default that overlaps custom
    fixtures, so test classes owning their VAT history clear it first.
    """
    VatRate.objects.all().delete()


@contextmanager
def trusted_proxies(num_proxies):
    """Set the trusted X-Forwarded-For hop count for tests.

    ``config.client_ip`` and DRF throttling both read the effective
    ``REST_FRAMEWORK["NUM_PROXIES"]`` setting (single source of truth, wired
    from the ``NUM_PROXIES`` env var in ``config/settings.py``), so tests
    only need to override that one key.
    """
    rest_framework = {**dj_settings.REST_FRAMEWORK, "NUM_PROXIES": num_proxies}
    with override_settings(REST_FRAMEWORK=rest_framework):
        yield
