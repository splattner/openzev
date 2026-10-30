# Feature Spec: Live energy data and production forecast

- Spec ID: SPEC-2026-live-energy-data
- Status: Draft
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-10-30
- Target Release: TBD
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
| API | Live snapshot, today's curve, forecast, compact `me` endpoint; source creation for the new capabilities and targets; PV plane CRUD |
| Frontend | Live and forecast cards on the participant and management dashboards; per-point table for managers; source setup for live/forecast; PV plane editor; building coordinates; i18n de/fr/it/en |
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
  data arrives" bridge is a follow-up idea.
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

**Frontend routes:** no new route. The live and forecast cards sit on `/` (participant and management
dashboards); live setup sits on `/me/metering-points` (holders) and `/metering/points` (managers);
the connection point and PV planes on the metering-point and ZEV settings screens (§7).

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
them from `zev.geocoding.geocode_building_footprint` (centroid). Requests to forecast.solar send the
coordinates rounded to **2 decimals** (~1 km); the precise values never leave the instance.
`BuildingSerializer` gains both fields.

### 4.4 Live samples (cache, not a model)

`metering/live/store.py`, on the Django `default` cache (Valkey in production, `LocMemCache` in
tests), keys versioned `live:v1:`. A `LiveSample` is
`(source_id, timestamp: aware UTC, received_at, meter_power_w: Decimal, production_w: Decimal | None, consumption_w: Decimal | None)`.

| Key | Value | TTL |
|---|---|---|
| `live:v1:src:{source_id}:latest` | the sample (JSON) | `LIVE_MAX_AGE_S` |
| `live:v1:src:{source_id}:b:{bucket_epoch}` | `{n, sum_meter_w, sum_production_w, n_production, sum_consumption_w, n_consumption}` | `LIVE_CURVE_RETENTION_H` |
| `live:v1:src:{source_id}:last_push` | `received_at` (rate floor) | `LIVE_MIN_PUSH_INTERVAL_S` |
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
| `LIVE_PULL_INTERVAL_S` | `env.int` | `30` | Beat period of `poll_live_sources`, and the minimum interval per pulled source |
| `LIVE_LAST_SEEN_RESOLUTION_S` | `env.int` | `30` | `live_last_seen_at` write resolution |
| `LIVE_MAX_ABS_POWER_W` | `env.int` | `5000000` | Plausibility cap for any value |
| `FORECAST_REFRESH_INTERVAL_S` | `env.int` | `3600` | Beat period of `refresh_production_forecasts` |
| `FORECAST_HORIZON_H` | `env.int` | `72` | Hours stored and shown |
| `FORECAST_SOLAR_BASE_URL` | `env` | `https://api.forecast.solar` | Fixed host; overridable only for test stubs |
| `FORECAST_SOLAR_API_KEY` | `env` | `""` | Optional paid key (higher limits, more planes) |
| `FORECAST_SOLAR_MAX_CALLS_PER_HOUR` | `env.int` | `10` | Instance-wide budget; the public tier is limited per calling IP |
| `PV_PLANES_MAX_PER_METERING_POINT` | `env.int` | `4` | |
| `DEFAULT_THROTTLE_RATES["live_push"]` | rate | `900/hour` | Per push token (one sample per 4 s on average), on top of the 5-second floor |
| `DEFAULT_THROTTLE_RATES["live_read"]` | rate | `720/hour` | Per user/API key on the live read endpoints (one every 5 s) |

## 5. API contracts

