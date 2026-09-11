"""Pure transform logic behind ``manage.py fetch_grid_operators``.

Split from ``test_grid_operators.py`` (which tests the shipped fixture and its
endpoints) because these exercise the command's SPARQL-row-to-fixture mapping
directly, with no network and no fixture file involved — see #691.
"""

from django.test import SimpleTestCase

from zev.management.commands.fetch_grid_operators import (
    build_operators,
    build_postal_codes,
    looks_like_direct_json,
    normalise_tariff_url,
    pick_tariff_url,
)


def _row(**bindings):
    """A SPARQL JSON result row from string values; absent keys stay unbound."""
    return {key: {"value": value} for key, value in bindings.items() if value is not None}


class NormaliseTariffUrlTests(SimpleTestCase):
    def test_blank_stays_blank(self):
        self.assertEqual(normalise_tariff_url(""), "")
        self.assertEqual(normalise_tariff_url("   "), "")

    def test_scheme_less_domain_gets_https(self):
        """About a tenth of ElCom's raw urltr values arrive this way — a human
        typed a domain into a form field, not a URL."""
        self.assertEqual(normalise_tariff_url("www.example.ch"), "https://www.example.ch")

    def test_existing_scheme_is_left_alone(self):
        self.assertEqual(normalise_tariff_url("http://example.ch/tarife.json"), "http://example.ch/tarife.json")
        self.assertEqual(normalise_tariff_url("https://example.ch/tarife.json"), "https://example.ch/tarife.json")

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(normalise_tariff_url("  www.example.ch  "), "https://www.example.ch")


class LooksLikeDirectJsonTests(SimpleTestCase):
    def test_direct_json_link(self):
        self.assertTrue(looks_like_direct_json("https://example.ch/tarife_2027.json"))

    def test_landing_page(self):
        self.assertFalse(looks_like_direct_json("https://example.ch/strompreise"))

    def test_trailing_slash_is_ignored(self):
        self.assertTrue(looks_like_direct_json("https://example.ch/tarife.json/"))

    def test_query_string_is_stripped_before_checking(self):
        """A ``.json`` inside a query string does not make the path itself a
        direct link — real example: aemsa.ch serves its tariffs from
        ``/api/download?filename=AEM_2027.json&mime=application/json``, whose
        *path* is ``/api/download`` and is correctly not "direct" by shape.
        This is only a UI hint; the fetch-and-parse step is what actually
        validates the URL, regardless of what this heuristic guesses."""
        self.assertFalse(looks_like_direct_json("https://example.ch/api/download?filename=X.json&mime=application/json"))

    def test_case_insensitive(self):
        self.assertTrue(looks_like_direct_json("https://example.ch/Tarife_2027.JSON"))


class PickTariffUrlTests(SimpleTestCase):
    def test_no_values(self):
        self.assertEqual(pick_tariff_url([]), ("", False))

    def test_single_value_is_normalised(self):
        self.assertEqual(
            pick_tariff_url(["www.example.ch"]),
            ("https://www.example.ch", False),
        )

    def test_blank_rows_are_ignored(self):
        self.assertEqual(
            pick_tariff_url(["", "https://example.ch/tarife.json", ""]),
            ("https://example.ch/tarife.json", True),
        )

    def test_most_common_value_wins(self):
        """One operator's 30 obs rows (categories x products) mostly repeat the
        same urltr; an outlier from a stale row must not win."""
        values = ["https://example.ch/tarife.json"] * 28 + ["https://old.example.ch/tarife.json"] * 2

        self.assertEqual(pick_tariff_url(values), ("https://example.ch/tarife.json", True))

    def test_tie_prefers_direct_json_over_landing_page(self):
        values = ["https://example.ch/strompreise"] * 5 + ["https://example.ch/tarife.json"] * 5

        self.assertEqual(pick_tariff_url(values), ("https://example.ch/tarife.json", True))

    def test_tie_between_two_direct_links_is_deterministic(self):
        """Real case: an operator mirrored on its own site and on a third-party
        aggregator, tied exactly. Any consistent choice is fine; it must not
        depend on SPARQL result ordering."""
        values_a = ["https://aettenschwil.example/tarife.json"] * 12 + ["https://aggregator.example/tarife.json"] * 12
        values_b = list(reversed(values_a))

        self.assertEqual(pick_tariff_url(values_a), pick_tariff_url(values_b))
        # Lexicographically first of the tied candidates.
        self.assertEqual(pick_tariff_url(values_a)[0], "https://aettenschwil.example/tarife.json")

    def test_normalisation_happens_before_counting(self):
        """A scheme-less and a schemed spelling of the same URL must be counted
        as one value, not split into two singleton ties."""
        values = ["www.example.ch/tarife.json"] * 3 + ["https://other.example/tarife.json"] * 2

        self.assertEqual(pick_tariff_url(values), ("https://www.example.ch/tarife.json", True))


