"""The series itself: numbers, bucketing, grouping and limits (not who may see them)."""

from datetime import date, datetime, timezone as dt_timezone

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from analytics.dataset import bucket_start
from analytics.testing import DAY, Community
from testing.factories import AdminFactory
from testing.helpers import authenticate

URL = "/api/v1/analytics/series/"


@pytest.fixture
def community(db):
    return Community()


@pytest.fixture
def admin_client(db):
    client = APIClient()
    authenticate(client, AdminFactory())
    return client


def get(client, community, **params):
    query = {"zev": str(community.zev.pk), "from": DAY.isoformat(), "to": DAY.isoformat(), **params}
    return client.get(URL, query)


def rows_by(response, *keys):
    return {tuple(row[key] for key in keys): row for row in response.json()["results"]}


def test_zev_totals_split_into_local_grid_and_feed_in(admin_client, community):
    body = get(admin_client, community, group_by="zev", granularity="day").json()

    consumption = next(r for r in body["results"] if r["direction"] == "in")
    production = next(r for r in body["results"] if r["direction"] == "out")
    # Two intervals: 10 kWh consumed and 6 produced in each.
    assert (consumption["total_kwh"], consumption["local_kwh"], consumption["grid_kwh"]) == (20.0, 12.0, 8.0)
    assert (production["total_kwh"], production["local_kwh"], production["feed_in_kwh"]) == (12.0, 12.0, 0.0)
    assert consumption["feed_in_kwh"] is None and production["grid_kwh"] is None
    assert consumption["source"] == "metering"
    assert body["meta"]["scope"] == "zev" and body["meta"]["timezone"] == "Europe/Zurich"


def test_participant_rows_share_the_community_meter_by_weight(admin_client, community):
    response = get(admin_client, community, group_by="participant", direction="in")

    rows = rows_by(response, "participant")
    # Alice: 2 x (4 + 3/4); the pool gives every kWh a 60 % local share.
    assert rows[("Alice Muster",)]["total_kwh"] == 9.5
    assert rows[("Alice Muster",)]["local_kwh"] == pytest.approx(9.5 * 0.6, abs=0.001)
    assert rows[("Bob Beispiel",)]["total_kwh"] == 7.5
    assert rows[("Carol Common",)]["total_kwh"] == 1.5
    assert rows[("Dan Producer",)]["total_kwh"] == 1.5
    assert sum(r["total_kwh"] for r in rows.values()) == 20.0


def test_participant_grouping_matches_the_dashboard(admin_client, community):
    series = rows_by(get(admin_client, community, group_by="participant", direction="in"), "participant_id")
    dashboard = admin_client.get(
        "/api/v1/metering/readings/dashboard-summary/",
        {"zev_id": str(community.zev.pk), "date_from": DAY.isoformat(), "date_to": DAY.isoformat()},
    ).json()

    assert dashboard["participant_stats"]
    for stat in dashboard["participant_stats"]:
        row = series[(stat["participant_id"],)]
        assert row["total_kwh"] == pytest.approx(stat["total_consumed_kwh"], abs=0.001)
        assert row["local_kwh"] == pytest.approx(stat["from_zev_kwh"], abs=0.001)
        assert row["grid_kwh"] == pytest.approx(stat["from_grid_kwh"], abs=0.001)


def test_metering_point_grouping_names_the_meter_and_its_holder(admin_client, community):
    rows = rows_by(get(admin_client, community, direction="in"), "metering_point", "participant")

    assert rows[("a-ALICE", "Alice Muster")]["total_kwh"] == 8.0
    # The common-area meter is held by Carol but billed to everybody by weight.
    assert {participant for meter, participant in rows if meter == "a-COMMON"} == {
        "Alice Muster", "Bob Beispiel", "Carol Common", "Dan Producer",
    }


def test_filters_narrow_the_rows(admin_client, community):
    only_bob = get(admin_client, community, group_by="participant", participant=str(community.bob.pk))
    assert {r["participant"] for r in only_bob.json()["results"]} == {"Bob Beispiel"}

    one_meter = get(admin_client, community, metering_point=str(community.alice_mp.pk))
    assert {r["metering_point"] for r in one_meter.json()["results"]} == {"a-ALICE"}

    production_only = get(admin_client, community, group_by="zev", direction="out")
    assert {r["direction"] for r in production_only.json()["results"]} == {"out"}


def test_unassigned_energy_is_kept_with_no_participant(admin_client, community):
    orphan = community.zev.metering_points.create(meter_id="a-ORPHAN")
    community.reading(orphan, datetime(2026, 6, 10, 10, 0, tzinfo=dt_timezone.utc), "1")

    rows = rows_by(get(admin_client, community, direction="in"), "metering_point", "participant")

    assert rows[("a-ORPHAN", None)]["total_kwh"] == 1.0


def test_hourly_buckets_are_swiss_hours(admin_client, community):
    rows = get(admin_client, community, granularity="hour", group_by="zev", direction="in").json()["results"]

    assert [r["bucket_start"] for r in rows] == ["2026-06-10T12:00:00+02:00"]
    assert rows[0]["total_kwh"] == 20.0


