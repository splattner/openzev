"""Wiring the BFE reference-market-price CSV into the dynamic tariff pipeline.

The parser itself is covered by ``test_bfe_rmp_parsing.py``, pure and without
the database. These tests are about the seams around it: that a
``DynamicApiVersion.BFE_RMP`` source is fetched as text rather than JSON, asked
for once and bare (never a range), created without the VSE discovery/probe
dance, and rejects a source with no technology selected.
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest
from django.core.exceptions import ValidationError

from tariffs.dynamic.fetch import refresh_source
from tariffs.dynamic.models import DynamicPricePoint, DynamicTariffSource, FetchStatus
from tariffs.dynamic.services import create_or_reuse_source, recheck_source_capabilities

pytestmark = pytest.mark.django_db

UTC = timezone.utc
TESTDATA = Path(__file__).parent / "dynamic" / "testdata"

QUARTERLY_URL = "https://www.bfe-ogd.ch/ogd60_rmp_quartalspreise.csv"


def quarterly_csv() -> str:
    return (TESTDATA / "bfe_rmp_quarterly.csv").read_text()


def make_bfe_source(**overrides) -> DynamicTariffSource:
    defaults = {
        "label": "BFE reference market price — PV",
        "url": QUARTERLY_URL,
        "api_version": "bfe_rmp",
        "request_mode": "exact_url",
        "supports_range": False,
        "tariff_type": "feed_in",
        "tariff_name": "pv",
    }
    return DynamicTariffSource.objects.create(**{**defaults, **overrides})


def served_text(text):
    return mock.patch(
        "tariffs.dynamic.fetch.fetch_tariff_text",
        side_effect=lambda url: (text, "digest"),
    )


class TestModelValidation:
    def test_a_bfe_source_requires_a_known_technology(self):
        with pytest.raises(ValidationError) as caught:
            make_bfe_source(tariff_name="")

        assert "tariff_name" in caught.value.message_dict

    def test_an_unknown_technology_is_rejected(self):
        with pytest.raises(ValidationError):
            make_bfe_source(tariff_name="coal")

    def test_a_recognised_technology_is_accepted(self):
        source = make_bfe_source(tariff_name="wasserkraft")

        assert source.tariff_name == "wasserkraft"


class TestRefreshSource:
    def test_a_bfe_source_is_fetched_as_text_once_and_bare(self):
        source = make_bfe_source()
        seen = []

        with mock.patch(
            "tariffs.dynamic.fetch.fetch_tariff_text",
            side_effect=lambda url: (seen.append(url), (quarterly_csv(), "d"))[1],
        ):
            refresh_source(source, now=datetime(2026, 9, 14, 9, tzinfo=UTC))

        assert seen == [QUARTERLY_URL]

    def test_the_json_downloader_is_never_used_for_a_bfe_source(self):
        source = make_bfe_source()

        with served_text(quarterly_csv()), mock.patch(
            "tariffs.dynamic.fetch.fetch_tariff_document",
            side_effect=AssertionError("fetch_tariff_document must not be called for a BFE_RMP source"),
        ):
            refresh_source(source, now=datetime(2026, 9, 14, 9, tzinfo=UTC))

    def test_every_parsed_quarter_is_stored(self):
        source = make_bfe_source()

        with served_text(quarterly_csv()):
            result = refresh_source(source, now=datetime(2026, 9, 14, 9, tzinfo=UTC))

        assert result.points_written == 12
        assert DynamicPricePoint.objects.filter(source=source).count() == 12
        source.refresh_from_db()
        assert source.last_fetch_status == FetchStatus.OK

    def test_a_different_technology_reads_a_different_column_end_to_end(self):
        pv = make_bfe_source(tariff_name="pv")
        wasserkraft = make_bfe_source(tariff_name="wasserkraft")

        with served_text(quarterly_csv()):
            refresh_source(pv, now=datetime(2026, 9, 14, 9, tzinfo=UTC))
            refresh_source(wasserkraft, now=datetime(2026, 9, 14, 9, tzinfo=UTC))

        pv_price = DynamicPricePoint.objects.get(source=pv, valid_from=datetime(2023, 6, 30, 22, 0, tzinfo=UTC))
        hydro_price = DynamicPricePoint.objects.get(source=wasserkraft, valid_from=datetime(2023, 6, 30, 22, 0, tzinfo=UTC))
        assert pv_price.price_chf_per_kwh == Decimal("0.07166")
        assert hydro_price.price_chf_per_kwh == Decimal("0.08941")


class TestCreateOrReuseSource:
    def test_creating_a_bfe_source_skips_vse_discovery_and_stores_points(self):
        with served_text(quarterly_csv()), mock.patch(
            "tariffs.dynamic.services.probe_source_configuration",
            side_effect=AssertionError("VSE discovery must not run for a BFE_RMP source"),
        ), mock.patch("tariffs.tasks.fetch_dynamic_prices.delay"):
            source, created, warnings = create_or_reuse_source(
                label="BFE reference market price — PV",
                url=QUARTERLY_URL,
                api_version="bfe_rmp",
                tariff_type="feed_in",
                tariff_name="pv",
            )

        assert created is True
        assert warnings == []
        assert source.request_mode == "exact_url"
        assert source.supports_range is False
        assert source.points.count() == 12

    def test_creating_it_again_reuses_the_same_row(self):
        with served_text(quarterly_csv()), mock.patch("tariffs.tasks.fetch_dynamic_prices.delay"):
            first, _created, _warnings = create_or_reuse_source(
                label="BFE reference market price — PV", url=QUARTERLY_URL,
                api_version="bfe_rmp", tariff_type="feed_in", tariff_name="pv",
            )
            second, created_again, _warnings = create_or_reuse_source(
                label="BFE reference market price — PV (2)", url=QUARTERLY_URL,
                api_version="bfe_rmp", tariff_type="feed_in", tariff_name="pv",
            )

        assert created_again is False
        assert second.pk == first.pk


class TestRecheck:
    def test_recheck_is_a_no_op_for_a_bfe_source(self):
        source = make_bfe_source()

        with mock.patch(
            "tariffs.dynamic.services.probe_source_configuration",
            side_effect=AssertionError("VSE discovery must not run for a BFE_RMP source"),
        ):
            rechecked, warnings = recheck_source_capabilities(source)

        assert rechecked.pk == source.pk
        assert warnings == []
