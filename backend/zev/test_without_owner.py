"""A ZEV without an owner account (#761, ADR 0028): access through grants, the
issuer through the dated role, and the old ``zev.owner`` template variables
answered by the issuer."""

from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.template import Context, Template
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.contract_pdf import _build_contract_context
from testing.helpers import authenticate, create_managed_zev, make_user

from .models import Participant, Zev, ZevAccessGrant, ZevAccessRole
from .parties import ensure_initial_roles


class ZevApiTests(TestCase):
    def setUp(self):
        self.manager = make_user("wo_manager", UserRole.USER)
        self.zev = create_managed_zev(name="No Owner", owner=self.manager, start_date=date(2026, 1, 1))
        self.client = APIClient()
        authenticate(self.client, self.manager)

    def test_a_zev_shows_its_issuer_and_no_owner(self):
        self.assertIsNone(self.client.get(f"/api/v1/zev/zevs/{self.zev.pk}/").json()["issuer"])
        own = Participant.objects.create(zev=self.zev, first_name="Ida", last_name="Issuer", valid_from=date(2026, 1, 1))
        ensure_initial_roles(self.zev, own.party, date(2026, 1, 1))
        body = self.client.get("/api/v1/zev/zevs/").json()
        row = (body.get("results", body) if isinstance(body, dict) else body)[0]
        self.assertNotIn("owner", row)
        self.assertEqual(row["issuer"], {"party": str(own.party_id), "display_name": "Ida Issuer"})

    def test_an_admin_creating_a_zev_gives_nobody_access(self):
        authenticate(self.client, make_user("wo_admin", UserRole.ADMIN))
        response = self.client.post(
            "/api/v1/zev/zevs/", {"name": "Admin made", "zev_type": "vzev", "invoice_prefix": "AM"}, format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertFalse(ZevAccessGrant.objects.filter(zev_id=response.json()["id"]).exists())

    def test_self_setup_makes_the_caller_manager_and_issuer(self):
        owner = make_user("wo_self", UserRole.USER, may_create_zev=True)
        owner.last_name = "Selbst"
        owner.save()
        authenticate(self.client, owner)
        response = self.client.post(
            "/api/v1/zev/zevs/self-setup/", {"name": "Mine", "zev_type": "vzev", "invoice_prefix": "MI"}, format="json",
        )
        self.assertIn(response.status_code, (200, 201), response.content)
        zev = Zev.objects.get(name="Mine")
        self.assertTrue(ZevAccessGrant.objects.filter(zev=zev, user=owner, role=ZevAccessRole.MANAGER).exists())
        self.assertEqual(zev.party_roles.filter(role="issuer").get().party.participations.get().user, owner)


class OwnerAliasTests(TestCase):
    def test_zev_owner_in_a_custom_template_is_the_issuer(self):
        zev = create_managed_zev(name="Alias", owner=make_user("wo_alias", UserRole.USER), start_date=date(2026, 1, 1))
        issuer = Participant.objects.create(
            zev=zev, first_name="Ida", last_name="Issuer", email="ida@example.com", valid_from=date(2026, 1, 1),
        )
        ensure_initial_roles(zev, issuer.party, date(2026, 1, 1))
        context = _build_contract_context(issuer, as_of=date(2026, 6, 1))
        rendered = Template(
            "{{ zev.owner.get_full_name }}|{{ zev.owner.email }}|{{ zev.owner.username }}|{{ zev.name }}"
        ).render(Context(context))
        self.assertEqual(rendered, "Ida Issuer|ida@example.com||Alias")


class RemoveOwnerMigrationTests(TransactionTestCase):
    BEFORE = [("zev", "0036_party_roles_from_owner")]
    AFTER = [("zev", "0037_remove_zev_owner")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        # Start from the latest schema: a plan that moves one app back while
        # another must move forward is refused, whatever an earlier test left.
        self.tearDown()

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_going_back_makes_the_current_manager_the_owner(self):
        manager = make_user("wo_mig_manager", UserRole.USER)
        zev = create_managed_zev(name="Mig", owner=manager)
        back = self.migrate(self.BEFORE)
        self.assertEqual(back.get_model("zev", "Zev").objects.get(pk=zev.pk).owner_id, manager.pk)
        self.migrate(self.AFTER)
        self.assertFalse(any(field.name == "owner" for field in Zev._meta.get_fields()))
