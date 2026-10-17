"""The Tokens & keys list: one row shape for API keys, analytics tokens and energy data push tokens."""

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from accounts.api_keys import generate_key
from accounts.models import ApiKey, FeatureFlag
from analytics.models import AnalyticsToken
from analytics.testing import enable_tokens
from metering.supplementary.testing import (
    SOURCES_URL,
    SupplementaryApiTestCase,
    client_for,
    enable_feature,
)

ME = "/api/v1/auth/me/credentials/"
ALL = "/api/v1/auth/credentials/"


def make_key(user, name="Script", **fields):
    _full, prefix, hashed = generate_key()
    return ApiKey.objects.create(user=user, name=name, prefix=prefix, hashed_key=hashed, **fields)


def make_analytics(user, zev, participant=None, name="Grafana", **fields):
    _full, prefix, hashed = generate_key("oza")
    return AnalyticsToken.objects.create(
        name=name, zev=zev, participant=participant, created_by=user, prefix=prefix, hashed_key=hashed, **fields
    )


class CredentialsTestCase(SupplementaryApiTestCase):
    def setUp(self):
        super().setUp()
        enable_tokens()
        self.key = make_key(self.holder_user, read_only=True)
        self.analytics = make_analytics(self.holder_user, self.zev, self.holder)
        created = self.create_push_source().json()
        self.source_id = created["id"]
        self.prefix = created["push_token_prefix"]

    def rows(self, user=None, url=ME, **params):
        response = client_for(user or self.holder_user).get(url, params)
        self.assertEqual(response.status_code, 200, response.content)
        return {row["kind"]: row for row in response.json()["credentials"]}


class MyCredentialsTests(CredentialsTestCase):
    def test_all_three_kinds_in_one_normalized_shape(self):
        rows = self.rows()

        self.assertEqual(set(rows), {"api_key", "analytics", "energy_push"})
        api_key, analytics, energy = rows["api_key"], rows["analytics"], rows["energy_push"]
        self.assertEqual((api_key["access"], analytics["access"], energy["access"]), ("read_only", "read", "write_readings"))
        self.assertEqual(api_key["prefix"], f"ozv_{self.key.prefix}")
        self.assertEqual(analytics["prefix"], f"oza_{self.analytics.prefix}")
        self.assertEqual(energy["prefix"], f"ozs_{self.prefix}")
        self.assertEqual(analytics["scope"]["zev"], str(self.zev.pk))
        self.assertEqual(analytics["scope"]["participant"], str(self.holder.pk))
        self.assertEqual(energy["scope"]["meter_id"], self.point.meter_id)
        self.assertEqual(energy["actions"], ["rotate", "revoke"])
        self.assertEqual(api_key["actions"], ["revoke"])
        self.assertEqual(set(api_key["scope"]), set(energy["scope"]))
        self.assertTrue(all(value is None for value in api_key["scope"].values()))

    def test_no_secret_or_hash_is_ever_listed(self):
        text = client_for(self.holder_user).get(ME).content.decode()

        for forbidden in ("hashed_key", "push_token_hash", "credential_encrypted", "push_token\""):
            self.assertNotIn(forbidden, text)

    def test_newest_first(self):
        ApiKey.objects.filter(pk=self.key.pk).update(created_at=timezone.now() + timedelta(hours=1))
        kinds = [row["kind"] for row in client_for(self.holder_user).get(ME).json()["credentials"]]
        self.assertEqual(kinds[0], "api_key")

    def test_revoked_credentials_are_not_listed_and_expired_ones_say_so(self):
        ApiKey.objects.filter(pk=self.key.pk).update(revoked_at=timezone.now())
        AnalyticsToken.objects.filter(pk=self.analytics.pk).update(expires_at=timezone.now() - timedelta(days=1))

        rows = self.rows()

        self.assertNotIn("api_key", rows)
        self.assertEqual(rows["analytics"]["status"], "expired")

    def test_a_push_token_shows_when_it_was_issued_and_last_used(self):
        row = self.rows()["energy_push"]
        self.assertIsNotNone(row["created_at"])
        self.assertIsNone(row["last_used_at"])

    def test_a_revoked_push_token_leaves_the_list(self):
        client_for(self.holder_user).post(f"{SOURCES_URL}{self.source_id}/revoke-push-token/")
        self.assertNotIn("energy_push", self.rows())

    def test_flags_off_hide_analytics_and_energy_rows(self):
        enable_feature(False)
        FeatureFlag.objects.filter(name=FeatureFlag.ANALYTICS_TOKENS_ENABLED).update(enabled=False)

        response = client_for(self.holder_user).get(ME).json()

        self.assertEqual({row["kind"] for row in response["credentials"]}, {"api_key"})
        self.assertEqual(response["can_create"], {"api_key": True, "analytics": False})

    def test_only_the_accounts_own_credentials_appear(self):
        make_key(self.other_user, "Other")
        make_analytics(self.manager, self.zev, None, "Manager token")

        for user in (self.holder_user, self.other_user, self.manager):
            names = [r["name"] for r in client_for(user).get(ME).json()["credentials"]]
            self.assertEqual(len(names), len(set(names)))
        self.assertEqual([r["name"] for r in client_for(self.other_user).get(ME).json()["credentials"]], ["Other"])
        self.assertEqual([r["name"] for r in client_for(self.manager).get(ME).json()["credentials"]], ["Manager token"])

    def test_a_manager_does_not_see_a_participants_analytics_token_or_push_token(self):
        manager = client_for(self.manager).get(ME).json()["credentials"]
        self.assertEqual(manager, [])

    def test_can_create(self):
        self.assertEqual(client_for(self.holder_user).get(ME).json()["can_create"], {"api_key": True, "analytics": True})
        self.assertEqual(client_for(self.stranger).get(ME).json()["can_create"], {"api_key": True, "analytics": False})
        self.assertEqual(client_for(self.manager).get(ME).json()["can_create"]["analytics"], True)

    def test_anonymous_is_401_and_credentials_cannot_list_credentials(self):
        self.assertEqual(APIClient().get(ME).status_code, 401)
        full, prefix, hashed = generate_key()
        ApiKey.objects.create(user=self.holder_user, name="Live", prefix=prefix, hashed_key=hashed)
        key_client = APIClient()
        key_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {full}")
        self.assertEqual(key_client.get(ME).status_code, 401)
        analytics_full, aprefix, ahash = generate_key("oza")
        AnalyticsToken.objects.create(name="t", zev=self.zev, created_by=self.holder_user, prefix=aprefix, hashed_key=ahash)
        token_client = APIClient()
        token_client.credentials(HTTP_AUTHORIZATION=f"Bearer {analytics_full}")
        self.assertEqual(token_client.get(ME).status_code, 401)


