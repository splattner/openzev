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
        "label": "Example dynamic grid",
        "url": "https://prices.example.test/tariffs",
        "api_version": "v1_0_5",
        "request_mode": "standard",
        "query_tariff_type": "grid",
        "supports_range": True,
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
    def test_rejected_replacements_cannot_hide_the_old_interval_from_other_candidates(self):
        from tariffs.dynamic.fetch import PriceSeriesConflict

        source = make_source()
        start = datetime(2026, 2, 1, tzinfo=UTC)
        def interval(begin, end):
            return PricePoint(start + timedelta(hours=begin), start + timedelta(hours=end), Decimal("0.1"))
        store_points(source, [interval(0, 10)])
        with pytest.raises(PriceSeriesConflict):
            store_points(source, [interval(0, 3), interval(2, 4), interval(8, 9), interval(12, 13)])
        assert list(source.points.values_list("valid_from", "valid_to")) == [
            (start, start + timedelta(hours=10)),
            (start + timedelta(hours=12), start + timedelta(hours=13)),
        ]

    def test_unbilled_resolution_changes_preserve_billed_history(self):
        from testing import factories

        source = make_source()
        tariff = factories.TariffFactory(dynamic_source=source, energy_type="grid")
        factories.InvoiceFactory(zev=tariff.zev, period_start="2026-01-01", period_end="2026-01-31")
        history = PricePoint(datetime(2026, 1, 15, tzinfo=UTC), datetime(2026, 1, 16, tzinfo=UTC), Decimal("0.1"))
        store_points(source, [history, point(10, "0.1", minutes=30), point(11, "0.1", minutes=30)])
        store_points(source, [point(10, "0.2", minutes=90)])
        assert source.points.count() == 2
        assert source.points.get(valid_from=history.valid_from).price_chf_per_kwh == Decimal("0.1")

    def test_schema_failures_are_failed_without_celery_retry(self):
        from tariffs.dynamic.fetch import PriceSeriesConflict
        from tariffs.tasks import fetch_dynamic_prices

        source = make_source()
        with served({"publication_timestamp": "", "prices": "invalid"}), mock.patch.object(fetch_dynamic_prices, "retry") as retry:
            with pytest.raises(PriceSeriesConflict):
                fetch_dynamic_prices(str(source.pk))
        retry.assert_not_called()
        source.refresh_from_db()
        assert source.last_fetch_status == FetchStatus.FAILED

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


