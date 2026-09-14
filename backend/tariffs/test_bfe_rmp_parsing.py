"""The BFE reference-market-price CSV parser.

No database and no network here — see ``dynamic/bfe_rmp.py``'s module
docstring. The fixtures under ``tariffs/dynamic/testdata/`` are the real
files BFE publishes, so these assert against what BFE actually serves rather
than against a guess about its shape.
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from .dynamic.bfe_rmp import DynamicTariffResponseError, parse_tariff_response

TESTDATA = Path(__file__).parent / "dynamic" / "testdata"

UTC = timezone.utc


def fixture(name: str) -> str:
    return (TESTDATA / name).read_text()


class TestQuarterlyFixture(SimpleTestCase):
    def test_every_quarter_since_2023_q3_is_read_for_pv(self):
        series = parse_tariff_response(fixture("bfe_rmp_quarterly.csv"), tariff_name="pv")

        assert len(series.points) == 12
        first = series.points[0]
        # 2023-07-01 00:00 Europe/Zurich is CEST (UTC+2).
        assert first.valid_from == datetime(2023, 6, 30, 22, 0, tzinfo=UTC)
        assert first.price_chf_per_kwh == Decimal("0.07166")

    def test_a_quarter_boundary_is_read_in_zurich_civil_time(self):
        # Q2 2026 is Apr-Jun; 2026-04-01 is CEST (UTC+2), so the interval
        # starts at 2026-03-31T22:00:00Z, not at UTC midnight.
        series = parse_tariff_response(fixture("bfe_rmp_quarterly.csv"), tariff_name="pv")

        q2_2026 = next(p for p in series.points if p.valid_from.year == 2026 and p.price_chf_per_kwh == Decimal("0.03896"))

        assert q2_2026.valid_from == datetime(2026, 3, 31, 22, 0, tzinfo=UTC)
        assert q2_2026.valid_to == datetime(2026, 6, 30, 22, 0, tzinfo=UTC)

    def test_periods_are_contiguous_and_do_not_overlap(self):
        series = parse_tariff_response(fixture("bfe_rmp_quarterly.csv"), tariff_name="pv")

        for earlier, later in zip(series.points, series.points[1:]):
            assert earlier.valid_to == later.valid_from

    def test_chf_per_mwh_converts_exactly_to_five_decimals_of_chf_per_kwh(self):
        series = parse_tariff_response(fixture("bfe_rmp_quarterly.csv"), tariff_name="wasserkraft")

        assert all(point.price_chf_per_kwh == point.price_chf_per_kwh.quantize(Decimal("0.00001")) for point in series.points)

    def test_a_different_technology_reads_a_different_column(self):
        pv = parse_tariff_response(fixture("bfe_rmp_quarterly.csv"), tariff_name="pv")
        wasserkraft = parse_tariff_response(fixture("bfe_rmp_quarterly.csv"), tariff_name="wasserkraft")

        assert pv.points[0].price_chf_per_kwh != wasserkraft.points[0].price_chf_per_kwh
        assert wasserkraft.points[0].price_chf_per_kwh == Decimal("0.08941")


class TestMonthlyFixture(SimpleTestCase):
    def test_every_month_since_2023_07_is_read_for_pv(self):
        series = parse_tariff_response(fixture("bfe_rmp_monthly.csv"), tariff_name="pv")

        assert len(series.points) == 36
        assert series.points[0].price_chf_per_kwh == Decimal("0.06463")

    def test_a_month_boundary_across_a_dst_change_is_still_contiguous(self):
        series = parse_tariff_response(fixture("bfe_rmp_monthly.csv"), tariff_name="pv")

        for earlier, later in zip(series.points, series.points[1:]):
            assert earlier.valid_to == later.valid_from


class TestValidation(SimpleTestCase):
    def test_an_unknown_technology_is_rejected(self):
        with self.assertRaises(DynamicTariffResponseError):
            parse_tariff_response(fixture("bfe_rmp_quarterly.csv"), tariff_name="coal")

    def test_a_missing_column_is_rejected(self):
        text = "Year,Period,Days\n2026,Q1,90\n"
        with self.assertRaises(DynamicTariffResponseError):
            parse_tariff_response(text, tariff_name="pv")

    def test_an_invalid_period_value_is_rejected(self):
        text = "Year,Period,Price_pv_CHF_MWh\n2026,Q9,38.96\n"
        with self.assertRaises(DynamicTariffResponseError):
            parse_tariff_response(text, tariff_name="pv")

    def test_a_blank_price_is_skipped_as_not_yet_published(self):
        # The current, not-yet-closed quarter appears in the file with an
        # empty price cell rather than being omitted — BFE's actual behaviour
        # for the file's last row before publication.
        text = "Year,Period,Price_pv_CHF_MWh\n2026,Q1,38.96\n2026,Q2,\n"
        series = parse_tariff_response(text, tariff_name="pv")

        assert len(series.points) == 1

    def test_a_non_numeric_price_is_rejected(self):
        text = "Year,Period,Price_pv_CHF_MWh\n2026,Q1,not-a-number\n"
        with self.assertRaises(DynamicTariffResponseError):
            parse_tariff_response(text, tariff_name="pv")
