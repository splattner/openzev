"""Participant credentials survive edits; only completed link logins permit recovery."""
from datetime import timedelta
from unittest.mock import patch

import pyotp
from cryptography.fernet import Fernet

from django.db import connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts import email_change, magic_links, mfa
from accounts.api_keys import generate_key
from accounts.jwt_utils import PASSWORD_RECOVERY_CLAIM, make_jwt_for_user, password_recovery_deadline
from accounts.models import ApiKey, AppSettings, MagicLinkToken, OAuthExchangeCode, TotpDevice, User
from accounts.session_revocation import revoke_sessions
from audit.models import AuditEvent
from testing.factories import ParticipantFactory
from testing.helpers import authenticate, make_user
from zev import onboarding
from zev.models import ZevAccessGrant
from zev.services import ensure_participant_account, get_participant_onboarding_link, send_participant_onboarding_link

ME = "/api/v1/auth/me/"
RESET = ME + "reset-password/"
INITIAL = ME + "set-initial-password/"
ONBOARD = "/api/v1/public/onboarding/consume/"
MAGIC = "/api/v1/public/magic-link/consume/"
MFA = "/api/v1/auth/token/mfa/"
PASSWORD = "A-new-participant-password42!"


class ParticipantPasswordRecoveryTests(TestCase):
    def setUp(self):
        self.participant = ParticipantFactory(user=None, email="recovery@example.com")
        self.user = ensure_participant_account(self.participant)
        self.client = APIClient()

    def choose_password(self, *, pending=False):
        self.user.set_password(PASSWORD)
        self.user.must_change_password = pending
        self.user.save(update_fields=["password", "must_change_password"])

    def link_login(self, door="onboarding", client=None):
        client = client or self.client
        if door == "onboarding":
            _, token = get_participant_onboarding_link(self.participant)
            return client.post(ONBOARD, {"prefix": token.prefix, "s": token.secret}, format="json")
        token = magic_links.issue(self.user)
        return client.post(MAGIC, {"token": token.token}, format="json")

    def test_participant_credential_password_login_does_not_grant_or_renew_recovery(self):
        self.choose_password()
        self.user.password_from_participant_link = True
        self.user.save(update_fields=["password_from_participant_link"])
        client = APIClient()
        response = client.post("/api/v1/auth/token/", {"email": self.user.email, "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(client.get(ME).data["password_recovery_expires_at"])
        self.assertEqual(client.post(RESET, {"new_password": "DeniedPassword42!"}).status_code, 403)
        self.assertEqual(client.post(ME + "change-password/", {
            "old_password": PASSWORD, "new_password": "ChangedParticipantPassword42!",
        }).status_code, 200)
        self.assertIsNone(client.get(ME).data["password_recovery_expires_at"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.password_from_participant_link)

    def test_link_setup_then_manager_address_edit_keeps_real_password_login_working(self):
        self.assertEqual(self.link_login().status_code, 200)
        self.assertEqual(self.client.post(INITIAL, {"new_password": PASSWORD}).status_code, 200)
        manager = make_user("recovery_manager")
        ZevAccessGrant.objects.create(zev=self.participant.zev, user=manager, role="manager")
        manager.refresh_from_db()
        editor = APIClient()
        authenticate(editor, manager)
        for address in ("New address 1", "New address 2"):
            response = editor.patch(
                f"/api/v1/zev/participants/{self.participant.pk}/", {"address_line1": address}, format="json",
            )
            self.assertEqual(response.status_code, 200, response.data)
            signed_in = APIClient().post("/api/v1/auth/token/", {"email": self.user.email, "password": PASSWORD})
            self.assertEqual(signed_in.status_code, 200, signed_in.data)

    def test_edits_copy_send_and_magic_request_preserve_password_and_pending_flag(self):
        for pending in (False, True):
            with self.subTest(pending=pending):
                self.choose_password(pending=pending)
                original = self.user.password
                operations = (
                    lambda: ensure_participant_account(self.participant),
                    lambda: get_participant_onboarding_link(self.participant),
                    lambda: send_participant_onboarding_link(self.participant, self.user),
                    lambda: magic_links.account_for_participant(self.participant),
                )
                self.participant.city = "Bern"
                self.participant.save()
                with patch("zev.emails.EmailMessage.send"):
                    for operation in operations:
                        operation()
                        self.user.refresh_from_db()
                        self.assertEqual(self.user.password, original)
                        self.assertEqual(self.user.must_change_password, pending)

    def test_both_link_doors_preserve_chosen_password_and_grant_recovery(self):
        self.choose_password()
        original = self.user.password
        for door in ("onboarding", "magic"):
            with self.subTest(door=door):
                self.assertEqual(self.link_login(door).status_code, 200)
                self.user.refresh_from_db()
                self.assertEqual(self.user.password, original)
                self.assertFalse(self.user.must_change_password)
                self.assertIsNotNone(self.client.get(ME).data["password_recovery_expires_at"])

    def test_only_valid_link_consumption_retires_pending_password(self):
        for door in ("onboarding", "magic"):
            with self.subTest(door=door):
                self.choose_password(pending=True)
                self.assertEqual(self.link_login(door).status_code, 200)
                self.user.refresh_from_db()
                self.assertFalse(self.user.has_usable_password())
                self.assertFalse(self.user.must_change_password)
        self.choose_password(pending=True)
        for url, data in ((ONBOARD, {"prefix": "bad", "s": "bad"}), (MAGIC, {"token": "bad"})):
            self.client.post(url, data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertTrue(self.user.must_change_password)

    def test_pending_credentials_survive_incomplete_mfa_and_retire_only_on_success(self):
        for door in ("onboarding", "magic"):
            with self.subTest(door=door):
                self.choose_password(pending=True)
                original = self.user.password
                client = APIClient()
                with patch("accounts.mfa.requires_challenge", return_value=True):
                    challenge = self.link_login(door, client)
                self.assertTrue(challenge.data["mfa_required"])
                self.assertNotIn("openzev_access", challenge.cookies)
                self.user.refresh_from_db()
                self.assertEqual(self.user.password, original)
                self.assertTrue(self.user.must_change_password)
                payload = {"mfa_token": challenge.data["mfa_token"], "code": "123456"}
                with patch("accounts.mfa.verify_mfa_code", return_value=(False, None, "invalid_code")):
                    self.assertEqual(client.post(MFA, payload).status_code, 400)
                self.user.refresh_from_db()
                self.assertEqual(self.user.password, original)
                self.assertTrue(self.user.must_change_password)
                with patch("accounts.mfa.verify_mfa_code", return_value=(True, "totp", None)):
                    self.assertEqual(client.post(MFA, payload).status_code, 200)
                self.user.refresh_from_db()
                self.assertFalse(self.user.has_usable_password())
                self.assertFalse(self.user.must_change_password)
                self.assertIsNotNone(client.get(ME).data["password_recovery_expires_at"])

    def test_setup_and_change_retire_account_wide_links_and_notify(self):
        second = ParticipantFactory(user=self.user, email=self.user.email)
        for endpoint in (INITIAL, ME + "change-password/"):
            with self.subTest(endpoint=endpoint):
                if endpoint != INITIAL:
                    self.choose_password()
                self.user.refresh_from_db()
                authenticate(self.client, self.user)
                _, token = get_participant_onboarding_link(self.participant)
                onboarding.get_or_create_for_participant(second)
                magic = magic_links.issue(self.user)
                data = {"new_password": "Replacement-password42!"}
                if endpoint != INITIAL:
                    data["old_password"] = PASSWORD
                with patch("accounts.views.notifications.notify") as notify, self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(endpoint, data)
                self.assertEqual(response.status_code, 200, response.data)
                notify.assert_called_once()
                self.client.credentials()
                self.assertFalse(second.onboarding_tokens.filter(revoked_at__isnull=True).exists())
                self.assertEqual(APIClient().post(ONBOARD, {"prefix": token.prefix, "s": token.secret}).status_code, 404)
                self.assertEqual(APIClient().post(MAGIC, {"token": magic.token}).status_code, 400)
                self.assertEqual(self.client.get(ME).status_code, 200)
                self.assertIsNone(self.client.get(ME).data["password_recovery_expires_at"])

    def test_participant_email_remains_manager_maintained_after_password_setup(self):
        self.choose_password()
        authenticate(self.client, self.user)
        self.assertFalse(self.client.get(ME).data["can_change_email"])
        response = self.client.post(ME + "email-change/", {
            "new_email": "new@example.com", "current_password": PASSWORD,
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "managed_email")
        token = email_change.issue_token(self.user, "new@example.com")
        self.assertEqual(APIClient().post("/api/v1/auth/confirm-email-change/", {"token": token}).status_code, 400)
        manager = make_user("email_manager")
        ZevAccessGrant.objects.create(zev=self.participant.zev, user=manager, role="manager")
        manager.refresh_from_db()
        editor = APIClient()
        authenticate(editor, manager)
        response = editor.patch(f"/api/v1/zev/participants/{self.participant.pk}/", {"city": "Bern"})
        self.assertEqual(response.status_code, 200, response.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "recovery@example.com")
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_sessions_without_live_recovery_claim_skip_eligibility_queries(self):
        token = AccessToken(make_jwt_for_user(self.user)["access"])
        for deadline in (None, int(timezone.now().timestamp()) - 1):
            if deadline is not None:
                token[PASSWORD_RECOVERY_CLAIM] = deadline
            with self.assertNumQueries(0):
                self.assertIsNone(password_recovery_deadline(token, self.user))

    def test_refresh_preserves_absolute_deadline_and_expiry_denies_without_mutation(self):
        self.choose_password()
        self.link_login()
        deadline = AccessToken(self.client.cookies["openzev_access"].value)[PASSWORD_RECOVERY_CLAIM]
        self.assertAlmostEqual(deadline - timezone.now().timestamp(), 900, delta=2)
        with patch("accounts.jwt_utils.timezone.now", return_value=timezone.now() + timedelta(minutes=5)):
            self.assertEqual(self.client.post("/api/v1/auth/token/refresh/").status_code, 200)
        refreshed = AccessToken(self.client.cookies["openzev_access"].value)
        self.assertEqual(refreshed[PASSWORD_RECOVERY_CLAIM], deadline)
        refresh = RefreshToken(self.client.cookies["openzev_refresh"].value)
        self.assertEqual(refresh[PASSWORD_RECOVERY_CLAIM], deadline)
        with patch("accounts.jwt_utils.timezone.now", return_value=timezone.now() + timedelta(minutes=16)):
            self.assertIsNone(self.client.get(ME).data["password_recovery_expires_at"])
            self.assertEqual(self.client.post(RESET, {"new_password": "Another-password42!"}).status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertTrue(AuditEvent.objects.filter(action_type="password.reset", status="denied").exists())

    def test_reset_retires_all_communities_sessions_and_links_keeps_caller_and_api_keys(self):
        self.choose_password(pending=True)
        self.link_login()
        proof = self.client.cookies["openzev_access"].value
        other = APIClient()
        authenticate(other, self.user)
        second = ParticipantFactory(user=self.user, email=self.user.email)
        onboarding.get_or_create_for_participant(second)
        magic_links.issue(self.user)
        OAuthExchangeCode.objects.create(user=self.user, code="pending-before-link-recovery")
        _, prefix, hashed_secret = generate_key()
        key = ApiKey.objects.create(user=self.user, name="existing", prefix=prefix, hashed_key=hashed_secret)
        with patch("accounts.views.notifications.notify") as notify, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(RESET, {"new_password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.data)
        notify.assert_called_once()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertFalse(self.user.must_change_password)
        self.assertEqual(self.client.get(ME).status_code, 200)
        self.assertIsNone(self.client.get(ME).data["password_recovery_expires_at"])
        self.assertEqual(other.get(ME).status_code, 401)
        self.assertFalse(MagicLinkToken.objects.filter(user=self.user, consumed_at__isnull=True).exists())
        self.assertFalse(second.onboarding_tokens.filter(revoked_at__isnull=True).exists())
        self.assertFalse(self.participant.onboarding_tokens.filter(revoked_at__isnull=True).exists())
        key.refresh_from_db()
        self.assertIsNone(key.revoked_at)
        self.assertEqual(APIClient().post("/api/v1/auth/oauth/token-exchange/", {
            "code": "pending-before-link-recovery",
        }).status_code, 400)
        replay = APIClient()
        replay.credentials(HTTP_AUTHORIZATION=f"Bearer {proof}")
        self.assertEqual(replay.post(RESET, {"new_password": "Replay-password42!"}).status_code, 401)
        event = AuditEvent.objects.get(action_type="password.reset", status="success")
        self.assertEqual(event.metadata_json["onboarding_links_revoked"], 2)
        self.assertEqual(event.metadata_json["magic_links_revoked"], 1)
        self.assertNotIn(PASSWORD, str(event.metadata_json))

    def test_profile_edit_loaded_before_recovery_cannot_restore_credentials_or_pending_flag(self):
        from accounts.serializers import SelfUserSerializer

        self.choose_password()
        self.link_login()
        User.objects.filter(pk=self.user.pk).update(must_change_password=True)
        stale = User.objects.get(pk=self.user.pk)
        response = self.client.post(RESET, {"new_password": "Replacement-password42!"})
        self.assertEqual(response.status_code, 200, response.data)
        serializer = SelfUserSerializer(stale, data={"first_name": "Updated"}, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")
        self.assertTrue(self.user.check_password("Replacement-password42!"))
        self.assertFalse(self.user.must_change_password)

    def test_ordinary_and_impersonated_sessions_cannot_recover(self):
        self.choose_password()
        for tokens in (make_jwt_for_user(self.user), make_jwt_for_user(self.user, impersonated_by=123)):
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
            self.assertIsNone(self.client.get(ME).data["password_recovery_expires_at"])
            self.assertEqual(self.client.post(RESET, {"new_password": "Another-password42!"}).status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_invalid_password_does_not_spend_recovery_permission(self):
        self.choose_password()
        self.link_login()
        for payload in ({"new_password": "short"}, {"new_password": None}, {"new_password": 42}, {}, []):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(RESET, payload, format="json").status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertIsNotNone(self.client.get(ME).data["password_recovery_expires_at"])

    def test_api_keys_and_missing_csrf_cannot_recover(self):
        self.choose_password()
        raw, prefix, hashed_secret = generate_key()
        ApiKey.objects.create(user=self.user, name="existing", prefix=prefix, hashed_key=hashed_secret)
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
        self.assertEqual(self.client.post(RESET, {"new_password": PASSWORD}).status_code, 403)
        csrf_client = APIClient(enforce_csrf_checks=True)
        self.link_login(client=csrf_client)
        self.assertEqual(csrf_client.post(RESET, {"new_password": PASSWORD}).status_code, 403)

    def test_revocation_and_promotion_invalidate_permission(self):
        self.choose_password()
        self.link_login()
        proof = self.client.cookies["openzev_access"].value
        revoke_sessions(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {proof}")
        self.assertEqual(self.client.post(RESET, {"new_password": PASSWORD}).status_code, 401)
        self.client.credentials()
        self.link_login()
        ZevAccessGrant.objects.create(zev=self.participant.zev, user=self.user, role="viewer")
        self.assertEqual(self.client.post(RESET, {"new_password": PASSWORD}).status_code, 401)

    def test_link_mfa_carries_provenance_only_after_completion(self):
        for door in ("onboarding", "magic"):
            with self.subTest(door=door), patch("accounts.mfa.requires_challenge", return_value=True):
                response = self.link_login(door, APIClient())
                self.assertNotIn("openzev_access", response.cookies)
                with patch("accounts.mfa.verify_mfa_code", return_value=(True, "totp", None)):
                    completed = self.client.post(MFA, {"mfa_token": response.data["mfa_token"], "code": "123456"})
                self.assertEqual(completed.status_code, 200)
                self.assertIsNotNone(self.client.get(ME).data["password_recovery_expires_at"])
        with patch("accounts.mfa.verify_mfa_code", return_value=(True, "totp", None)):
            response = self.client.post(MFA, {"mfa_token": mfa.issue_challenge(self.user), "code": "123456"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.get(ME).data["password_recovery_expires_at"])

    @override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()])
    def test_real_totp_link_login_grants_recovery_and_records_both_factors(self):
        for door in ("onboarding", "magic"):
            with self.subTest(door=door):
                participant = ParticipantFactory(user=None, email=f"totp-{door}@example.com")
                user = ensure_participant_account(participant)
                user.set_password(PASSWORD)
                user.save(update_fields=["password"])
                original_password = user.password
                secret = pyotp.random_base32()
                device = TotpDevice(user=user, confirmed_at=timezone.now())
                device.set_secret(secret)
                device.save()
                client = APIClient()
                if door == "onboarding":
                    _, token = get_participant_onboarding_link(participant)
                    url, data = ONBOARD, {"prefix": token.prefix, "s": token.secret}
                else:
                    token = magic_links.issue(user)
                    url, data = MAGIC, {"token": token.token}
                challenge = client.post(url, data)
                self.assertTrue(challenge.data["mfa_required"])
                self.assertNotIn("openzev_access", challenge.cookies)
                completed = client.post(MFA, {
                    "mfa_token": challenge.data["mfa_token"], "code": pyotp.TOTP(secret).now(),
                })
                self.assertEqual(completed.status_code, 200, completed.data)
                user.refresh_from_db()
                self.assertEqual(user.password, original_password)
                self.assertIsNotNone(client.get(ME).data["password_recovery_expires_at"])
                event = AuditEvent.objects.get(action_type="auth.login", actor_user=user)
                self.assertEqual(event.metadata_json, {
                    "method": "participant_link+totp", "first_factor": "participant_link", "second_factor": "totp",
                })
                self.assertEqual(client.post(RESET, {"new_password": "TOTP-replacement-password42!"}).status_code, 200)
                user.refresh_from_db()
                self.assertTrue(user.check_password("TOTP-replacement-password42!"))
                self.assertIsNone(client.get(ME).data["password_recovery_expires_at"])

    def test_existing_object_challenge_defaults_to_no_link_provenance(self):
        from django.core.signing import TimestampSigner

        challenge = TimestampSigner(salt=mfa.MFA_CHALLENGE_SALT).sign_object({
            "user": self.user.pk, "sv": self.user.session_version,
        })
        user, participant_link, recovery = mfa.resolve_challenge(challenge)
        self.assertEqual(user.pk, self.user.pk)
        self.assertFalse(participant_link)
        self.assertFalse(recovery)

    def test_initial_password_audit_uses_actual_pending_flag(self):
        for pending in (False, True):
            with self.subTest(pending=pending):
                user = User.objects.create_user(username=f"initial-audit-{pending}", must_change_password=pending)
                client = APIClient()
                authenticate(client, user)
                self.assertEqual(client.post(INITIAL, {"new_password": PASSWORD}).status_code, 200)
                event = AuditEvent.objects.get(action_type="password.set_initial", target_id=str(user.pk))
                expected = {"must_change_password": {"before": True, "after": False}} if pending else {}
                self.assertEqual(event.changes_json, expected)

    def test_password_change_and_credential_retirement_roll_back_on_audit_failure(self):
        self.choose_password(pending=True)
        authenticate(self.client, self.user)
        _, token = get_participant_onboarding_link(self.participant)
        magic = magic_links.issue(self.user)
        original_version = self.user.session_version
        with patch("accounts.views.record_audit_event", side_effect=RuntimeError("audit unavailable")), \
                patch("accounts.views.notifications.notify") as notify, self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                self.client.post(ME + "change-password/", {"old_password": PASSWORD, "new_password": "Replacement42!"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertTrue(self.user.must_change_password)
        self.assertEqual(self.user.session_version, original_version)
        token.refresh_from_db()
        magic.refresh_from_db()
        self.assertIsNone(token.revoked_at)
        self.assertIsNone(magic.consumed_at)
        notify.assert_not_called()
        self.assertEqual(self.client.get(ME).status_code, 200)

    def test_mfa_cannot_renew_challenge_revoked_between_resolution_and_lock(self):
        challenge = mfa.issue_challenge(self.user, participant_link=True)
        original = User.objects.locked

        def revoke_before_lock():
            User.objects.filter(pk=self.user.pk).update(session_version=self.user.session_version + 1)
            return original()

        with patch("accounts.models.User.objects.locked", side_effect=revoke_before_lock):
            response = self.client.post(MFA, {"mfa_token": challenge, "code": "123456"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("openzev_access", response.cookies)

    def test_mfa_rechecks_expiry_after_locked_lookup(self):
        challenge = mfa.issue_challenge(self.user, participant_link=True)
        payload = {"user": self.user.pk, "sv": self.user.session_version, "participant_link": True}
        order = []
        locked_users = User.objects.locked()
        original_get = locked_users.get

        def get_locked_user(*args, **kwargs):
            user = original_get(*args, **kwargs)
            order.append("locked_lookup")
            return user

        def resolve_payload(token):
            order.append("payload")
            if len(order) == 3:
                raise mfa.MfaChallengeError("expired_challenge")
            return payload

        with transaction.atomic(), patch("accounts.mfa._challenge_payload", side_effect=resolve_payload), \
                patch("accounts.models.User.objects.locked", return_value=locked_users), \
                patch.object(locked_users, "get", side_effect=get_locked_user):
            with self.assertRaises(mfa.MfaChallengeError) as error:
                mfa.resolve_challenge(challenge, lock=True)
        self.assertEqual(error.exception.reason, "expired_challenge")
        self.assertEqual(order, ["payload", "locked_lookup", "payload"])

    def test_passwordless_independent_account_can_still_set_initial_password(self):
        independent = User.objects.create_user(username="independent", may_create_zev=True, independent_login_required=True)
        authenticate(self.client, independent)
        self.assertEqual(self.client.post(INITIAL, {"new_password": PASSWORD}).status_code, 200)
        self.client.credentials()
        self.assertTrue(self.client.get(ME).data["can_change_email"])

    def test_protected_link_refusals_preserve_pending_credentials(self):
        self.choose_password(pending=True)
        ZevAccessGrant.objects.create(zev=self.participant.zev, user=self.user, role="viewer")
        token = onboarding.get_or_create_for_participant(self.participant)
        self.assertEqual(self.client.post(ONBOARD, {"prefix": token.prefix, "s": token.secret}).status_code, 404)
        self.assertEqual(self.link_login("magic").status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertTrue(self.user.must_change_password)

    def test_inactive_link_refusals_preserve_pending_credentials(self):
        self.choose_password(pending=True)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        token = onboarding.get_or_create_for_participant(self.participant)
        self.assertEqual(self.client.post(ONBOARD, {"prefix": token.prefix, "s": token.secret}).status_code, 404)
        self.assertEqual(self.link_login("magic").status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertTrue(self.user.must_change_password)

    def test_recovery_remains_available_when_mfa_enrolment_is_overdue(self):
        self.choose_password()
        self.link_login()
        settings = AppSettings.load()
        AppSettings.objects.filter(pk=settings.pk).update(
            mfa_required=True, mfa_grace_period_days=0,
            mfa_policy_changed_at=timezone.now() - timedelta(days=1),
        )
        self.assertEqual(self.client.post(RESET, {"new_password": PASSWORD}).status_code, 200)


class PasswordRecoveryLockTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_reset_rejects_link_consumption_waiting_on_the_user_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        for door in ("onboarding", "magic"):
            with self.subTest(door=door):
                participant = ParticipantFactory(user=None, email=f"race-{door}@example.com")
                user = ensure_participant_account(participant)
                _, token = get_participant_onboarding_link(participant)
                client = APIClient()
                self.assertEqual(client.post(ONBOARD, {"prefix": token.prefix, "s": token.secret}).status_code, 200)
                if door == "magic":
                    magic = magic_links.issue(user)
                    url, data = MAGIC, {"token": magic.token}
                else:
                    url, data = ONBOARD, {"prefix": token.prefix, "s": token.secret}
                waiting = Event()
                original_resolve = onboarding.resolve
                original_locked = User.objects.locked

                def resolved_before_lock(*args, **kwargs):
                    result = original_resolve(*args, **kwargs)
                    waiting.set()
                    return result

                def seeking_user_lock(*args, **kwargs):
                    waiting.set()
                    return original_locked(*args, **kwargs)

                def consume():
                    try:
                        return APIClient().post(url, data)
                    finally:
                        connections.close_all()

                target = "zev.onboarding.resolve" if door == "onboarding" else "accounts.models.User.objects.locked"
                callback = resolved_before_lock if door == "onboarding" else seeking_user_lock
                with ThreadPoolExecutor(1) as pool:
                    with transaction.atomic():
                        User.objects.locked().get(pk=user.pk)
                        with patch(target, side_effect=callback):
                            future = pool.submit(consume)
                            self.assertTrue(waiting.wait(5))
                            self.assertEqual(client.post(RESET, {"new_password": PASSWORD}).status_code, 200)
                    response = future.result(timeout=10)
                self.assertEqual(response.status_code, 404 if door == "onboarding" else 400)
                self.assertNotIn("openzev_access", response.cookies)
                user.refresh_from_db()
                self.assertTrue(user.check_password(PASSWORD))

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_resets_with_same_authority_only_one_succeeds(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event, Lock
        from accounts.session_revocation import lock_current_session

        participant = ParticipantFactory(user=None, email="reset-race@example.com")
        user = ensure_participant_account(participant)
        _, token = get_participant_onboarding_link(participant)
        client = APIClient()
        self.assertEqual(client.post(ONBOARD, {"prefix": token.prefix, "s": token.secret}).status_code, 200)
        proof = client.cookies["openzev_access"].value
        waiting, mutex, arrivals = Event(), Lock(), []

        def wait_for_session(request):
            with mutex:
                arrivals.append(True)
                if len(arrivals) == 2:
                    waiting.set()
            return lock_current_session(request)

        def reset():
            try:
                caller = APIClient()
                caller.credentials(HTTP_AUTHORIZATION=f"Bearer {proof}")
                return caller.post(RESET, {"new_password": PASSWORD}).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(2) as pool:
            with transaction.atomic():
                User.objects.locked().get(pk=user.pk)
                with patch("accounts.views.lock_current_session", side_effect=wait_for_session):
                    futures = [pool.submit(reset), pool.submit(reset)]
                    self.assertTrue(waiting.wait(5))
            self.assertEqual(sorted(future.result(timeout=10) for future in futures), [200, 401])
        user.refresh_from_db()
        self.assertTrue(user.check_password(PASSWORD))

    @skipUnlessDBFeature("has_select_for_update")
    def test_magic_issuance_waits_for_recovery_and_promotion(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        for action in ("recovery", "promotion"):
            with self.subTest(action=action):
                participant = ParticipantFactory(user=None, email=f"issuance-{action}@example.com")
                user = ensure_participant_account(participant)
                user.set_password(PASSWORD)
                user.save(update_fields=["password"])
                _, token = get_participant_onboarding_link(participant)
                client = APIClient()
                self.assertEqual(client.post(ONBOARD, {"prefix": token.prefix, "s": token.secret}).status_code, 200)
                seeking_lock = Event()
                original_locked = User.objects.locked

                def locked_users():
                    seeking_lock.set()
                    return original_locked()

                def issue():
                    try:
                        return magic_links.issue(user).pk
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(1) as pool:
                    with transaction.atomic():
                        User.objects.locked().get(pk=user.pk)
                        with patch("accounts.models.User.objects.locked", side_effect=locked_users):
                            future = pool.submit(issue)
                            self.assertTrue(seeking_lock.wait(5))
                            self.assertFalse(future.done())
                            if action == "recovery":
                                self.assertEqual(client.post(RESET, {"new_password": "Replacement42!"}).status_code, 200)
                            else:
                                ZevAccessGrant.objects.create(zev=participant.zev, user=user, role="viewer")
                            write_finished = timezone.now()
                    magic = MagicLinkToken.objects.get(pk=future.result(timeout=10))
                self.assertGreaterEqual(magic.created_at, write_finished)
                signed_in = APIClient().post(MAGIC, {"token": magic.token})
                self.assertEqual(signed_in.status_code, 200 if action == "recovery" else 400)
