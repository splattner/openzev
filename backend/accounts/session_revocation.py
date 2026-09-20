"""Signing accounts out of every session they hold.

Access and refresh tokens are stateless JWTs, so nothing server-side records
"sessions" to delete. Instead every token carries ``User.session_version`` as
it was when the token was issued; bumping the counter makes all older tokens
fail (``CookieJWTAuthentication.get_user`` for access tokens,
``CookieTokenRefreshView`` for refresh tokens). It is one integer per account
rather than a table of issued tokens — see ADR 0022 for why that is enough,
and what it deliberately does not give you (a per-device session list).

API keys are separate credentials with their own revocation and are not
affected.
"""

from django.db.models import F

from .cookies import set_auth_cookies
from .jwt_utils import impersonator_of, make_jwt_for_user


def revoke_sessions(user) -> None:
    """Invalidate every token issued for ``user`` so far.

    An atomic ``UPDATE`` on purpose, and the instance is reloaded so tokens
    minted straight afterwards carry the new value. ``User.save`` is written to
    leave the column alone — see the comment there.
    """
    type(user).objects.filter(pk=user.pk).update(session_version=F("session_version") + 1)
    user.refresh_from_db(fields=["session_version"])


def keep_current_session(request, response, user) -> None:
    """Hand the caller a fresh token pair so revoking *other* sessions does
    not sign them out of the one they are using.

    An impersonation session stays an impersonation session: the claim is
    carried over rather than silently promoting the admin to the target.
    """
    tokens = make_jwt_for_user(user, impersonated_by=impersonator_of(request.auth))
    set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])
