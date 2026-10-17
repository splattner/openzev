# Feature Spec: Analytics dataset API and analytics tokens (foundation)

- Spec ID: SPEC-2026-analytics-dataset-api
- Status: In Progress
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-10-17
- Target Release: 1.27
- Related Issues: [#1058](https://github.com/splattner/openzev/issues/1058) (parts 1 and 3 of the proposal; the Analysis page and in-browser exploration, parts 2, are follow-ups)
- Related ADRs: [ADR 0039](../adr/0039-analytics-through-a-scoped-dataset-api.md), ADR 0013 (shared allocation), ADR 0026 (Swiss civil time), ADR 0027 (per-ZEV access grants), ADR 0030 (supplementary data is not billing input)
- Impacted Areas: backend | docs | infra

---

## 1. Problem and outcome

Managers and participants can only look at their metering data through fixed views. Questions such
as "how did self-sufficiency develop month by month", "when do I use the most energy" or "what does
our load duration curve look like" need an export to Excel. The numbers behind them (local / grid /
feed-in) are not stored; they are computed by the allocation read model.

Outcome of this iteration: one read-only endpoint that returns a **scoped, tidy dataset** computed
from the allocation read model, plus **analytics tokens** so a tool that cannot hold a session
(Grafana's Infinity datasource, a spreadsheet, n8n) can read exactly one ZEV's, or one participant's,
dataset. Nobody gets SQL or database access (ADR 0039). The in-app Analysis page, Perspective/DuckDB
exploration and saved views build on this endpoint later.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Dataset | `GET /api/v1/analytics/series/`: long-format rows, JSON or CSV, granularities `15min`/`hour`/`day`/`week`/`month`/`year`, grouping by metering point, participant or ZEV (§5) |
| Scoping | Admin/manager/viewer see the ZEV; a participant sees their own rows; ZEV totals for participants only above a minimum community size (§6) |
| Limits | Span per granularity, readings scanned, rows returned (§7) |
| Tokens | `AnalyticsToken` model, `oza_` tokens, create/list/revoke endpoints, token authentication on the series endpoint only, audit, throttling, feature flag `analytics_tokens_enabled` (§4, §8) |
| Grafana | Documented recipe with the Infinity datasource, provisioning example and an example dashboard (§10); no Grafana-specific server code |
| Docs | ADR 0039, this spec, user-guide chapter, baseline-spec updates (§12) |

### Out of scope

- The in-app **Analysis** page, curated charts, Perspective / DuckDB-WASM, saved views (#1058 parts 2).
- A **frontend UI for tokens** (create/list/revoke). The endpoints exist and are documented; the
  API-keys page is the model for it. Until then tokens are created with the API (user guide §).
- The **hourly allocation fact table** and Parquet/Arrow output. Measured numbers are in §9; the
  fact table is a follow-up decision.
- Supplementary (behind-the-meter) data in the dataset (`source` is reserved for it, §5.4).
- MCP reuse of the dataset, Grafana straight on PostgreSQL (documented as unsupported, not built).
- Writing data of any kind.

## 3. Actors, permissions, and ZEV scope

Visibility is one value per request and ZEV, `analytics.dataset.Visibility(full, participant_ids)`,
produced by `analytics.scope.resolve_visibility(request, zev)`:

| Caller | Visibility in a ZEV | Notes |
|---|---|---|
| `admin` | full | any ZEV |
| manager or viewer grant (or managing party role) | full | `zev.access.can_view` |
| participant (`Participant.user`, record still current) | own rows only | none while the ZEV is disabled |
| account that is both | full | the wider rule wins |
| other account | `403` | "You have no access to this ZEV's data." |
| analytics token, whole-ZEV | full, that ZEV only | other ZEV: `403` |
| analytics token, participant | own rows of that participant only | |

Authentication of the series endpoint, in order: `AnalyticsTokenAuthentication` (only for a
`Bearer oza_…` header; passes on anything else), `CookieJWTAuthentication`, `ApiKeyAuthentication`
(read-only keys work, the endpoint is `GET`). Permission class `CanReadAnalytics`: a signed-in
account or a valid token.

The token endpoints accept `CookieJWTAuthentication` only: a token or API key cannot mint further
credentials.

## 4. Data model

### 4.1 `analytics.AnalyticsToken` (migration `analytics/0001_initial`)

| Field | Type | Constraints / default |
|---|---|---|
| `id` | UUID | PK, `uuid4` |
| `name` | CharField(100) | what the token is used for |
| `zev` | FK `zev.Zev` | `CASCADE`, `related_name="analytics_tokens"` |
| `participant` | FK `zev.Participant` | null, `CASCADE`; empty = whole ZEV; `clean()` requires the same ZEV |
| `created_by` | FK `AUTH_USER_MODEL` | `CASCADE`, `related_name="analytics_tokens"` |
| `prefix` | CharField(16) | unique, indexed; stored in clear |
| `hashed_key` | CharField(64) | SHA-256 of the secret (`accounts.api_keys.hash_secret`) |
| `created_at` | DateTime | `auto_now_add` |
| `expires_at` | DateTime | null; default `default_api_key_expiry()` (`API_KEY_DEFAULT_EXPIRY_DAYS`, 365) when not sent |
| `last_used_at` | DateTime | null; rewritten at most every `API_KEY_LAST_USED_RESOLUTION` |
| `revoked_at` | DateTime | null; revocation soft-deletes |

Backups: the model is in the `analytics` section of `backups/registry.py` (hashed like `ApiKey`, so a restore only brings back a credential that existed). Ordering `-created_at, id`; index `analyticstoken_creator_idx (created_by, -created_at)`. Properties
`is_expired`, `is_revoked`, `is_active`. Token format `oza_<12 hex prefix>_<secret>`
(`TOKEN_NAMESPACE = "oza"`, `accounts.api_keys.generate_key("oza")`), so it never parses as an API
key (`ozv`) or push token (`ozs`).

### 4.2 `accounts.FeatureFlag.ANALYTICS_TOKENS_ENABLED`

`analytics_tokens_enabled`, default **off**. Off: the token endpoints answer `404` and existing
tokens stop authenticating (`401`). The series endpoint for signed-in accounts and API keys is not
flagged. It appears in Platform → Settings → Functions with its description.

### 4.3 Settings (`config/settings.py`)

| Setting | Env var | Default | Meaning |
|---|---|---|---|
| `ANALYTICS_MAX_READINGS` | same | 300000 | readings of the ZEV in the range one request may scan |
| `ANALYTICS_MAX_ROWS` | same | 200000 | output rows per request |
| `ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE` | same | 5 | *k*, see §6 |
| `DEFAULT_THROTTLE_RATES["analytics_token"]` | `ANALYTICS_TOKEN_THROTTLE_RATE` | `1200/hour` | per token |

`analytics` is added to `INSTALLED_APPS`; `config/urls.py` mounts `api/v1/analytics/`.

## 5. The series endpoint

`GET /api/v1/analytics/series/` (`analytics.views.SeriesView`, route name `analytics-series`).

### 5.1 Query parameters (`SeriesQuerySerializer`)

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `zev` | UUID | token's ZEV | required for sessions and API keys (`400`), optional for a token; unknown id `404` |
| `from`, `to` | `YYYY-MM-DD` | required | inclusive Swiss civil dates |
| `granularity` | `15min`\|`hour`\|`day`\|`week`\|`month`\|`year` | `day` | |
| `group_by` | `metering_point`\|`participant`\|`zev` | `metering_point` | |
| `direction` | `in`\|`out` | both | `in` = consumption, `out` = production |
| `participant` | UUID | – | only that participant's rows; not with `group_by=zev` |
| `metering_point` | UUID | – | only that metering point's rows; not with `group_by=zev` |
| `format` | `json`\|`csv` | `json` | DRF format override; `Accept: text/csv` also works |

Validation errors are DRF's `400` field map.

### 5.2 Response

JSON: `{"meta": {...}, "results": [row, …]}`; `meta` = `zev`, `scope` (`zev`\|`participant`),
`from`, `to`, `granularity`, `group_by`, `timezone` (`Europe/Zurich`), `row_count`.

Row (`analytics.dataset.COLUMNS`, also the CSV header, `null` = empty cell):

| Column | Meaning |
|---|---|
| `bucket_start` | RFC 3339 start of the bucket in Europe/Zurich, with offset |
| `metering_point` | meter id; `null` unless `group_by=metering_point` (and, for a participant, only for meters they hold personally) |
| `participant`, `participant_id` | name and id; `null` for `group_by=zev` and for energy of no participant |
| `direction` | `in` or `out` |
| `total_kwh` | energy of the bucket |
| `local_kwh` | `in`: drawn from the community's own production; `out`: used by the community |
| `grid_kwh` | `in` only: drawn from the grid; `null` for `out` |
| `feed_in_kwh` | `out` only: exported to the grid; `null` for `in` |
| `source` | `metering` |

kWh are rounded half-up to 3 decimals. Rows are sorted by bucket, meter id, participant name,
participant id, direction.

CSV: `analytics.renderers.SeriesCsvRenderer`, header plus one line per row; an error response is a
single `detail` line.

### 5.3 How the rows are built (`analytics.dataset.build_series`)

- Window: `allocation.validity.period_window(from, to)`; ZEV-wide per-timestamp totals from
  `community_totals_by_timestamp` (physical, every meter, ADR 0013).
- `group_by=zev`: per timestamp `local = min(consumed, produced)`, grid `= consumed − local`,
  feed-in `= produced − local`, summed per bucket. Identical to the dashboard's ZEV totals.
- `group_by=metering_point|participant`: every reading from `iter_allocated_readings` for
  consumption and production (split with `split_consumption` / `split_production`), attributed by
  `_attribute`: personal assignment → its holder; community assignment → each eligible participant
  by `eligible_participant_shares` weight (so one reading yields several rows); a gap, or a
  community day with nobody eligible → `participant = null`, so the rows still add up to the ZEV
  totals. Per participant the sums equal the dashboard's `participant_stats` (parity test).
- A reading is bucketed by its own timestamp. `bucket_start`: `15min`/`hour` are cut on the UTC
  instant (the two 02:00 hours of the autumn DST change stay apart); `day`, `week` (Monday), `month`
  and `year` follow the Swiss civil date, so a DST day is a 23- or 25-hour bucket (ADR 0026).
- Readings that violate the split contracts (a negative `energy_kwh`) raise
  `AllocationError`; the endpoint answers `422` `inconsistent_readings` instead of a `500`.

### 5.4 Supplementary data

`source` is always `metering`. Supplementary (behind-the-meter) data is deliberately absent
(ADR 0030: not billing evidence, more personal). When added it becomes `source = "supplementary"`
with its own visibility rule; the row shape does not change.

### 5.5 Errors

`{"detail": "…", "code": "…"}` for dataset errors:

| Status | `code` | When |
|---|---|---|
| 400 | `range_too_large` | span over the granularity limit, or more readings than `ANALYTICS_MAX_READINGS` |
| 400 | `invalid_range` | `to` before `from` |
| 400 | `too_many_rows` | more than `ANALYTICS_MAX_ROWS` output rows |
| 403 | `participant_not_visible` | `participant` filter names somebody the caller may not see |
| 403 | `aggregate_suppressed` | `group_by=zev` for a participant in a community below *k* |
| 422 | `inconsistent_readings` | split contract violated |

Plus DRF `401` (no/invalid credentials), `403` (no access to the ZEV, token for another ZEV,
creator lost access, ZEV disabled), `404` (unknown ZEV), `429` (throttle).

## 6. Privacy rules (participant visibility)

For a caller with `full = False`:

1. Only rows whose participant is one of the caller's own participant ids; a gap row
   (`participant = null`) is never shown. A `participant` filter naming anyone else is `403`.
2. A community-mode share of a meter held by somebody else is real energy of the caller and is
   reported, but with `metering_point = null`: the meter id would name a neighbour's connection.
   Such energy is also not addressable through the `metering_point` filter. Personal meters are named.
3. `group_by=zev` is refused (`aggregate_suppressed`) unless every day of the range that had any
   eligible participant had at least *k* of them (`ANALYTICS_MIN_PARTICIPANTS_FOR_ZEV_AGGREGATE`,
   default 5; days with none are ignored; a range with no eligible participant at all is refused).
4. A participant whose record has ended, or any participant of a disabled ZEV, sees nothing.

Admin, manager and viewer visibility is never reduced by *k*.

Existing behaviour not changed here: the participant dashboard already returns ZEV totals
(`zev_totals`) without a minimum size. Aligning it is a separate decision.

## 7. Limits

| Limit | Value | Error |
|---|---|---|
| Span (inclusive days) | `15min` 14, `hour` 100, `day` 400, `week`/`month`/`year` 3660 | `range_too_large` |
| Readings scanned | `ANALYTICS_MAX_READINGS` (300,000) counted for the whole ZEV and range before computing | `range_too_large` |
| Output rows | `ANALYTICS_MAX_ROWS` (200,000) | `too_many_rows` |
| Rate | tokens `1200/hour` each; API keys the existing `api_key` throttle | `429` |

## 8. Analytics tokens

Endpoints (`analytics.views.AnalyticsTokenViewSet`, router prefix `tokens`, basename
`analytics-token`, `CookieJWTAuthentication`, `IsAuthenticated`, no pagination; `404` while the
flag is off):

| Method | Path | Behaviour |
|---|---|---|
| `GET` | `/analytics/tokens/` | non-revoked tokens: own, plus those of ZEVs the caller manages; admin: all |
| `POST` | `/analytics/tokens/` | body `{name, zev, participant?, expires_at?}`; `201` with the token fields and **`token`** (the secret, shown once) |
| `DELETE` | `/analytics/tokens/{id}/` | revokes (`revoked_at`), `204`; same visibility as the list (a foreign token is `404`) |

List item fields (`AnalyticsTokenSerializer`, all read-only): `id`, `name`, `zev`, `zev_name`,
`participant`, `participant_name`, `prefix`, `created_by_name`, `created_at`, `expires_at`,
`last_used_at`. Never the secret or the hash.

Creation rules (`analytics.scope.can_create_token`, `400` with `detail` otherwise): a whole-ZEV token
needs `can_view` of the ZEV; a participant token also goes to the participant themself (record
current) or to a manager (`can_manage`); the participant must belong to the ZEV; `expires_at`
must be in the future; the ZEV must not be disabled.

Authentication (`AnalyticsTokenAuthentication`, `Authorization: Bearer oza_<prefix>_<secret>`):
returns `(AnonymousUser, token)`. One `401` message for every failure ("Invalid or revoked analytics
token."): unknown prefix, wrong secret, revoked, expired, flag off, creator inactive. Per request
`resolve_visibility` additionally requires (`403`): token's ZEV equals the requested one, the ZEV is
not disabled, and `token_is_still_valid` (the creator could still create this token today), so a
token never outlives its creator's access, nor a participant their record.

Reach: the token is listed only on `SeriesView`; every other endpoint answers `401` (its default
authenticators do not know the scheme). Throttle: `AnalyticsTokenThrottle`, scope `analytics_token`,
keyed by token id.

Audit (`AuditActionCategory.AUTH`, target `analytics.AnalyticsToken`, `zev` set): `analytics_token.create`
(metadata `prefix`, `zev_id`, `participant_id`, `expires_at`) and `analytics_token.revoke`
(`prefix`). Reads are not audited per request (volume); `last_used_at` is the trace.

OpenAPI: `AnalyticsTokenAuthenticationScheme` documents the scheme.

## 9. Performance and the fact table

Measured on SQLite with a 25-meter ZEV (24 consumers, 1 producer), 30 days at 15 minutes
(72,000 readings), `day` granularity: `group_by=metering_point` / `participant` 1.3 s (750 rows),
`group_by=zev` 0.14 s. That is about 19 µs per reading, roughly 50,000 readings/s, in the
read-model loop (assignment lookup and Decimal split per reading). So the default cap of 300,000
readings is about six seconds for a ZEV-wide non-`zev` request, and a 25-meter ZEV can query about
four months at once; one year needs a ZEV of about eight meters. `group_by=zev` is cheap enough that
the reading cap, not time, is its only limit.

This is the evidence for the issue's "probably needed": a precomputed hourly allocation fact table
(per metering point, participant share and hour: total/local/grid/feed-in, refreshed by Celery after
imports, invalidated on assignment/reading changes, cleared by the privacy retention sweep) lifts
the caps and would speed up dashboards, the annual report and MCP. It is **not built here**;
`build_series` is the seam. Open points for that decision: invalidation on re-import and corrections,
retention sweep integration, and whether community-share rows are stored per participant or per meter.

## 10. Grafana (Infinity datasource)

No server code beyond §5/§8. Shipped artefacts:

- `deploy/grafana/provisioning/datasources/openzev.yaml`: Infinity datasource, URL allow-list for the
  instance, bearer token from an environment variable.
- `deploy/grafana/dashboards/openzev-analytics.json`: example dashboard (self-sufficiency per
  month, load profile, consumption by participant) with `zev`/granularity variables. Panels use the
  Infinity JSON parser with root selector `results` and the `${__from:date:YYYY-MM-DD}` macros for
  `from`/`to`.
- User guide chapter `21-analytics-and-grafana.md`: creating a token, the Infinity query settings,
  the unsupported "Grafana on PostgreSQL" path and why, privacy notes (data leaves OpenZEV).

The datasource provisioning and the example dashboard were checked by hand against Grafana (current OSS image) with the Infinity plugin, reading a seeded ZEV from a running backend with a token: the datasource provisions, the three panels draw the expected values (60 % self-sufficiency for 12 of 20 kWh local, one stacked series per participant, local vs grid per hour). There is no automated test for them.

## 11. Tests (`backend/analytics/`, 79 tests)

Shared fixture `analytics/testing.py` (`Community`: four participants, one community-mode meter,
known 10 kWh consumed / 6 kWh produced per interval; `enable_tokens`).

| Module | Count | Covers |
|---|---|---|
| `test_series.py` | 34 | ZEV totals split local/grid/feed-in; community meter shared by weight; parity with `dashboard-summary` `participant_stats`; meter + holder grouping; filters; unassigned energy kept with `participant = null`; hourly and 15-minute Swiss buckets; `bucket_start` for DST days, month, week, year, autumn hour (10 parametrised cases); CSV header/rows; span, reading, row limits; 422 on inconsistent readings; invalid parameters (6 cases); required `from`/`to`; unknown ZEV; empty range |
| `test_scoping.py` | 17 | anonymous 401; manager own ZEV / other ZEV 403; admin any; viewer; stranger 403; participant own rows only; own meter named, shared meter not; foreign `participant` filter 403; shared meter not addressable; other-ZEV participant 403; ZEV totals suppressed below *k*, shown at *k*, never for managers; ended participant; disabled ZEV; manager-and-participant sees all |
| `test_tokens.py` | 28 | create + secret once + hash only; audit without secret; participant/manager/viewer creation rules; foreign ZEV; participant of another ZEV; expiry in the past; tokens/keys cannot mint tokens; flag off hides endpoints; ZEV token reads without naming the ZEV; other ZEV 403; participant token narrowing (own, manager-made); reaches nothing else; garbage/foreign tokens 401; session still works; `last_used_at`; revoke (+audit); expired; flag off stops tokens; creator losing access; participant leaving; inactive creator; disabled ZEV; per-token throttle; list/revoke visibility (manager, participant, admin) |

Validation: `ruff check .`, `manage.py check`, `makemigrations --check`, full `pytest`.

## 12. Documentation and spec updates

- ADR 0039 and its index entry.
- User guide `21-analytics-and-grafana.md` (+ `mkdocs.yml` nav, `docs/user-guide/README.md`,
  cross-link from `16-api-keys.md`); `mkdocs build --strict` passes.
- `2026-03-community-and-access.md`: analytics token authentication on the series endpoint.
- `2026-03-admin-governance-and-settings.md`: the `analytics_tokens_enabled` flag.
- `2026-05-audit-log-and-operational-traceability.md`: `analytics_token.create` / `.revoke`.
- `AGENTS.md`: this spec listed under completed feature specs.

## 13. Follow-ups

1. Hourly allocation fact table (§9) once the caps hurt in practice.
2. Frontend: token management on the API-keys page; the Analysis page with curated Recharts views;
   Perspective / DuckDB-WASM exploration; saved views.
3. Supplementary data as `source = "supplementary"`.
4. Parquet/Arrow output for the in-browser engine.
5. MCP tools on the same dataset; savings simulator (#939) and load-shifting tips (#940) as consumers.
6. Align the participant dashboard's ZEV totals with the minimum community size.