New endpoints under `/api/v1/metering/live/` (registered in `metering/urls.py`, views in
`metering/live/views.py`). All answer `404` while the live flag is not effective.

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/live/ingest/` | POST | `SupplementaryPushAuthentication`, `IsPushSource`, `LivePushThrottle` | One sample for the token's source (§5.1). `202 {"accepted": true}` |
| `/live/zevs/{zev_id}/` | GET | `LiveEnergyPermission` | ZEV snapshot (§5.2), narrowed by role. From PR 4 on it also marks the ZEV as watched (`live:v1:watch:zev`) |
| `/live/zevs/{zev_id}/curve/` | GET | `LiveEnergyPermission` | `?date=YYYY-MM-DD` (civil date, default today, at most `LIVE_CURVE_RETENTION_H` back): 5-minute buckets (§5.3) |
| `/live/zevs/{zev_id}/forecast/` | GET | `LiveEnergyPermission` | Hourly ZEV production forecast for `FORECAST_HORIZON_H` (§5.4) |
| `/live/me/` | GET | authenticated (JWT or personal API key) | Compact snapshot for each ZEV the caller is a current participant of (§5.5), made for Home Assistant `rest` sensors and n8n |

Source management stays on `/supplementary/sources/` (supplementary spec §5) with these changes:

- `POST /sources/` accepts `target`, `held_by`, `provides_history`, `provides_live`,
  `provides_forecast` (defaults: `metering_point`, `participant`, `true`, `false`, `false`).
  `provider = forecast_solar` needs neither credential nor consent and returns no token. A
  `push` source with only `provides_live` returns its `push_token` once, as today. A Solar Manager
  source with only live/forecast is verified with one `/data/stream` call instead of a history
  interval. Capability conflicts (a second live source on the metering point) answer
  `400 {"provides_live": ["This metering point already has a live data source."]}`.
- `GET /sources/eligible/` adds, per held metering point, `eligible_capabilities`
  (`["history", "live", "forecast"]` subset) and the ids of existing sources per capability, and is no
  longer limited to metering points with `has_behind_meter_generation` while the live flag is on.
- New `GET /sources/zev-eligible/?zev_id=` (manager, admin): metering points of the ZEV with no
  personal holder today, their eligible capabilities and sources, and whether the connection point
  can be added (`zev_type = zev`, none yet).
- `POST /sources/{id}/test/` for a live-only Solar Manager source fetches one `/data/stream` sample.
- `POST /sources/{id}/sync/` on a forecast source queues a forecast refresh (same 5-minute floor).

PV planes: `GET/POST /api/v1/zev/metering-points/{id}/pv-planes/`,
`PATCH/DELETE /api/v1/zev/metering-points/{id}/pv-planes/{plane_id}/` (managers and admins write;
anyone who can read the metering point reads). Audited `pv_plane.create/update/delete`
(category `METERING`).

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
- *Producing points*: active metering points of the ZEV with `meter_type` in `PRODUCTION_METER_TYPES`.
  *Consuming points*: `CONSUMPTION_METER_TYPES` (`allocation.read_model`). A bidirectional point is in
  both, as in billing.
- `P = Σ max(−meter_power_w, 0)` over producing points; `C_sum = Σ max(meter_power_w, 0)` over
  consuming points. A production-type point's own draw is ignored, as in billing.
- `N` = the connection-point source's `meter_power_w`.

**Tier** (ADR 0044):
- `none` when no producing point exists, or any producing point is not fresh.
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
                "consuming_points": 6, "consuming_fresh": 1, "connection_point": "fresh" },
  "own": {
    "consumption_w": 1200.0, "local_w": 1200.0, "grid_w": 0.0,
    "production_w": null, "to_zev_w": null, "to_grid_w": null,
    "gross": { "production_w": null, "consumption_w": null },
    "complete": true, "points": 1, "points_fresh": 1
  },
  "max_age_s": 60
}
```

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

`GET /live/zevs/{id}/curve/?date=2026-10-30` → buckets of the civil day (`allocation.validity`),
oldest first:

```json
{ "date": "2026-10-30", "bucket_s": 300,
  "buckets": [ { "start": "2026-10-30T10:00:00Z", "tier": "exact",
                 "production_w": 7800.0, "consumption_w": 5100.0, "surplus_w": 2700.0,
                 "own_consumption_w": 1150.0, "own_local_w": 1150.0 } ] }
```

The tier rule of §5.2 is applied per bucket: a point counts as fresh in a bucket when its bucket has
`n > 0`. Values are bucket means, so a bucket's split is a split of means; that is labelled
"indicative" in the UI like everything live. Manager view adds `points[]` per bucket (`meter_power_w`
per point id). Buckets with tier `none` carry only `start` and `tier`.

### 5.4 Forecast

