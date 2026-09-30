"""Coverage for the annual ZEV report endpoint (docs/specs/2026-09-annual-zev-report.md).

The fixture is small enough to check by hand. In June 2026 the producer's
10 kWh at noon meet 4 kWh of consumption (4 used locally, 6 exported) and the
evening's 6 kWh come from the grid: 40 % self-consumption, 40 % self-sufficiency.
June 2025 has 10 kWh produced against 5 consumed at the same instant: 50 % and
100 %.
"""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from metering.models import MeterReading, ReadingDirection, ReadingResolution
from testing.helpers import authenticate as auth, make_user
from tariffs.models import TariffCategory
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType

from .annual_statement import compute_savings
from .models import InvoiceItem, InvoiceStatus
from .test_helpers import make_invoice, make_participant, make_zev

ANNUAL_REPORT = "/api/v1/invoices/invoices/annual-report/"
ZURICH = ZoneInfo("Europe/Zurich")


class AnnualReportTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = make_user("ar_admin", UserRole.ADMIN)
        self.owner = make_user("ar_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Annual ZEV")
        self.puser = make_user("ar_participant", UserRole.PARTICIPANT)

        self.producer = make_participant(self.zev, user=self.owner, first="Paul", last="Produzent")
        self.consumer = make_participant(self.zev, user=self.puser, first="Pia", last="Muster")
        for participant in (self.producer, self.consumer):
            participant.valid_from = date(2025, 1, 1)
            participant.save(update_fields=["valid_from"])

        self.consumption_mp = self._metering_point("CH-AR-CONS", MeteringPointType.CONSUMPTION, self.consumer)
        self.production_mp = self._metering_point("CH-AR-PROD", MeteringPointType.PRODUCTION, self.producer)

        self._reading(self.production_mp, datetime(2026, 6, 15, 12, 0, tzinfo=ZURICH), "10", ReadingDirection.OUT)
        self._reading(self.consumption_mp, datetime(2026, 6, 15, 12, 0, tzinfo=ZURICH), "4", ReadingDirection.IN)
        self._reading(self.consumption_mp, datetime(2026, 6, 15, 22, 0, tzinfo=ZURICH), "6", ReadingDirection.IN)

        self.other_owner = make_user("ar_other_owner", UserRole.ZEV_OWNER)
        self.other_zev = make_zev(self.other_owner, "Other ZEV")

    def _metering_point(self, meter_id, meter_type, participant):
        mp = MeteringPoint.objects.create(zev=self.zev, meter_id=meter_id, meter_type=meter_type)
        MeteringPointAssignment.objects.create(metering_point=mp, participant=participant, valid_from=date(2025, 1, 1))
        return mp

    def _reading(self, mp, ts, kwh, direction):
        MeterReading.objects.create(
            metering_point=mp,
            timestamp=ts,
            energy_kwh=Decimal(kwh),
            direction=direction,
            resolution=ReadingResolution.FIFTEEN_MIN,
        )

    def _invoice(self, participant, period, local, grid, inv_status=InvoiceStatus.SENT):
        """An invoice with one local and one grid energy item: ``(kWh, CHF)`` each."""
        invoice = make_invoice(self.zev, participant, inv_status=inv_status, period=period)
        invoice.total_local_kwh = Decimal(local[0])
        invoice.total_grid_kwh = Decimal(grid[0])
        invoice.save(update_fields=["total_local_kwh", "total_grid_kwh"])
        for item_type, (kwh, chf) in (
            (InvoiceItem.ItemType.LOCAL_ENERGY, local),
            (InvoiceItem.ItemType.GRID_ENERGY, grid),
        ):
            InvoiceItem.objects.create(
                invoice=invoice,
                item_type=item_type,
                tariff_category=TariffCategory.ENERGY,
                description=str(item_type),
                quantity_kwh=Decimal(kwh),
                unit="kWh",
                unit_price_chf=Decimal(chf) / Decimal(kwh),
                total_chf=Decimal(chf),
            )
        return invoice

    def _get(self, user, **params):
        auth(self.client, user)
        return self.client.get(ANNUAL_REPORT, params)

    def _report(self, year=2026):
        resp = self._get(self.owner, year=year, zev_id=str(self.zev.pk))
        self.assertEqual(resp.status_code, 200)
        return resp.data


