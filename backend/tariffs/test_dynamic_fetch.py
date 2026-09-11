"""Fetching, storing and scheduling a dynamic price series.

The network is faked throughout — these assert about windows, upserts, coverage
and failure recording, not about reachability. The one thing worth stating up
front: an operator answering ``200`` with an empty price list is a *successful*
fetch of nothing, and most of the care here is about not confusing that with
coverage.
"""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest

from tariffs.dynamic.fetch import (
    chunk_windows,
    coverage_gaps,
    refresh_source,
    store_points,
)
from tariffs.dynamic.models import (
    DynamicPricePoint,
    DynamicTariffSource,
    FetchStatus,
)
from tariffs.dynamic.vse_v1 import PricePoint
from tariffs.importers.remote import TariffFetchError
from tariffs.tasks import fetch_dynamic_prices_impl, refresh_dynamic_tariff_sources

pytestmark = pytest.mark.django_db

TESTDATA = Path(__file__).parent / "dynamic" / "testdata"
UTC = timezone.utc


def fixture(name: str) -> dict:
    return json.loads((TESTDATA / f"{name}.json").read_text())


def make_source(**overrides) -> DynamicTariffSource:
    defaults = {
        "label": "Groupe E vario — grid",
        "url": "https://api.tariffs.groupe-e.ch/v2/tariffs",
        "adapter": "groupe_e",
        "tariff_type": "grid",
        "tariff_name": "vario",
    }
    return DynamicTariffSource.objects.create(**{**defaults, **overrides})


def point(hour: int, price: str, *, day=1, minutes=15) -> PricePoint:
    start = datetime(2026, 2, day, hour, tzinfo=UTC)
    return PricePoint(start, start + timedelta(minutes=minutes), Decimal(price))


def served(payload):
    """Patch the HTTP layer to answer every request with ``payload``."""
    return mock.patch(
        "tariffs.dynamic.fetch.fetch_tariff_document",
        side_effect=lambda url: (payload(url) if callable(payload) else payload, "digest"),
    )


class TestChunkWindows:
    def test_a_long_window_is_split(self):
        # One Groupe E request for its whole retained history came back at
        # 95.7 % of the 5 MB fetch cap, so a backfill has to be walked.
        windows = chunk_windows(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC), max_days=31)

        assert len(windows) == 3
        assert windows[0].start == datetime(2026, 1, 1, tzinfo=UTC)
        assert windows[-1].end == datetime(2026, 4, 1, tzinfo=UTC)

    def test_the_chunks_are_contiguous_and_do_not_overlap(self):
        windows = chunk_windows(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 5, 3, tzinfo=UTC), max_days=31)

        for earlier, later in zip(windows, windows[1:]):
            assert earlier.end == later.start

    def test_an_empty_or_reversed_window_asks_for_nothing(self):
        instant = datetime(2026, 1, 1, tzinfo=UTC)
        assert chunk_windows(instant, instant, max_days=31) == []
        assert chunk_windows(instant, instant - timedelta(days=5), max_days=31) == []


class TestStorePoints:
    def test_points_are_stored_in_utc_whatever_offset_they_arrived_in(self):
        source = make_source()
        local = datetime(2026, 2, 1, 12, tzinfo=timezone(timedelta(hours=2)))

        store_points(source, [PricePoint(local, local + timedelta(minutes=15), Decimal("0.1"))])

        stored = DynamicPricePoint.objects.get()
        assert stored.valid_from == datetime(2026, 2, 1, 10, tzinfo=UTC)

    def test_refetching_the_same_interval_updates_rather_than_duplicates(self):
        # Both operators republish during the day, so a corrected price has to
        # land on the existing row. A second row would make the lookup ambiguous.
        source = make_source()
        store_points(source, [point(10, "0.10000")])
        store_points(source, [point(10, "0.20000")])

        stored = DynamicPricePoint.objects.get()
        assert stored.price_chf_per_kwh == Decimal("0.20000")

    def test_a_negative_price_survives_the_round_trip(self):
        source = make_source()
        store_points(source, [point(12, "-0.05430")])

        assert DynamicPricePoint.objects.get().price_chf_per_kwh == Decimal("-0.05430")

    def test_the_covered_extent_is_recorded_on_the_source(self):
        source = make_source()
        store_points(source, [point(10, "0.1"), point(14, "0.2")])

        source.refresh_from_db()
        assert source.covers_from == datetime(2026, 2, 1, 10, tzinfo=UTC)
        assert source.covers_to == datetime(2026, 2, 1, 14, 15, tzinfo=UTC)


