"""The versioned VSE response parsers and generic request construction.

No database and no network here: the parser takes a decoded payload and the
adapters build a URL string, which is the whole point of keeping them pure.
The fixtures under ``tariffs/dynamic/testdata/`` include two real captures, so
these assert against what the operators actually served rather than against a
guess about what they might serve.
"""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from .dynamic.adapters import DynamicRequestMode, FetchWindow, request_url
from .dynamic.protocol import (
    detect_api_version,
    discover_components,
    parse_tariff_response as parse_versioned_response,
)
from .dynamic.vse_v1 import (
    DynamicTariffResponseError,
    parse_tariff_response,
)

TESTDATA = Path(__file__).parent / "dynamic" / "testdata"


def fixture(name: str) -> dict:
    return json.loads((TESTDATA / f"{name}.json").read_text())


def response(*intervals, publication="2026-02-01T00:00:00+01:00") -> dict:
    return {"publication_timestamp": publication, "prices": list(intervals)}


def interval(start: str, end: str, **components) -> dict:
    return {"start_timestamp": start, "end_timestamp": end, **components}


def kwh(value) -> list[dict]:
    return [{"unit": "CHF_kWh", "value": value}]


class RealCaptureTests(SimpleTestCase):
    """Against what the two live endpoints actually returned on 2026-09-11.

    Every operator's endpoint is its own dialect until proven otherwise, so the
    thing worth testing is not that the parser handles a document we wrote — it
    is that it handles the ones they sent.
    """

    def test_groupe_e_grid_is_read_including_its_negative_prices(self):
        series = parse_tariff_response(fixture("groupe_e_v2_day"), tariff_type="grid")

        prices = [point.price_chf_per_kwh for point in series.points]
        self.assertEqual(len(series.points), 96)
        # Negative grid-usage prices are the mechanism, not an anomaly: they are
        # how a dynamic tariff steers consumption into the midday solar peak.
        self.assertEqual(sum(1 for price in prices if price < 0), 22)
        self.assertEqual(min(prices), Decimal("-0.05430"))

    def test_the_same_response_prices_a_different_component_differently(self):
        # One response carries several tariff types; which one a community bills
        # depends on what it buys from the operator, so the type is a parameter.
        grid = parse_tariff_response(fixture("groupe_e_v2_day"), tariff_type="grid")
        integrated = parse_tariff_response(fixture("groupe_e_v2_day"), tariff_type="integrated")

        self.assertEqual(len(grid.points), len(integrated.points))
        self.assertNotEqual(grid.points[0].price_chf_per_kwh, integrated.points[0].price_chf_per_kwh)

    def test_bkw_feed_in_is_read_from_utc_timestamps(self):
        # BKW publishes in UTC where Groupe E publishes local-with-offset. Both
        # are valid ISO-8601; the parser must not care which it is given.
        series = parse_tariff_response(fixture("bkw_energyreturn_day"), tariff_type="feed_in")

        self.assertEqual(len(series.points), 96)
        self.assertEqual(series.points[0].valid_from.utcoffset(), timedelta(0))

    def test_a_component_the_response_does_not_carry_yields_nothing(self):
        # BKW's energy-return endpoint serves feed_in only. Asking it for grid
        # is not an error — it is an empty answer, and the caller decides
        # whether an empty answer where it expected prices is a problem.
        series = parse_tariff_response(fixture("bkw_energyreturn_day"), tariff_type="grid")

        self.assertEqual(series.points, [])


class UnitSelectionTests(SimpleTestCase):
    """A tariff type carries a list of prices because it can carry several units."""

    def test_the_kwh_price_is_picked_by_unit_not_by_position(self):
        # The standard's own example pairs a CHF_kWh energy price with a CHF_m
        # monthly fee in one interval, and the fixture puts the billable one
        # second in the list. Reading element [0] would bill 12 CHF/kWh here.
        series = parse_tariff_response(fixture("vse_v1_multi_unit"), tariff_type="grid")

        self.assertEqual(
            [point.price_chf_per_kwh for point in series.points],
            [Decimal("0.11300"), Decimal("0.10200")],
        )

    def test_units_that_cannot_be_billed_are_reported_rather_than_dropped_silently(self):
        series = parse_tariff_response(fixture("vse_v1_multi_unit"), tariff_type="grid")

        joined = " ".join(series.warnings)
        self.assertIn("CHF_kW_m", joined)
        self.assertIn("demand", joined)
        self.assertIn("CHF_m", joined)

    def test_two_kwh_prices_in_one_interval_are_refused(self):
        # Not a guess we get to make: if an operator publishes two per-kWh
        # prices for one interval, which one bills is undefined.
        payload = response(interval(
            "2026-02-01T00:00:00+01:00", "2026-02-01T00:15:00+01:00",
            grid=[{"unit": "CHF_kWh", "value": 0.1}, {"unit": "CHF_kWh", "value": 0.2}],
        ))

        with self.assertRaises(DynamicTariffResponseError) as caught:
            parse_tariff_response(payload, tariff_type="grid")

        self.assertIn("more than one", str(caught.exception))


