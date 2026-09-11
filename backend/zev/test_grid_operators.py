"""The ElCom grid-operator list and the id stored alongside a typed name.

The list exists so `Zev.grid_operator` stops accumulating "EKZ",
"Elektrizitätswerke des Kantons Zürich" and typos for the same utility — a
value that is printed on contracts and invoices. It is a suggestion source,
not a constraint, so the free-text field and the hand-typed case must keep
working (see #518, `zev.grid_operators`).
"""

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from testing.helpers import make_user
from zev.grid_operators import grid_operator_ids, grid_operators_for_postal_code, load_grid_operators
from zev.models import Zev

URL = "/api/v1/zev/grid-operators/"
SUGGEST_URL = "/api/v1/zev/grid-operators/suggest/"


class GridOperatorFixtureTests(TestCase):
    def test_fixture_carries_its_provenance(self):
        """Reference data shipped in the repo has to say where it came from and
        under what terms, or the next person cannot tell whether refreshing it
        is allowed."""
        data = load_grid_operators()

        self.assertEqual(data["source"], "https://lindas.admin.ch/query")
        self.assertEqual(data["licence"], "https://ld.admin.ch/vocabulary/TermsOfUse/Open-Use")
        self.assertTrue(data["period"])
        self.assertTrue(data["fetched_on"])

    def test_every_operator_has_an_id_and_a_name(self):
        operators = load_grid_operators()["operators"]

        self.assertGreater(len(operators), 400, "fixture looks truncated")
        for operator in operators:
            self.assertIsInstance(operator["id"], int)
            self.assertTrue(operator["name"].strip(), f"operator {operator['id']} has no name")
            # uid/website are optional upstream — present as "" when absent.
            self.assertIn("uid", operator)
            self.assertIn("website", operator)

    def test_operator_ids_are_unique(self):
        operators = load_grid_operators()["operators"]

        self.assertEqual(len({operator["id"] for operator in operators}), len(operators))

    def test_operators_are_sorted_by_name(self):
        """The picker renders them in fixture order; sorting here keeps the
        frontend from having to re-sort 553 entries on every open."""
        names = [operator["name"] for operator in load_grid_operators()["operators"]]

        self.assertEqual(names, sorted(names, key=str.casefold))

    def test_every_operator_carries_a_tariff_url_field(self):
        """Present even when empty, so the frontend never has to distinguish
        "not fetched yet" from "this operator publishes nothing" (see #691)."""
        operators = load_grid_operators()["operators"]

        for operator in operators:
            self.assertIn("tariff_url", operator)
            self.assertIn("tariff_url_is_direct", operator)
            self.assertIsInstance(operator["tariff_url_is_direct"], bool)
            if not operator["tariff_url"]:
                self.assertFalse(operator["tariff_url_is_direct"])

    def test_a_majority_of_operators_publish_a_tariff_url(self):
        """Not a hard requirement (see fetch_grid_operators --min-tariff-urls),
        but a fixture where almost nobody has one would mean the command's
        urltr handling broke silently rather than the real world changing."""
        operators = load_grid_operators()["operators"]

        with_url = sum(1 for operator in operators if operator["tariff_url"])
        self.assertGreater(with_url, len(operators) / 2)

    def test_postal_codes_map_only_to_known_operators(self):
        data = load_grid_operators()
        known_ids = {operator["id"] for operator in data["operators"]}

        self.assertGreater(len(data["postal_codes"]), 1000, "postal code map looks truncated")
        for postal_code, operator_ids in data["postal_codes"].items():
            self.assertTrue(postal_code.strip())
            self.assertTrue(operator_ids, f"{postal_code} maps to no operator")
            for operator_id in operator_ids:
                self.assertIn(operator_id, known_ids)


class GridOperatorEndpointTests(TestCase):
    def setUp(self):
        self.user = make_user("grid_operator_reader", UserRole.PARTICIPANT)
        self.client = APIClient()

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_returns_the_whole_list_unpaginated(self):
        """The picker filters client-side, so a paginated response would give
        it only the first 50 operators with no indication any were missing."""
        self.client.force_authenticate(self.user)

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("results", body, "response is paginated; the picker needs the full list")
        self.assertEqual(len(body["operators"]), len(load_grid_operators()["operators"]))
        self.assertEqual(body["licence"], "https://ld.admin.ch/vocabulary/TermsOfUse/Open-Use")

    def test_available_to_any_authenticated_role(self):
        """The self-setup wizard is the first form a new owner sees, and they
        reach it before they own anything."""
        self.client.force_authenticate(self.user)

        self.assertEqual(self.client.get(URL).status_code, 200)


