"""Recovering an account whose password is lost.

An emailed, time-limited link. Like ``email_change`` the token is signed rather
than a database row: it carries what it was issued for and is checked against the
account's *current* state, so it dies on its own once the password changes (which
is what using it does, so it is single-use) or the address changes. No table, no
cleanup job. See spec 2026-03-community-and-access.md §5.6c.

The link only ever sets a password. It mints no session, so an account with a
second factor still meets its TOTP / passkey challenge when the person signs in
afterwards: a reset must not be a way around the factor.
"""

from django.core import signing
from django.utils.crypto import salted_hmac

from .models import User

SALT = "accounts.password-reset"
LIFETIME_SECONDS = 60 * 60


class PasswordResetError(Exception):
    """The token is not usable. One type on purpose: the response must not say
    which of the reasons applied."""


def can_reset(user: User | None) -> bool:
    """Whether a link may be sent: an active account that has a password to lose.

    Participants without a password sign in by emailed link, OAuth-only accounts
    through their provider, and inactive accounts are pending a signup or an
    invitation: a reset link would be a second, unintended way in for each.
    """
    return user is not None and user.is_active and bool(user.email) and user.has_usable_password()


def _state_fingerprint(user: User) -> str:
    """Stands for "the account as it was when the link was issued": its address
    and password hash. Either changing makes the fingerprint differ. A keyed MAC
    (as in Django's own reset tokens), so nothing can be recomputed from a leaked
    token without the server's secret key."""
    return salted_hmac(SALT, f"{user.pk}\x00{user.email}\x00{user.password}").hexdigest()[:16]


def issue_token(user: User) -> str:
    return signing.dumps({"u": user.pk, "f": _state_fingerprint(user)}, salt=SALT, compress=True)


def resolve_token(token: str, *, user: User | None = None) -> User:
    """The account a valid token belongs to.

    Raises ``PasswordResetError`` for a bad or expired signature, an account that
    was deactivated or lost its password, and one whose address or password has
    changed since the token was issued.
    Pass the locked user to revalidate the complete contract after a lock wait.
    """
    try:
        data = signing.loads(token, salt=SALT, max_age=LIFETIME_SECONDS)
        user_id, fingerprint = data["u"], data["f"]
    except (signing.BadSignature, KeyError, TypeError):
        raise PasswordResetError from None

    if user is None:
        user = User.objects.filter(pk=user_id).first()
    if not can_reset(user) or user.pk != user_id or _state_fingerprint(user) != fingerprint:
        raise PasswordResetError
    return user