class EmptyAndMalformedTests(SimpleTestCase):
    def test_an_empty_series_with_an_empty_publication_stamp_is_valid(self):
        # This is Groupe E's literal answer for a range it holds nothing for,
        # served with HTTP 200. The v1 schema declares an empty timestamp
        # conformant, so refusing it here would refuse a correct response.
        series = parse_tariff_response(fixture("vse_v1_empty"), tariff_type="grid")

        self.assertEqual(series.points, [])
        self.assertIsNone(series.publication_timestamp)

    def test_a_timestamp_without_an_offset_is_refused(self):
        payload = response(interval(
            "2026-02-01T00:00:00", "2026-02-01T00:15:00", grid=kwh(0.1),
        ))

        with self.assertRaises(DynamicTariffResponseError) as caught:
            parse_tariff_response(payload, tariff_type="grid")

        self.assertIn("offset", str(caught.exception))

    def test_an_interval_ending_before_it_starts_is_refused(self):
        payload = response(interval(
            "2026-02-01T01:00:00+01:00", "2026-02-01T00:15:00+01:00", grid=kwh(0.1),
        ))

        with self.assertRaises(DynamicTariffResponseError):
            parse_tariff_response(payload, tariff_type="grid")

    def test_overlapping_intervals_are_refused(self):
        payload = response(
            interval("2026-02-01T00:00:00+01:00", "2026-02-01T00:30:00+01:00", grid=kwh(0.1)),
            interval("2026-02-01T00:15:00+01:00", "2026-02-01T00:45:00+01:00", grid=kwh(0.2)),
        )

        with self.assertRaises(DynamicTariffResponseError) as caught:
            parse_tariff_response(payload, tariff_type="grid")

        self.assertIn("overlap", str(caught.exception))

    def test_schema_version_2_is_detected_and_parsed(self):
        payload = fixture("vse_v2_grid")

        self.assertEqual(detect_api_version(payload), "v2_0_0")
        self.assertEqual(
            discover_components(payload, "v2_0_0")[0].tariff_name,
            "standard",
        )
        series = parse_versioned_response(payload, api_version="v2_0_0", tariff_type="grid")
        self.assertEqual(series.points[0].price_chf_per_kwh, Decimal("0.11300"))

    def test_schema_version_1_is_detected(self):
        self.assertEqual(detect_api_version(fixture("vse_v1_multi_unit")), "v1_0_5")


class DaylightSavingTests(SimpleTestCase):
    """A day is not always 96 quarter-hours, which is why nothing counts them."""

    def test_the_spring_forward_day_has_92_intervals(self):
        series = parse_tariff_response(fixture("vse_v1_dst_spring"), tariff_type="grid")

        self.assertEqual(len(series.points), 92)
        # 02:00 local never happens: the hour is skipped, and the offset changes
        # across the jump.
        self.assertEqual(
            series.points[7].valid_to,
            series.points[8].valid_from,
        )

    def test_the_fall_back_day_has_100_intervals_and_no_overlap(self):
        # 02:00-03:00 is served twice under different offsets. As instants they
        # do not overlap, which is exactly why the parser compares instants.
        series = parse_tariff_response(fixture("vse_v1_dst_autumn"), tariff_type="grid")

        self.assertEqual(len(series.points), 100)


class RequestConstructionTests(SimpleTestCase):
    """Request behavior is driven by discovered capabilities, not VNB names."""

    window = FetchWindow(
        start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        end=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    def test_a_discovered_query_spelling_is_used(self):
        url = request_url(
            "https://x.example/tariffs", request_mode=DynamicRequestMode.STANDARD,
            query_tariff_type="feed-in",
        )

        self.assertIn("tariff_type=feed-in", url)

    def test_the_standard_query_value_is_used_unchanged(self):
        url = request_url(
            "https://x.example/tariffs", request_mode=DynamicRequestMode.STANDARD,
            query_tariff_type="feed_in",
        )

        self.assertIn("tariff_type=feed_in", url)

    def test_a_query_already_on_the_url_is_preserved(self):
        # The URL can arrive from `prices.dynamic.url` in a published document,
        # where an operator may already have pinned something.
        url = request_url(
            "https://x.example/tariffs?region=west", request_mode=DynamicRequestMode.STANDARD,
            query_tariff_type="grid", tariff_name="example",
        )

        self.assertIn("region=west", url)
        self.assertIn("tariff_name=example", url)

    def test_exact_url_mode_adds_no_query(self):
        url = request_url(
            "https://x.example/current", request_mode=DynamicRequestMode.EXACT_URL,
            query_tariff_type="feed_in",
        )

        self.assertEqual(url, "https://x.example/current")

    def test_exact_url_mode_cannot_be_asked_for_a_range(self):
        with self.assertRaises(ValueError):
            request_url(
                "https://x.example/current", request_mode=DynamicRequestMode.EXACT_URL,
                query_tariff_type="feed_in", window=self.window,
            )

    def test_a_range_becomes_iso_timestamps(self):
        url = request_url(
            "https://x.example/tariffs", request_mode=DynamicRequestMode.STANDARD,
            query_tariff_type="grid", window=self.window,
        )

        self.assertIn("start_timestamp=2026-08-01T00%3A00%3A00%2B00%3A00", url)
        self.assertIn("end_timestamp=2026-09-01T00%3A00%3A00%2B00%3A00", url)

    def test_an_unknown_request_mode_is_refused(self):
        with self.assertRaises(ValueError):
            request_url("https://x.example/tariffs", request_mode="nope", query_tariff_type="grid")
