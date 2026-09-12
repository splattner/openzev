"""Aggregate-component composition per API version (see components.py)."""

from django.test import SimpleTestCase

from tariffs.dynamic.adapters import DynamicApiVersion
from tariffs.dynamic.components import (
    aggregated_tariff_types,
    certain_components,
    possible_extra_components,
)

V1 = DynamicApiVersion.V1_0_5
V2 = DynamicApiVersion.V2_0_0


class AggregationTests(SimpleTestCase):
    def test_v1_integrated_is_electricity_and_grid(self):
        self.assertEqual(aggregated_tariff_types(V1, "integrated"), ("electricity", "grid"))

    def test_v2_expands_recursively(self):
        self.assertEqual(
            aggregated_tariff_types(V2, "integrated"),
            ("electricity", "grid", "metering", "national_fees"),
        )
        self.assertEqual(
            aggregated_tariff_types(V2, "integrated_complete"),
            ("electricity", "grid", "metering", "national_fees", "regional_fees"),
        )
        self.assertEqual(
            aggregated_tariff_types(V2, "dso_complete"),
            ("grid", "metering", "national_fees", "regional_fees"),
        )

    def test_v2_dso_contains_no_electricity(self):
        """A DSO does not sell energy; summing electricity + dso must not double it."""
        self.assertEqual(
            aggregated_tariff_types(V2, "dso"), ("grid", "metering", "national_fees")
        )

    def test_plain_and_unknown_types_expand_to_nothing(self):
        for tariff_type in ("grid", "electricity", "metering", "feed_in", "refund", "bogus"):
            self.assertEqual(aggregated_tariff_types(V1, tariff_type), ())
            self.assertEqual(aggregated_tariff_types(V2, tariff_type), ())
        self.assertEqual(aggregated_tariff_types("v9", "dso"), ())

    def test_integrated_is_the_only_version_dependent_row(self):
        self.assertEqual(certain_components("integrated"), ("electricity", "grid"))
        self.assertEqual(
            possible_extra_components("integrated"), ("metering", "national_fees")
        )
        for tariff_type in ("dso", "dso_complete", "integrated_complete"):
            self.assertEqual(
                certain_components(tariff_type), aggregated_tariff_types(V2, tariff_type)
            )
            self.assertEqual(possible_extra_components(tariff_type), ())

    def test_plain_types_have_no_certain_or_possible_components(self):
        for tariff_type in ("grid", "feed_in", "bogus"):
            self.assertEqual(certain_components(tariff_type), ())
            self.assertEqual(possible_extra_components(tariff_type), ())
