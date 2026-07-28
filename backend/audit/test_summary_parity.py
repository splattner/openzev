"""Pin the audit summary/target_display strings produced by AuditedUpdateMixin.

These strings were previously built inline in each viewset's perform_update.
They are user-visible in the audit log, so they must not drift when the
snapshot/diff plumbing is refactored.
"""
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent
from tariffs.models import BillingMode, Tariff, TariffCategory
from testing.helpers import authenticate as auth, make_user
from zev.models import (
    MeteringPoint,
    MeteringPointAssignment,
    MeteringPointType,
    Participant,
    Zev,
)


class AuditSummaryParityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("parity_admin", UserRole.ADMIN)
        self.owner = make_user("parity_owner", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(name="Parity ZEV", owner=self.owner)
        self.participant = Participant.objects.create(
            zev=self.zev,
            first_name="Par",
            last_name="Ity",
            email="parity@example.com",
            valid_from=timezone.localdate(),
        )
        self.metering_point = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH9990000000000000000000000000010",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        self.assignment = MeteringPointAssignment.objects.create(
            metering_point=self.metering_point,
            participant=self.participant,
            valid_from=timezone.localdate(),
        )

    def _latest(self, action_type, target_id):
        return AuditEvent.objects.filter(action_type=action_type, target_id=str(target_id)).latest("created_at")

    @mock.patch("zev.tasks.warm_participant_geocode_cache_task.delay")
    def test_participant_update_summary(self, _geocode):
        auth(self.client, self.admin)
        resp = self.client.patch(
            f"/api/v1/zev/participants/{self.participant.id}/", {"city": "Bern"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.participant.refresh_from_db()
        event = self._latest("participant.update", self.participant.id)
        self.assertEqual(event.summary, f"Updated participant {self.participant.full_name}.")
        self.assertEqual(event.target_display, self.participant.full_name)

    def test_metering_point_update_summary(self):
        auth(self.client, self.admin)
        resp = self.client.patch(
            f"/api/v1/zev/metering-points/{self.metering_point.id}/",
            {"location_description": "Attic"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        event = self._latest("metering_point.update", self.metering_point.id)
        self.assertEqual(event.summary, f"Updated metering point {self.metering_point.meter_id}.")
        self.assertEqual(event.target_display, self.metering_point.meter_id)

    def test_metering_assignment_update_summary(self):
        auth(self.client, self.admin)
        resp = self.client.patch(
            f"/api/v1/zev/metering-point-assignments/{self.assignment.id}/",
            {"valid_to": timezone.localdate().isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        event = self._latest("metering_assignment.update", self.assignment.id)
        self.assertEqual(
            event.summary,
            f"Updated metering point assignment for {self.metering_point.meter_id}.",
        )
        self.assertEqual(event.target_display, str(self.assignment.pk))

    def test_tariff_update_summary(self):
        tariff = Tariff.objects.create(
            zev=self.zev,
            name="Parity Tariff",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type="grid",
            valid_from=timezone.localdate(),
        )
        auth(self.client, self.owner)
        resp = self.client.patch(
            f"/api/v1/tariffs/tariffs/{tariff.id}/", {"name": "Parity Renamed"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        event = self._latest("tariff.update", tariff.id)
        self.assertEqual(event.summary, "Updated tariff Parity Renamed.")
        self.assertEqual(event.target_display, "Parity Renamed")

    def test_tariff_period_update_summary(self):
        tariff = Tariff.objects.create(
            zev=self.zev,
            name="Parity Period Tariff",
            category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY,
            energy_type="local",
            valid_from=timezone.localdate(),
        )
        period = tariff.periods.create(period_type="flat", price_chf_per_kwh="0.10000")
        auth(self.client, self.owner)
        resp = self.client.patch(
            f"/api/v1/tariffs/periods/{period.id}/", {"price_chf_per_kwh": "0.11000"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        event = self._latest("tariff_period.update", period.id)
        self.assertEqual(event.summary, f"Updated tariff period flat for tariff {tariff.name}.")
        self.assertEqual(event.target_display, "flat")

    def test_user_update_summary(self):
        target = make_user("parity_target", UserRole.PARTICIPANT)
        auth(self.client, self.admin)
        resp = self.client.patch(
            f"/api/v1/auth/users/{target.id}/", {"first_name": "Renamed"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        target.refresh_from_db()
        event = self._latest("user.update", target.id)
        self.assertEqual(event.summary, f"Updated user {target.email}.")
        self.assertEqual(event.target_display, target.email)