class ZevGridOperatorIdTests(TestCase):
    def setUp(self):
        self.admin = make_user("grid_operator_admin", UserRole.ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _create(self, **overrides):
        payload = {
            "name": "Grid Operator ZEV",
            "start_date": "2026-01-01",
            "zev_type": "vzev",
            "owner": self.admin.id,
        }
        payload.update(overrides)
        return self.client.post("/api/v1/zev/zevs/", payload, format="json")

    def test_a_known_elcom_id_is_accepted_and_stored(self):
        known = sorted(grid_operator_ids())[0]

        response = self._create(grid_operator="Picked From List", grid_operator_elcom_id=known)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Zev.objects.get(pk=response.data["id"]).grid_operator_elcom_id, known)

    def test_an_unknown_elcom_id_is_rejected(self):
        """An arbitrary integer would look like it had worked while making the
        name unresolvable, which is the whole point of the field."""
        response = self._create(grid_operator="Made Up", grid_operator_elcom_id=999_999)

        self.assertEqual(response.status_code, 400)
        self.assertIn("grid_operator_elcom_id", response.data)

    def test_a_hand_typed_operator_needs_no_id(self):
        """A utility missing from ElCom's tariff cube — a recent merger, a small
        municipal works — must still be enterable."""
        response = self._create(grid_operator="Genossenschaft Kleindorf")

        self.assertEqual(response.status_code, 201, response.data)
        zev = Zev.objects.get(pk=response.data["id"])
        self.assertEqual(zev.grid_operator, "Genossenschaft Kleindorf")
        self.assertIsNone(zev.grid_operator_elcom_id)

    def test_existing_zevs_are_unaffected(self):
        """The field is additive: nothing had to be backfilled, and a ZEV
        created before it existed stays valid."""
        zev = Zev.objects.create(
            name="Legacy ZEV", owner=self.admin, zev_type="vzev",
            grid_operator="Typed Long Ago", invoice_prefix="L",
        )

        self.assertIsNone(zev.grid_operator_elcom_id)


class ZevPostalCodeTests(TestCase):
    """``Zev.postal_code`` itself: free text, like ``grid_operator``, because a
    ZEV with an address the register does not resolve must stay enterable."""

    def setUp(self):
        self.admin = make_user("postal_code_admin", UserRole.ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_postal_code_round_trips_through_the_api(self):
        response = self.client.post(
            "/api/v1/zev/zevs/",
            {
                "name": "Postal Code ZEV", "start_date": "2026-01-01",
                "zev_type": "vzev", "owner": self.admin.id, "postal_code": "3110",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Zev.objects.get(pk=response.data["id"]).postal_code, "3110")

    def test_postal_code_defaults_to_blank(self):
        zev = Zev.objects.create(
            name="No Postal Code ZEV", owner=self.admin, zev_type="vzev", invoice_prefix="N",
        )

        self.assertEqual(zev.postal_code, "")

    def test_an_unresolvable_postal_code_is_still_accepted(self):
        """Nothing validates this against the ElCom register — it is a
        suggestion source, not a constraint (same rule as grid_operator)."""
        response = self.client.post(
            "/api/v1/zev/zevs/",
            {
                "name": "Foreign ZEV", "start_date": "2026-01-01",
                "zev_type": "vzev", "owner": self.admin.id, "postal_code": "00000",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)


class GridOperatorsForPostalCodeTests(TestCase):
    """The lookup behind the suggestion endpoint, exercised against whatever
    postal code the shipped fixture actually resolves to a single operator —
    Münsingen (3110 -> InfraWerkeMünsingen) at the time of writing, per #691."""

    def test_a_known_single_operator_postal_code_resolves(self):
        data = load_grid_operators()
        single_operator_code = next(
            code for code, ids in data["postal_codes"].items() if len(ids) == 1
        )

        result = grid_operators_for_postal_code(single_operator_code)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], data["postal_codes"][single_operator_code][0])

    def test_a_postal_code_with_several_operators_returns_all_of_them(self):
        data = load_grid_operators()
        multi_operator_code = next(
            (code for code, ids in data["postal_codes"].items() if len(ids) > 1), None
        )
        if multi_operator_code is None:
            self.skipTest("fixture has no postal code with several operators right now")

        result = grid_operators_for_postal_code(multi_operator_code)

        self.assertEqual(
            {operator["id"] for operator in result},
            set(data["postal_codes"][multi_operator_code]),
        )

    def test_an_unknown_postal_code_resolves_to_nothing(self):
        """The caller falls back to the free-text picker — this is not an
        error case."""
        self.assertEqual(grid_operators_for_postal_code("0000"), [])

    def test_blank_postal_code_resolves_to_nothing(self):
        self.assertEqual(grid_operators_for_postal_code(""), [])
        self.assertEqual(grid_operators_for_postal_code("   "), [])

    def test_surrounding_whitespace_is_tolerated(self):
        data = load_grid_operators()
        single_operator_code = next(
            code for code, ids in data["postal_codes"].items() if len(ids) == 1
        )

        self.assertEqual(
            grid_operators_for_postal_code(f"  {single_operator_code}  "),
            grid_operators_for_postal_code(single_operator_code),
        )


class GridOperatorSuggestionEndpointTests(TestCase):
    def setUp(self):
        self.user = make_user("grid_operator_suggestion_reader", UserRole.PARTICIPANT)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_requires_authentication(self):
        response = APIClient().get(SUGGEST_URL, {"postal_code": "3110"})

        self.assertEqual(response.status_code, 401)

    def test_a_resolvable_postal_code_returns_its_operator(self):
        data = load_grid_operators()
        single_operator_code = next(
            code for code, ids in data["postal_codes"].items() if len(ids) == 1
        )
        expected_id = data["postal_codes"][single_operator_code][0]

        response = self.client.get(SUGGEST_URL, {"postal_code": single_operator_code})

        self.assertEqual(response.status_code, 200)
        operators = response.json()["operators"]
        self.assertEqual(len(operators), 1)
        self.assertEqual(operators[0]["id"], expected_id)
        self.assertIn("tariff_url", operators[0])
        self.assertIn("tariff_url_is_direct", operators[0])

    def test_an_unresolvable_postal_code_returns_an_empty_list(self):
        """Not a 404: an address the register does not cover is an expected,
        silent outcome, not an error the frontend needs to handle specially."""
        response = self.client.get(SUGGEST_URL, {"postal_code": "0000"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"operators": []})

    def test_missing_postal_code_param_returns_an_empty_list(self):
        response = self.client.get(SUGGEST_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"operators": []})