def test_fifteen_minute_buckets_keep_the_intervals_apart(admin_client, community):
    rows = get(admin_client, community, granularity="15min", group_by="zev", direction="in").json()["results"]

    assert [r["bucket_start"] for r in rows] == ["2026-06-10T12:00:00+02:00", "2026-06-10T12:15:00+02:00"]


@pytest.mark.parametrize(
    ("ts", "granularity", "expected"),
    [
        # The day of the spring DST change: 23 hours long, boundaries follow local midnight.
        (datetime(2026, 3, 28, 23, 30, tzinfo=dt_timezone.utc), "day", "2026-03-29T00:00:00+01:00"),
        (datetime(2026, 3, 29, 21, 59, tzinfo=dt_timezone.utc), "day", "2026-03-29T00:00:00+01:00"),
        (datetime(2026, 3, 29, 22, 0, tzinfo=dt_timezone.utc), "day", "2026-03-30T00:00:00+02:00"),
        # 23:30 UTC on 31 Jan is already 00:30 on 1 Feb in Switzerland, so it belongs to February.
        (datetime(2026, 1, 31, 23, 30, tzinfo=dt_timezone.utc), "month", "2026-02-01T00:00:00+01:00"),
        (datetime(2026, 6, 10, 12, 0, tzinfo=dt_timezone.utc), "week", "2026-06-08T00:00:00+02:00"),
        (datetime(2026, 6, 10, 12, 0, tzinfo=dt_timezone.utc), "month", "2026-06-01T00:00:00+02:00"),
        (datetime(2026, 6, 10, 12, 0, tzinfo=dt_timezone.utc), "year", "2026-01-01T00:00:00+01:00"),
        # The two 02:00 hours of the autumn change stay apart.
        (datetime(2026, 10, 25, 0, 30, tzinfo=dt_timezone.utc), "hour", "2026-10-25T02:00:00+02:00"),
        (datetime(2026, 10, 25, 1, 30, tzinfo=dt_timezone.utc), "hour", "2026-10-25T02:00:00+01:00"),
        (datetime(2026, 6, 10, 10, 7, tzinfo=dt_timezone.utc), "15min", "2026-06-10T12:00:00+02:00"),
    ],
)
def test_bucket_start_follows_swiss_civil_time(ts, granularity, expected):
    assert bucket_start(ts, granularity).isoformat() == expected


def test_csv_has_a_header_and_one_row_per_record(admin_client, community):
    response = get(admin_client, community, group_by="zev", format="csv")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    lines = response.content.decode().splitlines()
    assert lines[0] == (
        "bucket_start,metering_point,participant,participant_id,direction,"
        "total_kwh,local_kwh,grid_kwh,feed_in_kwh,source"
    )
    assert lines[1].startswith("2026-06-10T00:00:00+02:00,,,,in,20.0,12.0,8.0,,metering")
    assert len(lines) == 3


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"granularity": "15min", "from": "2026-06-01", "to": "2026-06-30"}, "range_too_large"),
        ({"granularity": "day", "from": "2025-01-01", "to": "2026-06-30"}, "range_too_large"),
        ({"from": "2026-06-10", "to": "2026-06-01"}, "invalid_range"),
    ],
)
def test_span_limits(admin_client, community, params, code):
    response = get(admin_client, community, **params)

    assert response.status_code == 400
    assert response.json()["code"] == code


def test_reading_budget_refuses_a_range_that_is_too_expensive(admin_client, community):
    with override_settings(ANALYTICS_MAX_READINGS=3):
        response = get(admin_client, community)

    assert response.status_code == 400
    assert response.json()["code"] == "range_too_large"
    assert "Narrow the range" in response.json()["detail"]


def test_row_cap(admin_client, community):
    with override_settings(ANALYTICS_MAX_ROWS=2):
        response = get(admin_client, community)

    assert response.status_code == 400
    assert response.json()["code"] == "too_many_rows"


def test_inconsistent_readings_are_reported_not_a_server_error(admin_client, community):
    community.reading(community.zev.metering_points.create(meter_id="a-BAD"), datetime(2026, 6, 10, 10, 0, tzinfo=dt_timezone.utc), "-1")

    response = get(admin_client, community)

    assert response.status_code == 422
    assert response.json()["code"] == "inconsistent_readings"


@pytest.mark.parametrize(
    "params",
    [
        {"granularity": "decade"},
        {"group_by": "building"},
        {"direction": "sideways"},
        {"from": "yesterday"},
        {"participant": "not-a-uuid"},
        {"group_by": "zev", "participant": "00000000-0000-0000-0000-000000000001"},
    ],
)
def test_invalid_parameters_are_400(admin_client, community, params):
    assert get(admin_client, community, **params).status_code == 400


def test_from_and_to_are_required(admin_client, community):
    response = admin_client.get(URL, {"zev": str(community.zev.pk)})

    assert response.status_code == 400
    assert set(response.json()) == {"from", "to"}


def test_unknown_zev_is_404(admin_client, community):
    response = admin_client.get(URL, {"zev": "00000000-0000-0000-0000-000000000001", "from": "2026-06-10", "to": "2026-06-10"})

    assert response.status_code == 404


def test_dates_outside_the_data_give_an_empty_series(admin_client, community):
    response = get(admin_client, community, **{"from": "2026-05-01", "to": "2026-05-02"})

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert date.fromisoformat(response.json()["meta"]["from"]) == date(2026, 5, 1)
