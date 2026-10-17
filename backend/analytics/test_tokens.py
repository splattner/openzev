"""Analytics tokens: creation rules, what a token can reach, and when it stops working."""

from datetime import timedelta
from unittest import mock

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import FeatureFlag
from analytics.authentication import AnalyticsTokenThrottle
from analytics.models import AnalyticsToken
from analytics.testing import DAY, Community, enable_tokens
from audit.models import AuditEvent
from testing.factories import AdminFactory
from testing.helpers import authenticate, make_user
from zev.models import ZevAccessGrant, ZevAccessRole

SERIES = "/api/v1/analytics/series/"
TOKENS = "/api/v1/analytics/tokens/"


@pytest.fixture
def community(db):
    enable_tokens()
    return Community("a")


@pytest.fixture
def other(db):
    return Community("b")


def client_for(user):
    client = APIClient()
    authenticate(client, user)
    return client


def bearer(secret):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {secret}")
    return client


def create(user, community, **body):
    payload = {"name": "Grafana", "zev": str(community.zev.pk), **body}
    return client_for(user).post(TOKENS, payload, format="json")


def series(client, **params):
    return client.get(SERIES, {"from": DAY.isoformat(), "to": DAY.isoformat(), **params})


# ── creation ────────────────────────────────────────────────────────────────

def test_manager_creates_a_zev_token_and_the_secret_is_shown_once(community):
    response = create(community.manager, community)

    assert response.status_code == 201
    body = response.json()
    assert body["token"].startswith(f"oza_{body['prefix']}_")
    token = AnalyticsToken.objects.get(pk=body["id"])
    assert token.hashed_key and token.hashed_key not in body["token"]
    assert token.expires_at is not None  # the API-key default
    listed = client_for(community.manager).get(TOKENS).json()
    assert [t["id"] for t in listed] == [body["id"]]
    assert "token" not in listed[0] and "hashed_key" not in listed[0]


def test_creation_is_audited_without_the_secret(community):
    body = create(community.manager, community).json()

    event = AuditEvent.objects.get(action_type="analytics_token.create")
    assert event.zev_id == community.zev.pk and event.target_id == body["id"]
    assert body["token"] not in str(event.metadata_json) and body["token"] not in event.summary


def test_participant_creates_a_token_for_themself_only(community):
    assert create(community.alice_user, community, participant=str(community.alice.pk)).status_code == 201
    assert create(community.alice_user, community, participant=str(community.bob.pk)).status_code == 400
    assert create(community.alice_user, community).status_code == 400  # whole-ZEV scope needs a view of the ZEV


def test_manager_creates_a_participant_token_viewer_does_not(community):
    assert create(community.manager, community, participant=str(community.bob.pk)).status_code == 201
    viewer = make_user("a_viewer")
    ZevAccessGrant.objects.create(zev=community.zev, user=viewer, role=ZevAccessRole.VIEWER, valid_from=DAY.replace(month=1, day=1))
    assert create(viewer, community).status_code == 201
    assert create(viewer, community, participant=str(community.bob.pk)).status_code == 400


def test_nobody_creates_a_token_for_a_zev_they_cannot_see(community, other):
    assert create(community.manager, other).status_code == 400
    assert create(make_user("stranger"), community).status_code == 400


def test_participant_must_belong_to_the_zev(community, other):
    assert create(community.manager, community, participant=str(other.alice.pk)).status_code == 400


def test_expiry_must_be_in_the_future(community):
    past = (timezone.now() - timedelta(days=1)).isoformat()
    assert create(community.manager, community, expires_at=past).status_code == 400


def test_tokens_cannot_mint_tokens_and_api_keys_cannot_either(community):
    secret = create(community.manager, community).json()["token"]
    assert bearer(secret).post(TOKENS, {"name": "x", "zev": str(community.zev.pk)}, format="json").status_code in (401, 403)
    assert bearer(secret).get(TOKENS).status_code in (401, 403)


def test_feature_flag_off_hides_the_endpoints(community):
    FeatureFlag.objects.filter(name=FeatureFlag.ANALYTICS_TOKENS_ENABLED).update(enabled=False)

    assert client_for(community.manager).get(TOKENS).status_code == 404
    assert create(community.manager, community).status_code == 404


# ── using a token ───────────────────────────────────────────────────────────

def test_zev_token_reads_the_series_without_naming_the_zev(community):
    secret = create(community.manager, community).json()["token"]

    response = series(bearer(secret), group_by="zev")

    assert response.status_code == 200
    assert response.json()["meta"]["zev"] == str(community.zev.pk)
    assert response.json()["meta"]["scope"] == "zev"


def test_token_cannot_read_another_zev(community, other):
    secret = create(community.manager, community).json()["token"]

    assert series(bearer(secret), zev=str(other.zev.pk)).status_code == 403


def test_participant_token_sees_only_that_participant(community):
    secret = create(community.alice_user, community, participant=str(community.alice.pk)).json()["token"]

    response = series(bearer(secret), group_by="participant")

    assert {r["participant"] for r in response.json()["results"]} == {"Alice Muster"}
    assert series(bearer(secret), group_by="zev").status_code == 403


