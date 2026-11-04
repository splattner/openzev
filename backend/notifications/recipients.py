"""Who an event is addressed to (SPEC-2026-11-notification-center §4.2)."""

from django.db.models import Q

from allocation.validity import active_on
from zev import access
from zev.models import MeteringPointAssignment, ZevAccessGrant, ZevAccessRole


def manager_accounts(zev) -> list:
    """Accounts managing ``zev`` today: an active manager grant or a managing party role."""
    day = access._today()
    grants = active_on(
        ZevAccessGrant.objects.filter(zev_id=zev.pk, role=ZevAccessRole.MANAGER).select_related("user"), day
    )
    accounts = {grant.user_id: grant.user for grant in grants}
    for account, _row in access.role_managers(zev, day):
        accounts.setdefault(account.pk, account)
    return list(accounts.values())


def participant_recipient(participant) -> list[tuple]:
    """``[(account, participant)]`` for a participant with a login, else nothing."""
    if participant.user_id is None:
        return []
    return [(participant.user, participant)]


def metering_point_recipients(metering_point_id, first_day, last_day) -> list[tuple]:
    """Participants holding a metering point on some day of ``first_day``–``last_day``, with a login."""
    rows = (
        MeteringPointAssignment.objects.filter(
            metering_point_id=metering_point_id,
            valid_from__lte=last_day,
            participant__user__isnull=False,
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=first_day))
        .filter(access.live_participant_q("participant__"))
        .select_related("participant__user")
    )
    seen, recipients = set(), []
    for row in rows:
        if row.participant_id not in seen:
            seen.add(row.participant_id)
            recipients.append((row.participant.user, row.participant))
    return recipients
