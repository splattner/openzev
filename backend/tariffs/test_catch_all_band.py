"""A band without a time window prices "all other hours" (issue #1109).

"HT is Mon-Fri 07:00-21:00, NT is everything else" is the usual Swiss shape.
Before, an NT band entered without a window never matched, and every hour HT
did not cover was billed at whichever band happened to sort first (HT). Now a
non-flat band without a complete window is the catch-all of its months and
weekdays; a tariff without one prices exactly as before.

See docs/specs/2026-03-tariffs-and-billing-engine.md §3.2.
"""
from datetime import date, datetime, time
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.band_labels import band_description, band_recurrence, band_window, translations_for
from invoices.contract_translations import CONTRACT_TRANSLATIONS
from invoices.engine import _resolve_tariff_band
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory, TariffPeriod
from tariffs.periods import average_percentage, has_window, is_catch_all, resolve_band
from testing.helpers import authenticate, create_managed_zev, make_user

WINTER = "1,2,3,10,11,12"
SUMMER = "4,5,6,7,8,9"
WEEKDAYS = "0,1,2,3,4"

# 2026-03-02 is a Monday, 2026-03-07 a Saturday.
MONDAY = date(2026, 3, 2)
SATURDAY = date(2026, 3, 7)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def ht(price="0.29500", **extra):
    return TariffPeriod(
        period_type=PeriodType.HIGH, price_chf_per_kwh=Decimal(price),
        time_from=time(7, 0), time_to=time(21, 0), weekdays=WEEKDAYS, **extra,
    )


def nt(price="0.22500", **extra):
    return TariffPeriod(period_type=PeriodType.LOW, price_chf_per_kwh=Decimal(price), **extra)


def price_at(periods, ts):
    band = resolve_band(periods, ts)
    return band.price_chf_per_kwh if band is not None else None


class CatchAllHelperTests(SimpleTestCase):
    def test_a_non_flat_band_without_both_times_is_a_catch_all(self):
        self.assertTrue(is_catch_all(nt()))
        self.assertTrue(is_catch_all(TariffPeriod(period_type=PeriodType.BAND, time_from=time(7, 0))))
        self.assertFalse(is_catch_all(ht()))

    def test_a_flat_band_is_never_a_catch_all(self):
        self.assertFalse(is_catch_all(TariffPeriod(period_type=PeriodType.FLAT)))

    def test_has_window_needs_both_ends(self):
        self.assertTrue(has_window(ht()))
        self.assertFalse(has_window(TariffPeriod(time_to=time(7, 0))))


