"""Tests for the participant-onboarding-link flow.

Covers what zev/tests.py's participant CRUD tests do not: the token service
itself, the unauthenticated consume endpoint, and revocation. See
docs/specs and issue #712 for the design this implements.
"""
from datetime import date

from django.core import mail
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent, AuditEventSource
from testing.helpers import authenticate as auth, make_user

from . import onboarding
from .models import Participant, ParticipantOnboardingToken, Zev
from .services import get_participant_onboarding_link, send_participant_onboarding_link


class OnboardingTokenServiceTests(TestCase):
    def setUp(self):
        owner = make_user("owner_onboarding_svc", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(
            name="Onboarding ZEV", owner=owner, zev_type="vzev", invoice_prefix="O",
        )
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Ada", last_name="Onboardee",
            email="ada@example.com", valid_from=date(2026, 1, 1),
        )

    def test_get_or_create_returns_the_same_token_on_repeat_calls(self):
        first = onboarding.get_or_create_for_participant(self.participant)
        second = onboarding.get_or_create_for_participant(self.participant)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ParticipantOnboardingToken.objects.count(), 1)

    def test_resolve_rejects_wrong_secret(self):
        token = onboarding.get_or_create_for_participant(self.participant)

        self.assertIsNone(onboarding.resolve(token.prefix, "wrong-secret"))
        self.assertIsNotNone(onboarding.resolve(token.prefix, token.secret))

    def test_resolve_rejects_a_revoked_token(self):
        token = onboarding.get_or_create_for_participant(self.participant)
        onboarding.revoke(token)

        self.assertIsNone(onboarding.resolve(token.prefix, token.secret))

    def test_revoked_token_is_not_reused_by_get_or_create(self):
        first = onboarding.get_or_create_for_participant(self.participant)
        onboarding.revoke(first)

        second = onboarding.get_or_create_for_participant(self.participant)

        self.assertNotEqual(first.pk, second.pk)
        self.assertTrue(second.is_active)

    def test_public_url_carries_prefix_and_secret(self):
        token = onboarding.get_or_create_for_participant(self.participant)

        url = onboarding.public_url(token)

        self.assertIn(f"/join/{token.prefix}", url)
        self.assertIn(token.secret, url)


class SendOnboardingLinkServiceTests(TestCase):
    def setUp(self):
        owner = make_user("owner_onboarding_send", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(
            name="Send ZEV", owner=owner, zev_type="vzev", invoice_prefix="S",
        )
        self.owner = owner

    def test_raises_without_an_email_on_file(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="No", last_name="Email",
            valid_from=date(2026, 1, 1),
        )

        with self.assertRaises(ValueError):
            send_participant_onboarding_link(participant, self.owner)

    def test_sends_a_working_link_and_records_no_password(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="Bea", last_name="Recipient",
            email="bea@example.com", valid_from=date(2026, 1, 1),
        )

        url = send_participant_onboarding_link(participant, self.owner)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["bea@example.com"])
        self.assertIn(url, mail.outbox[0].body)
        participant.refresh_from_db()
        self.assertFalse(participant.user.has_usable_password())

    def test_resending_reuses_the_same_link(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="Cai", last_name="Repeat",
            email="cai@example.com", valid_from=date(2026, 1, 1),
        )

        first_url = send_participant_onboarding_link(participant, self.owner)
        second_url = send_participant_onboarding_link(participant, self.owner)

        self.assertEqual(first_url, second_url)
        self.assertEqual(len(mail.outbox), 2)

    def test_get_link_never_sends_mail(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="Dee", last_name="Silent",
            valid_from=date(2026, 1, 1),
        )

        url = get_participant_onboarding_link(participant)

        self.assertTrue(url)
        self.assertEqual(len(mail.outbox), 0)


class OnboardingConsumeViewTests(TestCase):
    CONSUME_URL = "/api/v1/public/onboarding/consume/"

    def setUp(self):
        owner = make_user("owner_onboarding_consume", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(
            name="Consume ZEV", owner=owner, zev_type="vzev", invoice_prefix="C",
        )
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Eve", last_name="Consumer",
            email="eve@example.com", valid_from=date(2026, 1, 1),
        )
        self.token = onboarding.get_or_create_for_participant(self.participant)
        self.client = APIClient()

    def test_valid_link_signs_in_and_creates_the_account_lazily(self):
        self.assertIsNone(self.participant.user_id)

        resp = self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["zev_name"], self.zev.name)
        self.participant.refresh_from_db()
        self.assertIsNotNone(self.participant.user)
        self.assertFalse(self.participant.user.has_usable_password())
        self.assertIn("openzev_access", resp.cookies)

    def test_link_is_reusable_unlike_a_magic_link(self):
        first = self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json",
        )
        second = self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

    def test_wrong_secret_is_a_404(self):
        resp = self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": "not-it"}, format="json",
        )

        self.assertEqual(resp.status_code, 404)

    def test_revoked_link_is_a_404(self):
        onboarding.revoke(self.token)

        resp = self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json",
        )

        self.assertEqual(resp.status_code, 404)

    def test_records_an_audit_event_with_the_onboarding_link_source(self):
        self.client.post(
            self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json",
        )

        event = AuditEvent.objects.filter(action_type="participant_onboarding.consumed").latest("created_at")
        self.assertEqual(event.source, AuditEventSource.ONBOARDING_LINK)


class RevokeAndUnlinkTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin_revoke", UserRole.ADMIN)
        owner = make_user("owner_revoke", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(
            name="Revoke ZEV", owner=owner, zev_type="vzev", invoice_prefix="R",
        )
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Fay", last_name="Revoked",
            email="fay@example.com", valid_from=date(2026, 1, 1),
        )
        self.client = APIClient()
        auth(self.client, self.admin)

    def test_revoke_action_kills_the_link_but_keeps_the_account(self):
        get_participant_onboarding_link(self.participant)
        self.participant.refresh_from_db()
        self.assertIsNotNone(self.participant.user_id)

        resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/revoke-onboarding-link/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["onboarding_status"], "revoked")
        self.participant.refresh_from_db()
        self.assertIsNotNone(self.participant.user_id)

    def test_unlink_account_also_revokes_the_active_link(self):
        self.client.post(f"/api/v1/zev/participants/{self.participant.id}/onboarding-link/")
        self.participant.refresh_from_db()
        self.assertTrue(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).exists()
        )

        resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/unlink-account/")

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).exists()
        )

    def test_onboarding_status_transitions(self):
        list_url = f"/api/v1/zev/participants/{self.participant.id}/"

        self.assertEqual(self.client.get(list_url).data["onboarding_status"], "not_sent")

        link_resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/onboarding-link/")
        self.assertEqual(link_resp.data["participant"]["onboarding_status"], "sent")

        token = self.participant.onboarding_tokens.get()
        onboarding.note_use(token)
        self.assertEqual(self.client.get(list_url).data["onboarding_status"], "active")

        revoke_resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/revoke-onboarding-link/")
        self.assertEqual(revoke_resp.data["onboarding_status"], "revoked")
