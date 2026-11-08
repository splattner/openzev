# Feature Spec: Live energy data and production forecast

- Spec ID: SPEC-2026-live-energy-data
- Status: Completed
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-10-30
- Target Release: 1.28.0 (PRs 0 to 5); PR 6 in the next release
- Related Issues: [#1032](https://github.com/splattner/openzev/issues/1032); builds on [#925](https://github.com/splattner/openzev/issues/925), [#944](https://github.com/splattner/openzev/issues/944); notifications later through [#989](https://github.com/splattner/openzev/issues/989)
- Related ADRs: [0044](../adr/0044-live-energy-data-is-ephemeral-and-measured-only.md) (new: ephemeral, measured only, split only when exact, connection point); applies [0030](../adr/0030-supplementary-energy-data-is-not-billing-input.md), [0031](../adr/0031-integration-credentials-encrypted-under-a-dedicated-key.md), [0033](../adr/0033-energy-data-flag-follows-the-integration-key.md), [0013](../adr/0013-shared-allocation-service.md), [0026](../adr/0026-swiss-civil-time-for-billing.md), [0027](../adr/0027-per-zev-access-grants.md)
- Related specs: [supplementary energy data](2026-10-supplementary-energy-data.md) (the source this generalises), [buildings and sites](2026-10-buildings-and-sites.md) (building coordinates), [tokens and keys](2026-10-tokens-and-keys.md) (push tokens, personal API keys)
- Impacted Areas: backend | frontend | async jobs | docs

---

## 1. Problem and outcome

A participant can use more local energy only if they know when it is there. OpenZEV knows only the
past: the grid operator's 15-minute data arrives days later, and the participant's own energy data
([SPEC-2026-supplementary-energy-data](2026-10-supplementary-energy-data.md)) is synced hourly and
used for statistics. Nobody can see *now* whether starting the washing machine or charging the car
would run on the ZEV's own production.

**Outcome:**

1. Any metering point (producer, consumer, a household with generation behind the meter) and, in a
   physical ZEV, the grid connection point can report its **current power** from a device people
   already run (Home Assistant, Shelly, Solar Manager, an inverter, a smart-meter reader), through an
   HTTP push endpoint or Solar Manager's live stream.
2. Every participant sees what the ZEV produces right now and, when the data allows it exactly, how
   much is spare and how much of their own consumption is covered locally. Managers additionally see
   the value per metering point and the coverage.
3. A **production forecast** per plant (Solar Manager where connected, otherwise forecast.solar from
   the plant's parameters) shows when production is expected.
4. The same view is available read-only to automations (Home Assistant, n8n) through the participant's
   personal API key and through MCP.

Figures are **measured only**. Where data is missing, the UI says so; nothing is estimated
([ADR 0044](../adr/0044-live-energy-data-is-ephemeral-and-measured-only.md)). None of it is billing
input ([ADR 0030](../adr/0030-supplementary-energy-data-is-not-billing-input.md)).

### Worked example (physical ZEV, tier `exact`)

| Live value | W |
|---|---|
| PV production meter `P1` | −8 000 (feeding 8 kW into the ZEV) |
| Connection-point source | −3 000 (3 kW going out to the grid) |
| Flat 2 (has its own live source) | +1 200 |

`P = 8 000`, `N = −3 000`, so `C = max(P + N, 0) = 5 000`. Spare now `max(P − C, 0) = 3 000 W`;
local share `min(P, C) / C = 100 %`. Flat 2: `split_consumption(1200, 5000, 8000)` = 1 200 W local,
0 W grid. Without the connection-point source the snapshot is tier `production`: "The ZEV produces
8.0 kW right now. We don't know how much the other participants are using at the moment."

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Data model | Generalise `metering.SupplementarySource` (capabilities, ZEV-held sources, connection-point target); new `zev.PvPlane`; new `metering.ProductionForecastPoint`; `zev.Building.latitude/longitude` |
| Live store | `metering/live/store.py` on the Django cache (Valkey): latest sample + 5-minute buckets, TTL-bound |
| Live service | `metering/live/snapshot.py`: ZEV snapshot, tiers, per-participant split through `allocation.split` |
| Ingest | `POST /api/v1/metering/live/ingest/` with the source's push token |
| Pull | Solar Manager `/v3/users/{smId}/data/stream`, demand-driven |
| Forecast | Solar Manager `/v3/users/{smId}/data/forecast`; forecast.solar `estimate/watts`; hourly Celery refresh |
| API | Live snapshot, today's curve (with the viewer's own history), own-system series, forecast, compact `me` endpoint; source creation for the new capabilities and targets; PV plane CRUD |
| Frontend | "My energy system" for participants, "Live energy" for managers, viewers and admins (`/my-energy`, alias `/live`; §7.1): the live card and per-point table for managers on top, then Today, 7 days and Period views of the participant's own system (live and history combined, §7.1); (forecast from PR 5) the forecast chart; source setup for live/forecast; PV plane editor; building coordinates; i18n de/fr/it/en |
| Automation | Personal API keys (read-only) on the live endpoints; MCP tool `live_energy` |
| Operations | Feature flag, settings, throttles, system-health additions, audit events, backup registry |
| Docs | User guide chapter with Home Assistant and Shelly recipes; updates to the supplementary-energy-data and buildings specs |

### Out of scope

- Any effect on billing, allocation results, invoices, data-quality checks or the history-based
  statistics (ADR 0030).
- Estimating missing live values, consumption profiles or a consumption forecast. The forecast is
  **production only**; there is no "surplus expected" figure.
- Upper bounds ("at most y kW local") with incomplete coverage (ADR 0044).
- Persisting live values or aggregating them into history (ADR 0044). A "keep until the official
  data arrives" bridge is a follow-up idea. Showing history and live in one own line is allowed
  (ADR 0044, amendment).
- Battery flows. Batteries behind a meter are netted out at the meter; Solar Manager's battery fields
  are ignored.
- Device control. Automation happens in the participant's own system through the read-only API.
- Websockets/SSE; polling only.
- Notifications ("production expected from 11:00"): later through the notification center (#989).
- **Future ideas, not in v1** (§12): native MQTT ingest; a direct Home Assistant connection (pull with a
  long-lived token and a sensor picker); Shelly Cloud pull; Open-Meteo or MeteoSwiss as forecast
  sources.

## 3. Actors, permissions, and ZEV scope

All access follows the per-ZEV model of [ADR 0027](../adr/0027-per-zev-access-grants.md).

| Actor | Capability |
|---|---|
| `admin` | Everything below for any ZEV (support), including creating any source. |
| Manager of the ZEV | Create, edit, test, disconnect and delete **ZEV-held** sources: on a metering point that has no personal holder today, and the connection point. Holds their credential and push token. Manage PV planes and building coordinates. Read every source's status, per-point live values, coverage, and per-plant forecasts. For participant-held sources: the existing rights of the supplementary spec §3 (enable/disable, disconnect, purge, delete; never the credential). |
| Viewer of the ZEV | Read-only: the same live and forecast views as a manager, as viewers already read per-point readings. |
| `participant` who personally holds a metering point today | Create, edit, test, disconnect and delete **their own** source on it, with any capability their meter qualifies for (§4.1). Read the ZEV snapshot with their own block, today's curve and the ZEV forecast. |
| Any other current participant of the ZEV | ZEV snapshot (totals, tier, coverage counts), their own block if they have a live source, ZEV curve and ZEV forecast. **Never** another participant's per-point value. |
| Push client (token) | `POST /supplementary/ingest/` (history) and `POST /live/ingest/` (live) for exactly its own source. |
| Personal API key | The same live endpoints as its user; `read_only` keys suffice. |

"Personally holds today" is unchanged from the supplementary spec (active `PERSONAL` assignment on
the Swiss civil date). "Current participant" means the user is linked to a participant of the ZEV with
an active assignment today, or a non-ended participant record (the same rule the participant
dashboard uses).

**Consent.** Creating a source with `live` requires `consent: true`, and the consent text names who
sees what: for a participant-held source, "Managers and viewers of the ZEV see the live value of this
metering point. Other participants see only ZEV totals; if this metering point produces, your
production is part of the ZEV production everyone sees." For a ZEV-held source, the manager confirms
"This metering point is operated by the ZEV, and no participant holds it personally."

**Holder change.** The daily `disable_orphaned_supplementary_sources` task (renamed in behaviour, not
in name) disconnects:
- participant-held sources whose participant no longer holds the metering point (unchanged, reason
  `assignment_ended`);
- ZEV-held sources on a metering point that **has** a personal holder today (new, reason
  `personal_holder_assigned`): a household's live data must not keep flowing to the manager without
  the household's consent.
Connection-point sources are never orphaned.

**Backend permission classes:** `SupplementarySourcePermission` gains the `zev` role resolution
(`role_for` uses `source.zev`, and a ZEV-held source has no `owner`, so managers act with owner
rights on it). New `LiveEnergyPermission` (in `metering/live/permissions.py`): authenticated, and
`access.can_view(user, zev)` or "current participant of the ZEV"; the view narrows the payload by
role. The ingest view uses `SupplementaryPushAuthentication` + `IsPushSource` + the new
`LivePushThrottle`. `NotWhileImpersonating` stays on source creation and token rotation.

**Frontend routes:** one route, `/my-energy` (`MyEnergyPage`, `ProtectedRoute` with the active scopes
manager, viewer, admin and participant, like `/dashboard`); `/live` is an alias that redirects to it
(`AliasNavigate`, query kept). The live, history and forecast views of a participant's devices sit only
there; the dashboards show the grid operator's figures and, where the own-system card used to be, a note
linking here. The sidebar entry follows "Energy balance" for managers and viewers, named "Live energy"
(`nav.liveEnergy`), and "Dashboard" for participants, named "My energy system" (`nav.myEnergy`): the
same page, named for what each role sees on it (a manager or viewer sees the whole community, a participant their
own system). Rule (`showMyEnergyEntry` in `lib/myEnergy.ts`):
shown when `/live/enabled/` answers `true`, **or** the energy data feature is on (`/supplementary/sources/eligible/`
answers `200`) and the user has community-wide access (manager, viewer, admin) or holds a meter an own
system can be connected to (`historyEligible`); never for a former participant. The managers' and viewers' entry,
named "Live energy", is shown **only** while `/live/enabled/` answers `true`: with the flag off it would promise live data
the page does not have (the participant's "My energy system" entry keeps the rule above). Live setup sits on
`/me/metering-points` (holders) and, for the community's own sources, the **Energy data** tab of the ZEV
settings (`/zev-settings/energy`, managers; §7.3); PV planes are on the metering-point list, building coordinates
on the building form. The metering-point list itself says nothing about live or history data.

**Feature flag:** new `FeatureFlag.LIVE_ENERGY_DATA_ENABLED` (`"live_energy_data_enabled"`, env
override `FEATURE_LIVE_ENERGY_DATA_ENABLED`, default **off**). Effective only while
`SUPPLEMENTARY_ENERGY_DATA_ENABLED` is also effective, because live setup uses the source endpoints.
While off: live endpoints and the live ingest answer `404`, creating or patching a source with
`provides_live`/`provides_forecast` or `target = connection_point` answers `400`, beat tasks skip,
and no live UI renders. Existing sources and plant data are kept.

## 4. Data model

### 4.1 SupplementarySource (generalised)

The model keeps its name, table, audit action names (`supplementary_source.*`) and push-token format
(`ozs_…`). User-facing text calls it "energy data source". Changes against the supplementary spec §4.1:

| Field | Change | Type | Default | Notes |
|---|---|---|---|---|
| `zev` | **new** | `ForeignKey(zev.Zev, CASCADE)` | — | `related_name="energy_data_sources"`. Denormalised from `metering_point` for metering-point targets; the only anchor for the connection point. Backfilled in the migration |
| `target` | **new** | `CharField(20)` | `metering_point` | `SourceTarget`: `metering_point`, `connection_point` |
| `metering_point` | changed | `ForeignKey(zev.MeteringPoint, CASCADE, null=True)` | `None` | Was a `OneToOneField`. `related_name="supplementary_sources"`. Null exactly when `target = connection_point` |
| `held_by` | **new** | `CharField(20)` | `participant` | `SourceHolder`: `participant`, `zev` |
| `participant` | changed | `ForeignKey(zev.Participant, CASCADE, null=True)` | — | Set exactly when `held_by = participant` |
| `provides_history` | **new** | `BooleanField` | `True` | 15-minute history (today's feature). Existing rows: `True` |
| `provides_live` | **new** | `BooleanField` | `False` | Current power |
| `provides_forecast` | **new** | `BooleanField` | `False` | Production forecast |
| `provider` | changed | `CharField(20)` | — | `SupplementaryProvider` gains `forecast_solar` ("forecast.solar (public)") |
| `live_last_seen_at` | **new** | `DateTimeField(null)` | `None` | Last accepted live sample, written at most once per `LIVE_LAST_SEEN_RESOLUTION_S` (30 s) so a 10-second feed does not write the row 6 times a minute. Status and health only; the resolution stays well below `LIVE_MAX_AGE_S`, or a feed pushing every 10 s would read as stale between two writes |

All other fields keep their meaning. `synced_through`, `covers_from`, `reconciliation` describe the
history capability only.

**Constraints (`Meta.constraints`):**
- `uniq_source_history_per_mp`: `UniqueConstraint(fields=["metering_point"], condition=Q(provides_history=True))`.
- `uniq_source_live_per_mp`: same with `provides_live=True`.
- `uniq_source_forecast_per_mp`: same with `provides_forecast=True`.
- `uniq_connection_point_per_zev`: `UniqueConstraint(fields=["zev"], condition=Q(target="connection_point"))`.
- `source_target_consistent`: `CheckConstraint`: (`target=metering_point` and `metering_point` not null)
  or (`target=connection_point` and `metering_point` null and `provides_live` and not
  `provides_history` and not `provides_forecast` and `held_by=zev`).
- `source_holder_consistent`: (`held_by=participant` and `participant` not null) or (`held_by=zev` and
  `participant` null).
- `source_has_capability`: at least one `provides_*` is true.

**Provider × capability matrix** (validated in `clean()` and the serializer):

| Provider | history | live | forecast | Credential |
|---|---|---|---|---|
| `solar_manager` | yes | yes (`/data/stream`) | yes (`/data/forecast`) | refresh token (ADR 0031) |
| `push` | yes (`/supplementary/ingest/`, CSV) | yes (`/live/ingest/`) | no | push token |
| `forecast_solar` | no | no | yes | none (instance-wide `FORECAST_SOLAR_API_KEY` optional) |

**Eligibility (`clean()`):**
- `provides_history` requires `metering_point.has_behind_meter_generation` (unchanged) and
  `held_by = participant` (history describes a household).
- `provides_live` on a metering point: any `meter_type`, `metering_point.is_active`.
- `provides_forecast` requires `meter_type` in `production` / `bidirectional`, and for
  `forecast_solar` at least one `PvPlane` and building coordinates (§4.3).
- `target = connection_point` requires `zev.zev_type = zev` (a vZEV has no shared main meter).
- `zev_id == metering_point.zev_id` for metering-point targets.
- At creation (serializer, not `clean()`): `held_by = participant` requires the requesting user (or
  the admin-named participant) to hold the metering point personally today; `held_by = zev` requires
  that **nobody** holds it personally today, and the requester to be a manager or admin.

**Cross-model rule (changed):** clearing `has_behind_meter_generation` is refused only while a source
with `provides_history` exists. `MeteringPoint._has_supplementary_source()` becomes
`_has_history_source()`.

**Serializer:** `SupplementarySourceSerializer` gains read fields `zev`, `target`, `held_by`,
`provides_history`, `provides_live`, `provides_forecast`, `live_last_seen_at`, `live_state`
(`SerializerMethodField`: `fresh`, `stale`, `never`, or `null` without `provides_live`), and write
fields `target`, `provides_history`, `provides_live`, `provides_forecast` (create only; capabilities
can be switched on and off later by the same people who may create), and `held_by` (create only;
admins and managers, default `participant`). `metering_point_meter_id` is `null` for the connection
point.

`MeteringPointSerializer.supplementary_source_status` keeps its meaning for the history source and
gains `live_state` (`fresh` / `stale` / `never` / `null`) under the same visibility rule.

### 4.2 ProductionForecastPoint

**Model:** `metering.models.ProductionForecastPoint`. One hour of expected production for one
producing metering point, from its forecast source.

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `BigAutoField` pk | — | |
| `source` | `ForeignKey(SupplementarySource, CASCADE)` | — | `related_name="forecast_points"`; the source with `provides_forecast` |
| `metering_point` | `ForeignKey(zev.MeteringPoint, CASCADE)` | — | `related_name="production_forecast"`; denormalised |
| `timestamp` | `DateTimeField` | — | UTC start of the hour |
| `power_w` | `DecimalField(12,1)` | — | Mean expected power over the hour, `>= 0` |
| `power_min_w` / `power_max_w` | `DecimalField(12,1, null)` | `None` | Solar Manager's `pWmin` / `pWmax`; `null` for forecast.solar |
| `fetched_at` | `DateTimeField` | — | When this value was retrieved |

**Meta:** `ordering = ["metering_point", "timestamp"]`;
`UniqueConstraint(fields=["metering_point", "timestamp"], name="uniq_forecast_point_mp_ts")`;
`CheckConstraint(power_w >= 0)`. A refresh replaces the source's future points in one transaction.
Points older than 24 h are deleted by the refresh task. **Excluded from backups and the transfer
archive** (`EXCLUDED_MODELS`, reason "derived, refetched within an hour").

### 4.3 PvPlane and building coordinates

**Model:** `zev.models.PvPlane`. One roof plane of a plant behind a producing metering point. A plant
on an east and a west roof has two.

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` pk | `uuid4` | |
| `metering_point` | `ForeignKey(MeteringPoint, CASCADE)` | — | `related_name="pv_planes"`; `meter_type` in `production`, `bidirectional` |
| `label` | `CharField(100)` | `""` | "South roof" |
| `peak_power_kwp` | `DecimalField(7,2)` | — | `> 0`, `<= 10 000` |
| `tilt_deg` | `PositiveSmallIntegerField` | — | `0` (flat) to `90` (vertical) |
| `azimuth_deg` | `SmallIntegerField` | — | `-180..180`, forecast.solar convention: `0` south, `-90` east, `90` west, `±180` north |
| `created_at` / `updated_at` | `DateTimeField` | auto | |

At most `PV_PLANES_MAX_PER_METERING_POINT` (4) per metering point. Serializer `PvPlaneSerializer`:
all fields, `id`/timestamps read-only. Included in backups and the transfer archive (ZEV section).

**`zev.Building` gains** `latitude` (`DecimalField(8,5, null)`) and `longitude`
(`DecimalField(8,5, null)`), editable by managers, with a "Locate from address" action that fills
them from `zev.geocoding.geocode_building_footprint` (centroid, `footprint_centroid`). Requests to forecast.solar send the
coordinates rounded to **2 decimals** (~1 km); the precise values never leave the instance.
`BuildingSerializer` gains both fields (writable like the rest of the building, and so tracked by the
`building.update` audit event). "Locate from address" is the stateless `POST /zev/buildings/locate/`
(manager, `{address_line1, postal_code, city}` → `{latitude, longitude}`, the mean of the corners of the
building's mapped outline from `geocode_building_footprint`): it saves nothing, the form saves the values like any
other field, and it answers `400` when the address does not resolve to a mapped building and `429` for a
second lookup by the same user within two seconds (Nominatim's usage policy).

### 4.4 Live samples (cache, not a model)

`metering/live/store.py`, on the Django `default` cache (Valkey in production, `LocMemCache` in
tests), keys versioned `live:v1:`. A `LiveSample` is
`(source_id, timestamp: aware UTC, received_at, meter_power_w: Decimal, production_w: Decimal | None, consumption_w: Decimal | None)`.

| Key | Value | TTL |
|---|---|---|
| `live:v1:src:{source_id}:latest` | the sample (JSON) | `LIVE_MAX_AGE_S` |
| `live:v1:src:{source_id}:b:{bucket_epoch}` | `{n, sum_meter_w, sum_production_w, n_production, sum_consumption_w, n_consumption}` | `LIVE_CURVE_RETENTION_H` |
| `live:v1:src:{source_id}:last_push` | `received_at` (rate floor) | `LIVE_MIN_PUSH_INTERVAL_S` |
| `live:v1:src:{source_id}:last_pull` | `1` (`cache.add` slot of `poll_live_sources`) | 80 % of `LIVE_PULL_INTERVAL_S` |
| `live:v1:src:{source_id}:backoff` | `1` (set on a `429`) | `Retry-After`, at least `LIVE_PULL_INTERVAL_S`, at most 15 min |
| `live:v1:watch:zev:{zev_id}` | `1` | `LIVE_WATCH_TTL_S` |
| `live:v1:sm-access:{source_id}` | Solar Manager bearer token, Fernet-encrypted under `INTEGRATION_ENCRYPTION_KEYS` | 50 min |

`bucket_epoch = floor(timestamp, LIVE_CURVE_BUCKET_S)`. A bucket's value is the mean of its samples
(`sum / n`); a bucket without samples is a gap. Bucket writes are read-modify-write; one writer per
source and the rate floor make lost updates negligible, and a lost sample only lowers `n`.

**Sign convention:** `meter_power_w > 0` is power drawn **in** through the meter (from the grid or the
ZEV); `< 0` is power fed **out**. This is the quantity allocation uses: a household with generation
behind its meter contributes its export to production, not its gross output. `production_w` and
`consumption_w` are optional gross values for the household's own view only; they never enter ZEV
totals.

### 4.5 Settings

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `LIVE_MAX_AGE_S` | `env.int` | `60` | A sample older than this is missing |
| `LIVE_MIN_PUSH_INTERVAL_S` | `env.int` | `5` | A second push within this window answers `429` |
| `LIVE_CURVE_BUCKET_S` | `env.int` | `300` | Curve resolution |
| `LIVE_CURVE_RETENTION_H` | `env.int` | `48` | Bucket lifetime |
| `LIVE_WATCH_TTL_S` | `env.int` | `120` | How long a viewed ZEV keeps its pull sources polled |
| `LIVE_PULL_INTERVAL_S` | `env.int` | `30` | Beat period of `poll_live_sources`, and the pace of a pulled source (a source is claimed for 80 % of it, `store.PULL_FLOOR_SHARE`, so a slightly early tick still pulls). Keep it below `LIVE_MAX_AGE_S`: `metering.W003` warns otherwise |
| `LIVE_LAST_SEEN_RESOLUTION_S` | `env.int` | `30` | `live_last_seen_at` write resolution |
| `LIVE_MAX_ABS_POWER_W` | `env.int` | `5000000` | Plausibility cap for any value |
| `FORECAST_REFRESH_INTERVAL_S` | `env.int` | `3600` | Beat period of `refresh_production_forecasts` |
| `FORECAST_HORIZON_H` | `env.int` | `72` | Upper cap on the hours stored from the current hour on. The providers reach less: forecast.solar's public tier today and tomorrow, Solar Manager three days |
| `FORECAST_SOLAR_BASE_URL` | `env` | `https://api.forecast.solar` | Fixed host; overridable only for test stubs |
| `FORECAST_SOLAR_API_KEY` | `env` | `""` | Optional paid key (higher limits, more planes) |
| `FORECAST_SOLAR_MAX_CALLS_PER_HOUR` | `env.int` | `10` | Instance-wide budget over a **rolling** hour (the public tier allows 12 per calling IP); every roof plane is one call |
| `FORECAST_SOLAR_MIN_REFRESH_S` | `env.int` | `10800` | A forecast.solar source is refreshed at most this often (a manual refresh skips it, the budget still applies) |
| `PV_PLANES_MAX_PER_METERING_POINT` | `env.int` | `4` | |
| `DEFAULT_THROTTLE_RATES["live_push"]` | rate | `900/hour` | Per push token (one sample per 4 s on average), on top of the 5-second floor |
| `DEFAULT_THROTTLE_RATES["live_read"]` | rate | `720/hour` | Per user/API key on the live read endpoints (one every 5 s) |

## 5. API contracts

New endpoints under `/api/v1/metering/live/` (registered in `metering/urls.py`, views in
`metering/live/views.py`). All answer `404` while the live flag is not effective, except
`/live/enabled/`, which answers `200 {"enabled": false}`.

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/live/enabled/` | GET | `IsAuthenticated` | `{"enabled": bool}`: the live flag is effective (`live_feature_enabled()`, the condition `LiveFeatureMixin` uses). Never `404`, so the nav and the page can ask; `401` when anonymous. Function view `live_enabled`, mirrors `/feasibility/enabled/` |
| `/live/ingest/` | POST | `SupplementaryPushAuthentication`, `IsPushSource`, `LivePushThrottle` | One sample for the token's source (§5.1). `202 {"accepted": true}` |
| `/live/zevs/{zev_id}/` | GET | `LiveEnergyPermission` | ZEV snapshot (§5.2), narrowed by role. It also marks the ZEV as watched (`store.mark_watched`, `live:v1:watch:zev`, PR 4) |
| `/live/zevs/{zev_id}/curve/` | GET | `LiveEnergyPermission` | `?date=YYYY-MM-DD` (civil date, default today, at most `LIVE_CURVE_RETENTION_H` back), `participant_id` (optional, §5.3): 5-minute buckets plus the viewer's own history of the day (§5.3). Marks the ZEV as watched too (PR 4) |
| `/live/zevs/{zev_id}/forecast/` | GET | `LiveEnergyPermission` | Hourly ZEV production forecast for `FORECAST_HORIZON_H` (§5.4) |
| `/live/me/` | GET | authenticated (JWT or personal API key) | Compact snapshot for each ZEV the caller is a current participant of (§5.5), made for Home Assistant `rest` sensors and n8n |

Not under `/live/` and not behind the live flag: `GET /supplementary/zevs/{zev_id}/own-series/` (§5.3a),
which answers `404` only while the energy data flag is off.

Source management stays on `/supplementary/sources/` (supplementary spec §5) with these changes:

- `POST /sources/` accepts `target`, `held_by`, `provides_history`, `provides_live`,
  `provides_forecast` (defaults: `metering_point`, `participant`, `true`, `false`, `false`).
  `provider = forecast_solar` needs neither credential nor consent and returns no token. A
  `push` source with only `provides_live` returns its `push_token` once, as today. A Solar Manager
  source with only live is verified with one `/data/stream` call (`verify_live`) instead of a history
  interval; one with history (alone or with live) as before. A Solar Manager source is participant-held
  on a metering point only: `held_by = zev` and `target = connection_point` answer
  `400 {"provider": ["A Solar Manager key is personal. ..."]}` (the key is a personal credential, ADR 0031).
  `PATCH {provides_live: true, consent: true}` on a Solar Manager history source adds live with the stored
  key (refused with a field error when the source holds no key); `PATCH {provides_history: true, ...}`
  on a live-only one queues a sync. Capability conflicts (a second live source on the metering point) answer
  `400 {"provides_live": ["This metering point already has a live data source."]}`.
- `GET /sources/eligible/` adds, per held metering point, `eligible_capabilities`
  (`["history", "live", "forecast"]` subset) and the ids of existing sources per capability, and is no
  longer limited to metering points with `has_behind_meter_generation` while the live flag is on.
- New `GET /sources/zev-eligible/?zev_id=` (manager, admin): metering points of the ZEV with no
  personal holder today, their eligible capabilities and sources, and whether the connection point
  can be added (`zev_type = zev`, none yet).
- `POST /sources/{id}/test/` for a live-only Solar Manager source fetches one `/data/stream` sample
  (`check_live`); with both capabilities it checks history and then live; a push source without history
  still answers `400 "This source does not provide history."`. `/sync/` and `/reconciliation/` still need
  `provides_history`.
- `POST /sources/{id}/sync/` on a forecast source queues a forecast refresh (same 5-minute floor; it skips the
  forecast.solar minimum interval, not the call budget). `POST /sources/{id}/test/` on a `forecast_solar`
  source fetches and stores the forecast now (`400` with the safe message when it fails or when the hourly call budget is used
  up); on a Solar Manager source with a forecast it reads the forecast once with the stored key (`check_forecast`).
- **Forecast sources.** `provider = forecast_solar` is a forecast-only source: `provides_forecast` defaults to
  `true`, `provides_history` to `false`, any other capability answers `400 {"provider": [...]}`, it takes no
  credential, id or consent and returns no token, and it is created like any other source: by the holder of
  a producing metering point (participant-held) or by a manager on one nobody holds (`held_by = zev`). Creating
  it (or adding `provides_forecast` to a forecast.solar source) needs the plant's roof planes and the building's
  coordinates (`400 {"provides_forecast": ["Add the roof planes ... first."]}`) and a producing, active metering
  point (`400` on `metering_point` otherwise). A push source cannot provide a forecast (`400`). A Solar Manager
  source gains `provides_forecast` by `PATCH` with the holder's consent and the stored key, and loses it with
  `{provides_forecast: false}`, which also deletes its forecast points. The forecast needs the live flag
  (`400 {"provides_forecast": ["Live energy data is not enabled."]}` otherwise). Creating or enabling a forecast
  source queues a refresh. `GET /sources/eligible/` and `zev-eligible/` list `forecast` in
  `eligible_capabilities` of an active producing or bidirectional point. A ZEV-held forecast source is
  disconnected, like any ZEV-held source, once somebody holds the meter personally (§6.5).

PV planes: `GET/POST /api/v1/zev/metering-points/{id}/pv-planes/`,
`GET/PATCH/DELETE /api/v1/zev/metering-points/{id}/pv-planes/{plane_id}/` (managers and admins write;
anyone who can read the metering point reads: `PvPlaneViewSet`, scoped through the metering point). The
metering point is the URL's whatever the body says, cannot be changed afterwards, must be a producing or bidirectional
meter, and a point has at most `PV_PLANES_MAX_PER_METERING_POINT` planes (`400` on `metering_point`). Audited
`pv_plane.create/update/delete` (category `METERING`, target `zev.PvPlane`).

### 5.1 Live ingest

```json
POST /api/v1/metering/live/ingest/
Authorization: Bearer ozs_<prefix>_<secret>
{ "timestamp": "2026-10-30T11:02:10Z", "meter_power_w": -3120.5,
  "production_w": 5400, "consumption_w": 2279.5 }
```

- `timestamp` optional; absent means the server's receive time. When present it must be aware, not
  more than 10 s in the future, and not older than `LIVE_MAX_AGE_S` (a stale sample is rejected,
  `400 {"timestamp": ["Sample is older than 60 seconds."]}`).
- `meter_power_w` required; `production_w`, `consumption_w` optional and `>= 0`. All finite and within
  `±LIVE_MAX_ABS_POWER_W`. Rounded half-up to 1 decimal.
- For a connection-point source `meter_power_w` is the net power at the grid connection.
- `401` for a bad token (one message), `403` for a disabled source or a source without
  `provides_live`, `429` (with `Retry-After`) within `LIVE_MIN_PUSH_INTERVAL_S` of the previous accepted
  sample or past the `live_push` throttle.
- Accepted samples write `latest` and the bucket, and touch `live_last_seen_at` at its resolution. Not
  audited per sample.
- Holder clipping: a participant-held source whose holder no longer holds the metering point today
  is rejected with `403` (the daily task disconnects it later). So is a ZEV-held source on a metering
  point somebody now holds personally, for the same reason as the task's `personal_holder_assigned`.
  A disabled ZEV accepts nothing (`403`).

### 5.2 ZEV snapshot

`metering/live/snapshot.py`, `zev_snapshot(zev, *, now, viewer) -> dict`. Definitions:

- *Fresh*: a source with `provides_live`, `enabled`, whose `latest` exists and
  `now − timestamp <= LIVE_MAX_AGE_S`.
- *Producing points*: active metering points of the ZEV with `meter_type` in `PRODUCTION_METER_TYPES`, **except** a bidirectional point with no live source and `has_behind_meter_generation = false`
  (`Topology.declared_idle`): the manager has declared that nothing feeds in there, so it reads 0 as a producer and does not
  hold the tier at `none` (ADR 0044, amendment). A point with a source gone quiet, a `production` point and a point with
  generation behind its meter are never idle. The point still counts as a consuming point and in `coverage.points`.
  *Consuming points*: `CONSUMPTION_METER_TYPES` (`allocation.read_model`). A bidirectional point is in
  both, as in billing.
- `P = Σ max(−meter_power_w, 0)` over producing points; `C_sum = Σ max(meter_power_w, 0)` over
  consuming points. A production-type point's own draw is ignored, as in billing.
- `N` = the connection-point source's `meter_power_w`.

**Tier** (ADR 0044):
- `none` when no producing point exists, or any producing point is not fresh (declared-idle points above are not producing points).
- `exact` when not `none` and either every consuming point is fresh (`C = C_sum`), or the ZEV is
  `zev_type = zev` and the connection-point source is fresh (`C = max(P + N, 0)`;
  `consumption_basis = "connection_point"`; if both hold, `C_sum` wins, basis `"all_points"`).
- `production` otherwise.

**Payload** (participant view; values in W as numbers with one decimal, `null` where the tier does not
allow them):

```json
{
  "zev_id": "…", "as_of": "2026-10-30T11:02:10Z", "tier": "exact",
  "consumption_basis": "connection_point",
  "production_w": 8000.0, "consumption_w": 5000.0,
  "surplus_w": 3000.0, "grid_import_w": 0.0, "local_share_pct": 100.0,
  "coverage": { "producing_points": 1, "producing_fresh": 1,
                "consuming_points": 6, "consuming_fresh": 1, "connection_point": "fresh",
                "live_sources": 2, "points": 7, "points_fresh": 2 },
  "own": {
    "consumption_w": 1200.0, "local_w": 1200.0, "grid_w": 0.0,
    "production_w": null, "to_zev_w": null, "to_grid_w": null,
    "gross": { "production_w": null, "consumption_w": null },
    "complete": true, "points": 1, "points_fresh": 1
  },
  "max_age_s": 60
}
```

- `coverage.live_sources` is the number of enabled sources with `provides_live` on active metering
  points, plus the connection-point source (`Topology.live_sources`). It is a count only, present for
  every viewer, and tells the frontend whether there is anything live to show (zero: hide the card).
- `coverage.points` / `coverage.points_fresh` count **distinct** active metering points of the ZEV and
  how many of them have a fresh value. A bidirectional point is in both per-role counts but once here,
  so they say how many points report. The card no longer shows them (the per-point table's summary counts the quiet ones); they stay in the payload. Present for every viewer.
- `as_of` is the **oldest** sample timestamp used. `connection_point` is `fresh`, `stale`, `never` or
  `null` (no such source, or a vZEV).
- `production_w` is shown for tiers `production` and `exact`; `consumption_w`, `surplus_w =
  max(P − C, 0)`, `grid_import_w = max(C − P, 0)` and `local_share_pct = min(P, C) / C × 100`
  (`null` when `C = 0`) for `exact` only.
- `own` is present when the viewer is a current participant with at least one personally held
  metering point with `provides_live`. `own.consumption_w` / `own.production_w` are the measured sums
  over the viewer's personally held points (shown at any tier, when every such point is fresh:
  `complete`). The split (`local_w`/`grid_w` via `split_consumption(x, C, P)`;
  `to_zev_w`/`to_grid_w` via `split_production(p, P, C)`) only at tier `exact`. If the inputs violate
  the split's contract (e.g. `x > C` from timing between sources with `consumption_basis =
  "connection_point"`), the split is `null` and `own.split_withheld_reason = "inconsistent"`.
  `own.gross` comes from the optional `production_w`/`consumption_w` of the viewer's sources.
  Community-mode metering points never appear in anyone's `own`.
- **Manager/viewer/admin view** adds `points[]`:
  `{metering_point_id, meter_id, meter_type, participant_name | null, held_by, live_state,
  meter_power_w | null, age_s | null, source_id | null}` for every active metering point, plus
  `{"target": "connection_point", …}` when present, and their own `own` block if they are participants
  too.
- Snapshots are computed per request: three small queries (active points, live sources, personal
  assignments) and one cache `get_many`. A topology cache was considered and left out until the
  polling load shows a need; it would have to be invalidated on source, point and assignment changes.
- Reads answer `404` (not `403`) for a ZEV the caller may not see, a former participant, and, for
  everyone but admins, a disabled ZEV.

### 5.3 Curve

`GET /live/zevs/{id}/curve/?date=2026-10-30&participant_id=…` → buckets of the civil day
(`allocation.validity`), oldest first, and the viewer's own history of that day:

```json
{ "date": "2026-10-30", "bucket_s": 300,
  "buckets": [ { "start": "2026-10-30T10:00:00Z", "tier": "exact",
                 "production_w": 7800.0, "consumption_w": 5100.0, "surplus_w": 2700.0,
                 "own_consumption_w": 1150.0, "own_production_w": null, "own_local_w": 1150.0 } ],
  "own_history": [ { "start": "2026-10-29T23:00:00+00:00", "consumption_w": 2000.0, "production_w": 1000.0 } ],
  "own_history_through": "2026-10-30T09:00:00Z" }
```

The tier rule of §5.2 is applied per bucket: a point counts as fresh in a bucket when its bucket has
`n > 0`. Values are bucket means, so a bucket's split is a split of means; that is labelled
"indicative" in the UI like everything live. Manager view adds `points[]` per bucket (`meter_power_w`
per point id). Buckets with tier `none` carry only `start` and `tier`. `own_production_w` joins
`own_consumption_w` wherever the viewer has a live point (`null` for a side they have no point on).

- `own_history`: one row per 15-minute interval of that civil day that a history source of the viewer's
  participant(s) has stored (`metering.supplementary.own_series.own_history_of_day`, through
  `stats.gross_energy`, so only intervals inside personal-holding windows between `covers_from` and
  `synced_through` count; community-mode points never). Power is the interval's kWh x 4000 W, summed over
  several sources; a missing interval is a missing row. `[]` without a source. `own_history_through` is
  the **earliest** `synced_through` of those sources (ISO, `Z`), `null` without one.
- **Precedence (display rule, ADR 0044 amendment).** The server never merges: `own_history` is stored
  data, the `own_*` bucket values are live. The merge is the pure helper `todayRows` in
  `frontend/src/lib/myEnergy.ts` (tested): a history row is used before `own_history_through`, a live
  bucket from it on, and a gap where neither has a value. The ZEV totals are live only.
- `participant_id` (optional): for a manager, viewer or admin, whose own values: the `own_*` bucket
  values then describe that participant's live points and `own_history` their history. A participant
  may name only themselves (`403` otherwise, `404` for an unknown participant or one of another ZEV,
  `400` for a malformed id). Without it, "own" is the signed-in user's participants in this ZEV. A
  manager sees any point's value in `points[]` already, so this widens nothing.
- The endpoint stays behind the live flag. With live off the page reads the same history through §5.3a.

### 5.3a Own-system series

`GET /api/v1/metering/supplementary/zevs/{zev_id}/own-series/?date_from&date_to&bucket=quarter|hour|day[&participant_id]`
(`metering/supplementary/views.py::OwnSeriesView`, logic in `metering/supplementary/own_series.py`). It
sits under the supplementary API because it is history; it is gated on the **energy data** flag only
(`require_feature()`, `404` while off), so "My energy system" works with history alone. `IsAuthenticated`
plus `readable_zev` (managers, viewers and admins of the ZEV, and its *current* participants; anybody
else `404`). Whose figures: `participant_ids_for` (a participant: their own, `participant_id` only
themselves; a manager, viewer or admin: any participant of the ZEV, else their own; same rule as the
dashboards' selected participant).

```json
{ "participant_id": "…" | null, "date_from": "2026-10-24", "date_to": "2026-10-30", "bucket": "hour",
  "history_through": "2026-10-30T09:00:00Z" | null,
  "gross": { "...": "GrossEnergy of supplementary spec §5.1, with a timeline" } | null }
```

`gross` is `stats.gross_energy(ids, civil_window(date_from, date_to), bucket_key)`: kWh for consumption,
production, import, export and self-consumption per bucket, the two rates, `coverage_pct` and
`rates_withheld_reason` exactly as on the dashboards; `null` when no source expects data in the range.
Bucket labels: `quarter` the interval start (UTC `isoformat`), `hour` the UTC hour, `day` the civil day
(`surfaces.bucket_key_for`). `participant_id` in the answer is the one asked about, `null` when the
user has none or several. Limits, `400` with a field error: `date_from` and `date_to` required
(`YYYY-MM-DD`), end not before start, and at most 3 days for `quarter`, 31 for `hour`, 400 for `day`;
an unknown `bucket` is `400`. Display only: nothing is written, and nothing here is read by billing
(ADR 0030).

### 5.4 Forecast

```json
{ "zev_id": "…", "horizon_h": 72, "complete": true,
  "plants": 1, "plants_with_forecast": 1, "fetched_at": "2026-10-30T10:00:12Z",
  "hours": [ { "start": "2026-10-30T11:00:00Z", "power_w": 7400.0, "min_w": 6100.0, "max_w": 8200.0 } ],
  "peak_windows": [ { "date": "2026-10-30", "from": "2026-10-30T10:00:00Z", "to": "2026-10-30T14:00:00Z", "peak_w": 7900.0 } ] }
```

- Sum over the active producing points (`production`, `bidirectional`) that have an enabled forecast source;
  `hours` start with the current civil day (Europe/Zurich), so the hours already past can be drawn, up to
  `FORECAST_HORIZON_H` ahead. `min_w`/`max_w` only when every summed point has
  them. `plants` counts the active producing points and `plants_with_forecast` those with stored hours. `complete` is false when a producing point has no forecast; the UI then says "Forecast for 1
  of 2 plants".
- `peak_windows`: per civil day, the longest contiguous run of hours with `power_w >= 50 %` of that
  day's maximum (ties: the earliest). Production only; never a surplus claim.
- Manager view adds `per_plant[]` with the same `hours` per metering point.

### 5.5 `me`

`GET /live/me/` → `{"zevs": [ { "zev_id", "zev_name", "tier", "as_of", "production_w", "surplus_w",
"local_share_pct", "own_consumption_w", "own_local_w", "forecast_next_peak": {"from","to","peak_w"} | null } ]}`.
Flat keys so a Home Assistant `rest` sensor can read them with `value_template` /
`json_attributes_path`. Throttled `live_read`. Works with a `read_only` personal API key.

### 5.6 MCP tool `live_energy`

`mcp_server/tools/live_energy.py` (SPEC-2026-mcp-server §6.8a), read-only, for managers, viewers and admins (the
MCP endpoint refuses participants, so the participant's own view stays on `/live/me/`, §5.5).
Input: `zev_id` (uuid, required), `forecast_hours` (integer 0 to 72, default 24; `0` returns the peak
windows only). It makes two allow-listed sub-requests, `live-snapshot` (§5.2) and `live-forecast`
(§5.4), so the live permission, the flag and the tiers are decided by those views and the tool adds
no rule of its own. Like the page, a call marks the ZEV as watched (Solar Manager is then polled).

Output, powers in **kW** (the MCP convention is kWh for energy and kW for power; three decimals):
`zev_id`, `tier`, `note` (what the tier allows to say, in words), `as_of`, `max_age_s`,
`consumption_basis`, `production_kw`, `consumption_kw`, `surplus_kw`, `grid_import_kw`,
`local_share_pct` (each `null` where the tier does not allow it, exactly as in §5.2), `coverage` (as
§5.2), `points[]` (`meter_id`, `target`, `meter_type`, `participant_name`, `held_by`, `live_state`,
`meter_power_kw` signed like the meter, `age_s`; at most 100, then `points_truncated` and `points_total`)
and `forecast` (`complete`, `plants`, `plants_with_forecast`, `fetched_at`, a `note` saying it is production
only, `hours[]` of `{start, power_kw, min_kw, max_kw}` from the current UTC hour on, `peak_windows[]` of
`{date, from, to, peak_kw}` that have not ended). Datetimes are ISO strings in UTC. The caller's `own`
block and the snapshot's ids (`metering_point_id`, `source_id`) are left out. A `404` from either view,
which is what a switched-off feature and a ZEV the caller may not see both answer, becomes a tool error
("Live energy data is not available: the feature is switched off, or the ZEV was not found."); other
failures carry the view's own message.

## 6. Async and integration behavior

### 6.1 Solar Manager live (`metering/supplementary/solar_manager.py`)

- `SolarManagerProvider.fetch_live(source) -> LiveSample` calls `GET /v3/users/{smId}/data/stream`
  (`SolarManagerClient.stream`, API v1.88.11, same HTTP hardening as `range`). The pure mapper
  `map_stream(payload, source_id, now)`: `t` → `timestamp` (aware UTC; missing, naive or unreadable → now;
  in the future → now); `meter_power_w = iW − eW`; `production_w = pW`; `consumption_w = cW`, each to one
  decimal. Battery and device fields are ignored. A missing or non-numeric `iW` or `eW` is no sample
  (`ProviderError`, never a zero); a missing `pW`/`cW` is `None`, a negative one is left out; a value that
  is not finite or beyond `LIVE_MAX_ABS_POWER_W` rejects the whole payload.
- `verify_live(external_id, credential)` and `check_live(source)` do the same with one stream sample, for
  creating, replacing the key of and testing a live-only source; the `Provider` protocol lists them next to
  `fetch_live`.
- Bearer tokens are cached in `live:v1:sm-access:{source_id}` (encrypted, 50 min) so a 30-second poll
  does not rotate the refresh token each time; the refresh runs under the existing `select_for_update`
  lock when the cache is empty (the rotated key is persisted before the bearer token is used). A cached
  token the vendor refuses is dropped and one fresh exchange is tried before the failure counts as an auth
  failure; an unreadable cache entry is dropped. The entry is deleted when the source is disconnected
  (`SupplementarySource.clear_credential`, which the orphan sweep uses too), deleted, or its key replaced.
- Error mapping and HTTP hardening as in the supplementary spec §6.2. An auth failure sets
  `reconnect_required` for the whole source (all capabilities).

### 6.2 `poll_live_sources` (beat, `LIVE_PULL_INTERVAL_S`)

`LiveSnapshotView` and `LiveCurveView` mark the ZEV watched (`store.mark_watched`, `live:v1:watch:zev:{id}`
for `LIVE_WATCH_TTL_S`); `/live/me/` does not. When the live flag is effective, `poll_live_sources` queues
`pull_live_source.delay(id)` for every enabled `solar_manager` source with `provides_live` that is not
`reconnect_required`, whose ZEV is not disabled and is watched, that is not in back-off and whose pull slot
(`store.claim_pull_slot`, 80 % of `LIVE_PULL_INTERVAL_S`) is free. A broker error on one source is logged
and does not stop the others. Pulls only while someone looks, so an unviewed ZEV costs no vendor calls.

`pull_live_source(source_id)` (`max_retries=0`; the next tick is the retry) re-checks the flag, `enabled`,
`provides_live`, `reconnect_required`, the ZEV and the holder (`live.source_state.holder_gone`, shared with
the push endpoint, as is `touch_last_seen`), calls `fetch_live`, `store.put_sample` and touches
`live_last_seen_at` at coarse resolution. A live-only source whose status is `pending` or `error` becomes
`ok` with the first sample (it has no sync to settle it). Outcomes: `ProviderAuthError` marks the whole
source `reconnect_required` (like a sync, audited once as `supplementary_source.sync` with
`capability: live`, since the next ticks skip it); `ProviderRateLimited` sets
`live:v1:src:{id}:backoff` for `min(max(Retry-After, LIVE_PULL_INTERVAL_S), 900)` seconds; any other
`ProviderError` is logged at warning level and is a missed sample that simply expires, never touching
`last_error`, which belongs to the history sync. No audit event per poll.

### 6.3 Forecast (`metering/live/forecast.py`, task in `metering/tasks.py`)

- `refresh_production_forecasts` (beat, `FORECAST_REFRESH_INTERVAL_S`): fans out
  `refresh_forecast_source.delay(id)` for enabled sources with `provides_forecast`, oldest
  `last_success_at` first.
- **Solar Manager:** `GET /v3/users/{smId}/data/forecast` (next 3 days). `data[]` items
  `{t, pW, pWmin, pWmax}` (W). Points are averaged into UTC hours. The interval of `t` (start or
  instant) is verified against a real response before PR 5 merges, as the history timestamps were.
- **forecast.solar:** per plane `GET {FORECAST_SOLAR_BASE_URL}[/{api_key}]/estimate/watts/{lat}/{lon}/{tilt}/{azimuth}/{kwp}`
  with coordinates rounded to 2 decimals; the per-plane series are summed after being averaged into hours.
  `result.watts` maps local timestamps (timezone in `message.info.timezone`) to the mean power **since the previous key**, so a key
  marks the end of the interval it covers: it is converted to UTC and belongs to the hour before it.
  *Limits and terms, checked 2026-11-01 (doc.forecast.solar/account_models):* the public tier needs no registration
  or key and is "free for life" with no non-commercial clause stated; it answers **one plane per call**,
  **12 calls per rolling 60 minutes per calling IP**, **today and tomorrow** only and one-hour resolution (a key lifts these:
  60 to 1200 calls an hour, 1 to 4 planes per call, 3 to 6 days). A plane is therefore one call, and
  the shipped design follows from that, not from the first draft (hourly refresh, 72 hours):
  - a forecast.solar source is refreshed at most every `FORECAST_SOLAR_MIN_REFRESH_S` (3 hours), forecasts moving slowly;
  - an instance-wide **rolling-hour** call list (`live:v1:forecast_solar:calls`) enforces
    `FORECAST_SOLAR_MAX_CALLS_PER_HOUR`, reserving all of a plant's calls at once or none: a source that does not
    fit is `deferred` (nothing changes, not even its status) and tried again on the next tick, oldest first;
  - a plant with more planes than the budget could ever allow gets `error` with a safe message naming
    `FORECAST_SOLAR_API_KEY` and the budget setting;
  - a `429` is honoured (`Retry-After`, else `X-Ratelimit-Reset`, at most an hour) through
    `live:v1:forecast_solar:backoff`, which holds back every forecast.solar source;
  - the horizon is what the tier returns (about two days); `FORECAST_HORIZON_H` only caps it.
  Fixed host, no redirects, 20 s timeout, 1 MiB cap.
- Each refresh replaces the source's points from the current hour on and deletes points older than 24 h, in one
  transaction. Status handling: a source that provides **only** a forecast keeps `ok`/`error`/`reconnect_required`
  and `last_*` like a history sync; one that also provides history or live leaves `status` and `last_error` to
  those (a failure is logged), except that an auth failure makes the whole source `reconnect_required` and is
  audited once as `supplementary_source.sync` with `capability: forecast`. Nothing is audited per refresh.
  `refresh_forecast_source` is not retried: the next beat tick is the retry. Both tasks do nothing while the live flag is off.
- **Solar Manager timestamps.** `t` of a forecast row is read as the *start* of its interval (`FORECAST_T_MARKS`
  in `solar_manager.py`, a one-line fix). *Checked against a real response on 2026-11-01:* `data[]` of 276 rows,
  15 minutes apart, each exactly `{t, pW, pWmin, pWmax}` (W, `t` in UTC with `Z`), from the next quarter hour for three days. The shape
  matches. The response cannot tell whether `t` marks the start or the end of its quarter hour; the hourly means differ by at most
  15 minutes either way, so the display is unaffected. A row without `t` or `pW` is skipped; no usable row is an error.

### 6.4 Time

All samples and buckets are UTC instants; "today" and `peak_windows` days are Swiss civil days
(ADR 0026). Bucket boundaries are UTC multiples of `LIVE_CURVE_BUCKET_S`, which align with civil
5-minute boundaries.

### 6.5 Operations

- **System health:** the `supplementary` probe gains `live_flag_enabled`, `live_sources`,
  `live_fresh`, `forecast_sources`, `forecast_stale` (no points fetched for 3 refresh intervals; a source that needs a new key is not counted, and a source that was never fetched counts from its creation) and
  `forecast_solar_calls_last_hour` (the rolling hour of §6.3). `degraded` additionally when more than half of the enabled
  forecast sources are stale. Live freshness never degrades health: devices going offline is the
  participant's matter.
- **Audit:** `supplementary_source.create/update/delete/disconnect` carry `capabilities`, `target` and
  `held_by` in metadata; the new disconnect reason `personal_holder_assigned`; `pv_plane.*`;
  `building.update` covers the coordinates. No per-sample or per-poll events.
- **Backups and transfer:** `PvPlane` and the new source fields are covered; `ProductionForecastPoint`
  is in `EXCLUDED_MODELS`; the cache is never backed up.
- **Deletion:** ZEV, metering point and participant cascades as today; cache keys expire by TTL.
- **System check:** `metering.W002` when `FEATURE_LIVE_ENERGY_DATA_ENABLED` is forced on in the
  environment while the cache backend is not Redis/Valkey (`LocMemCache` would split live data per
  process). `metering.W003` when `LIVE_PULL_INTERVAL_S >= LIVE_MAX_AGE_S` (a pulled value would expire before
  the next pull).

## 7. Frontend

### 7.1 My energy system and its cards

- `frontend/src/lib/live.ts` (next to `lib/supplementary.ts`): `useLiveEnergy(zevId)` wraps `useQuery({ queryKey: queryKeys.live.snapshot(zevId),
  queryFn: fetchLiveSnapshotOrNull, refetchInterval: liveSnapshotRefetchInterval (15_000),
  refetchIntervalInBackground: false, staleTime: 10_000, retry: false })`, enabled only with a ZEV. The
  API client maps `404` (flag off, no access) to `null` (`lib/api/live.ts`, `fetchLiveSnapshotOrNull`),
  and `liveSnapshotRefetchInterval` returns `false` for `null`, so polling stops for good. There is no
  separate flag query for the snapshot itself. `useLiveEnabled({ enabled? })` wraps `useQuery({ queryKey:
  queryKeys.live.enabled(), queryFn: fetchLiveEnabled, staleTime: 60_000, retry: false })` with no polling;
  the nav and the page share it. `useLiveCurve(zevId, enabled, participantId?)` refetches every 60 s and is enabled only while the
  card shows; the date is today's civil date (`todayBusinessIso`). Pure helpers: `kwFigure`, `formatKw`
  (kW, one decimal), `formatClock` (`hh:mm:ss`, Europe/Zurich), `showLiveCard` (snapshot non-null and
  `coverage.live_sources > 0`), `liveCardState` (what the card may say per tier), `liveCurveRows`,
  `liveDayAxis`. `useProductionForecast(zevId, enabled)` (`lib/forecast.ts`, plus `forecastForDay`, `hoursOfDay`, `hasExpectedProduction`, `tomorrowBusinessIso`: `queryKeys.live.forecast(zevId)`, every 15 min, no
  focus refetch, `404` to `null` and no polling after it) with the pure helpers `forecastRows` (kW, band `[min, max]` or `null`),
  `hasForecast` (a plant with hours), `nextPeakWindow` (the window that is running or next), `peakDayKind` (today, tomorrow, date) and `peakRange`.
- `frontend/src/lib/myEnergy.ts`: `MyEnergyRange` (`today`, `week`, `period`) with `parseMyEnergyRange`,
  `shiftIsoDate`/`lastDaysRange`, `showMyEnergyEntry` (the nav rule, §3), `useOwnSeries(params, enabled)`
  (`queryKeys.live.ownSeries(zevId, participantId, from, to, bucket)`, so a source change invalidates it
  with `queryKeys.live.all`), `ownHistoryFromSeries` and `todayRows` (the history/live merge, §5.3).
- `frontend/src/features/live/LiveEnergyCard.tsx`:
  - **Layout.** The card is **not** a white `.card` box: like the tiles of the Energy balance it is a plain `.live-now` section
    on the page: a heading row (`card-header` classes: "Right now" and the badge, the time on the right), then **one** `.stat-grid`
    with all the tiles, then the muted notes. The ZEV tile is labelled **ZEV production** (`live.production`) so it is not mistaken for **Your production**.
  - `none`: "No live production data right now". When the viewer's own tiles are shown (below), the sentence is the muted "No live data for the ZEV as a whole
    right now, because not all metering points report" (`live.noneZev`) instead, so it does not read as if the viewer's own
    system were silent. A vZEV of bidirectional meters of which only one has a source is tier `none` (every bidirectional
    point is a producing point), and the holder of that one still sees their own figures. The forecast is its own card below (`ProductionForecastChart`), shown from any plant that has one, also with no live source at all.
  - `production`: a **ZEV production** KPI tile (`StatCard`, `x kW`, the same tile as at `exact`) whose **tooltip** (`StatCard`'s `info`: an
    info mark beside the label, shown on hover, keyboard focus and tap; `role="tooltip"`, described by `aria-describedby`) says "We don't
    know how much the other participants are using at the moment, so part of it may already be in use" (`live.othersUnknown`). When the
    production reads `0.0 kW` the tooltip gives way to the tile's visible hint "Nothing spare right now" (`live.nothingSpare`):
    with no production nothing is spare whatever the others use. This is wording only; the payload still has no `surplus_w` below `exact`.
  - Own figures lead, ahead of the ZEV totals, as the first tiles of **one** `.stat-grid` that holds the ZEV tiles too (they share a row as far as the width allows) (a viewer's own
    consumption and, for a producer, own production; UI review of #1032, a participant came for their own number):
    **Your consumption** `x kW` with the hint "of which y kW local, z kW from the grid" (only at `exact`; below it the
    tile has no hint) and **Your production** `x kW` with "y kW to the ZEV, z kW to the grid" (only at `exact`).
    Both tiles need `own.complete` and nothing else: they show at tier `none` too (`liveCardState` does not gate them on the tier).
    When the viewer's source reports gross figures (`own.gross.consumption_w` / `production_w`, a system behind the meter), the
    tile shows the gross figure, because the meter alone shows only the surplus and the grid draw; the hint of that tile is then
    left out, as the split belongs to the metered power. With `split_withheld_reason = "inconsistent"` the tile shows the
    figure and a muted hint under the grid says the split cannot be shown right now.
  - `exact`: ZEV production, ZEV consumption (`live.production`, `live.consumption`), **spare now**, local share. The split is never shown below `exact`; a value
    the payload leaves `null` is never shown. A power that rounds to zero is `0.0`, never `-0.0` (`snapshot.watts`
    and `kwFigure` both normalise a negative zero).
  - When `own` is set and not `complete` (the viewer holds a point that reports no fresh value, so the own tiles are
    withheld): an `IssueText` warning under the title linking to `/me/metering-points`, "Your source is not reporting
    right now" when `own.points_fresh` is `0`, else "Not all of your metering points are reporting live right now"
    (`live.ownQuiet`, `live.ownPartlyQuiet`). The payload has no per-source age, so the text names none.
  - Always: "as of hh:mm:ss" (when `as_of` is set) and a "Live, indicative" badge (the page's **one** marker that the values are
    indicative: neither the page description nor the chart notes say it again). There is **no coverage line** ("Live data from X of
    Y metering points", the grid connection point's state): it repeated what the per-point table says, and for a participant it
    only confused. `liveCardState` no longer has `reporting`.
- `LivePointsTable.tsx` (meter or "Grid connection point", holder or "ZEV-operated", kW, age, state)
  for a snapshot that carries `points` (manager, viewer, admin). It is a `Disclosure` inside a card, **closed**, its summary
  a bold "Live values per metering point" and, while some points have no current value, the muted "no current data: N"
  (`live.points.summary`, `live.points.quiet`; N counts the points with `target = metering_point` whose `live_state` is not
  `fresh`, so it is the complement of the card's "X of Y", which also leaves out the grid connection point). The summary has no
  "X of Y" of its own: the card says it once (UI patterns §10.3 rule 12), and a long table must not push the chart off the first
  screen on a phone. The power
  reads in words, never with the meter's sign (a meter counts positive when it draws, negative when it feeds out):
  `livePointFlow` gives *6.2 kW produced* (production meter), *consumed* (positive), *fed in* (negative on any other
  meter), *from the grid* / *to the grid* (grid connection point); a power that rounds to `0.0` has no direction. A
  point without a source (`source_id` null, a metering point) gets a note beside its state: a point with a personal
  holder says "the participant connects it" (muted); a point nobody holds gives a manager (`canManage`) a
  **Connect** link (`.text-link`: underlined, so it differs from the text by more than colour and weight) to the Energy data tab of the ZEV settings (`/zev-settings/energy`) and a viewer nothing. From 640 px down the columns give way to one small
  card per point (`.live-points-list`), so the kW is never behind a horizontal scroll. The state is text
  (`LiveStateBadge`): a current value is plain, a source gone quiet is an `IssueText` warning and a point with no data a
  muted note; no coloured pill (UI patterns §10.1).
- `ProductionForecastChart.tsx` (`features/live/`, the body of the **Tomorrow** tab, §7.1 structure; it replaces the separate forecast card of the first cut): the title "Expected
  production" with "as of hh:mm", the next peak window in bold ("Highest production expected today 10:00-14:00",
  "tomorrow" or the date), hourly bars in kW (hours already past lighter) with the min/max band as an area only where the
  forecast gives one, an x axis with a tick every three hours (six beyond a day and a half or below 30em, where nine
  labels would collide), whose midnight tick names the
  day only on a chart that spans more than one, "Forecast for 1 of 2 plants" when the sum is partial, and the hint that it is an estimate and never a claim that power
  is spare. Chart colours come from `chartTokens`.
- Placement: its own page, `pages/MyEnergyPage.tsx` at `/my-energy` (alias `/live`; `PageHeader` with the
  community switch, scope note, `ScopeGuard`; the title and description follow the role: `pages.myEnergy.title` "My energy
  system" for a participant, `titleCommunity` "Live energy" (and a description about the community's devices) when
  `isZevScope`, which is also the browser-tab title). The page owns the billing period
  (`useBillingPeriodParams`, like `DashboardPage`) and renders `features/myEnergy/MyEnergyView.tsx`. The
  components are `features/live/` (card, table, `LiveEnergyView` = the "Right now" block) and
  `features/myEnergy/` (`MyEnergyView`, `TodayChart`). The dashboards render nothing live; where they
  showed the own-system card (`GrossEnergyCard`, `GrossEnergyCallToAction`) they show
  `components/dashboard/OwnSystemNote.tsx`: a muted line and a link to `/my-energy?range=period` carrying
  the period (and `participant=` for a selected participant), only where the card would have appeared.
- **Structure of `MyEnergyView`**, top to bottom:
  1. *States.* Energy data feature off (`useEnergyDataEligibility().featureOn` false) -> warning
     `Notice` `myEnergy.disabled` and nothing else; eligibility loading -> `PageSkeleton`; failing ->
     error `Notice` with retry (`myEnergy.loadFailed`).
  2. *Right now.* `LiveEnergyView`: card and, for managers, viewers and admins, the points table. It
     polls only while mounted and asks for the snapshot only once `/live/enabled/` answered `true`.
     Failure -> error `Notice` (`pages.live.loadFailed`); live off -> a muted line
     `pages.live.disabled`; loading -> `PageSkeleton`; snapshot `null` -> `Notice` `pages.live.unavailable`;
     `coverage.live_sources === 0` -> `EmptyState` `pages.live.empty.*` by what the user can do (UI patterns
     §10.3 rule 1): `canManage` -> "Connect a live source" to `/zev-settings/energy`; a viewer (`isZevScope` without
     `canManage`) -> the explanation `empty.viewer` that the community's management can connect a source, **no button**;
     a participant -> "Connect your own live source" to `/me/metering-points`. None of these hides the views below.
  3. *Participant picker* (`isZevScope`, not on Tomorrow, which is not about a participant), above the tabs it steers (§10.3 rule 2),
     with the placeholder `myEnergy.pickParticipant` and no helper text. *Range tabs* `AppTabs` (Today | Tomorrow | 7 days | Period, `keepMounted={false}`), the choice in the URL as
     `?range=tomorrow|week|period` (absent = `today`, `parseMyEnergyRange`; tab changes push history entries). The
     **Tomorrow** tab exists only while the ZEV forecast has an hour above zero for tomorrow's civil day
     (`hasExpectedProduction`); without one, `?range=tomorrow` falls back to Today. A
     `filter-bar` under the tabs holds the `PeriodSelector` on the Period tab. 7 days and Period
     exist only where a history is possible (`historyPossible`). For a participant that is a history-eligible point
     in the community. For a manager, viewer or admin it is **at least one source of the selected community with
     `provides_history`** (`listSupplementarySources`, the same query as the Energy data tab, so it costs no second request;
     while it loads the block is kept); a manager of a community without one is not promised a history. A participant without a
     possible history sees Today, and the strip is left out while there is a single view. With no live data, no forecast and no
     possible history the whole block, picker included, is left out: the `EmptyState` above already says what to do.
  4. *Participant picker* (`isZevScope` only, placed before the tabs, see 3): the ZEV's current participants (`fetchParticipants`,
     filtered to the ZEV and `valid_to` open or not past), the manager's own marked "(You)", and two participants with the same
     display name told apart by their e-mail ("Ben · ben@a.example"). `?participant=`
     in the URL, validated against that list. Default: the participant of a history-eligible point of the
     user with a source (`historyEligible`, `source !== null`), else none. Participants get no picker and send no `participant_id`; managers
     always send the selected one (the same permission path as the dashboards' selected participant, §5.3).
  5. *Today* (`TodayPanel`). With a live card: `useLiveCurve(zevId, true, participantId)`, own history from
     the curve's `own_history`/`own_history_through`. Without one (live off, no live source, or the curve
     answered `404`): the own-series endpoint (`bucket=quarter`, today) through `useOwnSeries`,
     `ownHistoryFromSeries` turning kWh per quarter hour into W. `TodayChart` draws the ZEV production
     (area) and consumption (line), both live only, and the own line of `todayRows` (§5.3): consumption
     from history **solid** (`stepAfter`), from live **dashed**, own production likewise when present, a
     dashed reference line at `own_history_through` labelled "History to live". The card has **no heading** (the
     tab says "Today", §10.3 rule 12). **Whose line it is** follows the subject: `isOwn` gives "Your consumption (history)" and
     so on (`myEnergy.today.own*`), a manager looking at somebody else gets "Person's consumption (history)"
     (`personHistory`, `personLive`, `personProductionHistory`, `personProductionLive`, `personEmptyHistory`), never "your". There is **no help text under the chart**:
     no forecast note, no "How to read the chart" disclosure (the legend and the dashed line say it). Gaps are `null`, `connectNulls={false}`. Nothing at
     all -> `myEnergy.today.empty`/`ownEmptyHistory`/`personEmptyHistory`.
     **Forecast overlay.** While the live view is on, `useProductionForecast(zevId)` (enabled only once the energy data
     feature is on) feeds `todayRows(..., {date, hours})`, which draws each of today's forecast hours flat across its
     5-minute steps (`forecast`, `forecastBand`; hours already past included, so the plan can be read against what
     happened). `TodayChart` shows it as a dashed `stepAfter` area "Expected production" with the min/max band behind it
     where there is one, names today's next peak window above the chart. The
     chart appears whenever there is live data, an own history **or** a forecast, so a ZEV with only a forecast still
     sees it here.
  5b. *Tomorrow* (`ProductionForecastChart` with `forecastForDay(forecast, tomorrow)`, title "Tomorrow: expected
     production"): the forecast alone, no live or own data and no participant.
  6. *7 days* (`SeriesPanel`): `useOwnSeries` for the last 7 civil days (`lastDaysRange(today, 7)`) in
     `hour` buckets, shown with `GrossEnergyCard` (totals, rates, chart) and the note "ZEV live totals are
     kept for 48 hours only; the official figures are on Energy balance" with an underlined link (`.text-link`) to `/dashboard`;
     for a manager looking at somebody else the note says "the person's own system" (`myEnergy.week.notePerson`). The card's
     provenance line names a vendor ("Reported by your own system (Solar Manager)") but not the provider "own system / file",
     which the sentence already says (`supplementary.gross.reportedOwnGeneric`/`reportedParticipantGeneric`).
  7. *Period*: the same panel for the billing period (`period.from..period.to`, `day` buckets, enabled
     once `periodReady`), `GrossEnergyCard` titled "Your own system" (`whose="own"`; for a manager looking
     at somebody else `whose="participant"` with their name).
  8. *No own system* (`NoOwnSystem`): no participant selected -> nothing (the picker's placeholder asks); the viewer's
     own system without a history-eligible point -> nothing (there is no history to wait for); the viewer's own system and
     `historyEligible` has a point without a source -> `GrossEnergyCallToAction`; the viewer's own system with a source ->
     "Your source has not delivered any history yet. It appears here after the next sync." (`myEnergy.notSynced`) and a
     `.text-link` to **My metering points**, so it does not say "once a source is connected" under a chart that already has a live line;
     otherwise the same link under `myEnergy.noOwnSystem`, or `noOwnSystemParticipant` for somebody else. The own-series
     answer's `gross: null` or an empty `own_history` is what triggers it.
  9. *Wording* (UI review of the page, #1163): the page description is one sentence (what the devices report, kept apart from the
     grid operator's figures); the participant empty state does not name the page differently from its title ("Live energy" is the
     community's page name only); the buttons name the task, not the place ("Connect a live source").

### 7.2 Setup

Shipped in PR 3b; Solar Manager live arrived with PR 4 and the forecast with PR 5 (below).

- **My connections** (`features/supplementary/MyConnections.tsx`): a card at the top of
  `/me/metering-points`, shown only while the feature is on, the source list has loaded and the holder has **two
  or more** such sources (one source is all on its meter's card; none is said by the cards' "Not connected"). It lists
  the sources the signed-in holder owns: `held_by = participant` sources whose `metering_point` is a
  held point (an `eligible` entry) of the selected community, so no ZEV-held, connection-point or
  other holder's source. One row per source: provider and label, the metering points it feeds (the
  meter ids as a list; always one today), a `badge-tag` per capability it provides (**History
  (15 min)**, **Live (now)**, **Forecast**) followed by a problem only when there is one
  (`capabilityProblem`: switched off and "no data yet" as muted text, a stale live source, a source in error or
  needing a new key as `IssueText`), never a status for a source that simply works (UI patterns §10.1), and an
  **Open** button that asks the page to open the source in its pane (§ pane below). There is no
  Connect here, that stays on the meter cards. It is a view only: a source still feeds exactly one metering
  point. The classes are `connection-*` (`styles/components/connections.css`). Tests:
  `tests/my-connections.test.ts` (7) and the cases of `tests/my-metering-points-page.test.ts` (25, with the pane in
  `describe('the source pane')`). The page's hint
  about asking a manager to flag a meter shows only while no held point is history-eligible and no own source is
  connected.

- **One card per held metering point** (`MeteringPointDataCard`, replacing the history card, the live
  section and the source card of the first PR 3b cut): the meter id with one muted line (what the meter is, from the participant's own metering point list, and
  "Surplus metering" as plain text when `historyEligible`: a classification is text, not a pill, UI patterns §10.1; the
  community is the page's eyebrow, not repeated), then two labelled parts. **Grid operator's meter** (`MeterDataBand`,
  a tinted band: "These readings are the basis of billing." and **View meter data**, the link to the metering chart) is kept
  apart from **Your own energy data** (`section.own-data`, with "From your own system. Only shown and used for
  statistics, never for billing."), so the link to the official readings is not taken for the data of the sources
  under it. A meter without energy data (the plain card) has the band only. The own-data part holds `CapabilityRows`,
  one row per capability the point is eligible for (`historyEligible` / `liveEligible`; an entry without
  `eligible_capabilities` is history only; a **Forecast** row for a producing point): **History (15 min)** and **Live
  (now)**. A row is the capability, the source that provides it as a `button-ghost` link (`provider · label`) that
  opens the source in the page's pane, a problem as text only when there is one (`capabilityProblem` through
  `CapabilityProblemText`: a stale live source or a source in error as `IssueText`, switched off or "no data" muted;
  a source that works carries no pill and no "OK") and a muted freshness line (history "up to <synced through>", live
  "last value <time>", forecast "updated <time>"); a push source providing both is in both rows and
  opens the same pane. An unconnected row says "Not connected" with a secondary **Connect** that opens
  the connect flow with that capability preselected. One primary **Connect energy data** shows only while **two or more**
  capabilities that share the connect flow (history, live) are unconnected (preselecting them); with one left, its own
  row's **Connect** is the only button. Connect and the row Connect are disabled while
  impersonating. A history source's reconnect-required and error banners stay on the card. While the
  source list is loading or failed and eligibility names a source (`source`, `sources.history` or
  `sources.live`), the card shows a loading or error state with a retry instead of rows.
- **The source pane** (`SourcePane` in `features/supplementary/SourceDialog.tsx`, owned by
  `MyMeteringPointsPage`): a source opened from a card's row or from My connections opens **beside the cards**, not in a
  dialog (UI patterns rule A: a record opened from a list). The cards are the list; `.detail-split` puts the pane next to
  them from 60rem of content width (`useMinWidth`), below it the pane replaces the cards until X or Back. The open source
  is `?source=<id>` in the URL (a reload, a link or Back reopens it; opening from the cards adds one history step,
  switching to another source replaces it, X takes the step back), only for a participant-held source on a meter the user
  holds. Focus moves to the pane's title when it opens and back to the control that opened it when it closes. The card
  and button of the open source are marked (`data-selected`, `aria-current`). A new Solar Manager key typed and not
  saved is a draft: closing the pane, opening another source or leaving the page asks first (`useDraftGuard`, fed by
  `SourceDetails`' `onDirtyChange`). Connecting stays a dialog: after it closes the new source opens in the pane
  (`SupplementarySourceModal`'s `onConnected`). That is a deliberate exception to rule F: the connect flow is a short
  task that creates the record, with its own steps (what, how, consent, one-time token). The managers' Energy data
  tab (§7.3) uses the same pane and hook (`useSourcePane`, `useSelectedSourceId`: the `?source=` selection, history step,
  focus, scroll and the draft guard); `SourceDialog` (a `FormModal` around the same body) is left for hosts that have
  no list to place a pane against.
- **`SourceDialog`** (`features/supplementary/SourceDialog.tsx`; `SourceDetails` is its body, shared with the pane)
  holds everything about one source, laid out as a manage surface (UI patterns §9): the pane's header (a `tone="brand"`
  `DetailPane`) names the source ("Solar Manager · Roof") with a facts line (the meter and what it provides); the dialog
  names it in the first line of the body. Then the banners (reconnect required, error), one **visible action** and a
  **"⋯" menu**, an inline key form when replacing, and a bordered block per capability it provides (**History**: last
  successful sync, covered range, the meter comparison as text; **Live**: last value; **Forecast**: last update), each
  with its problem as text only when there is one. Technical details are one closed `Disclosure` "Technical details":
  the Solar Manager id (plain text, not code), the push token prefix, issued and last used (the prefix stays monospace)
  and the push **endpoints** (`PushEndpoints`: CSV endpoint and columns for history, live endpoint, JSON example and
  sign convention for live). The visible action is **Sync now** (**Refresh forecast** for a forecast-only source) for a
  Solar Manager or forecast.solar source that can sync, or **Reconnect** when the key no longer works or the source is
  disconnected. The menu, in sections: *Connection* (**Test**, **Replace key**, **Import CSV**, **New push token**,
  **Revoke token**, **Disconnect**), *Data* (the capability switches) and *End* (**Delete data**, **Remove source**, in
  red); all of them confirm. **New push token** is shown once in `PushTokenPanel` with the endpoints of everything the
  source provides. The capability switches
  on the same connection: **Also send live data with this source** (confirm with the live consent,
  `PATCH {provides_live: true, consent: true}`, only a push source on a live-eligible point whose live
  slot is free), **Stop live data** (`PATCH {provides_live: false}`) and, for history,
  **Also provide history with this source** (`PATCH {provides_history: true, consent: true}`, a
  participant-held push source on a history-eligible point whose history slot is free) and **Stop
  history data**; stopping is only offered while the other capability remains. The mutations are in
  `useSourceActions`. Container: a **dialog** (`FormModal`, size `md`; ui-patterns rule 3/C: a detail
  opened from a card with no list beside it), with confirmations as the only thing opened over it.
  The host keeps it open by its own state (a source id), never by what the source list says, and the
  rotated token lives in the dialog above everything a refetch can change, so a refetch cannot swap the
  token screen away. The replace-key form is inline (Cancel then Save); a key typed and not saved is the pane's draft.
- **`SupplementarySourceModal`** is the one connect flow, taking `holder` (`participant`, `zev`,
  `connection-point`), the point, `available` (what the point offers and does not have yet), `initial`
  (preselected), the visible `sources` and an optional `frame` (so a host that is already a dialog draws
  the flow in its own dialog). Step **What**: a checkbox per available capability (skipped when only
  one is available; a ZEV-held point and the connection point offer live only). Step **How**: provider
  radios (Solar Manager and push for any choice; a ZEV-operated meter and the connection point are push only, because a Solar Manager key is personal; the Solar Manager hint says whether it syncs history hourly, reads live while the page is open, or both: `solarHintKey`); when the
  point already has an enabled participant-held push source, **Use my existing push source** comes
  first and adds the missing capabilities to it with one `PATCH {provides_*: true, consent: true}`
  (no new token; the screen then shows the token prefix and the endpoints). Otherwise one source with
  all chosen capabilities is created in ONE `POST` (`provides_history`, `provides_live`,
  `target: 'metering_point'`, `held_by: 'participant'`); a ZEV-operated meter sends `held_by: 'zev'`, `zev`
  (live only) and the connection point `target: 'connection_point'`, `held_by: 'zev'`, `zev`, no
  `metering_point`. Consent lists the texts of every chosen capability (history: stored, visible, not
  billing, revoke; live: §3) with one agreement line (`consent.agree`, `liveAgree` or `bothAgree`); the
  ZEV-held modes keep the ZEV-held confirmation (the connection point adds its net-power line). Field
  errors of `external_id`, `api_key`, `consent` and `provider` show at their input; `provides_live`,
  `provides_history`, `held_by`, `target`, `zev` and `metering_point` go to the form banner. A new push
  source ends on the one-time token screen with all applicable endpoints; a Solar Manager source has no
  token screen (a toast, `liveConnectedPull` for live only). The dialog offers **Also send live data** and
  **Also provide history** for a Solar Manager source as for a push one (the stored key is reused), hides
  Sync and the endpoints for a live-only one, and the card shows the reconnect banner for a live-only
  Solar Manager source too.
  Wording for a community member (no developer vocabulary): the push provider is **Own system / file** (not "Push");
  its hint names Home Assistant, Shelly or a script, mentions the CSV upload only when history is among the chosen
  capabilities (`providerHint.push`, else `push_live`: "sends the current power"), and the submit stays disabled until the
  consent box is ticked, with `modal.needsConsent` saying so.
- **`/me/metering-points`**: per held point with a capability exactly one `MeteringPointDataCard`; a
  point with no capability stays a plain card.
- **`/metering/points`** shows nothing of live or history data: no live chip on the rows, no "Energy data" badge in the
  expanded row, no **Live data** menu entry and no grid-connection card (they moved to the Energy data tab, §7.3). What
  stays is the meter itself: the **Roof planes** entry of a producing point while `useLiveEnabled` is true (the forecast
  needs the plant's planes, which belong to the meter and its building) and the generation-behind-the-meter flag the
  manager sets, shown as plain text next to the meter id (a classification, UI patterns §10.1).
- **7.3 The Energy data tab of the ZEV settings** (`features/supplementary/ZevEnergySources.tsx`; the tab `energy` of
  `/zev-settings/:tab`, shown while the energy data feature is on, and outside the settings form: no save bar). It is where
  a manager looks after the community's sources, and what the metering-point list used to carry. With **no source** the tab
  shows one `EmptyState` and nothing else: its explanation (`supplementary.zev.empty.manager`;
  `empty.nothing` when the community has nothing it could connect; `empty.other` for a viewer), for a manager the `note` line that says where
  participants connect their own sources (`participantsOwn` as plain text, or `participantsOwnSelf` followed by a `.text-link` to
  `/me/metering-points` when the manager holds a capable meter in this community, i.e. has the entry; the same line closes the description once sources exist; a viewer gets none) and, for a manager with something to connect, its
  **Connect a source** button, the one primary action (UI patterns §9, §10.3 rule 12). The short description and the toolbar button come
  with the first source. Then every source of the selected community in one list (`source-rows`: the grid connection point first, then the meters by
  id; each row the meter id, the holder or "ZEV-operated" and what it provides as plain text with a problem as
  `IssueText` next to the capability it concerns, no pills) and, beside it, the source in a `SourcePane`
  (`useSourcePane`: `?source=<id>`, from 56rem of content, focus and draft handling as on My metering points). Managers get a primary
  **Connect a source** in the toolbar (live flag on; disabled with "There is nothing left to connect." when `zevEligibleByPoint` and the
  connection point offer nothing): `ZevConnectDialog` asks "Which data do you want to show?" (`supplementary.zev.target`; until a choice exists a muted `pickHint` says what follows, since there is no
  primary action before it) among the grid connection point and a meter
  nobody holds personally with the capabilities it can still get: live, forecast), then runs the existing flows
  (`SupplementarySourceModal` with `holder="connection-point"` or `"zev"`, `ForecastConnectDialog`), and the new source
  opens in the pane (`onConnected`). A source the community holds shows every action of its owner. A participant's source
  is **somebody else's** (`SourceDetails`' `onBehalfOf`): the manager's own rights only, in the menu: **Switch off** or **Switch
  on** (`PATCH {enabled}`), **Delete data** (history) and **Remove source**, never test, sync, key, token or capabilities; the
  pane says who connected it, and for a manager who holds the meter themselves it links to My metering points. A
  viewer sees the list and the pane without any action. The connection point is no longer a card of its own.
- **Names (UI patterns §10.3 rule 9).** The tab is **Energy data** (the kind of data), one connection is an **energy data source**
  (empty-state title, `Quelle verbinden` inside the tab), and **Live energy** in the navigation is the page that *shows* the values, a
  different thing: the three are kept. The tab is absent while the feature is off and not replaced by an explanatory tab, because
  only the platform administrator can switch the feature on (a link that names the tab still shows `supplementary.zev.off`).
- **Eligibility semantics.** With the live flag on, `/sources/eligible/` lists every held point, so
  history logic uses `historyEligible` (capability `history`, or no `eligible_capabilities` field while
  the flag is off) and `useEnergyDataEligibility` exposes `historyEligible` and `liveEligible`;
  `canConnect` means history. The "show your real self-sufficiency" call to action
  (`ParticipantDashboardBody`, `ManagementDashboardBody`) uses history only. The manager's **My metering points** nav entry shows
  for any held meter with a capability (`hasCapability`), live included.
- Every source mutation calls `invalidateSourceQueries`: `queryKeys.live.all`, the source list,
  `supplementaryEligible()`, `supplementaryZevEligibleAll()` (prefix of
  `supplementaryZevEligible(zevId)`), the dashboard summary and `['metering','points']`.
- **Forecast setup (PR 5).** The capability rows gain **Forecast** (`RowCapability`, `sourceFor(..., 'forecast')`,
  `forecastEligible`) for a producing point: the source as a button with its status badge and, for forecast.solar, "updated
  <time>". Its **Connect** opens `ForecastConnectDialog` instead of the shared connect flow (forecast.solar needs no
  credential or consent): what the forecast is, what leaves the instance (location rounded to a kilometre and the planes'
  size, tilt and direction), that the roof planes and the building's location must have been entered (the server's refusal
  "Add the roof planes ..." is replaced by a translated text, `setupMissingManager` or `setupMissingParticipant`, that says
  who adds what; any other refusal is shown as the server words it). **Who adds what follows the user's management rights in
  the plant's community, not who holds the source** (UI review of #1032, #1164): `useCommunityAccess().canManage` with the plant's
  ZEV equal to the selected one (or none selected) gets `needsManager`/`setupMissingManager` and a **Set up roof planes and
  location** button (`.button-secondary` link to `/metering/points?search=<meter id>`, closing the dialog) to the page whose
  metering-point menu has **Roof planes** and whose buildings carry the location; anybody else, a participant or a manager of another
  community, keeps `needsParticipant`/`setupMissingParticipant` ("ask your community's management") without a link, and for a holder whose meter has a working Solar Manager connection (enabled, key stored, no forecast yet) a choice
  between that connection (default; consent checkbox, `PATCH {provides_forecast: true, consent: true}` instead of a new source) and
  forecast.solar. It creates `{provider: forecast_solar, provides_forecast: true, provides_history: false,
  provides_live: false, held_by, target: metering_point, consent: false}`. A holder's card hosts it directly; the
  manager's **Connect a source** dialog (§7.3) shows `Live` and `Forecast` rows for the meter chosen and opens it with `holder="zev"`. **My connections** shows a Forecast chip (with its own status only when the source has no history) and passes the meter's forecast
  eligibility to the source dialog. `SourceDialog` shows the forecast capability and its last update, **Refresh
  forecast** (`sync`) and **Test** for a forecast.solar source, and for a Solar Manager source **Also use the Solar
  Manager forecast** (consent confirmation, `PATCH {provides_forecast: true, consent: true}`) and **Stop forecast**; stopping
  any capability is offered while another remains.
- **Roof planes** (`features/meteringPoints/PvPlanesDialog.tsx`): the metering-point menu of a producing or bidirectional point
  has **Roof planes** while the live view is on (managers; viewers read). One dialog lists the planes ("8.50 kWp, tilt 25°,
  facing south") with Edit and Delete and a form for name, peak power (kWp), tilt and direction (degrees, 0 south, 90 west,
  -90 east, 180 north); `planeInput` checks the same ranges as the server before asking it (`lib/pvPlanes.ts`). The form is
  `noValidate`: after the first save a message by the field (`planeFieldProblems`, `planes.errors.kwp|tilt|azimuth`) names
  what is missing or out of range, so the browser's own tooltip never appears. Cancel comes before Save. The note that
  the forecast also needs the building's location shows only while the building has no coordinates (the page passes
  the point's building), with **Edit building** for someone who may write; it closes the dialog and opens the building
  form, so only one layer is ever open.
- **Building form** (`BuildingFormModal`): latitude and longitude (decimal degrees, comma accepted, both or neither,
  `coordinateInput`) with **Locate from address** (`locateBuilding`, enabled once street and city are filled; it fills the two
  fields and saves nothing). Its hint names the service, since the street address leaves the instance: "sends the
  address to OpenStreetMap (Nominatim)". The two fields have no example placeholder (an example looks like an entry).

### TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export type LiveTier = 'none' | 'production' | 'exact'
export type LiveState = 'fresh' | 'stale' | 'never'

export interface LiveOwn {
    consumption_w: number | null
    local_w: number | null
    grid_w: number | null
    production_w: number | null
    to_zev_w: number | null
    to_grid_w: number | null
    gross: { production_w: number | null; consumption_w: number | null }
    complete: boolean
    points: number
    points_fresh: number
    split_withheld_reason?: 'inconsistent'
}

export interface LivePoint {
    metering_point_id: string | null
    target: 'metering_point' | 'connection_point'
    meter_id: string | null
    meter_type: 'consumption' | 'production' | 'bidirectional' | null
    participant_name: string | null
    held_by: 'participant' | 'zev' | null
    live_state: LiveState
    meter_power_w: number | null
    age_s: number | null
    source_id: string | null
}

export interface LiveSnapshot {
    zev_id: string
    as_of: string | null
    tier: LiveTier
    consumption_basis: 'all_points' | 'connection_point' | null
    production_w: number | null
    consumption_w: number | null
    surplus_w: number | null
    grid_import_w: number | null
    local_share_pct: number | null
    coverage: {
        producing_points: number
        producing_fresh: number
        consuming_points: number
        consuming_fresh: number
        connection_point: LiveState | null
        live_sources: number
        points: number
        points_fresh: number
    }
    own: LiveOwn | null
    points?: LivePoint[]
    max_age_s: number
}

export interface LiveCurveBucket {
    start: string
    tier: LiveTier
    production_w?: number | null
    consumption_w?: number | null
    surplus_w?: number | null
    own_consumption_w?: number | null
    own_local_w?: number | null
    points?: Array<{ metering_point_id: string | null; target: SourceTarget; meter_power_w: number | null }>
}

export interface LiveCurve { date: string; bucket_s: number; buckets: LiveCurveBucket[] }

export interface ForecastHour { start: string; power_w: number; min_w: number | null; max_w: number | null }
export interface ForecastPeakWindow { date: string; from: string; to: string; peak_w: number }
export interface ProductionForecast {
    zev_id: string
    horizon_h: number
    complete: boolean
    plants: number
    plants_with_forecast: number
    fetched_at: string | null
    hours: ForecastHour[]
    peak_windows: ForecastPeakWindow[]
    per_plant?: { metering_point_id: string; meter_id: string; hours: ForecastHour[] }[]
}

export interface PvPlane {
    id: string
    metering_point: string
    label: string
    peak_power_kwp: string
    tilt_deg: number
    azimuth_deg: number
}
```

`SupplementarySource` gains `zev`, `target`, `held_by`, `provides_history`, `provides_live`,
`provides_forecast`, `live_last_seen_at`, `live_state`; `provider` gains `'forecast_solar'`;
`metering_point` and `participant` become nullable. `MeteringPoint` gains `live_state`; `Building`
gains `latitude`/`longitude` (`string | null`).

### API client functions

**File:** `frontend/src/lib/api/live.ts` (new) and `supplementary.ts`, `zev.ts`

| Function | Method | Endpoint |
|---|---|---|
| `fetchLiveSnapshot(zevId)` | GET | `/metering/live/zevs/{id}/` |
| `fetchLiveCurve(zevId, date?, participantId?)` | GET | `/metering/live/zevs/{id}/curve/` |
| `fetchOwnSeries({zevId, dateFrom, dateTo, bucket, participantId?})` | GET | `/metering/supplementary/zevs/{id}/own-series/` |
| `fetchLiveEnabled()` | GET | `/metering/live/enabled/` |
| `fetchLiveSnapshotOrNull(zevId)` / `fetchLiveCurveOrNull(zevId, date?, participantId?)` | GET | the same, `404` mapped to `null` |
| `fetchProductionForecastOrNull(zevId)` | GET | `/metering/live/zevs/{id}/forecast/`, `404` mapped to `null` |
| `locateBuilding({address_line1, postal_code, city})` | POST | `/zev/buildings/locate/` |
| `fetchZevEligibleSources(zevId)` | GET | `/metering/supplementary/sources/zev-eligible/` |
| `fetchPvPlanes(mpId)` / `createPvPlane` / `updatePvPlane` / `deletePvPlane` | GET/POST/PATCH/DELETE | `/zev/metering-points/{id}/pv-planes/` |

Source and PV-plane mutations invalidate `queryKeys.live.*`, the source lists and the metering-point
list.

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Participants read "production now" as "free for me" | Medium | Tier `production` always carries the "others' use unknown" note; spare power only at `exact` |
| Live household values reveal presence | High | Other participants never see per-point values; consent text names managers/viewers; holder change disconnects ZEV-held sources (§3) |
| `C = P + N` differs from the metered sum (unmetered loads, timing) | Low | Labelled indicative; the split's contract violation withholds the own split instead of clamping |
| One producer offline hides everything | Medium | Managers see which point is missing; forecast still shown |
| forecast.solar limits/terms change | Medium | Budgeted calls over a rolling hour, a 3-hour minimum refresh, optional key, provider interface allows adding Open-Meteo later; limits re-checked for PR 5 (2026-11-01, §6.3) |
| Solar Manager rate limits (undocumented) | Medium | Demand-driven polling, cached bearer token, `Retry-After` back-off |
| Push floods | Medium | 5-second floor per source, per-token throttle, no DB write per sample |
| Cache without persistence loses the curve | Low | Accepted (ADR 0044); W002 for non-Redis caches |
| Generalising the source breaks history behaviour | High | Existing rows migrate to `provides_history = True`, `held_by = participant`, `target = metering_point`; the whole supplementary test suite must stay green unchanged except for the renamed reverse accessor |

## 9. Test plan

Counts are filled in as each PR lands.

### Backend

PR 1 landed `metering/test_supplementary_capabilities.py` with 77 tests in the classes
`SourceCapabilityModelTests`, `SourceCreationRightsTests`, `OrphanTaskTests`, `EligibleTests`,
`ZevEligibleTests`, `HistoryCapabilityGuardTests`, `SourceListScopingTests`, `LiveStateTests` and
`MeteringPointStatusTests` (the plan below, plus the eligibility, history-guard, list-scoping and
status checks); `zev/test_transfer_supplementary.py` gained the capability fields and a
`CapabilityArchiveTests` class (3 tests: live and ZEV-held round trip, no live state in the archive,
older archives import as history sources).

PR 2 landed the live package tests, 132 in `metering/live/` (store 13, ingest 32, snapshot 57,
curve 17, `me` 10, W002 3), the live keys of the system-health probe (1) and the two billing-isolation
checks for `metering.live` (2). The classes differ slightly from the plan below: `ClassifyTests` (the
pure tier rule), `SnapshotTierTests`, `SnapshotSplitTests`, `ManagerPointsTests` and
`SnapshotVisibilityTests` in `test_snapshot.py`; `AcceptedSampleTests`, `ValidationTests`,
`RefusalTests` and `RateLimitTests` in `test_ingest.py`; `LiveStoreTests`, `BucketTests` and
`PushSlotTests` in `test_store.py`; `CurveTests` and `CurveEndpointTests`; `LiveMeTests`;
`LiveCacheCheckTests`.

- `metering/test_supplementary_capabilities.py` — **`SourceCapabilityModelTests`**: migration
  defaults for existing rows; each partial unique constraint; target/holder check constraints;
  provider × capability matrix; history still requires `has_behind_meter_generation`; connection
  point refused for a vZEV and for a second one; clearing the behind-meter flag allowed with a live-only
  source. **`SourceCreationRightsTests`**: holder creates live on a consumption meter; manager creates
  ZEV-held only without a personal holder; manager refused on a held meter (`403`); participant refused
  `held_by = zev`; admin anything; consent required for live; `forecast_solar` without consent.
  **`OrphanTaskTests`**: `personal_holder_assigned` disconnect; connection point untouched.
- `metering/live/test_store.py` — **`LiveStoreTests`**: latest expires after max age; bucket means;
  empty bucket is a gap; retention TTL; rate floor.
- `metering/live/test_ingest.py` — **`LiveIngestTests`**: accepted sample; stale/future/naive timestamp;
  non-finite and cap; `401`/`403` (disabled, no live capability, holder gone)/`429` with `Retry-After`;
  flag off `404`; `live_last_seen_at` resolution; no audit per sample.
- PR 3a added two tests to `SnapshotTierTests` (`test_live_sources_counts_enabled_live_sources_with_the_connection_point`,
  `test_live_sources_leaves_out_disabled_inactive_and_non_live_sources`) and `live_sources` to the
  coverage assertion of `test_production_when_only_some_consumers_report`. PR 3b added
  `test_a_bidirectional_point_counts_once_in_the_distinct_coverage` and `points`/`points_fresh` to that
  assertion.
- PR 3b (My energy system) added `metering/test_supplementary_own_series.py` with 25 tests in
  `OwnSeriesPermissionTests` (participant reads own; cannot read another `403`; manager, viewer and admin
  read a selected participant; no selection gives the manager's own; other ZEV and stranger `404`; unknown
  `404`, malformed `400`; anonymous; energy data flag off `404`; live flag not needed; community-mode
  excluded; former participant `404`), `OwnSeriesShapeTests` (buckets and totals equal the dashboards';
  `history_through`, also the earliest of several sources; 100 and 92 quarters on the DST days; low
  coverage withholds the rates), `OwnSeriesRangeTests` (limits per bucket, malformed, missing and reversed
  dates, unknown bucket, default bucket) and `OwnHistoryOfDayTests` (kWh to W, no invented interval, empty
  cases), and 6 tests in `metering/live/test_curve.py::OwnHistoryTests` (own history and
  `own_history_through` in the curve, no server-side merge and `own_production_w`, nobody else's history,
  a manager naming a participant, none without a selection, `participant_id` permissions over HTTP).
  `CurveTests`/`CurveEndpointTests` stay (17 in the file before, 23 now).
- The declared-idle rule added to `SnapshotTierTests` `test_a_bidirectional_household_declared_without_generation_reads_zero_without_a_source`,
  `test_such_a_household_still_consumes_so_the_consumption_stays_unknown`, `test_a_declared_idle_household_that_has_a_source_gone_quiet_is_a_gap_not_zero`,
  `test_a_production_point_without_a_source_is_never_assumed_idle` and (the renamed) `test_a_bidirectional_household_with_generation_behind_its_meter_but_no_source_keeps_the_zev_at_none`,
  and to `CurveTests` `test_a_declared_idle_household_without_a_source_does_not_hold_the_buckets_at_none`.
- `metering/live/test_snapshot.py` — **`SnapshotTierTests`**: `none` without producers and with one
  producer stale; `production` with partial consumers; `exact` with all points; `exact` through the
  connection point; connection point ignored in a vZEV; `all_points` wins over the connection point;
  the worked example of §1 to the watt. **`SnapshotSplitTests`**: own split equals
  `split_consumption`/`split_production` called directly; split only at `exact`; `inconsistent`
  withholding; community-mode points excluded from `own`; bidirectional point in both totals.
  **`SnapshotVisibilityTests`**: participant sees no `points`; manager and viewer do; non-participant
  outsider `404`/`403`; former participant refused.
- `metering/live/test_curve.py` — **`CurveTests`**: per-bucket tiers; civil-day boundaries incl. DST;
  retention limit on `date`.
- `metering/live/test_forecast.py` (PR 5: 43 tests) — **`HourBucketTests`** (5: hourly means, an end-marked key
  belongs to the hour before, negative power reads as zero, the band only when every value has one, planes add up and
  the band needs every plane), **`PeakWindowTests`** (3: longest run at half of the top, ties go to the earliest,
  one window per Swiss day and none for a dark day), **`MapWattsTests`** (3: local keys to UTC, an unreadable
  answer or timezone, unreadable values skipped), **`SolarManagerForecastMapTests`** (2),
  **`ForecastSolarProviderTests`** (8, stubbed host: one call per plane with rounded coordinates and the summed
  result, the key in the path, missing planes or coordinates without a call, the budget defers instead of calling, more
  planes than the budget can allow, `429` backs every source off, a server error carries no vendor text, the
  rolling hour), **`SolarManagerForecastFetchTests`** (2: stored key, bearer token reused), **`RefreshTests`**
  (11: future points replaced and old ones dropped, the horizon cap, forecast-only status ok and error, a source
  with other capabilities keeps its status, auth failure, the minimum interval and `force`, deferred changes
  nothing, flag off, disabled source, the beat's order and skips) and **`ForecastApiTests`** (9: manager sees
  the sum, the windows and every plant, a participant no plants, a viewer plants, `404`s, an incomplete sum, a
  disabled source drops out, the band only when every plant has one, `forecast_next_peak` in `me`).
- `metering/test_supplementary_forecast.py` (PR 5: 16 tests) — **`CreateForecastSolarTests`** (10: a manager connects a
  ZEV-operated plant without consent or token and a refresh is queued, a holder connects theirs, planes and
  coordinates first, only a producing meter, one forecast per point, forecast only, no key or id, a held meter is
  refused to a manager (`403`), the live flag, a push source never), **`SourceActionTests`** (3: `sync` and its
  cooldown, `test`, switching a Solar Manager forecast on with consent and off deleting its points),
  **`EligibleForecastTests`** (2) and **`DisconnectForecastTests`** (1). The two cases of
  `test_supplementary_capabilities.py` and `test_supplementary_solar_manager.py` that expected a refused forecast were
  rewritten, and `EligibleTests` lists `forecast` for a producer.
- `metering/test_supplementary_solar_manager.py` (PR 4: 48 tests) — **`MapStreamTests`** (11: `iW − eW`
  incl. negative export; optional `pW`/`cW`; missing or unreadable `iW`/`eW` is no sample; abnormal values;
  timestamp fallbacks), **`ClientStreamTests`** (4), **`SolarManagerLiveTests`** (15: bearer cache avoids a
  refresh per poll and survives rotation; stale cached token costs one re-exchange; a refused fresh token is an
  auth failure after one retry; `verify_live`, `check_live`) and **`SolarManagerLiveSourceApiTests`** (18:
  live-only creation verified with the stream, both capabilities, adding live or history to an existing
  source, key replacement, disconnect/delete/orphan sweep clear the cached token, the test action).
- `metering/live/test_polling.py` (PR 4: 29 tests) — **`PollLiveSourcesTests`** (11: only watched ZEVs; only
  enabled live `solar_manager` sources; skips `reconnect_required` and a disabled ZEV; interval floor;
  back-off; flag off; broker error), **`WatchTests`** (4: snapshot and curve mark the ZEV watched) and
  **`PullLiveSourceTests`** (14: sample stored and reaches the snapshot, auth failure → `reconnect_required`
  audited once, `429` back-off capped at 900 s, transient errors leave `last_error` alone).
- `metering/live/test_checks.py` — **`LivePullIntervalCheckTests`** (3): `metering.W003`.
- `metering/live/test_me.py` — **`LiveMeTests`**: JWT and read-only API key; several ZEVs; throttle.
- `zev/test_pv_planes.py` (PR 5: 16 tests) — **`PvPlaneApiTests`** (9: create, change and delete with their audit events,
  who reads, who does not write, the URL decides the point, producing meters only, a plane cannot move, at most four,
  bounds, another ZEV's manager), **`BuildingCoordinatesTests`** (5: set and clear with the `building.update` event, bounds,
  locate returns the outline's centre without saving, its refusals, managers only and rate limited) and
  **`FootprintCentroidTests`** (2). `zev/test_transfer.py` gained two tests (planes and coordinates survive a
  round trip; an archive without them still imports) and `zev/test_meter_identity_migration.py` now uses the historical
  models, since the real ones read columns added after the state it migrates to.
- `metering/test_supplementary_isolation.py` — extended: nothing under `allocation/`, `tariffs/` or the
  invoice modules imports `metering.live`.
- `accounts/test_system_health.py` — new probe keys (PR 5 adds two tests: forecast counts, staleness above half degrades, a source needing a key is not stale).
- `mcp_server/tests/test_live_energy.py` (PR 6: 9 tests) — **`TestLiveEnergy`**: the exact tier in kW with the points and no `own` block; the `production` tier withholds consumption, spare power and share and says why; tier `none` has no figures; the forecast keeps the current hour on and drops past ones, with ISO strings; `forecast_hours` caps the rows and `0` keeps the windows; out-of-range `forecast_hours` is `-32602`; an admin sees any ZEV; another owner's ZEV is a tool error with no figures; the flag off is a tool error.

### Frontend

- The move to its own page added `metering/live/test_enabled.py` (**`LiveEnabledTests`**, 4 tests: on, off
  answers `200` false, effective only with the energy data flag, anonymous `401`), `tests/live-page.test.ts`
  (6 tests: flag off asks for no snapshot, `null` snapshot notice, error with retry, the empty state's
  link for managers and participants, card and points table with sources) and six cases in
  `tests/layout-nav.test.ts` (Live entry only with the flag for admin, manager, viewer and participant;
  its place; none for a former participant).
- PR 5 landed `tests/forecast-helpers.test.ts` (12 tests: rows and bands, `hasForecast`, the peak window that is next, today and
  tomorrow in Zurich time, the range in local clock times, `planeInput` ranges, `azimuthLabelKey` for the eight directions,
  `coordinateInput`, `sourceFor` and `forecastEligible`) and `tests/forecast-ui.test.ts` (the chart's text, a partial sum, `ForecastConnectDialog` for a manager, a holder, a refusal and the
  existing Solar Manager connection, `PvPlanesDialog` lists, adds, refuses an impossible value and is read-only). `tests/my-energy.test.ts`
  gained the forecast rows of `todayRows`, the forecast in Today without live data, the Tomorrow tab (shown, absent without
  tomorrow hours or on a dark day) and no request while live data is off.
- PR 3a landed `tests/live-energy-card.test.ts` (12 tests: the three tiers' texts, the single
  coverage line (since removed), "as of", own split
  only at `exact`, the inconsistent hint, a producer's split, the connection point part, points table rows, empty curve) and `tests/live-helpers.test.ts` (16 tests: `formatKw`,
  `formatClock`, `showLiveCard` hidden for `null` or no live source, `liveCardState`, polling stops on
  `null`, curve rows with gaps, the day axis incl. the 25-hour day).
- PR 3b added `tests/live-setup.test.ts` (13 tests: live modal payloads and consent per holder, field errors, push
  panel endpoints; the former `PointLiveDialog` and `ConnectionPointCard` cases moved to
  `tests/zev-energy-sources.test.ts`, 11 tests: the community's list, the connect dialog, a participant's source seen by a
  manager, the viewer), `tests/source-pane.test.ts` (3, with the real menu), `tests/metering-point-data-card.test.ts` (46 tests: one card with
  both sources, rows per eligible capability, a shared push source in both rows opening one dialog,
  per-row Connect preselecting, the connect flow's providers per capability, one `POST` for both
  capabilities, "use my existing push source" as a `PATCH` with consent, the token screens surviving a
  refetch, impersonation, the source dialog's actions and capability switches, CSV import),
  `tests/energy-data-eligibility.test.ts` (4), eligibility helper tests in
  `tests/supplementary-helpers.test.ts`, one-card-per-point cases in
  `tests/my-metering-points-page.test.ts`, `tests/metering-points-list.test.ts` (no live or
  history data on the list) and `tests/layout-nav.test.ts`.
- My energy system (PR 3b): `tests/my-energy.test.ts` (24 tests: range parsing, civil-day arithmetic,
  `showMyEnergyEntry`, `ownHistoryFromSeries`, `todayRows` precedence and gaps, and `MyEnergyView`: feature
  off asks for nothing, participant's Today from the own-series endpoint with live off, the curve's own
  history while live has data, fallback when the curve is `404`, call to action vs explanation, the 7 days
  and Period requests, the manager's picker, prompt and default); `tests/live-page.test.ts` now covers the
  "Right now" block only; `tests/layout-nav.test.ts` covers the `/my-energy` entry and its rule;
  `tests/dashboard-behavior.test.ts` the note instead of the card; `tests/live-energy-card.test.ts` the
  `TodayChart` empty states.
- UI review of the page (#1163): `tests/my-energy.test.ts` (35 tests) gained the picker before the tabs, no tabs and no picker for
  a community without a history source, same-name participants told apart, and the person's (not "your") note; `tests/live-page.test.ts`
  the viewer's explanation without a button and the manager's and participant's task buttons; `tests/live-energy-card.test.ts` the closed
  points table with the missing count, the underlined Connect link, the quiet-own-source warning, the person's empty text and the chart's
  one visible hint with the rest in a `Disclosure`; `tests/gross-energy-card.test.ts` the provider-free provenance line.
- Setup guidance (#1164): `tests/forecast-ui.test.ts` gained the manager who connects their own plant (setup text and link) and the participant, or the
  manager of another community, who is told to ask; `tests/zev-energy-sources.test.ts` the empty tab with one explanation and one button (and none
  when nothing can be connected), the intro and toolbar button once a source exists; `tests/my-metering-points-page.test.ts` the history-only hint with and without the live pointer.
- `tests/production-forecast.test.ts`: peak window text, incomplete-forecast hint.
- `tests/pv-planes-editor.test.ts`: validation and the 4-row limit.
- Build, lint, style lint, hex sweep; screenshots of `/live` in all tiers, also at ~400 px.

### Acceptance criteria

- [x] A Home Assistant automation pushing every 10 s makes the producer's value appear on every
      participant's dashboard within one refetch interval. *(by design and tests; a real Home Assistant or Shelly feed has not been run against a live instance, see §12 "Not verified")*
- [x] With only the producer live, participants see production now and the "others' use unknown" note,
      and no spare/split figure anywhere (UI, `me`, MCP).
- [x] With a connection-point source in a physical ZEV, the worked example of §1 shows 3.0 kW spare.
- [x] A value older than 60 s is never shown as current.
- [x] Another participant's per-point value is not in any participant payload.
- [x] The forecast shows hourly production and a peak window per day, from Solar Manager where
      connected, otherwise forecast.solar, for as far as the provider reaches (about two days with
      forecast.solar's public tier, §6.3; `FORECAST_HORIZON_H` only caps it).
- [x] Invoices generated with and without live and forecast data are identical. *(by isolation: nothing under `allocation/`, `tariffs/` or the invoice modules imports `metering.live`, `test_supplementary_isolation.py`)*
- [x] With the live flag off, nothing live renders and all live endpoints answer `404`.

## 10. Implementation plan

1. **PR 0 — this spec and ADR 0044.**
2. **PR 1 — generalise the source.** Fields, constraints, migration with backfill, permissions
   (`held_by = zev`), eligibility endpoints, orphan task, flag, serializer and type changes. No live
   data yet; the supplementary suite stays green.

   *Rollout (PR 1).* Source management accepts the new shapes, but the serializer refuses with a
   `400` and a field error: `provides_forecast` ("not available yet", until PR 5, which also adds the
   `forecast_solar` provider); `provides_live` with `provider = solar_manager` (until PR 4; live is
   push only); a `solar_manager` source without `provides_history`; and, while the live flag is not
   effective, anything live: `provides_live`, `target = connection_point`, `held_by = zev`. A
   push source with `provides_live` can be created and shows `live_state = never`, but
   `POST /live/ingest/` arrives with PR 2, so no sample is accepted yet. ZEV-held push tokens appear in
   every ZEV manager's Tokens & keys list (`held_by = zev`) and, without an owner, in the admin list
   (SPEC-2026-tokens-and-keys §3, §5.1).
3. **PR 2 — live push and snapshot.** `metering/live/` (store, ingest, snapshot, curve, `me`),
   throttles, settings, W002, health keys.

   *Rollout (PR 2).* `POST /live/ingest/`, `/live/zevs/{id}/`, `/curve/` and `/live/me/` are live
   behind the flag. `forecast_next_peak` in `me` is always `null` until PR 5. The "watched ZEV" key and
   `LIVE_WATCH_TTL_S`, `LIVE_PULL_INTERVAL_S` arrive with the Solar Manager pull (PR 4); the forecast
   settings and health keys (`forecast_sources`, `forecast_stale`, `forecast_solar_calls_this_hour`)
   with PR 5. The MCP tool and the frontend types follow in PR 6 and PR 3.
4. **PR 3 — frontend live**, split in two:
   - **PR 3a — live page (read-only).** Types, API client, query keys, `lib/live.ts`, the card, the
     curve and the points table on the new `/live` page with its sidebar entry, `GET /live/enabled/`,
     i18n (`live.*`, `pages.live.*`, `nav.live`), and `coverage.live_sources` in the snapshot. *Rollout
     (PR 3a).* The entry shows only once the live flag is on; the page then shows an empty state until a
     live source exists. With the flag off the snapshot answers `404` and nothing polls. The dashboards
     are unchanged.
   - **PR 3b — setup and the page.** The page becomes "My energy system" (`/my-energy`, alias `/live`):
     Today / 7 days / Period, the own line merged from history and live, the manager's participant picker,
     the curve's `own_history`, `GET /supplementary/zevs/{id}/own-series/`, and the own-system card moved
     off the dashboards (§3, §5.3, §5.3a, §7.1). Solar Manager live stays PR 4. Source modal capabilities, the push panel with the live endpoint, ZEV-held and
     connection-point setup on both metering-point pages, the live-state marker (§7.2). The holder page
     shows one card per meter with a row per capability, a source dialog and one connect flow (a follow-up
     to the first cut, which had a history card and a live card per meter). *Rollout (PR 3b).*
     Everything is behind the live flag; live is push only and the forecast is not offered. It also fixes
     history logic that took the flag-on eligible list for behind-meter points (`historyEligible`).
5. **PR 4 — Solar Manager live.** Stream pull, bearer cache, demand-driven polling.

   *Rollout (PR 4).* A Solar Manager source may now be live-only, history-only or both (the refusals
   "Live data is only available for push sources" and "A Solar Manager source provides history" are gone;
   the forecast refusal stays). Beat entry `poll-live-sources` (`LIVE_PULL_INTERVAL_S`), tasks
   `poll_live_sources` and `pull_live_source`, settings `LIVE_WATCH_TTL_S` and `LIVE_PULL_INTERVAL_S`,
   system check `metering.W003`. The snapshot and curve endpoints mark the ZEV watched. A Solar Manager
   source is participant-held on a metering point only: `held_by = zev` and the grid connection point stay
   push only because the key is a personal credential (`400` on `provider`). The source modal offers Solar
   Manager for live. Decisions the plan did not settle: the pull slot is 80 % of the interval (a tick that
   comes a moment early must still pull); a live-only source's status becomes `ok` with its first sample;
   `test` on a source with both capabilities checks history and then live; adding live to a source without
   a stored key is refused; a negative `pW`/`cW` is dropped rather than clamped.
6. **PR 5 — forecast.** `PvPlane`, building coordinates, `ProductionForecastPoint`, both providers,
   forecast endpoint and chart.

   *Rollout (PR 5).* Everything is behind the live flag. `provides_forecast` is accepted (the "not available
   yet" refusal is gone) with the `forecast_solar` provider; `forecast` joins `eligible_capabilities`; migrations
   `zev.0048` (building coordinates, `PvPlane`) and `metering.0013` (`ProductionForecastPoint`, the provider choice).
   New endpoints: `GET /live/zevs/{id}/forecast/`, the nested `pv-planes` routes and `POST /zev/buildings/locate/`; `forecast_next_peak`
   in `me` is now filled. Beat entry `refresh-production-forecasts`, tasks `refresh_production_forecasts` and
   `refresh_forecast_source`, the settings of §4.5 and the health keys of §6.5. Decisions the plan did not settle: forecast.solar's
   real public limits (one plane per call, 12 calls per rolling hour, two days) changed the refresh cadence and the
   horizon (§6.3); a forecast.solar source needs no consent and carries no personal data, yet follows the usual holder
   rules (a ZEV-held one is disconnected once somebody holds the meter personally); the forecast keeps its own status
   only when it is the source's only capability; "Locate from address" saves nothing and is its own endpoint so the
   building form can use it before the building exists; roof planes are written by managers only, so a participant
   whose plant has none asks one. The system-health probe's history staleness now counts only sources that provide history.
   **Still open before merge:** the Solar Manager `/data/forecast` shape was confirmed against a real response (§6.3), only the
   meaning of `t` is open (`FORECAST_T_MARKS`); forecast.solar's real response has not been fetched from this instance
   (the mapping follows its documentation and is tested against a stand-in); the forecast cards were looked at in the dev stack with
   pre-filled hours at 1440 and 400 px, the connect dialogs only through tests.
7. **PR 6 — automation and docs.** MCP `live_energy`, user-guide chapter with the Home Assistant
   (`rest_command` + automation, `rest` sensor reading `/live/me/`) and Shelly (Gen2+ script) recipes,
   screenshots.

   *Rollout (PR 6).* The MCP tool `live_energy` (§5.6), registered as the eleventh tool; the energy-data
   chapter of the user guide gains "Send live power (push)" (the live endpoint with its rules, a Home Assistant
   `rest_command` automation, a Shelly Gen2+ script), "Read it back: automations" (`/live/me/` with a personal
   API key, a Home Assistant `rest` sensor) and a troubleshooting entry; the AI-assistants chapter lists the tool.
   The spec moves to Completed and joins the completed feature specs. No migration, no setting. The guide
   screenshots were not regenerated (the dev data has no live source) and the recipes were not run against a
   real Home Assistant or Shelly.

## 11. Documentation to update

- `docs/user-guide/`: new chapter "Live energy data and forecast" (participant view, manager setup,
  connection point, PV planes, recipes); the energy-data chapter for capabilities.
- `docs/specs/2026-10-supplementary-energy-data.md`: §2 out-of-scope pointer, §3 (ZEV-held sources),
  §4.1 (generalised fields), §12.1 and §12.6 (answered here).
- `docs/specs/2026-10-buildings-and-sites.md`: building coordinates.
- `docs/specs/README.md`: list this spec under Drafts, later under completed feature specs; `AGENTS.md`
  once implemented.
- Settings of §4.5: all have working defaults; like the other feature settings they are documented in §4.5 and not listed in `.env.example` or the Helm values.

## 12. Decisions and future ideas

Decided with the issue owner on 2026-10-30 ([#1032](https://github.com/splattner/openzev/issues/1032)):

1. **Generalise `SupplementarySource`** with capability flags instead of a sibling model (§4.1).
2. **Incomplete coverage hides the split**; no bounds (ADR 0044, §5.2).
3. **Max age 60 s; minimum push interval 5 s** (10 s recommended); live kept 48 h in 5-minute
   buckets, cache only.
4. **ZEV-operated meters and the connection point are connected by a manager** (admins as always).
5. **Managers (and viewers) see live values per metering point**; participants only totals and their own.
6. **No long-term history from live values** (ADR 0044).
7. **Forecast: Solar Manager, else forecast.solar**; plant parameters as `PvPlane` + building
   coordinates; production only.
8. **HTTP push with recipes** for Home Assistant and Shelly in v1.
9. **No battery handling.**
10. **The grid connection point is a live-only source on the ZEV**, not a metering point (ADR 0044).

Not verified when the spec was completed (nothing here blocks the feature, which stays behind its flag and is
described as an early version in the release notes):

- Solar Manager's `/data/stream` and the meaning of `t` in `/data/forecast` (`FORECAST_T_MARKS`, a one-line fix) against a real
  account; the stream mapping follows the vendor's swagger (1.88.11).
- forecast.solar's real response from this instance; the mapping follows its documentation and is tested against a stand-in.
- The Home Assistant and Shelly recipes of the user guide on real devices.
- The forecast connect dialogs and the delete-data and remove-source confirmations in a browser (tests only).
- The roof-planes refusal is recognised by its English text in the forecast dialog; an error code from the API would be sturdier.

Future ideas (not planned):

- **Account-level connections feeding several metering points** (one token for several meters), if a
  use case appears (§7.2: the overview already lists a source's meters as a list).
- **Native MQTT ingest** (a broker with per-source credentials, or a bridge service).
- **Direct Home Assistant connection**: pull through the HA REST/WebSocket API with a long-lived token
  and a sensor picker (live via `/api/states/<entity_id>`, history via
  `recorder/statistics_during_period`). Needs a user-supplied host, so an instance-level address policy
  (public HTTPS by default, private networks only when an admin allows them, DNS pinned after the
  check, no redirects), and a warning that HA tokens are not read-only.
- **Shelly Cloud pull**, **Open-Meteo / MeteoSwiss** forecasts.
- **Bridge live into a "recent days" view** until the official data is imported.
- **Notifications** on expected production through #989.
