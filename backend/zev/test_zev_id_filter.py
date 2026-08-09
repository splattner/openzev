"""``?zev_id=`` on the ZEV-scoped list endpoints.

Every one of these accepted the parameter and ignored it, answering 200 with
every ZEV the caller could see (#411) — while the custom actions beside them
honoured it, so a caller had every reason to assume it worked. The sharp case
was ``/metering/readings/?zev_id=X``, which returned the whole instance's
readings to an admin and looked scoped.

The failure mode is *returning too much*, so an assertion on a non-empty result
proves nothing. Each case pins the exact set, and every endpoint is checked
against a ZEV that exists but is not the one asked for.
"""

from datetime import date, datetime, timezone

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import Invoice, InvoiceStatus
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
READINGS = "/api/v1/metering/readings/"
INVOICES = "/api/v1/invoices/invoices/"
ZEVS = "/api/v1/zev/zevs/"


def _rows(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


class _TwoPopulatedCommunities(TestCase):
    """Two complete communities, so an unfiltered list is never a subset of one."""

    def setUp(self):
        self.admin = make_user("zf_admin", UserRole.ADMIN)
        self.owner_a = make_user("zf_owner_a", UserRole.ZEV_OWNER)
        self.owner_b = make_user("zf_owner_b", UserRole.ZEV_OWNER)
        self.zev_a = Zev.objects.create(name="Community A", owner=self.owner_a, invoice_prefix="AAA")
        self.zev_b = Zev.objects.create(name="Community B", owner=self.owner_b, invoice_prefix="BBB")

        for zev, tag in ((self.zev_a, "A"), (self.zev_b, "B")):
            participant = Participant.objects.create(
                zev=zev, first_name=tag, last_name="Member",
                email=f"{tag.lower()}@example.com", valid_from=date(2026, 1, 1),
            )
            meter = MeteringPoint.objects.create(
                zev=zev, meter_id=f"{tag}-METER", meter_type=MeteringPointType.CONSUMPTION,
            )
            MeteringPointAssignment.objects.create(
                metering_point=meter, participant=participant, valid_from=date(2026, 1, 1),
            )
            MeterReading.objects.create(
                metering_point=meter, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                energy_kwh="1.0", direction="in",
            )
            tariff = Tariff.objects.create(
                zev=zev, name=f"{tag} Tariff", category=TariffCategory.ENERGY,
                billing_mode=BillingMode.ENERGY, energy_type=EnergyType.LOCAL,
                valid_from=date(2026, 1, 1),
            )
            TariffPeriod.objects.create(
                tariff=tariff, period_type="flat", price_chf_per_kwh="0.20",
            )
            Invoice.objects.create(
                zev=zev, participant=participant, invoice_number=f"{tag}-00001",
                period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
                status=InvoiceStatus.DRAFT,
            )
            setattr(self, f"participant_{tag.lower()}", participant)
            setattr(self, f"meter_{tag.lower()}", meter)

        self.client = APIClient()
        auth(self.client, self.admin)


class AdminFilteringTests(_TwoPopulatedCommunities):
    """An admin sees both communities, so the filter has something to do."""

    def assertOnlyCommunityA(self, url, field, expected):
        unfiltered = self.client.get(url)
        self.assertEqual(len(_rows(unfiltered)), 2, f"{url} fixture should hold both communities")

        filtered = self.client.get(url, {"zev_id": str(self.zev_a.id)})
        self.assertEqual(filtered.status_code, 200, filtered.content)
        self.assertEqual([row[field] for row in _rows(filtered)], [expected])

    def test_participants(self):
        self.assertOnlyCommunityA(PARTICIPANTS, "first_name", "A")

    def test_metering_points(self):
        self.assertOnlyCommunityA(METERING_POINTS, "meter_id", "A-METER")

    def test_tariffs(self):
        self.assertOnlyCommunityA(TARIFFS, "name", "A Tariff")

    def test_invoices(self):
        self.assertOnlyCommunityA(INVOICES, "invoice_number", "A-00001")

    def test_metering_point_assignments(self):
        filtered = self.client.get(ASSIGNMENTS, {"zev_id": str(self.zev_a.id)})
        self.assertEqual(filtered.status_code, 200)
        rows = _rows(filtered)
        self.assertEqual(len(_rows(self.client.get(ASSIGNMENTS))), 2)
        self.assertEqual([row["metering_point"] for row in rows], [str(self.meter_a.id)])

    def test_meter_readings(self):
        """The sharpest case: this one returned the whole instance's readings."""
        self.assertEqual(len(_rows(self.client.get(READINGS))), 2)
        filtered = self.client.get(READINGS, {"zev_id": str(self.zev_a.id)})
        self.assertEqual(filtered.status_code, 200)
        rows = _rows(filtered)
        self.assertEqual([row["metering_point"] for row in rows], [str(self.meter_a.id)])

    def test_zevs(self):
        filtered = self.client.get(ZEVS, {"zev_id": str(self.zev_a.id)})
        self.assertEqual([row["name"] for row in _rows(filtered)], ["Community A"])


class NonExistentZevTests(_TwoPopulatedCommunities):
    """A ZEV id nobody owns must empty the list, not fall back to everything."""

    UNKNOWN = "00000000-0000-0000-0000-000000000000"

    def test_every_endpoint_returns_nothing(self):
        for url in (PARTICIPANTS, METERING_POINTS, ASSIGNMENTS, TARIFFS, READINGS, INVOICES, ZEVS):
            with self.subTest(url=url):
                response = self.client.get(url, {"zev_id": self.UNKNOWN})
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(_rows(response), [], f"{url} ignored the filter")


class MalformedValueTests(_TwoPopulatedCommunities):
    def test_a_non_uuid_is_refused_rather_than_ignored(self):
        for url in (PARTICIPANTS, METERING_POINTS, TARIFFS, READINGS, INVOICES):
            with self.subTest(url=url):
                response = self.client.get(url, {"zev_id": "not-a-uuid"})
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("zev_id", response.json())

    def test_an_empty_value_is_treated_as_absent(self):
        """``?zev_id=`` with no value is a client building a querystring from an
        empty field, not a request to match a ZEV with no id."""
        response = self.client.get(f"{PARTICIPANTS}?zev_id=")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(_rows(response)), 2)