class TestEvidenceProtection:
    def test_overwriting_a_billed_interval_is_refused(self):
        from tariffs.dynamic.fetch import BilledPriceChanged
        from testing import factories
        from tariffs.models import EnergyType

        source = make_source()
        tariff = factories.TariffFactory(dynamic_source=source, energy_type=EnergyType.GRID)
        factories.InvoiceFactory(zev=tariff.zev, period_start="2026-02-01", period_end="2026-02-28", status="sent")
        store_points(source, [point(10, "0.10000")])
        with pytest.raises(BilledPriceChanged):
            store_points(source, [point(10, "0.20000")])
        assert DynamicPricePoint.objects.get().price_chf_per_kwh == Decimal("0.10000")

    def test_a_draft_invoice_freezes_a_republished_price(self):
        from tariffs.dynamic.fetch import BilledPriceChanged
        from tariffs.models import EnergyType
        from testing import factories

        source = make_source()
        tariff = factories.TariffFactory(
            dynamic_source=source, energy_type=EnergyType.GRID
        )
        factories.InvoiceFactory(
            zev=tariff.zev,
            period_start="2026-02-01",
            period_end="2026-02-28",
            status="draft",
        )
        store_points(source, [point(10, "0.10000")])

        with pytest.raises(BilledPriceChanged):
            store_points(source, [point(10, "0.20000")])
        assert DynamicPricePoint.objects.get().price_chf_per_kwh == Decimal("0.10000")

    def test_shortening_an_interval_cannot_remove_billed_coverage(self):
        from tariffs.dynamic.fetch import BilledPriceChanged
        from tariffs.models import EnergyType
        from testing import factories

        source = make_source()
        tariff = factories.TariffFactory(
            dynamic_source=source, energy_type=EnergyType.GRID,
            valid_from="2026-01-01", valid_to="2026-02-28",
        )
        factories.InvoiceFactory(
            zev=tariff.zev, period_start="2026-02-01", period_end="2026-02-28", status="sent",
        )
        start = datetime(2026, 1, 31, 23, 45, tzinfo=UTC)
        store_points(source, [PricePoint(start, datetime(2026, 2, 1, 0, 15, tzinfo=UTC), Decimal("0.1"))])

        with pytest.raises(BilledPriceChanged):
            store_points(source, [PricePoint(start, datetime(2026, 1, 31, 23, 59, tzinfo=UTC), Decimal("0.1"))])

    def test_an_interval_ending_at_invoice_start_is_not_frozen(self):
        from tariffs.models import EnergyType
        from testing import factories

        source = make_source()
        tariff = factories.TariffFactory(dynamic_source=source, energy_type=EnergyType.GRID)
        factories.InvoiceFactory(
            zev=tariff.zev, period_start="2026-02-01", period_end="2026-02-28", status="sent",
        )
        start = datetime(2026, 1, 31, 23, 45, tzinfo=UTC)
        end = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)
        store_points(source, [PricePoint(start, end, Decimal("0.1"))])

        assert store_points(source, [PricePoint(start, end, Decimal("0.2"))]) == 1

    def test_invoice_evidence_is_intersected_with_tariff_validity(self):
        from tariffs.models import EnergyType
        from testing import factories

        source = make_source()
        tariff = factories.TariffFactory(
            dynamic_source=source, energy_type=EnergyType.GRID,
            valid_from="2026-02-01", valid_to="2026-02-28",
        )
        factories.InvoiceFactory(
            zev=tariff.zev, period_start="2026-01-01", period_end="2026-01-31", status="sent",
        )
        start = datetime(2026, 1, 31, 23, 45, tzinfo=UTC)

        store_points(source, [PricePoint(start, datetime(2026, 2, 1, 0, 15, tzinfo=UTC), Decimal("0.1"))])
        assert store_points(source, [PricePoint(start, datetime(2026, 2, 1, 0, 15, tzinfo=UTC), Decimal("0.2"))]) == 1

    def test_one_billed_conflict_does_not_discard_an_unrelated_new_point(self):
        from tariffs.dynamic.fetch import PriceSeriesConflict
        from tariffs.models import EnergyType
        from testing import factories

        source = make_source()
        tariff = factories.TariffFactory(dynamic_source=source, energy_type=EnergyType.GRID)
        factories.InvoiceFactory(
            zev=tariff.zev, period_start="2026-02-01", period_end="2026-02-28", status="sent",
        )
        stored = point(10, "0.10000")
        store_points(source, [stored])

        with pytest.raises(PriceSeriesConflict):
            store_points(source, [point(10, "0.20000"), point(11, "0.30000")])

        assert DynamicPricePoint.objects.get(valid_from=stored.valid_from).price_chf_per_kwh == Decimal("0.10000")
        assert DynamicPricePoint.objects.get(valid_from=point(11, "0.30000").valid_from).price_chf_per_kwh == Decimal("0.30000")

    def test_replacing_an_interval_with_adjacent_intervals_checks_the_result(self):
        source = make_source()
        start = datetime(2026, 2, 1, 10, tzinfo=UTC)
        store_points(source, [PricePoint(start, start + timedelta(hours=1), Decimal("0.1"))])

        assert store_points(source, [
            PricePoint(start, start + timedelta(minutes=30), Decimal("0.2")),
            PricePoint(start + timedelta(minutes=30), start + timedelta(hours=1), Decimal("0.3")),
        ]) == 2
        assert DynamicPricePoint.objects.filter(source=source).count() == 2

    def test_overlapping_a_stored_interval_is_refused(self):
        from tariffs.dynamic.vse_v1 import DynamicTariffResponseError

        source = make_source()
        start = datetime(2026, 2, 1, 10, tzinfo=UTC)
        store_points(source, [PricePoint(start, start + timedelta(minutes=30), Decimal("0.1"))])
        with pytest.raises(DynamicTariffResponseError):
            store_points(source, [PricePoint(
                start + timedelta(minutes=15), start + timedelta(minutes=45), Decimal("0.2"),
            )])

    def test_repeated_upserts_report_no_new_writes(self):
        source = make_source()
        assert store_points(source, [point(10, "0.1", day=3)]) == 1
        assert store_points(source, [point(10, "0.1", day=3)]) == 0

    def test_refresh_recovers_from_the_stored_extent(self):
        source = make_source()
        source.covers_to = datetime(2026, 1, 1, tzinfo=UTC)
        source.save()
        with mock.patch("tariffs.dynamic.fetch.fetch_window", return_value=([], [])) as fetch:
            refresh_source(source, now=datetime(2026, 2, 1, 12, tzinfo=UTC))

        assert fetch.call_args_list[0].args[1].start == datetime(2026, 1, 1, tzinfo=UTC)

    def test_a_current_series_asks_for_yesterday_instead_of_its_whole_history(self):
        source = make_source()
        source.covers_to = datetime(2026, 2, 3, tzinfo=UTC)
        source.save()
        with mock.patch("tariffs.dynamic.fetch.fetch_window", return_value=([], [])) as fetch:
            refresh_source(source, now=datetime(2026, 2, 1, 12, tzinfo=UTC))

        assert fetch.call_count == 1
        assert fetch.call_args.args[1].start == datetime(2026, 1, 31, tzinfo=UTC)

    def test_nothing_stored_falls_back_to_the_last_successful_fetch(self):
        source = make_source()
        source.last_success_at = datetime(2026, 1, 20, tzinfo=UTC)
        source.save()
        with mock.patch("tariffs.dynamic.fetch.fetch_window", return_value=([], [])) as fetch:
            refresh_source(source, now=datetime(2026, 2, 1, 12, tzinfo=UTC))

        assert fetch.call_args_list[0].args[1].start == datetime(2026, 1, 20, tzinfo=UTC)

    def test_a_refused_price_fails_the_refresh_instead_of_vanishing(self):
        from tariffs.dynamic.fetch import PriceSeriesConflict
        from tariffs.models import EnergyType
        from testing import factories

        source = make_source()
        tariff = factories.TariffFactory(dynamic_source=source, energy_type=EnergyType.GRID)
        factories.InvoiceFactory(
            zev=tariff.zev, period_start="2026-02-01", period_end="2026-02-28", status="sent",
        )
        store_points(source, [point(10, "0.10000")])

        with mock.patch(
            "tariffs.dynamic.fetch.fetch_window", return_value=([point(10, "0.20000")], [])
        ):
            with pytest.raises(PriceSeriesConflict):
                refresh_source(source, now=datetime(2026, 2, 1, 12, tzinfo=UTC))

        source.refresh_from_db()
        assert source.last_fetch_status == FetchStatus.FAILED
        assert "already priced an invoice" in source.last_fetch_error
        assert DynamicPricePoint.objects.get().price_chf_per_kwh == Decimal("0.10000")

    def test_a_window_that_could_not_be_fetched_is_reported_not_dropped(self):
        source = make_source()
        source.covers_to = datetime(2026, 1, 1, tzinfo=UTC)
        source.save()
        with mock.patch(
            "tariffs.dynamic.fetch.fetch_window",
            side_effect=[([], []), TariffFetchError("The endpoint refused the request.")],
        ):
            result = refresh_source(source, now=datetime(2026, 2, 1, 12, tzinfo=UTC))

        assert result.requests == 1
        assert any("could not be fetched" in warning for warning in result.warnings)
        source.refresh_from_db()
        assert source.last_fetch_status == FetchStatus.OK
        assert source.recovery_from == datetime(2026, 2, 1, tzinfo=UTC)

        with mock.patch("tariffs.dynamic.fetch.fetch_window", return_value=([], [])) as retry:
            refresh_source(source, now=datetime(2026, 2, 2, 12, tzinfo=UTC))
        assert retry.call_args.args[1].start == datetime(2026, 2, 1, tzinfo=UTC)
        source.refresh_from_db()
        assert source.recovery_from is None

    def test_an_unexpected_error_is_recorded_and_audited(self):
        source = make_source()
        with mock.patch("tariffs.dynamic.fetch.fetch_window", side_effect=RuntimeError("boom")),                 mock.patch("tariffs.tasks._audit_best_effort") as audit:
            with pytest.raises(RuntimeError):
                fetch_dynamic_prices_impl(str(source.pk))
        source.refresh_from_db()
        assert source.last_fetch_status == FetchStatus.FAILED
        assert "RuntimeError" in source.last_fetch_error
        audit.assert_called_once()

    @pytest.mark.parametrize("backfill,previous_days,fail_first", [
        (False, 100, False),
        (False, 100, True),
        (True, None, True),
        (True, 500, False),
    ])
    def test_recovery_retains_failed_and_unattempted_history(self, backfill, previous_days, fail_first):
        today = datetime(2026, 9, 12, tzinfo=UTC)
        previous = today - timedelta(days=previous_days) if previous_days else None
        source = make_source(recovery_from=previous)
        attempted = []

        def fetch(_source, window):
            attempted.append(window)
            if fail_first and len(attempted) == 1:
                raise TariffFetchError("The endpoint is unavailable.")
            return [], []

        with mock.patch("tariffs.dynamic.fetch.fetch_window", side_effect=fetch):
            if fail_first and not backfill:
                with pytest.raises(TariffFetchError):
                    refresh_source(source, backfill=backfill, now=today)
            else:
                refresh_source(source, backfill=backfill, now=today)

        assert attempted[0].start == today - timedelta(days=400 if backfill else 14)
        source.refresh_from_db()
        assert source.recovery_from == (previous or attempted[0].start)

    def test_an_unexpected_error_does_not_write_its_message_to_the_operator_field(self):
        # Confirm the operator field excludes server-only error details.
        source = make_source()
        with mock.patch(
            "tariffs.dynamic.fetch.fetch_window",
            side_effect=RuntimeError("could not connect to db.internal:5432"),
        ):
            with pytest.raises(RuntimeError):
                refresh_source(source, now=datetime(2026, 2, 1, 12, tzinfo=UTC))

        source.refresh_from_db()
        assert "db.internal" not in source.last_fetch_error
        assert "RuntimeError" in source.last_fetch_error


