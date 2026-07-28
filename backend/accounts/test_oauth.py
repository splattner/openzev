"""Coverage for the OAuth 2.0 / OIDC flows.

Before this module the OAuth block had three tests, all on
``oauth_token_exchange``. ``oauth_callback`` — the 100-line function that
validates CSRF state, talks to the provider, links accounts and auto-provisions
local users — had none, despite being the most security-sensitive code in the
project.

Provider HTTP is faked by patching ``urllib.request.urlopen``, which is what the
two provider helpers call.
"""

import io
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from testing.helpers import authenticate as auth, make_user

from .models import (
    OAuthExchangeCode,
    OAuthProvider,
    OAuthState,
    SocialAccount,
    User,
    UserRole,
)

FRONTEND = "http://localhost:5173"
PROVIDERS_PUBLIC = "/api/v1/auth/oauth/providers/"
PROVIDERS_CONFIG = "/api/v1/auth/oauth/providers/config/"
TOKEN_EXCHANGE = "/api/v1/auth/oauth/token-exchange/"
SOCIAL_ACCOUNTS = "/api/v1/auth/me/social-accounts/"


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_provider_http(*payloads):
    """Patch target returning ``payloads`` in order, one per urlopen() call."""
    responses = iter(payloads)

    def _urlopen(request, timeout=None):
        return _FakeResponse(json.dumps(next(responses)).encode())

    return patch("urllib.request.urlopen", _urlopen)


def make_provider(name="testidp", *, enabled=True) -> OAuthProvider:
    return OAuthProvider.objects.create(
        name=name,
        client_id="client-id",
        client_secret="super-secret",
        authorization_url="https://idp.example/authorize",
        token_url="https://idp.example/token",
        userinfo_url="https://idp.example/userinfo",
        redirect_url="https://app.example/callback",
        enabled=enabled,
    )


class OAuthTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.provider = make_provider()

    def callback(self, **params):
        return self.client.get(f"/api/v1/auth/oauth/callback/{self.provider.name}/", params)

    def start_state(self, state="state-token", *, user=None):
        return OAuthState.objects.create(state=state, provider=self.provider, user=user)


class ProviderListingTests(OAuthTestCase):
    def test_public_listing_never_exposes_client_credentials(self):
        """This endpoint is AllowAny and feeds the login page."""
        resp = self.client.get(PROVIDERS_PUBLIC)

        self.assertEqual(resp.status_code, 200)
        serialised = json.dumps(resp.data)
        self.assertNotIn("super-secret", serialised)
        self.assertNotIn("client_secret", serialised)
        self.assertNotIn("client_id", serialised)

    def test_public_listing_hides_disabled_providers(self):
        make_provider("disabled", enabled=False)

        resp = self.client.get(PROVIDERS_PUBLIC)

        self.assertEqual([p["name"] for p in resp.data], ["testidp"])

    def test_provider_config_is_admin_only(self):
        for role, expected in ((UserRole.ADMIN, 200), (UserRole.ZEV_OWNER, 403), (UserRole.PARTICIPANT, 403)):
            with self.subTest(role=role):
                auth(self.client, make_user(f"cfg_{role}", role))
                self.assertEqual(self.client.get(PROVIDERS_CONFIG).status_code, expected)

    def test_provider_config_rejects_anonymous(self):
        self.client.credentials()

        self.assertEqual(self.client.get(PROVIDERS_CONFIG).status_code, 401)


class InitiateTests(OAuthTestCase):
    def test_login_initiate_is_public_and_mints_a_state_token(self):
        resp = self.client.post(f"/api/v1/auth/oauth/login/{self.provider.name}/")

        self.assertEqual(resp.status_code, 200)
        state = OAuthState.objects.get()
        self.assertIsNone(state.user, "a login flow must not be bound to a user")
        self.assertIn(f"state={state.state}", resp.data["redirect_url"])
        self.assertTrue(resp.data["redirect_url"].startswith(self.provider.authorization_url))

    def test_link_initiate_binds_the_state_to_the_caller(self):
        user = make_user("linker", UserRole.PARTICIPANT)
        auth(self.client, user)

        resp = self.client.post(f"/api/v1/auth/oauth/link/{self.provider.name}/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(OAuthState.objects.get().user, user)

    def test_link_initiate_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.client.post(f"/api/v1/auth/oauth/link/{self.provider.name}/").status_code, 401)

    def test_unknown_or_disabled_provider_is_404(self):
        make_provider("switched-off", enabled=False)

        self.assertEqual(self.client.post("/api/v1/auth/oauth/login/nope/").status_code, 404)
        self.assertEqual(self.client.post("/api/v1/auth/oauth/login/switched-off/").status_code, 404)


