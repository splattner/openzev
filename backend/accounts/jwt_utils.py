from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth.models import update_last_login
from django.utils import timezone
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

#: Claim carrying ``User.session_version`` at the moment the token was issued.
#: A token whose value no longer matches the account's is a signed-out session
#: (see ``accounts.session_revocation`` and ADR 0022).
SESSION_CLAIM = "sv"

IMPERSONATOR_CLAIM = "impersonated_by"
PASSWORD_RECOVERY_CLAIM = "password_recovery_until"
PASSWORD_RECOVERY_WINDOW = timedelta(minutes=15)


def make_jwt_for_user(user, *, impersonated_by=None, participant_link: bool = False) -> dict:
    refresh = RefreshToken.for_user(user)
    add_custom_claims(refresh, user)
    if impersonated_by:
        refresh[IMPERSONATOR_CLAIM] = impersonated_by
    elif participant_link:
        refresh[PASSWORD_RECOVERY_CLAIM] = int((timezone.now() + PASSWORD_RECOVERY_WINDOW).timestamp())
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def password_recovery_deadline(token, user):
    """Live link-login permission for this account and session, or None."""
    from zev.services import requires_independent_login

    if not isinstance(token, AccessToken) or impersonator_of(token):
        return None
    deadline = token.get(PASSWORD_RECOVERY_CLAIM)
    if not isinstance(deadline, int) or deadline <= timezone.now().timestamp():
        return None
    if (str(token.get(api_settings.USER_ID_CLAIM)) != str(user.pk)
            or token.get(SESSION_CLAIM) != user.session_version
            or not user.is_active or requires_independent_login(user)):
        return None
    return datetime.fromtimestamp(deadline, tz=dt_timezone.utc)


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
