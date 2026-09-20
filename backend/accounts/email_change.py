"""Changing the address an account signs in with.

The email is the login identifier and the target of every emailed sign-in link,
so whoever controls it controls the account. Changing it therefore has to
survive a stolen session: asking for the change needs the current password (the
session alone is not enough), the new address has to prove it is reachable
before anything changes, and the old address is told afterwards.

The link is a signed, time-limited token rather than a database row: it carries
what it was issued for and is checked against the account's *current* state, so
it dies on its own once used (the address it was issued from is gone), once the
password changes, or once someone else takes the address. See spec
2026-03-community-and-access.md §5.6a.
"""

import hashlib

from django.core import signing

from .models import User

SALT = "accounts.email-change"
LIFETIME_SECONDS = 24 * 60 * 60


class EmailChangeError(Exception):
    """The token is not usable. One type on purpose: the response must not say
    which of the reasons applied."""


def _state_fingerprint(user: User) -> str:
    """Stands for "the account as it was when the link was issued": its current
    address and password. Either changing makes the fingerprint differ, which is
    what makes a link single-use and mortal — and folding both into one short
    value keeps the emailed URL short."""
    return hashlib.sha256(f"{user.email}\x00{user.password}".encode()).hexdigest()[:16]


def address_in_use(email: str, *, excluding: User) -> bool:
    return User.objects.filter(email__iexact=email).exclude(pk=excluding.pk).exists()


def issue_token(user: User, new_email: str) -> str:
    return signing.dumps({"u": user.pk, "n": new_email, "f": _state_fingerprint(user)}, salt=SALT, compress=True)


def resolve_token(token: str) -> tuple[User, str]:
    """The account and the address a valid token would move it to.

    Raises ``EmailChangeError`` for anything else: a bad or expired signature,
    a deactivated account, an account whose address or password has changed
    since the token was issued, or a target address someone else now holds.
    """
    try:
        data = signing.loads(token, salt=SALT, max_age=LIFETIME_SECONDS)
        user_id, new, fingerprint = data["u"], data["n"], data["f"]
    except (signing.BadSignature, KeyError, TypeError):
        raise EmailChangeError from None

    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or _state_fingerprint(user) != fingerprint:
        raise EmailChangeError
    if address_in_use(new, excluding=user):
        raise EmailChangeError
    return user, new
