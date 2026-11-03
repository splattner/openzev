"""Combined tariff progression (docs/specs/2026-11-tariff-progression.md).

The computation is checked against hand-worked numbers, and against the invoice
engine's own pricing for sample timestamps, so the two cannot drift apart.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from accounts.models import VatRate
from allocation.validity import period_window, wall_clock
from invoices import tariff_progression
from invoices.engine import (
    InvoiceGenerationContext, ItemAccumulator, TariffResolver, _price_energy, _tariff_bears_input_vat,
)
from invoices.tariff_progression import TooManyBands, build_progression
from tariffs.dynamic.models import DynamicPricePoint, DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, PeriodType, Tariff, TariffCategory
from testing import factories
from testing.helpers import clear_vat_rates
from zev.models import VatMode

pytestmark = pytest.mark.django_db

D = Decimal
TODAY = date(2026, 3, 15)
ALL_MONTHS = list(range(1, 13))
ALL_DAYS = list(range(7))


@pytest.fixture(autouse=True)
def seeded_vat_rates_removed(db):
    """A migration seeds the real Swiss rates; these tests choose their own."""
    clear_vat_rates()


@pytest.fixture
def zev():
    return factories.ZevFactory()


def flat(price):
    return {"period_type": PeriodType.FLAT, "price_chf_per_kwh": D(price)}


def ht(price, start="07:00", end="20:00", weekdays="0,1,2,3,4", months=""):
    return {
        "period_type": PeriodType.HIGH, "price_chf_per_kwh": D(price),
        "time_from": start, "time_to": end, "weekdays": weekdays, "months": months,
    }


def nt(price, months=""):
    """A low band with no window: it prices the hours the high band does not."""
    return {"period_type": PeriodType.LOW, "price_chf_per_kwh": D(price), "months": months}


def make(zev, name, bands, *, category=TariffCategory.ENERGY, energy_type=EnergyType.GRID,
         mode=BillingMode.ENERGY, valid_from=date(2025, 1, 1), valid_to=None, **extra):
    tariff = factories.TariffFactory(
        zev=zev, name=name, category=category, energy_type=energy_type, billing_mode=mode,
        valid_from=valid_from, valid_to=valid_to, **extra,
    )
    for band in bands:
        factories.TariffPeriodFactory(tariff=tariff, **band)
    return tariff


def percentage(share, **kwargs):
    return {"period_type": PeriodType.FLAT, "price_chf_per_kwh": None, "percentage": D(share), **kwargs}


def make_percentage(zev, name, share, **kwargs):
    kwargs.setdefault("energy_type", EnergyType.LOCAL)
    return make(zev, name, [percentage(share)], mode=BillingMode.PERCENTAGE_OF_ENERGY, **kwargs)


def progress(zev, energy_type="grid", **kwargs):
    zev.refresh_from_db()
    tariffs = Tariff.objects.filter(zev=zev).prefetch_related("periods")
    kwargs.setdefault("today", TODAY)
    return build_progression(zev, tariffs, energy_type, **kwargs)


def set_vat(zev, mode, rate="0.0810"):
    zev.vat_mode = mode
    if mode == VatMode.REGISTERED:
        zev.vat_number = "CHE-123.456.789 MWST"
    zev.save()
    if rate is not None:
        VatRate.objects.create(rate=D(rate), valid_from=date(2020, 1, 1))


def totals(result):
    return [[slot["net"] for slot in interval["slots"]] for interval in result["intervals"]]


def slot_at(result, interval_index, moment):
    """The slot whose rules cover ``moment`` (a wall-clock datetime)."""
    clock = f"{moment.hour:02d}:{moment.minute:02d}"
    lines = {line["key"]: line["rules"] for line in result["lines"]}
    for slot in result["intervals"][interval_index]["slots"]:
        for rule in lines[slot["line"]]:
            if moment.month not in rule["months"] or moment.weekday() not in rule["weekdays"]:
                continue
            for window in rule["windows"]:
                start, end = window["from"], window["to"]
                inside = start <= clock < end if start < end else (clock >= start or clock < end)
                if inside:
                    return slot
    raise AssertionError(f"no slot covers {moment}")


class TestIntervals:
    def test_sum_changes_at_each_version_boundary(self, zev):
        make(zev, "Energie", [flat("0.20")], valid_to=date(2025, 12, 31))
        make(zev, "Energie", [flat("0.22")], valid_from=date(2026, 1, 1))
        make(zev, "Netz", [flat("0.05")], category=TariffCategory.GRID_FEES, valid_to=date(2025, 6, 30))
        make(zev, "Netz", [flat("0.06")], category=TariffCategory.GRID_FEES, valid_from=date(2025, 7, 1))

        result = progress(zev)

        assert [(i["from"], i["to"]) for i in result["intervals"]] == [
            ("2025-01-01", "2025-06-30"), ("2025-07-01", "2025-12-31"), ("2026-01-01", "2026-03-15"),
        ]
        assert totals(result) == [["0.25000"], ["0.26000"], ["0.28000"]]

    def test_valid_to_is_inclusive(self, zev):
        make(zev, "Energie", [flat("0.20")], valid_to=date(2025, 3, 31))
        make(zev, "Energie", [flat("0.25")], valid_from=date(2025, 4, 1))

        first, second = progress(zev)["intervals"]

        assert first["to"] == "2025-03-31"
        assert second["from"] == "2025-04-01"

    def test_open_ended_version_runs_to_today(self, zev):
        make(zev, "Energie", [flat("0.20")])

        result = progress(zev)

        assert (result["from"], result["to"]) == ("2025-01-01", "2026-03-15")

    def test_range_clips_intervals(self, zev):
        make(zev, "Energie", [flat("0.20")], valid_to=date(2025, 6, 30))
        make(zev, "Energie", [flat("0.25")], valid_from=date(2025, 7, 1))

        result = progress(zev, date_from=date(2025, 3, 1), date_to=date(2025, 9, 30))

        assert [(i["from"], i["to"]) for i in result["intervals"]] == [
            ("2025-03-01", "2025-06-30"), ("2025-07-01", "2025-09-30"),
        ]

    def test_gap_gives_empty_interval(self, zev):
        make(zev, "Energie", [flat("0.20")], valid_to=date(2025, 3, 31))
        make(zev, "Energie", [flat("0.20")], valid_from=date(2025, 6, 1))

        gap = progress(zev)["intervals"][1]

        assert (gap["from"], gap["to"]) == ("2025-04-01", "2025-05-31")
        assert gap["slots"] == []
        assert gap["missing_categories"] == ["energy"]

    def test_unchanged_price_new_version_is_still_an_interval(self, zev):
        make(zev, "Energie", [flat("0.20")], valid_to=date(2025, 12, 31))
        make(zev, "Energie", [flat("0.20")], valid_from=date(2026, 1, 1))

        assert totals(progress(zev)) == [["0.20000"], ["0.20000"]]

    def test_no_tariffs_gives_an_empty_progression(self, zev):
        result = progress(zev)

        assert (result["intervals"], result["lines"], result["fixed_fees"]) == ([], [], [])


class TestSlots:
    def test_flat_tariffs_make_one_line(self, zev):
        make(zev, "Energie", [flat("0.20")])
        make(zev, "Netz", [flat("0.05")], category=TariffCategory.GRID_FEES)

        result = progress(zev)

        assert result["lines"] == [{"key": "line-1", "rules": [
            {"months": ALL_MONTHS, "weekdays": ALL_DAYS, "windows": [{"from": "00:00", "to": "24:00"}]},
        ]}]
        assert totals(result) == [["0.25000"]]

    def test_ht_nt_beside_a_flat_tariff_gives_two_lines(self, zev):
        make(zev, "Energie", [ht("0.30"), nt("0.20")])
        make(zev, "Netz", [flat("0.05")], category=TariffCategory.GRID_FEES)

        result = progress(zev)

        assert sorted(totals(result)[0]) == ["0.25000", "0.35000"]
        high = slot_at(result, 0, datetime(2025, 1, 6, 10, 0))
        low = slot_at(result, 0, datetime(2025, 1, 6, 22, 0))
        assert high["net"] == "0.35000" and low["net"] == "0.25000"
        assert slot_at(result, 0, datetime(2025, 1, 5, 10, 0))["line"] == low["line"]

    def test_wrapping_window_is_one_window(self, zev):
        make(zev, "Energie", [ht("0.30"), nt("0.20")])

        result = progress(zev)

        night = slot_at(result, 0, datetime(2025, 1, 6, 22, 0))["line"]
        rules = {line["key"]: line["rules"] for line in result["lines"]}[night]
        assert {"months": ALL_MONTHS, "weekdays": [0, 1, 2, 3, 4],
                "windows": [{"from": "20:00", "to": "07:00"}]} in rules
        assert {"months": ALL_MONTHS, "weekdays": [5, 6],
                "windows": [{"from": "00:00", "to": "24:00"}]} in rules

    def test_misaligned_windows_split_at_both_edges(self, zev):
        make(zev, "Energie", [ht("0.30"), nt("0.20")])
        make(zev, "Netz", [ht("0.08", "06:00", "22:00"), nt("0.04")], category=TariffCategory.GRID_FEES)

        result = progress(zev)

        # 07-20 both high; 06-07 and 20-22 energy low, grid fee high; the rest both low.
        assert sorted(totals(result)[0]) == ["0.24000", "0.28000", "0.38000"]
        assert slot_at(result, 0, datetime(2025, 1, 6, 6, 30))["net"] == "0.28000"
        assert slot_at(result, 0, datetime(2025, 1, 6, 21, 0))["net"] == "0.28000"

    def test_seasonal_bands_split_by_months(self, zev):
        winter = "11,12,1,2,3"
        make(zev, "Energie", [
            ht("0.30", months=winter), nt("0.20", months=winter),
            {**flat("0.15"), "months": "4,5,6,7,8,9,10"},
        ])

        result = progress(zev)

        assert sorted(totals(result)[0]) == ["0.15000", "0.20000", "0.30000"]
        assert slot_at(result, 0, datetime(2025, 7, 7, 10, 0))["net"] == "0.15000"
        assert slot_at(result, 0, datetime(2025, 12, 8, 10, 0))["net"] == "0.30000"
        summer = slot_at(result, 0, datetime(2025, 7, 7, 10, 0))["line"]
        rules = {line["key"]: line["rules"] for line in result["lines"]}[summer]
        assert rules[0]["months"] == [4, 5, 6, 7, 8, 9, 10]

    def test_the_same_when_in_two_intervals_shares_a_line(self, zev):
        make(zev, "Energie", [flat("0.20")], valid_to=date(2025, 12, 31))
        make(zev, "Energie", [flat("0.22")], valid_from=date(2026, 1, 1))

        result = progress(zev)

        assert len(result["lines"]) == 1
        assert {slot["line"] for i in result["intervals"] for slot in i["slots"]} == {"line-1"}

    def test_a_changed_window_starts_a_new_line(self, zev):
        make(zev, "Energie", [ht("0.30"), nt("0.20")], valid_to=date(2025, 12, 31))
        make(zev, "Energie", [ht("0.32", "06:00", "22:00"), nt("0.21")], valid_from=date(2026, 1, 1))

        result = progress(zev)

        before = {slot["line"] for slot in result["intervals"][0]["slots"]}
        after = {slot["line"] for slot in result["intervals"][1]["slots"]}
        assert before.isdisjoint(after)
        assert len(result["lines"]) == 4

    def test_the_all_hours_line_comes_first(self, zev):
        make(zev, "Energie", [ht("0.30"), nt("0.20")], valid_to=date(2025, 12, 31))
        make(zev, "Energie", [flat("0.25")], valid_from=date(2026, 1, 1))

        result = progress(zev)

        assert result["lines"][0]["key"] == "line-1"
        assert result["lines"][0]["rules"][0]["windows"] == [{"from": "00:00", "to": "24:00"}]
        assert result["intervals"][1]["slots"][0]["line"] == "line-1"

    def test_too_many_bands_is_refused(self, zev, monkeypatch):
        make(zev, "Energie", [ht("0.30"), nt("0.20")])
        monkeypatch.setattr(tariff_progression, "MAX_SLOTS_PER_INTERVAL", 1)

        with pytest.raises(TooManyBands):
            progress(zev)


class TestPricing:
    def test_category_subtotals_add_up_to_the_total(self, zev):
        make(zev, "Energie", [flat("0.15")])
        make(zev, "Netz", [flat("0.08")], category=TariffCategory.GRID_FEES)
        make(zev, "Abgaben", [flat("0.02")], category=TariffCategory.LEVIES)
        make(zev, "Zähler", [flat("0.01")], category=TariffCategory.METERING)

        slot = progress(zev)["intervals"][0]["slots"][0]

        assert [(c["category"], c["net"]) for c in slot["categories"]] == [
            ("energy", "0.15000"), ("grid_fees", "0.08000"), ("levies", "0.02000"), ("metering", "0.01000"),
        ]
        assert slot["net"] == "0.26000"
        assert slot["gross"] is None

    def test_components_are_listed_under_their_category(self, zev):
        tariff = make(zev, "Energie", [flat("0.15")])

        component = progress(zev)["intervals"][0]["slots"][0]["categories"][0]["components"][0]

        assert component["tariff_id"] == str(tariff.pk)
        assert (component["name"], component["net"]) == ("Energie", "0.15000")
        assert (component["percentage"], component["base_net"]) == (None, None)

    def test_the_energy_type_filter_excludes_other_types(self, zev):
        make(zev, "Netzstrom", [flat("0.30")])
        make(zev, "Solar", [flat("0.12")], energy_type=EnergyType.LOCAL)

        assert totals(progress(zev, "grid")) == [["0.30000"]]
        assert totals(progress(zev, "local")) == [["0.12000"]]

    def test_feed_in_is_a_separate_view(self, zev):
        make(zev, "Netzstrom", [flat("0.30")])
        make(zev, "Einspeisung", [flat("0.08")], energy_type=EnergyType.FEED_IN)

        assert totals(progress(zev, "feed_in")) == [["0.08000"]]

    def test_a_missing_category_is_reported(self, zev):
        make(zev, "Energie", [flat("0.15")])
        make(zev, "Netz", [flat("0.08")], category=TariffCategory.GRID_FEES, valid_to=date(2025, 3, 31))
        make(zev, "Netz", [flat("0.08")], category=TariffCategory.GRID_FEES, valid_from=date(2025, 7, 1))

        result = progress(zev)

        assert result["expected_categories"] == ["energy", "grid_fees"]
        assert [i["missing_categories"] for i in result["intervals"]] == [[], ["grid_fees"], []]
        assert totals(result) == [["0.23000"], ["0.15000"], ["0.23000"]]

    def test_a_category_that_starts_later_or_has_ended_is_not_missing(self, zev):
        make(zev, "Energie", [flat("0.15")])
        make(zev, "Altlast", [flat("0.01")], category=TariffCategory.LEVIES, valid_to=date(2025, 3, 31))
        make(zev, "Neu", [flat("0.02")], category=TariffCategory.METERING, valid_from=date(2025, 7, 1))

        result = progress(zev)

        assert [i["missing_categories"] for i in result["intervals"]] == [[], [], []]
        assert totals(result) == [["0.16000"], ["0.15000"], ["0.17000"]]

    def test_a_tariff_without_bands_is_incomplete(self, zev):
        make(zev, "Energie", [flat("0.15")])
        empty = make(zev, "Netz", [], category=TariffCategory.GRID_FEES)

        interval = progress(zev)["intervals"][0]

        assert interval["incomplete"] == [{"tariff_id": str(empty.pk), "name": "Netz", "reason": "no_bands"}]
        assert totals({"intervals": [interval]}) == [["0.15000"]]
        assert interval["missing_categories"] == []

    @pytest.mark.parametrize("mode", [VatMode.NOT_REGISTERED, VatMode.REGISTERED, VatMode.INCLUSIVE])
    def test_matches_the_engine_price_for_sample_timestamps(self, zev, mode):
        set_vat(zev, mode)
        rate = D("0.0810")
        make(zev, "Energie", [ht("0.30"), nt("0.20")])
        make(zev, "Netz", [ht("0.08", "06:00", "22:00"), nt("0.04")], category=TariffCategory.GRID_FEES)
        make(zev, "Abgaben", [flat("0.02")], category=TariffCategory.LEVIES)
        make(zev, "Solar", [flat("0.12")], energy_type=EnergyType.LOCAL)
        make_percentage(zev, "Lokalanteil", "65")
        result = progress(zev, "grid")
        local = progress(zev, "local")

        engine = TariffResolver(
            list(Tariff.objects.filter(zev=zev).prefetch_related("periods")),
            input_vat_rate=rate if mode == VatMode.INCLUSIVE else D("0"),
        )
        for view, energy_type in ((result, "grid"), (local, "local")):
            for moment in (datetime(2025, 1, 6, 10, 0), datetime(2025, 1, 6, 6, 30),
                           datetime(2025, 1, 6, 22, 0), datetime(2025, 1, 5, 11, 0)):
                accumulator = ItemAccumulator()
                _price_energy(accumulator, engine, energy_type, D("1"), moment, moment.date(), sign=1)
                net = sum((entry["total"] for entry in accumulator), D("0"))
                if mode == VatMode.INCLUSIVE:
                    billed = sum(
                        (entry["total"] * (1 + rate) if _tariff_bears_input_vat(entry["tariff"]) else entry["total"]
                         for entry in accumulator), D("0"),
                    )
                elif mode == VatMode.REGISTERED:
                    billed = net * (1 + rate)
                else:
                    billed = None

                slot = slot_at(view, 0, moment)

                if mode == VatMode.INCLUSIVE:
                    assert D(slot["gross"]) == billed.quantize(D("0.00001"))
                else:
                    assert D(slot["net"]) == net.quantize(D("0.00001"))
                    assert (slot["gross"] is None) == (billed is None)
                    if billed is not None:
                        assert D(slot["gross"]) == billed.quantize(D("0.00001"))


class TestPercentage:
    def test_a_percentage_uses_the_grid_band_at_the_same_slot(self, zev):
        make(zev, "Netzstrom", [ht("0.30"), nt("0.20")])
        make_percentage(zev, "Lokalanteil", "65")

        result = progress(zev, "local")

        assert sorted(totals(result)[0]) == ["0.13000", "0.19500"]
        slot = slot_at(result, 0, datetime(2025, 1, 6, 10, 0))
        component = slot["categories"][0]["components"][0]
        assert (component["percentage"], component["base_net"], component["net"]) == (
            "65.00", "0.30000", "0.19500",
        )

    def test_a_percentage_follows_a_grid_version_change(self, zev):
        make(zev, "Netzstrom", [flat("0.30")], valid_to=date(2025, 6, 30))
        make(zev, "Netzstrom", [flat("0.40")], valid_from=date(2025, 7, 1))
        make_percentage(zev, "Lokalanteil", "50")

        result = progress(zev, "local")

        assert [(i["from"], i["to"]) for i in result["intervals"]] == [
            ("2025-01-01", "2025-06-30"), ("2025-07-01", "2026-03-15"),
        ]
        assert totals(result) == [["0.15000"], ["0.20000"]]

    def test_a_zero_percent_band_contributes_nothing(self, zev):
        make(zev, "Netzstrom", [flat("0.30")])
        make_percentage(zev, "Lokalanteil", "0")

        slot = progress(zev, "local")["intervals"][0]["slots"][0]

        assert slot["categories"] == []
        assert slot["net"] == "0.00000"

    def test_inclusive_takes_a_share_of_the_gross_grid_base(self, zev):
        set_vat(zev, VatMode.INCLUSIVE)
        make(zev, "Netzstrom", [flat("0.30")])
        make_percentage(zev, "Lokalanteil", "50")

        slot = progress(zev, "local")["intervals"][0]["slots"][0]

        assert (slot["net"], slot["gross"]) == ("0.15000", "0.16215")

    def test_inclusive_never_grosses_a_bearing_percentage_twice(self, zev):
        set_vat(zev, VatMode.INCLUSIVE)
        make(zev, "Netzstrom", [flat("0.30")])
        make_percentage(zev, "Abgabe", "50", category=TariffCategory.LEVIES, energy_type=EnergyType.GRID)

        slot = progress(zev, "grid")["intervals"][0]["slots"][0]

        # grid 0.30 -> 0.3243; levy 50 % of the net base 0.30 -> 0.15 -> 0.16215.
        assert slot["gross"] == "0.48645"


def make_source(tariff_type="grid"):
    return DynamicTariffSource.objects.create(
        label=f"vario {tariff_type}", url="https://api.tariffs.groupe-e.ch/v2/tariffs", api_version="v1_0_5",
        tariff_type=tariff_type, tariff_name="vario",
    )


def seed_prices(source, first, last, price):
    """Quarter-hourly prices for the civil days ``first``..``last``; ``price(local_datetime)``."""
    start, end = period_window(first, last)
    points, cursor = [], start
    while cursor < end:
        local = wall_clock(cursor).replace(tzinfo=None)
        points.append(DynamicPricePoint(
            source=source, valid_from=cursor, valid_to=cursor + timedelta(minutes=15),
            price_chf_per_kwh=D(price(local)),
        ))
        cursor += timedelta(minutes=15)
    DynamicPricePoint.objects.bulk_create(points)


JANUARY = (date(2026, 1, 1), date(2026, 1, 31))


def make_dynamic(zev, name="Spot", *, source=None, tariff_type="grid", **kwargs):
    kwargs.setdefault("category", TariffCategory.GRID_FEES)
    kwargs.setdefault("valid_from", date(2026, 1, 1))
    source = source or make_source(tariff_type)
    return make(zev, name, [], dynamic_source=source, **kwargs), source


class TestDynamic:
    def test_a_dynamic_tariff_is_averaged_per_month(self, zev):
        spot, source = make_dynamic(zev)
        seed_prices(source, date(2026, 1, 1), date(2026, 2, 28), lambda moment: "0.10")

        result = progress(zev, date_from=date(2026, 1, 1), date_to=date(2026, 2, 28))

        assert [(i["from"], i["to"]) for i in result["intervals"]] == [
            ("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28"),
        ]
        assert totals(result) == [["0.10000"], ["0.10000"]]
        component = result["intervals"][0]["slots"][0]["categories"][0]["components"][0]
        assert (component["tariff_id"], component["dynamic"], component["coverage"]) == (str(spot.pk), True, "1.0000")
        assert (component["band_period_id"], component["percentage"]) == (None, None)
        assert result["intervals"][0]["incomplete"] == []

    def test_months_are_breakpoints_only_while_the_tariff_is_in_force(self, zev):
        make_dynamic(zev, valid_from=date(2026, 1, 15), valid_to=date(2026, 3, 10))

        result = progress(zev)

        assert [(i["from"], i["to"]) for i in result["intervals"]] == [
            ("2026-01-15", "2026-01-31"), ("2026-02-01", "2026-02-28"), ("2026-03-01", "2026-03-10"),
        ]

    def test_the_mean_is_added_to_the_static_components(self, zev):
        make(zev, "Energie", [flat("0.15")])
        _, source = make_dynamic(zev)
        seed_prices(source, *JANUARY, lambda moment: "0.10")

        slot = progress(zev, date_from=JANUARY[0], date_to=JANUARY[1])["intervals"][0]["slots"][0]

        assert slot["net"] == "0.25000"
        assert [c["category"] for c in slot["categories"]] == ["energy", "grid_fees"]

    def test_the_mean_matches_the_engine_prices_in_every_slot(self, zev):
        make(zev, "Energie", [ht("0.30"), nt("0.20")])
        spot, source = make_dynamic(zev)
        seed_prices(source, *JANUARY, lambda moment: D("0.10") + D("0.01") * moment.hour
                    + (D("0.005") if moment.weekday() >= 5 else 0))
        result = progress(zev, date_from=JANUARY[0], date_to=JANUARY[1])
        series = InvoiceGenerationContext.build(zev, *JANUARY).dynamic_series(source.pk)

        start, end = period_window(*JANUARY)
        sums, counts = {}, {}
        cursor = start
        while cursor < end:
            local = wall_clock(cursor).replace(tzinfo=None)
            line = slot_at(result, 0, local)["line"]
            sums[line] = sums.get(line, 0) + series.price_at(cursor)
            counts[line] = counts.get(line, 0) + 1
            cursor += timedelta(minutes=15)

        assert len(sums) == 2
        for slot in result["intervals"][0]["slots"]:
            dynamic_part = next(
                c for cat in slot["categories"] for c in cat["components"] if c["tariff_id"] == str(spot.pk)
            )
            expected = (sums[slot["line"]] / counts[slot["line"]]).quantize(D("0.00001"))
            assert D(dynamic_part["net"]) == expected
            assert dynamic_part["coverage"] == "1.0000"

    def test_a_month_without_prices_is_reported_and_not_priced(self, zev):
        spot, _ = make_dynamic(zev)

        interval = progress(zev, date_from=JANUARY[0], date_to=JANUARY[1])["intervals"][0]

        assert interval["incomplete"] == [{"tariff_id": str(spot.pk), "name": "Spot", "reason": "dynamic_no_data"}]
        assert interval["slots"] == []
        assert interval["missing_categories"] == []

    def test_a_month_without_prices_leaves_the_static_components_in_place(self, zev):
        make(zev, "Energie", [flat("0.15")])
        make_dynamic(zev)

        interval = progress(zev, date_from=JANUARY[0], date_to=JANUARY[1])["intervals"][0]

        assert [slot["net"] for slot in interval["slots"]] == ["0.15000"]
        assert [item["reason"] for item in interval["incomplete"]] == ["dynamic_no_data"]

    def test_a_gap_in_the_fetched_prices_is_partial(self, zev):
        spot, source = make_dynamic(zev)
        seed_prices(source, date(2026, 1, 1), date(2026, 1, 15), lambda moment: "0.10")

        interval = progress(zev, date_from=JANUARY[0], date_to=JANUARY[1])["intervals"][0]

        assert interval["incomplete"] == [{"tariff_id": str(spot.pk), "name": "Spot", "reason": "dynamic_partial"}]
        component = interval["slots"][0]["categories"][0]["components"][0]
        assert component["net"] == "0.10000"
        assert D(component["coverage"]) < D("0.5")

    def test_a_month_with_a_clock_change_is_complete(self, zev):
        _, source = make_dynamic(zev, valid_from=date(2026, 3, 1))
        seed_prices(source, date(2026, 3, 1), date(2026, 3, 31), lambda moment: "0.10")

        interval = progress(zev, date_from=date(2026, 3, 1), date_to=date(2026, 3, 31))["intervals"][0]

        # The 23-hour day reads a little under the nominal 24, which is not a gap.
        assert interval["incomplete"] == []
        assert D(interval["slots"][0]["categories"][0]["components"][0]["coverage"]) > D("0.99")

    def test_a_feed_in_floor_applies_to_each_interval(self, zev):
        _, source = make_dynamic(
            zev, "Einspeisung", tariff_type="feed_in", energy_type=EnergyType.FEED_IN,
            category=TariffCategory.ENERGY, minimum_price_chf_per_kwh=D("0.05"),
        )
        seed_prices(source, *JANUARY, lambda moment: "0.02" if moment.hour < 12 else "0.10")

        slot = progress(zev, "feed_in", date_from=JANUARY[0], date_to=JANUARY[1])["intervals"][0]["slots"][0]

        assert slot["net"] == "0.07500"

    def test_a_percentage_takes_its_share_of_the_dynamic_grid_mean(self, zev):
        _, source = make_dynamic(zev)
        seed_prices(source, *JANUARY, lambda moment: "0.20")
        make_percentage(zev, "Lokalanteil", "50", valid_from=date(2026, 1, 1))

        slot = progress(zev, "local", date_from=JANUARY[0], date_to=JANUARY[1])["intervals"][0]["slots"][0]

        component = slot["categories"][0]["components"][0]
        assert (slot["net"], component["base_net"], component["dynamic"]) == ("0.10000", "0.20000", False)

    def test_a_percentage_follows_the_dynamic_mean_in_each_slot(self, zev):
        make(zev, "Netzstrom", [ht("0.30"), nt("0.20")], valid_from=date(2026, 1, 1))
        _, source = make_dynamic(zev)
        seed_prices(source, *JANUARY, lambda moment: "0.10" if moment.hour < 12 else "0.30")
        make_percentage(zev, "Lokalanteil", "50", valid_from=date(2026, 1, 1))

        result = progress(zev, "local", date_from=JANUARY[0], date_to=JANUARY[1])

        # HT is 07-20 on weekdays: 07-12 at 0.10 and 12-20 at 0.30 -> 8 of 13 hours at 0.30.
        high = slot_at(result, 0, datetime(2026, 1, 6, 10, 0))
        assert D(high["net"]) == ((D("0.30") + (D("0.10") * 5 + D("0.30") * 8) / 13) * D("0.5")).quantize(D("0.00001"))

    def test_a_percentage_is_blocked_when_the_dynamic_base_has_no_data(self, zev):
        make_dynamic(zev)
        percentage_tariff = make_percentage(zev, "Lokalanteil", "50", valid_from=date(2026, 1, 1))

        interval = progress(zev, "local", date_from=JANUARY[0], date_to=JANUARY[1])["intervals"][0]

        assert {"tariff_id": str(percentage_tariff.pk), "name": "Lokalanteil", "reason": "dynamic_base"} in interval["incomplete"]
        assert interval["slots"] == []

    def test_inclusive_grosses_a_dynamic_grid_tariff(self, zev):
        set_vat(zev, VatMode.INCLUSIVE)
        _, source = make_dynamic(zev)
        seed_prices(source, *JANUARY, lambda moment: "0.10")

        slot = progress(zev, date_from=JANUARY[0], date_to=JANUARY[1])["intervals"][0]["slots"][0]

        assert (slot["net"], slot["gross"]) == ("0.10000", "0.10810")


class TestVat:
    def test_not_registered_has_no_gross_and_no_vat_breakpoints(self, zev):
        VatRate.objects.create(rate=D("0.0810"), valid_from=date(2025, 6, 1))
        make(zev, "Energie", [flat("0.20")])

        result = progress(zev)

        assert len(result["intervals"]) == 1
        interval = result["intervals"][0]
        assert interval["vat_rate"] is None
        assert interval["slots"][0]["gross"] is None

    def test_registered_grosses_every_component(self, zev):
        set_vat(zev, VatMode.REGISTERED)
        make(zev, "Energie", [flat("0.20")])
        make(zev, "Solar", [flat("0.10")], energy_type=EnergyType.LOCAL)

        grid = progress(zev, "grid")["intervals"][0]
        local = progress(zev, "local")["intervals"][0]

        assert grid["vat_rate"] == "0.0810"
        assert (grid["slots"][0]["net"], grid["slots"][0]["gross"]) == ("0.20000", "0.21620")
        assert local["slots"][0]["gross"] == "0.10810"

    def test_inclusive_grosses_only_the_bearing_tariffs(self, zev):
        set_vat(zev, VatMode.INCLUSIVE)
        make(zev, "Netzstrom", [flat("0.20")])
        make(zev, "Solar", [flat("0.10")], energy_type=EnergyType.LOCAL)
        make(zev, "Einspeisung", [flat("0.08")], energy_type=EnergyType.FEED_IN)

        assert progress(zev, "grid")["intervals"][0]["slots"][0]["gross"] == "0.21620"
        assert progress(zev, "local")["intervals"][0]["slots"][0]["gross"] == "0.10000"
        assert progress(zev, "feed_in")["intervals"][0]["slots"][0]["gross"] == "0.08000"

    def test_a_vat_rate_change_is_a_breakpoint(self, zev):
        set_vat(zev, VatMode.REGISTERED, rate=None)
        VatRate.objects.create(rate=D("0.0770"), valid_from=date(2020, 1, 1), valid_to=date(2025, 12, 31))
        VatRate.objects.create(rate=D("0.0810"), valid_from=date(2026, 1, 1))
        make(zev, "Energie", [flat("0.20")])

        first, second = progress(zev)["intervals"]

        assert (first["to"], second["from"]) == ("2025-12-31", "2026-01-01")
        assert first["slots"][0]["net"] == second["slots"][0]["net"] == "0.20000"
        assert (first["slots"][0]["gross"], second["slots"][0]["gross"]) == ("0.21540", "0.21620")

    def test_no_active_rate_means_gross_equals_net(self, zev):
        set_vat(zev, VatMode.REGISTERED, rate=None)
        make(zev, "Energie", [flat("0.20")])

        interval = progress(zev)["intervals"][0]

        assert interval["vat_rate"] == "0.0000"
        assert interval["slots"][0]["gross"] == "0.20000"

    def test_prices_round_to_five_places_half_up(self, zev):
        set_vat(zev, VatMode.REGISTERED, rate="0.0810")
        make(zev, "Energie", [flat("0.12345")])

        # 0.12345 * 1.081 = 0.13344945 -> 0.13345
        assert progress(zev)["intervals"][0]["slots"][0]["gross"] == "0.13345"


class TestFixedFees:
    def fee(self, zev, name, mode, amount, **kwargs):
        kwargs.setdefault("category", TariffCategory.METERING)
        kwargs.setdefault("energy_type", None)
        return factories.TariffFactory(
            zev=zev, name=name, billing_mode=mode, fixed_price_chf=D(amount), **kwargs,
        )

    def test_fees_are_listed_but_not_summed(self, zev):
        make(zev, "Energie", [flat("0.20")])
        self.fee(zev, "Grundgebühr", BillingMode.MONTHLY_FEE, "5.00")

        result = progress(zev)

        assert totals(result) == [["0.20000"]]
        assert [fee["name"] for fee in result["fixed_fees"]] == ["Grundgebühr"]

    @pytest.mark.parametrize(("mode", "unit", "scope"), [
        (BillingMode.MONTHLY_FEE, "month", "participant"),
        (BillingMode.YEARLY_FEE, "year", "participant"),
        (BillingMode.PER_METERING_POINT_MONTHLY_FEE, "month", "metering_point"),
        (BillingMode.PER_METERING_POINT_YEARLY_FEE, "year", "metering_point"),
        (BillingMode.SHARED_MONTHLY_FEE, "month", "community"),
        (BillingMode.SHARED_YEARLY_FEE, "year", "community"),
    ])
    def test_unit_and_scope_per_billing_mode(self, zev, mode, unit, scope):
        self.fee(zev, "Fee", mode, "12.00")

        fee = progress(zev)["fixed_fees"][0]

        assert (fee["unit"], fee["scope"]) == (unit, scope)

    def test_a_shared_fee_reports_the_community_amount_and_split_key(self, zev):
        self.fee(zev, "Verwaltung", BillingMode.SHARED_MONTHLY_FEE, "40.00", split_key="weight")

        fee = progress(zev)["fixed_fees"][0]

        assert (fee["scope"], fee["split_key"]) == ("community", "weight")
        assert fee["versions"][0]["amount_net"] == "40.00"

    def test_only_a_shared_fee_has_a_split_key(self, zev):
        self.fee(zev, "Grundgebühr", BillingMode.MONTHLY_FEE, "5.00")

        assert progress(zev)["fixed_fees"][0]["split_key"] is None

    def test_fee_rows_split_at_a_vat_change(self, zev):
        set_vat(zev, VatMode.REGISTERED, rate=None)
        VatRate.objects.create(rate=D("0.0770"), valid_from=date(2020, 1, 1), valid_to=date(2025, 12, 31))
        VatRate.objects.create(rate=D("0.0810"), valid_from=date(2026, 1, 1))
        self.fee(zev, "Grundgebühr", BillingMode.MONTHLY_FEE, "10.00", valid_from=date(2025, 1, 1))

        rows = progress(zev)["fixed_fees"][0]["versions"]

        assert [(r["valid_from"], r["valid_to"], r["vat_rate"], r["amount_gross"]) for r in rows] == [
            ("2025-01-01", "2025-12-31", "0.0770", "10.77"),
            ("2026-01-01", None, "0.0810", "10.81"),
        ]

    def test_fee_gross_follows_the_input_vat_classifier(self, zev):
        set_vat(zev, VatMode.INCLUSIVE)
        self.fee(zev, "Zählermiete", BillingMode.MONTHLY_FEE, "10.00", category=TariffCategory.METERING)
        self.fee(zev, "Verwaltung", BillingMode.MONTHLY_FEE, "10.00", category=TariffCategory.ENERGY)

        fees = {fee["name"]: fee["versions"][0]["amount_gross"] for fee in progress(zev)["fixed_fees"]}

        assert fees == {"Zählermiete": "10.81", "Verwaltung": "10.00"}

    def test_fees_are_independent_of_the_requested_energy_type(self, zev):
        make(zev, "Netzstrom", [flat("0.30")])
        make(zev, "Solar", [flat("0.12")], energy_type=EnergyType.LOCAL)
        self.fee(zev, "Grundgebühr", BillingMode.MONTHLY_FEE, "5.00")

        assert progress(zev, "grid")["fixed_fees"] == progress(zev, "local")["fixed_fees"]

    def test_fee_versions_outside_an_explicit_range_are_left_out(self, zev):
        self.fee(zev, "Grundgebühr", BillingMode.MONTHLY_FEE, "5.00",
                 valid_from=date(2024, 1, 1), valid_to=date(2024, 12, 31))
        self.fee(zev, "Grundgebühr", BillingMode.MONTHLY_FEE, "6.00", valid_from=date(2025, 1, 1))

        rows = progress(zev, date_from=date(2025, 3, 1), date_to=date(2025, 6, 30))["fixed_fees"][0]["versions"]

        assert [row["amount_net"] for row in rows] == ["6.00"]
