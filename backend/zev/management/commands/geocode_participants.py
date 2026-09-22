"""
Django management command: python manage.py geocode_participants

Warms the geocoding cache for every participant that has an address but
hasn't been geocoded yet — e.g. participants created before this feature
existed, or ones whose owner-setup bootstrap bypassed the usual API path.

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
from zev.models import Participant


class Command(BaseCommand):
    help = "Warm the geocoding cache for participants with an address that hasn't been geocoded yet."

    def handle(self, *args, **options):
        if not FeatureFlag.is_enabled(FeatureFlag.PARTICIPANT_GEOCODING_ENABLED):
            raise CommandError(
                "Participant geocoding is disabled "
                f"(FeatureFlag '{FeatureFlag.PARTICIPANT_GEOCODING_ENABLED}' is off). "
                "Enable it in Admin → System Settings → Features before running this command."
            )

        participants = Participant.objects.exclude(address_line1="").exclude(city="")

        geocoded = 0
        for participant in participants:
            warm_geocode_cache(participant.address_line1, participant.postal_code, participant.city)
            geocoded += 1

        self.stdout.write(self.style.SUCCESS(f"Warmed geocoding cache for {geocoded} participant address(es)."))
