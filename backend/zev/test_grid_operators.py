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
from zev.grid_operators import grid_operator_ids, load_grid_operators
from zev.models import Zev

URL = "/api/v1/zev/grid-operators/"


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