```json
{ "zev_id": "…", "horizon_h": 72, "complete": true,
  "plants": 1, "plants_with_forecast": 1, "fetched_at": "2026-10-30T10:00:12Z",
  "hours": [ { "start": "2026-10-30T11:00:00Z", "power_w": 7400.0, "min_w": 6100.0, "max_w": 8200.0 } ],
  "peak_windows": [ { "date": "2026-10-30", "from": "2026-10-30T10:00:00Z", "to": "2026-10-30T14:00:00Z", "peak_w": 7900.0 } ] }
```

- Sum over producing points with a forecast source; `min_w`/`max_w` only when every summed point has
  them. `complete` is false when a producing point has no forecast; the UI then says "Forecast for 1
  of 2 plants".
- `peak_windows`: per civil day, the longest contiguous run of hours with `power_w >= 50 %` of that
  day's maximum (ties: the earliest). Production only; never a surplus claim.
- Manager view adds `per_plant[]` with the same `hours` per metering point.

### 5.5 `me`

`GET /live/me/` → `{"zevs": [ { "zev_id", "zev_name", "tier", "as_of", "production_w", "surplus_w",
"local_share_pct", "own_consumption_w", "own_local_w", "forecast_next_peak": {"from","to","peak_w"} | null } ]}`.
Flat keys so a Home Assistant `rest` sensor can read them with `value_template` /
`json_attributes_path`. Throttled `live_read`. Works with a `read_only` personal API key.

## 6. Async and integration behavior

### 6.1 Solar Manager live (`metering/supplementary/solar_manager.py`)

- `SolarManagerProvider.fetch_live(source) -> LiveSample` calls `GET /v3/users/{smId}/data/stream`
  (API v1.88.11). Mapping: `t` → `timestamp`; `meter_power_w = iW − eW`; `production_w = pW`;
  `consumption_w = cW`. Battery and device fields are ignored. A missing `iW` or `eW` is no sample.
- Bearer tokens are cached in `live:v1:sm-access:{source_id}` (encrypted, 50 min) so a 30-second poll
  does not rotate the refresh token each time; the refresh runs under the existing `select_for_update`
  lock when the cache is empty.
- Error mapping and HTTP hardening as in the supplementary spec §6.2. An auth failure sets
  `reconnect_required` for the whole source (all capabilities).

### 6.2 `poll_live_sources` (beat, `LIVE_PULL_INTERVAL_S`)

When the live flag is effective: for every ZEV with a `live:v1:watch:zev` key, every enabled
`solar_manager` source with `provides_live` that is not `reconnect_required` and has not been pulled
within `LIVE_PULL_INTERVAL_S` gets `pull_live_source.delay(id)` (`max_retries=0`; the next tick is the
retry). Pulls only while someone looks, so an unviewed ZEV costs no vendor calls. `429` sets a
`live:v1:src:{id}:backoff` key for its `Retry-After` (max 15 min).

### 6.3 Forecast (`metering/live/forecast.py`, task in `metering/tasks.py`)

- `refresh_production_forecasts` (beat, `FORECAST_REFRESH_INTERVAL_S`): fans out
  `refresh_forecast_source.delay(id)` for enabled sources with `provides_forecast`, oldest
  `last_success_at` first.
- **Solar Manager:** `GET /v3/users/{smId}/data/forecast` (next 3 days). `data[]` items
  `{t, pW, pWmin, pWmax}` (W). Points are averaged into UTC hours. The interval of `t` (start or
  instant) is verified against a real response before PR 5 merges, as the history timestamps were.
- **forecast.solar:** per plane `GET {FORECAST_SOLAR_BASE_URL}[/{api_key}]/estimate/watts/{lat}/{lon}/{tilt}/{azimuth}/{kwp}`
  with coordinates rounded to 2 decimals; the per-plane series are summed. Its `result` maps local
  timestamps (timezone in `message.info.timezone`) to W; they are converted to UTC and averaged into
  hours. An instance-wide counter (`live:v1:forecast_solar:calls:{hour}`) enforces
  `FORECAST_SOLAR_MAX_CALLS_PER_HOUR`; a source that does not fit is refreshed on the next tick, oldest
  first. A plant whose planes exceed what the public tier accepts gets `error` with a safe message
  naming `FORECAST_SOLAR_API_KEY`. `429` is honoured with its `Retry-After`. Fixed host, no redirects,
  20 s timeout, 1 MiB cap. The free tier's current limits and terms of use are checked and recorded
  here before PR 5 merges.
