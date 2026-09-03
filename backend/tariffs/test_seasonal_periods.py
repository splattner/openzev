"""Seasonal price bands: a `TariffPeriod` that applies only in some months.

Winter/summer pricing is ordinary in Switzerland, and until now a ZEV on such
a tariff had to be billed from a hand-entered approximation. The month mask
mirrors the `weekdays` field exactly — blank means every month — so every
tariff that predates it keeps behaving identically, which is most of what
these tests are checking.

See docs/specs/2026-03-tariffs-and-billing-engine.md §3.2 and issue #527.
"""
from datetime import date, datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.engine import _get_tariff_price
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory, TariffPeriod
from tariffs.periods import ALL_MONTHS, month_ranges, months_of, weekdays_of
from testing.helpers import authenticate, make_user
from zev.models import Zev

WINTER = "1,2,3,10,11,12"
SUMMER = "4,5,6,7,8,9"


class MonthRangeTests(SimpleTestCase):
    """Ranges are for humans: a contract that prints "Jan–Mar, Oct–Dec" makes
    the reader work out for themselves that it is one season."""

    def test_a_season_spanning_new_year_is_one_range(self):
        self.assertEqual(month_ranges({10, 11, 12, 1, 2, 3}), [(10, 3)])

    def test_a_season_inside_the_year_is_one_range(self):
        self.assertEqual(month_ranges({4, 5, 6, 7, 8, 9}), [(4, 9)])

    def test_every_month_has_no_range_to_name(self):
        self.assertEqual(month_ranges(ALL_MONTHS), [])
        self.assertEqual(month_ranges(set()), [])

    def test_genuinely_disjoint_months_stay_separate(self):
        self.assertEqual(month_ranges({1, 2, 6, 7, 12}), [(6, 7), (12, 2)])


class PeriodRecurrenceTests(SimpleTestCase):
    """Blank means "no restriction", so the common band needs no parsing at
    all and the two axes read the same way."""

    def test_a_blank_mask_means_everything(self):
        period = TariffPeriod(months="", weekdays="")

        self.assertEqual(months_of(period), ALL_MONTHS)
        self.assertEqual(weekdays_of(period), frozenset(range(7)))

    def test_a_set_mask_is_parsed_once_and_remembered(self):
        """The engine reads this per reading — tens of thousands of times for a
        year of 15-minute data — so it must not re-split the string each time."""
        period = TariffPeriod(months=WINTER)

        first = months_of(period)

        self.assertEqual(first, {1, 2, 3, 10, 11, 12})
        self.assertIs(months_of(period), first)