class TestCoverageGaps:
    def test_a_fully_covered_window_has_no_gaps(self):
        source = make_source()
        store_points(source, [point(10, "0.1"), point(10, "0.1", minutes=15)])
        store_points(source, [PricePoint(
            datetime(2026, 2, 1, 10, 15, tzinfo=UTC), datetime(2026, 2, 1, 10, 30, tzinfo=UTC), Decimal("0.1"),
        )])

        gaps = coverage_gaps(source, datetime(2026, 2, 1, 10, tzinfo=UTC), datetime(2026, 2, 1, 10, 30, tzinfo=UTC))

        assert gaps == []

    def test_a_hole_in_the_middle_is_reported_as_its_own_span(self):
        # BKW documents omitting an interval when its source has no value, so
        # this is ordinary operator behaviour rather than corruption.
        source = make_source()
        store_points(source, [point(10, "0.1"), point(12, "0.1")])

        gaps = coverage_gaps(source, datetime(2026, 2, 1, 10, tzinfo=UTC), datetime(2026, 2, 1, 12, 15, tzinfo=UTC))

        assert gaps == [(datetime(2026, 2, 1, 10, 15, tzinfo=UTC), datetime(2026, 2, 1, 12, tzinfo=UTC))]

    def test_a_window_with_nothing_stored_is_one_whole_gap(self):
        source = make_source()

        gaps = coverage_gaps(source, datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 2, 2, tzinfo=UTC))

        assert gaps == [(datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 2, 2, tzinfo=UTC))]

    def test_coverage_is_measured_in_intervals_not_in_counts(self):
        # The spring-forward day has 92 quarter-hours rather than 96. Anything
        # that checked a count would call a complete day incomplete, twice a
        # year, and refuse to bill it.
        source = make_source(adapter="vse_v1", tariff_name="")
        with served(fixture("vse_v1_dst_spring")):
            refresh_source(source, now=datetime(2026, 3, 29, 12, tzinfo=UTC))

        assert DynamicPricePoint.objects.filter(source=source).count() == 92
        gaps = coverage_gaps(source, datetime(2026, 3, 28, 23, tzinfo=UTC), datetime(2026, 3, 29, 22, tzinfo=UTC))
        assert gaps == []


