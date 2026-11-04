"""Hourly profile, PDF chart and data quality on the two clock-change days.

The autumn change day has 25 real hours (100 quarter-hours) and the spring day
23 (92). Readings are UTC instants and the Swiss hour/day is derived from them
(ADR 0026), so the day must show up with its real length: the repeated 02:00
hour adds to bucket 2, the missing one leaves bucket 2 empty, and the whole day
stays on one civil date.

Spec: docs/specs/2026-09-swiss-civil-time.md §9.
"""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from allocation.validity import period_window
from invoices.models import Invoice
from invoices.pdf_charts import _build_hourly_profile_chart_svg
from invoices.pdf_translations import INVOICE_TRANSLATIONS
from metering.models import MeterReading, ReadingDirection, ReadingResolution
from testing.helpers import authenticate as auth, create_managed_zev, make_user
from zev.models import MeteringPoint, MeteringPointAssignment, MeteringPointType, Participant

AUTUMN = date(2026, 10, 25)  # 25 h, 100 quarter-hours
SPRING = date(2026, 3, 29)   # 23 h, 92 quarter-hours
DAYS = [(AUTUMN, 25), (SPRING, 23)]


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _real_slots(day, step=timedelta(minutes=15)):
    start, end = period_window(day, day)
    ts = start
    while ts < end:
        yield ts
        ts += step


