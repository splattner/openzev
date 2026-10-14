"""Coverage for the OAuth 2.0 / OIDC flows.

Before this module the OAuth block had three tests, all on
``oauth_token_exchange``. ``oauth_callback`` — the 100-line function that
validates CSRF state, talks to the provider, links accounts and auto-provisions
local users — had none, despite being the most security-sensitive code in the
project.

Provider HTTP is faked at the opener's transport boundary; public DNS is
faked separately so the address guard still runs.
"""

import io
import json
import socket
import urllib.error
import urllib.request
import urllib.response
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditActionCategory, AuditEvent, AuditEventStatus
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
SOCIAL_ACCOUNTS = "/api/v1/auth/me/social-accounts/"


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


@contextmanager
def fake_provider_http(*payloads):
    """Return ``payloads`` in order, one per opener.open() call."""
    responses = iter(payloads)

    def _open(opener, request, data=None, timeout=None):
        return _FakeResponse(json.dumps(next(responses)).encode())

    with (
        patch("urllib.request.OpenerDirector.open", _open),
        patch("config.net.socket.getaddrinfo", return_value=PUBLIC_DNS),
    ):
        yield


def make_provider(name="testidp", *, enabled=True, **overrides) -> OAuthProvider:
    return OAuthProvider.objects.create(
        name=name,
        client_id="client-id",
        client_secret="super-secret",
        authorization_url="https://idp.example/authorize",
        token_url="https://idp.example/token",
        userinfo_url="https://idp.example/userinfo",
        redirect_url="https://app.example/callback",
        enabled=enabled,
        **overrides,
    )


