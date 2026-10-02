"""Parties of a ZEV and participants as their billing relationships (#761, ADR 0028)."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from invoices.document_parties import build_recipient
from invoices.models import Invoice
from invoices.pdf import _build_qr_svg
from testing.helpers import authenticate, make_user, create_managed_zev, zev_manager

from .models import Participant, Party, PartyKind
from zev.parties import ensure_initial_roles


def make_zev(name="Party ZEV"):
    owner = make_user(f"owner_{name.replace(' ', '_').lower()}", UserRole.USER)
    return create_managed_zev(name=name, owner=owner, zev_type="vzev", invoice_prefix="P", start_date=date(2026, 1, 1))


class PartyTests(TestCase):
    def setUp(self):
        self.zev = make_zev()

    def test_a_person_needs_a_last_name_and_an_organisation_a_name(self):
        with self.assertRaises(ValidationError) as person:
            Party(zev=self.zev, kind=PartyKind.PERSON, first_name="Ann").full_clean()
        self.assertIn("last_name", person.exception.message_dict)
        with self.assertRaises(ValidationError) as organisation:
            Party(zev=self.zev, kind=PartyKind.ORGANISATION, last_name="Contact").full_clean()
        self.assertIn("organisation_name", organisation.exception.message_dict)

    def test_names(self):
        person = Party(zev=self.zev, title="ms", first_name="Ann", last_name="Muster", name_addition="and Max Muster")
        self.assertEqual(person.display_name, "Ms. Ann Muster")
        self.assertEqual(person.name_lines, ["Ms. Ann Muster", "and Max Muster"])
        company = Party(zev=self.zev, kind=PartyKind.ORGANISATION, organisation_name="Bäckerei Sonne AG",
                        first_name="Ann", last_name="Contact")
        self.assertEqual(company.display_name, "Bäckerei Sonne AG")
        self.assertEqual(company.name_lines, ["Bäckerei Sonne AG"])

    def test_the_qr_name_is_one_line_of_at_most_70_characters(self):
        party = Party(zev=self.zev, kind=PartyKind.ORGANISATION, organisation_name="A" * 60, name_addition="c/o Somebody Long")
        self.assertEqual(len(party.qr_name), 70)
        self.assertTrue(party.qr_name.startswith("A" * 60 + " c/o"))

    def test_lists_sort_organisations_by_name_among_people(self):
        for kind, org, last in ((PartyKind.PERSON, "", "Zulu"), (PartyKind.ORGANISATION, "Mitte AG", ""),
                                (PartyKind.PERSON, "", "Alpha")):
            Party.objects.create(zev=self.zev, kind=kind, organisation_name=org, last_name=last)
        self.assertEqual([p.display_name for p in Party.objects.filter(zev=self.zev)], ["Alpha", "Mitte AG", "Zulu"])


class ParticipantFacadeTests(TestCase):
    def setUp(self):
        self.zev = make_zev()

    def test_creating_a_participant_creates_its_party(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="Ann", last_name="Muster", email="ann@example.com",
            city="Bern", valid_from=date(2026, 1, 1),
        )
        party = Party.objects.get(pk=participant.party_id)
        self.assertEqual((party.zev_id, party.last_name, party.email, party.city), (self.zev.pk, "Muster", "ann@example.com", "Bern"))
        self.assertEqual(participant.full_name, "Ann Muster")

    def test_edits_write_through_to_the_party(self):
        participant = Participant.objects.create(zev=self.zev, first_name="Ann", last_name="Muster", valid_from=date(2026, 1, 1))
        participant.city = "Thun"
        participant.save(update_fields=["city"])
        self.assertEqual(Party.objects.get(pk=participant.party_id).city, "Thun")

        participant.address_line1 = "Seeweg 1"
        participant.save()
        fresh = Participant.objects.get(pk=participant.pk)
        self.assertEqual((fresh.address_line1, fresh.city), ("Seeweg 1", "Thun"))

    def test_participations_of_one_party_share_its_name_and_address(self):
        first = Participant.objects.create(zev=self.zev, first_name="Ann", last_name="Muster", valid_from=date(2026, 1, 1))
        second = Participant.objects.create(zev=self.zev, party=first.party, valid_from=date(2026, 7, 1))
        first.city = "Biel"
        first.save()
        second.refresh_from_db()
        self.assertEqual((second.full_name, second.city), ("Ann Muster", "Biel"))
        self.assertEqual(Party.objects.filter(zev=self.zev).count(), 1)

    def test_refresh_discards_staged_values(self):
        participant = Participant.objects.create(zev=self.zev, first_name="Ann", last_name="Muster", valid_from=date(2026, 1, 1))
        participant.last_name = "Unsaved"
        participant.refresh_from_db()
        self.assertEqual(participant.last_name, "Muster")

    def test_a_participant_cannot_take_a_party_of_another_zev(self):
        other = Party.objects.create(zev=make_zev("Other ZEV"), last_name="Elsewhere")
        participant = Participant(zev=self.zev, party=other, valid_from=date(2026, 1, 1))
        with self.assertRaises(ValidationError):
            participant.full_clean()

    def test_an_organisation_participant_is_billed_under_its_name(self):
        participant = Participant.objects.create(
            zev=self.zev, kind=PartyKind.ORGANISATION, organisation_name="Bäckerei Sonne AG",
            name_addition="z. Hd. Buchhaltung", address_line1="Hauptgasse 2", postal_code="3000", city="Bern",
            valid_from=date(2026, 1, 1),
        )
        self.assertEqual(participant.full_name, "Bäckerei Sonne AG")
        recipient = build_recipient(participant)
        self.assertEqual(recipient["name"], "Bäckerei Sonne AG")
        self.assertEqual(recipient["name_lines"], ["Bäckerei Sonne AG", "z. Hd. Buchhaltung"])
        self.assertEqual((recipient["kind"], recipient["party"]), ("organisation", str(participant.party_id)))

    def test_the_qr_bill_carries_the_organisation_and_its_second_line(self):
        self.zev.bank_iban = "CH9300762011623852957"
        self.zev.save(update_fields=["bank_iban"])
        issuer = Participant.objects.create(
            zev=self.zev, user=zev_manager(self.zev), first_name="Olga", last_name="Owner",
            address_line1="Hof 1", postal_code="8001", city="Zuerich", valid_from=date(2026, 1, 1),
        )
        ensure_initial_roles(issuer.zev, issuer.party, issuer.valid_from)
        company = Participant.objects.create(
            zev=self.zev, kind=PartyKind.ORGANISATION, organisation_name="Sonne AG", name_addition="Filiale Bern",
            address_line1="Hauptgasse 2", postal_code="3000", city="Bern", valid_from=date(2026, 1, 1),
        )
        invoice = Invoice.objects.create(
            invoice_number="P-1", zev=self.zev, participant=company, period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31), total_chf=Decimal("10.00"),
        )
        with patch("qrbill.QRBill") as qrbill_cls:
            bill = MagicMock()
            qrbill_cls.return_value = bill
            bill.as_svg.side_effect = lambda output: output.write(b"<svg/>")
            _build_qr_svg(invoice)
        self.assertEqual(qrbill_cls.call_args.kwargs["debtor"]["name"], "Sonne AG Filiale Bern")


class ParticipantApiTests(TestCase):
    def setUp(self):
        self.zev = make_zev()
        self.client = APIClient()
        authenticate(self.client, make_user("party_admin", UserRole.ADMIN))

    def post(self, **payload):
        body = {"zev": str(self.zev.pk), "email": "x@example.com", "valid_from": "2026-01-01", **payload}
        return self.client.post("/api/v1/zev/participants/", body, format="json")

    def test_an_organisation_participant(self):
        response = self.post(kind="organisation", organisation_name="Sonne AG", name_addition="Filiale Bern")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["display_name"], body["full_name"], body["kind"]), ("Sonne AG", "Sonne AG", "organisation"))
        self.assertEqual(body["name_addition"], "Filiale Bern")
        self.assertTrue(body["party"])

    def test_names_are_required_by_kind(self):
        self.assertIn("organisation_name", self.post(kind="organisation").json())
        self.assertIn("last_name", self.post(first_name="Ann").json())

    def test_a_second_participation_of_the_same_party(self):
        first = self.post(first_name="Ann", last_name="Muster").json()
        response = self.post(party=first["party"], valid_from="2026-07-01")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["full_name"], "Ann Muster")
        self.assertEqual(Participant.objects.filter(party_id=first["party"]).count(), 2)

    def test_a_party_of_another_zev_is_refused(self):
        other = Party.objects.create(zev=make_zev("Elsewhere"), last_name="Other")
        response = self.post(party=str(other.pk))
        self.assertEqual(response.status_code, 400)
        self.assertIn("party", response.json())


class PartyMigrationTests(TransactionTestCase):
    BEFORE = [("zev", "0031_zev_access_grant"), ("accounts", "0021_collapse_user_role")]
    AFTER = [("zev", "0034_participant_party_required")]

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

    def test_every_participant_gets_a_party_with_its_fields_and_back(self):
        old = self.migrate(self.BEFORE)
        owner = make_user("mig_party_owner")
        zev = old.get_model("zev", "Zev").objects.create(name="Mig", owner_id=owner.pk)
        old.get_model("zev", "Participant").objects.create(
            zev=zev, title="ms", first_name="Ann", last_name="Muster", email="ann@example.com",
            address_line1="Weg 1", postal_code="3000", city="Bern", valid_from=date(2026, 1, 1),
        )

        new = self.migrate(self.AFTER)
        participant = new.get_model("zev", "Participant").objects.select_related("party").get()
        party = participant.party
        self.assertEqual(
            (party.zev_id, party.kind, party.title, party.first_name, party.last_name, party.email, party.city, party.sort_name),
            (zev.pk, "person", "ms", "Ann", "Muster", "ann@example.com", "Bern", "Muster"),
        )

        back = self.migrate(self.BEFORE)
        restored = back.get_model("zev", "Participant").objects.get()
        self.assertEqual((restored.first_name, restored.last_name, restored.city), ("Ann", "Muster", "Bern"))
