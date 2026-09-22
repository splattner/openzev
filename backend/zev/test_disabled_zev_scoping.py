"""Cutting off access to the data *underneath* a disabled ZEV — the second
half of ZEV lifecycle phase 2 (the state and its disable/enable actions
landed first, without this).

Three layers, each covered by its own class:

- Creating a new row into a disabled ZEV (``assert_within_scope``, the
  create-time counterpart of the object-permission check below — DRF never
  consults object permissions on POST).
- Writing to an existing row under a disabled ZEV (``has_object_permission``
  on ``BaseZevScopedPermission``): read-only for the owner, blocked entirely
  for a participant, open for an admin.
- Reading rows under a disabled ZEV as a participant (``_scope_by_role`` /
  ``_exclude_disabled_zev``): invisible, not merely read-only — the same as a
  ZEV the participant was never part of.

Deliberately not covered here, and not yet fixed: Tariff/TariffPeriod/
Invoice/MeterReading use ``IsZevOwnerOrAdmin``, which has no
``has_object_permission``, so an owner can still PATCH/DELETE an *existing*
row of those models under their own disabled ZEV. Only creating new ones is
blocked for those four (assert_within_scope covers every model with a
``scope_parent_path``). See the comment above
``BaseZevScopedPermission.has_object_permission``.
"""
from datetime import date

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.test_helpers import make_invoice
from metering.models import MeterReading
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory, TariffPeriod
from testing.helpers import authenticate as auth, make_user
from zev.models import (
    MeteringPoint,
    MeteringPointAssignment,
    MeteringPointType,
    Participant,
    Zev,
)

PARTICIPANTS = "/api/v1/zev/participants/"
METERING_POINTS = "/api/v1/zev/metering-points/"
ASSIGNMENTS = "/api/v1/zev/metering-point-assignments/"
TARIFFS = "/api/v1/tariffs/tariffs/"
TARIFF_PERIODS = "/api/v1/tariffs/periods/"
READINGS = "/api/v1/metering/readings/"
INVOICES = "/api/v1/invoices/invoices/"


class _OwnerAndParticipant(TestCase):
    """One ZEV, its owner, an admin, and one participant fully wired up:
    a metering point, an assignment, a tariff, a reading, and an invoice."""

    def setUp(self):
        self.owner = make_user("dz_owner", UserRole.ZEV_OWNER)
        self.admin = make_user("dz_admin", UserRole.ADMIN)
        self.zev = Zev.objects.create(name="Disable-scoping ZEV", owner=self.owner)

        self.participant_user = make_user("dz_participant", UserRole.PARTICIPANT)
        self.participant = Participant.objects.create(
            zev=self.zev, user=self.participant_user, first_name="Paula", last_name="Participant",
            email="paula@example.com", valid_from=date(2026, 1, 1),
        )
        self.meter = MeteringPoint.objects.create(
            zev=self.zev, meter_id="DZ-METER", meter_type=MeteringPointType.CONSUMPTION,
        )
        self.assignment = MeteringPointAssignment.objects.create(
            metering_point=self.meter, participant=self.participant, valid_from=date(2026, 1, 1),
        )
        self.tariff = Tariff.objects.create(
            zev=self.zev, name="DZ Tariff", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.LOCAL,
            valid_from=date(2026, 1, 1),
        )
        self.reading = MeterReading.objects.create(
            metering_point=self.meter, timestamp="2026-01-15T12:00:00Z", energy_kwh="1.5000",
        )
        self.invoice = make_invoice(self.zev, self.participant)

        self.owner_client = APIClient()
        auth(self.owner_client, self.owner)
        self.admin_client = APIClient()
        auth(self.admin_client, self.admin)
        self.participant_client = APIClient()
        auth(self.participant_client, self.participant_user)

    def _disable(self):
        self.zev.disabled_at = timezone.now()
        self.zev.disabled_by = self.owner
        self.zev.save()