class OAuthEndpointSafetyTests(SimpleTestCase):
    def setUp(self):
        self.provider = OAuthProvider(
            token_url="https://idp.example/token", userinfo_url="https://idp.example/userinfo",
            client_id="client", client_secret="secret",
        )

    def _call(self, endpoint):
        from .views_oauth import _exchange_code_for_tokens, _fetch_user_info

        if endpoint == "token_url":
            return _exchange_code_for_tokens(self.provider, "code", "https://app.example/callback")
        return _fetch_user_info(self.provider, "access-token")

    @override_settings(OAUTH_ALLOW_PRIVATE_HOSTS=False)
    def test_private_endpoints_are_refused_before_any_request(self):
        for endpoint in ("token_url", "userinfo_url"):
            with self.subTest(endpoint=endpoint), patch("urllib.request.OpenerDirector.open") as transport:
                setattr(self.provider, endpoint, "https://127.0.0.1/endpoint")
                with self.assertRaises(ValueError):
                    self._call(endpoint)
                transport.assert_not_called()

    @override_settings(OAUTH_ALLOW_PRIVATE_HOSTS=True)
    def test_private_endpoints_are_reachable_when_the_operator_opts_in(self):
        self.provider.token_url = "https://127.0.0.1/token"
        with patch("urllib.request.OpenerDirector.open", return_value=_FakeResponse(b'{"access_token": "t"}')):
            self.assertEqual(self._call("token_url"), {"access_token": "t"})

    @override_settings(DEBUG=False)
    def test_http_endpoints_are_refused_in_production_before_any_request(self):
        for endpoint in ("token_url", "userinfo_url"):
            with self.subTest(endpoint=endpoint), patch("urllib.request.OpenerDirector.open") as transport:
                setattr(self.provider, endpoint, "http://idp.example/endpoint")
                with self.assertRaises(ValueError):
                    self._call(endpoint)
                transport.assert_not_called()

    def test_redirects_do_not_send_a_second_request_or_forward_credentials(self):
        for endpoint in ("token_url", "userinfo_url"):
            with self.subTest(endpoint=endpoint):
                response = urllib.response.addinfourl(
                    io.BytesIO(), {"Location": "https://127.0.0.1/private"}, getattr(self.provider, endpoint), code=302,
                )
                response.msg = "Redirect"
                with (
                    patch("config.net.socket.getaddrinfo", return_value=PUBLIC_DNS),
                    patch("urllib.request.OpenerDirector._open", return_value=response) as transport,
                ):
                    with self.assertRaises(urllib.error.HTTPError):
                        self._call(endpoint)
                    transport.assert_called_once()

    def test_non_object_json_is_refused(self):
        for endpoint in ("token_url", "userinfo_url"):
            for value in ([], None, "profile", 42):
                with self.subTest(endpoint=endpoint, value=value), fake_provider_http(value):
                    with self.assertRaisesRegex(ValueError, "JSON object"):
                        self._call(endpoint)

    def test_response_size_is_bounded(self):
        from .views_oauth import MAX_OAUTH_RESPONSE_BYTES

        for endpoint in ("token_url", "userinfo_url"):
            response = _FakeResponse(b" " * (MAX_OAUTH_RESPONSE_BYTES + 100))
            with (
                self.subTest(endpoint=endpoint),
                patch("config.net.socket.getaddrinfo", return_value=PUBLIC_DNS),
                patch("urllib.request.OpenerDirector.open", return_value=response),
                patch.object(response, "read", wraps=response.read) as read,
            ):
                with self.assertRaisesRegex(ValueError, "size limit"):
                    self._call(endpoint)
                read.assert_called_once_with(MAX_OAUTH_RESPONSE_BYTES + 1)


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
        for role, expected in ((UserRole.ADMIN, 200), (UserRole.USER, 403)):
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
        user = make_user("linker", UserRole.USER)
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
    def test_invalid_access_tokens_are_refused_before_userinfo(self):
        for data in ({}, *({"access_token": value} for value in (None, [], {}, 123, True, "", "   "))):
            self.start_state()
            with (
                self.subTest(data=data),
                fake_provider_http(data),
                patch("accounts.views_oauth._fetch_user_info") as fetch,
            ):
                response = self.callback(code="c", state="state-token")
            self.assertEqual(response.url, f"{FRONTEND}/login?oauth_error=token_exchange_failed")
            fetch.assert_not_called()
        self.assertFalse(User.objects.exists())

    def test_malformed_profile_fields_are_controlled_errors(self):
        invalid = [
            {"sub": value} for value in ([], {}, 123, True, "x" * 501, "   ")
        ] + [
            {"sub": None, "id": value} for value in ([], {}, True, 1.5, "x" * 501)
        ] + [
            {"email": value} for value in ([], {}, 123, True, "invalid", "x" * 255)
        ] + [
            {claim: value} for claim in ("given_name", "family_name")
            for value in ([], {}, 123, "x" * 151)
        ]
        for fields in invalid:
            self.start_state()
            info = {"sub": "uid", "email": "person@example.com", "email_verified": True, **fields}
            with self.subTest(fields=fields), fake_provider_http({"access_token": "at"}, info):
                response = self.callback(code="c", state="state-token")
            self.assertEqual(response.url, f"{FRONTEND}/login?oauth_error=token_exchange_failed")
            self.assertFalse(User.objects.exists())
            self.assertFalse(SocialAccount.objects.exists())

    def test_profile_limits_and_numeric_ids_are_accepted(self):
        email = "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 61
        profiles = (
            {"sub": "u" * 500, "email": email, "given_name": "f" * 150, "family_name": "l" * 150},
            {"id": 123, "email": "numeric@example.com", "given_name": None, "family_name": None},
        )
        for info in profiles:
            self.start_state()
            with self.subTest(profile=info), fake_provider_http({"access_token": "at"}, {**info, "email_verified": True}):
                response = self.callback(code="c", state="state-token")
            self.assertTrue(response.url.startswith(f"{FRONTEND}/oauth/callback?code="))
            account = SocialAccount.objects.get(uid=str(info.get("sub") or info["id"]))
            self.assertEqual(account.user.first_name, info["given_name"] or "")
            self.assertEqual(account.user.last_name, info["family_name"] or "")

    def test_non_object_token_and_userinfo_responses_are_controlled_errors(self):
        for payloads in (([],), ({"access_token": "t"}, [])):
            self.start_state()
            with self.subTest(payloads=payloads), fake_provider_http(*payloads):
                response = self.callback(code="c", state="state-token")
            self.assertEqual(response.url, f"{FRONTEND}/login?oauth_error=token_exchange_failed")
        self.assertFalse(SocialAccount.objects.exists())

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
        with fake_provider_http({"access_token": "at"}, {"sub": "uid-1", "email": "a@example.com", "email_verified": True}):
            first = self.callback(code="c", state="once")
        self.assertIn("/oauth/callback?code=", first.url)

        replayed = self.callback(code="c", state="once")

        self.assertEqual(replayed.url, f"{FRONTEND}/login?oauth_error=invalid_state")

    def test_provider_http_failure_is_not_leaked_to_the_browser(self):
        self.start_state("boom")

        with (
            patch("config.net.socket.getaddrinfo", return_value=PUBLIC_DNS),
            patch("urllib.request.OpenerDirector.open", side_effect=OSError("connection refused to https://idp.example/token")) as transport,
        ):
            resp = self.callback(code="c", state="boom")
            transport.assert_called_once()

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
            {"sub": "uid-new", "email": "Fresh@Example.com", "email_verified": True, "given_name": "Fre", "family_name": "Sh"},
        ):
            resp = self.callback(code="c", state="new")

        user = User.objects.get(email="fresh@example.com")
        self.assertEqual(user.role, UserRole.USER, "auto-provisioned users get the lowest role")
        self.assertEqual(user.first_name, "Fre")
        self.assertFalse(user.has_usable_password())
        self.assertTrue(resp.url.startswith(f"{FRONTEND}/oauth/callback?code="))

    def test_a_known_identity_reuses_its_linked_user(self):
        existing = make_user("known", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-known", user=existing)
        self.start_state("known-state")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-known", "email": "other@example.com"}):
            self.callback(code="c", state="known-state")

        self.assertEqual(OAuthExchangeCode.objects.get().user, existing)
        self.assertEqual(User.objects.filter(email="other@example.com").count(), 0,
                         "the uid match wins; no second account is created")

    def test_a_known_identity_can_log_in_without_email(self):
        user = make_user("known_no_email", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-known", user=user)
        self.start_state()
        with fake_provider_http({"access_token": "at"}, {"sub": "uid-known"}):
            response = self.callback(code="c", state="state-token")
        self.assertTrue(response.url.startswith(f"{FRONTEND}/oauth/callback?code="))
        self.assertEqual(OAuthExchangeCode.objects.get().user, user)

    def test_an_inactive_user_cannot_log_in(self):
        user = make_user("dormant", UserRole.USER)
        User.objects.filter(pk=user.pk).update(is_active=False)
        SocialAccount.objects.create(provider=self.provider, uid="uid-dormant", user=user)
        self.start_state("dormant-state")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-dormant", "email": user.email}):
            resp = self.callback(code="c", state="dormant-state")

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=account_inactive")
        self.assertFalse(OAuthExchangeCode.objects.exists())


class CallbackExistingAccountTests(OAuthTestCase):
    """Taking over an existing local account requires a verified email.

    An unrecognised ``sub`` matched to a local user by email inherits that
    user's role, so anyone able to register the address at a configured
    provider could otherwise claim the account. The provider has to vouch for
    the address before that link is made.
    """

    def _attempt(self, state, victim, **extra_claims):
        self.start_state(state)
        with fake_provider_http(
            {"access_token": "at"},
            {"sub": f"uid-{state}", "email": victim.email, **extra_claims},
        ):
            return self.callback(code="c", state=state)

    def test_a_verified_email_links_to_the_existing_account(self):
        user = make_user("verified_owner", UserRole.USER)

        resp = self._attempt("verified", user, email_verified=True)

        self.assertEqual(SocialAccount.objects.get(uid="uid-verified").user, user)
        self.assertEqual(OAuthExchangeCode.objects.get().user, user)
        self.assertTrue(resp.url.startswith(f"{FRONTEND}/oauth/callback?code="))

    def test_an_absent_email_verified_claim_is_refused(self):
        """Most of the real risk: a provider that simply omits the claim."""
        victim = make_user("victim_absent", UserRole.ADMIN)

        resp = self._attempt("absent", victim)

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=email_not_verified")
        self.assertFalse(SocialAccount.objects.exists())
        self.assertFalse(OAuthExchangeCode.objects.exists(), "no session may be issued")

    def test_an_explicitly_unverified_email_is_refused(self):
        victim = make_user("victim_false", UserRole.ADMIN)

        resp = self._attempt("false", victim, email_verified=False)

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=email_not_verified")
        self.assertFalse(SocialAccount.objects.exists())

    def test_a_truthy_but_non_true_claim_is_refused(self):
        """`"false"` and `0` are both truthy/falsy traps; only a real True passes."""
        victim = make_user("victim_str", UserRole.ADMIN)

        resp = self._attempt("stringy", victim, email_verified="false")

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=email_not_verified")
        self.assertFalse(SocialAccount.objects.exists())

    def test_a_refusal_is_audited_against_the_targeted_account(self):
        victim = make_user("victim_audit", UserRole.ADMIN)

        self._attempt("audited", victim, email_verified=False)

        event = AuditEvent.objects.get()
        self.assertEqual(event.action_category, AuditActionCategory.AUTH)
        self.assertEqual(event.action_type, "oauth.link_refused")
        self.assertEqual(event.status, AuditEventStatus.DENIED)
        self.assertEqual(event.target_id, str(victim.pk))
        self.assertEqual(event.metadata_json["provider"], self.provider.name)

    def test_provisioning_a_brand_new_account_requires_verified_email(self):
        self.start_state("brandnew")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-brandnew", "email": "nobody@example.com"}):
            resp = self.callback(code="c", state="brandnew")

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=email_not_verified")
        self.assertFalse(User.objects.filter(email="nobody@example.com").exists())
        self.assertTrue(AuditEvent.objects.filter(action_type="oauth.provision_refused").exists())

    def test_the_audited_claim_value_is_bounded(self):
        self.start_state("bounded")
        claim = {"x": "y" * 500}

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-b", "email": "b@example.com", "email_verified": claim}):
            self.callback(code="c", state="bounded")

        recorded = AuditEvent.objects.get(action_type="oauth.provision_refused").metadata_json["email_verified"]
        self.assertIsInstance(recorded, str)
        self.assertLessEqual(len(recorded), 32)

    def test_provider_can_opt_in_to_missing_email_verified_claim(self):
        self.provider.trust_missing_email_verified = True
        self.provider.save(update_fields=["trust_missing_email_verified"])
        self.start_state("trusted")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-trusted", "email": "trusted@example.com"}):
            resp = self.callback(code="c", state="trusted")

        self.assertTrue(resp.url.startswith(f"{FRONTEND}/oauth/callback?code="))
        self.assertEqual(User.objects.get(email="trusted@example.com").role, UserRole.USER)

    def test_provisioning_rejects_unverified_and_non_boolean_claims_even_when_trusted(self):
        for trusted in (False, True):
            self.provider.trust_missing_email_verified = trusted
            self.provider.save(update_fields=["trust_missing_email_verified"])
            for claim in (False, None, "true", 1):
                with self.subTest(trusted=trusted, claim=claim):
                    self.start_state("unverified")
                    with fake_provider_http(
                        {"access_token": "at"},
                        {"sub": "uid-unverified", "email": "unverified@example.com", "email_verified": claim},
                    ):
                        resp = self.callback(code="c", state="unverified")
                    self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=email_not_verified")
                    self.assertFalse(User.objects.filter(email="unverified@example.com").exists())
                    self.assertFalse(SocialAccount.objects.filter(uid="uid-unverified").exists())

    def test_trust_exception_cannot_inherit_an_existing_account(self):
        self.provider.trust_missing_email_verified = True
        self.provider.save(update_fields=["trust_missing_email_verified"])
        victim = make_user("trusted_victim", UserRole.ADMIN)
        resp = self._attempt("trusted-existing", victim)
        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=email_not_verified")
        self.assertFalse(SocialAccount.objects.filter(user=victim).exists())

    def test_a_previously_linked_identity_is_unaffected(self):
        """Once the link exists, the uid match short-circuits before any email
        handling — so an established login does not start failing."""
        user = make_user("already_linked", UserRole.ADMIN)
        SocialAccount.objects.create(provider=self.provider, uid="uid-established", user=user)
        self.start_state("established")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-established", "email": user.email}):
            resp = self.callback(code="c", state="established")

        self.assertTrue(resp.url.startswith(f"{FRONTEND}/oauth/callback?code="))
        self.assertEqual(OAuthExchangeCode.objects.get().user, user)

    def test_email_matching_is_case_insensitive(self):
        user = make_user("case_user", UserRole.USER)
        self.start_state("case")

        with fake_provider_http(
            {"access_token": "at"},
            {"sub": "uid-case", "email": user.email.upper(), "email_verified": True},
        ):
            self.callback(code="c", state="case")

        self.assertEqual(SocialAccount.objects.get(uid="uid-case").user, user)


class CallbackLinkFlowTests(OAuthTestCase):
    def test_linking_attaches_the_identity_to_the_state_owner(self):
        user = make_user("owner_link", UserRole.USER)
        self.start_state("link", user=user)

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-link", "email": "anything@example.com"}):
            resp = self.callback(code="c", state="link")

        self.assertEqual(resp.url, f"{FRONTEND}/account?oauth_linked=true")
        self.assertEqual(SocialAccount.objects.get(uid="uid-link").user, user)
        self.assertFalse(OAuthExchangeCode.objects.exists(), "linking must not mint a session")

    def test_an_identity_already_linked_elsewhere_is_refused(self):
        holder = make_user("holder", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-taken", user=holder)
        other = make_user("other_link", UserRole.USER)
        self.start_state("link-taken", user=other)

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-taken", "email": "x@example.com"}):
            resp = self.callback(code="c", state="link-taken")

        self.assertEqual(resp.url, f"{FRONTEND}/account?oauth_error=already_linked_other")
        self.assertEqual(SocialAccount.objects.get(uid="uid-taken").user, holder)

    def test_relinking_the_same_identity_to_the_same_user_is_idempotent(self):
        user = make_user("relink", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-same", user=user)
        self.start_state("relink-state", user=user)

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-same", "email": user.email}):
            resp = self.callback(code="c", state="relink-state")

        self.assertEqual(resp.url, f"{FRONTEND}/account?oauth_linked=true")
        self.assertEqual(SocialAccount.objects.filter(uid="uid-same").count(), 1)


class SocialAccountTests(OAuthTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user("sa_user", UserRole.USER)
        self.other = make_user("sa_other", UserRole.USER)
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


class ProviderConfigAuditTests(OAuthTestCase):
    """Provider configuration is the highest-leverage thing an admin can change
    here: repointing token_url or userinfo_url redirects authentication itself.
    It is audited under GOVERNANCE, like the other admin-only config endpoints.
    """

    def setUp(self):
        super().setUp()
        auth(self.client, make_user("prov_admin", UserRole.ADMIN))

    def _payload(self, **overrides):
        payload = {
            "name": "newidp",
            "display_name": "New IdP",
            "client_id": "new-client",
            "client_secret": "new-secret",
            "authorization_url": "https://new.example/authorize",
            "token_url": "https://new.example/token",
            "userinfo_url": "https://new.example/userinfo",
            "redirect_url": "https://app.example/callback",
            "scope": "openid email",
            "enabled": True,
        }
        payload.update(overrides)
        return payload

    def test_creating_a_provider_is_audited(self):
        resp = self.client.post(PROVIDERS_CONFIG, self._payload(), format="json")

        self.assertEqual(resp.status_code, 201)
        event = AuditEvent.objects.get(action_type="oauth_provider.create")
        self.assertEqual(event.action_category, AuditActionCategory.GOVERNANCE)
        self.assertEqual(event.target_display, "newidp")
        self.assertEqual(event.changes_json["token_url"]["after"], "https://new.example/token")

    def test_a_created_providers_secret_is_never_stored_in_the_event(self):
        self.client.post(PROVIDERS_CONFIG, self._payload(), format="json")

        event = AuditEvent.objects.get(action_type="oauth_provider.create")
        self.assertNotIn("new-secret", json.dumps(event.changes_json))
        self.assertNotIn("new-secret", json.dumps(event.metadata_json))

    def test_repointing_the_token_url_shows_before_and_after(self):
        url = f"{PROVIDERS_CONFIG}{self.provider.pk}/"

        resp = self.client.patch(url, {"token_url": "https://attacker.example/token"}, format="json")

        self.assertEqual(resp.status_code, 200)
        event = AuditEvent.objects.get(action_type="oauth_provider.update")
        self.assertEqual(
            event.changes_json["token_url"],
            {"before": "https://idp.example/token", "after": "https://attacker.example/token"},
        )

    def test_trusted_missing_claim_policy_is_admin_only_and_audited(self):
        url = f"{PROVIDERS_CONFIG}{self.provider.pk}/"
        auth(self.client, make_user("trust_non_admin", UserRole.USER))
        denied = self.client.patch(url, {"trust_missing_email_verified": True}, format="json")
        self.assertEqual(denied.status_code, 403)
        self.provider.refresh_from_db()
        self.assertFalse(self.provider.trust_missing_email_verified)

        auth(self.client, make_user("trust_admin", UserRole.ADMIN))
        response = self.client.patch(url, {"trust_missing_email_verified": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["trust_missing_email_verified"])
        event = AuditEvent.objects.get(action_type="oauth_provider.update")
        self.assertEqual(event.changes_json["trust_missing_email_verified"], {"before": False, "after": True})

    def test_a_secret_rotation_is_recorded_as_a_flag_not_a_value(self):
        """The secret must not reach the audit trail, but rotating it is
        exactly the kind of change worth being able to see after the fact."""
        url = f"{PROVIDERS_CONFIG}{self.provider.pk}/"

        self.client.patch(url, {"client_secret": "rotated-secret"}, format="json")

        event = AuditEvent.objects.get(action_type="oauth_provider.update")
        self.assertTrue(event.metadata_json["client_secret_rotated"])
        self.assertNotIn("rotated-secret", json.dumps(event.metadata_json))
        self.assertNotIn("rotated-secret", json.dumps(event.changes_json))

    def test_an_unrelated_edit_does_not_claim_the_secret_rotated(self):
        url = f"{PROVIDERS_CONFIG}{self.provider.pk}/"

        self.client.patch(url, {"scope": "openid"}, format="json")

        self.assertFalse(AuditEvent.objects.get(action_type="oauth_provider.update")
                         .metadata_json["client_secret_rotated"])

    def test_deleting_a_provider_records_how_many_links_it_took_with_it(self):
        user = make_user("linked_to_doomed", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="doomed", user=user)

        resp = self.client.delete(f"{PROVIDERS_CONFIG}{self.provider.pk}/")

        self.assertEqual(resp.status_code, 204)
        event = AuditEvent.objects.get(action_type="oauth_provider.delete")
        self.assertEqual(event.action_category, AuditActionCategory.GOVERNANCE)
        self.assertEqual(event.target_display, "testidp")
        self.assertEqual(event.metadata_json["unlinked_social_accounts"], 1)


class OAuthFlowAuditTests(OAuthTestCase):
    def _event(self, action_type):
        return AuditEvent.objects.get(action_type=action_type)

    def test_a_successful_login_is_audited(self):
        user = make_user("audit_login", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-login", user=user)
        self.start_state("s")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-login", "email": user.email}):
            self.callback(code="c", state="s")

        event = self._event("oauth.login")
        self.assertEqual(event.action_category, AuditActionCategory.AUTH)
        self.assertEqual(event.status, AuditEventStatus.SUCCESS)
        self.assertEqual(event.target_id, str(user.pk))
        self.assertEqual(event.metadata_json["provider"], "testidp")

    def test_provisioning_a_new_account_is_audited_separately_from_the_login(self):
        """Account creation deserves its own event — it is the moment a new
        principal appears, not just a session."""
        self.start_state("s")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-p", "email": "brand@example.com", "email_verified": True}):
            self.callback(code="c", state="s")

        provision = self._event("oauth.provision")
        self.assertEqual(provision.metadata_json["role"], UserRole.USER)
        self.assertEqual(provision.target_display, "brand@example.com")
        self.assertTrue(AuditEvent.objects.filter(action_type="oauth.login").exists())

    def test_claiming_an_existing_account_with_a_verified_email_is_audited_as_a_link(self):
        user = make_user("audit_claim", UserRole.USER)
        self.start_state("s")

        with fake_provider_http(
            {"access_token": "at"},
            {"sub": "uid-claim", "email": user.email, "email_verified": True},
        ):
            self.callback(code="c", state="s")

        self.assertEqual(self._event("oauth.link").metadata_json["matched_by"], "verified_email")

    def test_an_invalid_state_is_audited_as_a_failure(self):
        """The clearest CSRF/replay signal the flow produces."""
        self.callback(code="c", state="forged")

        event = self._event("oauth.login_failed")
        self.assertEqual(event.status, AuditEventStatus.FAILED)
        self.assertEqual(event.metadata_json["reason"], "invalid_state")

    def test_an_inactive_account_is_audited_against_that_account(self):
        user = make_user("audit_inactive", UserRole.USER)
        User.objects.filter(pk=user.pk).update(is_active=False)
        SocialAccount.objects.create(provider=self.provider, uid="uid-inactive", user=user)
        self.start_state("s")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-inactive", "email": user.email}):
            self.callback(code="c", state="s")

        event = self._event("oauth.login_failed")
        self.assertEqual(event.status, AuditEventStatus.DENIED)
        self.assertEqual(event.target_id, str(user.pk))
        self.assertEqual(event.metadata_json["reason"], "account_inactive")

    def test_a_token_exchange_failure_is_audited(self):
        self.start_state("s")

        with (
            patch("config.net.socket.getaddrinfo", return_value=PUBLIC_DNS),
            patch("urllib.request.OpenerDirector.open", side_effect=OSError("boom")) as transport,
        ):
            self.callback(code="c", state="s")
            transport.assert_called_once()

        self.assertEqual(self._event("oauth.login_failed").metadata_json["reason"],
                         "token_exchange_failed")

    def test_normal_user_cancellation_is_not_audited(self):
        """Declining consent at the provider, and bare GETs from crawlers, are
        ordinary traffic — auditing them would bury the real signals."""
        self.callback(error="access_denied")
        self.callback()

        self.assertFalse(AuditEvent.objects.exists())

    def test_linking_and_unlinking_are_audited(self):
        user = make_user("audit_link", UserRole.USER)
        self.start_state("s", user=user)
        with fake_provider_http({"access_token": "at"}, {"sub": "uid-l", "email": user.email}):
            self.callback(code="c", state="s")
        self.assertEqual(self._event("oauth.link").target_id, str(user.pk))

        auth(self.client, user)
        account = SocialAccount.objects.get(uid="uid-l")
        self.client.delete(f"{SOCIAL_ACCOUNTS}{account.pk}/")

        unlink = self._event("oauth.unlink")
        self.assertEqual(unlink.target_id, str(user.pk))
        self.assertEqual(unlink.metadata_json["provider"], "testidp")

    def test_linking_an_identity_owned_by_someone_else_is_audited_as_denied(self):
        holder = make_user("audit_holder", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-held", user=holder)
        claimer = make_user("audit_claimer", UserRole.USER)
        self.start_state("s", user=claimer)

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-held", "email": claimer.email}):
            self.callback(code="c", state="s")

        event = self._event("oauth.link_refused")
        self.assertEqual(event.status, AuditEventStatus.DENIED)
        self.assertEqual(event.target_id, str(claimer.pk))
        self.assertEqual(event.metadata_json["reason"], "already_linked_other")


class OAuthMfaClaimTests(OAuthTestCase):
    """Spec 2026-09-two-factor-authentication.md §5.4 door 4: the IdP owns
    authentication, so this is opt-in per provider — the default leaves OAuth
    completely unaffected, and only a provider explicitly configured to
    require it is checked against its own ``amr`` claim."""

    def setUp(self):
        super().setUp()
        self.provider.require_mfa_claim = True
        self.provider.save(update_fields=["require_mfa_claim"])

    def test_login_refused_without_an_mfa_amr_value(self):
        user = make_user("oauth_mfa_pwd_only", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-noamr", user=user)
        self.start_state("s")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-noamr", "email": user.email, "amr": ["pwd"]}):
            resp = self.callback(code="c", state="s")

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=mfa_claim_missing")
        event = AuditEvent.objects.get(action_type="oauth.login_failed")
        self.assertEqual(event.status, AuditEventStatus.DENIED)
        self.assertEqual(event.metadata_json["reason"], "mfa_claim_missing")
        self.assertFalse(OAuthExchangeCode.objects.exists())

    def test_missing_amr_claim_entirely_is_refused(self):
        user = make_user("oauth_mfa_no_claim", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-none", user=user)
        self.start_state("s")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-none", "email": user.email}):
            resp = self.callback(code="c", state="s")

        self.assertEqual(resp.url, f"{FRONTEND}/login?oauth_error=mfa_claim_missing")

    def test_login_succeeds_with_an_mfa_amr_value(self):
        user = make_user("oauth_mfa_satisfied", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-amr", user=user)
        self.start_state("s")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-amr", "email": user.email, "amr": ["mfa", "pwd"]}):
            resp = self.callback(code="c", state="s")

        self.assertTrue(resp.url.startswith(f"{FRONTEND}/oauth/callback?code="))
        self.assertTrue(OAuthExchangeCode.objects.filter(user=user).exists())

    def test_amr_as_a_space_separated_string_is_also_accepted(self):
        """Some providers send a space-separated string rather than a JSON
        array — tolerate the OIDC-spirit-compliant shape, not just the
        textbook one."""
        user = make_user("oauth_mfa_string_amr", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-str", user=user)
        self.start_state("s")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-str", "email": user.email, "amr": "pwd otp"}):
            resp = self.callback(code="c", state="s")

        self.assertTrue(resp.url.startswith(f"{FRONTEND}/oauth/callback?code="))

    def test_provider_without_the_requirement_is_unaffected(self):
        """The default (require_mfa_claim=False) is today's behaviour,
        unchanged, regardless of what amr says or doesn't say."""
        self.provider.require_mfa_claim = False
        self.provider.save(update_fields=["require_mfa_claim"])
        user = make_user("oauth_mfa_default", UserRole.USER)
        SocialAccount.objects.create(provider=self.provider, uid="uid-default", user=user)
        self.start_state("s")

        with fake_provider_http({"access_token": "at"}, {"sub": "uid-default", "email": user.email}):
            resp = self.callback(code="c", state="s")

        self.assertTrue(resp.url.startswith(f"{FRONTEND}/oauth/callback?code="))


class ProviderUrlSerializerTests(TestCase):
    @override_settings(DEBUG=False)
    def test_a_stored_plain_http_endpoint_can_be_resubmitted_but_not_newly_set(self):
        from .serializers import OAuthProviderSerializer

        provider = OAuthProvider.objects.create(
            name="legacy", client_id="c", client_secret="s",
            authorization_url="http://idp.example/auth", token_url="http://idp.example/token",
            userinfo_url="http://idp.example/userinfo", redirect_url="https://app.example/cb",
        )
        unchanged = OAuthProviderSerializer(provider, data={"token_url": "http://idp.example/token", "enabled": False}, partial=True)
        self.assertTrue(unchanged.is_valid(), unchanged.errors)
        changed = OAuthProviderSerializer(provider, data={"token_url": "http://idp.example/other"}, partial=True)
        self.assertFalse(changed.is_valid())
        self.assertIn("token_url", changed.errors)


class OAuthCallbackRevocationTests(OAuthTestCase):
    def test_callback_does_not_issue_a_code_after_revocation_or_deactivation(self):
        for change in ("version", "inactive"):
            with self.subTest(change=change):
                user = make_user(f"callback_{change}")
                SocialAccount.objects.create(provider=self.provider, user=user, uid=change)
                self.start_state(change)
                lock = User.objects.locked

                def change_before_lock():
                    updates = {"session_version": user.session_version + 1} if change == "version" else {"is_active": False}
                    User.objects.filter(pk=user.pk).update(**updates)
                    return lock()

                with fake_provider_http({"access_token": "at"}, {"sub": change, "email": user.email}), patch(
                    "accounts.views_oauth.User.objects.locked", side_effect=change_before_lock,
                ):
                    response = self.callback(code="c", state=change)
                self.assertEqual(response.url, f"{FRONTEND}/login?oauth_error=account_inactive")
                self.assertFalse(OAuthExchangeCode.objects.filter(user=user).exists())


class OAuthExchangeRevocationTests(TestCase):
    def setUp(self):
        self.user = make_user("oauth_exchange_owner")
        self.code = "one-time-exchange-code"
        OAuthExchangeCode.objects.create(user=self.user, code=self.code)

    def exchange(self):
        return APIClient().post("/api/v1/auth/oauth/token-exchange/", {"code": self.code}, format="json")

    def test_session_revocation_discards_pending_exchange_codes(self):
        from .session_revocation import revoke_sessions

        revoke_sessions(self.user)
        response = self.exchange()
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("openzev_access", response.cookies)
        self.assertFalse(OAuthExchangeCode.objects.exists())

    def test_inactive_account_cannot_exchange_an_existing_code(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        response = self.exchange()
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("openzev_access", response.cookies)

    def test_revocation_between_code_lookup_and_user_lock_refuses_exchange(self):
        from .session_revocation import revoke_sessions

        lock = User.objects.locked

        # A deterministic interleaving at the view's lock boundary.
        with patch("accounts.views_oauth.User.objects.locked") as acquire:
            def revoke_once():
                acquire.side_effect = lock
                revoke_sessions(self.user)
                return lock()
            acquire.side_effect = revoke_once
            response = self.exchange()
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("openzev_access", response.cookies)


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locking")
class OAuthExchangeConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = make_user("concurrent_exchange_owner")
        self.code = "concurrent-exchange-code"
        OAuthExchangeCode.objects.create(user=self.user, code=self.code)

    def exchange(self):
        response = APIClient().post("/api/v1/auth/oauth/token-exchange/", {"code": self.code}, format="json")
        return response.status_code, response.cookies.get("openzev_access")

    def simultaneously(self, *operations):
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            return list(executor.map(run, operations))

    def test_concurrent_redemption_mints_at_most_one_session(self):
        responses = self.simultaneously(self.exchange, self.exchange)
        self.assertEqual(sorted(status for status, _cookie in responses), [200, 400])
        self.assertFalse(OAuthExchangeCode.objects.exists())

    def test_exchange_racing_revocation_cannot_leave_a_valid_session(self):
        from rest_framework_simplejwt.tokens import AccessToken
        from .session_revocation import revoke_sessions
        from .session_revocation import is_session_current

        response, _ = self.simultaneously(
            self.exchange, lambda: revoke_sessions(self.user),
        )
        status, cookie = response
        self.user.refresh_from_db()
        self.assertIn(status, (200, 400))
        if cookie is not None:
            self.assertFalse(is_session_current(AccessToken(cookie.value), self.user))
        self.assertFalse(OAuthExchangeCode.objects.exists())
