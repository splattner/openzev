"""Participant raw/chart access follows the meter's UTC assignment windows (#570)."""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from metering.models import MeterReading
from testing.factories import (
    AdminFactory,
    MeteringPointAssignmentFactory,
    MeteringPointFactory,
    ParticipantFactory,
    ParticipantUserFactory,
)
from testing.helpers import authenticate

pytestmark = pytest.mark.django_db


@pytest.fixture(params=["raw-summary", "raw-detail", "chart-day", "chart-hour", "chart-month"])
def read_energy(request, api_client):
    """Exercise all raw-data modes and chart buckets through authenticated HTTP."""
    mode = request.param

    def read(user, meter, day, **extra_params):
        authenticate(api_client, user)
        params = {"metering_point": str(meter.pk)}
        if mode == "raw-detail":
            params["date"] = day
        else:
            params.update(date_from=day, date_to=day)
        if mode.startswith("chart-"):
            params["bucket"] = mode.removeprefix("chart-")
        params.update(extra_params)
        action = "chart-data" if mode.startswith("chart-") else "raw-data"
        response = api_client.get(f"/api/v1/metering/readings/{action}/", params)
        assert response.status_code == 200, response.data
        if mode == "raw-detail":
            return {
                direction: sum(row["energy_kwh"] for row in response.data if row["direction"] == direction)
                for direction in ("in", "out")
            }
        return {
            direction: sum(row[f"{direction}_kwh"] for row in response.data)
            for direction in ("in", "out")
        }

    return read


def add_readings(meter, timestamp):
    for direction, energy in (("in", "1.25"), ("out", "0.75")):
        MeterReading.objects.create(
            metering_point=meter,
            timestamp=datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc),
            direction=direction,
            energy_kwh=Decimal(energy),
        )


@pytest.fixture
def history():
    holder = ParticipantFactory(user=ParticipantUserFactory())
    other = ParticipantFactory(zev=holder.zev, user=ParticipantUserFactory())
    meter = MeteringPointFactory(zev=holder.zev, meter_type="bidirectional")
    for participant, start, end in (
        (other, date(2026, 1, 1), date(2026, 1, 9)),
        (holder, date(2026, 1, 10), date(2026, 1, 15)),
        (other, date(2026, 1, 16), date(2026, 1, 20)),
        (holder, date(2026, 2, 1), None),
    ):
        MeteringPointAssignmentFactory(
            metering_point=meter, participant=participant, valid_from=start, valid_to=end,
        )
    for timestamp in (
        "2026-01-09T23:45:00",  # Zurich is already on the holder's first day.
        "2026-01-10T00:00:00",
        "2026-01-15T23:45:00",  # Still the holder's last UTC day.
        "2026-01-16T00:00:00",
        "2026-01-21T12:00:00",  # No assignment covers this gap.
        "2026-02-01T00:00:00",
        "2026-03-29T23:45:00",  # Open-ended assignment, after the DST change.
    ):
        add_readings(meter, timestamp)
    return SimpleNamespace(holder=holder, other=other, meter=meter)


@pytest.mark.parametrize("day,visible", [
    ("2026-01-09", False),
    ("2026-01-10", True),
    ("2026-01-15", True),
    ("2026-01-16", False),
    ("2026-01-21", False),
    ("2026-02-01", True),
    ("2026-03-29", True),
])
def test_only_assignment_days_are_visible_without_duplicate_totals(history, read_energy, day, visible):
    # The returning holder has two assignments; neither may multiply sums.
    expected = {"in": 1.25, "out": 0.75} if visible else {"in": 0, "out": 0}
    assert read_energy(history.holder.user, history.meter, day) == expected


def test_next_holder_can_read_their_own_readings(history, read_energy):
    assert read_energy(history.other.user, history.meter, "2026-01-16") == {"in": 1.25, "out": 0.75}


@pytest.mark.parametrize("action", ["raw-data", "chart-data"])
def test_unbounded_requests_only_aggregate_owned_readings(history, api_client, action):
    authenticate(api_client, history.holder.user)
    response = api_client.get(
        f"/api/v1/metering/readings/{action}/", {"metering_point": str(history.meter.pk)},
    )
    assert response.status_code == 200
    assert sum(row["in_kwh"] for row in response.data) == 5
    assert sum(row["out_kwh"] for row in response.data) == 3
    if action == "raw-data":
        assert sum(row["readings_count"] for row in response.data) == 8


def test_assignment_to_one_meter_does_not_grant_access_to_another(history, read_energy):
    meter = MeteringPointFactory(zev=history.holder.zev)
    MeteringPointAssignmentFactory(metering_point=meter, participant=history.other)
    add_readings(meter, "2026-01-10T12:00:00")
    assert read_energy(history.holder.user, meter, "2026-01-10") == {"in": 0, "out": 0}


def test_zev_filter_cannot_widen_participant_visibility(history, read_energy):
    foreign_meter = MeteringPointFactory()
    add_readings(foreign_meter, "2026-01-10T12:00:00")
    assert read_energy(
        history.holder.user, foreign_meter, "2026-01-10", zev_id=str(foreign_meter.zev_id),
    ) == {"in": 0, "out": 0}
    assert read_energy(
        history.holder.user, history.meter, "2026-01-10", zev_id=str(foreign_meter.zev_id),
    ) == {"in": 0, "out": 0}


def test_participant_without_assignments_sees_no_readings(history, read_energy):
    user = ParticipantUserFactory()
    ParticipantFactory(zev=history.holder.zev, user=user)
    assert read_energy(user, history.meter, "2026-01-10") == {"in": 0, "out": 0}


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_managers_can_read_assignment_gaps(history, read_energy, role):
    user = history.holder.zev.owner if role == "owner" else AdminFactory()
    assert read_energy(user, history.meter, "2026-01-21") == {"in": 1.25, "out": 0.75}


def test_owner_cannot_read_another_zevs_meter(history, read_energy):
    foreign_meter = MeteringPointFactory()
    add_readings(foreign_meter, "2026-01-10T12:00:00")
    assert read_energy(history.holder.zev.owner, foreign_meter, "2026-01-10") == {"in": 0, "out": 0}