class AnnualReportContentTests(AnnualReportTestCase):
    def test_totals_carry_the_balance_and_both_rates(self):
        totals = self._report()["totals"]

        self.assertEqual(totals["produced_kwh"], 10.0)
        self.assertEqual(totals["consumed_kwh"], 10.0)
        self.assertEqual(totals["imported_kwh"], 6.0)
        self.assertEqual(totals["exported_kwh"], 6.0)
        self.assertEqual(totals["self_consumed_kwh"], 4.0)
        self.assertEqual(totals["self_consumption_rate"], 40.0)
        self.assertEqual(totals["self_sufficiency_rate"], 40.0)

    def test_months_are_always_twelve_with_null_rates_where_there_is_no_data(self):
        months = self._report()["months"]

        self.assertEqual([m["month"] for m in months], list(range(1, 13)))
        june = months[5]
        self.assertEqual(june["self_consumption_rate"], 40.0)
        self.assertEqual(june["self_sufficiency_rate"], 40.0)
        january = months[0]
        self.assertEqual(january["produced_kwh"], 0.0)
        self.assertIsNone(january["self_consumption_rate"])
        self.assertIsNone(january["self_sufficiency_rate"])

    def test_previous_year_supplies_the_comparison_rates(self):
        self._reading(self.production_mp, datetime(2025, 6, 15, 12, 0, tzinfo=ZURICH), "10", ReadingDirection.OUT)
        self._reading(self.consumption_mp, datetime(2025, 6, 15, 12, 0, tzinfo=ZURICH), "5", ReadingDirection.IN)

        report = self._report()

        june = report["months"][5]
        self.assertEqual(june["previous_self_consumption_rate"], 50.0)
        self.assertEqual(june["previous_self_sufficiency_rate"], 100.0)
        self.assertIsNone(report["months"][0]["previous_self_consumption_rate"])
        self.assertEqual(report["previous_totals"]["produced_kwh"], 10.0)
        self.assertEqual(report["previous_totals"]["self_consumption_rate"], 50.0)

    def test_previous_totals_are_null_without_previous_year_readings(self):
        report = self._report()

        self.assertIsNone(report["previous_totals"])
        self.assertTrue(all(m["previous_self_consumption_rate"] is None for m in report["months"]))

    def test_year_follows_swiss_civil_time(self):
        """New Year's midnight in Zurich is 23:00 UTC on 31 December: that
        reading belongs to January of the new year, the quarter hour before
        it to the old one (ADR 0026)."""
        self._reading(self.consumption_mp, datetime(2026, 1, 1, 0, 0, tzinfo=ZURICH), "3", ReadingDirection.IN)
        self._reading(self.consumption_mp, datetime(2025, 12, 31, 23, 45, tzinfo=ZURICH), "7", ReadingDirection.IN)

        report = self._report()

        self.assertEqual(report["months"][0]["consumed_kwh"], 3.0)
        self.assertEqual(report["totals"]["consumed_kwh"], 13.0)
        self.assertEqual(report["previous_totals"]["consumed_kwh"], 7.0)

    def test_participants_carry_their_split_and_rate(self):
        rows = {row["participant_id"]: row for row in self._report()["participants"]}

        consumer = rows[str(self.consumer.pk)]
        self.assertEqual(consumer["participant_name"], "Pia Muster")
        self.assertEqual(consumer["consumed_kwh"], 10.0)
        self.assertEqual(consumer["from_zev_kwh"], 4.0)
        self.assertEqual(consumer["from_grid_kwh"], 6.0)
        self.assertEqual(consumer["self_sufficiency_rate"], 40.0)
        producer = rows[str(self.producer.pk)]
        self.assertEqual(producer["produced_kwh"], 10.0)
        self.assertIsNone(producer["self_sufficiency_rate"])

    def test_participants_are_sorted_by_name(self):
        names = [row["participant_name"] for row in self._report()["participants"]]

        self.assertEqual(names, ["Paul Produzent", "Pia Muster"])

    def test_savings_match_the_annual_statement(self):
        invoice = self._invoice(self.consumer, (date(2026, 6, 1), date(2026, 6, 30)), ("4", "0.80"), ("6", "1.80"))

        report = self._report()

        consumer = next(r for r in report["participants"] if r["participant_id"] == str(self.consumer.pk))
        self.assertEqual(consumer["savings"], compute_savings([invoice]))
        # 4 kWh at the 30 Rp grid rate would have cost 1.20; billed locally at 0.80.
        self.assertEqual(consumer["savings"]["saved_chf"], "0.40")
        self.assertEqual(report["savings_total_chf"], "0.40")

    def test_cancelled_invoices_and_other_years_do_not_count(self):
        self._invoice(self.consumer, (date(2026, 6, 1), date(2026, 6, 30)), ("4", "0.80"), ("6", "1.80"),
                      inv_status=InvoiceStatus.CANCELLED)
        self._invoice(self.consumer, (date(2025, 6, 1), date(2025, 6, 30)), ("4", "0.80"), ("6", "1.80"))

        report = self._report()

        self.assertTrue(all(row["savings"] is None for row in report["participants"]))
        self.assertIsNone(report["savings_total_chf"])

    def test_invoiced_participant_without_readings_keeps_a_row(self):
        late = make_participant(self.zev, first="Lara", last="Spaet")
        self._invoice(late, (date(2026, 3, 1), date(2026, 3, 31)), ("2", "0.40"), ("3", "0.90"))

        rows = {row["participant_id"]: row for row in self._report()["participants"]}

        self.assertEqual(rows[str(late.pk)]["consumed_kwh"], 0.0)
        self.assertEqual(rows[str(late.pk)]["savings"]["saved_chf"], "0.20")

    def test_year_without_readings_reports_no_data(self):
        report = self._report(year=2024)

        self.assertFalse(report["has_data"])
        self.assertEqual(report["totals"]["produced_kwh"], 0.0)
        self.assertIsNone(report["totals"]["self_consumption_rate"])
        self.assertEqual(report["participants"], [])
        self.assertEqual(len(report["months"]), 12)


