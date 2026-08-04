"""Coverage for API key authentication.

The tests that matter most here are the negative ones. A key is a standing
credential: the value of the feature is not that a valid key works, it is that a
leaked one stays bounded — read-only really is read-only, revocation takes
effect on the next request, and a key can never be used to mint a session,
change a password, impersonate somebody or issue further keys.
"""

from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEvent, AuditEventSource
from testing.helpers import authenticate, make_user

from .api_keys import (
    KEY_NAMESPACE,
    SEPARATOR,
    generate_key,
    hash_secret,
    split_key,
    verify_secret,
)
from .models import ApiKey, UserRole
from .throttling import ApiKeyRateThrottle


def create_api_key(user, **overrides) -> tuple[ApiKey, str]:
    """Create a persisted key and return it alongside its plaintext secret."""
    full_key, prefix, hashed = generate_key()
    defaults = {
        "name": "test key",
        "prefix": prefix,
        "hashed_key": hashed,
    }
    defaults.update(overrides)
    return ApiKey.objects.create(user=user, **defaults), full_key


class ApiKeyGenerationTests(TestCase):
    def test_generated_key_round_trips(self):
        full_key, prefix, hashed = generate_key()

        self.assertTrue(full_key.startswith(f"{KEY_NAMESPACE}_"))
        parsed = split_key(full_key)
        self.assertIsNotNone(parsed)
        parsed_prefix, secret = parsed
        self.assertEqual(parsed_prefix, prefix)
        self.assertTrue(verify_secret(secret, hashed))

    def test_secret_is_not_recoverable_from_the_stored_hash(self):
        full_key, _, hashed = generate_key()
        _, secret = split_key(full_key)

        self.assertNotIn(hashed, full_key)
        self.assertNotIn(secret, hashed)

    def test_a_secret_containing_the_separator_still_parses(self):
        """``token_urlsafe`` includes ``_`` in its alphabet.

        A naive three-way split rejected roughly a third of issued keys — and
        did so only for the unlucky ones, which is the worst way to find out.
        """
        parsed = split_key(f"{KEY_NAMESPACE}_abc123_se_cr_et")

        self.assertEqual(parsed, ("abc123", "se_cr_et"))

    def test_the_prefix_never_contains_the_separator(self):
        for _ in range(50):
            self.assertNotIn(SEPARATOR, generate_key()[1])

    def test_keys_are_unique(self):
        keys = {generate_key()[0] for _ in range(50)}
        self.assertEqual(len(keys), 50)

    def test_split_rejects_malformed_keys(self):
        for candidate in ["", "nonsense", "ozv_only-two", "xyz_a_b", "ozv__secret", "ozv_prefix_"]:
            with self.subTest(candidate=candidate):
                self.assertIsNone(split_key(candidate))

    def test_verify_secret_rejects_a_different_secret(self):
        self.assertFalse(verify_secret("wrong", hash_secret("right")))


