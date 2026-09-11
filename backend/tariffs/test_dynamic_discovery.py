"""Protocol discovery is based on responses and capabilities, not provider names."""

import json
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from tariffs.dynamic.discovery import discover_endpoint, probe_source_configuration
from tariffs.dynamic.vse_v1 import DynamicTariffResponseError
from tariffs.importers.remote import TariffFetchError

TESTDATA = Path(__file__).parent / "dynamic" / "testdata"


def fixture(name):
    return json.loads((TESTDATA / f"{name}.json").read_text())


def feed_in_payload():
    return {
        "publication_timestamp": "2026-09-11T12:00:00+02:00",
        "prices": [{
            "start_timestamp": "2026-09-11T00:00:00+02:00",
            "end_timestamp": "2026-09-11T00:15:00+02:00",
            "feed_in": [{"unit": "CHF_kWh", "value": 0.08}],
        }],
    }


class DiscoveryTests(SimpleTestCase):
    @mock.patch("tariffs.dynamic.discovery.fetch_tariff_document")
    def test_version_and_v2_product_are_discovered(self, fetch):
        fetch.return_value = (fixture("vse_v2_grid"), "digest")

        result = discover_endpoint("https://prices.example.test/tariffs")

        self.assertEqual(result.api_version, "v2_0_0")
        self.assertEqual(result.components[0].tariff_type, "grid")
        self.assertEqual(result.components[0].tariff_name, "standard")

    @mock.patch("tariffs.dynamic.discovery.fetch_tariff_document")
    def test_an_incorrect_version_override_is_refused(self, fetch):
        fetch.return_value = (fixture("vse_v2_grid"), "digest")

        with self.assertRaises(DynamicTariffResponseError):
            discover_endpoint("https://prices.example.test/tariffs", api_version="v1_0_5")

    @mock.patch("tariffs.dynamic.discovery.fetch_tariff_document")
    def test_an_explicit_version_unlocks_configuration_for_an_empty_response(self, fetch):
        fetch.return_value = ({"publication_timestamp": "", "prices": []}, "digest")

        result = discover_endpoint(
            "https://prices.example.test/tariffs", api_version="v1_0_5"
        )

        self.assertFalse(result.version_detected)
        self.assertFalse(result.components_discovered)
        self.assertIn("grid", [item.tariff_type for item in result.components])

    @mock.patch("tariffs.dynamic.discovery.fetch_tariff_document")
    def test_standard_query_and_range_support_are_measured(self, fetch):
        fetch.return_value = (fixture("vse_v1_multi_unit"), "digest")

        result = probe_source_configuration(
            "https://prices.example.test/tariffs",
            api_version="v1_0_5",
            tariff_type="grid",
        )

        self.assertEqual(result.request_mode, "standard")
        self.assertEqual(result.query_tariff_type, "grid")
        self.assertTrue(result.supports_range)

    @mock.patch("tariffs.dynamic.discovery.fetch_tariff_document")
    def test_an_endpoint_rejecting_queries_is_kept_as_an_exact_url(self, fetch):
        payload = feed_in_payload()

        def answer(url):
            if "?" in url:
                raise TariffFetchError("Query parameters are not accepted.")
            return payload, "digest"

        fetch.side_effect = answer
        result = probe_source_configuration(
            "https://prices.example.test/current",
            api_version="v1_0_5",
            tariff_type="feed_in",
        )

        self.assertEqual(result.request_mode, "exact_url")
        self.assertFalse(result.supports_range)

    @mock.patch("tariffs.dynamic.discovery.fetch_tariff_document")
    def test_a_hyphenated_query_value_is_discovered_generically(self, fetch):
        payload = feed_in_payload()

        def answer(url):
            if "tariff_type=feed_in" in url:
                raise TariffFetchError("Invalid enum value.")
            return payload, "digest"

        fetch.side_effect = answer
        result = probe_source_configuration(
            "https://prices.example.test/tariffs",
            api_version="v1_0_5",
            tariff_type="feed_in",
        )

        self.assertEqual(result.request_mode, "standard")
        self.assertEqual(result.query_tariff_type, "feed-in")
