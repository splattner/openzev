"""
Django management command: python manage.py geocode_participants

Warms the geocoding cache for every building that has an address but
hasn't been geocoded yet — e.g. buildings created before the map was turned
on. The map shows buildings, not participants' billing addresses (#890, ADR
0012 amended); the command keeps its name for existing cron jobs.

Calls Nominatim sequentially (one request at a time) rather than enqueuing
Celery tasks in a burst, to respect its public usage policy.

Gated by ``FeatureFlag.PARTICIPANT_GEOCODING_ENABLED`` (off by default, #796):
``warm_geocode_cache`` itself is a no-op while the flag is off, so running
this command on a disabled instance would otherwise silently do nothing and
report success. Checked up front instead so the operator gets a clear reason.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from accounts.models import FeatureFlag
from zev.geocoding import warm_geocode_cache
from zev.models import Building


class Command(BaseCommand):
    help = "Warm the geocoding cache for buildings with an address that hasn't been geocoded yet."

    def handle(self, *args, **options):
        if not FeatureFlag.is_enabled(FeatureFlag.PARTICIPANT_GEOCODING_ENABLED):
            raise CommandError(
                "Map geocoding is disabled "
                f"(FeatureFlag '{FeatureFlag.PARTICIPANT_GEOCODING_ENABLED}' is off). "
                "Enable it in Platform → Settings → Functions before running this command."
            )

        buildings = Building.objects.exclude(address_line1="").exclude(city="")

        geocoded = 0
        for building in buildings:
            warm_geocode_cache(building.address_line1, building.postal_code, building.city)
            geocoded += 1

        self.stdout.write(self.style.SUCCESS(f"Warmed geocoding cache for {geocoded} building address(es)."))