class TestRefreshSource:
    def test_a_plain_refresh_reaches_back_a_day_and_forward_two(self):
        # The window is in UTC while operators publish in local time, so
        # starting at UTC midnight would clip the first hours of the Swiss day.
        source = make_source()
        seen = []

        with mock.patch(
            "tariffs.dynamic.fetch.fetch_tariff_document",
            side_effect=lambda url: (seen.append(url), (fixture("vse_v1_empty"), "d"))[1],
        ):
            refresh_source(source, now=datetime(2026, 6, 15, 9, tzinfo=UTC))

        assert len(seen) == 1
        assert "start_timestamp=2026-06-14T00%3A00%3A00%2B00%3A00" in seen[0]
        assert "end_timestamp=2026-06-17T00%3A00%3A00%2B00%3A00" in seen[0]

    def test_a_backfill_is_walked_in_chunks(self):
        source = make_source()
        seen = []

        with mock.patch(
            "tariffs.dynamic.fetch.fetch_tariff_document",
            side_effect=lambda url: (seen.append(url), (fixture("vse_v1_empty"), "d"))[1],
        ):
            refresh_source(source, backfill=True, now=datetime(2026, 6, 15, 9, tzinfo=UTC))

        assert len(seen) > 10

    def test_an_endpoint_without_range_support_is_asked_once_and_bare(self):
        source = make_source(adapter="bkw", tariff_type="feed_in", tariff_name="",
                             url="https://api.bkw.ch/api/dyntariffs/v1/Tariffs/energyreturn")
        seen = []

        with mock.patch(
            "tariffs.dynamic.fetch.fetch_tariff_document",
            side_effect=lambda url: (seen.append(url), (fixture("bkw_energyreturn_day"), "d"))[1],
        ):
            # Even a backfill cannot ask BKW for history — it has none to give.
            refresh_source(source, backfill=True, now=datetime(2026, 9, 11, 12, tzinfo=UTC))

        assert seen == ["https://api.bkw.ch/api/dyntariffs/v1/Tariffs/energyreturn"]
        assert DynamicPricePoint.objects.filter(source=source).count() == 96

    def test_success_is_recorded_on_the_source(self):
        source = make_source(adapter="vse_v1", tariff_name="")
        with served(fixture("vse_v1_gap")):
            refresh_source(source, now=datetime(2026, 2, 1, 12, tzinfo=UTC))

        source.refresh_from_db()
        assert source.last_fetch_status == FetchStatus.OK
        assert source.last_success_at is not None
        assert source.last_fetch_error == ""

    def test_an_empty_answer_is_a_success_that_stores_nothing(self):
        # Groupe E answers 200 with an empty list for a range it holds nothing
        # for. Treating that as failure would raise a false alarm every time a
        # source is asked for tomorrow before the day-ahead auction publishes.
        source = make_source()
        with served(fixture("vse_v1_empty")):
            refresh_source(source, now=datetime(2026, 6, 15, 9, tzinfo=UTC))

        source.refresh_from_db()
        assert source.last_fetch_status == FetchStatus.OK
        assert DynamicPricePoint.objects.count() == 0

    def test_a_failure_is_recorded_in_user_safe_text_and_re_raised(self):
        source = make_source()
        failure = TariffFetchError(
            "The operator's server answered HTTP 410.", log_detail="resolved 93.184.216.34",
        )

        with mock.patch("tariffs.dynamic.fetch.fetch_tariff_document", side_effect=failure):
            with pytest.raises(TariffFetchError):
                refresh_source(source, now=datetime(2026, 6, 15, 9, tzinfo=UTC))

        source.refresh_from_db()
        assert source.last_fetch_status == FetchStatus.FAILED
        # The user-facing field must never carry the server-only detail.
        assert source.last_fetch_error == "The operator's server answered HTTP 410."
        assert "93.184.216.34" not in source.last_fetch_error

    def test_a_failed_refresh_leaves_the_previous_success_intact(self):
        # A blip must not look like "we never had prices": the stored series is
        # still the evidence behind any invoice already issued from it.
        source = make_source(adapter="vse_v1", tariff_name="")
        with served(fixture("vse_v1_gap")):
            refresh_source(source, now=datetime(2026, 2, 1, 12, tzinfo=UTC))
        stored = DynamicPricePoint.objects.count()

        with mock.patch("tariffs.dynamic.fetch.fetch_tariff_document", side_effect=TariffFetchError("down")):
            with pytest.raises(TariffFetchError):
                refresh_source(source, now=datetime(2026, 2, 2, 12, tzinfo=UTC))

        source.refresh_from_db()
        assert DynamicPricePoint.objects.count() == stored
        assert source.last_success_at is not None


class TestTasks:
    def test_the_task_returns_what_it_wrote(self):
        source = make_source(adapter="vse_v1", tariff_name="")
        with served(fixture("vse_v1_gap")):
            result = fetch_dynamic_prices_impl(source.pk)

        assert result["points_written"] == 92
        assert result["source_id"] == str(source.pk)

    def test_a_source_deleted_before_the_task_ran_is_not_an_error(self):
        # The beat job fans out ids; one can be removed in between.
        import uuid

        result = fetch_dynamic_prices_impl(uuid.uuid4())

        assert result["skipped"] == "missing"

    def test_the_beat_job_fans_out_one_task_per_source(self):
        # Fanned out rather than looped so one unreachable operator cannot
        # delay or fail the refresh of the others.
        make_source()
        make_source(url="https://api.bkw.ch/api/dyntariffs/v1/Tariffs/energyreturn",
                    adapter="bkw", tariff_type="feed_in", tariff_name="", label="BKW feed-in")

        with mock.patch("tariffs.tasks.fetch_dynamic_prices.delay") as delay:
            result = refresh_dynamic_tariff_sources()

        assert result["queued"] == 2
        assert delay.call_count == 2


class TestSourceIdentity:
    def test_the_same_endpoint_component_and_product_is_one_source(self):
        # Shared globally on purpose: the price of Groupe E vario grid at a
        # given instant is one fact, not one per community.
        from django.db.utils import IntegrityError

        make_source()
        with pytest.raises(IntegrityError):
            make_source(label="Someone else's name for it")

    def test_the_same_endpoint_serving_a_different_product_is_a_different_source(self):
        # Measured: Groupe E quoted 0.1398 for `vario` and 0.1267 for `double`
        # at the same instant, so the product is part of the identity.
        make_source()
        other = make_source(tariff_name="double", label="Groupe E double — grid")

        assert DynamicTariffSource.objects.count() == 2
        assert other.pk is not None

    def test_an_endpoint_that_takes_no_range_reports_that_it_cannot_backfill(self):
        source = make_source(adapter="bkw", tariff_type="feed_in", tariff_name="")

        assert source.supports_backfill is False
        assert make_source(tariff_name="vario2").supports_backfill is True