class CreateIntoDisabledZevTests(_OwnerAndParticipant):
    """assert_within_scope's disabled-ZEV rule — create-time, every model
    with a scope_parent_path."""

    def setUp(self):
        super().setUp()
        self._disable()

    def assertRefused(self, response, field):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(field, response.json())
        self.assertIn("disabled", str(response.json()[field]).lower())

    def test_owner_cannot_create_a_participant(self):
        response = self.owner_client.post(PARTICIPANTS, {
            "zev": str(self.zev.id), "first_name": "New", "last_name": "Member",
            "email": "new@example.com", "valid_from": "2026-01-01",
        }, format="json")
        self.assertRefused(response, "zev")

    def test_admin_can_still_create_a_participant(self):
        response = self.admin_client.post(PARTICIPANTS, {
            "zev": str(self.zev.id), "first_name": "New", "last_name": "Member",
            "email": "new-admin@example.com", "valid_from": "2026-01-01",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)

    def test_owner_cannot_create_a_metering_point(self):
        response = self.owner_client.post(METERING_POINTS, {
            "zev": str(self.zev.id), "meter_id": "NEW-METER", "meter_type": "consumption",
        }, format="json")
        self.assertRefused(response, "zev")

    def test_owner_cannot_create_an_assignment(self):
        other_meter = MeteringPoint.objects.create(
            zev=self.zev, meter_id="DZ-METER-2", meter_type=MeteringPointType.CONSUMPTION,
        )
        response = self.owner_client.post(ASSIGNMENTS, {
            "metering_point": str(other_meter.id), "participant": str(self.participant.id),
            "valid_from": "2026-01-01",
        }, format="json")
        self.assertRefused(response, "metering_point")

    def test_owner_cannot_create_a_tariff(self):
        response = self.owner_client.post(TARIFFS, {
            "zev": str(self.zev.id), "name": "New Tariff", "category": "energy",
            "billing_mode": "energy", "energy_type": "local", "valid_from": "2026-01-01",
        }, format="json")
        self.assertRefused(response, "zev")

    def test_owner_cannot_create_a_tariff_period(self):
        response = self.owner_client.post(TARIFF_PERIODS, {
            "tariff": str(self.tariff.id), "period_type": "flat", "price_chf_per_kwh": "0.20",
        }, format="json")
        self.assertRefused(response, "tariff")
        self.assertFalse(TariffPeriod.objects.filter(tariff=self.tariff).exists())

    def test_owner_cannot_create_a_reading(self):
        response = self.owner_client.post(READINGS, {
            "metering_point": str(self.meter.id),
            "timestamp": "2026-01-16T00:00:00Z", "energy_kwh": "1.0", "direction": "in",
        }, format="json")
        self.assertRefused(response, "metering_point")


class WriteExistingRowInDisabledZevTests(_OwnerAndParticipant):
    """has_object_permission's disabled-ZEV rule — PATCH/DELETE on rows
    already there, for the models governed by BaseZevScopedPermission."""

    def setUp(self):
        super().setUp()
        self._disable()

    def test_owner_cannot_patch_participant(self):
        response = self.owner_client.patch(
            f"{PARTICIPANTS}{self.participant.id}/", {"first_name": "Renamed"}, format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)

    def test_admin_can_still_patch_participant(self):
        response = self.admin_client.patch(
            f"{PARTICIPANTS}{self.participant.id}/", {"first_name": "Renamed"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_owner_cannot_delete_participant(self):
        response = self.owner_client.delete(f"{PARTICIPANTS}{self.participant.id}/")
        self.assertEqual(response.status_code, 403, response.content)
        self.assertTrue(Participant.objects.filter(pk=self.participant.pk).exists())

    def test_owner_cannot_patch_metering_point(self):
        response = self.owner_client.patch(
            f"{METERING_POINTS}{self.meter.id}/", {"location_description": "Cellar"}, format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)

    def test_owner_cannot_patch_assignment(self):
        response = self.owner_client.patch(
            f"{ASSIGNMENTS}{self.assignment.id}/", {"valid_to": "2026-06-30"}, format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)

    def test_owner_read_access_to_these_rows_is_unaffected(self):
        """The write block must not have become a read block too."""
        for url in (
            f"{PARTICIPANTS}{self.participant.id}/",
            f"{METERING_POINTS}{self.meter.id}/",
            f"{ASSIGNMENTS}{self.assignment.id}/",
        ):
            self.assertEqual(self.owner_client.get(url).status_code, 200, url)


class ParticipantReadCutoffTests(_OwnerAndParticipant):
    """A disabled ZEV is invisible to its participants, not merely read-only
    the way it is to its owner."""

    def setUp(self):
        super().setUp()
        self._disable()

    # ParticipantViewSet and MeteringPointAssignmentViewSet are not covered
    # here: a participant already gets 403 from every method on those two,
    # in every ZEV state, matching the RBAC matrix in
    # 2026-03-community-and-access.md §12.1 — there is nothing for a
    # disabled-ZEV rule to change on an endpoint they never reach. The two
    # that a participant genuinely does read from (metering points, per
    # MeteringPointPermission.allow_participant_safe_methods, and invoices)
    # are what this class covers.

    def test_participant_no_longer_sees_their_metering_point(self):
        response = self.participant_client.get(f"{METERING_POINTS}{self.meter.id}/")
        self.assertEqual(response.status_code, 404, response.content)

    def test_participant_no_longer_sees_their_invoice(self):
        list_resp = self.participant_client.get(INVOICES)
        self.assertEqual(list_resp.status_code, 200, list_resp.content)
        ids = [row["id"] for row in list_resp.json().get("results", list_resp.json())]
        self.assertNotIn(str(self.invoice.id), ids)

    def test_participant_no_longer_sees_their_reading(self):
        """Readings reach a participant through raw-data, not the plain CRUD
        list (IsZevOwnerOrAdmin keeps that 403 for a participant in every ZEV
        state) — raw-data overrides to IsAuthenticated and reads through the
        same get_queryset() this class's other cases exercise."""
        response = self.participant_client.get(
            "/api/v1/metering/readings/raw-data/",
            {"metering_point": str(self.meter.id), "date": "2026-01-15"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), [])

    def test_owner_still_sees_all_of_it(self):
        """The participant cutoff must not have taken the owner's read
        access down with it."""
        self.assertEqual(self.owner_client.get(f"{PARTICIPANTS}{self.participant.id}/").status_code, 200)
        self.assertEqual(self.owner_client.get(f"{METERING_POINTS}{self.meter.id}/").status_code, 200)
        self.assertIn(
            str(self.invoice.id),
            [row["id"] for row in self.owner_client.get(INVOICES).json().get("results", [])],
        )
        self.assertIn(
            str(self.reading.id),
            [row["id"] for row in self.owner_client.get(READINGS).json().get("results", [])],
        )


class ReEnabledZevRestoresAccessTests(_OwnerAndParticipant):
    """Enable is a full reversal, not a one-way door."""

    def test_participant_regains_access_after_enable(self):
        self._disable()
        self.assertEqual(
            self.participant_client.get(f"{METERING_POINTS}{self.meter.id}/").status_code, 404,
        )

        self.zev.disabled_at = None
        self.zev.disabled_by = None
        self.zev.save()

        self.assertEqual(
            self.participant_client.get(f"{METERING_POINTS}{self.meter.id}/").status_code, 200,
        )

    def test_owner_write_access_returns_after_enable(self):
        self._disable()
        self.zev.disabled_at = None
        self.zev.save()

        response = self.owner_client.patch(
            f"{PARTICIPANTS}{self.participant.id}/", {"first_name": "Renamed"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