class ResolveCatchAllTests(SimpleTestCase):
    def test_nt_without_a_window_prices_nights_and_weekends(self):
        periods = [ht(), nt()]

        self.assertEqual(price_at(periods, at(MONDAY, 3)), Decimal("0.22500"))
        self.assertEqual(price_at(periods, at(MONDAY, 12)), Decimal("0.29500"))
        self.assertEqual(price_at(periods, at(MONDAY, 21)), Decimal("0.22500"))
        self.assertEqual(price_at(periods, at(SATURDAY, 12)), Decimal("0.22500"))

    def test_the_order_of_the_bands_does_not_matter(self):
        self.assertEqual(price_at([nt(), ht()], at(MONDAY, 12)), Decimal("0.29500"))
        self.assertEqual(price_at([nt(), ht()], at(SATURDAY, 12)), Decimal("0.22500"))

    def test_a_band_type_and_a_high_band_can_be_the_catch_all_too(self):
        rest = TariffPeriod(period_type=PeriodType.BAND, price_chf_per_kwh=Decimal("0.10"))
        low = TariffPeriod(
            period_type=PeriodType.LOW, price_chf_per_kwh=Decimal("0.20"),
            time_from=time(21, 0), time_to=time(7, 0),
        )
        self.assertEqual(price_at([low, rest], at(MONDAY, 12)), Decimal("0.10"))
        self.assertEqual(price_at([low, rest], at(MONDAY, 22)), Decimal("0.20"))

        rest_high = TariffPeriod(period_type=PeriodType.HIGH, price_chf_per_kwh=Decimal("0.40"))
        self.assertEqual(price_at([low, rest_high], at(MONDAY, 12)), Decimal("0.40"))

    def test_each_season_uses_its_own_catch_all(self):
        periods = [
            ht("0.30", months=WINTER), nt("0.20", months=WINTER),
            ht("0.25", months=SUMMER), nt("0.15", months=SUMMER),
        ]
        winter_day, summer_day = date(2026, 3, 2), date(2026, 7, 6)  # both Mondays

        self.assertEqual(price_at(periods, at(winter_day, 3)), Decimal("0.20"))
        self.assertEqual(price_at(periods, at(winter_day, 12)), Decimal("0.30"))
        self.assertEqual(price_at(periods, at(summer_day, 3)), Decimal("0.15"))
        self.assertEqual(price_at(periods, at(summer_day, 12)), Decimal("0.25"))

    def test_a_catch_all_in_another_season_does_not_apply(self):
        """Winter has HT only: nothing in winter catches the night, so the
        summer catch-all must not either, and the first band prices it."""
        periods = [ht("0.30", months=WINTER), nt("0.15", months=SUMMER)]

        self.assertEqual(price_at(periods, at(date(2026, 3, 2), 3)), Decimal("0.30"))

    def test_a_catch_all_restricted_to_weekdays_applies_on_those_days_only(self):
        periods = [ht(), nt(weekdays="5,6")]

        self.assertEqual(price_at(periods, at(SATURDAY, 12)), Decimal("0.22500"))
        # Monday 03:00: no window, and the catch-all is weekend only, so the
        # old fallback (first band) prices it.
        self.assertEqual(price_at(periods, at(MONDAY, 3)), Decimal("0.29500"))

    def test_a_tariff_without_a_catch_all_keeps_the_first_band_fallback(self):
        night = TariffPeriod(
            period_type=PeriodType.LOW, price_chf_per_kwh=Decimal("0.20"),
            time_from=time(22, 0), time_to=time(6, 0),
        )
        periods = [ht(), night]

        # 18:00 on a Saturday matches neither window: the first band prices it.
        self.assertEqual(price_at(periods, at(SATURDAY, 18)), Decimal("0.29500"))

    def test_a_flat_band_still_short_circuits_its_months(self):
        flat = TariffPeriod(period_type=PeriodType.FLAT, price_chf_per_kwh=Decimal("0.18"), months=WINTER)
        periods = [flat, ht("0.25", months=SUMMER), nt("0.15", months=SUMMER)]

        self.assertEqual(price_at(periods, at(date(2026, 3, 2), 3)), Decimal("0.18"))
        self.assertEqual(price_at(periods, at(date(2026, 7, 6), 3)), Decimal("0.15"))

    def test_a_half_open_window_is_a_catch_all_not_a_window(self):
        half = TariffPeriod(period_type=PeriodType.LOW, price_chf_per_kwh=Decimal("0.20"), time_from=time(21, 0))

        self.assertEqual(price_at([ht(), half], at(MONDAY, 3)), Decimal("0.20"))

    def test_a_percentage_band_catch_all_resolves_the_same_way(self):
        periods = [
            TariffPeriod(period_type=PeriodType.HIGH, percentage=Decimal("80"), time_from=time(7, 0),
                         time_to=time(21, 0), weekdays=WEEKDAYS),
            TariffPeriod(period_type=PeriodType.LOW, percentage=Decimal("60")),
        ]

        self.assertEqual(resolve_band(periods, at(MONDAY, 12)).percentage, Decimal("80"))
        self.assertEqual(resolve_band(periods, at(MONDAY, 3)).percentage, Decimal("60"))
        self.assertEqual(resolve_band(periods, at(SATURDAY, 12)).percentage, Decimal("60"))


class CatchAllEngineTests(TestCase):
    """The engine and the average go through the same resolution."""

    def setUp(self):
        self.owner = make_user("catch_all_owner", UserRole.USER)
        self.zev = create_managed_zev(name="Catch-all ZEV", owner=self.owner, zev_type="zev")

    def _tariff(self, billing_mode, high, low):
        tariff = Tariff.objects.create(
            zev=self.zev, name="HT/NT", category=TariffCategory.ENERGY,
            billing_mode=billing_mode, energy_type=EnergyType.GRID, valid_from=date(2026, 1, 1),
        )
        TariffPeriod.objects.create(
            tariff=tariff, period_type=PeriodType.HIGH, time_from=time(7, 0), time_to=time(21, 0),
            weekdays=WEEKDAYS, **high,
        )
        TariffPeriod.objects.create(tariff=tariff, period_type=PeriodType.LOW, **low)
        return tariff

    def test_the_engine_prices_the_demo_grid_tariff_at_nt_outside_ht_hours(self):
        """Shaped like the seed_demo "Grid Energy HT/NT" tariff: HT Mon-Fri
        07:00-21:00 and an NT band with no window, data unchanged."""
        from zev.management.commands.seed_demo import SECOND_DEMO_TARIFF_SPECS

        spec = next(entry for entry in SECOND_DEMO_TARIFF_SPECS if entry["name"] == "Grid Energy HT/NT")
        tariff = Tariff.objects.create(
            zev=self.zev, name=spec["name"], category=spec["category"], billing_mode=spec["billing_mode"],
            energy_type=spec["energy_type"], valid_from=date(2026, 1, 1),
        )
        for period in spec["periods"]:
            TariffPeriod.objects.create(tariff=tariff, **period)

        def price(ts):
            return _resolve_tariff_band(tariff, ts).price_chf_per_kwh

        self.assertEqual(price(at(MONDAY, 12)), Decimal("0.29500"))
        self.assertEqual(price(at(MONDAY, 23)), Decimal("0.22500"))
        self.assertEqual(price(at(SATURDAY, 12)), Decimal("0.22500"))

    def test_average_percentage_counts_the_catch_all_for_the_remaining_hours(self):
        tariff = self._tariff(BillingMode.PERCENTAGE_OF_ENERGY, {"percentage": Decimal("100")}, {"percentage": Decimal("50")})

        # HT covers 14 h x 5 days = 70 of 168 weekly hours; NT the other 98.
        expected = (Decimal(70) * 100 + Decimal(98) * 50) / 168
        self.assertAlmostEqual(float(average_percentage(tariff)), float(expected), delta=0.5)


