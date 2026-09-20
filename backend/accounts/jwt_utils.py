from django.contrib.auth.models import update_last_login
from rest_framework_simplejwt.tokens import RefreshToken

#: Claim carrying ``User.session_version`` at the moment the token was issued.
#: A token whose value no longer matches the account's is a signed-out session
#: (see ``accounts.session_revocation`` and ADR 0022).
SESSION_CLAIM = "sv"

IMPERSONATOR_CLAIM = "impersonated_by"


def make_jwt_for_user(user, *, impersonated_by=None) -> dict:
    refresh = RefreshToken.for_user(user)
    add_custom_claims(refresh, user)
    if impersonated_by:
        refresh[IMPERSONATOR_CLAIM] = impersonated_by
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def add_custom_claims(token, user) -> None:
    token["role"] = user.role
    token["email"] = user.email
    token["full_name"] = user.get_full_name()
    token["must_change_password"] = user.must_change_password
    token[SESSION_CLAIM] = user.session_version


def impersonator_of(token) -> int | None:
    """The admin behind an impersonation session, or ``None``.

    ``request.auth`` is a validated JWT for browser sessions but an ``ApiKey``
    for scripts, which carry no such claim — hence the ``hasattr`` guard.
    """
    if token is None or not hasattr(token, "get"):
        return None
    return token.get(IMPERSONATOR_CLAIM) or None


def record_login(user) -> None:
    """Stamp ``last_login`` for a genuine new sign-in.

    Called explicitly at each door that mints a session because a person just
    authenticated — never from inside ``make_jwt_for_user`` itself, which also
    backs two things that are not that: ``session_revocation.keep_current_session``
    (reissuing tokens under the *same* session after a password or email
    change) and impersonation (the admin signed in; the target did not).
    Reuses Django's own ``update_last_login`` — the same function
    ``django.contrib.auth`` wires to the ``user_logged_in`` signal for the
    admin site, which none of this project's own login views raise (they
    return JSON, not a redirect through ``django.contrib.auth.login()``).
    """
    update_last_login(None, user)
