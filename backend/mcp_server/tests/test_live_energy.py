"""``live_energy``: the ZEV snapshot and forecast through MCP (SPEC-2026-live-energy-data §5.6)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.core.cache import cache

from metering.live import store
from metering.live.forecast_hours import floor_hour
from metering.live.testing import enable_live
from metering.models import ProductionForecastPoint, SourceHolder, SourceTarget, SupplementarySource
from accounts.models import UserRole
from testing import factories
from testing.helpers import make_user
from zev.models import MeteringPointType, ZevType

from .conftest import call_tool, client_for

pytestmark = pytest.mark.django_db

VALID_FROM = datetime(2025, 1, 1).date()


@pytest.fixture(autouse=True)
def live_on(db):
    cache.clear()
    enable_live()


def _result(response):
    body = response.json()
    assert "error" not in body, body
    return body["result"]


def _structured(response):
    return _result(response)["structuredContent"]


def _sample(source, watts, *, now):
    moment = now - timedelta(seconds=5)
    store.put_sample(
        store.LiveSample(
            source_id=str(source.pk), timestamp=moment, received_at=moment, meter_power_w=Decimal(str(watts)),
            production_w=None, consumption_w=None,
        )
    )


def _live_source(point, *, participant=None):
    return SupplementarySource.objects.create(
        zev=point.zev, metering_point=point, target=SourceTarget.METERING_POINT,
        held_by=SourceHolder.PARTICIPANT if participant else SourceHolder.ZEV, participant=participant,
        provider="push", provides_history=False, provides_live=True,
    )


@pytest.fixture
def community(owner_user):
    """A physical ZEV with a PV plant and two flats, each with a participant."""
    now = datetime.now(dt_timezone.utc).replace(microsecond=0)
    zev = factories.ZevFactory(owner=owner_user, zev_type=ZevType.ZEV)
    pv = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.PRODUCTION)
    flats = []
    for _ in range(2):
        flat = factories.MeteringPointFactory(zev=zev, meter_type=MeteringPointType.CONSUMPTION)
        participant = factories.ParticipantFactory(zev=zev, valid_from=VALID_FROM)
        factories.MeteringPointAssignmentFactory(metering_point=flat, participant=participant, valid_from=VALID_FROM)
        flats.append((flat, participant))
    return {"zev": zev, "pv": pv, "flats": flats, "now": now}


def _wire(community, *, pv=-8000, flat1=None, flat2=None):
    now = community["now"]
    _sample(_live_source(community["pv"]), pv, now=now)
    for (flat, participant), value in zip(community["flats"], (flat1, flat2)):
        if value is not None:
            _sample(_live_source(flat, participant=participant), value, now=now)


def _forecast(community, *rows):
    point = community["pv"]
    source = SupplementarySource.objects.create(
        zev=community["zev"], metering_point=point, held_by=SourceHolder.ZEV, provider="forecast_solar",
        provides_history=False, provides_live=False, provides_forecast=True,
    )
    current = floor_hour(datetime.now(dt_timezone.utc))
    for offset, power in rows:
        ProductionForecastPoint.objects.create(
            source=source, metering_point=point, timestamp=current + timedelta(hours=offset),
            power_w=Decimal(str(power)), fetched_at=current,
        )


class TestLiveEnergy:
    def test_exact_tier_gives_kw_figures_and_the_points(self, owner_mcp_client, community):
        _wire(community, pv=-8000, flat1=2000, flat2=3000)

        result = _structured(call_tool(owner_mcp_client, "live_energy", {"zev_id": str(community["zev"].pk)}))

        assert result["tier"] == "exact"
        assert (result["production_kw"], result["consumption_kw"], result["surplus_kw"]) == (8.0, 5.0, 3.0)
        assert result["local_share_pct"] == 100.0
        assert result["grid_import_kw"] == 0.0
        assert "exact" in result["note"]
        by_meter = {p["meter_id"]: p for p in result["points"]}
        assert by_meter[community["pv"].meter_id]["meter_power_kw"] == -8.0
        assert by_meter[community["pv"].meter_id]["live_state"] == "fresh"
        assert {p["participant_name"] for p in result["points"]} >= {community["flats"][0][1].display_name}
        assert "own" not in result

    def test_production_tier_withholds_consumption_spare_and_share(self, owner_mcp_client, community):
        _wire(community, pv=-6200)

        result = _structured(call_tool(owner_mcp_client, "live_energy", {"zev_id": str(community["zev"].pk)}))

        assert result["tier"] == "production"
        assert result["production_kw"] == 6.2
        assert result["consumption_kw"] is None
        assert result["surplus_kw"] is None
        assert result["local_share_pct"] is None
        assert "not known" in result["note"]
        assert result["coverage"]["consuming_fresh"] == 0

    def test_tier_none_has_no_figures(self, owner_mcp_client, community):
        result = _structured(call_tool(owner_mcp_client, "live_energy", {"zev_id": str(community["zev"].pk)}))

        assert result["tier"] == "none"
        assert result["production_kw"] is None
        assert result["surplus_kw"] is None

    def test_forecast_returns_hours_from_now_and_peak_windows_as_strings(self, owner_mcp_client, community):
        _wire(community)
        _forecast(community, (-2, 500), (0, 1000), (1, 3000), (2, 3200), (3, 800))

        forecast = _structured(
            call_tool(owner_mcp_client, "live_energy", {"zev_id": str(community["zev"].pk)})
        )["forecast"]

        # The hour already past is left out; the current hour is in.
        assert [h["power_kw"] for h in forecast["hours"]] == [1.0, 3.0, 3.2, 0.8]
        assert all(isinstance(h["start"], str) and h["start"].endswith("Z") for h in forecast["hours"])
        assert forecast["complete"] is True
        assert forecast["peak_windows"]
        assert all(isinstance(w["from"], str) for w in forecast["peak_windows"])
        assert "not a statement that power is spare" in forecast["note"]

    def test_forecast_hours_caps_the_rows_and_zero_keeps_the_windows(self, owner_mcp_client, community):
        _wire(community)
        _forecast(community, (0, 1000), (1, 3000), (2, 3200), (3, 800))
        zev_id = str(community["zev"].pk)

        capped = _structured(call_tool(owner_mcp_client, "live_energy", {"zev_id": zev_id, "forecast_hours": 2}))
        none = _structured(call_tool(owner_mcp_client, "live_energy", {"zev_id": zev_id, "forecast_hours": 0}))

        assert len(capped["forecast"]["hours"]) == 2
        assert none["forecast"]["hours"] == []
        assert none["forecast"]["peak_windows"]

    def test_forecast_hours_out_of_range_is_invalid_params(self, owner_mcp_client, community):
        response = call_tool(owner_mcp_client, "live_energy", {"zev_id": str(community["zev"].pk), "forecast_hours": 500})
        assert response.json()["error"]["code"] == -32602

    def test_admin_sees_any_zev(self, admin_mcp_client, community):
        _wire(community, pv=-8000, flat1=2000, flat2=3000)
        result = _structured(call_tool(admin_mcp_client, "live_energy", {"zev_id": str(community["zev"].pk)}))
        assert result["tier"] == "exact"

    def test_another_owners_zev_is_a_tool_error_without_data(self, community):
        stranger_user = make_user("stranger", UserRole.USER)
        factories.ZevFactory(owner=stranger_user)  # an MCP caller needs read access to some ZEV
        _wire(community, pv=-8000, flat1=2000, flat2=3000)

        result = _result(call_tool(client_for(stranger_user), "live_energy", {"zev_id": str(community["zev"].pk)}))

        assert result["isError"] is True
        assert "production_kw" not in result["structuredContent"]
        assert "not available" in result["content"][0]["text"]

    def test_flag_off_is_a_tool_error(self, owner_mcp_client, community):
        enable_live(False)
        result = _result(call_tool(owner_mcp_client, "live_energy", {"zev_id": str(community["zev"].pk)}))
        assert result["isError"] is True
        assert "switched off" in result["content"][0]["text"]