- Each refresh replaces the source's points from now on and deletes points older than 24 h, in one
  transaction; status handling (`ok`/`error`/`reconnect_required`, `last_*`) as for history syncs.

### 6.4 Time

All samples and buckets are UTC instants; "today" and `peak_windows` days are Swiss civil days
(ADR 0026). Bucket boundaries are UTC multiples of `LIVE_CURVE_BUCKET_S`, which align with civil
5-minute boundaries.

### 6.5 Operations

- **System health:** the `supplementary` probe gains `live_flag_enabled`, `live_sources`,
  `live_fresh`, `forecast_sources`, `forecast_stale` (no success for 3 refresh intervals) and
  `forecast_solar_calls_this_hour`. `degraded` additionally when more than half of the enabled
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
  process).

## 7. Frontend

### 7.1 Live and forecast cards

- `frontend/src/lib/live.ts` (next to `lib/supplementary.ts`): `useLiveEnergy(zevId)` wraps `useQuery({ queryKey: queryKeys.live.snapshot(zevId),
  queryFn: () => fetchLiveSnapshot(zevId), refetchInterval: 15_000, refetchIntervalInBackground: false,
  staleTime: 10_000 })`, disabled while the flag is off (eligibility/feature query) or without a ZEV.
  `useLiveCurve(zevId, date)` refetches every 60 s; `useProductionForecast(zevId)` every 15 min.
