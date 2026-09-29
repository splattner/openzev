"""Civil-time helpers: local-midnight bounds and civil dates (ADR 0026)."""
from datetime import date, datetime, timedelta, timezone

from django.test import SimpleTestCase

from allocation.validity import civil_date, day_length, period_start_dt, period_window, wall_clock


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class CivilTimeHelperTests(SimpleTestCase):
    def test_period_start_is_local_midnight_in_winter_and_summer(self):
        self.assertEqual(period_start_dt(date(2026, 1, 15)), _utc(2026, 1, 14, 23))
        self.assertEqual(period_start_dt(date(2026, 7, 15)), _utc(2026, 7, 14, 22))

    def test_dst_days_are_23_and_25_hours(self):
        self.assertEqual(day_length(date(2026, 3, 29)), timedelta(hours=23))
        self.assertEqual(day_length(date(2026, 10, 25)), timedelta(hours=25))
        self.assertEqual(day_length(date(2026, 6, 1)), timedelta(hours=24))

    def test_period_window_spans_whole_local_month(self):
        self.assertEqual(
            period_window(date(2026, 1, 1), date(2026, 1, 31)),
            (_utc(2025, 12, 31, 23), _utc(2026, 1, 31, 23)),
        )

    def test_civil_date_near_midnight(self):
        self.assertEqual(civil_date(_utc(2026, 6, 30, 21, 45)), date(2026, 6, 30))
        self.assertEqual(civil_date(_utc(2026, 6, 30, 22, 30)), date(2026, 7, 1))

    def test_civil_date_rejects_naive(self):
        with self.assertRaises(ValueError):
            civil_date(datetime(2026, 6, 30, 22, 30))

    def test_wall_clock_converts_aware_and_keeps_naive(self):
        self.assertEqual(wall_clock(_utc(2026, 7, 1, 4, 30)).hour, 6)
        naive = datetime(2026, 7, 1, 4, 30)
        self.assertIs(wall_clock(naive), naive)
