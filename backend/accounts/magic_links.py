"""Passwordless sign-in for participants, reached from an invoice link.

Tier 2 of ``docs/specs/2026-09-participant-invoice-access.md``. Tier 1 shows the
bearer one invoice and needs no authentication because it discloses nothing the
paper does not. This grants real access, so it does not travel on paper: the
link goes to the address the operator recorded, and the requester never names
the destination.

That is also what removes account enumeration from the design rather than
mitigating it — there is no address field to probe.
"""
import logging
import secrets

from django.db import transaction
from django.utils import timezone

from .models import MagicLinkToken

logger = logging.getLogger(__name__)

TOKEN_BYTES = 32


def account_for_participant(participant):
    """The user a magic link should sign in, creating one if needed.

    Returns ``None`` when the participant has no address to send to — the
    caller still answers 202, because saying "no account here" would answer a
    question the requester is not entitled to ask.

    A freshly created account gets **no usable password**: nothing is
    transmitted, so there is nothing to rotate, and ``must_change_password``
    would strand the user in a form asking them to change a password they were
    never given.
    """
    from zev.services import ensure_participant_account

    if not participant.email:
        return None

    user, _created_password = ensure_participant_account(participant)

    # ensure_participant_account mints a temporary password for the invitation
    # flow. Nothing here transmits it, so leaving it usable would keep a
    # credential alive that nobody has and nobody can rotate.
    if user.must_change_password or not user.has_usable_password():
        user.set_unusable_password()
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
    return user


@transaction.atomic
def issue(user) -> MagicLinkToken:
    """Mint a token, invalidating any earlier unconsumed one for this user.

    Superseding rather than accumulating: a participant who taps the button
    twice should not leave a spare key lying in an inbox, and the most recent
    request is the one they are waiting for.
    """
    MagicLinkToken.objects.filter(user=user, consumed_at__isnull=True).update(
        consumed_at=timezone.now()
    )
    return MagicLinkToken.objects.create(user=user, token=secrets.token_urlsafe(TOKEN_BYTES))


def consume(token_value: str):
    """The user for a valid, unconsumed token, or ``None``.

    Consuming an outstanding invitation's temporary password too: a participant
    who was invited, never activated, and then used a magic link instead would
    otherwise leave that emailed password valid indefinitely.
    """
    if not token_value:
        return None

    with transaction.atomic():
        token = (
            MagicLinkToken.objects
            .select_for_update()
            .select_related("user")
            .filter(token=token_value)
            .first()
        )
        if token is None or not token.is_valid():
            return None

        token.consumed_at = timezone.now()
        token.save(update_fields=["consumed_at"])

        user = token.user
        if user.must_change_password:
            user.set_unusable_password()
            user.must_change_password = False
            user.save(update_fields=["password", "must_change_password"])
        return user
