"""Tenant isolation on writes: a ZEV owner may only write into their own ZEV.

Scoping the queryset protects what a caller can *see*. It does not protect what
they can *write*: DRF consults ``has_object_permission`` on detail routes but
never on create, so before #424 a payload naming another community's ZEV was
accepted on every ZEV-scoped endpoint — and an owner could also move one of
their own objects into someone else's community with a PATCH.

The failure mode is "returns 201 when it should not", which an assertion on a
successful create can never catch, so each case asserts the rejection *and*
that nothing landed in the victim's ZEV.
"""

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
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


class _TwoCommunities(TestCase):
    """One victim community and one attacker community, each with an owner."""

    def setUp(self):
        self.victim = make_user("ws_victim", UserRole.ZEV_OWNER)
        self.attacker = make_user("ws_attacker", UserRole.ZEV_OWNER)
        self.admin = make_user("ws_admin", UserRole.ADMIN)

        self.victim_zev = Zev.objects.create(name="Victim ZEV", owner=self.victim)
        self.attacker_zev = Zev.objects.create(name="Attacker ZEV", owner=self.attacker)

        self.victim_participant = Participant.objects.create(
            zev=self.victim_zev, first_name="Vera", last_name="Victim",
            email="vera@example.com", valid_from=date(2026, 1, 1),
        )
        self.victim_meter = MeteringPoint.objects.create(
            zev=self.victim_zev, meter_id="VICTIM-METER",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        self.victim_tariff = self._tariff(self.victim_zev, "Victim Tariff")

        self.attacker_participant = Participant.objects.create(
            zev=self.attacker_zev, first_name="Alan", last_name="Attacker",
            email="alan@example.com", valid_from=date(2026, 1, 1),
        )
        self.attacker_meter = MeteringPoint.objects.create(
            zev=self.attacker_zev, meter_id="ATTACKER-METER",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        self.attacker_tariff = self._tariff(self.attacker_zev, "Attacker Tariff")

        self.client = APIClient()
        auth(self.client, self.attacker)

    def _tariff(self, zev, name):
        return Tariff.objects.create(
            zev=zev, name=name, category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.LOCAL,
            valid_from=date(2026, 1, 1),
        )

    def assertRefused(self, response, field):
        """A 400 naming the offending relation, not a silent success."""
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(field, response.json())


class CreateIntoAnotherCommunityTests(_TwoCommunities):
    def test_participant(self):
        response = self.client.post(PARTICIPANTS, {
            "zev": str(self.victim_zev.id), "first_name": "Injected",
            "last_name": "Person", "email": "injected@example.com",
            "valid_from": "2026-01-01",
        }, format="json")
        self.assertRefused(response, "zev")
        self.assertEqual(self.victim_zev.participants.count(), 1)

    def test_participant_creates_no_account(self):
        """``ParticipantSerializer.create`` provisions a login, so a refused
        create must not leave a usable account behind."""
        from accounts.models import User

        before = User.objects.count()
        self.client.post(PARTICIPANTS, {
            "zev": str(self.victim_zev.id), "first_name": "Injected",
            "last_name": "Person", "email": "injected@example.com",
            "valid_from": "2026-01-01",
        }, format="json")
        self.assertEqual(User.objects.count(), before)

    def test_metering_point(self):
        response = self.client.post(METERING_POINTS, {
            "zev": str(self.victim_zev.id), "meter_id": "INJECTED-METER",
            "meter_type": "consumption",
        }, format="json")
        self.assertRefused(response, "zev")
        self.assertFalse(MeteringPoint.objects.filter(meter_id="INJECTED-METER").exists())

    def test_metering_point_assignment(self):
        response = self.client.post(ASSIGNMENTS, {
            "metering_point": str(self.victim_meter.id),
            "participant": str(self.victim_participant.id),
            "valid_from": "2026-01-01",
        }, format="json")
        self.assertRefused(response, "metering_point")
        self.assertFalse(
            MeteringPointAssignment.objects.filter(metering_point=self.victim_meter).exists()
        )

    def test_tariff(self):
        response = self.client.post(TARIFFS, {
            "zev": str(self.victim_zev.id), "name": "Injected Tariff",
            "category": "energy", "billing_mode": "energy", "energy_type": "local",
            "valid_from": "2026-01-01",
        }, format="json")
        self.assertRefused(response, "zev")
        self.assertEqual(self.victim_zev.tariffs.count(), 1)

    def test_tariff_period(self):
        response = self.client.post(TARIFF_PERIODS, {
            "tariff": str(self.victim_tariff.id), "period_type": "flat",
            "price_chf_per_kwh": "0.20",
        }, format="json")
        self.assertRefused(response, "tariff")
        self.assertFalse(TariffPeriod.objects.filter(tariff=self.victim_tariff).exists())

    def test_meter_reading(self):
        response = self.client.post(READINGS, {
            "metering_point": str(self.victim_meter.id),
            "timestamp": "2026-01-01T00:00:00Z", "energy_kwh": "1.0", "direction": "in",
        }, format="json")
        self.assertRefused(response, "metering_point")
        self.assertFalse(MeterReading.objects.filter(metering_point=self.victim_meter).exists())


class MoveIntoAnotherCommunityTests(_TwoCommunities):
    """The other direction: donating one of your own objects to a stranger.

    ``get_object()`` already stops an owner editing somebody else's row, but
    nothing stopped them rewriting their *own* row's ZEV to point elsewhere.
    """

    def test_participant(self):
        response = self.client.patch(
            f"{PARTICIPANTS}{self.attacker_participant.id}/",
            {"zev": str(self.victim_zev.id)}, format="json",
        )
        self.assertRefused(response, "zev")
        self.attacker_participant.refresh_from_db()
        self.assertEqual(self.attacker_participant.zev, self.attacker_zev)

    def test_metering_point(self):
        response = self.client.patch(
            f"{METERING_POINTS}{self.attacker_meter.id}/",
            {"zev": str(self.victim_zev.id)}, format="json",
        )
        self.assertRefused(response, "zev")
        self.attacker_meter.refresh_from_db()
        self.assertEqual(self.attacker_meter.zev, self.attacker_zev)

    def test_tariff(self):
        response = self.client.patch(
            f"{TARIFFS}{self.attacker_tariff.id}/",
            {"zev": str(self.victim_zev.id)}, format="json",
        )
        self.assertRefused(response, "zev")
        self.attacker_tariff.refresh_from_db()
        self.assertEqual(self.attacker_tariff.zev, self.attacker_zev)


class LegitimateWritesStillWorkTests(_TwoCommunities):
    """The guard must not cost an owner the use of their own community."""

    def test_owner_can_create_in_their_own_zev(self):
        response = self.client.post(PARTICIPANTS, {
            "zev": str(self.attacker_zev.id), "first_name": "Legit",
            "last_name": "Member", "email": "legit@example.com",
            "valid_from": "2026-01-01",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)

    def test_owner_can_patch_their_own_object_without_naming_the_zev(self):
        response = self.client.patch(
            f"{PARTICIPANTS}{self.attacker_participant.id}/",
            {"city": "Zurich"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.attacker_participant.refresh_from_db()
        self.assertEqual(self.attacker_participant.city, "Zurich")

    def test_owner_can_restate_their_own_zev_on_patch(self):
        """A full PUT-style payload repeats ``zev``; that is not a move."""
        response = self.client.patch(
            f"{PARTICIPANTS}{self.attacker_participant.id}/",
            {"zev": str(self.attacker_zev.id), "city": "Bern"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_owner_can_assign_their_own_meter_to_their_own_participant(self):
        response = self.client.post(ASSIGNMENTS, {
            "metering_point": str(self.attacker_meter.id),
            "participant": str(self.attacker_participant.id),
            "valid_from": "2026-01-01",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)

    def test_admin_may_write_into_any_community(self):
        admin_client = APIClient()
        auth(admin_client, self.admin)
        response = admin_client.post(PARTICIPANTS, {
            "zev": str(self.victim_zev.id), "first_name": "Admin",
            "last_name": "Added", "email": "adminadded@example.com",
            "valid_from": "2026-01-01",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.victim_zev.participants.count(), 2)


class AuditTrailStillRecordedTests(_TwoCommunities):
    """``AuditedUpdateMixin`` now saves through ``super()``; the diff it records
    must survive that change."""

    def test_update_still_records_a_diff(self):
        from audit.models import AuditEvent

        self.client.patch(
            f"{PARTICIPANTS}{self.attacker_participant.id}/",
            {"city": "Winterthur"}, format="json",
        )
        event = AuditEvent.objects.filter(action_type="participant.update").latest("created_at")
        self.assertEqual(event.changes_json["city"]["after"], "Winterthur")

    def test_create_still_records_an_event(self):
        from audit.models import AuditEvent

        self.client.post(PARTICIPANTS, {
            "zev": str(self.attacker_zev.id), "first_name": "Audited",
            "last_name": "Member", "email": "audited@example.com",
            "valid_from": "2026-01-01",
        }, format="json")
        self.assertTrue(
            AuditEvent.objects.filter(
                action_type="participant.create", target_display__icontains="Audited"
            ).exists()
        )
