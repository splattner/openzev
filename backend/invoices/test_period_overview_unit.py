"""Direct unit tests for invoices.period_overview.compute_period_overview.

These tests call the pure function directly, bypassing the HTTP layer,
to cover edge cases more precisely and cheaply.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from django.test import TestCase

from accounts.models import UserRole
from invoices.models import InvoiceStatus
from invoices.period_overview import compute_period_overview
from invoices.test_helpers import make_invoice, make_participant, make_user, make_zev
from metering.models import MeterReading, ReadingDirection, ReadingResolution
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType


def _reading(mp, day_date):
    return MeterReading.objects.create(
        metering_point=mp,
        timestamp=datetime(day_date.year, day_date.month, day_date.day, 0, 0, tzinfo=timezone.utc),
        energy_kwh=Decimal("1.0000"),
        direction=ReadingDirection.IN,
        resolution=ReadingResolution.FIFTEEN_MIN,
    )


def _fill_readings(mp, start: date, end: date):
    """Create one reading per day for mp over [start, end] inclusive."""
    from datetime import timedelta
    d = start
    while d <= end:
        _reading(mp, d)
        d += timedelta(days=1)


class ComputePeriodOverviewTests(TestCase):
    def setUp(self):
        self.owner = make_user("po_owner", UserRole.USER)
        self.zev = make_zev(self.owner, "Unit ZEV")
        self.period_start = date(2026, 3, 1)
        self.period_end = date(2026, 3, 31)

    # ------------------------------------------------------------------ helpers
    def _mp(self, meter_id="CH-UNIT-1"):
        return MeteringPoint.objects.create(
            zev=self.zev,
            meter_id=meter_id,
            meter_type=MeteringPointType.CONSUMPTION,
        )

    def _assign(self, mp, participant, valid_from=None, valid_to=None):
        return MeteringPointAssignment.objects.create(
            metering_point=mp,
            participant=participant,
            valid_from=valid_from or self.period_start,
            valid_to=valid_to,
        )

    def _run(self):
        return compute_period_overview(
            zev=self.zev,
            period_start=self.period_start,
            period_end=self.period_end,
            request=None,
        )

    # ------------------------------------------------------------------ tests

    def test_participant_with_full_readings_is_complete(self):
        p = make_participant(self.zev, first="Full", last="Coverage")
        mp = self._mp("CH-UNIT-FULL")
        self._assign(mp, p)
        _fill_readings(mp, self.period_start, self.period_end)

        rows = self._run()

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row["metering_data_complete"])
        self.assertEqual(row["missing_meter_ids"], [])
        self.assertEqual(row["metering_points_total"], 1)
        self.assertEqual(row["metering_points_with_data"], 1)

    def test_participant_with_no_readings_is_incomplete(self):
        p = make_participant(self.zev, first="No", last="Readings")
        mp = self._mp("CH-UNIT-EMPTY")
        self._assign(mp, p)
        # no readings created

        rows = self._run()

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertFalse(row["metering_data_complete"])
        self.assertEqual(row["missing_meter_ids"], ["CH-UNIT-EMPTY"])
        self.assertEqual(row["missing_meter_details"][0]["missing_days"], 31)

    def test_participant_with_one_missing_day_is_incomplete(self):
        p = make_participant(self.zev, first="Almost", last="Complete")
        mp = self._mp("CH-UNIT-GAP")
        self._assign(mp, p)
        _fill_readings(mp, self.period_start, self.period_end)
        # remove the last day
        MeterReading.objects.filter(
            metering_point=mp,
            timestamp__date=self.period_end,
        ).delete()

        rows = self._run()
        row = rows[0]

        self.assertFalse(row["metering_data_complete"])
        self.assertEqual(row["missing_meter_details"][0]["missing_days"], 1)

    def test_participant_without_assignment_in_period_excluded(self):
        p = make_participant(self.zev, first="No", last="Assignment")
        # assignment ends before period starts
        mp = self._mp("CH-UNIT-NOASSIGN")
        MeteringPointAssignment.objects.create(
            metering_point=mp,
            participant=p,
            valid_from=date(2025, 1, 1),
            valid_to=date(2026, 2, 28),
        )

        rows = self._run()

        self.assertEqual(rows, [])

    def test_partial_assignment_restricts_required_days(self):
        """Only days within the assignment window are required to have readings."""
        p = make_participant(self.zev, first="Partial", last="Window")
        mp = self._mp("CH-UNIT-PARTIAL")
        # Assignment covers only March 10–20 (11 days)
        self._assign(mp, p, valid_from=date(2026, 3, 10), valid_to=date(2026, 3, 20))
        # Fill full month — all 11 assigned days are covered
        _fill_readings(mp, self.period_start, self.period_end)

        rows = self._run()

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["metering_data_complete"])

    def test_partial_assignment_with_gap_inside_window(self):
        """A missing day inside the assignment window still counts as incomplete."""
        p = make_participant(self.zev, first="PartialGap", last="Window")
        mp = self._mp("CH-UNIT-PARTGAP")
        self._assign(mp, p, valid_from=date(2026, 3, 10), valid_to=date(2026, 3, 20))
        _fill_readings(mp, date(2026, 3, 10), date(2026, 3, 20))
        # Delete March 15 reading
        MeterReading.objects.filter(
            metering_point=mp,
            timestamp__date=date(2026, 3, 15),
        ).delete()

        rows = self._run()
        self.assertFalse(rows[0]["metering_data_complete"])
        self.assertEqual(rows[0]["missing_meter_details"][0]["missing_days"], 1)

    def test_invoice_is_included_for_matching_period(self):
        p = make_participant(self.zev, first="Has", last="Invoice")
        mp = self._mp("CH-UNIT-INV")
        self._assign(mp, p)
        _fill_readings(mp, self.period_start, self.period_end)
        inv = make_invoice(self.zev, p, InvoiceStatus.APPROVED)
        # Override period to match
        inv.period_start = self.period_start
        inv.period_end = self.period_end
        inv.save()

        rows = self._run()
        self.assertIsNotNone(rows[0]["invoice"])
        self.assertEqual(rows[0]["invoice"]["id"], str(inv.id))

    def test_invoice_not_included_for_different_period(self):
        p = make_participant(self.zev, first="Wrong", last="Period")
        mp = self._mp("CH-UNIT-WRONGPERIOD")
        self._assign(mp, p)
        _fill_readings(mp, self.period_start, self.period_end)
        # Invoice is for a different period
        make_invoice(self.zev, p, InvoiceStatus.DRAFT)  # default period Jan 2026

        rows = self._run()
        self.assertIsNone(rows[0]["invoice"])

    def test_rows_ordered_by_last_name_first_name(self):
        p_b = make_participant(self.zev, first="Adam", last="Ziegler")
        p_a = make_participant(self.zev, first="Zara", last="Alder")
        for p, mid in [(p_b, "CH-UNIT-Z"), (p_a, "CH-UNIT-A")]:
            mp = self._mp(mid)
            self._assign(mp, p)

        rows = self._run()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["participant_name"], p_a.full_name)  # Alder before Ziegler
        self.assertEqual(rows[1]["participant_name"], p_b.full_name)

    def test_multiple_metering_points_counts_correctly(self):
        p = make_participant(self.zev, first="Multi", last="Meter")
        mp1 = self._mp("CH-UNIT-M1")
        mp2 = self._mp("CH-UNIT-M2")
        self._assign(mp1, p)
        self._assign(mp2, p)
        _fill_readings(mp1, self.period_start, self.period_end)
        # mp2 has no readings

        rows = self._run()
        row = rows[0]

        self.assertFalse(row["metering_data_complete"])
        self.assertEqual(row["metering_points_total"], 2)
        self.assertEqual(row["metering_points_with_data"], 1)
        self.assertIn("CH-UNIT-M2", row["missing_meter_ids"])
        self.assertNotIn("CH-UNIT-M1", row["missing_meter_ids"])
