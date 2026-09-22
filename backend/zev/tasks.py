"""Celery tasks for the zev app."""
import logging

from celery import shared_task
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def warm_participant_geocode_cache_task(self, participant_id: str):
    """Best-effort: geocode a participant's address and cache the building bbox."""
    from .geocoding import warm_geocode_cache
    from .models import Participant

    try:
        participant = Participant.objects.get(pk=participant_id)
    except Participant.DoesNotExist:
        logger.warning("Participant %s not found for geocode task", participant_id)
        return

    if not (participant.address_line1 and participant.city):
        return

    warm_geocode_cache(participant.address_line1, participant.postal_code, participant.city)


def trigger_geocode_if_address_present(participant) -> None:
    """Enqueue a best-effort cache warm-up for a participant's address.

    Safe to call unconditionally on every create/update: the task itself is a
    no-op once the address is cached, so this never causes repeated Nominatim
    calls for an unchanged address. Also a no-op while
    ``FeatureFlag.PARTICIPANT_GEOCODING_ENABLED`` is off — checked here too
    (on top of the check inside ``warm_geocode_cache``) purely so a disabled
    instance doesn't churn the Celery queue with tasks that would just return
    immediately.
    """
    from accounts.models import FeatureFlag

    if not FeatureFlag.is_enabled(FeatureFlag.PARTICIPANT_GEOCODING_ENABLED):
        return

    if participant.address_line1 and participant.city:
        participant_id = str(participant.pk)
        transaction.on_commit(
            lambda: warm_participant_geocode_cache_task.delay(participant_id),
            robust=True,
        )
