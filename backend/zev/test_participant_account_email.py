"""#1005: a participant's email identifies its account; rows with one address share it."""

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from testing.helpers import authenticate, create_managed_zev, make_user

from .models import Participant, Zev, ZevAccessGrant, ZevAccessRole
from .services import ensure_participant_account


class ParticipantAccountEmailTests(TestCase):
    def setUp(self):
        self.owner = make_user("pe_owner", UserRole.USER)
        self.zev = create_managed_zev(name="Email ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="E")
        self.other_zev = create_managed_zev(name="Other ZEV", zev_type="vzev", invoice_prefix="O")

    def participant(self, email, *, zev=None, last_name="Muster"):
        row = Participant.objects.create(
            zev=zev or self.zev, first_name="Anna", last_name=last_name, email=email, valid_from=date(2026, 1, 1),
        )
        ensure_participant_account(row)
        row.refresh_from_db()
        return row

    def test_rows_with_one_address_share_one_account(self):
        first = self.participant("anna@example.com")
        second = self.participant("ANNA@example.com", last_name="Zweit")
        third = self.participant("anna@example.com", zev=self.other_zev)

        self.assertEqual({first.user_id, second.user_id, third.user_id}, {first.user_id})
        self.assertEqual(User.objects.filter(email__iexact="anna@example.com").count(), 1)

    def test_an_existing_login_is_linked_untouched(self):
        login = make_user("pe_login", UserRole.USER)
        before = login.password

        row = self.participant(login.email.upper())

        login.refresh_from_db()
        self.assertEqual(row.user_id, login.pk)
        self.assertEqual((login.password, login.email), (before, "pe_login@example.com"))

    def test_editing_a_sole_row_moves_its_account_to_the_new_address(self):
        row = self.participant("old@example.com")
        account = row.user

        row.email = "new@example.com"
        ensure_participant_account(row)

        account.refresh_from_db()
        self.assertEqual(account.email, "new@example.com")
        self.assertEqual(User.objects.count(), 2)  # owner + the participant

    def test_editing_one_of_several_rows_leaves_the_shared_account_alone(self):
        first = self.participant("shared@example.com")
        second = self.participant("shared@example.com", last_name="Zweit")

        second.email = "own@example.com"
        ensure_participant_account(second)
        first.refresh_from_db()
        second.refresh_from_db()

        self.assertEqual(User.objects.get(pk=first.user_id).email, "shared@example.com")
        self.assertNotEqual(second.user_id, first.user_id)
        self.assertEqual(User.objects.get(pk=second.user_id).email, "own@example.com")

    def test_moving_a_row_to_an_address_that_has_an_account_relinks_it(self):
        mine = self.participant("mine@example.com")
        theirs = self.participant("theirs@example.com", last_name="Andere")

        mine.email = "theirs@example.com"
        ensure_participant_account(mine)
        mine.refresh_from_db()

        self.assertEqual(mine.user_id, theirs.user_id)


class ParticipantApiEmailTests(TestCase):
    def setUp(self):
        self.admin = make_user("pa_admin", UserRole.ADMIN)
        self.owner = make_user("pa_owner", UserRole.USER)
        self.zev = create_managed_zev(name="Api ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="A")
        self.viewer = make_user("pa_viewer", UserRole.USER)
        ZevAccessGrant.objects.create(
            zev=self.zev, user=self.viewer, role=ZevAccessRole.VIEWER, valid_from=date(2026, 1, 1),
        )

    def client_for(self, user):
        client = APIClient()
        authenticate(client, user)
        return client

    def payload(self, email):
        return {
            "zev": str(self.zev.pk), "first_name": "Neu", "last_name": "Teilnehmer", "email": email,
            "valid_from": "2026-01-01", "kind": "person",
        }

    def test_a_manager_cannot_attach_a_row_to_an_account_with_its_own_login(self):
        response = self.client_for(self.owner).post(
            "/api/v1/zev/participants/", self.payload(self.viewer.email), format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("user", response.json())
        self.assertFalse(Participant.objects.filter(party__email__iexact=self.viewer.email).exists())

    def test_an_admin_can(self):
        response = self.client_for(self.admin).post(
            "/api/v1/zev/participants/", self.payload(self.viewer.email), format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Participant.objects.get(pk=response.json()["id"]).user_id, self.viewer.pk)

    def test_a_manager_reuses_a_participant_only_account_by_address(self):
        client = self.client_for(self.owner)
        first = client.post("/api/v1/zev/participants/", self.payload("same@example.com"), format="json")
        second = client.post("/api/v1/zev/participants/", self.payload("SAME@example.com"), format="json")
        self.assertEqual((first.status_code, second.status_code), (201, 201), (first.content, second.content))
        users = Participant.objects.filter(pk__in=[first.json()["id"], second.json()["id"]]).values_list("user_id", flat=True)
        self.assertEqual(len(set(users)), 1)
        self.assertEqual(User.objects.filter(email__iexact="same@example.com").count(), 1)


class ZevOwnerSetupEmailTests(TestCase):
    def test_an_owner_address_that_has_an_account_is_refused(self):
        admin = make_user("os_admin", UserRole.ADMIN)
        taken = make_user("os_taken", UserRole.USER)
        client = APIClient()
        authenticate(client, admin)

        response = client.post(
            "/api/v1/zev/zevs/create-with-owner/",
            {
                "name": "Owner ZEV", "start_date": "2026-03-01", "zev_type": "vzev", "billing_interval": "monthly",
                "owner": {"first_name": "Ta", "last_name": "Ken", "email": taken.email.upper()},
                "metering_points": [{"meter_id": "METER-OWN", "meter_type": "consumption"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("email", response.json()["owner"])


class ZevOwnerSetupExistingAccountTests(TestCase):
    """#1009: the wizard can make an existing account the owner."""

    def setUp(self):
        self.admin = make_user("eo_admin", UserRole.ADMIN)
        self.client = APIClient()
        authenticate(self.client, self.admin)

    def post(self, owner, **extra):
        payload = {
            "name": "Existing Owner ZEV", "start_date": "2026-03-01", "zev_type": "vzev",
            "billing_interval": "monthly", "owner": owner,
            "metering_points": [{"meter_id": "METER-EXO", "meter_type": "consumption"}],
            **extra,
        }
        return self.client.post("/api/v1/zev/zevs/create-with-owner/", payload, format="json")

    def test_an_existing_account_becomes_the_owner_untouched(self):
        account = make_user("eo_account", UserRole.USER)
        before = (account.password, account.email, account.first_name, account.last_name, account.must_change_password)

        response = self.post({"account": account.pk, "phone": "044 000 00 00"})

        self.assertEqual(response.status_code, 201, response.content)
        owner = response.json()["owner"]
        self.assertEqual(owner["id"], account.pk)
        self.assertIsNone(owner["temporary_password"])
        self.assertTrue(owner["existing_account"])
        self.assertEqual(User.objects.filter(email__iexact=account.email).count(), 1)
        account.refresh_from_db()
        self.assertEqual(
            (account.password, account.email, account.first_name, account.last_name, account.must_change_password), before,
        )
        participant = Participant.objects.get(pk=response.json()["owner_participant_id"])
        self.assertEqual(participant.user_id, account.pk)
        self.assertEqual(participant.email, account.email)
        self.assertEqual(participant.phone, "044 000 00 00")
        self.assertTrue(account.independent_login_required)

    def test_the_owner_manages_the_zev_through_the_issuer_role_without_a_grant(self):
        account = make_user("eo_role", UserRole.USER)
        response = self.post({"account": account.pk}, start_date="2020-01-01")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertFalse(ZevAccessGrant.objects.filter(user=account).exists())
        zev_ids = [row["id"] for row in self.client_for(account).get("/api/v1/zev/zevs/").json()["results"]]
        self.assertIn(response.json()["zev"]["id"], zev_ids)

    def client_for(self, user):
        client = APIClient()
        authenticate(client, user)
        return client

    def test_a_zev_starting_later_gets_a_bridging_grant(self):
        account = make_user("eo_later", UserRole.USER)
        response = self.post({"account": account.pk}, start_date="2999-01-01")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(ZevAccessGrant.objects.filter(user=account, role=ZevAccessRole.MANAGER).count(), 1)

    def test_the_new_person_fields_are_ignored_for_an_existing_account(self):
        account = make_user("eo_ignored", UserRole.USER)
        taken = make_user("eo_taken", UserRole.USER)

        response = self.post({
            "account": account.pk, "first_name": "Other", "last_name": "Name",
            "email": taken.email, "username": taken.username,
        })

        self.assertEqual(response.status_code, 201, response.content)
        account.refresh_from_db()
        self.assertNotEqual(account.first_name, "Other")
        self.assertEqual(Participant.objects.get(pk=response.json()["owner_participant_id"]).email, account.email)

    def test_an_admin_account_is_refused(self):
        response = self.post({"account": make_user("eo_other_admin", UserRole.ADMIN).pk})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("account", response.json()["owner"])

    def test_a_deactivated_account_is_refused(self):
        account = make_user("eo_off", UserRole.USER)
        account.is_active = False
        account.save(update_fields=["is_active"])

        response = self.post({"account": account.pk})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("account", response.json()["owner"])

    def test_a_participant_password_cannot_establish_owner_access(self):
        account = make_user("eo_participant", UserRole.USER)
        account.password_from_participant_link = True
        account.save(update_fields=["password_from_participant_link"])

        response = self.post({"account": account.pk})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("account", response.json()["owner"])
        self.assertFalse(Zev.objects.filter(name="Existing Owner ZEV").exists())
        account.refresh_from_db()
        self.assertTrue(account.check_password("pass1234"))
        self.assertFalse(account.independent_login_required)

    def test_an_account_without_a_login_is_refused(self):
        account = make_user("eo_nologin", UserRole.USER)
        account.set_unusable_password()
        account.save(update_fields=["password"])

        response = self.post({"account": account.pk})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("account", response.json()["owner"])
        self.assertFalse(Zev.objects.filter(name="Existing Owner ZEV").exists())

    def test_an_unknown_account_is_refused(self):
        response = self.post({"account": 999999})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("account", response.json()["owner"])

    def test_a_new_person_still_needs_name_and_email(self):
        response = self.post({"first_name": "Only"})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(set(response.json()["owner"]), {"last_name", "email"})

    def test_a_new_account_reports_its_temporary_password(self):
        response = self.post({"first_name": "Neu", "last_name": "Person", "email": "neu.person@example.com"})

        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["owner"]["temporary_password"])
        self.assertFalse(response.json()["owner"]["existing_account"])

    def test_making_an_existing_account_owner_is_audited(self):
        from audit.models import AuditEvent

        account = make_user("eo_audit", UserRole.USER)
        response = self.post({"account": account.pk})

        self.assertEqual(response.status_code, 201, response.content)
        event = AuditEvent.objects.get(action_type="zev.owner_existing_account")
        self.assertEqual(event.target_id, response.json()["zev"]["id"])
        self.assertEqual(event.metadata_json["owner_user_id"], account.pk)
