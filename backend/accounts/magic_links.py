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

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import MagicLinkToken, User

logger = logging.getLogger(__name__)

TOKEN_BYTES = 32


def account_for_participant(participant):
    """Return the account a participant link may sign in, or None."""
    from zev.services import LinkRefused, link_account_for

    if not participant.email:
        return None

    try:
        return link_account_for(participant)
    except (LinkRefused, ObjectDoesNotExist, ValidationError):
        return None


@transaction.atomic
def issue(user) -> MagicLinkToken:
    """Mint a token, invalidating any earlier unconsumed one for this user.

    Superseding rather than accumulating: a participant who taps the button
    twice should not leave a spare key lying in an inbox, and the most recent
    request is the one they are waiting for.
    """
    # Serialize issuance with password writes and access promotion.
    user = User.objects.locked().get(pk=user.pk)
    MagicLinkToken.objects.filter(user=user, consumed_at__isnull=True).update(
        consumed_at=timezone.now()
    )
    return MagicLinkToken.objects.create(user=user, token=secrets.token_urlsafe(TOKEN_BYTES))


def consume(token_value: str):
    """Spend a valid token even on refusal; return its user only when participant links are allowed."""
    from zev.services import requires_independent_login

    if not token_value:
        return None

    with transaction.atomic():
        user_id = MagicLinkToken.objects.filter(token=token_value).values_list("user_id", flat=True).first()
        if user_id is None:
            return None
        # Promotions retire tokens under the user lock: always lock user first.
        user = User.objects.locked().filter(pk=user_id).first()
        if user is None:
            return None
        token = (
            MagicLinkToken.objects
            .select_for_update()
            .filter(token=token_value)
            .first()
        )
        if token is None or not token.is_valid():
            return None

        token.consumed_at = timezone.now()
        token.save(update_fields=["consumed_at"])

        if not user.is_active or requires_independent_login(user):
            return None
        return user


def retire_pending_password(user) -> None:
    """Retire pending credentials after full link authentication, under the user lock."""
    if user.must_change_password:
        user.set_unusable_password()
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])


def revoke_for_user(user) -> int:
    return MagicLinkToken.objects.filter(user=user, consumed_at__isnull=True).update(
        consumed_at=timezone.now(),
    )