def test_a_manager_made_participant_token_is_narrowed_to_that_participant(community):
    secret = create(community.manager, community, participant=str(community.bob.pk)).json()["token"]

    response = series(bearer(secret), group_by="participant")

    assert {r["participant"] for r in response.json()["results"]} == {"Bob Beispiel"}


def test_token_reaches_nothing_but_the_series(community):
    secret = create(community.manager, community).json()["token"]

    for path in ("/api/v1/zev/zevs/", "/api/v1/auth/me/", "/api/v1/metering/readings/"):
        assert bearer(secret).get(path).status_code == 401, path


def test_garbage_and_foreign_tokens_are_401(community):
    assert series(bearer("oza_nothing_here"), zev=str(community.zev.pk)).status_code == 401
    assert series(bearer("ozv_abc_def"), zev=str(community.zev.pk)).status_code == 401
    secret = create(community.manager, community).json()["token"]
    prefix = secret.split("_")[1]
    assert series(bearer(f"oza_{prefix}_wrongsecret")).status_code == 401


def test_a_session_still_authenticates_next_to_a_token_scheme(community):
    assert series(client_for(community.manager), zev=str(community.zev.pk)).status_code == 200


def test_first_use_is_recorded(community):
    body = create(community.manager, community).json()
    assert AnalyticsToken.objects.get(pk=body["id"]).last_used_at is None

    series(bearer(body["token"]))

    assert AnalyticsToken.objects.get(pk=body["id"]).last_used_at is not None


# ── when it stops working ───────────────────────────────────────────────────

def test_revoked_token_stops_at_once_and_revocation_is_audited(community):
    body = create(community.manager, community).json()
    assert series(bearer(body["token"])).status_code == 200

    assert client_for(community.manager).delete(f"{TOKENS}{body['id']}/").status_code == 204

    assert series(bearer(body["token"])).status_code == 401
    assert client_for(community.manager).get(TOKENS).json() == []
    assert AnalyticsToken.objects.get(pk=body["id"]).revoked_at is not None
    assert AuditEvent.objects.filter(action_type="analytics_token.revoke", target_id=body["id"]).exists()


def test_expired_token_is_401(community):
    body = create(community.manager, community).json()
    AnalyticsToken.objects.filter(pk=body["id"]).update(expires_at=timezone.now() - timedelta(minutes=1))

    assert series(bearer(body["token"])).status_code == 401


def test_flag_off_stops_existing_tokens(community):
    body = create(community.manager, community).json()
    FeatureFlag.objects.filter(name=FeatureFlag.ANALYTICS_TOKENS_ENABLED).update(enabled=False)

    assert series(bearer(body["token"])).status_code == 401


def test_token_does_not_outlive_its_creators_access(community):
    body = create(community.manager, community).json()
    ZevAccessGrant.objects.filter(zev=community.zev, user=community.manager).delete()

    response = series(bearer(body["token"]))

    assert response.status_code == 403


def test_participant_token_stops_when_the_participant_leaves(community):
    body = create(community.alice_user, community, participant=str(community.alice.pk)).json()
    community.alice.valid_to = DAY.replace(month=3, day=1)
    community.alice.save()

    assert series(bearer(body["token"])).status_code == 403


def test_inactive_creator_stops_their_tokens(community):
    body = create(community.manager, community).json()
    community.manager.is_active = False
    community.manager.save()

    assert series(bearer(body["token"])).status_code == 401


def test_token_of_a_disabled_zev_is_refused(community):
    body = create(community.manager, community).json()
    community.zev.disabled_at = timezone.now()
    community.zev.save()

    assert series(bearer(body["token"])).status_code == 403


@mock.patch.object(AnalyticsTokenThrottle, "THROTTLE_RATES", {"analytics_token": "2/hour"})
def test_tokens_are_throttled_per_token(community):
    cache.clear()
    body = create(community.manager, community).json()
    second = create(community.manager, community, name="Second").json()

    statuses = [series(bearer(body["token"])).status_code for _ in range(3)]

    assert statuses == [200, 200, 429]
    assert series(bearer(second["token"])).status_code == 200


# ── who sees and revokes which tokens ───────────────────────────────────────

def test_a_manager_sees_and_revokes_tokens_of_their_zev_but_not_of_others(community, other):
    alice_token = create(community.alice_user, community, participant=str(community.alice.pk)).json()
    foreign = create(other.manager, other).json()

    manager = client_for(community.manager)
    listed = {t["id"] for t in manager.get(TOKENS).json()}
    assert listed == {alice_token["id"]}
    assert manager.delete(f"{TOKENS}{foreign['id']}/").status_code == 404
    assert manager.delete(f"{TOKENS}{alice_token['id']}/").status_code == 204


def test_a_participant_sees_only_their_own_tokens(community):
    create(community.alice_user, community, participant=str(community.alice.pk))
    create(community.bob_user, community, participant=str(community.bob.pk))

    assert len(client_for(community.alice_user).get(TOKENS).json()) == 1


def test_admin_sees_every_token(community, other):
    create(community.manager, community)
    enable_tokens()
    create(other.manager, other)

    assert len(client_for(AdminFactory()).get(TOKENS).json()) == 2