class AnnualReportAccessTests(AnnualReportTestCase):
    def test_admin_can_read_any_zev(self):
        resp = self._get(self.admin, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["has_data"])

    def test_owner_cannot_read_another_owners_zev(self):
        resp = self._get(self.owner, year=2026, zev_id=str(self.other_zev.pk))

        self.assertEqual(resp.status_code, 403)

    def test_participant_is_forbidden(self):
        resp = self._get(self.puser, year=2026, zev_id=str(self.zev.pk))

        self.assertEqual(resp.status_code, 403)

    def test_anonymous_is_rejected(self):
        resp = self.client.get(ANNUAL_REPORT, {"year": 2026, "zev_id": str(self.zev.pk)})

        self.assertEqual(resp.status_code, 401)

    def test_zev_id_is_required(self):
        resp = self._get(self.owner, year=2026)

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["error"], "zev_id is required.")

    def test_year_is_required_and_bounded(self):
        missing = self._get(self.owner, zev_id=str(self.zev.pk))
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.data["error"], "year is required.")

        # The previous year is read too, so year 1 has nothing to compare with.
        first = self._get(self.owner, year=1, zev_id=str(self.zev.pk))
        self.assertEqual(first.status_code, 400)

    def test_unknown_or_malformed_zev_is_404(self):
        for zev_id in ("00000000-0000-0000-0000-000000000000", "not-a-uuid"):
            resp = self._get(self.admin, year=2026, zev_id=zev_id)
            self.assertEqual(resp.status_code, 404, zev_id)
