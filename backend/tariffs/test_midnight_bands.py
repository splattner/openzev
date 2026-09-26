"""Tariff bands whose window crosses midnight (#837).

A band written 22:00–06:00 is the night, and one ending at 00:00 runs to the
end of the day. Both used to match no hour at all, so every hour they were
meant for billed at the tariff's fallback band — with HT/NT that is HT, since
"high" sorts before "low".

See docs/specs/2026-03-tariffs-and-billing-engine.md §3.2.
"""
from datetime import date, datetime, time
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from invoices.engine import _resolve_tariff_band
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from tariffs.periods import in_window, resolve_band
from testing.helpers import make_user
from accounts.models import UserRole
from zev.models import Zev

MONDAY = date(2026, 3, 16)


def _at(hour, minute=0, day=MONDAY):
    return datetime(day.year, day.month, day.day, hour, minute)


def _band(period_type, start, end, price, weekdays=""):
    return TariffPeriod(
        period_type=period_type, time_from=start, time_to=end,
        price_chf_per_kwh=Decimal(price), weekdays=weekdays,
    )


class InWindowTests(SimpleTestCase):
    def test_an_ordinary_window_is_half_open(self):
        self.assertTrue(in_window(time(6), time(6), time(22)))
        self.assertTrue(in_window(time(21, 59), time(6), time(22)))
        self.assertFalse(in_window(time(22), time(6), time(22)))

    def test_a_backwards_window_wraps_past_midnight(self):
        for hour in (22, 23, 0, 3, 5):
            self.assertTrue(in_window(time(hour), time(22), time(6)), hour)
        for hour in (6, 12, 21):
            self.assertFalse(in_window(time(hour), time(22), time(6)), hour)

    def test_an_end_of_midnight_runs_to_the_end_of_the_day(self):
        self.assertTrue(in_window(time(16), time(16), time(0)))
        self.assertTrue(in_window(time(23, 59), time(16), time(0)))
        self.assertFalse(in_window(time(0), time(16), time(0)))
        self.assertFalse(in_window(time(15, 59), time(16), time(0)))

    def test_equal_ends_cover_the_whole_day(self):
        for hour in (0, 7, 23):
            self.assertTrue(in_window(time(hour), time(0), time(0)), hour)


class HtNtAcrossMidnightTests(SimpleTestCase):
    """The shape the user guide describes: HT by day, NT 22:00–06:00."""

    def setUp(self):
        self.ht = _band(PeriodType.HIGH, time(6), time(22), "0.30")
        self.nt = _band(PeriodType.LOW, time(22), time(6), "0.20")

    def test_night_hours_bill_at_nt(self):
        for hour in (22, 23, 0, 2, 5):
            self.assertIs(resolve_band([self.ht, self.nt], _at(hour)), self.nt, hour)

    def test_day_hours_still_bill_at_ht(self):
        for hour in (6, 12, 21):
            self.assertIs(resolve_band([self.ht, self.nt], _at(hour)), self.ht, hour)

    def test_the_weekday_is_the_timestamps_own(self):
        """A weekday-only night band covers Friday 00:00–06:00 and 22:00–24:00,
        not Saturday early morning — the same meaning the VSE importer gives
        the two rows it splits such a window into."""
        weekday_nt = _band(PeriodType.LOW, time(22), time(6), "0.20", weekdays="0,1,2,3,4")
        weekend = _band(PeriodType.BAND, time(0), time(0), "0.10", weekdays="5,6")
        bands = [self.ht, weekday_nt, weekend]
        friday, saturday = date(2026, 3, 20), date(2026, 3, 21)

        self.assertIs(resolve_band(bands, _at(2, day=friday)), weekday_nt)
        self.assertIs(resolve_band(bands, _at(23, day=friday)), weekday_nt)
        self.assertIs(resolve_band(bands, _at(2, day=saturday)), weekend)


class EngineUsesWrappedWindowsTests(TestCase):
    def test_a_stored_night_band_prices_the_night(self):
        owner = make_user("midnight_owner", UserRole.ZEV_OWNER)
        zev = Zev.objects.create(name="Midnight ZEV", owner=owner, zev_type="zev")
        tariff = Tariff.objects.create(
            zev=zev, name="Grid", category=TariffCategory.ENERGY,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.HIGH,
            price_chf_per_kwh=Decimal("0.30"), time_from=time(6), time_to=time(22),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.LOW,
            price_chf_per_kwh=Decimal("0.20"), time_from=time(22), time_to=time(6),
        )

        self.assertEqual(_resolve_tariff_band(tariff, _at(2)).price_chf_per_kwh, Decimal("0.20000"))
        self.assertEqual(_resolve_tariff_band(tariff, _at(23)).price_chf_per_kwh, Decimal("0.20000"))
        self.assertEqual(_resolve_tariff_band(tariff, _at(12)).price_chf_per_kwh, Decimal("0.30000"))
