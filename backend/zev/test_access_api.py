"""Giving and taking away access to a ZEV, and the account changes around it (#761, spec §7–§8)."""

from datetime import date, timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import EmailVerificationToken, User, UserRole
from audit.models import AuditEvent, AuditEventStatus
from invoices.models import EmailTemplate
from testing.helpers import authenticate, make_user, create_managed_zev
from zev import access
from zev.models import Participant, Zev, ZevAccessGrant, ZevAccessRole
from zev.services import ensure_participant_account

MANAGER, VIEWER = ZevAccessRole.MANAGER, ZevAccessRole.VIEWER


class AccessApiTestCase(TestCase):
    def setUp(self):
        self.owner = make_user("api_owner", UserRole.USER)
        self.zev = create_managed_zev(name="Grant ZEV", owner=self.owner, zev_type="vzev", invoice_prefix="G",
                                      invoice_language="de")
        self.viewer = make_user("api_viewer", UserRole.USER)
        # Started earlier, so ending it leaves a row (a grant that starts today
        # is deleted when revoked — it never took effect).
        self.viewer_grant = ZevAccessGrant.objects.create(
            zev=self.zev, user=self.viewer, role=VIEWER, valid_from=date(2026, 1, 1),
        )
        self.stranger = make_user("api_stranger", UserRole.USER)
        self.admin = make_user("api_admin", UserRole.ADMIN)
        self.owner_grant = ZevAccessGrant.objects.get(zev=self.zev, user=self.owner)

    def client_for(self, user):
        client = APIClient()
        authenticate(client, user)
        return client

    def url(self, pk=None, suffix=""):
        base = f"/api/v1/zev/zevs/{self.zev.pk}/access/"
        return f"{base}{pk}/{suffix}" if pk else base