class BuildOperatorsTests(SimpleTestCase):
    def test_collapses_repeated_rows_to_one_entry_per_operator(self):
        """The query is not DISTINCT — one row per (operator, municipality,
        category, product) — so 30-ish rows for one operator must become one
        fixture entry."""
        rows = [
            _row(id="625", name="InfraWerkeMünsingen (IWM)", uid="CHE-109.834.319",
                 website="www.inframuensingen.ch", urltr="www.inframuensingen.ch")
            for _ in range(30)
        ]

        operators = build_operators(rows)

        self.assertEqual(len(operators), 1)
        self.assertEqual(operators[0], {
            "id": 625,
            "name": "InfraWerkeMünsingen (IWM)",
            "uid": "CHE-109.834.319",
            "website": "www.inframuensingen.ch",
            "tariff_url": "https://www.inframuensingen.ch",
            "tariff_url_is_direct": False,
        })

    def test_operator_with_no_urltr_gets_blank_tariff_url(self):
        rows = [_row(id="1", name="No URL Utility", uid=None, website=None, urltr=None)]

        operators = build_operators(rows)

        self.assertEqual(operators[0]["tariff_url"], "")
        self.assertFalse(operators[0]["tariff_url_is_direct"])

    def test_sorted_case_insensitively_by_name(self):
        rows = [
            _row(id="1", name="zeta ag", uid=None, website=None, urltr=None),
            _row(id="2", name="Alpha AG", uid=None, website=None, urltr=None),
        ]

        operators = build_operators(rows)

        self.assertEqual([o["name"] for o in operators], ["Alpha AG", "zeta ag"])


class BuildPostalCodesTests(SimpleTestCase):
    def test_groups_operator_ids_by_postal_code(self):
        rows = [
            {"plz": {"value": "3110"}, "operatorId": {"value": "625"}},
            {"plz": {"value": "8001"}, "operatorId": {"value": "1"}},
            {"plz": {"value": "8001"}, "operatorId": {"value": "2"}},
        ]

        codes = build_postal_codes(rows)

        self.assertEqual(codes, {"3110": [625], "8001": [1, 2]})

    def test_duplicate_rows_are_deduplicated(self):
        """The query is DISTINCT, but a fixture builder should not rely on its
        caller having gotten that right."""
        rows = [
            {"plz": {"value": "3110"}, "operatorId": {"value": "625"}},
            {"plz": {"value": "3110"}, "operatorId": {"value": "625"}},
        ]

        self.assertEqual(build_postal_codes(rows), {"3110": [625]})

    def test_operator_ids_within_a_code_are_sorted(self):
        rows = [
            {"plz": {"value": "8001"}, "operatorId": {"value": "9"}},
            {"plz": {"value": "8001"}, "operatorId": {"value": "1"}},
        ]

        self.assertEqual(build_postal_codes(rows)["8001"], [1, 9])
