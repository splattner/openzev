"""Credential writes stay intentional; operator recovery establishes ownership."""

import io

from asgiref.sync import async_to_sync
from unittest.mock import patch

from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from testing.helpers import make_user

from .admin import IndependentPasswordChangeForm
from .jwt_utils import is_participant_link_session, make_jwt_for_user
from .models import MagicLinkToken, OAuthExchangeCode, OAuthProvider, SocialAccount, User
from .passwords import recover_password
from .session_revocation import is_session_current


class PasswordRecoveryTests(TestCase):
    def setUp(self):
        self.user = make_user("password_recovery")
        self.user.is_staff = True
        self.user.password_from_participant_link = True
        self.user.save(update_fields=["is_staff", "password_from_participant_link"])

    def test_operator_recovery_retires_old_participant_sign_in_links(self):
        from testing.factories import ParticipantFactory
        from zev import onboarding
        from accounts import magic_links

        participant = ParticipantFactory(user=self.user, email=self.user.email)
        token = onboarding.get_or_create_for_participant(participant)
        magic = magic_links.issue(self.user)
        recover_password(self.user, "OperatorReplacement42!")
        token.refresh_from_db()
        magic.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        self.assertIsNotNone(magic.consumed_at)
        response = APIClient().post("/api/v1/public/magic-link/consume/", {"token": magic.token})
        self.assertEqual(response.status_code, 400)

    def test_set_unusable_password_with_plain_save_persists_without_replay_on_later_saves(self):
        self.user.set_unusable_password()
        self.user.save()
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        recover_password(self.user, "RecoveredPassword42!")
        self.user.first_name = "Stale disabled instance"
        self.user.save()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("RecoveredPassword42!"))

    def test_participant_session_policy_has_bounded_query_cost(self):
        token = {"sv": self.user.session_version, "src": "participant_link"}
        with self.assertNumQueries(2):
            self.assertTrue(is_session_current(token, self.user))
        self.user.independent_login_required = True
        self.user.save(update_fields=["independent_login_required"])
        with self.assertNumQueries(0):
            self.assertFalse(is_session_current(token, self.user))

    def test_empty_profile_patch_is_a_noop(self):
        from testing.helpers import authenticate as auth

        client = APIClient()
        auth(client, self.user)
        response = client.patch("/api/v1/auth/me/", {"role": self.user.role}, format="json")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("pass1234"))
        self.assertTrue(self.user.password_from_participant_link)

    def test_deferred_admin_form_does_not_write_or_revoke(self):
        form = IndependentPasswordChangeForm(self.user, data={
            "password1": "DeferredPassword42!", "password2": "DeferredPassword42!", "usable_password": "true",
        })
        self.assertTrue(form.is_valid(), form.errors)
        staged = form.save(commit=False)
        self.assertTrue(staged.check_password("DeferredPassword42!"))
        stored = User.objects.get(pk=self.user.pk)
        self.assertTrue(stored.check_password("pass1234"))
        self.assertTrue(stored.password_from_participant_link)
        self.assertEqual(stored.session_version, 0)

    def test_recovery_discards_pending_oauth_exchange_codes(self):
        code = "pending-before-recovery"
        OAuthExchangeCode.objects.create(user=self.user, code=code)
        recover_password(self.user, "RecoveredPassword42!")
        response = APIClient().post("/api/v1/auth/oauth/token-exchange/", {"code": code}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("openzev_access", response.cookies)
        self.assertFalse(OAuthExchangeCode.objects.filter(code=code).exists())

    def test_stale_profile_save_cannot_restore_a_staff_password(self):
        stale = User.objects.get(pk=self.user.pk)
        provider = OAuthProvider.objects.create(name="recovery-provider")
        SocialAccount.objects.create(user=self.user, provider=provider, uid="owner")
        self.user.role = "admin"
        self.user.save(update_fields=["role"])
        stale.first_name = "Late profile write"
        stale.save()
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertIsNone(authenticate(username=self.user.username, password="pass1234"))

    def test_independent_password_and_requirement_changes_survive_promotion(self):
        self.user.password_from_participant_link = False
        self.user.save(update_fields=["password_from_participant_link"])
        self.user.set_password("NewIndependentPassword42!")
        self.user.must_change_password = True
        self.user.role = "admin"
        self.user.save()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewIndependentPassword42!"))
        self.assertTrue(self.user.must_change_password)
        self.assertTrue(self.user.independent_login_required)

    def test_combined_marked_password_write_and_promotion_is_explicitly_refused(self):
        provider = OAuthProvider.objects.create(name="combined-provider")
        SocialAccount.objects.create(user=self.user, provider=provider, uid="owner")
        self.user.set_password("StillParticipantPassword42!")
        self.user.role = "admin"
        with self.assertRaises(ValidationError):
            self.user.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, "user")
        self.assertTrue(self.user.check_password("pass1234"))

    def test_recovery_clears_origin_and_revokes_existing_sessions(self):
        self.user.independent_login_required = True
        self.user.save(update_fields=["independent_login_required"])
        old_version = self.user.session_version
        recover_password(self.user, "OperatorReplacement42!")
        self.user.refresh_from_db()
        self.assertFalse(self.user.password_from_participant_link)
        self.assertFalse(self.user.must_change_password)
        self.assertEqual(self.user.session_version, old_version + 1)
        client = APIClient()
        response = client.post("/api/v1/auth/token/", {
            "username": self.user.username, "password": "OperatorReplacement42!",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 200)
        self.assertFalse(is_session_current({"sv": old_version}, self.user))

    def test_command_uses_trusted_recovery(self):
        with patch("accounts.management.commands.recover_password.getpass", return_value="CommandReplacement42!"):
            call_command("recover_password", self.user.username, stdout=io.StringIO())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("CommandReplacement42!"))
        self.assertFalse(self.user.password_from_participant_link)
        self.assertEqual(self.user.session_version, 1)

    def test_command_audit_failure_rolls_back_password_and_credential_retirement(self):
        from accounts import magic_links
        from testing.factories import ParticipantFactory
        from zev import onboarding

        self.user.must_change_password = True
        self.user.save(update_fields=["must_change_password"])
        original = self.user.password
        participant = ParticipantFactory(user=self.user, email=self.user.email)
        token = onboarding.get_or_create_for_participant(participant)
        magic = magic_links.issue(self.user)
        code = OAuthExchangeCode.objects.create(user=self.user, code="operator-audit-rollback")
        with patch("accounts.management.commands.recover_password.getpass", return_value="CommandReplacement42!"), patch(
            "accounts.management.commands.recover_password.record_audit_event", side_effect=RuntimeError("audit failed"),
        ), self.assertRaises(RuntimeError):
            call_command("recover_password", self.user.username, stdout=io.StringIO())
        self.user.refresh_from_db()
        token.refresh_from_db()
        magic.refresh_from_db()
        self.assertEqual(self.user.password, original)
        self.assertTrue(self.user.password_from_participant_link)
        self.assertTrue(self.user.must_change_password)
        self.assertEqual(self.user.session_version, 0)
        self.assertIsNone(token.revoked_at)
        self.assertIsNone(magic.consumed_at)
        self.assertTrue(OAuthExchangeCode.objects.filter(pk=code.pk).exists())

    def test_command_rejects_mismatched_and_weak_passwords_without_changes(self):
        for passwords in (("FirstPassword42!", "DifferentPassword42!"), ("a", "a")):
            with self.subTest(passwords=passwords), patch(
                "accounts.management.commands.recover_password.getpass", side_effect=passwords,
            ), self.assertRaises(CommandError):
                call_command("recover_password", self.user.username, stdout=io.StringIO())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("pass1234"))
        self.assertTrue(self.user.password_from_participant_link)
        self.assertEqual(self.user.session_version, 0)

    def test_django_admin_password_recovery_clears_origin_and_revokes_sessions(self):
        for usable in (True, False):
            with self.subTest(usable=usable):
                if not usable:
                    self.user.set_unusable_password()
                self.user.password_from_participant_link = True
                self.user.save(update_fields=["password", "password_from_participant_link"])
                version = self.user.session_version
                form = IndependentPasswordChangeForm(self.user, data={
                    "password1": "AdminReplacement42!", "password2": "AdminReplacement42!",
                    "usable_password": "true",
                })
                self.assertTrue(form.is_valid(), form.errors)
                form.save()
                self.user.refresh_from_db()
                self.assertTrue(self.user.check_password("AdminReplacement42!"))
                self.assertFalse(self.user.password_from_participant_link)
                self.assertEqual(self.user.session_version, version + 1)

    def test_django_admin_can_disable_password_login(self):
        magic = MagicLinkToken.objects.create(user=self.user, token="disable-password-link")
        OAuthExchangeCode.objects.create(user=self.user, code="disable-password-exchange")
        form = IndependentPasswordChangeForm(self.user, data={"usable_password": "false"})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.user.refresh_from_db()
        magic.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertFalse(self.user.password_from_participant_link)
        self.assertEqual(self.user.session_version, 1)
        self.assertIsNotNone(magic.consumed_at)
        self.assertFalse(OAuthExchangeCode.objects.filter(user=self.user).exists())

    @override_settings(PASSWORD_HASHERS=[
        "django.contrib.auth.hashers.PBKDF2PasswordHasher", "django.contrib.auth.hashers.MD5PasswordHasher",
    ])
    def test_password_hash_upgrade_preserves_participant_origin(self):
        original = self.user.password
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                User.objects.filter(pk=self.user.pk).update(password=original)
                self.user.refresh_from_db()
                check = async_to_sync(self.user.acheck_password) if asynchronous else self.user.check_password
                self.assertTrue(check("pass1234"))
                self.user.refresh_from_db()
                self.assertTrue(self.user.password.startswith("pbkdf2_sha256$"))
                self.assertTrue(self.user.password_from_participant_link)

    @override_settings(PASSWORD_HASHERS=[
        "django.contrib.auth.hashers.PBKDF2PasswordHasher", "django.contrib.auth.hashers.MD5PasswordHasher",
    ])
    def test_password_hash_upgrade_cannot_restore_a_concurrently_retired_password(self):
        from django.contrib.auth.hashers import make_password

        def retire_before_upgrade(password):
            retired = make_password(None)
            User.objects.filter(pk=self.user.pk).update(
                password=retired, password_from_participant_link=False, independent_login_required=True,
            )
            self.user.password = retired
            return make_password(password)

        original = self.user.password
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                User.objects.filter(pk=self.user.pk).update(password=original, password_from_participant_link=True)
                self.user.refresh_from_db()
                check = async_to_sync(self.user.acheck_password) if asynchronous else self.user.check_password
                with patch("accounts.models.make_password", side_effect=retire_before_upgrade):
                    self.assertFalse(check("pass1234"))
                self.user.refresh_from_db()
                self.assertFalse(self.user.has_usable_password())

    def test_marked_password_tokens_still_fail_for_protected_accounts(self):
        self.user.independent_login_required = True
        self.user.save(update_fields=["independent_login_required"])
        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken(make_jwt_for_user(self.user, participant_link=True)["access"])
        self.assertTrue(is_participant_link_session(token))
        self.assertFalse(is_session_current(token, self.user))