class CallbackGuardTests(OAuthTestCase):
    def test_provider_error_never_reaches_the_redirect_target(self):
        """CWE-601: the provider's error value is attacker-influenced, so a
        fixed slug is used instead of echoing it."""
        resp = self.callback(error="evil&next=https://attacker.example")

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=provider_error")

    def test_missing_params_redirect(self):
        self.assertEqual(self.callback().url, f"{FRONTEND}/login?oauth_error=missing_params")

    def test_unknown_state_is_rejected(self):
        self.assertEqual(
            self.callback(code="c", state="never-issued").url,
            f"{FRONTEND}/login?oauth_error=invalid_state",
        )

    def test_state_from_a_different_provider_is_rejected(self):
        other = make_provider("other-idp")
        OAuthState.objects.create(state="cross", provider=other)

        self.assertEqual(self.callback(code="c", state="cross").url,
                         f"{FRONTEND}/login?oauth_error=invalid_state")

    def test_expired_state_is_rejected_and_consumed(self):
        state = self.start_state("stale")
        OAuthState.objects.filter(pk=state.pk).update(
            created_at=timezone.now() - timedelta(minutes=11))

        resp = self.callback(code="c", state="stale")

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=state_expired")
        self.assertFalse(OAuthState.objects.filter(pk=state.pk).exists())

    def test_state_is_single_use(self):
        self.start_state("once")
        with fake_provider_http({"access_token": "at"}, {"sub": "uid-1", "email": "a@example.com"}):
            first = self.callback(code="c", state="once")
        self.assertIn("/oauth/callback?code=", first.url)

        replayed = self.callback(code="c", state="once")

        self.assertEqual(replayed.url, f"{FRONTEND}/login?oauth_error=invalid_state")

    def test_provider_http_failure_is_not_leaked_to_the_browser(self):
        self.start_state("boom")

        def explode(request, timeout=None):
            raise OSError("connection refused to https://idp.example/token")

        with patch("urllib.request.urlopen", explode):
            resp = self.callback(code="c", state="boom")

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=token_exchange_failed")

    def test_profile_without_a_subject_is_rejected(self):
        self.start_state("nosub")
        with fake_provider_http({"access_token": "at"}, {"email": "a@example.com"}):
            resp = self.callback(code="c", state="nosub")

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=missing_uid")

    def test_profile_without_an_email_is_rejected_for_a_new_identity(self):
        self.start_state("noemail")
        with fake_provider_http({"access_token": "at"}, {"sub": "uid-x"}):
            resp = self.callback(code="c", state="noemail")

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=no_email")


