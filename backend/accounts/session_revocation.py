"""Signing accounts out of every session they hold.

Access and refresh tokens are stateless JWTs, so nothing server-side records
"sessions" to delete. Instead every token carries ``User.session_version`` as
it was when the token was issued; bumping the counter makes all older tokens
fail (``CookieJWTAuthentication.get_user`` for access tokens,
``CookieTokenRefreshView`` for refresh tokens). It is one integer per account
rather than a table of issued tokens — see ADR 0022 for why that is enough,
and what it deliberately does not give you (a per-device session list).

Revocation also discards pending OAuth exchange codes. API keys are separate
credentials with their own revocation and are not affected.
"""

from django.db import transaction
from django.db.models import F
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken

from .cookies import set_auth_cookies
from .jwt_utils import SESSION_CLAIM, impersonator_of, is_participant_link_session, make_jwt_for_user
from .models import OAuthExchangeCode, User


def is_session_current(token, user) -> bool:
    """True when ``token`` was issued in ``user``'s current session.

    Participant-derived sessions also fail once independent access is required.
    ``is_active`` stays at the call sites.
    """
    if token.get(SESSION_CLAIM, 0) != user.session_version:
        return False
    if is_participant_link_session(token):
        from zev.services import requires_independent_login

        return not requires_independent_login(user)
    return True


def validate_refresh_token(refresh_token: str) -> RefreshToken:
    """Validate a refresh token against its active account's current session."""
    token = RefreshToken(refresh_token)
    user_id = token.get(jwt_settings.USER_ID_CLAIM)
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or not is_session_current(token, user):
        raise TokenError("Session has been signed out.")
    return token


def lock_current_session(request):
    """Recheck authentication under the user lock; caller must hold a transaction."""
    user = User.objects.locked().filter(pk=request.user.pk).first()
    if user is None or not user.is_active or not is_session_current(request.auth, user):
        raise AuthenticationFailed("This session has been signed out.")
    return user


@transaction.atomic
def revoke_sessions(user) -> None:
    """Invalidate every token issued for ``user`` so far.

    An atomic ``UPDATE`` on purpose, and the instance is reloaded so tokens
    minted straight afterwards carry the new value. ``User.save`` is written to
    leave the column alone — see the comment there.
    """
    type(user).objects.filter(pk=user.pk).update(session_version=F("session_version") + 1)
    OAuthExchangeCode.objects.filter(user=user).delete()
    user.refresh_from_db(fields=["session_version"])


def keep_current_session(request, response, user) -> None:
    """Hand the caller a fresh token pair so revoking *other* sessions does
    not sign them out of the one they are using.

    An impersonation session stays an impersonation session: the claim is
    carried over rather than silently promoting the admin to the target.
    """
    tokens = make_jwt_for_user(
        user, impersonated_by=impersonator_of(request.auth),
        participant_link=is_participant_link_session(request.auth),
    )
    set_auth_cookies(request, response, access=tokens["access"], refresh=tokens["refresh"])