class _DstDayCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = make_user("dst_owner", UserRole.USER)
        self.user = make_user("dst_alice", UserRole.USER)
        self.zev = create_managed_zev(name="DST ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="DS")
        self.participant = Participant.objects.create(
            zev=self.zev, user=self.user, first_name="Alice", last_name="Dst",
            email="alice.dst@example.com", valid_from=date(2026, 1, 1),
        )
        self.meter = MeteringPoint.objects.create(
            zev=self.zev, meter_id="CH-DST-1", meter_type=MeteringPointType.CONSUMPTION,
        )

    def assign(self, **kwargs):
        kwargs.setdefault("valid_from", date(2026, 1, 1))
        return MeteringPointAssignment.objects.create(
            metering_point=self.meter, participant=self.participant, **kwargs,
        )

    def read(self, ts, kwh="0.25", resolution=ReadingResolution.FIFTEEN_MIN):
        return MeterReading.objects.create(
            metering_point=self.meter, timestamp=ts, energy_kwh=Decimal(kwh),
            direction=ReadingDirection.IN, resolution=resolution,
        )

    def fill_day(self, day, **kwargs):
        slots = list(_real_slots(day))
        for ts in slots:
            self.read(ts, **kwargs)
        return slots


class HourlyProfileDstDayTests(_DstDayCase):
    def profile(self, date_from, date_to):
        auth(self.client, self.user)
        resp = self.client.get(
            "/api/v1/metering/readings/hourly-profile/",
            {"zev_id": str(self.zev.id), "date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        return [float(row["from_grid_kwh"]) for row in resp.data["hourly_profile"]]

    def test_autumn_day_counts_the_repeated_hour_in_bucket_2(self):
        self.assign()
        self.assertEqual(len(self.fill_day(AUTUMN)), 100)

        grid = self.profile(AUTUMN, AUTUMN)

        # 4 × 0.25 kWh per real hour; 02:00–02:59 happens twice.
        self.assertEqual(grid[2], 2.0)
        self.assertEqual([v for h, v in enumerate(grid) if h != 2], [1.0] * 23)
        self.assertEqual(sum(grid), 25.0)

    def test_spring_day_leaves_the_missing_hour_empty(self):
        self.assign()
        self.assertEqual(len(self.fill_day(SPRING)), 92)

        grid = self.profile(SPRING, SPRING)

        self.assertEqual(grid[2], 0.0)
        self.assertEqual([v for h, v in enumerate(grid) if h != 2], [1.0] * 23)
        self.assertEqual(sum(grid), 23.0)

    def test_average_divides_by_civil_days_not_hours(self):
        self.assign()
        for day in (date(2026, 10, 24), AUTUMN, date(2026, 10, 26)):
            self.fill_day(day)

        grid = self.profile(date(2026, 10, 24), date(2026, 10, 26))

        self.assertAlmostEqual(grid[2], 4 / 3, places=4)
        self.assertEqual(grid[1], 1.0)
        self.assertEqual(grid[3], 1.0)

    def test_hourly_resolution_readings_land_in_their_swiss_hour(self):
        self.assign()
        slots = list(_real_slots(AUTUMN, step=timedelta(hours=1)))
        self.assertEqual(len(slots), 25)
        for ts in slots:
            self.read(ts, kwh="1", resolution=ReadingResolution.HOURLY)

        grid = self.profile(AUTUMN, AUTUMN)

        self.assertEqual(grid[2], 2.0)
        self.assertEqual(grid[0], 1.0)
        self.assertEqual(grid[23], 1.0)

    def test_assignment_ending_on_the_change_day_keeps_every_real_slot(self):
        self.assign(valid_to=AUTUMN)
        self.fill_day(AUTUMN)
        # 00:00 CET on 26 October is the next civil day, after the move-out.
        self.read(_utc(2026, 10, 25, 23, 0))

        grid = self.profile(AUTUMN, AUTUMN)

        self.assertEqual(sum(grid), 25.0)


class HourlyProfileChartDstDayTests(_DstDayCase):
    def bars(self, day):
        invoice = Invoice.objects.create(
            invoice_number="DST-1", zev=self.zev, participant=self.participant,
            period_start=day, period_end=day, total_chf=Decimal("1.00"),
        )
        chart = _build_hourly_profile_chart_svg(invoice, INVOICE_TRANSLATIONS["de"])
        self.assertIsNotNone(chart)
        heights = {}
        for height, hour in re.findall(r'height="([\d.]+)"[^>]*data-hour="(\d+)"', chart):
            heights[int(hour)] = float(height)
        return heights

    def test_autumn_day_shows_all_24_hours_and_a_double_height_hour_2(self):
        self.assign()
        self.fill_day(AUTUMN)

        heights = self.bars(AUTUMN)

        self.assertEqual(set(heights), set(range(24)))
        self.assertAlmostEqual(heights[2], 2 * heights[1], delta=0.2)

    def test_spring_day_has_no_bar_for_the_missing_hour(self):
        self.assign()
        self.fill_day(SPRING)

        heights = self.bars(SPRING)

        self.assertEqual(set(heights), set(range(24)) - {2})


class DataQualityDstDayTests(_DstDayCase):
    def status(self, date_from, date_to):
        auth(self.client, self.owner)
        resp = self.client.get(
            "/api/v1/metering/readings/data-quality-status/",
            {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data["metering_points"][0]

    def test_complete_days_around_both_changes_are_100_percent(self):
        self.assign()
        for change in (AUTUMN, SPRING):
            for offset in (-1, 0, 1):
                self.fill_day(change + timedelta(days=offset))

        for change in (AUTUMN, SPRING):
            status = self.status(change - timedelta(days=1), change + timedelta(days=1))
            self.assertEqual(status["days_with_data"], 3, change)
            self.assertEqual(status["data_completeness"], 100, change)
            self.assertEqual(status["severity"], "green", change)
            self.assertEqual(status["gaps"], [], change)

    def test_every_slot_of_a_change_day_belongs_to_that_one_day(self):
        self.assign()
        for day, hours in DAYS:
            slots = self.fill_day(day)
            self.assertEqual(len(slots), hours * 4)

            status = self.status(day - timedelta(days=1), day + timedelta(days=1))

            # Only the middle day has data: neither the first slot (00:00 local)
            # nor the last (23:45 local) spills onto a neighbouring day.
            self.assertEqual(status["days_with_data"], 1, day)
            self.assertEqual(
                [(g["start_date"], g["end_date"]) for g in status["gaps"]],
                [((day - timedelta(days=1)).isoformat(),) * 2, ((day + timedelta(days=1)).isoformat(),) * 2],
                day,
            )

    def test_unassigned_readings_split_at_local_midnight_of_the_change_day(self):
        self.assign(valid_to=AUTUMN)
        self.fill_day(AUTUMN)
        # 00:00 CET on 26 October (23:00Z) is after the move-out; the last slot
        # of the 25th (23:45 CET = 22:45Z) is not.
        self.read(_utc(2026, 10, 25, 23, 0))

        status = self.status(AUTUMN, AUTUMN + timedelta(days=1))

        self.assertEqual(status["days_with_data"], 2)
        self.assertEqual(status["unassigned_days"], 1)
        self.assertEqual(status["unassigned_readings"], 1)

    def test_spring_move_in_covers_all_92_slots(self):
        self.assign(valid_from=SPRING)
        self.fill_day(SPRING)
        # 23:45 CET on 28 March (22:45Z) is before the move-in.
        self.read(_utc(2026, 3, 28, 22, 45))

        status = self.status(SPRING - timedelta(days=1), SPRING)

        self.assertEqual(status["unassigned_days"], 1)
        self.assertEqual(status["unassigned_readings"], 1)