class AdminCredentialsTests(CredentialsTestCase):
    def test_non_admin_is_403(self):
        self.assertEqual(client_for(self.manager).get(ALL).status_code, 403)
        self.assertEqual(client_for(self.holder_user).get(ALL).status_code, 403)

    def test_admin_sees_every_kind_of_every_owner_with_the_owner(self):
        make_key(self.other_user, "Other")

        response = client_for(self.admin).get(ALL).json()["credentials"]

        self.assertEqual({row["kind"] for row in response}, {"api_key", "analytics", "energy_push"})
        self.assertEqual(len(response), 4)
        owners = {row["name"]: row["owner"]["id"] for row in response}
        self.assertEqual(owners["Other"], self.other_user.pk)
        self.assertEqual(owners["Script"], self.holder_user.pk)

    def test_revoked_are_included_and_filterable(self):
        ApiKey.objects.filter(pk=self.key.pk).update(revoked_at=timezone.now())

        everything = client_for(self.admin).get(ALL).json()["credentials"]
        revoked = client_for(self.admin).get(ALL, {"status": "revoked"}).json()["credentials"]
        active = client_for(self.admin).get(ALL, {"status": "active"}).json()["credentials"]

        self.assertEqual(len(everything), 3)
        self.assertEqual([row["kind"] for row in revoked], ["api_key"])
        self.assertNotIn("api_key", {row["kind"] for row in active})

    def test_filters_by_kind_and_user(self):
        make_key(self.other_user, "Other")
        admin = client_for(self.admin)

        self.assertEqual([r["kind"] for r in admin.get(ALL, {"kind": "analytics"}).json()["credentials"]], ["analytics"])
        by_user = admin.get(ALL, {"user": self.other_user.pk}).json()["credentials"]
        self.assertEqual([r["name"] for r in by_user], ["Other"])

    def test_bad_filters_are_400(self):
        admin = client_for(self.admin)
        for params in ({"kind": "password"}, {"status": "weird"}, {"user": "abc"}):
            self.assertEqual(admin.get(ALL, params).status_code, 400, params)