class ZevAccessGrantApiTests(AccessApiTestCase):
    def test_managers_and_viewers_list_the_grants_strangers_get_404(self):
        for user in (self.owner, self.viewer, self.admin):
            with self.subTest(user=user.username):
                response = self.client_for(user).get(self.url())
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {row["user"]["email"] for row in response.json()},
                    {self.owner.email, self.viewer.email},
                )
        self.assertEqual(self.client_for(self.stranger).get(self.url()).status_code, 404)

    def test_ended_grants_are_listed_only_on_request(self):
        access.revoke(self.viewer_grant, today=timezone.localdate())
        client = self.client_for(self.owner)
        self.assertEqual(len(client.get(self.url()).json()), 1)
        self.assertEqual(len(client.get(self.url(), {"include_ended": "true"}).json()), 2)

    def test_a_manager_gives_an_existing_account_access(self):
        response = self.client_for(self.owner).post(
            self.url(), {"email": self.stranger.email.upper(), "role": VIEWER}, format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["role"], body["user"]["email"], body["email_sent"]), (VIEWER, self.stranger.email, True))
        self.assertEqual(body["granted_by"]["id"], self.owner.pk)
        self.assertTrue(access.can_view(self.stranger, self.zev))
        self.assertEqual(mail.outbox[-1].to, [self.stranger.email])
        self.assertIn("Grant ZEV", mail.outbox[-1].subject)
        self.assertIn("Einsicht", mail.outbox[-1].body)  # the ZEV's language (de)
        event = AuditEvent.objects.get(action_type="zev_access.grant")
        self.assertEqual((event.zev_id, event.status), (self.zev.pk, AuditEventStatus.SUCCESS))

    def test_the_new_grantee_sees_the_zev_at_once(self):
        self.client_for(self.owner).post(self.url(), {"email": self.stranger.email, "role": VIEWER}, format="json")
        zevs = self.client_for(self.stranger).get("/api/v1/zev/zevs/").json()
        self.assertIn(str(self.zev.pk), {row["id"] for row in zevs["results"]})

    def test_viewers_and_strangers_cannot_give_access(self):
        body = {"email": "new@example.com", "role": VIEWER}
        self.assertEqual(self.client_for(self.viewer).post(self.url(), body, format="json").status_code, 403)
        self.assertEqual(self.client_for(self.stranger).post(self.url(), body, format="json").status_code, 404)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())
        self.assertTrue(AuditEvent.objects.filter(action_type="zev_access.grant", status=AuditEventStatus.DENIED).exists())

    def test_refusals(self):
        client = self.client_for(self.owner)
        cases = {
            "an admin": {"email": self.admin.email, "role": VIEWER},
            "an account that already has access": {"email": self.viewer.email, "role": MANAGER},
            "an end date in the past": {"email": "x@example.com", "role": VIEWER, "valid_to": "2020-01-01"},
            "an unknown role": {"email": "x@example.com", "role": "owner"},
        }
        for label, body in cases.items():
            with self.subTest(label):
                self.assertEqual(client.post(self.url(), body, format="json").status_code, 400)

    def test_a_disabled_zev_refuses_changes_except_by_an_admin(self):
        Zev.objects.filter(pk=self.zev.pk).update(disabled_at=timezone.now())
        body = {"email": self.stranger.email, "role": VIEWER}
        self.assertEqual(self.client_for(self.owner).post(self.url(), body, format="json").status_code, 400)
        self.assertEqual(self.client_for(self.admin).post(self.url(), body, format="json").status_code, 201)

    def test_changing_a_role_keeps_the_history(self):
        response = self.client_for(self.owner).patch(self.url(self.viewer_grant.pk), {"role": MANAGER}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["role"], MANAGER)
        self.assertEqual(ZevAccessGrant.objects.filter(zev=self.zev, user=self.viewer).count(), 2)
        self.assertTrue(access.can_manage(self.viewer, self.zev))

    def test_the_last_manager_cannot_be_downgraded_ended_or_revoked(self):
        client = self.client_for(self.owner)
        self.assertEqual(client.patch(self.url(self.owner_grant.pk), {"role": VIEWER}, format="json").status_code, 400)
        end = (timezone.localdate() + timedelta(days=30)).isoformat()
        self.assertEqual(client.patch(self.url(self.owner_grant.pk), {"valid_to": end}, format="json").status_code, 400)
        self.assertEqual(client.delete(self.url(self.owner_grant.pk)).status_code, 400)
        self.assertTrue(access.can_manage(self.owner, self.zev))

    def test_with_a_second_manager_the_first_may_leave(self):
        ZevAccessGrant.objects.create(zev=self.zev, user=self.stranger, role=MANAGER)
        self.assertEqual(self.client_for(self.owner).delete(self.url(self.owner_grant.pk)).status_code, 204)
        self.assertFalse(access.can_view(self.owner, self.zev))
        self.assertTrue(AuditEvent.objects.filter(action_type="zev_access.revoke").exists())

    def test_revoking_a_viewer_ends_its_access(self):
        self.assertEqual(self.client_for(self.owner).delete(self.url(self.viewer_grant.pk)).status_code, 204)
        self.assertEqual(self.client_for(self.viewer).get("/api/v1/zev/participants/").status_code, 403)

    def test_a_planned_end_date(self):
        end = timezone.localdate() + timedelta(days=10)
        response = self.client_for(self.owner).patch(
            self.url(self.viewer_grant.pk), {"valid_to": end.isoformat()}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.viewer_grant.refresh_from_db()
        self.assertEqual(self.viewer_grant.valid_to, end)
        self.assertTrue(access.can_view(self.viewer, self.zev))


class ZevAccessInvitationTests(AccessApiTestCase):
    def invite(self, email="new.person@example.com", role=VIEWER, as_user=None):
        return self.client_for(as_user or self.owner).post(self.url(), {"email": email, "role": role}, format="json")

    def test_an_unknown_email_gets_an_inactive_account_a_grant_and_an_invitation(self):
        response = self.invite()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["user"]["pending_invitation"])
        account = User.objects.get(email="new.person@example.com")
        self.assertFalse(account.is_active)
        self.assertFalse(account.has_usable_password())
        self.assertFalse(account.may_create_zev)
        token = EmailVerificationToken.objects.get(user=account)
        self.assertEqual(token.purpose, EmailVerificationToken.Purpose.INVITATION)
        self.assertIn(f"/verify-email?token={token.token}", mail.outbox[-1].body)
        self.assertIn("7", mail.outbox[-1].body)
        self.assertTrue(AuditEvent.objects.filter(action_type="zev_access.invite").exists())

    def test_accepting_the_invitation_signs_in_and_reaches_the_zev(self):
        self.invite(role=MANAGER)
        account = User.objects.get(email="new.person@example.com")
        token = EmailVerificationToken.objects.get(user=account)
        response = APIClient().post("/api/v1/auth/verify-email/", {"token": token.token}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["purpose"], "invitation")
        account.refresh_from_db()
        self.assertTrue(account.is_active)
        self.assertTrue(access.can_manage(account, self.zev))
        # A signup token still says so.
        signup = EmailVerificationToken.objects.create(user=make_user("api_signup", UserRole.USER), token="s" * 40)
        self.assertEqual(
            APIClient().post("/api/v1/auth/verify-email/", {"token": signup.token}, format="json").json()["purpose"],
            "signup",
        )

    def test_the_invitation_link_lasts_seven_days(self):
        self.invite()
        token = EmailVerificationToken.objects.get(user__email="new.person@example.com")
        for days, valid in ((6, True), (8, False)):
            with self.subTest(days=days):
                EmailVerificationToken.objects.filter(pk=token.pk).update(created_at=timezone.now() - timedelta(days=days))
                token.refresh_from_db()
                self.assertIs(token.is_valid(), valid)

    def test_resending_replaces_the_link(self):
        grant = ZevAccessGrant.objects.get(pk=self.invite().json()["id"])
        old = EmailVerificationToken.objects.get(user=grant.user)
        response = self.client_for(self.owner).post(self.url(grant.pk, "resend-invitation/"))
        self.assertEqual(response.status_code, 202)
        old.refresh_from_db()
        self.assertIsNotNone(old.consumed_at)
        self.assertEqual(EmailVerificationToken.objects.filter(user=grant.user, consumed_at__isnull=True).count(), 1)
        grant.user.is_active = True
        grant.user.save(update_fields=["is_active"])
        self.assertEqual(self.client_for(self.owner).post(self.url(grant.pk, "resend-invitation/")).status_code, 400)

    def test_revoking_an_unaccepted_invitation_removes_the_account(self):
        grant_id = self.invite().json()["id"]
        self.assertEqual(self.client_for(self.owner).delete(self.url(grant_id)).status_code, 204)
        self.assertFalse(User.objects.filter(email="new.person@example.com").exists())

    def test_revoking_an_accepted_invitation_keeps_the_account(self):
        grant = ZevAccessGrant.objects.get(pk=self.invite().json()["id"])
        grant.user.is_active = True
        grant.user.save(update_fields=["is_active"])
        EmailVerificationToken.objects.filter(user=grant.user).update(consumed_at=timezone.now())
        self.client_for(self.owner).delete(self.url(grant.pk))
        self.assertTrue(User.objects.filter(pk=grant.user.pk).exists())

    def test_a_failed_send_keeps_the_grant_and_says_so(self):
        with mock.patch("zev.views_access.EmailMessage.send", side_effect=OSError("smtp down")):
            response = self.invite()
        self.assertEqual(response.status_code, 201)
        self.assertIs(response.json()["email_sent"], False)
        self.assertTrue(ZevAccessGrant.objects.filter(user__email="new.person@example.com").exists())
        self.assertTrue(AuditEvent.objects.filter(action_type="zev_access.invite", status=AuditEventStatus.FAILED).exists())

    def test_a_custom_template_is_used_and_a_broken_one_falls_back(self):
        EmailTemplate.objects.create(template_key="zev_access_invitation", subject="Join {zev_name}", body="Go: {link_url}")
        self.invite("custom@example.com")
        self.assertEqual(mail.outbox[-1].subject, "Join Grant ZEV")
        EmailTemplate.objects.filter(template_key="zev_access_invitation").update(body="Broken {nope}")
        self.invite("broken@example.com")
        self.assertIn("/verify-email?token=", mail.outbox[-1].body)


