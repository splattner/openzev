"""User creation and authentication helpers shared across the test suite.

The project authenticates with JWT delivered via httpOnly cookies, but
``CookieJWTAuthentication`` also accepts a standard ``Authorization: Bearer``
header. For tests we mint a token directly and set the header on the client,
which avoids an extra HTTP round-trip through the login endpoint.
"""

from __future__ import annotations

from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
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
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