class ApiKeyModelTests(TestCase):
    def setUp(self):
        self.user = make_user("keyowner", UserRole.PARTICIPANT)

    def test_a_fresh_key_is_active(self):
        api_key, _ = create_api_key(self.user)
        self.assertTrue(api_key.is_active)

    def test_expiry_in_the_past_deactivates(self):
        api_key, _ = create_api_key(self.user, expires_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(api_key.is_expired)
        self.assertFalse(api_key.is_active)

    def test_revocation_deactivates(self):
        api_key, _ = create_api_key(self.user, revoked_at=timezone.now())
        self.assertTrue(api_key.is_revoked)
        self.assertFalse(api_key.is_active)


class ApiKeyAuthenticationTests(TestCase):
    """Authenticating a request with ``Authorization: Api-Key``."""

    def setUp(self):
        self.user = make_user("scripter", UserRole.ZEV_OWNER)
        self.api_key, self.raw_key = create_api_key(self.user, name="reporting")
        self.client = APIClient()

    def auth(self, raw_key=None):
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw_key or self.raw_key}")

    def test_valid_key_authenticates(self):
        self.auth()
        response = self.client.get("/api/v1/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["username"], "scripter")

    def test_no_credentials_is_rejected(self):
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_revoked_key_is_rejected(self):
        self.api_key.revoked_at = timezone.now()
        self.api_key.save(update_fields=["revoked_at"])

        self.auth()
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_expired_key_is_rejected(self):
        self.api_key.expires_at = timezone.now() - timedelta(minutes=1)
        self.api_key.save(update_fields=["expires_at"])

        self.auth()
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_key_for_an_inactive_user_is_rejected(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        self.auth()
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_key_is_deleted_with_its_owner(self):
        self.user.delete()
        self.assertFalse(ApiKey.objects.filter(pk=self.api_key.pk).exists())

    def test_wrong_secret_with_a_real_prefix_is_rejected(self):
        _, _, _ = generate_key()
        forged = f"{KEY_NAMESPACE}_{self.api_key.prefix}_notthesecret"

        self.auth(forged)
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_malformed_keys_are_rejected(self):
        for candidate in ["garbage", "ozv_missing", f"{self.raw_key}extra"]:
            with self.subTest(candidate=candidate):
                self.auth(candidate)
                self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_header_without_a_credential_is_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION="Api-Key")
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_rejection_does_not_reveal_whether_the_prefix_exists(self):
        """A caller learns that their key does not work, not why."""
        self.auth(f"{KEY_NAMESPACE}_{self.api_key.prefix}_wrongsecret")
        known_prefix = self.client.get("/api/v1/auth/me/")

        self.auth(f"{KEY_NAMESPACE}_nosuchpfx_wrongsecret")
        unknown_prefix = self.client.get("/api/v1/auth/me/")

        self.assertEqual(known_prefix.status_code, unknown_prefix.status_code)
        self.assertEqual(str(known_prefix.data["detail"]), str(unknown_prefix.data["detail"]))

    def test_bearer_tokens_still_work_alongside_key_auth(self):
        authenticate(self.client, self.user)
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 200)

    def test_me_does_not_break_on_a_key_carrying_no_impersonation_claim(self):
        """``request.auth`` is a JWT under cookie auth and an ApiKey here.

        The impersonation branch used to read ``token.payload`` unconditionally,
        which raises AttributeError for anything that is not a JWT.
        """
        self.auth()
        response = self.client.get("/api/v1/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("impersonated_by", response.data)


class ApiKeyLastUsedTests(TestCase):
    def setUp(self):
        self.user = make_user("toucher", UserRole.ZEV_OWNER)
        self.api_key, self.raw_key = create_api_key(self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.raw_key}")

    def test_first_use_is_recorded(self):
        self.assertIsNone(self.api_key.last_used_at)

        self.client.get("/api/v1/auth/me/")

        self.api_key.refresh_from_db()
        self.assertIsNotNone(self.api_key.last_used_at)

    def test_last_used_is_not_written_on_every_request(self):
        """The field finds abandoned keys; it is not an access log.

        Writing it per request would turn every authenticated read into a write.
        """
        self.client.get("/api/v1/auth/me/")
        self.api_key.refresh_from_db()
        first_write = self.api_key.last_used_at

        # One SELECT — the key joined to its user — and no UPDATE.
        with self.assertNumQueries(1):
            self.client.get("/api/v1/auth/me/")

        self.api_key.refresh_from_db()
        self.assertEqual(self.api_key.last_used_at, first_write)

    @override_settings(API_KEY_LAST_USED_RESOLUTION=timedelta(seconds=0))
    def test_last_used_is_refreshed_once_the_window_has_passed(self):
        self.client.get("/api/v1/auth/me/")
        self.api_key.refresh_from_db()
        first_write = self.api_key.last_used_at

        self.client.get("/api/v1/auth/me/")

        self.api_key.refresh_from_db()
        self.assertGreater(self.api_key.last_used_at, first_write)


class ReadOnlyApiKeyTests(TestCase):
    """A read-only key must be read-only on *every* endpoint.

    Enforcement lives in the authentication class rather than in
    ``DEFAULT_PERMISSION_CLASSES`` because DRF replaces the default permissions
    whenever a view declares its own — which nearly every view here does. These
    tests drive views with their own ``permission_classes`` on purpose.
    """

    def setUp(self):
        self.admin = make_user("ro-admin", UserRole.ADMIN)
        self.api_key, self.raw_key = create_api_key(self.admin, read_only=True)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.raw_key}")

    def test_get_is_allowed(self):
        self.assertEqual(self.client.get("/api/v1/auth/vat-rates/").status_code, 200)

    def test_post_is_refused_on_a_view_with_its_own_permissions(self):
        response = self.client.post(
            "/api/v1/auth/vat-rates/",
            {"rate": "0.0810", "valid_from": "2026-01-01"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("read-only", str(response.data["detail"]))

    def test_every_unsafe_method_is_refused(self):
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)("/api/v1/zev/zevs/")
                self.assertEqual(response.status_code, 403)

    def test_a_full_key_for_the_same_user_may_write(self):
        _, writable_raw = create_api_key(self.admin, name="writable")
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {writable_raw}")

        response = self.client.post(
            "/api/v1/auth/vat-rates/",
            {"rate": "0.0770", "valid_from": "2030-01-01"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)


class ApiKeyScopeTests(TestCase):
    """Endpoints a key must never reach.

    This is what decides whether a leaked key is a revocable credential or a
    permanent account takeover. The key here belongs to an admin — a
    full-permission key — so nothing below is blocked by role permissions.
    """

    def setUp(self):
        self.admin = make_user("scoped-admin", UserRole.ADMIN)
        self.victim = make_user("victim", UserRole.PARTICIPANT)
        self.api_key, self.raw_key = create_api_key(self.admin)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.raw_key}")

    def test_a_key_cannot_mint_a_browser_session(self):
        """The token endpoints ignore the Authorization header entirely.

        ``TokenViewBase`` sets ``authentication_classes = ()``, so no
        authenticator — ours included — runs there. That means the allowlist
        cannot reach these views, and does not need to: minting a session takes
        the account password, which a key does not carry. This test pins that
        property, because the day somebody gives those views an authenticator is
        the day the allowlist has to cover them.
        """
        response = self.client.post("/api/v1/auth/token/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("openzev_access", response.cookies)

    def test_a_key_cannot_refresh_a_token(self):
        """Unlike ``token/``, refresh is one of our own APIViews.

        It inherits the default authentication classes, so the allowlist does
        cover it — and refuses it, because a key must not be upgradeable into a
        browser session.
        """
        response = self.client.post("/api/v1/auth/token/refresh/")

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("openzev_access", response.cookies)

    def test_a_key_cannot_change_its_owners_password(self):
        response = self.client.post(
            "/api/v1/auth/me/change-password/",
            {"old_password": "pass1234", "new_password": "hijacked-pw-9182"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("pass1234"))

    def test_a_key_cannot_set_an_initial_password(self):
        response = self.client.post(
            "/api/v1/auth/me/set-initial-password/",
            {"new_password": "hijacked-pw-9182"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_a_key_cannot_impersonate(self):
        response = self.client.post(f"/api/v1/auth/users/{self.victim.pk}/impersonate/")
        self.assertEqual(response.status_code, 403)

    def test_a_key_cannot_change_the_owners_own_profile(self):
        """PATCH /me/ can move the account's email, which moves password reset."""
        response = self.client.patch(
            "/api/v1/auth/me/", {"email": "attacker@example.com"}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.email, "scoped-admin@example.com")

    def test_a_key_cannot_create_or_modify_users(self):
        create = self.client.post(
            "/api/v1/auth/users/",
            {"username": "backdoor", "email": "b@example.com", "role": "admin"},
            format="json",
        )
        modify = self.client.patch(
            f"/api/v1/auth/users/{self.victim.pk}/", {"role": "admin"}, format="json"
        )

        self.assertEqual(create.status_code, 403)
        self.assertEqual(modify.status_code, 403)

    def test_a_key_may_still_read_users(self):
        """Read access is the point of the feature; only the writes are closed."""
        self.assertEqual(self.client.get("/api/v1/auth/users/").status_code, 200)

    def test_a_key_may_reach_the_rest_of_the_api(self):
        self.assertEqual(self.client.get("/api/v1/zev/zevs/").status_code, 200)

    def test_a_cookie_session_is_unaffected_by_the_scope_rules(self):
        """The rules bound API keys, not people."""
        session_client = APIClient()
        authenticate(session_client, self.admin)

        response = session_client.patch(
            "/api/v1/auth/me/", {"first_name": "Real"}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    def test_new_accounts_endpoints_are_closed_until_opened(self):
        """The allowlist is the whole contract for the accounts app.

        Anything resolved there and not named is denied, so an endpoint added
        tomorrow fails closed rather than silently becoming key-reachable.
        """
        from .authentication import ACCOUNTS_API_KEY_ALLOWLIST
        from .urls import urlpatterns

        named = {pattern.name for pattern in urlpatterns if pattern.name}
        self.assertTrue(set(ACCOUNTS_API_KEY_ALLOWLIST).issubset(named))

        response = self.client.get("/api/v1/auth/feature-flags/")
        self.assertEqual(response.status_code, 200)  # allow-listed
        self.assertEqual(
            self.client.get("/api/v1/auth/me/social-accounts/").status_code, 403
        )  # not allow-listed


class ApiKeyAuditTests(TestCase):
    def setUp(self):
        self.admin = make_user("audited", UserRole.ADMIN)
        self.api_key, self.raw_key = create_api_key(self.admin, name="nightly job")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.raw_key}")

    def test_an_action_taken_with_a_key_names_the_credential(self):
        response = self.client.post(
            "/api/v1/auth/vat-rates/",
            {"rate": "0.0810", "valid_from": "2029-01-01"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        event = AuditEvent.objects.filter(target_type="accounts.VatRate").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.source, AuditEventSource.API_KEY)
        self.assertEqual(event.metadata_json["api_key_id"], str(self.api_key.pk))
        self.assertEqual(event.metadata_json["api_key_name"], "nightly job")

    def test_a_cookie_session_is_still_recorded_as_plain_api(self):
        session_client = APIClient()
        authenticate(session_client, self.admin)
        session_client.post(
            "/api/v1/auth/vat-rates/",
            {"rate": "0.0770", "valid_from": "2031-01-01"},
            format="json",
        )

        event = AuditEvent.objects.filter(target_type="accounts.VatRate").first()
        self.assertEqual(event.source, AuditEventSource.API)
        self.assertNotIn("api_key_id", event.metadata_json)


@mock.patch.object(ApiKeyRateThrottle, "THROTTLE_RATES", {"api_key": "3/hour"})
class ApiKeyThrottleTests(TestCase):
    """DRF snapshots ``DEFAULT_THROTTLE_RATES`` onto ``SimpleRateThrottle`` at
    import time, so ``override_settings`` cannot reach it — the rate has to be
    patched on the class. That snapshot is also what lets ``settings_test``
    switch throttling off for the rest of the suite: without it, the 601st
    key-authenticated request in the whole run would start failing, in whichever
    test happened to make it.
    """

    def setUp(self):
        cache.clear()
        self.user = make_user("busy", UserRole.ZEV_OWNER)
        self.api_key, self.raw_key = create_api_key(self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.raw_key}")

    def tearDown(self):
        cache.clear()

    def test_a_key_past_its_limit_gets_429(self):
        for _ in range(3):
            self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 200)

        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 429)

    def test_each_key_has_its_own_budget(self):
        _, other_raw = create_api_key(self.user, name="second")

        for _ in range(3):
            self.client.get("/api/v1/auth/me/")
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 429)

        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {other_raw}")
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 200)

    def test_a_cookie_session_is_not_throttled(self):
        for _ in range(3):
            self.client.get("/api/v1/auth/me/")
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 429)

        session_client = APIClient()
        authenticate(session_client, self.user)
        for _ in range(5):
            self.assertEqual(session_client.get("/api/v1/auth/me/").status_code, 200)


class ApiKeyCrudTests(TestCase):
    """Creating, listing and revoking keys through the API."""

    LIST_URL = "/api/v1/auth/me/api-keys/"

    def setUp(self):
        self.user = make_user("owner", UserRole.PARTICIPANT)
        self.client = APIClient()
        authenticate(self.client, self.user)

    def create(self, **payload):
        payload.setdefault("name", "my script")
        return self.client.post(self.LIST_URL, payload, format="json")

    def test_create_returns_the_secret_exactly_once(self):
        response = self.create()

        self.assertEqual(response.status_code, 201)
        secret = response.data["key"]
        self.assertTrue(secret.startswith(f"{KEY_NAMESPACE}{SEPARATOR}"))

        listed = self.client.get(self.LIST_URL)
        self.assertEqual(len(listed.data["results"]), 1)
        self.assertNotIn("key", listed.data["results"][0])
        self.assertNotIn("hashed_key", listed.data["results"][0])

    def test_the_created_key_authenticates(self):
        secret = self.create().data["key"]

        key_client = APIClient()
        key_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {secret}")
        self.assertEqual(key_client.get("/api/v1/auth/me/").status_code, 200)

    def test_the_plaintext_secret_is_not_stored(self):
        secret = self.create().data["key"]
        _, plaintext = split_key(secret)

        stored = ApiKey.objects.get()
        self.assertNotEqual(stored.hashed_key, plaintext)
        self.assertNotIn(plaintext, stored.hashed_key)

    def test_a_name_is_required(self):
        self.assertEqual(self.client.post(self.LIST_URL, {"name": "   "}, format="json").status_code, 400)

    def test_default_expiry_is_applied(self):
        response = self.create()

        self.assertIsNotNone(response.data["expires_at"])
        expires_at = ApiKey.objects.get().expires_at
        self.assertAlmostEqual(
            (expires_at - timezone.now()).days,
            settings.API_KEY_DEFAULT_EXPIRY_DAYS,
            delta=1,
        )

    @override_settings(API_KEY_DEFAULT_EXPIRY_DAYS=0)
    def test_expiry_can_be_switched_off_by_configuration(self):
        self.create()
        self.assertIsNone(ApiKey.objects.get().expires_at)

    def test_an_explicit_expiry_wins(self):
        chosen = (timezone.now() + timedelta(days=7)).isoformat()

        self.create(expires_at=chosen)

        self.assertLess((ApiKey.objects.get().expires_at - timezone.now()).days, 8)

    def test_an_expiry_in_the_past_is_refused(self):
        response = self.create(expires_at=(timezone.now() - timedelta(days=1)).isoformat())

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ApiKey.objects.exists())

    def test_read_only_flag_is_persisted(self):
        self.create(read_only=True)
        self.assertTrue(ApiKey.objects.get().read_only)

    def test_a_user_only_sees_their_own_keys(self):
        other = make_user("stranger", UserRole.ADMIN)
        create_api_key(other, name="not yours")
        self.create()

        response = self.client.get(self.LIST_URL)

        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "my script")

    def test_an_admin_cannot_read_another_users_keys(self):
        """Admins can already act as anybody; reading their credential list is
        a different power, and one nothing here needs."""
        create_api_key(self.user, name="private")
        admin_client = APIClient()
        authenticate(admin_client, make_user("nosy-admin", UserRole.ADMIN))

        response = admin_client.get(self.LIST_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_revoking_takes_effect_on_the_next_request(self):
        secret = self.create().data["key"]
        key_id = ApiKey.objects.get().pk
        key_client = APIClient()
        key_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {secret}")
        self.assertEqual(key_client.get("/api/v1/auth/me/").status_code, 200)

        self.assertEqual(self.client.delete(f"{self.LIST_URL}{key_id}/").status_code, 204)

        self.assertEqual(key_client.get("/api/v1/auth/me/").status_code, 401)

    def test_a_revoked_key_leaves_the_list_but_stays_in_the_table(self):
        """The row is what lets an audit event still resolve the key's name."""
        self.create()
        key_id = ApiKey.objects.get().pk

        self.client.delete(f"{self.LIST_URL}{key_id}/")

        self.assertEqual(self.client.get(self.LIST_URL).data["results"], [])
        self.assertTrue(ApiKey.objects.filter(pk=key_id).exists())

    def test_a_user_cannot_revoke_somebody_elses_key(self):
        other = make_user("target", UserRole.PARTICIPANT)
        victim_key, _ = create_api_key(other)

        response = self.client.delete(f"{self.LIST_URL}{victim_key.pk}/")

        self.assertEqual(response.status_code, 404)
        victim_key.refresh_from_db()
        self.assertIsNone(victim_key.revoked_at)

    def test_key_management_needs_authentication(self):
        self.assertEqual(APIClient().get(self.LIST_URL).status_code, 401)

    def test_a_key_cannot_manage_keys(self):
        """Otherwise revoking a leaked key achieves nothing: the holder mints
        a replacement first."""
        _, secret = create_api_key(self.user)
        key_client = APIClient()
        key_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {secret}")

        self.assertEqual(key_client.get(self.LIST_URL).status_code, 403)
        self.assertEqual(key_client.post(self.LIST_URL, {"name": "x"}, format="json").status_code, 403)

    def test_creation_and_revocation_are_audited(self):
        self.create(name="nightly export")
        key_id = ApiKey.objects.get().pk
        self.client.delete(f"{self.LIST_URL}{key_id}/")

        actions = list(
            AuditEvent.objects.filter(target_type="accounts.ApiKey")
            .order_by("created_at")
            .values_list("action_type", flat=True)
        )
        self.assertEqual(actions, ["api_key.create", "api_key.revoke"])

    def test_the_audit_trail_never_carries_the_secret(self):
        secret = self.create().data["key"]

        event = AuditEvent.objects.get(action_type="api_key.create")
        self.assertNotIn(secret, str(event.metadata_json))
        self.assertNotIn(split_key(secret)[1], str(event.metadata_json))


class AdminApiKeyManagementTests(TestCase):
    """Admin console: see every key, revoke any of them.

    What stays closed is *creating* a key for somebody else, which would be a
    durable credential in their name.
    """

    LIST_URL = "/api/v1/auth/api-keys/"

    def setUp(self):
        self.admin = make_user("console-admin", UserRole.ADMIN)
        self.owner = make_user("key-owner", UserRole.ZEV_OWNER)
        self.participant = make_user("key-participant", UserRole.PARTICIPANT)

        self.owner_key, self.owner_raw = create_api_key(self.owner, name="owner nightly")
        self.participant_key, _ = create_api_key(self.participant, name="participant export")
        self.admin_key, _ = create_api_key(self.admin, name="admin own")

        self.client = APIClient()
        authenticate(self.client, self.admin)

    # ── listing ──────────────────────────────────────────────────────────

    def test_admin_sees_every_users_keys(self):
        response = self.client.get(self.LIST_URL)

        self.assertEqual(response.status_code, 200)
        names = {row["name"] for row in response.data["results"]}
        self.assertEqual(names, {"owner nightly", "participant export", "admin own"})

    def test_the_list_names_the_owner(self):
        response = self.client.get(self.LIST_URL)

        row = next(r for r in response.data["results"] if r["name"] == "owner nightly")
        self.assertEqual(row["username"], "key-owner")
        self.assertEqual(row["user_email"], "key-owner@example.com")
        self.assertEqual(row["user_role"], UserRole.ZEV_OWNER)

    def test_the_list_never_exposes_the_hash(self):
        """There is no admin path to a secret — none exists to expose."""
        response = self.client.get(self.LIST_URL)

        for row in response.data["results"]:
            self.assertNotIn("hashed_key", row)
            self.assertNotIn("key", row)

    def test_revoked_keys_are_listed_too(self):
        self.owner_key.revoked_at = timezone.now()
        self.owner_key.save(update_fields=["revoked_at"])

        response = self.client.get(self.LIST_URL)

        row = next(r for r in response.data["results"] if r["name"] == "owner nightly")
        self.assertTrue(row["is_revoked"])
        self.assertIsNotNone(row["revoked_at"])

    def test_can_filter_by_user(self):
        response = self.client.get(self.LIST_URL, {"user": self.owner.pk})

        self.assertEqual([r["name"] for r in response.data["results"]], ["owner nightly"])

    def test_can_filter_by_status(self):
        self.owner_key.revoked_at = timezone.now()
        self.owner_key.save(update_fields=["revoked_at"])

        active = self.client.get(self.LIST_URL, {"status": "active"})
        revoked = self.client.get(self.LIST_URL, {"status": "revoked"})

        self.assertNotIn("owner nightly", {r["name"] for r in active.data["results"]})
        self.assertEqual([r["name"] for r in revoked.data["results"]], ["owner nightly"])

    def test_an_unknown_status_is_refused_not_silently_ignored(self):
        response = self.client.get(self.LIST_URL, {"status": "expired"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.json())

    def test_a_non_numeric_user_filter_is_refused_not_a_server_error(self):
        response = self.client.get(self.LIST_URL, {"user": "not-a-number"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("user", response.json())

    def test_a_unicode_digit_user_filter_is_refused_not_a_server_error(self):
        response = self.client.get(self.LIST_URL, {"user": "١٢٣"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("user", response.json())

    # ── revoking ─────────────────────────────────────────────────────────

    def test_admin_can_revoke_another_users_key(self):
        response = self.client.delete(f"{self.LIST_URL}{self.owner_key.pk}/")

        self.assertEqual(response.status_code, 204)
        self.owner_key.refresh_from_db()
        self.assertIsNotNone(self.owner_key.revoked_at)

    def test_the_revoked_key_stops_working_on_the_next_request(self):
        key_client = APIClient()
        key_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.owner_raw}")
        self.assertEqual(key_client.get("/api/v1/auth/me/").status_code, 200)

        self.client.delete(f"{self.LIST_URL}{self.owner_key.pk}/")

        self.assertEqual(key_client.get("/api/v1/auth/me/").status_code, 401)

    def test_revoking_twice_is_refused_rather_than_silently_accepted(self):
        self.client.delete(f"{self.LIST_URL}{self.owner_key.pk}/")

        second = self.client.delete(f"{self.LIST_URL}{self.owner_key.pk}/")

        self.assertEqual(second.status_code, 400)

    def test_revoking_someone_elses_key_is_audited_as_such(self):
        self.client.delete(f"{self.LIST_URL}{self.owner_key.pk}/")

        event = AuditEvent.objects.filter(action_type="api_key.revoke").latest("created_at")
        self.assertEqual(event.actor_user, self.admin)
        self.assertTrue(event.metadata_json["revoked_by_admin"])
        self.assertEqual(event.metadata_json["owner_username"], "key-owner")
        self.assertIn("key-owner@example.com", event.summary)

    def test_revoking_your_own_key_here_is_not_flagged_as_an_admin_action(self):
        self.client.delete(f"{self.LIST_URL}{self.admin_key.pk}/")

        event = AuditEvent.objects.filter(action_type="api_key.revoke").latest("created_at")
        self.assertFalse(event.metadata_json["revoked_by_admin"])

    # ── what stays closed ────────────────────────────────────────────────

    def test_an_admin_cannot_mint_a_key_for_somebody_else(self):
        """A durable credential in another person's name outlives the admin's
        session and bills every action to its owner — strictly more than
        impersonation, and nothing here needs it."""
        response = self.client.post(
            self.LIST_URL, {"name": "backdoor", "user": self.owner.pk}, format="json"
        )

        self.assertIn(response.status_code, (403, 405))
        self.assertFalse(ApiKey.objects.filter(name="backdoor").exists())

    def test_a_non_admin_cannot_reach_the_console_endpoints(self):
        for user in (self.owner, self.participant):
            with self.subTest(role=user.role):
                client = APIClient()
                authenticate(client, user)

                self.assertEqual(client.get(self.LIST_URL).status_code, 403)
                self.assertEqual(
                    client.delete(f"{self.LIST_URL}{self.participant_key.pk}/").status_code, 403
                )

    def test_an_api_key_cannot_reach_the_console_endpoints(self):
        """Not even an admin's own key: a leaked key must not be able to revoke
        every other credential in the system."""
        _, admin_raw = create_api_key(self.admin, name="admin second")
        key_client = APIClient()
        key_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {admin_raw}")

        self.assertEqual(key_client.get(self.LIST_URL).status_code, 403)
        self.assertEqual(
            key_client.delete(f"{self.LIST_URL}{self.owner_key.pk}/").status_code, 403
        )

    def test_the_owner_endpoint_is_still_scoped_to_its_owner(self):
        """Widening the admin console must not widen /me/api-keys/."""
        client = APIClient()
        authenticate(client, self.owner)

        response = client.get("/api/v1/auth/me/api-keys/")

        self.assertEqual([r["name"] for r in response.data["results"]], ["owner nightly"])
