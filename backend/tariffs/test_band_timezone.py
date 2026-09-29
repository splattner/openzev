"""Tariff bands are read in Swiss local time, not UTC.

A band's hours, weekdays and months describe the Swiss wall clock (HT 06–22
means 06:00 in Zurich). Readings reach the engine as UTC-aware datetimes —
that is what the ORM returns with ``USE_TZ`` — so resolving a band on the
UTC components shifts every boundary by one hour in winter and two in summer.
The other band tests pass naive datetimes and never see this.
"""
from datetime import datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from tariffs.models import PeriodType, TariffPeriod
from tariffs.periods import resolve_band

ZURICH = ZoneInfo("Europe/Zurich")


def _utc(year, month, day, hour, minute=0):
    """A Swiss wall-clock moment as the UTC-aware datetime the ORM returns."""
    local = datetime(year, month, day, hour, minute, tzinfo=ZURICH)
    return local.astimezone(timezone.utc)


def _band(period_type, start, end, price, weekdays="", months=""):
    return TariffPeriod(
        period_type=period_type, time_from=start, time_to=end,
        price_chf_per_kwh=Decimal(price), weekdays=weekdays, months=months,
    )


class BandsResolveInSwissLocalTimeTests(SimpleTestCase):
    def setUp(self):
        self.ht = _band(PeriodType.HIGH, time(6), time(22), "0.30")
        self.nt = _band(PeriodType.LOW, time(22), time(6), "0.20")

    def test_summer_morning_after_six_is_ht(self):
        # 06:30 CEST is 04:30 UTC.
        self.assertIs(resolve_band([self.ht, self.nt], _utc(2026, 7, 1, 6, 30)), self.ht)

    def test_summer_evening_after_ten_is_nt(self):
        # 22:30 CEST is 20:30 UTC.
        self.assertIs(resolve_band([self.ht, self.nt], _utc(2026, 7, 1, 22, 30)), self.nt)

    def test_winter_morning_after_six_is_ht(self):
        # 06:30 CET is 05:30 UTC.
        self.assertIs(resolve_band([self.ht, self.nt], _utc(2026, 1, 14, 6, 30)), self.ht)

    def test_weekday_is_the_swiss_one(self):
        # Saturday 00:30 CET is Friday 23:30 UTC.
        weekday = _band(PeriodType.HIGH, time(0), time(0), "0.30", weekdays="0,1,2,3,4")
        weekend = _band(PeriodType.LOW, time(0), time(0), "0.10", weekdays="5,6")
        self.assertIs(resolve_band([weekday, weekend], _utc(2026, 1, 3, 0, 30)), weekend)

    def test_month_is_the_swiss_one(self):
        # 1 April 00:30 CEST is 31 March 22:30 UTC.
        winter = _band(PeriodType.FLAT, None, None, "0.30", months="10,11,12,1,2,3")
        summer = _band(PeriodType.FLAT, None, None, "0.20", months="4,5,6,7,8,9")
        self.assertIs(resolve_band([winter, summer], _utc(2026, 4, 1, 0, 30)), summer)