class FilterCannotWidenScopeTests(_TwoPopulatedCommunities):
    """The filter narrows. It must never be a way to reach another community."""

    def test_owner_naming_another_community_gets_nothing(self):
        client = APIClient()
        auth(client, self.owner_a)
        for url in (PARTICIPANTS, METERING_POINTS, TARIFFS, READINGS, INVOICES):
            with self.subTest(url=url):
                response = client.get(url, {"zev_id": str(self.zev_b.id)})
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(_rows(response), [])

    def test_owner_naming_their_own_community_still_works(self):
        client = APIClient()
        auth(client, self.owner_a)
        response = client.get(PARTICIPANTS, {"zev_id": str(self.zev_a.id)})
        self.assertEqual([row["first_name"] for row in _rows(response)], ["A"])

    def test_participant_naming_a_foreign_community_gets_nothing(self):
        member = make_user("zf_member", UserRole.PARTICIPANT)
        self.participant_a.user = member
        self.participant_a.save(update_fields=["user"])

        client = APIClient()
        auth(client, member)
        response = client.get(METERING_POINTS, {"zev_id": str(self.zev_b.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_rows(response), [])


class UnfilteredBehaviourUnchangedTests(_TwoPopulatedCommunities):
    """Omitting the parameter must behave exactly as before."""

    def test_admin_still_sees_both_communities(self):
        self.assertEqual(len(_rows(self.client.get(PARTICIPANTS))), 2)

    def test_owner_still_sees_only_their_own(self):
        client = APIClient()
        auth(client, self.owner_a)
        self.assertEqual([row["first_name"] for row in _rows(client.get(PARTICIPANTS))], ["A"])