- `frontend/src/components/dashboard/LiveEnergyCard.tsx`:
  - `none`: "No live production data right now", plus the forecast peak if any; managers get the
    reason ("Live data from 0 of 1 producing metering points").
  - `production`: "The ZEV produces **x kW** right now" and the note "We don't know how much the other
    participants are using at the moment, so part of it may already be in use." Own consumption if
    the viewer has a live source.
  - `exact`: production, consumption, **spare now**, local share, and the own split ("of your
    1.2 kW, 1.2 kW is local").
  - Always: "as of hh:mm:ss" and a "live, indicative" label; values older than the max age never shown.
- `LiveCurveChart.tsx` (today's curve: production, consumption where exact, own consumption) and
  `ProductionForecastChart.tsx` (hourly bars, min/max band, "Highest production expected 10:00–14:00").
  Both follow the chart rules of the UI redesign spec and use design tokens only.
- Placement: `ParticipantDashboardBody` and `ManagementDashboardBody`, above the history cards,
  rendered only while the live flag is on and the ZEV has at least one live or forecast source.
- Manager: `LivePointsTable.tsx` in `ManagementDashboardBody` (meter, holder, value, age, state), and
  a coverage line.

### 7.2 Setup

- `/me/metering-points` (`MyMeteringPointsPage`): per held metering point, "Live data" and (for
  producing points) "Production forecast" sections next to the existing history section, driven by
  `eligible_capabilities`. Live via push shows the token once and links the user-guide recipes.
- `/metering/points` (`MeteringPointsPage`): managers see a live-state marker per point and, for
  points without a personal holder, the same setup as a ZEV-held source; a "Grid connection point"
  entry (physical ZEV only) for the connection-point live source; a "PV planes" editor on producing
  points (`PvPlanesEditor.tsx`, at most 4 rows: kWp, tilt, azimuth with an E/S/W helper).
- Building form: latitude/longitude with "Locate from address".

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
    meter_type: MeteringPointType | null
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
}

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
| `fetchLiveCurve(zevId, date)` | GET | `/metering/live/zevs/{id}/curve/` |
| `fetchProductionForecast(zevId)` | GET | `/metering/live/zevs/{id}/forecast/` |
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
| forecast.solar limits/terms change | Medium | Budgeted calls, optional key, provider interface allows adding Open-Meteo later; limits re-checked before PR 5 |
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
- `metering/live/test_forecast.py` — **`ForecastSolarTests`** (stubbed host): URL with rounded
  coordinates; plane sum; timezone conversion; hourly averaging; budget enforcement; `429`.
  **`SolarManagerForecastTests`**: mapping of `pW/pWmin/pWmax`; replace-future semantics; 24 h cleanup.
  **`ForecastPayloadTests`**: `complete`, `peak_windows` rule incl. ties, min/max only when all present.
- `metering/test_supplementary_solar_manager.py` — **`SolarManagerLiveTests`**: stream mapping
  `iW − eW`; bearer cache avoids a refresh per poll; auth failure → `reconnect_required`.
- `metering/live/test_polling.py` — **`PollLiveSourcesTests`**: only watched ZEVs; interval floor;
  back-off on `429`.
- `metering/live/test_me.py` — **`LiveMeTests`**: JWT and read-only API key; several ZEVs; throttle.
- `zev/test_pv_planes.py` — **`PvPlaneTests`**: validation ranges; max 4; manager-only write; audit.
- `zev/test_building_coordinates.py` — locate action; rounding sent to forecast.solar.
- `metering/test_supplementary_isolation.py` — extended: nothing under `allocation/`, `tariffs/` or the
  invoice modules imports `metering.live`.
- `accounts/test_system_health.py` — new probe keys.
- `mcp_server/tests` — **`LiveEnergyToolTests`**: scoping, participant vs manager shape.

### Frontend

- `tests/live-energy-card.test.ts`: the three tiers' texts, "as of", own split only at `exact`,
  hidden while the flag is off.
- `tests/production-forecast.test.ts`: peak window text, incomplete-forecast hint.
- `tests/pv-planes-editor.test.ts`: validation and the 4-row limit.
- Build, lint, style lint, hex sweep; screenshots of both dashboards in all tiers, also at ~400 px.

### Acceptance criteria

- [ ] A Home Assistant automation pushing every 10 s makes the producer's value appear on every
      participant's dashboard within one refetch interval.
- [ ] With only the producer live, participants see production now and the "others' use unknown" note,
      and no spare/split figure anywhere (UI, `me`, MCP).
- [ ] With a connection-point source in a physical ZEV, the worked example of §1 shows 3.0 kW spare.
- [ ] A value older than 60 s is never shown as current.
- [ ] Another participant's per-point value is not in any participant payload.
- [ ] The forecast shows hourly production for 72 h and a peak window, from Solar Manager where
      connected, otherwise forecast.solar.
- [ ] Invoices generated with and without live and forecast data are identical.
- [ ] With the live flag off, nothing live renders and all live endpoints answer `404`.

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
4. **PR 3 — frontend live.** Cards, curve, manager table, setup on both metering-point pages,
   connection point, i18n.
5. **PR 4 — Solar Manager live.** Stream pull, bearer cache, demand-driven polling.
6. **PR 5 — forecast.** `PvPlane`, building coordinates, `ProductionForecastPoint`, both providers,
   forecast endpoint and chart.
7. **PR 6 — automation and docs.** MCP `live_energy`, user-guide chapter with the Home Assistant
   (`rest_command` + automation, `rest` sensor reading `/live/me/`) and Shelly (Gen2+ script) recipes,
   screenshots.

## 11. Documentation to update

- `docs/user-guide/`: new chapter "Live energy data and forecast" (participant view, manager setup,
  connection point, PV planes, recipes); the energy-data chapter for capabilities.
- `docs/specs/2026-10-supplementary-energy-data.md`: §2 out-of-scope pointer, §3 (ZEV-held sources),
  §4.1 (generalised fields), §12.1 and §12.6 (answered here).
- `docs/specs/2026-10-buildings-and-sites.md`: building coordinates.
- `docs/specs/README.md`: list this spec under Drafts, later under completed feature specs; `AGENTS.md`
  once implemented.
- `.env.example`, Helm values: the settings of §4.5.

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

Future ideas (not planned):

- **Native MQTT ingest** (a broker with per-source credentials, or a bridge service).
- **Direct Home Assistant connection**: pull through the HA REST/WebSocket API with a long-lived token
  and a sensor picker (live via `/api/states/<entity_id>`, history via
  `recorder/statistics_during_period`). Needs a user-supplied host, so an instance-level address policy
  (public HTTPS by default, private networks only when an admin allows them, DNS pinned after the
  check, no redirects), and a warning that HA tokens are not read-only.
- **Shelly Cloud pull**, **Open-Meteo / MeteoSwiss** forecasts.
- **Bridge live into a "recent days" view** until the official data is imported.
- **Notifications** on expected production through #989.