class TestAdminCreation:
    def test_creating_a_source_in_the_admin_queues_one_backfill(self):
        from django.contrib import admin as django_admin

        from tariffs.admin import DynamicTariffSourceAdmin

        model_admin = DynamicTariffSourceAdmin(DynamicTariffSource, django_admin.site)
        source = make_source()
        with (
            mock.patch("tariffs.admin.transaction.on_commit") as on_commit,
            mock.patch("tariffs.tasks.fetch_dynamic_prices.delay") as delay,
        ):
            model_admin.save_model(request=None, obj=source, form=None, change=False)
            on_commit.assert_called_once()
            on_commit.call_args.args[0]()

        delay.assert_called_once_with(str(source.pk), backfill=True)

    def test_editing_a_source_in_the_admin_does_not_queue_a_backfill(self):
        from django.contrib import admin as django_admin

        from tariffs.admin import DynamicTariffSourceAdmin

        model_admin = DynamicTariffSourceAdmin(DynamicTariffSource, django_admin.site)
        source = make_source()
        with mock.patch("tariffs.admin.transaction.on_commit") as on_commit:
            model_admin.save_model(request=None, obj=source, form=None, change=True)

        on_commit.assert_not_called()

    def test_price_points_are_read_only_in_the_admin(self):
        from django.contrib import admin as django_admin
        from tariffs.admin import DynamicPricePointAdmin

        model_admin = DynamicPricePointAdmin(DynamicPricePoint, django_admin.site)

        assert model_admin.has_add_permission(None) is False
        assert model_admin.has_change_permission(None) is False
        assert model_admin.has_delete_permission(None) is False


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
        source = make_source(tariff_name="")
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
        source = make_source(
            request_mode="exact_url", supports_range=False, query_tariff_type="",
            tariff_type="feed_in", tariff_name="", url="https://prices.example.test/current",
        )
        seen = []

        with mock.patch(
            "tariffs.dynamic.fetch.fetch_tariff_document",
            side_effect=lambda url: (seen.append(url), (fixture("bkw_energyreturn_day"), "d"))[1],
        ):
            # Even a backfill cannot ask an exact-URL endpoint for history.
            refresh_source(source, backfill=True, now=datetime(2026, 9, 11, 12, tzinfo=UTC))

        assert seen == ["https://prices.example.test/current"]
        assert DynamicPricePoint.objects.filter(source=source).count() == 96

    def test_success_is_recorded_on_the_source(self):
        source = make_source(tariff_name="")
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

    def test_an_expected_exact_url_404_is_an_empty_success(self):
        source = make_source(
            request_mode="exact_url",
            supports_range=False,
            query_tariff_type="",
            tariff_type="feed_in",
            tariff_name="",
            empty_on_not_found=True,
        )
        missing = TariffFetchError(
            "The operator's server answered HTTP 404.", status_code=404
        )

        with mock.patch(
            "tariffs.dynamic.fetch.fetch_tariff_document", side_effect=missing
        ):
            result = refresh_source(source, now=datetime(2026, 6, 15, 9, tzinfo=UTC))

        source.refresh_from_db()
        assert result.requests == 1
        assert result.points_written == 0
        assert source.last_fetch_status == FetchStatus.OK

    def test_a_410_remains_a_failure_for_an_exact_url_source(self):
        source = make_source(
            request_mode="exact_url",
            supports_range=False,
            query_tariff_type="",
            tariff_type="feed_in",
            tariff_name="",
            empty_on_not_found=True,
        )
        gone = TariffFetchError(
            "The operator's server answered HTTP 410.", status_code=410
        )

        with mock.patch(
            "tariffs.dynamic.fetch.fetch_tariff_document", side_effect=gone
        ):
            with pytest.raises(TariffFetchError):
                refresh_source(source, now=datetime(2026, 6, 15, 9, tzinfo=UTC))

        source.refresh_from_db()
        assert source.last_fetch_status == FetchStatus.FAILED

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
        source = make_source(tariff_name="")
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
        source = make_source(tariff_name="")
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
        make_source(
            url="https://prices.example.test/current", request_mode="exact_url",
            supports_range=False, query_tariff_type="", tariff_type="feed_in",
            tariff_name="", label="Example feed-in",
        )

        with mock.patch("tariffs.tasks.fetch_dynamic_prices.delay") as delay:
            result = refresh_dynamic_tariff_sources()

        assert result["queued"] == 2
        assert delay.call_count == 2

    def test_the_beat_job_skips_disabled_sources(self):
        enabled = make_source()
        make_source(
            url="https://prices.example.test/disabled",
            tariff_name="disabled",
            enabled=False,
        )

        with mock.patch("tariffs.tasks.fetch_dynamic_prices.delay") as delay:
            result = refresh_dynamic_tariff_sources()

        assert result["queued"] == 1
        delay.assert_called_once_with(str(enabled.pk))


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
        source = make_source(
            request_mode="exact_url", supports_range=False,
            query_tariff_type="", tariff_type="feed_in", tariff_name="",
        )

        assert source.supports_backfill is False
        assert make_source(tariff_name="vario2").supports_backfill is True
