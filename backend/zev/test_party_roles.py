"""Dated issuer, representative and landowner roles of a ZEV's parties (#761, ADR 0028)."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.template import Context, Template
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.contract_pdf import _build_contract_context
from invoices.document_parties import build_copy, copy_for_render
from invoices.models import Invoice, InvoiceStatus
from invoices.workflow import approve_invoice
from testing.helpers import authenticate, make_user

from .models import Participant, Party, PartyKind, PartyRole, Zev, ZevAccessGrant, ZevAccessRole, ZevPartyRole
from .parties import assign_role, end_role, ensure_initial_roles, issuer_on, representative_on
from .services import create_zev_for_existing_owner


def make_zev(name="Role ZEV"):
    owner = make_user(f"owner_{name.replace(' ', '_').lower()}", UserRole.USER)
    return Zev.objects.create(name=name, owner=owner, zev_type="vzev", invoice_prefix="R", start_date=date(2026, 1, 1))


def party(zev, last_name, **fields):
    return Party.objects.create(zev=zev, last_name=last_name, city="Bern", **fields)


class AssignRoleTests(TestCase):
    def setUp(self):
        self.zev = make_zev()
        self.ann, self.bob = party(self.zev, "Ann"), party(self.zev, "Bob")

    def test_a_new_issuer_ends_the_previous_one_the_day_before(self):
        first = assign_role(self.zev, self.ann, PartyRole.ISSUER, date(2026, 1, 1))
        assign_role(self.zev, self.bob, PartyRole.ISSUER, date(2026, 7, 1))
        first.refresh_from_db()
        self.assertEqual(first.valid_to, date(2026, 6, 30))
        self.assertEqual(issuer_on(self.zev, date(2026, 6, 30)), self.ann)
        self.assertEqual(issuer_on(self.zev, date(2026, 7, 1)), self.bob)

    def test_a_holder_replaced_on_its_first_day_is_removed(self):
        assign_role(self.zev, self.ann, PartyRole.REPRESENTATIVE, date(2026, 3, 1))
        assign_role(self.zev, self.bob, PartyRole.REPRESENTATIVE, date(2026, 3, 1))
        self.assertEqual(list(ZevPartyRole.objects.values_list("party_id", flat=True)), [self.bob.pk])
        self.assertEqual(representative_on(self.zev, date(2026, 3, 1)), self.bob)

    def test_a_later_holder_must_be_ended_first(self):
        assign_role(self.zev, self.ann, PartyRole.ISSUER, date(2026, 7, 1))
        with self.assertRaises(ValidationError):
            assign_role(self.zev, self.bob, PartyRole.ISSUER, date(2026, 1, 1))

    def test_landowners_are_many_but_once_per_party(self):
        assign_role(self.zev, self.ann, PartyRole.LANDOWNER, date(2026, 1, 1))
        assign_role(self.zev, self.bob, PartyRole.LANDOWNER, date(2026, 1, 1))
        self.assertEqual(ZevPartyRole.objects.filter(role=PartyRole.LANDOWNER).count(), 2)
        with self.assertRaises(ValidationError):
            assign_role(self.zev, self.ann, PartyRole.LANDOWNER, date(2026, 5, 1))

    def test_a_party_of_another_zev_is_refused(self):
        stranger = party(make_zev("Other"), "Stranger")
        with self.assertRaises(ValidationError):
            assign_role(self.zev, stranger, PartyRole.ISSUER, date(2026, 1, 1))

    def test_ending_before_the_start_removes_the_role(self):
        row = assign_role(self.zev, self.ann, PartyRole.ISSUER, date(2026, 5, 1))
        self.assertIsNone(end_role(row, date(2026, 4, 30)))
        self.assertFalse(ZevPartyRole.objects.exists())
        row = assign_role(self.zev, self.ann, PartyRole.ISSUER, date(2026, 5, 1))
        self.assertEqual(end_role(row, date(2026, 5, 31)).valid_to, date(2026, 5, 31))
        self.assertIsNone(issuer_on(self.zev, date(2026, 6, 1)))

    def test_the_database_allows_one_open_issuer(self):
        ZevPartyRole.objects.create(zev=self.zev, party=self.ann, role=PartyRole.ISSUER, valid_from=date(2026, 1, 1))
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ZevPartyRole.objects.create(zev=self.zev, party=self.bob, role=PartyRole.ISSUER, valid_from=date(2026, 2, 1))
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ZevPartyRole.objects.create(
                zev=self.zev, party=self.bob, role=PartyRole.LANDOWNER,
                valid_from=date(2026, 2, 1), valid_to=date(2026, 1, 1),
            )


class IssuerLookupTests(TestCase):
    def setUp(self):
        self.zev = make_zev()

    def test_without_any_issuer_role_the_owner_participation_is_the_issuer(self):
        own = Participant.objects.create(zev=self.zev, user=self.zev.owner, last_name="Owner", valid_from=date(2026, 1, 1))
        self.assertEqual(issuer_on(self.zev, date(2026, 3, 1)), own.party)

    def test_once_a_zev_has_issuer_roles_a_gap_has_no_issuer(self):
        Participant.objects.create(zev=self.zev, user=self.zev.owner, last_name="Owner", valid_from=date(2026, 1, 1))
        assign_role(self.zev, party(self.zev, "Later"), PartyRole.ISSUER, date(2026, 7, 1))
        self.assertIsNone(issuer_on(self.zev, date(2026, 3, 1)))

    def test_creating_a_zev_for_its_owner_makes_them_issuer_and_landowner(self):
        owner = make_user("self_setup_owner", UserRole.USER)
        owner.last_name = "Selbst"
        owner.save()
        result = create_zev_for_existing_owner(
            owner_user=owner, zev_data={"name": "Own", "start_date": date(2026, 2, 1)},
        )
        zev = Zev.objects.get(pk=result["zev"]["id"])
        own = Participant.objects.get(pk=result["owner_participant_id"])
        self.assertEqual(
            sorted(zev.party_roles.values_list("role", "party_id", "valid_from")),
            [("issuer", own.party_id, date(2026, 2, 1)), ("landowner", own.party_id, date(2026, 2, 1))],
        )
        ensure_initial_roles(zev, own.party, date(2026, 3, 1))
        self.assertEqual(zev.party_roles.count(), 2)


class DocumentIssuerByDateTests(TestCase):
    """Which issuer a document names follows its own date."""

    def setUp(self):
        self.zev = make_zev()
        self.old = party(self.zev, "Alt", first_name="Anna", address_line1="Altweg 1")
        self.new = Party.objects.create(
            zev=self.zev, kind=PartyKind.ORGANISATION, organisation_name="Neu AG", address_line1="Neuweg 2",
        )
        assign_role(self.zev, self.old, PartyRole.ISSUER, date(2026, 1, 1))
        assign_role(self.zev, self.new, PartyRole.ISSUER, date(2026, 7, 1))
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Paul", last_name="Teil", email="p@example.com", valid_from=date(2026, 1, 1),
        )

    def invoice(self, start, end, number):
        return Invoice.objects.create(
            invoice_number=number, zev=self.zev, participant=self.participant,
            period_start=start, period_end=end, total_chf=Decimal("10.00"),
        )

    def test_an_invoice_is_from_the_issuer_on_its_last_day(self):
        before = build_copy(self.invoice(date(2026, 6, 1), date(2026, 6, 30), "R-1"))["issuer"]
        after = build_copy(self.invoice(date(2026, 7, 1), date(2026, 7, 31), "R-2"))["issuer"]
        self.assertEqual((before["name"], before["address_line1"]), ("Anna Alt", "Altweg 1"))
        self.assertEqual((after["name"], after["kind"], after["party"]), ("Neu AG", "organisation", str(self.new.pk)))

    def test_an_approved_invoice_keeps_its_issuer_when_the_issuer_changes(self):
        invoice = self.invoice(date(2026, 8, 1), date(2026, 8, 31), "R-3")
        approve_invoice(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.APPROVED)
        assign_role(self.zev, self.old, PartyRole.ISSUER, date(2026, 8, 1))
        issuer, _recipient = copy_for_render(invoice)
        self.assertEqual(issuer["name"], "Neu AG")

    def test_a_contract_is_from_the_issuer_on_its_date(self):
        before = _build_contract_context(self.participant, as_of=date(2026, 6, 30))
        after = _build_contract_context(self.participant, as_of=date(2026, 7, 1))
        self.assertEqual(before["issuer"]["name"], "Anna Alt")
        self.assertEqual(after["issuer"]["name"], "Neu AG")
        # The deprecated alias keeps custom templates rendering.
        self.assertEqual(
            Template("{{ owner_participant.full_name }}, {{ owner_participant.address_line1 }}").render(Context(before)),
            "Anna Alt, Altweg 1",
        )

    def test_an_annual_statement_is_from_the_issuer_on_31_december(self):
        captured = {}

        def render(_template, context):
            captured.update(context)
            return ""

        from invoices.annual_statement import generate_annual_statement_pdf

        with patch("invoices.annual_statement._render_template", side_effect=render), \
                patch("invoices.annual_statement.render_pdf", return_value=b""):
            generate_annual_statement_pdf(self.participant, self.zev, 2026)
        self.assertEqual(captured["issuer"]["name"], "Neu AG")
        self.assertIsNone(captured["representative"])

    def test_the_representative_on_the_document_date(self):
        assign_role(self.zev, self.old, PartyRole.REPRESENTATIVE, date(2026, 1, 1))
        context = _build_contract_context(self.participant, as_of=date(2026, 7, 1))
        self.assertEqual(context["representative"]["name"], "Anna Alt")


class PartyRoleApiTests(TestCase):
    def setUp(self):
        self.zev = make_zev()
        self.ann, self.bob = party(self.zev, "Ann"), party(self.zev, "Bob")
        assign_role(self.zev, self.ann, PartyRole.ISSUER, date(2020, 1, 1))
        assign_role(self.zev, self.bob, PartyRole.ISSUER, date(2021, 1, 1))
        assign_role(self.zev, self.bob, PartyRole.LANDOWNER, date(2021, 1, 1))
        self.member = Participant.objects.create(
            zev=self.zev, party=self.bob, valid_from=date(2021, 1, 1),
            user=make_user("party_member", UserRole.USER),
        )
        party(make_zev("Elsewhere"), "Stranger")
        self.client = APIClient()

    def as_viewer(self):
        viewer = make_user("party_viewer", UserRole.USER)
        ZevAccessGrant.objects.create(zev=self.zev, user=viewer, role=ZevAccessRole.VIEWER, valid_from=date(2020, 1, 1))
        authenticate(self.client, viewer)

    def test_a_viewer_lists_the_parties_of_its_zev(self):
        self.as_viewer()
        response = self.client.get("/api/v1/zev/parties/")
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        self.assertEqual([row["display_name"] for row in rows], ["Ann", "Bob"])
        bob = rows[1]
        self.assertEqual([p["id"] for p in bob["participations"]], [str(self.member.pk)])
        self.assertEqual(sorted(role["role"] for role in bob["roles"]), ["issuer", "landowner"])
        self.assertEqual(rows[0]["roles"], [])

    def test_roles_list_the_current_ones_and_on_request_the_history(self):
        self.as_viewer()
        current = self.client.get(f"/api/v1/zev/party-roles/?zev_id={self.zev.pk}").json()
        current = current.get("results", current) if isinstance(current, dict) else current
        self.assertEqual(sorted((row["role"], row["party_display_name"]) for row in current),
                         [("issuer", "Bob"), ("landowner", "Bob")])
        history = self.client.get(f"/api/v1/zev/party-roles/?zev_id={self.zev.pk}&include_ended=true").json()
        history = history.get("results", history) if isinstance(history, dict) else history
        self.assertEqual(len(history), 3)

    def test_the_endpoints_are_read_only(self):
        authenticate(self.client, make_user("party_admin", UserRole.ADMIN))
        response = self.client.post("/api/v1/zev/parties/", {"zev": str(self.zev.pk), "last_name": "X"}, format="json")
        self.assertEqual(response.status_code, 405)

    def test_a_participant_reaches_no_parties(self):
        authenticate(self.client, self.member.user)
        self.assertEqual(self.client.get("/api/v1/zev/parties/").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/zev/party-roles/").status_code, 403)

    def test_a_participant_row_lists_its_party_roles(self):
        self.as_viewer()
        own = self.client.get(f"/api/v1/zev/participants/{self.member.pk}/").json()
        self.assertEqual(sorted(role["role"] for role in own["roles"]), ["issuer", "landowner"])

    def test_another_zev_is_out_of_reach(self):
        self.as_viewer()
        stranger = Party.objects.get(last_name="Stranger")
        self.assertEqual(self.client.get(f"/api/v1/zev/parties/{stranger.pk}/").status_code, 404)

class PartyRoleMigrationTests(TransactionTestCase):
    BEFORE = [("zev", "0035_party_role"), ("invoices", "0019_invoice_issuer_recipient_copy")]
    AFTER = [("zev", "0036_party_roles_from_owner")]

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

    def test_the_owner_party_becomes_issuer_and_landowner_from_the_first_dated_document(self):
        old = self.migrate(self.BEFORE)
        owner, other = make_user("mig_role_owner"), make_user("mig_role_other")
        Zev_, Party_, Participant_ = (old.get_model("zev", name) for name in ("Zev", "Party", "Participant"))
        zev = Zev_.objects.create(name="Mig", owner_id=owner.pk, start_date=date(2026, 1, 1))
        own_party = Party_.objects.create(zev=zev, last_name="Owner", sort_name="Owner")
        own = Participant_.objects.create(zev=zev, party=own_party, user_id=owner.pk, valid_from=date(2026, 1, 1))
        old.get_model("invoices", "Invoice").objects.create(
            invoice_number="M-1", zev=zev, participant=own,
            period_start=date(2025, 10, 1), period_end=date(2025, 12, 31),
        )
        lonely = Zev_.objects.create(name="No owner row", owner_id=other.pk, start_date=date(2026, 1, 1))

        new = self.migrate(self.AFTER)
        roles = new.get_model("zev", "ZevPartyRole").objects
        self.assertEqual(
            sorted(roles.filter(zev_id=zev.pk).values_list("role", "party_id", "valid_from", "valid_to")),
            [("issuer", own_party.pk, date(2025, 10, 1), None), ("landowner", own_party.pk, date(2025, 10, 1), None)],
        )
        self.assertFalse(roles.filter(zev_id=lonely.pk).exists())

        self.migrate(self.BEFORE)
        self.assertFalse(old.get_model("zev", "ZevPartyRole").objects.exists())
