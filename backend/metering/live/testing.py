"""Shared fixtures for the live energy tests (not collected by pytest).

A physical ZEV: a PV production point that the ZEV operates, two flats that each have a household
participant, a manager, a viewer, a participant without any live source and an outsider.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import FeatureFlag, UserRole
from metering.live import store
from metering.models import SourceHolder, SourceTarget, SupplementarySource
from testing import factories
from testing.helpers import authenticate, make_user
from zev.models import MeteringPointType, ZevAccessGrant, ZevAccessRole, ZevType

LIVE = "/api/v1/metering/live/"
INGEST_URL = LIVE + "ingest/"
ME_URL = LIVE + "me/"
VALID_FROM = date(2025, 1, 1)


def enable_live(enabled: bool = True) -> None:
    for name in (FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED, FeatureFlag.LIVE_ENERGY_DATA_ENABLED):
        FeatureFlag.objects.update_or_create(name=name, defaults={"enabled": enabled})


def client_for(user) -> APIClient:
    client = APIClient()
    if user is not None:
        authenticate(client, user)
    return client


def snapshot_url(zev) -> str:
    return f"{LIVE}zevs/{zev.pk}/"


def curve_url(zev) -> str:
    return f"{LIVE}zevs/{zev.pk}/curve/"


class LiveTestCase(TestCase):
    zev_type = ZevType.ZEV

    def setUp(self):
        cache.clear()
        enable_live()
        self.now = datetime.now(dt_timezone.utc).replace(microsecond=0)
        self.admin = make_user("live_admin", UserRole.ADMIN)
        self.manager = make_user("live_manager", UserRole.USER)
        self.viewer = make_user("live_viewer", UserRole.USER)
        self.user1 = make_user("live_user1", UserRole.USER)
        self.user2 = make_user("live_user2", UserRole.USER)
        self.quiet_user = make_user("live_quiet", UserRole.USER)
        self.outsider = make_user("live_outsider", UserRole.USER)

        self.zev = factories.ZevFactory(owner=self.manager, zev_type=self.zev_type)
        ZevAccessGrant.objects.create(zev=self.zev, user=self.viewer, role=ZevAccessRole.VIEWER)

        self.p1 = factories.ParticipantFactory(zev=self.zev, user=self.user1, valid_from=VALID_FROM)
        self.p2 = factories.ParticipantFactory(zev=self.zev, user=self.user2, valid_from=VALID_FROM)
        self.quiet = factories.ParticipantFactory(zev=self.zev, user=self.quiet_user, valid_from=VALID_FROM)

        self.pv = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.PRODUCTION)
        self.flat1 = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)
        self.flat2 = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)
        self.flat3 = factories.MeteringPointFactory(zev=self.zev, meter_type=MeteringPointType.CONSUMPTION)
        for point, participant in ((self.flat1, self.p1), (self.flat2, self.p2), (self.flat3, self.quiet)):
            factories.MeteringPointAssignmentFactory(
                metering_point=point, participant=participant, valid_from=VALID_FROM
            )

    # -- sources and samples ---------------------------------------------------------------------

    def live_source(self, point=None, *, participant=None, **extra) -> SupplementarySource:
        """A live-only push source. A point nobody holds personally gets a ZEV-held one."""
        if point is None:
            fields = dict(zev=self.zev, target=SourceTarget.CONNECTION_POINT, held_by=SourceHolder.ZEV)
        else:
            fields = dict(zev=point.zev, metering_point=point)
            if participant is not None:
                fields.update(held_by=SourceHolder.PARTICIPANT, participant=participant)
            else:
                fields.update(held_by=SourceHolder.ZEV)
        fields.update(provider="push", provides_history=False, provides_live=True, **extra)
        return SupplementarySource.objects.create(**fields)

    def sample(self, source, meter_power_w, *, age=5, now=None, production_w=None, consumption_w=None):
        """Store a sample ``age`` seconds before ``now`` and return its source."""
        now = now or self.now
        moment = now - timedelta(seconds=age)
        store.put_sample(
            store.LiveSample(
                source_id=str(source.pk),
                timestamp=moment,
                received_at=moment,
                meter_power_w=Decimal(str(meter_power_w)),
                production_w=None if production_w is None else Decimal(str(production_w)),
                consumption_w=None if consumption_w is None else Decimal(str(consumption_w)),
            )
        )
        return source

    def wire(self, *, pv=-8000, flat1=None, flat2=None, flat3=None, connection=None):
        """Sources with a fresh sample for every value that is not ``None``. Returns the sources by name."""
        sources = {}
        for name, point, value, holder in (
            ("pv", self.pv, pv, None),
            ("flat1", self.flat1, flat1, self.p1),
            ("flat2", self.flat2, flat2, self.p2),
            ("flat3", self.flat3, flat3, self.quiet),
        ):
            if value is not None:
                sources[name] = self.sample(self.live_source(point, participant=holder), value)
        if connection is not None:
            sources["connection"] = self.sample(self.live_source(), connection)
        return sources
