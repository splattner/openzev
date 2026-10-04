"""Celery tasks for the zev app."""
import logging

from celery import shared_task
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def warm_building_geocode_cache_task(self, building_id: str):
    """Best-effort: geocode a building's address and cache the building bbox."""
    from .geocoding import warm_geocode_cache
    from .models import Building

    try:
        building = Building.objects.get(pk=building_id)
    except Building.DoesNotExist:
        logger.warning("Building %s not found for geocode task", building_id)
        return

    if not (building.address_line1 and building.city):
        return

    warm_geocode_cache(building.address_line1, building.postal_code, building.city)


def trigger_building_geocode_if_address_present(building) -> None:
    """Enqueue a best-effort cache warm-up for a building's address (#890).

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

    if building.address_line1 and building.city:
        building_id = str(building.pk)
        transaction.on_commit(
            lambda: warm_building_geocode_cache_task.delay(building_id),
            robust=True,
        )
