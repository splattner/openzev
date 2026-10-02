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
from testing.helpers import authenticate, create_managed_zev, make_user, zev_manager

from .models import Participant, Party, PartyKind, PartyRole, Zev, ZevAccessGrant, ZevAccessRole, ZevPartyRole
from .parties import assign_role, end_role, ensure_initial_roles, issuer_on, representative_on
from .services import create_zev_for_existing_owner


def make_zev(name="Role ZEV"):
    owner = make_user(f"owner_{name.replace(' ', '_').lower()}", UserRole.USER)
    return create_managed_zev(name=name, owner=owner, zev_type="vzev", invoice_prefix="R", start_date=date(2026, 1, 1))


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

    def test_a_participant_with_the_managing_account_is_not_the_issuer_by_itself(self):
        # Before Zev.owner was dropped its participation stood in; now only the role counts.
        Participant.objects.create(zev=self.zev, user=zev_manager(self.zev), last_name="Owner", valid_from=date(2026, 1, 1))
        self.assertIsNone(issuer_on(self.zev, date(2026, 3, 1)))

    def test_a_day_before_the_first_issuer_has_no_issuer(self):
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

    def test_roles_change_only_by_assigning_and_ending(self):
        authenticate(self.client, make_user("party_admin", UserRole.ADMIN))
        row = ZevPartyRole.objects.filter(zev=self.zev).first()
        self.assertEqual(self.client.patch(f"/api/v1/zev/party-roles/{row.pk}/", {"role": "landowner"}, format="json").status_code, 405)
        self.assertEqual(self.client.delete(f"/api/v1/zev/party-roles/{row.pk}/").status_code, 405)

    def test_a_participant_reaches_no_parties(self):
        # Ann was issuer until 2020: her participation's account gets nothing from that.
        former = Participant.objects.create(
            zev=self.zev, party=self.ann, valid_from=date(2021, 1, 1), user=make_user("party_former", UserRole.USER),
        )
        authenticate(self.client, former.user)
        self.assertEqual(self.client.get("/api/v1/zev/parties/").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/zev/party-roles/").status_code, 403)

    def test_the_issuers_participant_account_manages_the_zev(self):
        authenticate(self.client, self.member.user)
        self.assertEqual(self.client.get("/api/v1/zev/parties/").status_code, 200)

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


class PartyWriteApiTests(TestCase):
    """Managers add, edit and delete parties and assign and end roles; viewers only read."""

    def setUp(self):
        self.manager = make_user("pw_manager", UserRole.USER)
        self.zev = create_managed_zev(name="Write ZEV", owner=self.manager, start_date=date(2026, 1, 1))
        self.viewer = make_user("pw_viewer", UserRole.USER)
        ZevAccessGrant.objects.create(zev=self.zev, user=self.viewer, role=ZevAccessRole.VIEWER, valid_from=date(2026, 1, 1))
        self.client = APIClient()
        authenticate(self.client, self.manager)

    def create_party(self, **fields):
        body = {"zev": str(self.zev.pk), "kind": "organisation", "organisation_name": "Verwaltung Nord", **fields}
        return self.client.post("/api/v1/zev/parties/", body, format="json")

    def test_a_manager_adds_edits_and_deletes_a_contact(self):
        from audit.models import AuditEvent

        created = self.create_party(email="nord@example.com")
        self.assertEqual(created.status_code, 201, created.content)
        party_id = created.json()["id"]
        self.assertEqual(created.json()["display_name"], "Verwaltung Nord")
        patched = self.client.patch(f"/api/v1/zev/parties/{party_id}/", {"city": "Basel"}, format="json")
        self.assertEqual((patched.status_code, patched.json()["city"]), (200, "Basel"))
        self.assertEqual(self.client.delete(f"/api/v1/zev/parties/{party_id}/").status_code, 204)
        self.assertEqual(
            list(AuditEvent.objects.filter(target_type="zev.Party").order_by("created_at").values_list("action_type", flat=True)),
            ["party.create", "party.update", "party.delete"],
        )

    def test_names_are_required_by_kind(self):
        self.assertIn("organisation_name", self.create_party(organisation_name="").json())
        self.assertIn("last_name", self.create_party(kind="person").json())

    def test_a_party_in_use_cannot_be_deleted(self):
        tenant = Participant.objects.create(zev=self.zev, last_name="Muster", valid_from=date(2026, 1, 1))
        response = self.client.delete(f"/api/v1/zev/parties/{tenant.party_id}/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "This party is still a participant or holds a role.")

    def test_edits_show_on_every_participation(self):
        tenant = Participant.objects.create(zev=self.zev, last_name="Muster", valid_from=date(2026, 1, 1))
        self.client.patch(f"/api/v1/zev/parties/{tenant.party_id}/", {"name_addition": "c/o Muster"}, format="json")
        self.assertEqual(Participant.objects.get(pk=tenant.pk).name_addition, "c/o Muster")

    def test_a_manager_of_another_zev_cannot_add_a_party_here(self):
        stranger = make_user("pw_stranger", UserRole.USER)
        create_managed_zev(name="Elsewhere", owner=stranger)
        authenticate(self.client, stranger)
        response = self.create_party()
        self.assertEqual(response.status_code, 400)
        self.assertIn("zev", response.json())

    def test_a_viewer_reads_but_cannot_write(self):
        party_id = self.create_party().json()["id"]
        authenticate(self.client, self.viewer)
        self.assertEqual(self.client.get(f"/api/v1/zev/parties/?zev_id={self.zev.pk}").status_code, 200)
        self.assertEqual(self.create_party().status_code, 403)
        self.assertEqual(self.client.patch(f"/api/v1/zev/parties/{party_id}/", {"city": "X"}, format="json").status_code, 403)
        response = self.client.post("/api/v1/zev/party-roles/", {
            "zev": str(self.zev.pk), "party": party_id, "role": "issuer", "valid_from": "2026-01-01",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def assign(self, party_id, role, valid_from, **extra):
        return self.client.post("/api/v1/zev/party-roles/", {
            "zev": str(self.zev.pk), "party": party_id, "role": role, "valid_from": valid_from, **extra,
        }, format="json")

    def test_assigning_a_new_issuer_ends_the_previous_one(self):
        from audit.models import AuditEvent

        first, second = self.create_party().json()["id"], self.create_party(organisation_name="Süd AG").json()["id"]
        self.assertEqual(self.assign(first, "issuer", "2026-01-01").status_code, 201)
        response = self.assign(second, "issuer", "2026-07-01")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["party_display_name"], "Süd AG")
        self.assertEqual(
            sorted(self.zev.party_roles.values_list("party__organisation_name", "valid_to")),
            [("Süd AG", None), ("Verwaltung Nord", date(2026, 6, 30))],
        )
        event = AuditEvent.objects.filter(action_type="party_role.assign").latest("created_at")
        self.assertEqual((event.zev_id, event.metadata_json["role"], event.metadata_json["valid_from"]), (self.zev.pk, "issuer", "2026-07-01"))

    def test_a_later_holder_is_refused_with_the_reason(self):
        first, second = self.create_party().json()["id"], self.create_party(organisation_name="Süd AG").json()["id"]
        self.assign(first, "issuer", "2026-07-01")
        response = self.assign(second, "issuer", "2026-01-01")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"valid_from": ["A later holder exists; end it first."]})

    def test_ending_a_role(self):
        party_id = self.create_party().json()["id"]
        role_id = self.assign(party_id, "landowner", "2026-01-01").json()["id"]
        ended = self.client.post(f"/api/v1/zev/party-roles/{role_id}/end/", {"last_day": "2026-12-31"}, format="json")
        self.assertEqual((ended.status_code, ended.json()["valid_to"]), (200, "2026-12-31"))
        future = self.assign(party_id, "representative", "2027-03-01").json()["id"]
        gone = self.client.post(f"/api/v1/zev/party-roles/{future}/end/", {"last_day": "2027-02-28"}, format="json")
        self.assertEqual(gone.status_code, 204)
        self.assertFalse(ZevPartyRole.objects.filter(pk=future).exists())
