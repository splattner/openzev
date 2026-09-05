"""Invoice period overview readiness tests."""

from datetime import date, datetime, timezone
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.models import InvoiceStatus
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from metering.models import MeterReading, ReadingDirection, ReadingResolution
from testing.helpers import authenticate as auth
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType


class InvoicePeriodOverviewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("overview_owner", UserRole.ZEV_OWNER)
        self.other_owner = make_user("overview_other_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Overview ZEV")

        self.p_with_data = make_participant(self.zev, first="With", last="Data")
        self.p_missing_data = make_participant(self.zev, first="Missing", last="Data")

        self.mp_with_data = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-OVERVIEW-1",
            meter_type=MeteringPointType.CONSUMPTION,
        )
        self.mp_missing_data = MeteringPoint.objects.create(
            zev=self.zev,
            meter_id="CH-OVERVIEW-2",
            meter_type=MeteringPointType.CONSUMPTION,
        )

        # Assignments define whose meter requires readings on which days.
        MeteringPointAssignment.objects.create(
            metering_point=self.mp_with_data,
            participant=self.p_with_data,
            valid_from=date(2026, 1, 1),
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.mp_missing_data,
            participant=self.p_missing_data,
            valid_from=date(2026, 1, 1),
        )

        for day in range(1, 32):
            MeterReading.objects.create(
                metering_point=self.mp_with_data,
                timestamp=datetime(2026, 1, day, 0, 0, tzinfo=timezone.utc),
                energy_kwh=Decimal("3.0000"),
                direction=ReadingDirection.IN,
                resolution=ReadingResolution.FIFTEEN_MIN,
            )

        self.invoice = make_invoice(self.zev, self.p_with_data, InvoiceStatus.DRAFT)

    def test_owner_gets_participant_rows_with_invoice_and_metering_readiness(self):
        auth(self.client, self.owner)

        resp = self.client.get(
            "/api/v1/invoices/invoices/period-overview/",
            {
                "zev_id": str(self.zev.id),
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["billing_interval"], self.zev.billing_interval)
        self.assertEqual(len(resp.data["rows"]), 2)

        rows_by_participant = {row["participant_name"]: row for row in resp.data["rows"]}

        with_data_row = rows_by_participant[self.p_with_data.full_name]
        self.assertTrue(with_data_row["metering_data_complete"])
        self.assertIsNotNone(with_data_row["invoice"])
        self.assertEqual(with_data_row["invoice"]["id"], str(self.invoice.id))

        missing_data_row = rows_by_participant[self.p_missing_data.full_name]
        self.assertFalse(missing_data_row["metering_data_complete"])
        self.assertEqual(missing_data_row["missing_meter_ids"], ["CH-OVERVIEW-2"])
        self.assertEqual(missing_data_row["missing_meter_details"], [{"meter_id": "CH-OVERVIEW-2", "missing_days": 31}])
        self.assertIsNone(missing_data_row["invoice"])

    def test_owner_cannot_view_other_owners_zev_overview(self):
        auth(self.client, self.other_owner)

        resp = self.client.get(
            "/api/v1/invoices/invoices/period-overview/",
            {
                "zev_id": str(self.zev.id),
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

        self.assertEqual(resp.status_code, 403)

    def test_partial_daily_coverage_marks_metering_incomplete(self):
        MeterReading.objects.filter(
            metering_point=self.mp_with_data,
            timestamp__date=date(2026, 1, 31),
        ).delete()

        auth(self.client, self.owner)

        resp = self.client.get(
            "/api/v1/invoices/invoices/period-overview/",
            {
                "zev_id": str(self.zev.id),
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )

        self.assertEqual(resp.status_code, 200)
        rows_by_participant = {row["participant_name"]: row for row in resp.data["rows"]}

        with_data_row = rows_by_participant[self.p_with_data.full_name]
        self.assertFalse(with_data_row["metering_data_complete"])
        self.assertEqual(with_data_row["missing_meter_ids"], ["CH-OVERVIEW-1"])
        self.assertEqual(with_data_row["missing_meter_details"], [{"meter_id": "CH-OVERVIEW-1", "missing_days": 1}])

    def test_partial_period_assignment_only_requires_data_for_assigned_days(self):
        """If an assignment covers only part of the period, only those days require readings."""
        # Remove the full-period assignment for p_with_data and replace with a mid-month one.
        MeteringPointAssignment.objects.filter(metering_point=self.mp_with_data).delete()
        MeteringPointAssignment.objects.create(
            metering_point=self.mp_with_data,
            participant=self.p_with_data,
            valid_from=date(2026, 1, 11),
            valid_to=date(2026, 1, 20),
        )
        # Jan 1–31 readings exist; only Jan 11–20 (10 days) should be checked.
        # All 10 assigned days have readings → complete.
        auth(self.client, self.owner)
        resp = self.client.get(
            "/api/v1/invoices/invoices/period-overview/",
            {"zev_id": str(self.zev.id), "period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
        self.assertEqual(resp.status_code, 200)
        rows_by_participant = {row["participant_name"]: row for row in resp.data["rows"]}
        with_data_row = rows_by_participant[self.p_with_data.full_name]
        self.assertTrue(with_data_row["metering_data_complete"])

    def test_no_assignment_means_participant_excluded_from_overview(self):
        """A participant with no assignment in the period is excluded from the
        overview unless they hold an invoice for it — an invoice keeps its row
        so attention links (retry / mark paid) never land on an empty table."""
        # Remove the assignment for p_with_data so they have no assignment this period.
        MeteringPointAssignment.objects.filter(metering_point=self.mp_with_data).delete()

        auth(self.client, self.owner)
        resp = self.client.get(
            "/api/v1/invoices/invoices/period-overview/",
            {"zev_id": str(self.zev.id), "period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
        self.assertEqual(resp.status_code, 200)
        rows_by_participant = {row["participant_name"]: row for row in resp.data["rows"]}
        # p_with_data still holds an invoice for the period → the row stays,
        # but with no metering data behind it.
        row = rows_by_participant[self.p_with_data.full_name]
        self.assertIsNotNone(row["invoice"])
        self.assertFalse(row["metering_data_complete"])
        # p_missing_data still has an assignment → included
        self.assertIn(self.p_missing_data.full_name, rows_by_participant)
        # Drop the invoice too: with neither assignment nor invoice the
        # participant is excluded from the overview entirely.
        self.invoice.delete()
        resp = self.client.get(
            "/api/v1/invoices/invoices/period-overview/",
            {"zev_id": str(self.zev.id), "period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
        participant_names = [row["participant_name"] for row in resp.data["rows"]]
        self.assertNotIn(self.p_with_data.full_name, participant_names)


class GenerationEligibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("eligibility_owner", UserRole.ZEV_OWNER)
        self.zev = make_zev(self.owner, "Eligibility ZEV")
        self.zev.billing_interval = "quarterly"
        self.zev.save()
        self.participant = make_participant(self.zev, first="Eligible")
        self.mp = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-ELIG", meter_type=MeteringPointType.CONSUMPTION
        )
        MeteringPointAssignment.objects.create(
            metering_point=self.mp, participant=self.participant,
            valid_from=date(2026, 1, 1),
        )

    def _rows(self, start="2026-01-01", end="2026-03-31"):
        auth(self.client, self.owner)
        resp = self.client.get(
            "/api/v1/invoices/invoices/period-overview/",
            {"zev_id": str(self.zev.id), "period_start": start, "period_end": end},
        )
        self.assertEqual(resp.status_code, 200)
        return {row["participant_name"]: row for row in resp.data["rows"]}

    def test_row_without_invoice_is_eligible(self):
        row = self._rows()[self.participant.full_name]
        self.assertIsNone(row["invoice"])
        self.assertEqual(
            row["generation_eligibility"],
            {"state": "eligible", "invoice_id": None, "invoice_number": None},
        )

    def test_live_invoice_row_has_no_eligibility(self):
        make_invoice(
            self.zev, self.participant, InvoiceStatus.DRAFT,
            period=(date(2026, 1, 1), date(2026, 3, 31)),
        )
        row = self._rows()[self.participant.full_name]
        self.assertIsNotNone(row["invoice"])
        self.assertIsNone(row["generation_eligibility"])

    def test_partially_locked_row_is_blocked_with_destination(self):
        paid = make_invoice(
            self.zev, self.participant, InvoiceStatus.PAID,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        row = self._rows()[self.participant.full_name]
        self.assertEqual(
            row["generation_eligibility"],
            {
                "state": "blocked",
                "invoice_id": str(paid.id),
                "invoice_number": paid.invoice_number,
            },
        )

    def test_fully_settled_row_is_covered_with_first_covering_invoice(self):
        first = make_invoice(
            self.zev, self.participant, InvoiceStatus.PAID,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        make_invoice(
            self.zev, self.participant, InvoiceStatus.PAID,
            period=(date(2026, 2, 1), date(2026, 2, 28)),
        )
        make_invoice(
            self.zev, self.participant, InvoiceStatus.PAID,
            period=(date(2026, 3, 1), date(2026, 3, 31)),
        )
        row = self._rows()[self.participant.full_name]
        self.assertEqual(
            row["generation_eligibility"],
            {
                "state": "covered",
                "invoice_id": str(first.id),
                "invoice_number": first.invoice_number,
            },
        )

    def test_draft_overlap_stays_eligible_and_cancelled_exact_is_blocked(self):
        make_invoice(
            self.zev, self.participant, InvoiceStatus.DRAFT,
            period=(date(2026, 1, 1), date(2026, 1, 31)),
        )
        row = self._rows()[self.participant.full_name]
        self.assertEqual(row["generation_eligibility"]["state"], "eligible")
        paid = make_invoice(
            self.zev, self.participant, InvoiceStatus.PAID,
            period=(date(2026, 2, 1), date(2026, 2, 28)),
        )
        cancelled = make_invoice(
            self.zev, self.participant, InvoiceStatus.CANCELLED,
            period=(date(2026, 1, 1), date(2026, 3, 31)),
        )
        row = self._rows()[self.participant.full_name]
        self.assertIsNotNone(row["invoice"])
        self.assertEqual(row["invoice"]["id"], str(cancelled.id))
        self.assertEqual(row["generation_eligibility"]["state"], "blocked")
        self.assertEqual(
            row["generation_eligibility"]["invoice_id"], str(paid.id)
        )

    def test_every_blocked_row_is_protected_past_the_cockpit_truncation(self):
        """Row eligibility is complete per row: with four locked participants
        every row is blocked with a destination, even though the cockpit's
        display summary carries only three."""
        from zev.models import Participant

        participants = [self.participant]
        for index in range(3):
            other = Participant.objects.create(
                zev=self.zev, first_name=f"Extra{index}", last_name="Blocked",
                email=f"extra{index}@example.com", valid_from=date(2026, 1, 1),
            )
            MeteringPoint.objects.create(
                zev=self.zev, meter_id=f"CH-ELIG-{index}",
                meter_type=MeteringPointType.CONSUMPTION,
            )
            MeteringPointAssignment.objects.create(
                metering_point=MeteringPoint.objects.get(
                    zev=self.zev, meter_id=f"CH-ELIG-{index}"
                ),
                participant=other, valid_from=date(2026, 1, 1),
            )
            participants.append(other)
        for participant in participants:
            make_invoice(
                self.zev, participant, InvoiceStatus.PAID,
                period=(date(2026, 1, 1), date(2026, 1, 31)),
            )
        rows = self._rows()
        self.assertEqual(len(rows), 4)
        for row in rows.values():
            self.assertEqual(row["generation_eligibility"]["state"], "blocked")
            self.assertIsNotNone(row["generation_eligibility"]["invoice_id"])
