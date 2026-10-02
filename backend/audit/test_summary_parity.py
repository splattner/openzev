"""Pin the audit summary/target_display strings produced by the audit mixins.

These strings were previously built inline in each viewset's
perform_create/perform_update/perform_destroy. They are user-visible in the
audit log, so they must not drift when the audit plumbing is refactored.
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
        self.owner = make_user("parity_owner", UserRole.USER)
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
        target = make_user("parity_target", UserRole.USER)
        auth(self.client, self.admin)
        resp = self.client.patch(
            f"/api/v1/auth/users/{target.id}/", {"first_name": "Renamed"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        target.refresh_from_db()
        event = self._latest("user.update", target.id)
        self.assertEqual(event.summary, f"Updated user {target.email}.")
        self.assertEqual(event.target_display, target.email)

    @mock.patch("zev.tasks.warm_participant_geocode_cache_task.delay")
    def test_participant_create_summary(self, _geocode):
        auth(self.client, self.admin)
        resp = self.client.post(
            "/api/v1/zev/participants/",
            {
                "zev": str(self.zev.id),
                "first_name": "New",
                "last_name": "Member",
                "email": "newmember@example.com",
                "valid_from": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        participant = Participant.objects.get(id=resp.data["id"])
        event = self._latest("participant.create", participant.id)
        self.assertEqual(event.summary, f"Created participant {participant.full_name}.")
        self.assertEqual(event.target_display, participant.full_name)
        self.assertEqual(event.metadata_json, {"zev_id": str(self.zev.id)})

    def test_participant_destroy_summary(self):
        auth(self.client, self.admin)
        participant_id = self.participant.id
        full_name = self.participant.full_name
        resp = self.client.delete(f"/api/v1/zev/participants/{participant_id}/")
        self.assertEqual(resp.status_code, 204, resp.content)
        event = self._latest("participant.delete", participant_id)
        self.assertEqual(event.summary, f"Deleted participant {full_name}.")
        self.assertEqual(event.target_display, full_name)
        self.assertEqual(event.metadata_json, {"zev_id": str(self.zev.id)})

    def test_metering_point_create_summary(self):
        auth(self.client, self.admin)
        resp = self.client.post(
            "/api/v1/zev/metering-points/",
            {
                "zev": str(self.zev.id),
                "meter_id": "CH9990000000000000000000000000020",
                "meter_type": MeteringPointType.CONSUMPTION,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        point = MeteringPoint.objects.get(id=resp.data["id"])
        event = self._latest("metering_point.create", point.id)
        self.assertEqual(event.summary, f"Created metering point {point.meter_id}.")
        self.assertEqual(event.target_display, point.meter_id)
        self.assertEqual(
            event.metadata_json,
            {"zev_id": str(self.zev.id), "meter_type": point.meter_type},
        )

    def test_metering_point_destroy_summary(self):
        auth(self.client, self.admin)
        point_id = self.metering_point.id
        meter_id = self.metering_point.meter_id
        resp = self.client.delete(f"/api/v1/zev/metering-points/{point_id}/")
        self.assertEqual(resp.status_code, 204, resp.content)
        event = self._latest("metering_point.delete", point_id)
        self.assertEqual(event.summary, f"Deleted metering point {meter_id}.")
        self.assertEqual(event.target_display, meter_id)
        self.assertEqual(event.metadata_json, {"zev_id": str(self.zev.id)})

    def test_metering_assignment_create_summary(self):
        point = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH9990000000000000000000000000030",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        auth(self.client, self.admin)
        resp = self.client.post(
            "/api/v1/zev/metering-point-assignments/",
            {
                "metering_point": str(point.id),
                "participant": str(self.participant.id),
                "valid_from": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        assignment = MeteringPointAssignment.objects.get(id=resp.data["id"])
        event = self._latest("metering_assignment.create", assignment.id)
        self.assertEqual(
            event.summary,
            f"Created metering point assignment for {point.meter_id}.",
        )
        self.assertEqual(event.target_display, str(assignment.pk))
        self.assertEqual(
            event.metadata_json,
            {
                "metering_point_id": str(point.id),
                "participant_id": str(self.participant.id),
            },
        )

    def test_metering_assignment_destroy_summary(self):
        auth(self.client, self.admin)
        assignment_id = self.assignment.id
        meter_id = self.metering_point.meter_id
        participant_id = str(self.participant.id)
        resp = self.client.delete(f"/api/v1/zev/metering-point-assignments/{assignment_id}/")
        self.assertEqual(resp.status_code, 204, resp.content)
        event = self._latest("metering_assignment.delete", assignment_id)
        self.assertEqual(event.summary, f"Deleted metering point assignment for {meter_id}.")
        self.assertEqual(event.target_display, str(assignment_id))
        self.assertEqual(event.metadata_json, {"participant_id": participant_id})
