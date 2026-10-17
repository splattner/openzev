"""Promotion retires participant bearer credentials."""

import uuid
from datetime import timedelta
from unittest.mock import patch

import pyotp
from cryptography.fernet import Fernet
from django.contrib.admin import site
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.magic_links import consume, issue
from accounts import mfa
from accounts.api_keys import generate_key
from accounts.authentication import CookieJWTAuthentication
from accounts.jwt_utils import is_participant_link_session
from accounts.models import ApiKey, EmailVerificationToken, OAuthProvider, SocialAccount, TotpDevice, User
from testing.passkeys import SoftAuthenticator, register_passkey, sign_in_with
from testing.helpers import authenticate, create_managed_zev, make_user
from zev import access, onboarding
from zev.models import Participant, Party, PartyRole, ZevAccessGrant
from zev.parties import assign_role
from zev.services import (
    ensure_participant_account, get_participant_onboarding_link, lock_participant_account, send_participant_onboarding_link,
)
from zev.views_access import _ZevAccessBase


class LoginProtectionUpgradeTests(TransactionTestCase):
    def migrate_to_latest(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def setUp(self):
        self.migrate_to_latest()
        self.addCleanup(self.migrate_to_latest)
        executor = MigrationExecutor(connection)
        targets = [
            (app, "0023_featureflag_follows_default") if app == "accounts" else (app, name)
            for app, name in executor.loader.graph.leaf_nodes()
        ]
        executor.migrate(targets)
        self.apps = executor.loader.project_state(targets).apps
        self.old_user = self.apps.get_model("accounts", "User")
        self.today = timezone.localdate()

    def test_upgrade_backfills_independent_accounts_only(self):
        protected = [
            self.old_user.objects.create(username="legacy_admin", role="admin"),
            self.old_user.objects.create(username="legacy_superuser", is_superuser=True),
            self.old_user.objects.create(username="legacy_self_setup", may_create_zev=True),
        ]
        zev = self.apps.get_model("zev", "Zev").objects.create(name="Legacy", invoice_prefix="L")
        windows = [
            (self.today, None),
            (self.today - timedelta(days=2), self.today - timedelta(days=1)),
            (self.today + timedelta(days=1), None),
        ]
        for role in ("manager", "viewer"):
            for index, (start, end) in enumerate(windows):
                user = self.old_user.objects.create(username=f"legacy_grant_{role}_{index}")
                self.apps.get_model("zev", "ZevAccessGrant").objects.create(
                    zev=zev, user=user, role=role, valid_from=start, valid_to=end,
                )
                protected.append(user)
        unprotected = [self.old_user.objects.create(username="legacy_participant_only")]
        self.apps.get_model("zev", "Participant").objects.create(
            zev=zev, user=unprotected[0], valid_from=self.today,
            party=self.apps.get_model("zev", "Party").objects.create(zev=zev, last_name="Tenant"),
        )
        for role in ("issuer", "representative", "landowner"):
            for through_participant in (False, True):
                for index, (start, end) in enumerate(windows):
                    name = f"legacy_{role}_{through_participant}_{index}"
                    user = self.old_user.objects.create(username=name)
                    role_zev = self.apps.get_model("zev", "Zev").objects.create(name=name, invoice_prefix="L")
                    party = self.apps.get_model("zev", "Party").objects.create(
                        zev=role_zev, last_name=name, user=None if through_participant else user,
                    )
                    if through_participant:
                        self.apps.get_model("zev", "Participant").objects.create(
                            zev=role_zev, party=party, user=user, valid_from=start, valid_to=end,
                        )
                    self.apps.get_model("zev", "ZevPartyRole").objects.create(
                        zev=role_zev, party=party, role=role, valid_from=start, valid_to=end,
                    )
                    (unprotected if role == "landowner" else protected).append(user)

        self.migrate_to_latest()

        self.assertSetEqual(
            set(User.objects.filter(independent_login_required=True).values_list("pk", flat=True)),
            {user.pk for user in protected},
        )
        self.assertFalse(User.objects.filter(pk__in=[user.pk for user in unprotected], independent_login_required=True).exists())

    def test_upgrade_profile_save_preserves_existing_credentials(self):
        admin = self.old_user.objects.create(
            username="legacy_key_admin", role="admin", password=make_password("pass1234"), session_version=7,
        )
        client = APIClient()
        authenticate(client, admin)
        full_key, prefix, hashed = generate_key()
        key = self.apps.get_model("accounts", "ApiKey").objects.create(
            user=admin, name="Legacy automation", prefix=prefix, hashed_key=hashed,
        )

        self.migrate_to_latest()
        user = User.objects.get(pk=admin.pk)
        user.first_name = "Edited"
        user.save()

        user.refresh_from_db()
        self.assertEqual(user.session_version, 7)
        self.assertTrue(ApiKey.objects.get(pk=key.pk).is_active)
        self.assertEqual(user.password, admin.password)
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 200)
        key_client = APIClient()
        key_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {full_key}")
        self.assertEqual(key_client.get("/api/v1/zev/zevs/").status_code, 200)

    def test_upgrade_passwordless_admin_can_be_edited_and_stays_protected_after_demotion(self):
        admin = self.old_user.objects.create(
            username="legacy_passwordless_admin", role="admin", password=make_password(None),
        )
        self.migrate_to_latest()
        user = User.objects.get(pk=admin.pk)
        user.first_name = "Edited"
        user.save()
        user.role = "user"
        user.save(update_fields=["role"])
        user.refresh_from_db()

        self.assertTrue(user.independent_login_required)
        self.assertEqual(user.session_version, 0)
        self.assertFalse(user.has_usable_password())

    def test_upgrade_marks_only_legacy_participant_credentials_and_retires_their_sessions(self):
        Zev = self.apps.get_model("zev", "Zev")
        OldParticipant = self.apps.get_model("zev", "Participant")
        OldParty = self.apps.get_model("zev", "Party")
        Provider = self.apps.get_model("accounts", "OAuthProvider")
        Social = self.apps.get_model("accounts", "SocialAccount")
        Factor = self.apps.get_model("accounts", "TotpDevice")
        Passkey = self.apps.get_model("accounts", "WebAuthnCredential")
        Recovery = self.apps.get_model("accounts", "MfaRecoveryCode")
        State = self.apps.get_model("accounts", "OAuthState")
        Exchange = self.apps.get_model("accounts", "OAuthExchangeCode")
        zev = Zev.objects.create(name="Legacy", invoice_prefix="L")
        participant_account = self.old_user.objects.create(username="legacy_tenant", password=make_password("pass1234"))
        party_account = self.old_user.objects.create(username="legacy_party", password=make_password("pass1234"))
        promoted = self.old_user.objects.create(username="legacy_manager", role="admin", password=make_password("pass1234"))
        independent = self.old_user.objects.create(username="legacy_independent", password=make_password("pass1234"))
        provider = Provider.objects.create(name="legacy-provider", enabled=True)
        login_state = State.objects.create(provider=provider, state="legacy-login")
        for user in (participant_account, party_account, promoted):
            party_only = user == party_account
            OldParticipant.objects.create(
                zev=zev, user=None if party_only else user, valid_from=self.today,
                party=OldParty.objects.create(zev=zev, last_name=user.username, user=user if party_only else None),
            )
            Factor.objects.create(user=user, secret_encrypted=b"legacy")
            Passkey.objects.create(user=user, credential_id=user.username.encode(), public_key=b"legacy")
            Recovery.objects.create(user=user, code_hash="legacy")
            Social.objects.create(
                user=user, provider=provider, uid=user.username,
                extra_data={"email_verified": True, "email": "other@example.com"},
            )
            State.objects.create(user=user, provider=provider, state=user.username)
            Exchange.objects.create(user=user, code=user.username)
        participant_account.email = "tenant@example.com"
        participant_account.save(update_fields=["email"])
        Social.objects.create(
            user=participant_account, provider=provider, uid="verified-owner",
            extra_data={"email_verified": True, "email": f" {participant_account.email.upper()} "},
        )
        from rest_framework_simplejwt.tokens import RefreshToken

        old_token = RefreshToken.for_user(participant_account)
        old_token["sv"] = 0
        old_challenge = mfa.issue_challenge(participant_account)
        self.migrate_to_latest()
        for old_user in (participant_account, party_account, promoted, independent):
            user = User.objects.get(pk=old_user.pk)
            marked = old_user in (participant_account, party_account)
            enrolled = old_user != independent
            self.assertEqual(user.password_from_participant_link, marked)
            self.assertEqual(user.session_version, int(marked))
            self.assertEqual(user.password, old_user.password)
            for credentials in (user.webauthn_credentials, user.mfa_recovery_codes):
                self.assertEqual(credentials.count(), int(enrolled))
                self.assertFalse(credentials.exclude(from_participant_link=marked).exists())
            self.assertFalse(user.oauthstate_set.exists())
            devices = TotpDevice.objects.filter(user=user)
            self.assertEqual(devices.count(), int(enrolled))
            self.assertFalse(devices.exclude(from_participant_link=marked).exists())
            socials = user.social_accounts.exclude(uid="verified-owner")
            self.assertEqual(socials.count(), int(enrolled))
            self.assertFalse(socials.exclude(from_participant_link=marked).exists())
            from accounts.models import OAuthExchangeCode

            self.assertEqual(OAuthExchangeCode.objects.filter(user=user).count(), int(enrolled and not marked))
        self.assertFalse(SocialAccount.objects.get(uid="verified-owner").from_participant_link)
        from accounts.models import OAuthState

        self.assertTrue(OAuthState.objects.filter(pk=login_state.pk, session_version__isnull=True).exists())
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_token.access_token}")
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 401)
        with self.assertRaises(mfa.MfaChallengeError):
            mfa.resolve_challenge(old_challenge)


class LoginProtectionTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.manager = make_user("login_manager")
        self.zev = create_managed_zev(name="Login protection", owner=self.manager)
        self.participant = Participant.objects.create(
            zev=self.zev, last_name="Tenant", email="login_tenant@example.com", valid_from=self.today,
        )
        self.account = ensure_participant_account(self.participant)
        self.client = APIClient()
        authenticate(self.client, self.manager)
        self.url = f"/api/v1/zev/zevs/{self.zev.pk}/access/"

    def invite(self):
        response = self.client.post(self.url, {"email": self.account.email, "role": "viewer"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.data["id"]

    def managing_party(self):
        party = Party.objects.create(zev=self.zev, last_name="Representative")
        assign_role(self.zev, party, PartyRole.REPRESENTATIVE, self.today)
        return party

    def test_another_zevs_manager_cannot_deactivate_a_participant(self):
        other = create_managed_zev(name="Other", owner=self.manager)
        old_session = APIClient()
        authenticate(old_session, self.account)
        response = self.client.post(
            f"/api/v1/zev/zevs/{other.pk}/access/",
            {"email": self.account.email, "role": "viewer"}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_active)
        self.assertEqual(old_session.get("/api/v1/auth/me/").status_code, 200)
        self.assertFalse(ZevAccessGrant.objects.filter(user=self.account).exists())

    def test_cancelling_yesterdays_invitation_restores_login_and_only_spends_invitation_tokens(self):
        grant_id = self.invite()
        ZevAccessGrant.objects.filter(pk=grant_id).update(valid_from=self.today - timedelta(days=1))
        token = self.account.email_verification_tokens.get(purpose="invitation")
        signup = EmailVerificationToken.objects.create(user=self.account, purpose="signup", token="unrelated-signup")
        self.assertEqual(self.client.delete(self.url + grant_id + "/").status_code, 204)
        self.account.refresh_from_db()
        token.refresh_from_db()
        signup.refresh_from_db()
        self.assertTrue(self.account.is_active)
        self.assertIsNotNone(token.consumed_at)
        self.assertIsNone(signup.consumed_at)
        response = APIClient().post("/api/v1/auth/verify-email/", {"token": token.token}, format="json")
        self.assertEqual(response.status_code, 400)
        get_participant_onboarding_link(self.participant)

    def test_accepted_access_keeps_its_login_after_same_day_revocation(self):
        grant_id = self.invite()
        token = self.account.email_verification_tokens.get(purpose="invitation")
        client = APIClient()
        response = client.post("/api/v1/auth/verify-email/", {"token": token.token}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.post(
            "/api/v1/auth/me/set-initial-password/", {"new_password": "SafeIndependentPassword42!"}, format="json",
        ).status_code, 200)
        self.assertEqual(self.client.delete(self.url + grant_id + "/").status_code, 204)
        response = self.client.post(f"/api/v1/zev/participants/{self.participant.pk}/onboarding-link/")
        self.assertEqual(response.status_code, 400)
        ensure_participant_account(self.participant)
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password("SafeIndependentPassword42!"))

    def test_raw_id_saves_cannot_link_a_passwordless_account_to_a_managing_party(self):
        party = self.managing_party()
        target = Participant.objects.create(zev=self.zev, party=party, valid_from=self.today)
        for instance, field, value in (
            (target, "user_id", self.account.pk),
            (target, "user_id", str(self.account.pk)),
            (self.participant, "party_id", party.pk),
            (self.participant, "party_id", str(party.pk)),
            (party, "user_id", self.account.pk),
            (Party(pk=party.pk, zev=self.zev, last_name=party.last_name), "user", self.account),
        ):
            with self.subTest(model=type(instance).__name__, field=field):
                setattr(instance, field, value)
                with self.assertRaises(ValidationError):
                    instance.save(update_fields=[field])
                instance.refresh_from_db()
        self.assertFalse(access.can_manage(self.account, self.zev))

    def test_user_only_save_checks_the_current_party(self):
        stale = Participant.objects.get(pk=self.participant.pk)
        self.participant.user = None
        self.participant.party = self.managing_party()
        self.participant.save(update_fields=["user", "party"])

        stale.user = self.account
        with self.assertRaises(ValidationError):
            stale.save(update_fields=["user_id"])
        self.participant.refresh_from_db()
        self.assertIsNone(self.participant.user_id)

    def test_party_only_save_checks_the_current_account(self):
        original_party_id = self.participant.party_id
        stale = Participant.objects.get(pk=self.participant.pk)
        stale_account = make_user("stale_participant_account")
        stale.user = stale_account
        stale.party = self.managing_party()

        with self.assertRaises(ValidationError):
            stale.save(update_fields=["party_id"])
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.party_id, original_party_id)
        self.assertFalse(access.can_manage(self.account, self.zev))

    def test_link_lookup_refreshes_a_stale_party(self):
        stale = Participant.objects.get(pk=self.participant.pk)
        self.participant.user = None
        self.participant.party = self.managing_party()
        self.participant.save(update_fields=["user", "party"])

        from .services import LinkRefused, link_account_for

        with self.assertRaises(LinkRefused) as caught:
            link_account_for(stale)
        self.assertEqual(caught.exception.code, "login_setup_required")

    def test_link_lookup_refuses_a_removed_participant(self):
        from .services import link_account_for

        stale = Participant.objects.get(pk=self.participant.pk)
        self.participant.delete()

        with self.assertRaises(Participant.DoesNotExist):
            link_account_for(stale)

    def test_full_save_refuses_a_removed_participant(self):
        stale = Participant.objects.get(pk=self.participant.pk)
        self.participant.delete()

        with self.assertRaises(Participant.DoesNotExist):
            stale.save()
        self.assertFalse(Participant.objects.filter(pk=stale.pk).exists())

    def test_empty_saves_preserve_pending_fields_and_cached_objects(self):
        party, user = self.participant.party, self.participant.user
        self.participant.first_name = "Staged"
        for fields in ([], ()):
            with self.subTest(fields=fields), self.assertNumQueries(0):
                self.participant.save(update_fields=fields)
            self.assertIs(self.participant.party, party)
            self.assertIs(self.participant.user, user)
            self.assertEqual(self.participant.first_name, "Staged")
        self.participant.save(update_fields=["first_name"])
        party.refresh_from_db()
        self.assertEqual(party.first_name, "Staged")

    def test_unrelated_saves_do_not_query_or_reload_links(self):
        party, user = self.participant.party, self.participant.user
        party.city = "Unsaved"
        for field in ("notes", "valid_to", "allocation_weight"):
            with self.subTest(field=field), self.assertNumQueries(3):
                self.participant.save(update_fields=[field])
            self.assertIs(self.participant.party, party)
            self.assertIs(self.participant.user, user)
            self.assertEqual(party.city, "Unsaved")

    def test_failed_link_save_preserves_pending_party_fields(self):
        self.participant.first_name = "Staged"
        with patch("zev.services.lock_participant_account", side_effect=ValidationError("Changed")):
            with self.assertRaises(ValidationError):
                self.participant.save()
        self.assertEqual(self.participant.first_name, "Staged")
        self.participant.save(update_fields=["first_name"])
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.first_name, "Staged")

    def test_user_only_save_does_not_write_a_staged_party(self):
        party_id = self.participant.party_id
        account = User.objects.create_user(username="staged_link_account")
        self.participant.user = account
        self.participant.party = self.managing_party()

        self.participant.save(update_fields=["user"])

        self.participant.refresh_from_db()
        self.assertEqual(self.participant.user_id, account.pk)
        self.assertEqual(self.participant.party_id, party_id)

    def test_link_saves_preserve_unchanged_cached_objects(self):
        party, user = self.participant.party, self.participant.user
        party.city = "Unsaved"
        self.participant.save(update_fields=["user_id"])
        self.assertIs(self.participant.party, party)
        self.assertIs(self.participant.user, user)
        self.assertEqual(self.participant.party.city, "Unsaved")

    def test_missing_link_targets_return_field_errors(self):
        for field, value in (("user", 2**60), ("party", uuid.uuid4())):
            with self.subTest(field=field):
                setattr(self.participant, f"{field}_id", value)
                with self.assertRaises(ValidationError) as caught:
                    self.participant.save(update_fields=[field])
                self.assertIn(field, caught.exception.message_dict)
                self.participant.refresh_from_db()

    def test_link_lock_requires_an_outer_transaction(self):
        with patch.object(connection, "in_atomic_block", False), self.assertRaisesRegex(RuntimeError, "outer transaction"):
            lock_participant_account(self.participant)

    def test_link_actions_return_404_after_a_participant_is_removed(self):
        def remove_before_lock(participant):
            Participant.objects.filter(pk=participant.pk).delete()
            return lock_participant_account(participant)

        original_party_lock = Party.objects.select_for_update

        def remove_after_snapshot(*args, **kwargs):
            Participant.objects.filter(pk=self.participant.pk).delete()
            return original_party_lock(*args, **kwargs)

        for action in ("onboarding-link", "send-onboarding-link"):
            for seam, callback in (
                ("zev.services.lock_participant_account", remove_before_lock),
                ("zev.models.Party.objects.select_for_update", remove_after_snapshot),
            ):
                with self.subTest(action=action, seam=seam), patch(seam, side_effect=callback):
                    response = self.client.post(f"/api/v1/zev/participants/{self.participant.pk}/{action}/")
                self.assertEqual(response.status_code, 404, response.content)

    def test_link_actions_return_400_on_a_locking_conflict(self):
        for action in ("onboarding-link", "send-onboarding-link"):
            with self.subTest(action=action), patch("zev.services.lock_participant_account", side_effect=ValidationError("Changed")):
                response = self.client.post(f"/api/v1/zev/participants/{self.participant.pk}/{action}/")
            self.assertEqual(response.status_code, 400, response.content)

    def test_public_links_conceal_removed_or_changed_participants(self):
        from accounts.magic_links import account_for_participant

        _url, token = get_participant_onboarding_link(self.participant)
        for error in (Participant.DoesNotExist(), ValidationError("Changed")):
            with self.subTest(error=type(error).__name__), patch("zev.services.lock_participant_account", side_effect=error):
                response = APIClient().post(
                    "/api/v1/public/onboarding/consume/", {"prefix": token.prefix, "s": token.secret}, format="json",
                )
                self.assertIsNone(account_for_participant(self.participant))
            self.assertEqual(response.status_code, 404, response.content)
            self.assertNotIn("openzev_access", response.cookies)

    def test_participant_edit_returns_404_for_a_removed_participant(self):
        with patch("zev.serializers.lock_participant_account", side_effect=Participant.DoesNotExist):
            response = self.client.patch(f"/api/v1/zev/participants/{self.participant.pk}/", {"last_name": "Changed"})
        self.assertEqual(response.status_code, 404, response.content)

    def test_participant_edit_rechecks_unchanged_party_after_locking(self):
        from rest_framework.exceptions import ValidationError as APIValidationError

        from .serializers import ParticipantSerializer

        request = RequestFactory().patch("/")
        request.user = self.manager
        serializer = ParticipantSerializer(
            self.participant, data={"party": str(self.participant.party_id)}, partial=True,
            context={"request": request},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        moved = Participant.objects.get(pk=self.participant.pk)
        moved.party = Party.objects.create(zev=self.zev, last_name="Moved")
        moved.save(update_fields=["party"])

        with self.assertRaises(APIValidationError) as caught:
            serializer.save()

        self.assertIn("party", caught.exception.detail)
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.party_id, moved.party_id)

    def test_accepted_access_remains_protected_after_an_older_grant_is_revoked(self):
        grant_id = self.invite()
        token = self.account.email_verification_tokens.get(purpose="invitation")
        response = APIClient().post("/api/v1/auth/verify-email/", {"token": token.token}, format="json")
        self.assertEqual(response.status_code, 200)
        ZevAccessGrant.objects.filter(pk=grant_id).update(valid_from=self.today - timedelta(days=1))
        self.assertEqual(self.client.delete(self.url + grant_id + "/").status_code, 204)
        self.assertTrue(ZevAccessGrant.objects.filter(pk=grant_id, valid_to=self.today - timedelta(days=1)).exists())
        response = self.client.post(f"/api/v1/zev/participants/{self.participant.pk}/onboarding-link/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "own_login_required")

    def test_raw_id_saves_linking_a_managing_party_retire_participant_credentials(self):
        for model, field in (("participant", "user_id"), ("participant", "party_id"), ("party", "user_id")):
            with self.subTest(model=model, field=field):
                tenant = Participant.objects.create(
                    zev=self.zev, last_name="Tenant", email=f"{model}-{field}@example.com", valid_from=self.today,
                )
                _url, onboarding = get_participant_onboarding_link(tenant)
                tenant.user.set_password("IndependentPassword42!")
                tenant.user.save(update_fields=["password"])
                magic = issue(tenant.user)
                old = APIClient()
                authenticate(old, tenant.user)
                party = Party.objects.create(zev=self.zev, last_name="Issuer")
                assign_role(self.zev, party, PartyRole.ISSUER, self.today, valid_to=self.today)
                if field == "party_id":
                    target, value = tenant, party.pk
                elif model == "party":
                    target, value = party, tenant.user_id
                else:
                    target = Participant.objects.create(zev=self.zev, party=party, valid_from=self.today)
                    value = tenant.user_id
                setattr(target, field, value)
                target.save(update_fields=[field])
                self.assertEqual(old.get("/api/v1/auth/me/").status_code, 401)
                onboarding.refresh_from_db()
                magic.refresh_from_db()
                self.assertIsNotNone(onboarding.revoked_at)
                self.assertIsNotNone(magic.consumed_at)

    def test_saving_a_removed_grant_or_role_is_refused(self):
        grant = ZevAccessGrant.objects.get(zev=self.zev, user=self.manager)
        row = assign_role(self.zev, self.participant.party, PartyRole.LANDOWNER, self.today)
        for instance in (grant, row):
            type(instance).objects.filter(pk=instance.pk).delete()
            with self.subTest(model=type(instance).__name__), self.assertRaisesRegex(ValidationError, "removed"):
                instance.save()

    def test_role_identity_cannot_be_changed_in_place(self):
        row = assign_role(self.zev, self.participant.party, PartyRole.LANDOWNER, self.today)
        row.role = PartyRole.REPRESENTATIVE
        with self.assertRaises(ValidationError):
            row.save(update_fields=["role"])
        row = assign_role(self.zev, self.managing_party(), PartyRole.REPRESENTATIVE, self.today)
        row.party_id = self.participant.party_id
        with self.assertRaises(ValidationError):
            row.save(update_fields=["party_id"])
        self.assertFalse(access.can_manage(self.account, self.zev))

    def test_grant_recipient_cannot_be_changed_in_place(self):
        grant = ZevAccessGrant.objects.create(zev=self.zev, user=make_user("original_grantee"), role="viewer")
        grant.user_id = self.account.pk
        with self.assertRaises(ValidationError):
            grant.save(update_fields=["user_id"])
        self.assertFalse(access.can_view(self.account, self.zev))

    def test_managing_party_without_an_account_reports_setup_required(self):
        self.participant.user = None
        self.participant.save(update_fields=["user"])
        assign_role(self.zev, self.participant.party, PartyRole.REPRESENTATIVE, self.today)
        response = self.client.post(f"/api/v1/zev/participants/{self.participant.pk}/onboarding-link/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "login_setup_required")
        token = onboarding.get_or_create_for_participant(self.participant)
        response = APIClient().post(
            "/api/v1/public/onboarding/consume/", {"prefix": token.prefix, "s": token.secret}, format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("openzev_access", response.cookies)

    def test_account_sync_errors_on_participant_edit_return_400(self):
        with patch("zev.serializers.ensure_participant_account", side_effect=ValidationError("Invalid account")):
            response = self.client.patch(
                f"/api/v1/zev/participants/{self.participant.pk}/", {"notes": "changed"}, format="json",
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid account", str(response.data))

    def test_admin_form_rejects_passwordless_managing_party_link(self):
        party = self.managing_party()
        request = RequestFactory().get("/admin/zev/participant/add/")
        request.user = make_user("form_admin")
        request.user.is_superuser = True
        form_class = site._registry[Participant].get_form(request)
        form = form_class(data={
            "zev": self.zev.pk, "party": party.pk, "user": self.account.pk,
            "valid_from": self.today, "allocation_weight": "1",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("user", form.errors)

    def test_rejected_valid_magic_token_is_spent(self):
        self.account.set_password("IndependentPassword42!")
        self.account.save(update_fields=["password"])
        ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="viewer")
        token = issue(self.account)
        self.assertIsNone(consume(token.token))
        token.refresh_from_db()
        self.assertIsNotNone(token.consumed_at)

    def test_failed_existing_participant_invitation_can_be_resent(self):
        with patch("zev.views_access.EmailMessage.send", side_effect=OSError("smtp unavailable")):
            response = self.client.post(self.url, {"email": self.account.email, "role": "viewer"}, format="json")
        self.assertFalse(response.data["email_sent"])
        self.assertTrue(response.data["user"]["pending_invitation"])
        resent = self.client.post(self.url + response.data["id"] + "/resend-invitation/")
        self.assertEqual(resent.status_code, 202)
        self.assertTrue(resent.data["email_sent"])

    def test_stale_user_save_cannot_clear_independent_login_protection(self):
        self.account.set_password("IndependentPassword42!")
        self.account.save(update_fields=["password"])
        ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="viewer")
        self.account.first_name = "Updated"
        self.account.save()
        self.account.refresh_from_db()
        self.assertTrue(self.account.independent_login_required)

    def test_a_manager_cannot_deactivate_a_participant_shared_with_another_zev(self):
        other = create_managed_zev(name="Shared account")
        Participant.objects.create(zev=other, user=self.account, last_name="Shared", valid_from=self.today)
        response = self.client.post(self.url, {"email": self.account.email, "role": "viewer"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_active)

    def test_participant_api_key_is_retired_before_it_can_inherit_grants(self):
        client = APIClient()
        authenticate(client, self.account)
        response = client.post("/api/v1/auth/me/api-keys/", {"name": "participant key"}, format="json")
        self.assertEqual(response.status_code, 201)
        key = response.data["key"]
        self.participant.user = None
        self.participant.save(update_fields=["user"])
        self.account.set_password("IndependentPassword42!")
        self.account.save(update_fields=["password"])
        ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="manager")
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
        self.assertEqual(api.get(f"/api/v1/zev/participants/?zev={self.zev.pk}").status_code, 401)
        self.assertIsNotNone(ApiKey.objects.get(user=self.account).revoked_at)

    def test_key_creation_rechecks_a_session_authenticated_before_promotion(self):
        client = APIClient()
        authenticate(client, self.account)
        self.account.set_password("IndependentPassword42!")
        self.account.save(update_fields=["password"])

        def promote_before_key_lock():
            ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="viewer")
            return generate_key()

        with patch("accounts.views.generate_key", side_effect=promote_before_key_lock):
            response = client.post("/api/v1/auth/me/api-keys/", {"name": "late key"}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(ApiKey.objects.filter(user=self.account).exists())

    def sign_in_through_link(self, recovery_code=None):
        _url, token = get_participant_onboarding_link(self.participant)
        client = APIClient()
        response = client.post("/api/v1/public/onboarding/consume/", {
            "prefix": token.prefix, "s": token.secret,
        }, format="json")
        self.assertEqual(response.status_code, 200)
        if recovery_code is not None:
            self.complete_participant_mfa(client, response, recovery_code)
        self.assertTrue(is_participant_link_session(CookieJWTAuthentication().get_validated_token(
            client.cookies["openzev_access"].value,
        )))
        return client

    def test_participant_can_recover_a_forgotten_password_through_a_fresh_link(self):
        old_session = self.sign_in_through_link()
        self.assertEqual(old_session.post("/api/v1/auth/me/set-initial-password/", {
            "new_password": "ForgottenParticipantPassword42!",
        }, format="json").status_code, 200)
        recovered = self.sign_in_through_link()
        self.assertIsNotNone(recovered.get("/api/v1/auth/me/").data["password_recovery_expires_at"])
        self.assertEqual(recovered.post("/api/v1/auth/me/reset-password/", {
            "new_password": "RecoveredParticipantPassword42!",
        }, format="json").status_code, 200)
        self.assertEqual(old_session.get("/api/v1/auth/me/").status_code, 401)
        me = recovered.get("/api/v1/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertIsNone(me.data["password_recovery_expires_at"])
        self.account.refresh_from_db()
        self.assertTrue(self.account.password_from_participant_link)
        with self.assertRaises(ValidationError):
            ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="viewer")

    def test_credential_origin_alone_does_not_authorize_password_recovery(self):
        from accounts.jwt_utils import make_jwt_for_user

        self.account.set_password("ExistingPassword42!")
        self.account.save(update_fields=["password"])
        for session_origin, password_origin in ((True, False), (False, True), (True, True)):
            with self.subTest(session_origin=session_origin, password_origin=password_origin):
                self.account.password_from_participant_link = password_origin
                self.account.save(update_fields=["password_from_participant_link"])
                tokens = make_jwt_for_user(self.account, participant_link=session_origin)
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
                self.assertIsNone(client.get("/api/v1/auth/me/").data["password_recovery_expires_at"])
                response = client.post("/api/v1/auth/me/reset-password/", {
                    "new_password": "UnprovenReplacement42!",
                }, format="json")
                self.assertEqual(response.status_code, 403)
                self.account.refresh_from_db()
                self.assertTrue(self.account.check_password("ExistingPassword42!"))

    def test_a_password_enrolled_through_a_participant_link_requires_a_fresh_invitation(self):
        client = self.sign_in_through_link()
        password = "ParticipantOwnedPassword42!"
        self.assertEqual(client.post("/api/v1/auth/me/set-initial-password/", {
            "new_password": password,
        }, format="json").status_code, 200)
        self.account.refresh_from_db()
        self.assertTrue(self.account.password_from_participant_link)
        response = client.post("/api/v1/auth/me/email-change/", {
            "current_password": password, "new_email": "link-holder@example.com",
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "managed_email")
        with self.assertRaises(ValidationError):
            ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="viewer")
        self.assertTrue(self.account.check_password(password))
        self.invite()
        self.account.refresh_from_db()
        self.assertFalse(self.account.has_usable_password())
        self.assertFalse(self.account.is_active)
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 401)
        response = APIClient().post("/api/v1/auth/token/", {
            "username": self.account.username, "password": password,
        }, format="json")
        self.assertEqual(response.status_code, 401)
        invitation = self.account.email_verification_tokens.get(consumed_at__isnull=True)
        owner = APIClient()
        self.assertEqual(owner.post("/api/v1/auth/verify-email/", {"token": invitation.token}, format="json").status_code, 200)
        self.assertEqual(owner.post("/api/v1/auth/me/set-initial-password/", {
            "new_password": "FreshIndependentPassword42!",
        }, format="json").status_code, 200)
        self.account.refresh_from_db()
        self.assertFalse(self.account.password_from_participant_link)
        self.assertTrue(self.account.check_password("FreshIndependentPassword42!"))

    def test_password_login_refresh_and_changes_cannot_clear_participant_origin(self):
        client = self.sign_in_through_link()
        password = "ParticipantOwnedPassword42!"
        client.post("/api/v1/auth/me/set-initial-password/", {"new_password": password}, format="json")
        client = APIClient()
        self.assertEqual(client.post("/api/v1/auth/token/", {
            "username": self.account.username, "password": password,
        }, format="json").status_code, 200)
        self.assertEqual(client.post("/api/v1/auth/token/refresh/").status_code, 200)
        self.assertEqual(client.post("/api/v1/auth/me/change-password/", {
            "old_password": password, "new_password": "ChangedParticipantPassword42!",
        }, format="json").status_code, 200)
        self.account.refresh_from_db()
        self.assertTrue(self.account.password_from_participant_link)
        self.assertTrue(is_participant_link_session(CookieJWTAuthentication().get_validated_token(
            client.cookies["openzev_access"].value,
        )))
        with self.assertRaises(ValidationError):
            ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="manager")

    @override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()])
    def test_link_enrolled_totp_and_recovery_codes_are_removed_but_an_independent_password_survives(self):
        client = self.sign_in_through_link()
        self.account.set_password("IndependentPassword42!")
        self.account.save(update_fields=["password"])
        setup = client.post("/api/v1/auth/me/mfa/totp/")
        self.assertEqual(setup.status_code, 200)
        confirmed = client.post("/api/v1/auth/me/mfa/totp/confirm/", {
            "code": pyotp.TOTP(setup.data["secret"]).now(),
        }, format="json")
        self.assertEqual(confirmed.status_code, 200)
        self.assertTrue(self.account.mfa_recovery_codes.filter(from_participant_link=True).exists())
        ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="manager")
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password("IndependentPassword42!"))
        self.assertFalse(TotpDevice.objects.filter(user=self.account).exists())
        self.assertFalse(self.account.mfa_recovery_codes.exists())

    @override_settings(WEBAUTHN_RP_ID="localhost", WEBAUTHN_ORIGIN="http://localhost:5173")
    def test_link_enrolled_passkeys_and_their_descendants_are_removed_on_invitation(self):
        client = self.sign_in_through_link()
        authenticator = SoftAuthenticator()
        registered = register_passkey(client, authenticator)
        self.assertEqual(registered.status_code, 201)
        self.assertTrue(self.account.webauthn_credentials.get().from_participant_link)
        with self.assertRaises(ValidationError):
            ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="viewer")
        client = APIClient()
        self.assertEqual(sign_in_with(client, authenticator).status_code, 200)
        self.assertEqual(client.post("/api/v1/auth/me/set-initial-password/", {
            "new_password": "PasskeyDescendantPassword42!",
        }, format="json").status_code, 200)
        self.account.refresh_from_db()
        self.assertTrue(self.account.password_from_participant_link)
        self.invite()
        self.assertFalse(self.account.webauthn_credentials.exists())
        self.assertFalse(self.account.mfa_recovery_codes.exists())

    @override_settings(WEBAUTHN_RP_ID="localhost", WEBAUTHN_ORIGIN="http://localhost:5173")
    def test_independent_passkeys_survive_promotion_alongside_link_enrolled_credentials(self):
        participant_client = self.sign_in_through_link()
        self.assertEqual(register_passkey(participant_client, SoftAuthenticator()).status_code, 201)
        independent_client = APIClient()
        authenticate(independent_client, self.account)
        independent_key = SoftAuthenticator()
        self.assertEqual(register_passkey(independent_client, independent_key).status_code, 201)
        ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="manager")
        self.assertEqual(self.account.webauthn_credentials.count(), 1)
        self.assertFalse(self.account.webauthn_credentials.get().from_participant_link)
        self.assertEqual(sign_in_with(APIClient(), independent_key).status_code, 200)

    def complete_participant_mfa(self, client, challenge, code):
        self.assertEqual(challenge.status_code, 200)
        self.assertTrue(challenge.data["mfa_required"])
        completed = client.post("/api/v1/auth/token/mfa/", {
            "mfa_token": challenge.data["mfa_token"], "code": code,
        }, format="json")
        self.assertEqual(completed.status_code, 200)
        self.assertTrue(is_participant_link_session(CookieJWTAuthentication().get_validated_token(
            client.cookies["openzev_access"].value,
        )))

    @override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()])
    def test_participant_origin_survives_each_mfa_login_door(self):
        client = self.sign_in_through_link()
        password = "ParticipantOwnedPassword42!"
        self.assertEqual(client.post("/api/v1/auth/me/set-initial-password/", {
            "new_password": password,
        }, format="json").status_code, 200)
        setup = client.post("/api/v1/auth/me/mfa/totp/")
        codes = client.post("/api/v1/auth/me/mfa/totp/confirm/", {
            "code": pyotp.TOTP(setup.data["secret"]).now(),
        }, format="json").data["recovery_codes"]
        magic = issue(self.account)
        _url, token = get_participant_onboarding_link(self.participant)
        doors = [
            ("/api/v1/auth/token/", {"username": self.account.username, "password": password}),
            ("/api/v1/public/onboarding/consume/", {"prefix": token.prefix, "s": token.secret}),
            ("/api/v1/public/magic-link/consume/", {"token": magic.token}),
        ]
        for code, (url, data) in zip(codes, doors):
            with self.subTest(url=url):
                signed_in = APIClient()
                self.complete_participant_mfa(signed_in, signed_in.post(url, data, format="json"), code)

    @override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()])
    def test_link_regenerated_codes_are_retired_but_independent_totp_survives(self):
        independent = APIClient()
        authenticate(independent, self.account)
        setup = independent.post("/api/v1/auth/me/mfa/totp/")
        secret = setup.data["secret"]
        confirmed = independent.post("/api/v1/auth/me/mfa/totp/confirm/", {
            "code": pyotp.TOTP(secret).now(),
        }, format="json")
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(self.account.mfa_recovery_codes.filter(from_participant_link=False).count(), 10)
        participant = self.sign_in_through_link(confirmed.data["recovery_codes"][0])
        self.assertEqual(participant.post("/api/v1/auth/me/mfa/recovery-codes/").status_code, 200)
        self.assertEqual(self.account.mfa_recovery_codes.filter(from_participant_link=True).count(), 10)
        self.account.set_password("IndependentPassword42!")
        self.account.save(update_fields=["password"])
        ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="viewer")
        self.assertTrue(TotpDevice.objects.get(user=self.account).is_active)
        self.assertFalse(self.account.mfa_recovery_codes.exists())
        self.account.refresh_from_db()
        owner = APIClient()
        authenticate(owner, self.account)
        self.assertEqual(owner.post("/api/v1/auth/me/mfa/recovery-codes/").status_code, 200)
        self.assertEqual(self.account.mfa_recovery_codes.filter(from_participant_link=False).count(), 10)

    @override_settings(MFA_ENCRYPTION_KEYS=[Fernet.generate_key().decode()])
    def test_totp_origin_is_sticky_across_setup_and_confirmation_sessions(self):
        participant = self.sign_in_through_link()
        independent = APIClient()
        authenticate(independent, self.account)
        for setup_client, confirm_client in ((participant, independent), (independent, participant)):
            with self.subTest(participant_starts=setup_client is participant):
                setup = setup_client.post("/api/v1/auth/me/mfa/totp/")
                response = confirm_client.post("/api/v1/auth/me/mfa/totp/confirm/", {
                    "code": pyotp.TOTP(setup.data["secret"]).now(),
                }, format="json")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(TotpDevice.objects.get(user=self.account).from_participant_link)
                self.assertEqual(self.account.mfa_recovery_codes.filter(from_participant_link=True).count(), 10)
                TotpDevice.objects.filter(user=self.account).delete()
                self.account.mfa_recovery_codes.all().delete()

    def test_admin_promotion_does_not_restore_a_retired_password_from_its_loaded_instance(self):
        client = self.sign_in_through_link()
        client.post("/api/v1/auth/me/set-initial-password/", {
            "new_password": "ParticipantOwnedPassword42!",
        }, format="json")
        provider = OAuthProvider.objects.create(name="Verified provider", enabled=True)
        SocialAccount.objects.create(user=self.account, provider=provider, uid="verified-owner")
        SocialAccount.objects.create(user=self.account, provider=provider, uid="legacy-link-holder", from_participant_link=True)
        self.account.refresh_from_db()
        self.account.role = "admin"
        self.account.save()
        self.account.refresh_from_db()
        self.assertTrue(self.account.independent_login_required)
        self.assertFalse(self.account.has_usable_password())
        self.assertEqual(self.account.social_accounts.get().uid, "verified-owner")

    def test_stale_profile_save_does_not_restore_retired_password(self):
        client = self.sign_in_through_link()
        password = "ParticipantOwnedPassword42!"
        client.post("/api/v1/auth/me/set-initial-password/", {"new_password": password}, format="json")
        self.account.refresh_from_db()
        stale = User.objects.get(pk=self.account.pk)
        provider = OAuthProvider.objects.create(name="stale-profile-provider", enabled=True)
        SocialAccount.objects.create(user=self.account, provider=provider, uid="independent-owner")
        ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="manager")
        stale.first_name = "Late profile update"
        stale.save()
        signed_in = APIClient()
        self.account.refresh_from_db()
        self.assertFalse(self.account.has_usable_password())
        response = signed_in.post("/api/v1/auth/token/", {
            "username": self.account.username, "password": password,
        }, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("openzev_access", signed_in.cookies)
        self.assertEqual(signed_in.get("/api/v1/auth/me/").status_code, 401)
        self.assertEqual(signed_in.post("/api/v1/auth/token/refresh/").status_code, 401)

    def test_promotion_retires_an_outstanding_mfa_challenge(self):
        challenge = mfa.issue_challenge(self.account)
        self.account.set_password("IndependentPassword42!")
        self.account.save(update_fields=["password"])
        ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="viewer")
        with self.assertRaises(mfa.MfaChallengeError):
            mfa.resolve_challenge(challenge)

    def test_direct_grants_and_admin_forms_require_login_setup(self):
        with self.assertRaises(ValidationError):
            ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="viewer")
        request = RequestFactory().get("/admin/zev/zevaccessgrant/add/")
        request.user = self.manager
        form_class = site._registry[ZevAccessGrant].get_form(request)
        form = form_class(data={
            "zev": self.zev.pk, "user": self.account.pk, "role": "viewer", "valid_from": self.today,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("user", form.errors)
        self.account.refresh_from_db()
        self.assertFalse(self.account.independent_login_required)

    def test_foreign_manager_cannot_rotate_an_already_pending_invitation(self):
        self.invite()
        token = self.account.email_verification_tokens.get(consumed_at__isnull=True)
        other = create_managed_zev(name="Foreign pending", owner=self.manager)
        response = self.client.post(f"/api/v1/zev/zevs/{other.pk}/access/", {
            "email": self.account.email, "role": "viewer",
        }, format="json")
        self.assertEqual(response.status_code, 403)
        token.refresh_from_db()
        self.assertIsNone(token.consumed_at)
        self.assertFalse(ZevAccessGrant.objects.filter(zev=other, user=self.account).exists())

    def invitation_interleaving(self, action):
        original = _ZevAccessBase.grant_in
        first = True

        def lookup(view, zev, pk):
            nonlocal first
            grant = original(view, zev, pk)
            if first:
                first = False
                action(grant)
            return grant

        return patch.object(_ZevAccessBase, "grant_in", lookup)

    def accept(self, grant):
        token = grant.user.email_verification_tokens.get(consumed_at__isnull=True)
        response = APIClient().post("/api/v1/auth/verify-email/", {"token": token.token}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_acceptance_between_cancellation_lookup_and_lock_preserves_history(self):
        grant_id = self.invite()
        ZevAccessGrant.objects.filter(pk=grant_id).update(valid_from=self.today - timedelta(days=1))
        with self.invitation_interleaving(self.accept):
            response = self.client.delete(self.url + grant_id + "/")
        self.assertEqual(response.status_code, 204)
        self.assertTrue(ZevAccessGrant.objects.filter(pk=grant_id, valid_to=self.today - timedelta(days=1)).exists())

    def test_acceptance_between_resend_lookup_and_lock_refuses_a_new_token(self):
        grant_id = self.invite()
        with self.invitation_interleaving(self.accept):
            response = self.client.post(self.url + grant_id + "/resend-invitation/")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.account.email_verification_tokens.filter(consumed_at__isnull=True).exists())

    def test_cancellation_between_resend_lookup_and_lock_refuses_a_new_token(self):
        self.participant.delete()
        authenticate(self.client, make_user("resend_admin", "admin"))
        grant_id = self.invite()

        def cancel(grant):
            self.assertEqual(self.client.delete(self.url + str(grant.pk) + "/").status_code, 204)

        with self.invitation_interleaving(cancel):
            response = self.client.post(self.url + grant_id + "/resend-invitation/")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.account.email_verification_tokens.filter(consumed_at__isnull=True).exists())

    def test_cancelling_a_reinvitation_restores_a_protected_accounts_active_state(self):
        self.account.independent_login_required = True
        self.account.save(update_fields=["independent_login_required"])
        admin = make_user("reinvite_admin", "admin")
        authenticate(self.client, admin)
        grant_id = self.invite()
        token = self.account.email_verification_tokens.get(consumed_at__isnull=True)
        self.assertEqual(self.client.delete(self.url + grant_id + "/").status_code, 204)
        self.account.refresh_from_db()
        token.refresh_from_db()
        self.assertTrue(self.account.is_active)
        self.assertTrue(self.account.independent_login_required)
        self.assertIsNotNone(token.consumed_at)

    def test_admin_and_self_setup_protection_survives_demotion(self):
        for field, promoted, demoted in (("role", "admin", "user"), ("may_create_zev", True, False)):
            with self.subTest(field=field):
                account = make_user(f"demoted_{field}")
                setattr(account, field, promoted)
                account.save(update_fields=[field])
                setattr(account, field, demoted)
                account.save(update_fields=[field])
                account.refresh_from_db()
                self.assertTrue(account.independent_login_required)

    def test_passwordless_privilege_promotion_requires_login_setup(self):
        old_session = APIClient()
        authenticate(old_session, self.account)
        for field, value in (("role", "admin"), ("is_superuser", True), ("may_create_zev", True)):
            with self.subTest(field=field):
                setattr(self.account, field, value)
                with self.assertRaises(ValidationError) as caught:
                    self.account.save(update_fields=[field])
                self.assertIn(field, caught.exception.message_dict)
                self.account.refresh_from_db()
                self.assertFalse(self.account.independent_login_required)
                self.assertEqual(old_session.get("/api/v1/auth/me/").status_code, 200)

    def test_passwordless_admin_promotion_returns_api_and_form_errors(self):
        admin = make_user("privilege_admin", "admin")
        authenticate(self.client, admin)
        response = self.client.patch(
            f"/api/v1/auth/users/{self.account.pk}/", {"role": "admin"}, format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("role", response.data)
        request = RequestFactory().get(f"/admin/accounts/user/{self.account.pk}/change/")
        request.user = admin
        form_class = site._registry[User].get_form(request, obj=self.account)
        form = form_class(instance=self.account, data={
            "username": self.account.username, "email": self.account.email,
            "role": "admin", "is_active": True,
            "date_joined_0": self.account.date_joined.strftime("%Y-%m-%d"),
            "date_joined_1": self.account.date_joined.strftime("%H:%M:%S"),
        })
        self.assertFalse(form.is_valid())
        self.assertIn("role", form.errors)
        self.account.refresh_from_db()
        self.assertEqual(self.account.role, "user")
        self.assertFalse(self.account.independent_login_required)

    def test_party_account_selection_uses_the_state_under_the_party_lock(self):
        original_account = make_user("old_party_account")
        new_account = make_user("new_party_account")
        party = Party.objects.create(zev=self.zev, last_name="Relinking", user=original_account)
        select_for_update = Party.objects.select_for_update

        def relink_before_lock(*args, **kwargs):
            Party.objects.filter(pk=party.pk).update(user=new_account)
            return select_for_update(*args, **kwargs)

        with patch("zev.views_access.Party.objects.select_for_update", side_effect=relink_before_lock):
            response = self.client.post(self.url, {"party": str(party.pk), "role": "viewer"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(ZevAccessGrant.objects.filter(zev=self.zev, user=new_account).exists())
        self.assertFalse(ZevAccessGrant.objects.filter(zev=self.zev, user=original_account).exists())

    def test_onboarding_email_runs_after_the_service_transaction(self):
        outer_depth = len(connection.atomic_blocks)
        with patch("zev.emails.send_onboarding_email") as send:
            send.side_effect = lambda *_args: self.assertEqual(len(connection.atomic_blocks), outer_depth)
            send_participant_onboarding_link(self.participant, self.manager)
        send.assert_called_once()

    def test_access_validation_failure_rolls_back_pending_invitation_changes(self):
        with patch("zev.views_access.ZevAccessGrant.objects.create", side_effect=ValidationError("Login unavailable")):
            response = self.client.post(self.url, {"email": self.account.email, "role": "viewer"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_active)
        self.assertFalse(self.account.email_verification_tokens.exists())
        self.assertFalse(self.account.zev_grants.exists())

    def test_session_writes_refuse_a_request_authenticated_before_promotion(self):
        for index, (method, path, data) in enumerate((
            ("post", "sessions/revoke/", {}),
            ("post", "set-initial-password/", {"new_password": "LatePassword42!"}),
            ("post", "change-password/", {"old_password": "BeforePassword42!", "new_password": "LatePassword42!"}),
            ("post", "mfa/totp/", {}),
            ("delete", "mfa/totp/", {}),
            ("post", "mfa/totp/confirm/", {"code": "000000"}),
            ("post", "mfa/recovery-codes/", {}),
            ("post", "passkeys/register/complete/", {"credential": {}}),
            ("delete", f"passkeys/{uuid.uuid4()}/", {}),
        )):
            with self.subTest(method=method, path=path):
                participant = Participant.objects.create(
                    zev=self.zev, last_name="Late", email=f"late-{index}@example.com", valid_from=self.today,
                )
                account = ensure_participant_account(participant)
                provider = OAuthProvider.objects.create(name=f"late-{index}", enabled=True)
                SocialAccount.objects.create(user=account, provider=provider, uid="independent-login")
                if path == "change-password/":
                    account.set_password("BeforePassword42!")
                    account.save(update_fields=["password"])
                password = account.password
                client = APIClient()
                authenticate(client, account)
                original_authenticate = CookieJWTAuthentication.authenticate

                def promote_after_authentication(authenticator, request):
                    result = original_authenticate(authenticator, request)
                    if result is not None:
                        ZevAccessGrant.objects.create(zev=self.zev, user=account, role="manager")
                    return result

                with patch.object(CookieJWTAuthentication, "authenticate", promote_after_authentication):
                    response = getattr(client, method)(f"/api/v1/auth/me/{path}", data, format="json")
                self.assertEqual(response.status_code, 401, response.content)
                self.assertNotIn("openzev_access", response.cookies)
                account.refresh_from_db()
                self.assertEqual(account.password, password)
                self.assertEqual(account.session_version, 1)
                self.assertFalse(TotpDevice.objects.filter(user=account).exists())

    def test_participant_edit_rechecks_admin_rule_after_locking(self):
        provider = OAuthProvider.objects.create(name="edit-race", enabled=True)
        SocialAccount.objects.create(user=self.account, provider=provider, uid="independent-login")
        original_lock = lock_participant_account

        def promote_then_lock(participant):
            ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="viewer")
            return original_lock(participant)

        with patch("zev.serializers.lock_participant_account", side_effect=promote_then_lock):
            response = self.client.patch(
                f"/api/v1/zev/participants/{self.participant.pk}/", {"last_name": "Renamed"}, format="json",
            )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("user", response.data)
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.last_name, "Tenant")

    def test_concurrent_grant_for_the_same_account_is_refused_after_the_lock(self):
        other = make_user("concurrent_grantee")
        manager_class = type(User.objects)
        original_locked = manager_class.locked
        raced = []

        def grant_elsewhere_first(manager):
            if not raced:
                raced.append(True)
                ZevAccessGrant.objects.create(zev=self.zev, user=other, role="viewer")
            return original_locked(manager)

        with patch.object(manager_class, "locked", grant_elsewhere_first):
            response = self.client.post(self.url, {"email": other.email, "role": "viewer"}, format="json")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(ZevAccessGrant.objects.filter(zev=self.zev, user=other).count(), 1)

    def test_login_paths_use_supported_row_locks(self):
        with (
            patch.object(connection.features, "has_select_for_update", True),
            patch.object(connection.features, "has_select_for_no_key_update", False),
            patch.object(connection.ops, "for_update_sql", return_value=""),
        ):
            get_participant_onboarding_link(self.participant)
            token = issue(self.account)
            self.assertEqual(consume(token.token).pk, self.account.pk)
            authenticate(self.client, self.account)
            response = self.client.post("/api/v1/auth/me/api-keys/", {"name": "portable"}, format="json")
            self.assertEqual(response.status_code, 201, response.content)
            self.account.set_password("IndependentPassword42!")
            self.account.save(update_fields=["password"])
            grant = ZevAccessGrant.objects.create(zev=self.zev, user=self.account, role="viewer")
            access.revoke(grant)
            self.account.refresh_from_db()
            self.assertTrue(self.account.independent_login_required)

    def test_key_creation_refuses_an_account_deleted_after_authentication(self):
        client = APIClient()
        authenticate(client, self.account)

        def delete_before_key_lock():
            self.account.delete()
            return generate_key()

        with patch("accounts.views.generate_key", side_effect=delete_before_key_lock):
            response = client.post("/api/v1/auth/me/api-keys/", {"name": "deleted key"}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(ApiKey.objects.exists())
