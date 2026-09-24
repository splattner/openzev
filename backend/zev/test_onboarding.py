"""Tests for the participant-onboarding-link flow.

Covers what zev/tests.py's participant CRUD tests do not: the token service
itself, the unauthenticated consume endpoint, and revocation. See
docs/specs and issue #712 for the design this implements.
"""
from datetime import date, timedelta

from django.core import mail
from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserRole
from audit.models import AuditEvent, AuditEventSource
from testing.helpers import authenticate as auth, make_user

from . import onboarding
from invoices.models import EmailTemplate

from .emails import format_expiry_date
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

    def test_resolve_rejects_a_disabled_zev(self):
        token = onboarding.get_or_create_for_participant(self.participant)
        self.zev.disabled_at = timezone.now()
        self.zev.save()

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

        url, token = send_participant_onboarding_link(participant, self.owner)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["bea@example.com"])
        self.assertIn(url, mail.outbox[0].body)
        self.assertIn(format_expiry_date(token.expires_at), mail.outbox[0].body)
        participant.refresh_from_db()
        self.assertFalse(participant.user.has_usable_password())

    def test_custom_template_uses_every_send_time_field(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="All", last_name="Fields",
            email="all.fields@example.com", valid_from=date(2026, 1, 1),
        )
        EmailTemplate.objects.create(
            template_key="participant_onboarding",
            subject="{participant_name}|{inviter_name}|{zev_name}|{link_url}|{expiry_date}",
            body="{participant_name}|{inviter_name}|{zev_name}|{link_url}|{expiry_date}",
        )

        url, token = send_participant_onboarding_link(participant, self.owner)

        expected = "|".join(
            [
                participant.full_name,
                self.owner.username,
                self.zev.name,
                url,
                format_expiry_date(token.expires_at),
            ]
        )
        self.assertEqual(mail.outbox[-1].subject, expected)
        self.assertEqual(mail.outbox[-1].body, expected)

    def test_resending_reuses_the_same_link(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="Cai", last_name="Repeat",
            email="cai@example.com", valid_from=date(2026, 1, 1),
        )

        first_url, _first = send_participant_onboarding_link(participant, self.owner)
        second_url, second_token = send_participant_onboarding_link(participant, self.owner)

        self.assertEqual(first_url, second_url)
        self.assertEqual(len(mail.outbox), 2)

    def test_resend_states_the_actual_expiry_not_30_days(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="Dag", last_name="Aged",
            email="dag@example.com", valid_from=date(2026, 1, 1),
        )
        first_url, first_token = send_participant_onboarding_link(participant, self.owner)
        ParticipantOnboardingToken.objects.filter(pk=first_token.pk).update(
            expires_at=timezone.now() + timedelta(days=1)
        )
        mail.outbox = []

        second_url, second_token = send_participant_onboarding_link(participant, self.owner)

        self.assertEqual(first_url, second_url)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(format_expiry_date(second_token.expires_at), mail.outbox[0].body)

    def test_get_link_never_sends_mail(self):
        participant = Participant.objects.create(
            zev=self.zev, first_name="Dee", last_name="Silent",
            valid_from=date(2026, 1, 1),
        )

        url, _token = get_participant_onboarding_link(participant)

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

    def test_disabled_zev_link_is_a_404(self):
        self.zev.disabled_at = timezone.now()
        self.zev.save()

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

    def test_stamps_last_login(self):
        self.client.post(self.CONSUME_URL, {"prefix": self.token.prefix, "s": self.token.secret}, format="json")

        self.participant.refresh_from_db()
        self.assertIsNotNone(self.participant.user.last_login)


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


