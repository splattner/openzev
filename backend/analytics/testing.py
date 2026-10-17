"""A small community with known numbers, shared by the analytics tests.

Four participants: Alice and Bob (consumers with accounts), Carol (consumer and
holder of a community-allocated common-area meter), Dan (producer). Every 15
minutes on 2026-06-10 (UTC 10:00 and 10:15 = 12:00 and 12:15 local) the community
consumes 10 kWh and produces 6, so 6 kWh are local and 4 come from the grid.
"""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from accounts.models import FeatureFlag
from metering.models import MeterReading, ReadingDirection
from testing.helpers import create_managed_zev, make_named_participant, make_user
from zev.models import AllocationMode, MeteringPoint, MeteringPointAssignment, MeteringPointType

DAY = date(2026, 6, 10)
NOON_1 = datetime(2026, 6, 10, 10, 0, tzinfo=dt_timezone.utc)
NOON_2 = datetime(2026, 6, 10, 10, 15, tzinfo=dt_timezone.utc)


class Community:
    def __init__(self, prefix="a"):
        self.manager = make_user(f"{prefix}_manager")
        self.zev = create_managed_zev(
            name=f"Analytics ZEV {prefix}", owner=self.manager, zev_type="vzev",
            start_date=date(2026, 1, 1), billing_interval="monthly", invoice_prefix=prefix.upper(),
        )
        self.alice_user = make_user(f"{prefix}_alice")
        self.bob_user = make_user(f"{prefix}_bob")
        self.alice = self._participant("Alice Muster", user=self.alice_user)
        self.bob = self._participant("Bob Beispiel", user=self.bob_user)
        self.carol = self._participant("Carol Common")
        self.dan = self._participant("Dan Producer")

        self.alice_mp = self._meter(f"{prefix}-ALICE", MeteringPointType.CONSUMPTION, self.alice)
        self.bob_mp = self._meter(f"{prefix}-BOB", MeteringPointType.CONSUMPTION, self.bob)
        self.common_mp = self._meter(
            f"{prefix}-COMMON", MeteringPointType.CONSUMPTION, self.carol, mode=AllocationMode.COMMUNITY
        )
        self.dan_mp = self._meter(f"{prefix}-SOLAR", MeteringPointType.PRODUCTION, self.dan)

        for ts in (NOON_1, NOON_2):
            self.reading(self.alice_mp, ts, "4")
            self.reading(self.bob_mp, ts, "3")
            self.reading(self.common_mp, ts, "3")  # community: 0.75 each
            self.reading(self.dan_mp, ts, "6", ReadingDirection.OUT)

    def _participant(self, name, user=None):
        participant = make_named_participant(self.zev, name, date(2026, 1, 1))
        if user is not None:
            participant.user = user
            participant.save()
        return participant

    def _meter(self, meter_id, meter_type, holder, mode=AllocationMode.PERSONAL):
        mp = MeteringPoint.objects.create(zev=self.zev, meter_id=meter_id, meter_type=meter_type)
        MeteringPointAssignment.objects.create(
            metering_point=mp, participant=holder, valid_from=date(2026, 1, 1), allocation_mode=mode,
        )
        return mp

    @staticmethod
    def reading(mp, ts, kwh, direction=ReadingDirection.IN):
        return MeterReading.objects.create(
            metering_point=mp, timestamp=ts, energy_kwh=Decimal(kwh), direction=direction,
        )


def enable_tokens():
    FeatureFlag.objects.update_or_create(
        name=FeatureFlag.ANALYTICS_TOKENS_ENABLED, defaults={"enabled": True, "follows_default": False},
    )