class SeasonalPricingTests(TestCase):
    """What the engine actually charges. `_get_tariff_price` is the single
    place a season can change a number on an invoice."""

    def setUp(self):
        self.owner = make_user("seasonal_owner", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(name="Seasonal ZEV", owner=self.owner, zev_type="zev")

    def _tariff(self, *periods) -> Tariff:
        tariff = Tariff.objects.create(
            zev=self.zev, name=f"Grid {len(Tariff.objects.all())}",
            category=TariffCategory.GRID_FEES, billing_mode=BillingMode.ENERGY,
            energy_type=EnergyType.GRID, valid_from=date(2026, 1, 1),
        )
        for kwargs in periods:
            TariffPeriod.objects.create(tariff=tariff, **kwargs)
        return tariff

    def _price(self, tariff, month, hour=12, day=15):
        return _get_tariff_price(tariff, datetime(2026, month, day, hour))

    def test_a_winter_flat_band_does_not_price_july(self):
        """The regression this whole change turns on. The engine short-circuits
        on a flat band before looking at any window, so a seasonal flat band
        that skipped the month check would bill its winter price all year."""
        tariff = self._tariff(
            {"period_type": "flat", "price_chf_per_kwh": Decimal("0.20"), "months": WINTER},
            {"period_type": "flat", "price_chf_per_kwh": Decimal("0.10"), "months": SUMMER},
        )

        self.assertEqual(self._price(tariff, month=1), Decimal("0.20000"))
        self.assertEqual(self._price(tariff, month=7), Decimal("0.10000"))

    def test_seasons_and_time_bands_combine(self):
        """Four bands, four prices — which no single tariff could express
        before, because HT and NT were the only two slots there were."""
        tariff = self._tariff(
            {"period_type": "high", "price_chf_per_kwh": Decimal("0.24"),
             "time_from": "07:00", "time_to": "22:00", "months": WINTER},
            {"period_type": "low", "price_chf_per_kwh": Decimal("0.18"),
             "time_from": "22:00", "time_to": "23:59", "months": WINTER},
            {"period_type": "high", "price_chf_per_kwh": Decimal("0.14"),
             "time_from": "07:00", "time_to": "22:00", "months": SUMMER},
            {"period_type": "low", "price_chf_per_kwh": Decimal("0.11"),
             "time_from": "22:00", "time_to": "23:59", "months": SUMMER},
        )

        self.assertEqual(self._price(tariff, month=1, hour=12), Decimal("0.24000"))
        self.assertEqual(self._price(tariff, month=1, hour=23), Decimal("0.18000"))
        self.assertEqual(self._price(tariff, month=7, hour=12), Decimal("0.14000"))
        self.assertEqual(self._price(tariff, month=7, hour=23), Decimal("0.11000"))

    def test_a_band_with_no_months_still_prices_every_month(self):
        """Every tariff that existed before this change is one of these, so it
        is the assertion that says nothing was broken."""
        tariff = self._tariff(
            {"period_type": "flat", "price_chf_per_kwh": Decimal("0.15")},
        )

        for month in range(1, 13):
            self.assertEqual(self._price(tariff, month=month), Decimal("0.15000"))

    def test_an_unpriced_hour_falls_back_within_its_own_season(self):
        """The first-band fallback is unchanged, but it now prefers a band that
        at least applies this month: charging a January night at the summer
        rate would be the worse of two guesses."""
        tariff = self._tariff(
            {"period_type": "high", "price_chf_per_kwh": Decimal("0.24"),
             "time_from": "07:00", "time_to": "22:00", "months": WINTER},
            {"period_type": "flat", "price_chf_per_kwh": Decimal("0.10"), "months": SUMMER},
        )

        self.assertEqual(self._price(tariff, month=1, hour=3), Decimal("0.24000"))

    def test_weekday_and_month_restrictions_both_apply(self):
        tariff = self._tariff(
            {"period_type": "high", "price_chf_per_kwh": Decimal("0.30"),
             "time_from": "00:00", "time_to": "23:59", "weekdays": "0,1,2,3,4", "months": WINTER},
            {"period_type": "low", "price_chf_per_kwh": Decimal("0.12"),
             "time_from": "00:00", "time_to": "23:59", "months": WINTER},
        )

        # 2026-01-15 is a Thursday, 2026-01-17 a Saturday.
        self.assertEqual(self._price(tariff, month=1, day=15), Decimal("0.30000"))
        self.assertEqual(self._price(tariff, month=1, day=17), Decimal("0.12000"))


class MonthMaskValidationTests(TestCase):
    """The engine parses these strings with a bare `int()`. Anything it cannot
    read has to be refused at entry, not discovered at invoice time."""

    def setUp(self):
        self.admin = make_user("seasonal_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)
        self.zev = Zev.objects.create(name="Validation ZEV", owner=self.admin, zev_type="zev")
        self.tariff = Tariff.objects.create(
            zev=self.zev, name="Grid", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )

    def _post(self, **overrides):
        payload = {
            "tariff": str(self.tariff.id), "period_type": "flat",
            "price_chf_per_kwh": "0.20",
        }
        payload.update(overrides)
        return self.client.post("/api/v1/tariffs/periods/", payload, format="json")

    def test_a_valid_month_mask_is_accepted(self):
        response = self._post(months=WINTER)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(TariffPeriod.objects.get().months, WINTER)

    def test_blank_months_stay_blank(self):
        response = self._post(months="")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(TariffPeriod.objects.get().months, "")

    def test_a_month_out_of_range_is_rejected(self):
        response = self._post(months="1,13")

        self.assertEqual(response.status_code, 400)
        self.assertIn("months", response.data)

    def test_a_non_numeric_month_is_rejected(self):
        response = self._post(months="Jan,Feb")

        self.assertEqual(response.status_code, 400)

    def test_a_weekday_out_of_range_is_rejected_too(self):
        """`weekdays` went unvalidated for a long time, and the engine parses
        it the same way, so a stray value there was a crash at invoice time."""
        response = self._post(weekdays="0,9")

        self.assertEqual(response.status_code, 400)
        self.assertIn("weekdays", response.data)