class OnboardingExpiryTests(TestCase):
    def setUp(self):
        owner = make_user("owner_onboarding_expiry", UserRole.ZEV_OWNER)
        self.zev = Zev.objects.create(
            name="Expiry ZEV", owner=owner, zev_type="vzev", invoice_prefix="E",
        )
        self.participant = Participant.objects.create(
            zev=self.zev, first_name="Exp", last_name="Ired",
            email="exp@example.com", valid_from=date(2026, 1, 1),
        )
        self.client = APIClient()

    def _expire(self, token):
        ParticipantOnboardingToken.objects.filter(pk=token.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        token.refresh_from_db()
        return token

    def _mint_link(self, username):
        admin = make_user(username, UserRole.ADMIN)
        auth(self.client, admin)
        resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/onboarding-link/")
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_new_token_carries_a_30_day_expiry(self):
        token = onboarding.get_or_create_for_participant(self.participant)

        delta = token.expires_at - timezone.now()
        self.assertTrue(timedelta(days=29) < delta <= timedelta(days=30))
        self.assertTrue(token.is_active)

    def test_creating_a_token_without_expiry_fails(self):
        with self.assertRaises(IntegrityError):
            ParticipantOnboardingToken.objects.create(
                participant=self.participant, prefix="no-expiry", secret="s" * 32,
            )

    def test_resolve_rejects_an_expired_token(self):
        token = onboarding.get_or_create_for_participant(self.participant)
        self._expire(token)

        self.assertIsNone(onboarding.resolve(token.prefix, token.secret))
        self.assertFalse(
            ParticipantOnboardingToken.objects.get(pk=token.pk).is_active
        )

    def test_expired_link_is_a_404(self):
        token = onboarding.get_or_create_for_participant(self.participant)
        self._expire(token)

        resp = self.client.post(
            "/api/v1/public/onboarding/consume/",
            {"prefix": token.prefix, "s": token.secret}, format="json",
        )

        self.assertEqual(resp.status_code, 404)

    def test_expired_active_token_is_revoked_and_replaced(self):
        first = onboarding.get_or_create_for_participant(self.participant)
        self._expire(first)

        second = onboarding.get_or_create_for_participant(self.participant)

        self.assertNotEqual(first.pk, second.pk)
        first.refresh_from_db()
        self.assertIsNotNone(first.revoked_at)
        self.assertTrue(second.is_active)
        self.assertNotEqual(first.prefix, second.prefix)

    def test_expired_link_reads_as_expired_with_its_date(self):
        self._mint_link("admin_expiry_status")
        token = self.participant.onboarding_tokens.get()
        self._expire(token)

        data = self.client.get(f"/api/v1/zev/participants/{self.participant.id}/").data

        self.assertEqual(data["onboarding_status"], "expired")
        self.assertEqual(data["onboarding_link_expires_at"], token.expires_at)

    def test_copy_rotates_an_expired_link(self):
        self._mint_link("admin_expiry_copy")
        first_token = self.participant.onboarding_tokens.order_by("-created_at").first()
        first_prefix = first_token.prefix
        self._expire(first_token)

        second_resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/onboarding-link/")

        self.assertEqual(second_resp.status_code, 200)
        self.assertIsNotNone(second_resp.data["onboarding_expires_at"])
        live = self.participant.onboarding_tokens.filter(revoked_at__isnull=True).get()
        self.assertTrue(live.is_active)
        self.assertNotEqual(live.prefix, first_prefix)

    def test_copy_response_url_and_expiry_belong_to_the_same_token(self):
        resp = self._mint_link("admin_expiry_match_copy")

        live = self.participant.onboarding_tokens.filter(revoked_at__isnull=True).get()
        self.assertIn(f"/join/{live.prefix}", resp.data["onboarding_url"])
        self.assertEqual(resp.data["onboarding_expires_at"], resp.data["participant"]["onboarding_link_expires_at"])
        self.assertEqual(resp.data["onboarding_expires_at"], live.expires_at)

    def test_send_response_url_and_expiry_belong_to_the_same_token(self):
        admin = make_user("admin_expiry_match_send", UserRole.ADMIN)
        auth(self.client, admin)
        resp = self.client.post(f"/api/v1/zev/participants/{self.participant.id}/send-onboarding-link/")

        self.assertEqual(resp.status_code, 200)
        live = self.participant.onboarding_tokens.filter(revoked_at__isnull=True).get()
        self.assertIn(f"/join/{live.prefix}", resp.data["onboarding_url"])
        self.assertEqual(resp.data["onboarding_expires_at"], live.expires_at)

    def test_setting_a_password_revokes_the_link(self):
        from .services import ensure_participant_account

        user = ensure_participant_account(self.participant)
        onboarding.get_or_create_for_participant(self.participant)
        self.assertTrue(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).exists()
        )
        auth(self.client, user)

        resp = self.client.post(
            "/api/v1/auth/me/set-initial-password/",
            {"new_password": "A-very-long-initial-1!"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).exists()
        )
        event = AuditEvent.objects.get(action_type="password.set_initial")
        self.assertEqual(event.metadata_json["onboarding_links_revoked"], 1)

    def test_changing_a_password_revokes_the_link(self):
        user = make_user("pw_change_participant", UserRole.PARTICIPANT)
        participant = Participant.objects.create(
            zev=self.zev, user=user, first_name="Pam", last_name="Word",
            email="pam@example.com", valid_from=date(2026, 1, 1),
        )
        onboarding.get_or_create_for_participant(participant)
        auth(self.client, user)

        resp = self.client.post(
            "/api/v1/auth/me/change-password/",
            {"old_password": "pass1234", "new_password": "A-very-long-changed-2!"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(
            participant.onboarding_tokens.filter(revoked_at__isnull=True).exists()
        )

    def test_only_one_unrevoked_link_per_participant(self):
        from django.db import transaction

        onboarding.get_or_create_for_participant(self.participant)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ParticipantOnboardingToken.objects.create(
                    participant=self.participant, prefix="second-live",
                    secret="s" * 32,
                    expires_at=timezone.now() + timedelta(days=30),
                )


    def test_racing_mint_returns_the_winners_link(self):
        from contextlib import nullcontext
        from unittest import mock

        first = onboarding.get_or_create_for_participant(self.participant)
        self._expire(first)
        real_create = ParticipantOnboardingToken.objects.create

        def racy_create(**kwargs):
            # A concurrent copy/send mints and commits first, so our insert
            # hits the one-unrevoked-link constraint.
            real_create(
                participant=self.participant, prefix="racer-winner",
                secret="r" * 32,
                expires_at=timezone.now() + timedelta(days=30),
            )
            raise IntegrityError("one_unrevoked_onboarding_token_per_participant")

        # No savepoint: on a real second connection the winner's commit
        # survives our rollback; in this single test connection it must stay
        # visible for the fallback fetch.
        with (
            mock.patch.object(
                ParticipantOnboardingToken.objects, "create", racy_create
            ),
            mock.patch("zev.onboarding.transaction.atomic", nullcontext),
        ):
            result = onboarding.get_or_create_for_participant(self.participant)

        self.assertEqual(result.prefix, "racer-winner")
        self.assertTrue(result.is_active)
        self.assertEqual(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).count(),
            1,
        )

    def test_failed_mint_is_retried_not_stranded(self):
        from unittest import mock

        first = onboarding.get_or_create_for_participant(self.participant)
        self._expire(first)
        real_create = ParticipantOnboardingToken.objects.create
        calls = {"n": 0}

        def flaky_create(**kwargs):
            # First mint attempt fails with nobody else holding a live link.
            calls["n"] += 1
            if calls["n"] == 1:
                raise IntegrityError("one_unrevoked_onboarding_token_per_participant")
            return real_create(**kwargs)

        # Real savepoint (not mocked): the failed mint must roll the revoke back.
        with mock.patch.object(
            ParticipantOnboardingToken.objects, "create", flaky_create
        ):
            result = onboarding.get_or_create_for_participant(self.participant)

        self.assertEqual(calls["n"], 2)
        self.assertTrue(result.is_active)
        first.refresh_from_db()
        self.assertIsNotNone(first.revoked_at)
        self.assertEqual(
            self.participant.onboarding_tokens.filter(revoked_at__isnull=True).count(),
            1,
        )


class OnboardingConstraintUpgradeTests(TransactionTestCase):
    """Migration 0029 cleans up before constraining.

    Rows minted by the old race-prone implementation can hold several
    unrevoked links per participant; the migration revokes all but the
    newest before adding the partial unique constraint.
    """

    def test_upgrade_revokes_older_duplicates_then_constrains(self):
        from django.core.management import call_command

        call_command("migrate", "zev", "0028", verbosity=0, interactive=False)
        try:
            owner = make_user("owner_mig_0029", UserRole.ZEV_OWNER)
            zev = Zev.objects.create(
                name="Mig ZEV", owner=owner, zev_type="vzev", invoice_prefix="M",
            )
            participant = Participant.objects.create(
                zev=zev, first_name="Mig", last_name="Rate",
                email="mig@example.com", valid_from=date(2026, 1, 1),
            )
            old = ParticipantOnboardingToken.objects.create(
                participant=participant, prefix="mig-old", secret="o" * 32,
                expires_at=timezone.now() + timedelta(days=30),
            )
            ParticipantOnboardingToken.objects.filter(pk=old.pk).update(
                created_at=timezone.now() - timedelta(days=1)
            )
            new = ParticipantOnboardingToken.objects.create(
                participant=participant, prefix="mig-new", secret="n" * 32,
                expires_at=timezone.now() + timedelta(days=30),
            )

            call_command("migrate", "zev", verbosity=0, interactive=False)

            live = list(
                participant.onboarding_tokens.filter(revoked_at__isnull=True)
            )
            self.assertEqual([t.pk for t in live], [new.pk])
            old.refresh_from_db()
            self.assertIsNotNone(old.revoked_at)
        finally:
            call_command("migrate", "zev", verbosity=0, interactive=False)
