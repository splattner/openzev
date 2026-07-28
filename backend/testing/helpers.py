"""User creation and authentication helpers shared across the test suite.

The project authenticates with JWT delivered via httpOnly cookies, but
``CookieJWTAuthentication`` also accepts a standard ``Authorization: Bearer``
header. For tests we mint a token directly and set the header on the client,
which avoids an extra HTTP round-trip through the login endpoint.
"""

from __future__ import annotations

from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User


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


def authenticate(client, user) -> None:
    """Authenticate ``client`` as ``user`` via a Bearer token.

    Mirrors the production ``CookieJWTAuthentication`` header fallback so test
    clients can authenticate without driving the full cookie-based login flow.
    """
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


def access_token_for(user) -> str:
    """Return a raw access token string for ``user`` (useful for cookie tests)."""
    return str(RefreshToken.for_user(user).access_token)