class CatchAllValidationTests(TestCase):
    def setUp(self):
        self.admin = make_user("catch_all_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)
        self.zev = create_managed_zev(name="Validation ZEV", owner=self.admin, zev_type="zev")
        self.tariff = Tariff.objects.create(
            zev=self.zev, name="Grid", category=TariffCategory.GRID_FEES,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            valid_from=date(2026, 1, 1),
        )

    def _post(self, **overrides):
        payload = {"tariff": str(self.tariff.id), "price_chf_per_kwh": "0.20", "period_type": "low"}
        payload.update(overrides)
        return self.client.post("/api/v1/tariffs/periods/", payload, format="json")

    def test_exactly_one_time_is_rejected_on_the_missing_field(self):
        response = self._post(time_from="07:00")
        self.assertEqual(response.status_code, 400)
        self.assertIn("time_to", response.data)

        response = self._post(time_to="07:00")
        self.assertEqual(response.status_code, 400)
        self.assertIn("time_from", response.data)

    def test_neither_time_is_accepted(self):
        self.assertEqual(self._post().status_code, 201)

    def test_two_catch_alls_sharing_months_and_weekdays_are_rejected(self):
        self._post()

        response = self._post(period_type="high")

        self.assertEqual(response.status_code, 400)
        self.assertIn("time_from", response.data)
        self.assertIn("1,2,3,4,5,6,7,8,9,10,11,12", str(response.data["time_from"]))

    def test_two_catch_alls_in_disjoint_seasons_are_accepted(self):
        self.assertEqual(self._post(months=WINTER).status_code, 201)
        self.assertEqual(self._post(months=SUMMER).status_code, 201)

    def test_two_catch_alls_on_disjoint_weekdays_are_accepted(self):
        self.assertEqual(self._post(weekdays=WEEKDAYS).status_code, 201)
        self.assertEqual(self._post(weekdays="5,6").status_code, 201)

    def test_overlapping_weekdays_in_the_same_season_are_rejected(self):
        self._post(weekdays="0,1,2")

        self.assertEqual(self._post(weekdays="2,3").status_code, 400)

    def test_a_catch_all_beside_windowed_bands_is_accepted(self):
        self._post(period_type="high", time_from="07:00", time_to="21:00", weekdays=WEEKDAYS)

        self.assertEqual(self._post().status_code, 201)

    def test_editing_the_existing_catch_all_does_not_collide_with_itself(self):
        created = self._post()

        response = self.client.patch(
            f"/api/v1/tariffs/periods/{created.data['id']}/", {"price_chf_per_kwh": "0.25"}, format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)

    def test_clearing_a_window_into_a_second_catch_all_is_rejected(self):
        self._post()
        windowed = self._post(period_type="high", time_from="07:00", time_to="21:00")

        response = self.client.patch(
            f"/api/v1/tariffs/periods/{windowed.data['id']}/", {"time_from": None, "time_to": None}, format="json",
        )

        self.assertEqual(response.status_code, 400)


class CatchAllLabelTests(SimpleTestCase):
    def test_every_language_has_the_other_hours_text(self):
        for lang, tr in CONTRACT_TRANSLATIONS.items():
            self.assertIn("tariff_other_hours", tr, lang)

    def test_a_named_catch_all_names_the_hours_in_the_recurrence(self):
        for lang, hours in (("de", "alle übrigen Zeiten"), ("en", "all other hours")):
            tr = translations_for(lang)
            self.assertEqual(band_recurrence(nt(), tr), hours)
            self.assertEqual(band_recurrence(nt(weekdays="5,6"), tr), f"{tr['tariff_weekdays_short'][5]}–{tr['tariff_weekdays_short'][6]}, {hours}")

    def test_an_unnamed_band_catch_all_is_named_once(self):
        rest = TariffPeriod(period_type=PeriodType.BAND, price_chf_per_kwh=Decimal("0.10"))
        tr = translations_for("en")

        self.assertEqual(band_window(rest, tr), "all other hours")
        self.assertEqual(band_description(rest, tr), "all other hours")
        self.assertEqual(band_recurrence(rest, tr), "")

    def test_a_labelled_band_catch_all_keeps_its_label(self):
        rest = TariffPeriod(period_type=PeriodType.BAND, label="Night", price_chf_per_kwh=Decimal("0.10"))
        tr = translations_for("de")

        self.assertEqual(band_description(rest, tr), "Night")
        self.assertEqual(band_recurrence(rest, tr), "alle übrigen Zeiten")

    def test_a_windowed_band_reads_as_before(self):
        self.assertEqual(band_recurrence(ht(), translations_for("en")), "Mon–Fri, 07:00–21:00")