class AccountsAroundGrantsTests(AccessApiTestCase):
    def test_me_lists_every_zev_the_account_relates_to(self):
        other = create_managed_zev(name="Other", owner=self.stranger, zev_type="vzev", invoice_prefix="O")
        Participant.objects.create(zev=other, user=self.viewer, first_name="V", last_name="Iewer",
                                   valid_from=date(2026, 1, 1))
        body = self.client_for(self.viewer).get("/api/v1/auth/me/").json()
        by_name = {m["zev_name"]: m for m in body["memberships"]}
        self.assertEqual(by_name["Grant ZEV"]["access"], VIEWER)
        self.assertEqual(by_name["Grant ZEV"]["participants"], [])
        self.assertIsNone(by_name["Other"]["access"])
        self.assertEqual(len(by_name["Other"]["participants"]), 1)
        self.assertIs(body["may_create_zev"], False)

    def test_self_setup_needs_may_create_zev(self):
        self.stranger.may_create_zev = False
        self.stranger.save(update_fields=["may_create_zev"])
        body = {"name": "Mine", "start_date": "2026-01-01"}
        self.assertEqual(self.client_for(self.stranger).post("/api/v1/zev/zevs/self-setup/", body, format="json").status_code, 403)

    def test_self_registration_may_create_a_zev(self):
        from accounts.models import FeatureFlag

        FeatureFlag.objects.update_or_create(name=FeatureFlag.ZEV_SELF_REGISTRATION_ENABLED, defaults={"enabled": True})
        APIClient().post("/api/v1/auth/register/", {"email": "selfreg@example.com"}, format="json")
        self.assertIs(User.objects.get(email="selfreg@example.com").may_create_zev, True)

    def test_a_grant_holders_login_survives_being_a_participant(self):
        participant = Participant.objects.create(
            zev=self.zev, user=self.viewer, first_name="View", last_name="Er", email=self.viewer.email,
            valid_from=date(2026, 1, 1),
        )
        ensure_participant_account(participant)
        self.viewer.refresh_from_db()
        self.assertTrue(self.viewer.has_usable_password())

    def test_a_manager_cannot_edit_a_participant_row_of_an_account_with_its_own_login(self):
        # Saving the row copies its email onto the account: that would let one
        # manager rewrite another's login email.
        participant = Participant.objects.create(
            zev=self.zev, user=self.viewer, first_name="View", last_name="Er", email=self.viewer.email,
            valid_from=date(2026, 1, 1),
        )
        response = self.client_for(self.owner).patch(
            f"/api/v1/zev/participants/{participant.pk}/", {"email": "attacker@example.com"}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.viewer.refresh_from_db()
        self.assertNotEqual(self.viewer.email, "attacker@example.com")
