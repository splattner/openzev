"""Shared fixtures for the supplementary-data API tests (not collected by pytest)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone

from cryptography.fernet import Fernet
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import FeatureFlag, UserRole
from testing import factories
from testing.helpers import authenticate, make_user
from zev.models import MeteringPointType, ZevAccessGrant, ZevAccessRole

INTEGRATION_KEY = Fernet.generate_key().decode()
SOURCES_URL = "/api/v1/metering/supplementary/sources/"
INGEST_URL = "/api/v1/metering/supplementary/ingest/"


def enable_feature(enabled: bool = True) -> None:
    FeatureFlag.objects.update_or_create(
        name=FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED, defaults={"enabled": enabled}
    )


def client_for(user) -> APIClient:
    client = APIClient()
    if user is not None:
        authenticate(client, user)
    return client


def quarter_hours(count: int, *, end: datetime | None = None, step_back: int = 0):
    """``count`` aligned 15-minute interval starts, the last one a few hours in the past."""
    end = (end or datetime.now(dt_timezone.utc)).replace(second=0, microsecond=0, minute=0) - timedelta(hours=3)
    start = end - timedelta(minutes=15 * (count + step_back))
    return [start + timedelta(minutes=15 * i) for i in range(count)]


def reading_payload(ts: datetime, **overrides) -> dict:
    row = {
        "timestamp": ts.isoformat(),
        "consumption_kwh": "0.4",
        "production_kwh": "1.2",
        "import_kwh": "0.1",
        "export_kwh": "0.9",
    }
    row.update(overrides)
    return row


class SupplementaryApiTestCase(TestCase):
    """A ZEV with a manager, a viewer, a participant holding a flagged meter, and a stranger."""

    def setUp(self):
        enable_feature()
        self.admin = make_user("sup_admin", UserRole.ADMIN)
        self.manager = make_user("sup_manager", UserRole.USER)
        self.viewer = make_user("sup_viewer", UserRole.USER)
        self.holder_user = make_user("sup_holder", UserRole.USER)
        self.other_user = make_user("sup_other", UserRole.USER)
        self.stranger = make_user("sup_stranger", UserRole.USER)

        self.zev = factories.ZevFactory(owner=self.manager)
        ZevAccessGrant.objects.create(zev=self.zev, user=self.viewer, role=ZevAccessRole.VIEWER)

        self.holder = factories.ParticipantFactory(zev=self.zev, user=self.holder_user, valid_from=date(2025, 1, 1))
        self.other = factories.ParticipantFactory(zev=self.zev, user=self.other_user, valid_from=date(2025, 1, 1))
        self.point = factories.MeteringPointFactory(
            zev=self.zev, meter_type=MeteringPointType.BIDIRECTIONAL, has_behind_meter_generation=True
        )
        self.assignment = factories.MeteringPointAssignmentFactory(
            metering_point=self.point, participant=self.holder, valid_from=date(2025, 1, 1)
        )

    def create_push_source(self, *, as_user=None, point=None, **extra):
        payload = {
            "metering_point": str((point or self.point).pk),
            "provider": "push",
            "label": "Home Assistant",
            "consent": True,
            **extra,
        }
        return client_for(as_user or self.holder_user).post(SOURCES_URL, payload, format="json")