class CallbackLoginTests(OAuthTestCase):
    def test_a_new_identity_is_auto_provisioned_as_a_participant(self):
        self.start_state("new")

        with fake_provider_http(
            {"access_token": "at"},
            {"sub": "uid-new", "email": "Fresh@Example.com", "given_name": "Fre", "family_name": "Sh"},
        ):
            resp = self.callback(code="c", state="new")

        user = User.objects.get(email="fresh@example.com")
        self.assertEqual(user.role, UserRole.PARTICIPANT, "auto-provisioned users get the lowest role")
        self.assertEqual(user.first_name, "Fre")
        self.assertFalse(user.has_usable_password())
        self.assertTrue(resp.url.startswith(f"{FRONTEND}/oauth/callback?code="))

    def test_a_known_identity_reuses_its_linked_user(self):
        existing = make_user("known", UserRole.ZEV_OWNER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-known", user=existing)
        self.start_state("known-state")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-known", "email": "other@example.com"}):
            self.callback(code="c", state="known-state")

        self.assertEqual(OAuthExchangeCode.objects.get().user, existing)
        self.assertEqual(User.objects.filter(email="other@example.com").count(), 0,
                         "the uid match wins; no second account is created")

    def test_an_inactive_user_cannot_log_in(self):
        user = make_user("dormant", UserRole.PARTICIPANT)
        User.objects.filter(pk=user.pk).update(is_active=False)
        SocialAccount.objects.create(provider=self.provider, uid="uid-dormant", user=user)
        self.start_state("dormant-state")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-dormant", "email": user.email}):
            resp = self.callback(code="c", state="dormant-state")

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=account_inactive")
        self.assertFalse(OAuthExchangeCode.objects.exists())


class CallbackEmailLinkingHazardTests(OAuthTestCase):
    """Documents — deliberately, not endorses — how an unknown provider identity
    is attached to an existing local account.

    A ``sub`` the system has never seen is matched to a local user purely on the
    email string the provider asserts. The provider's ``email_verified`` claim
    is not consulted, and the matched account may be an admin. These tests pin
    that behaviour so any change to it is visible; see the PR discussion for the
    proposed guard.
    """

    def test_an_unknown_identity_is_linked_to_an_existing_user_by_email_alone(self):
        victim = make_user("victim", UserRole.ADMIN)
        self.start_state("takeover")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-unknown", "email": victim.email}):
            resp = self.callback(code="c", state="takeover")

        self.assertEqual(SocialAccount.objects.get(uid="uid-unknown").user, victim)
        self.assertEqual(OAuthExchangeCode.objects.get().user, victim)
        self.assertTrue(resp.url.startswith(f"{FRONTEND}/oauth/callback?code="))

    def test_linking_happens_even_when_the_provider_says_the_email_is_unverified(self):
        victim = make_user("victim2", UserRole.ADMIN)
        self.start_state("unverified")

        with fake_provider_http(
            {"access_token": "at"},
            {"sub": "uid-unverified", "email": victim.email, "email_verified": False},
        ):
            self.callback(code="c", state="unverified")

        self.assertEqual(SocialAccount.objects.get(uid="uid-unverified").user, victim)

    def test_email_matching_is_case_insensitive(self):
        victim = make_user("victim3", UserRole.PARTICIPANT)
        self.start_state("case")

        with fake_provider_http(
            {"access_token": "at"}, {"sub": "uid-case", "email": victim.email.upper()},
        ):
            self.callback(code="c", state="case")

        self.assertEqual(SocialAccount.objects.get(uid="uid-case").user, victim)


class CallbackLinkFlowTests(OAuthTestCase):
    def test_linking_attaches_the_identity_to_the_state_owner(self):
        user = make_user("owner_link", UserRole.PARTICIPANT)
        self.start_state("link", user=user)

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-link", "email": "anything@example.com"}):
            resp = self.callback(code="c", state="link")

        self.assertEqual(resp.url, f"{FRONTEND}/account?oauth_linked=true")
        self.assertEqual(SocialAccount.objects.get(uid="uid-link").user, user)
        self.assertFalse(OAuthExchangeCode.objects.exists(), "linking must not mint a session")

    def test_an_identity_already_linked_elsewhere_is_refused(self):
        holder = make_user("holder", UserRole.PARTICIPANT)
        SocialAccount.objects.create(provider=self.provider, uid="uid-taken", user=holder)
        other = make_user("other_link", UserRole.PARTICIPANT)
        self.start_state("link-taken", user=other)

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-taken", "email": "x@example.com"}):
            resp = self.callback(code="c", state="link-taken")

        self.assertEqual(resp.url, f"{FRONTEND}/account?oauth_error=already_linked_other")
        self.assertEqual(SocialAccount.objects.get(uid="uid-taken").user, holder)

    def test_relinking_the_same_identity_to_the_same_user_is_idempotent(self):
        user = make_user("relink", UserRole.PARTICIPANT)
        SocialAccount.objects.create(provider=self.provider, uid="uid-same", user=user)
        self.start_state("relink-state", user=user)

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-same", "email": user.email}):
            resp = self.callback(code="c", state="relink-state")

        self.assertEqual(resp.url, f"{FRONTEND}/account?oauth_linked=true")
        self.assertEqual(SocialAccount.objects.filter(uid="uid-same").count(), 1)


class SocialAccountTests(OAuthTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user("sa_user", UserRole.PARTICIPANT)
        self.other = make_user("sa_other", UserRole.PARTICIPANT)
        self.mine = SocialAccount.objects.create(provider=self.provider, uid="mine", user=self.user)
        self.theirs = SocialAccount.objects.create(provider=self.provider, uid="theirs", user=self.other)

    def test_listing_shows_only_the_callers_own_accounts(self):
        auth(self.client, self.user)

        resp = self.client.get(SOCIAL_ACCOUNTS)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual([a["id"] for a in resp.data], [self.mine.pk])

    def test_a_caller_can_unlink_their_own_account(self):
        auth(self.client, self.user)

        resp = self.client.delete(f"{SOCIAL_ACCOUNTS}{self.mine.pk}/")

        self.assertEqual(resp.status_code, 204)
        self.assertFalse(SocialAccount.objects.filter(pk=self.mine.pk).exists())

    def test_a_caller_cannot_unlink_somebody_elses(self):
        auth(self.client, self.user)

        resp = self.client.delete(f"{SOCIAL_ACCOUNTS}{self.theirs.pk}/")

        self.assertEqual(resp.status_code, 404)
        self.assertTrue(SocialAccount.objects.filter(pk=self.theirs.pk).exists())

    def test_anonymous_callers_are_refused(self):
        self.client.credentials()

        self.assertEqual(self.client.get(SOCIAL_ACCOUNTS).status_code, 401)
