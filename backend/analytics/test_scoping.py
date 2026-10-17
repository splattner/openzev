"""Who may read which rows of the series (ADR 0039)."""

from datetime import date

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from analytics.testing import DAY, Community
from testing.factories import AdminFactory
from testing.helpers import authenticate, make_user
from zev.models import ZevAccessRole
from zev.access import grant_manager
from zev.models import ZevAccessGrant

URL = "/api/v1/analytics/series/"


@pytest.fixture
def community(db):
    return Community("a")


@pytest.fixture
def other(db):
    return Community("b")


def client_for(user):
    client = APIClient()
    authenticate(client, user)
    return client


def get(client, community, **params):
    query = {"zev": str(community.zev.pk), "from": DAY.isoformat(), "to": DAY.isoformat(), **params}
    return client.get(URL, query)


def test_anonymous_is_401(community):
    assert get(APIClient(), community).status_code == 401


def test_manager_sees_everything_in_their_zev(community):
    response = get(client_for(community.manager), community, group_by="participant")

    assert response.status_code == 200
    assert response.json()["meta"]["scope"] == "zev"
    assert {r["participant"] for r in response.json()["results"]} == {
        "Alice Muster", "Bob Beispiel", "Carol Common", "Dan Producer",
    }


def test_manager_cannot_read_another_zev(community, other):
    assert get(client_for(community.manager), other).status_code == 403


def test_admin_reads_any_zev(community, other):
    assert get(client_for(AdminFactory()), other).status_code == 200


def test_viewer_reads_but_is_not_a_manager(community):
    viewer = make_user("a_viewer")
    ZevAccessGrant.objects.create(zev=community.zev, user=viewer, role=ZevAccessRole.VIEWER, valid_from=date(2026, 1, 1))

    response = get(client_for(viewer), community)

    assert response.status_code == 200
    assert response.json()["meta"]["scope"] == "zev"


def test_account_without_relationship_is_403(community):
    assert get(client_for(make_user("stranger")), community).status_code == 403


def test_participant_sees_only_their_own_rows(community):
    response = get(client_for(community.alice_user), community, group_by="participant")

    assert response.status_code == 200
    rows = response.json()["results"]
    assert response.json()["meta"]["scope"] == "participant"
    assert {r["participant"] for r in rows} == {"Alice Muster"}
    assert {r["direction"] for r in rows} == {"in"}


def test_participant_names_their_own_meter_but_not_a_shared_one(community):
    rows = get(client_for(community.alice_user), community).json()["results"]

    by_meter = {r["metering_point"]: r for r in rows}
    assert by_meter["a-ALICE"]["total_kwh"] == 8.0
    # Alice's 0.75 kWh x 2 share of the common-area meter is real energy of hers, but the
    # meter itself is Carol's: it is reported without naming it.
    assert by_meter[None]["total_kwh"] == 1.5
    assert "a-COMMON" not in by_meter


def test_participant_cannot_ask_for_somebody_elses_rows(community):
    response = get(client_for(community.alice_user), community, participant=str(community.bob.pk))

    assert response.status_code == 403
    assert response.json()["code"] == "participant_not_visible"


def test_participant_cannot_address_the_shared_meter(community):
    response = get(client_for(community.alice_user), community, metering_point=str(community.common_mp.pk))

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_participant_of_another_zev_is_403(community, other):
    assert get(client_for(community.alice_user), other).status_code == 403


def test_participant_zev_totals_are_suppressed_in_a_small_community(community):
    response = get(client_for(community.alice_user), community, group_by="zev")

    assert response.status_code == 403
    assert response.json()["code"] == "aggregate_suppressed"


def test_participant_zev_totals_are_shown_from_the_minimum_size(community):
    with override_settings(ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE=4):
        response = get(client_for(community.alice_user), community, group_by="zev")

    assert response.status_code == 200
    assert {r["direction"] for r in response.json()["results"]} == {"in", "out"}


def test_manager_zev_totals_are_never_suppressed(community):
    with override_settings(ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE=50):
        assert get(client_for(community.manager), community, group_by="zev").status_code == 200


def test_a_participant_who_has_left_sees_nothing(community):
    community.alice.valid_to = date(2026, 3, 1)
    community.alice.save()

    assert get(client_for(community.alice_user), community).status_code == 403


def test_participant_of_a_disabled_zev_sees_nothing(community):
    from django.utils import timezone

    community.zev.disabled_at = timezone.now()
    community.zev.save()

    assert get(client_for(community.alice_user), community).status_code == 403


def test_account_that_manages_and_participates_sees_the_whole_zev(community):
    grant_manager(community.zev, community.alice_user)

    response = get(client_for(community.alice_user), community, group_by="participant")

    assert len(response.json()["results"]) > 1
