"""The issuer and the representative manage their ZEV (#761, ADR 0028 amended).

Access follows the dated role: an account belonging to the party — its own
(``Party.user``) or through one of its participations — manages the ZEV while
the party holds the issuer or representative role. A landowner gets nothing.
Zugang lists those accounts read-only and can give access to a party.
"""

from datetime import date, timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from audit.models import AuditEvent
from testing.helpers import authenticate, create_managed_zev, make_user

from . import access
from .models import Participant, Party, PartyKind, PartyRole, ZevAccessGrant, ZevAccessRole
from .parties import NO_MANAGER_LEFT, assign_role, end_role
from .services import has_its_own_login

TODAY = date(2026, 6, 15)


def on_day(day):
    return mock.patch("zev.access._today", return_value=day)


class RoleAccessTests(TestCase):
    def setUp(self):
        patcher = on_day(TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.admin_made = create_managed_zev(name="Role Access", start_date=date(2026, 1, 1))
        self.zev = self.admin_made
        self.issuer_account = make_user("ra_issuer", UserRole.USER)
        self.issuer = Participant.objects.create(
            zev=self.zev, user=self.issuer_account, last_name="Issuer", valid_from=date(2026, 1, 1),
        )
        self.agency_account = make_user("ra_agency", UserRole.USER)
        self.agency = Party.objects.create(
            zev=self.zev, kind=PartyKind.ORGANISATION, organisation_name="Verwaltung", user=self.agency_account,
        )

    def manages(self, user, day=TODAY):
        access.invalidate(user)
        with on_day(day):
            return access.can_manage(user, self.zev)

    def test_the_issuers_participant_account_manages_while_the_role_lasts(self):
        self.assertFalse(self.manages(self.issuer_account))
        row = assign_role(self.zev, self.issuer.party, PartyRole.ISSUER, date(2026, 6, 1))
        self.assertTrue(self.manages(self.issuer_account))
        self.assertFalse(self.manages(self.issuer_account, date(2026, 5, 31)))
        end_role(row, date(2026, 6, 20))
        self.assertTrue(self.manages(self.issuer_account, date(2026, 6, 20)))
        self.assertFalse(self.manages(self.issuer_account, date(2026, 6, 21)))

    def test_a_representative_with_its_own_account_manages_and_a_landowner_does_not(self):
        assign_role(self.zev, self.agency, PartyRole.REPRESENTATIVE, date(2026, 1, 1))
        assign_role(self.zev, self.issuer.party, PartyRole.LANDOWNER, date(2026, 1, 1))
        self.assertTrue(self.manages(self.agency_account))
        self.assertFalse(self.manages(self.issuer_account))
        access.invalidate(self.issuer_account)
        self.assertFalse(access.can_view(self.issuer_account, self.zev))

    def test_memberships_name_the_role(self):
        assign_role(self.zev, self.issuer.party, PartyRole.ISSUER, date(2026, 1, 1))
        entry = next(item for item in access.memberships_for(self.issuer_account) if item["zev"] == str(self.zev.pk))
        self.assertEqual((entry["access"], entry["roles"]), ("manager", ["issuer"]))

    def test_holding_the_role_protects_the_login(self):
        self.assertFalse(has_its_own_login(self.issuer_account))
        assign_role(self.zev, self.issuer.party, PartyRole.ISSUER, date(2026, 1, 1))
        self.assertTrue(has_its_own_login(self.issuer_account))


class LastManagerTests(TestCase):
    """A role change never leaves a managed ZEV without a manager."""

    def setUp(self):
        self.zev = create_managed_zev(name="Last Manager", start_date=date(2026, 1, 1))
        self.account = make_user("lm_issuer", UserRole.USER)
        self.issuer = Participant.objects.create(zev=self.zev, user=self.account, last_name="Issuer", valid_from=date(2026, 1, 1))
        self.row = assign_role(self.zev, self.issuer.party, PartyRole.ISSUER, date(2026, 1, 1))
        self.nobody = Party.objects.create(zev=self.zev, last_name="Without Login")

    def test_ending_the_only_managing_role_is_refused(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError) as ctx:
            end_role(self.row, timezone.localdate() - timedelta(days=1))
        self.assertEqual(ctx.exception.message_dict, {"party": [NO_MANAGER_LEFT]})
        self.row.refresh_from_db()
        self.assertIsNone(self.row.valid_to)

    def test_handing_the_role_to_a_party_without_a_login_is_refused(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            assign_role(self.zev, self.nobody, PartyRole.ISSUER, timezone.localdate())
        self.assertEqual(self.zev.party_roles.get(role="issuer").party, self.issuer.party)

    def test_with_a_manager_grant_the_role_can_go(self):
        ZevAccessGrant.objects.create(zev=self.zev, user=make_user("lm_grant", UserRole.USER), role=ZevAccessRole.MANAGER)
        assign_role(self.zev, self.nobody, PartyRole.ISSUER, timezone.localdate())
        self.assertEqual(self.zev.party_roles.filter(role="issuer", valid_to=None).get().party, self.nobody)

    def test_a_manager_grant_can_go_when_the_issuer_manages(self):
        grant = ZevAccessGrant.objects.create(zev=self.zev, user=make_user("lm_other", UserRole.USER), role=ZevAccessRole.MANAGER)
        self.assertFalse(access.is_last_manager(grant))

    def test_the_api_reports_the_reason(self):
        client = APIClient()
        authenticate(client, make_user("lm_admin", UserRole.ADMIN))
        response = client.post(
            f"/api/v1/zev/party-roles/{self.row.pk}/end/", {"last_day": (timezone.localdate() - timedelta(days=1)).isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"party": [NO_MANAGER_LEFT]})


class ZugangTests(TestCase):
    def setUp(self):
        self.manager = make_user("zg_manager", UserRole.USER)
        self.zev = create_managed_zev(name="Zugang", owner=self.manager, start_date=date(2026, 1, 1))
        self.client = APIClient()
        authenticate(self.client, self.manager)
        self.url = f"/api/v1/zev/zevs/{self.zev.pk}/access/"

    def test_the_list_shows_who_manages_through_a_role(self):
        account = make_user("zg_issuer", UserRole.USER)
        issuer = Participant.objects.create(zev=self.zev, user=account, last_name="Issuer", valid_from=date(2026, 1, 1))
        assign_role(self.zev, issuer.party, PartyRole.ISSUER, date(2026, 1, 1))
        rows = self.client.get(self.url).json()
        self.assertEqual([row["source"] for row in rows], ["grant", "role"])
        role_row = rows[1]
        self.assertEqual((role_row["user"]["email"], role_row["role"]), (account.email, "manager"))
        self.assertEqual(role_row["party_role"]["role"], "issuer")

    def test_access_for_a_party_with_a_login_goes_to_that_login(self):
        account = make_user("zg_tenant", UserRole.USER)
        tenant = Participant.objects.create(zev=self.zev, user=account, last_name="Tenant", valid_from=date(2026, 1, 1))
        response = self.client.post(self.url, {"party": str(tenant.party_id), "role": "viewer"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(ZevAccessGrant.objects.filter(zev=self.zev, user=account, role="viewer").exists())

    def test_a_party_without_a_login_is_invited_and_linked(self):
        agency = Party.objects.create(
            zev=self.zev, kind=PartyKind.ORGANISATION, organisation_name="Verwaltung Nord", email="nord@example.com",
        )
        response = self.client.post(self.url, {"party": str(agency.pk), "role": "manager"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        account = User.objects.get(email="nord@example.com")
        self.assertFalse(account.is_active)
        agency.refresh_from_db()
        self.assertEqual(agency.user, account)
        self.assertEqual(mail.outbox[-1].to, ["nord@example.com"])
        event = AuditEvent.objects.filter(action_type="zev_access.invite").latest("created_at")
        self.assertEqual(event.metadata_json["party"], str(agency.pk))

    def test_a_party_without_an_email_cannot_be_invited(self):
        nobody = Party.objects.create(zev=self.zev, last_name="Nobody")
        response = self.client.post(self.url, {"party": str(nobody.pk), "role": "viewer"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("party", response.json())

    def test_email_or_party_but_not_both(self):
        party = Party.objects.create(zev=self.zev, last_name="Both", email="both@example.com")
        response = self.client.post(
            self.url, {"party": str(party.pk), "email": "both@example.com", "role": "viewer"}, format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_assigning_the_issuer_records_who_gets_access(self):
        account = make_user("zg_new_issuer", UserRole.USER)
        agency = Party.objects.create(zev=self.zev, kind=PartyKind.ORGANISATION, organisation_name="Agentur", user=account)
        response = self.client.post("/api/v1/zev/party-roles/", {
            "zev": str(self.zev.pk), "party": str(agency.pk), "role": "issuer", "valid_from": "2026-01-01",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        event = AuditEvent.objects.filter(action_type="party_role.assign").latest("created_at")
        self.assertEqual(event.metadata_json["manager_accounts"], [account.email])
        parties = self.client.get(f"/api/v1/zev/parties/?zev_id={self.zev.pk}").json()
        parties = parties.get("results", parties) if isinstance(parties, dict) else parties
        self.assertEqual(next(item for item in parties if item["id"] == str(agency.pk))["accounts"][0]["email"], account.email)
