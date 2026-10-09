# Feature Spec: Supplementary energy data for metering points with generation behind the meter

- Spec ID: SPEC-2026-supplementary-energy-data
- Status: Implemented
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-10-08
- Target Release: TBD
- Related Issues: [#925](https://github.com/splattner/openzev/issues/925)
- Related ADRs: [0030](../adr/0030-supplementary-energy-data-is-not-billing-input.md) (never billing input), [0031](../adr/0031-integration-credentials-encrypted-under-a-dedicated-key.md) (connector credentials); builds on [0013](../adr/0013-shared-allocation-service.md), [0021](../adr/0021-mfa-secret-encryption-key.md), [0024](../adr/0024-backup-encryption-key.md), [0026](../adr/0026-swiss-civil-time-for-billing.md), [0027](../adr/0027-per-zev-access-grants.md)
- Related specs: [behind-the-meter generation](2026-09-behind-the-meter-generation.md) (the flag this feature hangs off)
- Impacted Areas: backend | frontend | async jobs | docs

---

## 1. Problem and outcome

A participant whose PV system sits **behind** their grid meter has a metering point that
records only the surplus fed in (`out`) and the residual grid draw (`in`). Their real
production and consumption never reach OpenZEV, so every statistic about them is misleading.
[SPEC-2026-behind-the-meter-generation](2026-09-behind-the-meter-generation.md) (1.21.0) stopped
the platform from *showing* a wrong self-sufficiency rate for such participants (they see `—`
and a note). It did not supply the right one. Its out-of-scope list names this feature.

Many such participants already own a system that measures the missing numbers: Solar Manager,
Home Assistant, an inverter portal. One real day from a Solar Manager installation (2026-07-01):

| Quantity | Value | Visible in OpenZEV today |
|---|---|---|
| Gross production | 48.2 kWh | no |
| Gross consumption | 12.5 kWh | no |
| Export (meter `out`) | 41.3 kWh | yes |
| Import (meter `in`) | 5.6 kWh | yes |
| Self-consumed directly | ~6.9 kWh | no |
| Self-sufficiency | ~55 % | shown as `—` |
| Self-consumption rate | ~14 % | not computable |

**Outcome:**

1. A participant who personally holds a metering point flagged `has_behind_meter_generation`
   can connect an external data source for it, with their explicit consent. Solar Manager is
   pulled from its cloud API; anything else (Home Assistant, n8n, an inverter export) delivers
   the same data through a token-authenticated push endpoint or a CSV upload.
2. The platform stores that data per 15-minute interval in its own table, separate from
   `MeterReading` and **never read by billing** ([ADR 0030](../adr/0030-supplementary-energy-data-is-not-billing-input.md)).
3. Statistics surfaces show the participant's real production, consumption, self-consumption
   rate and self-sufficiency, labelled as reported by their own system, wherever the data
   covers the period well enough. Where it does not, the `—` and note from the previous spec
   remain.
4. The source is reconciled against the official meter, so a wrong mapping, a unit error or a
   shifted timestamp is visible instead of silently producing a plausible-looking number.

Billing, allocation, invoices and invoice PDFs are unchanged and byte-identical in amounts with
or without this data.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Data model | `metering.SupplementarySource`, `metering.SupplementaryReading`, migrations |
| Credentials | `INTEGRATION_ENCRYPTION_KEYS`, `metering/supplementary/crypto.py`, `rotate_integration_key` command ([ADR 0031](../adr/0031-integration-credentials-encrypted-under-a-dedicated-key.md)) |
| Providers | Solar Manager pull (v3 API); push endpoint; CSV upload |
| Async | Beat-driven sync, per-source lease, backfill, retries, reconnect handling, orphan clean-up |
| Reconciliation | Source vs official meter: deviation, timestamp-shift detection |
| API | Source CRUD and actions, push ingest, CSV import, additive `gross_energy` blocks on existing payloads |
| Statistics | Participant dashboard, owner dashboard, annual report, annual statement PDF, MCP `consumption_summary` |
| Frontend | Account "Energy data" tab (participant), source status on the metering-point list (owner), gross cards and rates, i18n (de/fr/it/en) |
| Operations | Feature flag, system-health entry, system check, backup registry + manifest fingerprint, audit events |
| Transfer archive | Sources (without secrets) and readings (last phase) |
| Docs | User guide, baseline specs (see §11), `.env.example`, Helm values |

### Out of scope

- Any change to billing, allocation (`split_consumption` / `split_production`), invoices, invoice
  PDFs, tariffs or the data-quality checks on `MeterReading` (ADR 0030).
- Using supplementary values to fill, correct or replace official meter readings.
- Recomputing or excluding ZEV-wide totals and rates: they keep describing energy exchanged at
  the connection points.
- A Home Assistant **pull** connector. HA is usually LAN-only and entity ids are arbitrary; it
  is served by the push endpoint (documented recipe) in v1.
- Battery- and EV-specific figures. The rates below only need `import`, `export`, `production`
  and `consumption`, and are correct with a battery present because battery flows are internal
  to the site. Battery columns can be added later without breaking the model.
- Storing resolutions other than 15 minutes. The push endpoint and CSV reject anything else.
- Device control through the Solar Manager API (the key is used for reading only).
- The ZEV owner entering or holding a participant's credentials (open decision 12.1).
- Auto-detecting the timestamp convention of arbitrary providers.

## 3. Actors, permissions, and ZEV scope

All access follows the per-ZEV model of [ADR 0027](../adr/0027-per-zev-access-grants.md).

| Actor | Capability |
|---|---|
| `admin` | Everything below for any ZEV, including creating a source on a participant's behalf (support). |
| Manager of the ZEV (`zev_owner`, or a party holding a managing role) | Read sources and status in their ZEVs. `PATCH enabled`, `disconnect`, `purge`, `DELETE`. **Cannot** create a source, set or replace a credential, or rotate a push token. Cannot read any credential. |
| Viewer of the ZEV | Read-only: source list and status. |
| `participant` who personally holds the metering point today | Create, test, sync, edit, disconnect, purge and delete **their own** source; rotate their push token; read the gross figures about themselves. |
| Any other participant | No access to the source. They see the anonymised ZEV-wide figures only, as today. |
| Push client (token) | `POST /ingest/` for exactly one source. No other endpoint. |

"Personally holds today" means an active `MeteringPointAssignment` with
`allocation_mode = PERSONAL` whose `participant.user` is the requesting user, evaluated on the
Swiss civil date ([ADR 0026](../adr/0026-swiss-civil-time-for-billing.md)). Community-mode
holders cannot connect a source: their readings are split by weight and no single person's
household is described.

**Backend permission class:** `SupplementarySourcePermission` (new, in
`metering/permissions.py`), built on `BaseZevScopedPermission` semantics for scoping, with the
per-action rules above enforced in the view (`create`, `rotate_push_token`, credential writes
require the holder-or-admin check). Disabled ZEVs follow the existing rule: read-only for
non-admins.

**Frontend routes:** the participant UI lives on the existing `/account` page (all roles, tab
visible only to users who hold a flagged metering point); the owner view lives on
`/metering-points`. No new top-level route.

**Feature flag:** `FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED`
(`"supplementary_energy_data_enabled"`, default `False`, registered with a description, env
override `FEATURE_SUPPLEMENTARY_ENERGY_DATA_ENABLED`). While off: source and ingest endpoints
answer `404`, beat tasks skip, and every statistics surface behaves exactly as in 1.21.0
(`gross_energy` is `null`). Existing data is kept, not deleted.

## 4. Data model

### 4.1 SupplementarySource

**Model:** `metering.models.SupplementarySource`. One connection between one metering point and
one external system.

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` pk | `uuid4` | |
| `metering_point` | `OneToOneField(zev.MeteringPoint, CASCADE)` | — | `related_name="supplementary_source"`. One source per metering point in v1 |
| `participant` | `ForeignKey(zev.Participant, CASCADE)` | — | `related_name="supplementary_sources"`. The consenting holder; ingestion is clipped to their personal assignment windows |
| `provider` | `CharField(20)` | — | `SupplementaryProvider`: `solar_manager`, `push` ("push or file") |
| `label` | `CharField(100)` | `""` | Free text, e.g. "Solar Manager at home" |
| `external_id` | `CharField(64)` | `""` | Solar Manager `smId`; validated `^[A-Za-z0-9]{3,24}$`; required for `solar_manager`, empty for `push` |
| `credential_encrypted` | `BinaryField` | `b""` | Fernet ciphertext under `INTEGRATION_ENCRYPTION_KEYS` of `{"refresh_token": "..."}`. Never serialized. `solar_manager` only |
| `push_token_prefix` | `CharField(16, unique, null)` | `None` | `push` only. Identifies the token; stored in clear |
| `push_token_hash` | `CharField(64)` | `""` | `push` only. SHA-256 of the secret part, as `accounts.api_keys.hash_secret` |
| `enabled` | `BooleanField` | `True` | A disabled source is never pulled and rejects pushes |
| `status` | `CharField(20)` | `pending` | `SupplementaryStatus`: `pending`, `ok`, `error`, `reconnect_required`, `disabled` (see below) |
| `consented_at` | `DateTimeField` | — | Set at creation from the explicit consent in the request |
| `last_sync_at` | `DateTimeField(null)` | `None` | Last attempt |
| `last_success_at` | `DateTimeField(null)` | `None` | Last attempt that completed |
| `last_error` | `CharField(500)` | `""` | User-safe text only, never a raw exception or response body |
| `synced_through` | `DateTimeField(null)` | `None` | End of the last interval ingested (the pull high-water mark) |
| `covers_from` | `DateTimeField(null)` | `None` | Start of the earliest stored interval |
| `reconciliation` | `JSONField` | `dict` | Result of the last reconciliation (§6.5) |
| `created_by` | `ForeignKey(accounts.User, SET_NULL, null)` | `None` | |
| `created_at` / `updated_at` | `DateTimeField` | auto | |

**Status** is derived, not free-form: `disabled` when `enabled` is false; `reconnect_required`
when the vendor rejected the credential or it can no longer be decrypted (sync stops until the
participant enters a key again); `error` after a transient failure (sync is retried on the next
tick); `ok` after a completed sync; `pending` until the first one.

**Validation (`clean()`):**
- `metering_point.has_behind_meter_generation` must be true.
- `participant.zev_id == metering_point.zev_id`.
- `solar_manager` requires `external_id`; `push` requires it empty.
- At creation the participant must hold the metering point personally on the civil date
  (enforced in the serializer, not `clean()`, so a later assignment change does not invalidate
  existing rows).

**Cross-model rule:** `MeteringPointSerializer.validate()` rejects clearing
`has_behind_meter_generation` (and `MeteringPoint.clean()` the same) while a source exists:
`{"has_behind_meter_generation": ["Disconnect the energy data source first."]}`.

**Methods:** `credential` property decrypts on access and is never cached on the instance;
`set_credential(refresh_token)` encrypts and raises `ValidationError` when
`INTEGRATION_ENCRYPTION_KEYS` is empty; `clear_credential()` drops the credential and push
token; `disconnect()` also disables the source; `mark_ok()`, `mark_error(safe_text)`,
`mark_reconnect_required(safe_text)` (none of these save). `issue_push_token()` returns the full
token once and stores prefix and hash; it arrives with the push endpoint (PR 2). `save()` keeps
`status` consistent with `enabled`: disabling sets `disabled`, re-enabling returns to `pending`.

**Serializer:** `SupplementarySourceSerializer`. Read: `id`, `metering_point`,
`metering_point_meter_id`, `participant`, `participant_name`, `provider`, `label`,
`external_id`, `enabled`, `status`, `consented_at`, `last_sync_at`, `last_success_at`,
`last_error`, `synced_through`, `covers_from`, `reconciliation`, `has_credential`
(`SerializerMethodField`), `push_token_prefix`, `created_at`, `updated_at`. Write: `label`,
`enabled`, `external_id`, and the write-only `api_key` (replaces the credential) and `consent`
(must be `true` on create). Read-only: all others. `participant` is set from the request, not
accepted, except for admins.

### 4.2 SupplementaryReading

**Model:** `metering.models.SupplementaryReading`. One 15-minute interval of the participant's
own measurements, in kWh.

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` pk | `uuid4` | |
| `source` | `ForeignKey(SupplementarySource, CASCADE)` | — | `related_name="readings"`. Deleting a source deletes its data |
| `metering_point` | `ForeignKey(zev.MeteringPoint, CASCADE)` | — | `related_name="supplementary_readings"`. Denormalised from `source` for the unique constraint and range queries |
| `timestamp` | `DateTimeField` | — | **UTC start of the interval**, aligned to :00/:15/:30/:45, same convention as `MeterReading.timestamp` |
| `consumption_kwh` | `DecimalField(12,4)` | — | Gross consumption of the site |
| `production_kwh` | `DecimalField(12,4)` | — | Gross production of the site |
| `import_kwh` | `DecimalField(12,4)` | — | Drawn from the grid |
| `export_kwh` | `DecimalField(12,4)` | — | Fed into the grid |
| `created_at` / `updated_at` | `DateTimeField` | auto | |

**Meta:** `ordering = ["metering_point", "timestamp", "id"]`;
`UniqueConstraint(fields=["metering_point", "timestamp"], name="uniq_supplementary_reading_mp_ts")`;
`CheckConstraint` that all four energies are `>= 0` (`supplementary_reading_non_negative`).
Re-delivery of an interval is an **upsert** (vendors revise recent values). There is deliberately
no `direction` and no `import_source`: the row is one interval with all four flows.

**Values are stored as delivered.** Derived quantities (self-consumption) are computed at read
time (§4.3), because vendors disagree with themselves on the derived fields: in the sample day
Solar Manager's `cPvWh` and `scWh` differ without a battery and import and export are both
non-zero in the same interval.

### 4.3 Derived figures (the one definition)

Implemented once in `metering/supplementary/stats.py` (`gross_energy(...)`), used by every
surface. Per interval *i*:

```
self_consumption_i = min( max(production_i - export_i, 0), production_i, consumption_i )
```

Over a window:

```
self_consumption_kwh   = Σ self_consumption_i
self_sufficiency_rate  = clamp( 1 - Σ import_i / Σ consumption_i , 0, 1 )   # null if Σ consumption = 0
self_consumption_rate  = Σ self_consumption_i / Σ production_i               # null if Σ production = 0
```

Percent rounding follows `invoices.annual_report._rate`. All four inputs come from the
supplementary data alone, so numerator and denominator are one consistent measurement. The
official meter is used only for reconciliation (§6.5).

### 4.4 Coverage

An interval counts as *expected* when it lies inside a window during which the source's
participant held the metering point personally, falls between `covers_from` and `synced_through`,
and lies in the requested window. `coverage_pct = present / expected`. Rates are computed when
`coverage_pct >= SUPPLEMENTARY_MIN_COVERAGE` (default `0.95`) and `present > 0`; otherwise they
are `null` and `rates_withheld_reason` is `"low_coverage"` or `"no_data"`. The payload also
reports `covered_from` / `covered_to`, and a window the source only partly spans (the participant
connected in March; the report is for the year) is shown as "based on data from 3 March", never
silently extrapolated.

### 4.5 Settings

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `INTEGRATION_ENCRYPTION_KEYS` | `env.list` | `[]` | Fernet keys for connector credentials (ADR 0031) |
| `SUPPLEMENTARY_SYNC_INTERVAL_S` | `env.int` | `3600` | Beat period of `refresh_supplementary_sources` |
| `SUPPLEMENTARY_MIN_COVERAGE` | `env.float` | `0.95` | §4.4 |
| `SUPPLEMENTARY_BACKFILL_MAX_DAYS` | `env.int` | `400` | Oldest history ever pulled for a new source |
| `SUPPLEMENTARY_RECONCILE_TOLERANCE` | `env.float` | `0.10` | Deviation above which reconciliation warns |
| `SOLAR_MANAGER_BASE_URL` | `env` | `https://cloud.solar-manager.ch` | Overridable only so tests can point at a stub; the production value is the only host the client contacts |
| `SUPPLEMENTARY_INGEST_MAX_ROWS` | `env.int` | `2000` | Rows per push request |
| `SUPPLEMENTARY_CSV_MAX_ROWS` | `env.int` | `50000` | Rows per CSV upload (the file is also capped at 8 MB) |
| `DEFAULT_THROTTLE_RATES["supplementary_push"]` | rate | `120/hour` | Per push token |

## 5. API contracts

New endpoints sit under `/api/v1/metering/supplementary/` (registered in `metering/urls.py`).
All answer `404` while the feature flag is off.

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/sources/` | GET | `SupplementarySourcePermission` | Scoped list (admin all; manager/viewer their ZEVs; participant their own). Filter `?zev_id=` (as on every ZEV-scoped list), `?metering_point=` |
| `/sources/` | POST | holder or admin | Create. Requires `consent: true`, a flagged metering point, a free metering point (one source each). `solar_manager`: needs `external_id` and `api_key`; the key is exchanged and one interval fetched **before** anything is saved, so a wrong key is a `400` with a safe message, not a broken row. Without a configured `INTEGRATION_ENCRYPTION_KEYS`: `503` naming the setting. `push`: returns the push token **once** in `push_token`. A provider that is not registered is refused with `400`. After the commit a backfill sync is queued (`backfill=True`, §6.3); a broker outage is logged and does not fail the request. A manager gets `403`; someone who cannot see the metering point gets `400 Invalid pk`, so its existence is not revealed. Audited `supplementary_source.create` |
| `/sources/eligible/` | GET | authenticated | The flagged metering points the caller personally holds today (enabled ZEVs only), each with its `source` id or `null`; `[]` for anyone else, an admin included. What the Account page offers to connect (PR 5) |
| `/sources/{id}/` | GET | scoped | Detail |
| `/sources/{id}/` | PATCH | holder or admin; manager only for `enabled` | `label`, `enabled`, `external_id`, write-only `api_key`. An absent `api_key` keeps the stored one. A new key, or switching a disabled source back on, queues a sync. Audited `supplementary_source.update` with a diff over the tracked fields and `credential_changed` in metadata, never the value |
| `/sources/{id}/` | DELETE | holder, manager, admin | Deletes the source **and all its readings**. Audited `supplementary_source.delete` |
| `/sources/{id}/disconnect/` | POST | holder, manager, admin | Sets `enabled = false`, wipes the credential or push token, **keeps the readings**. Audited `supplementary_source.disconnect` |
| `/sources/{id}/purge/` | POST | holder, manager, admin | Body `{date_from?, date_to?}` (civil dates; both absent = everything). Deletes readings only. Audited `supplementary_source.purge` with the count |
| `/sources/{id}/test/` | POST | holder or admin | `solar_manager`: refresh (a rotated key is stored) + one hour of data; `{"ok": true}` or `400 {"detail"}` with a safe message. A rejected key also sets `reconnect_required`. Never echoes credentials or a raw vendor response. `400` for a push, disconnected or unregistered source |
| `/sources/{id}/sync/` | POST | holder or admin | Queues a sync now, `202 {"queued": true}`. At most one per source per 5 minutes (`429` with `Retry-After: 300` otherwise). `400` for a push or disconnected source and for one that is `reconnect_required` (enter the key again first) |
| `/sources/{id}/rotate-push-token/` | POST | holder or admin | `push` only. Issues a new token, returned once; the old one stops working at once |
| `/sources/{id}/reconciliation/` | GET | scoped | The newest 14 comparable days with per-day totals (§6.5), computed on demand |
| `/sources/{id}/import-csv/` | POST | holder or admin | Multipart `file`; `?dry_run=true` validates only. Columns `timestamp,consumption_kwh,production_kwh,import_kwh,export_kwh`. All-or-nothing: one invalid row rejects the file with per-row errors. Same response as ingest |
| `/ingest/` | POST | `SupplementaryPushAuthentication` (token `ozs_<prefix>_<secret>` as `Authorization: Bearer`) | Body `{"readings": [{timestamp, consumption_kwh, production_kwh, import_kwh, export_kwh}, ...]}`, at most 2000 per request. Throttled per token (`supplementary_push`) |

**Ingest/CSV validation and response.** A reading is rejected, not coerced, if: the timestamp
is naive, not aligned to a 15-minute boundary, in the future, or older than
`SUPPLEMENTARY_BACKFILL_MAX_DAYS`; any value is missing, negative, non-numeric, not finite or
implausibly large; or the same timestamp appears twice in the request. Values are **rounded
half-up to four decimals** rather than refused: a Home Assistant sensor reports `0.0933500001`,
and a Solar Manager Wh value divided by 1000 has five. Offsets are normalised to UTC. A reading is
dropped (counted separately as `dropped_outside_assignment`, not an error) when its interval lies
outside the participant's personal assignment windows. Valid rows are upserted in one transaction
per request; a successful store advances `covers_from` / `synced_through` (never backwards) and
marks the source `ok`. Pushes are not audited one by one (a 15-minute feed would flood the log);
the source's `last_sync_at` is their trace. The ingest endpoint answers `401` (one message for
every bad token), `403` for a disabled source and `429` past the per-token throttle.

```json
{ "accepted": 96, "updated": 4, "rejected": [{"index": 17, "reason": "timestamp not aligned to 15 minutes"}],
  "dropped_outside_assignment": 0 }
```

A disabled source answers `403 {"detail": "Source is disabled."}`; a disconnected one has no token left and answers `401`.

### 5.1 Additive changes to existing payloads

No existing field changes meaning or type. Each block below is present in every response and is
`null` when the feature flag is off, the participant has no source, or the source has no data in
the window. All of it is computed in `metering/supplementary/surfaces.py` on top of
`stats.gross_energy`; the surfaces never read the models. The window is the inclusive civil
dates the request asked for (open ends are unbounded), not the span of the meter readings,
because official data is often imported later than the source delivers. The shared shape
(`GrossEnergy`):

```json
{
  "source_provider": "solar_manager",
  "covered_from": "2026-07-01T00:00:00Z",
  "covered_to": "2026-10-07T21:45:00Z",
  "coverage_pct": 99.2,
  "production_kwh": 4812.4, "consumption_kwh": 1249.1,
  "import_kwh": 561.8,      "export_kwh": 4128.8,
  "self_consumption_kwh": 683.6,
  "self_consumption_rate": 14.2, "self_sufficiency_rate": 55.0,
  "rates_withheld_reason": null,
  "timeline": [{"bucket": "...", "production_kwh": 0, "consumption_kwh": 0,
                "import_kwh": 0, "export_kwh": 0, "self_consumption_kwh": 0}]
}
```

- **Participant dashboard** (`dashboard-summary`, participant path): top-level `gross_energy`
  (`GrossEnergy | null`) for the signed-in user's own participants (summed if they have several),
  with `timeline` bucketed like the dashboard's own (`bucket_key_for` produces the identical
  `isoformat()` labels: civil days and months in the business timezone, UTC hours).
  `has_behind_meter_generation` and the `—` semantics are unchanged. The anonymised
  `zev_participant_stats` of other participants carry no gross figures.
- **Owner dashboard** (`dashboard-summary`, ZEV path, so managers, viewers and admins, the roles
  the consent text tells the participant about): each `participant_stats[]` entry gains
  `gross_energy` (without `timeline`); a selected participant adds top-level
  `selected_gross_energy` (with `timeline`, `null` without a source). Participants without a
  source cost no extra query. It also carries `own_gross_energy` (with `timeline`): the signed-in
  user's own figures as a participant of that ZEV, whoever is selected, `null` without one. A
  manager is usually a participant too, and their own picture should not hide behind a dropdown.
- **Annual report** (`/api/v1/invoices/invoices/annual-report/`): `participants[]` gains
  `gross_energy` (without `timeline`). `self_sufficiency_rate` stays `null` for net-metered
  participants; `totals`, `previous_totals` and `months` are unchanged.
- **Annual statement** (PDF context): for a net-metered participant, each civil month with
  coverage `>= SUPPLEMENTARY_MIN_COVERAGE` carries the gross `self_sufficiency_pct`; other months
  stay `None` (`—`). The year's `totals.self_sufficiency_pct` is filled only when the year, judged
  on its own coverage, passes too (so one badly covered month keeps the total at `—`). Participants
  who are not net-metered are untouched. Context gains `gross_energy_source: "solar_manager" | "push" | None`, and the
  template swaps `behind_meter_note` for the new `behind_meter_supplementary_note` when at least
  one month shows a gross rate (new key in all four languages of `ANNUAL_TRANSLATIONS`, and in
  `field_catalog_data.py`). de: "Ihre Photovoltaikanlage liegt hinter dem Zähler. Die
  ausgewiesene Autarkie beruht auf den Messwerten Ihres eigenen Systems (z. B. Solar Manager),
  nicht auf der Zählerablesung des Netzbetreibers. Monate ohne ausreichende Daten sind mit —
  gekennzeichnet." en/fr/it equivalents.
- **MCP** `consumption_summary`: each participant entry gains `gross_self_sufficiency_pct`,
  `gross_self_consumption_pct` and `gross_coverage_pct` (`null` when absent), under the tool's
  existing scoping; with `participant_id` the same three keys are added to `totals`. The tool
  reads them from the dashboard endpoint it already calls.
- **Metering point** (`MeteringPointSerializer`): gains read-only `supplementary_source_status`
  (`null` or the source status string) so the list can show it without a second request. It is
  `null` for anyone who could not read the source itself (another participant must not learn that
  a neighbour has one) and while the feature is off.

## 6. Async and integration behavior

### 6.1 Provider interface

`metering/supplementary/providers.py`:

```python
class Provider(Protocol):
    def verify(self, external_id: str, credential: str) -> str: ...      # returns the credential to store
    def check(self, source: SupplementarySource) -> None: ...             # "test connection"
    def fetch(self, source: SupplementarySource, start: datetime, end: datetime) -> Iterator[list[Point]]: ...
```

`Point` is a `NamedTuple` `(timestamp, consumption_kwh, production_kwh, import_kwh, export_kwh)`
with an aware UTC interval-start timestamp. `fetch` yields one list per chunk (for Solar Manager
one civil day), oldest first, so the caller stores each before asking for the next. Errors:
`ProviderAuthError` (the vendor rejected the credential or the installation),
`ProviderRateLimited(retry_after)` and `ProviderError` (transient); every message is safe to show
the participant. `solar_manager.py` registers `SolarManagerProvider` in `PROVIDERS` on import,
and `MeteringConfig.ready()` imports it. `push` has no provider, it delivers through §5. A future
provider only has to return `Point`s.

### 6.2 Solar Manager

Source of truth: `https://cloud.solar-manager.ch/swagger.json` (API v1.88.11, retrieved
2026-10-08), and one real response (2026-07-01, 96 intervals).

- **Endpoint:** `GET /v3/users/{smId}/data/range?from=&to=&interval=900` with an ISO
  `from`/`to`. The v1 `/v1/consumption/gateway/{smId}/range` named in the original idea is
  **deprecated since 2025-06 with removal scheduled for 2026-06** and returns power only; it is
  not used.
- **Fields mapped:** `cWh` → `consumption_kwh`, `pWh` → `production_kwh`, `iWh` →
  `import_kwh`, `eWh` → `export_kwh`, each divided by 1000. `t` is the interval timestamp in
  UTC. The vendor's derived `cPvWh` / `scWh` and all `*W` power fields are ignored.
- **Observed on the real day:** exactly 96 intervals 900 s apart, no gaps or nulls, `cWh` equals
  `cW × 0.25 h` to within ~1 Wh, and the balance closes within 1.5 Wh per interval
  (`pWh = eWh + cPvWh`, `cWh = cPvWh + iWh`). A system without a battery returns `0` for the
  battery fields.
- **Authentication:** the participant's API key is a **refresh token**. `POST /v3/auth/refresh`
  exchanges it for a one-hour bearer token. With key rotation on, the response also carries a
  **new refresh token** (30 days) and the old one is dead. The client persists the new token
  before using the bearer token (ADR 0031); a response that cannot be saved is a failed
  refresh. The legacy email/password `/v1/oauth/login` is deprecated (removal 2027-06) and is
  not supported.
- **Chunking:** one civil day per request (96 intervals). The vendor does not document a
  maximum range or a rate limit, so the client pulls conservatively (0.25 s between requests,
  sequential per source), turns a `429` into `ProviderRateLimited` carrying `Retry-After`
  (bounded to one hour), and treats 5xx and timeouts as transient. A `401`, `403` or `404` from
  the data endpoint, and a `400`, `401` or `403` from the refresh, mean the key or the installation
  is not accepted (`ProviderAuthError`). A row missing any of the four flows is skipped (a gap,
  never a zero); a negative value within 5 Wh is sensor noise and reads as 0, a larger one is left
  for ingest validation to reject.
- **HTTP:** `urllib` as in `tariffs/importers/remote.py`; one fixed host
  (`SOLAR_MANAGER_BASE_URL`), redirects refused, a 20 s timeout, a 2 MiB response-size cap, and the
  `smId` validated against `^[A-Za-z0-9]{3,24}$` before it enters a URL. No user-supplied host.
- **Timestamp convention (verified 2026-10-08):** `t` is the **start** of its interval, the
  same convention as `MeterReading.timestamp`, so values are stored without any shift. Checked
  by importing the real SDAT data for the same metering point and comparing Solar Manager's
  2026-07-01 series (96 intervals) with the meter's `out`/`in` at shifts of -3 to +3 intervals.
  The mean absolute error per interval is smallest at shift 0 by a wide margin:

  | Shift (intervals) | -3 | -2 | -1 | **0** | +1 | +2 | +3 |
  |---|---|---|---|---|---|---|---|
  | `eWh` vs meter `out` (kWh) | 0.205 | 0.179 | 0.118 | **0.0045** | 0.121 | 0.180 | 0.208 |
  | `iWh` vs meter `in` (kWh) | 0.028 | 0.019 | 0.010 | **0.0005** | 0.010 | 0.019 | 0.028 |

  Day totals agree to within the metering noise: export 41.29 vs 41.31 kWh (0.05 %), import
  5.62 vs 5.64 kWh (0.4 %). The provider therefore carries `T_MARKS_INTERVAL = "start"` and
  applies no offset; the constant stays so a vendor change would be a one-line fix, and
  reconciliation (§6.5) keeps checking it. Both series are UTC, so no timezone conversion is
  involved at ingestion.

### 6.3 Sync tasks (`metering/tasks.py`)

- `refresh_supplementary_sources` (beat, `SUPPLEMENTARY_SYNC_INTERVAL_S`): when the flag is on,
  fans out `sync_supplementary_source.delay(id)` for every `enabled` source of a pull provider
  with status other than `reconnect_required`. One unreachable vendor account cannot delay the
  others.
- `sync_supplementary_source(source_id, backfill=False)` (`bind=True, max_retries=2,
  default_retry_delay=600`; the logic is `sync_supplementary_source_impl`, called directly by
  tests): takes a per-source cache lease (30 minutes, same pattern as `dynamic_source_lock`); if
  held, skips. The window is `[max(synced_through - 2 days, backfill_floor), floor(now to 15
  min))`: the two-day overlap re-fetches recent intervals so late or revised vendor values are
  upserted. `backfill_floor` is the latest of `now - SUPPLEMENTARY_BACKFILL_MAX_DAYS` and the
  start of the participant's personal assignment; `backfill=True` ignores `synced_through`. The
  window is cut to the participant's personal assignment windows before anything is requested, and
  every chunk goes through `ingest.ingest`, the same validation and clipping as push and CSV
  (a rejected vendor row is counted, not fatal). Each civil day is stored, and `synced_through`,
  `covers_from` and `last_*` advanced, before the next is requested, so an interrupted run
  resumes. The source is re-checked as enabled before each chunk and failure states are written
  with a conditional update, so a disconnect during a run is never overwritten. A run that finds
  nothing new still succeeds. Skip reasons (returned, not errors): `feature_off`,
  `not_a_pull_source`, `disabled`, `reconnect_required`, `nothing_to_sync`, `missing`, `busy`.
- **When it is queued:** by the beat fan-out; with `backfill=True` after a source is created; and
  after a new key or after a disabled source is switched back on. The `sync` action queues it too.
- **Failure handling:** an auth failure from the vendor, or `MultiFernet` unable to decrypt,
  sets `reconnect_required` (no retry; the UI asks the participant to enter a key again). A
  transport error, `429` or 5xx sets `error` and retries (a `429` waits at least its `Retry-After`, otherwise the default delay); the next tick picks it up anyway. A
  deleted source between fan-out and execution is not an error.
- **Credential refresh** runs inside `transaction.atomic()` with
  `select_for_update()` on the source row, so two workers cannot both exchange the same
  refresh token. The row is re-read under the lock, so the token spent is always the latest. A
  long run renews its one-hour access token after 45 minutes.
- **Audit:** best-effort `supplementary_source.sync` events (category `METERING`, source
  `CELERY`), never carrying a token; the audit write cannot turn a successful sync into a failure.
- `disable_orphaned_supplementary_sources` (beat, daily): any source whose participant no longer
  holds the metering point personally today is set `enabled = false`, its credential or push
  token wiped, its readings kept. This is the consent boundary of ADR 0030: data stops flowing
  when the tenancy ends. Audited `supplementary_source.disconnect` with reason
  `assignment_ended`.

### 6.4 Time

Readings are UTC instants; every calendar question (which day, month, year, whether the
participant held the meter) is answered in Swiss civil time with `allocation.validity.civil_date`
([ADR 0026](../adr/0026-swiss-civil-time-for-billing.md)). Chunk boundaries for the vendor are
civil days converted to UTC, so a DST day yields 92 or 100 intervals, not 96.

### 6.5 Reconciliation (`metering/supplementary/reconcile.py`)

Run after every successful sync (and on demand by `GET /reconciliation/`) over the newest 7
(on demand: 14) civil days that have both supplementary rows and official `MeterReading`s for
the metering point, looking back at most 60 days because official data is often imported in
batches. A day is comparable when at least 90 % of its intervals (92 or 100 on a DST day) are
present on both sides for both flows, and only intervals present on both sides are summed. `energy_kwh` of `direction = "out"` is compared with `export_kwh`, and
`direction = "in"` with `import_kwh`.

Result stored in `SupplementarySource.reconciliation` (the on-demand view adds `days`, one
`{date, export_source_kwh, export_meter_kwh, import_source_kwh, import_meter_kwh}` per day):

```json
{ "checked_at": "...", "days_compared": 7, "export_deviation_pct": 1.8, "import_deviation_pct": 3.1,
  "best_shift_intervals": 0, "state": "ok" }
```

- `*_deviation_pct = |Σ source − Σ meter| / max(Σ meter, 1 kWh) × 100` per flow.
- `best_shift_intervals`: the shift in `[-2, 2]` intervals that minimises the summed absolute
  difference of the 15-minute export series against the meter's `out`.
- `state`: `ok` below `SUPPLEMENTARY_RECONCILE_TOLERANCE`; `warn` above it, or when a non-zero
  shift cuts the error by more than half ("timestamps look shifted by N intervals");
  `insufficient` when fewer than 2 days are comparable (e.g. official data not imported yet).
- Purely diagnostic: it changes nothing, never blocks a sync and never alters a rate. A `warn`
  is shown on the source card and in the owner's status.

### 6.6 Operations

- **System health:** `GET /auth/system-health/` gains a `supplementary` probe: `unknown` while
  the flag is off; otherwise `degraded` when `INTEGRATION_ENCRYPTION_KEYS` is unset or an enabled
  pull source (not `pending` or `reconnect_required`, which are the participant's to fix) has not
  succeeded for six sync intervals, else `ok`. It carries `feature_enabled`,
  `encryption_key_configured`, `sources_by_status`, `stale_sources` and `oldest_last_success_at`
  (the TypeScript type is added now; the panel renders it with the frontend, PR 5).
- **System check:** `metering.W001` warns when the feature flag is forced on through the
  environment (`FEATURE_SUPPLEMENTARY_ENERGY_DATA_ENABLED`) and no key is configured. Environment
  only, because system checks run without a database; the health panel reports the case where the
  flag is switched on in the admin UI.
- **Backups:** `backups/registry.py` lists both models in a new ZEV section `supplementary`
  (sources before readings); the registry's coverage test enforces it. The manifest's
  `secret_fingerprints` gains `integration_encryption_keys`, and restore warns when a source's
  credential was encrypted under a key this instance lacks. Those sources come back as they were
  and become `reconnect_required` at their first sync, when decryption fails.
- **Key rotation:** `manage.py rotate_integration_key`, idempotent, one transaction.
- **Deletion cascades:** deleting a participant, a metering point or a ZEV removes their
  sources and readings (`CASCADE`); the ZEV purge (`zev/purge.py`) needs no change beyond the models being covered by the backup registry.

## 7. Frontend

### 7.1 Participant: Account → "Energy data"

**Files:** `frontend/src/features/account/EnergyDataSection.tsx`,
`SupplementarySourceModal.tsx`, `SupplementarySourceCard.tsx`; shared pieces in
`features/supplementary/` (`SourceStatusBadge`, `ReconciliationSummary`, `PushTokenPanel`,
`CsvImport`); `accountTabs.ts` gains `'energy-data'` (`ACCOUNT_TABS`) and
`resolveAccountTab` takes `energyDataAvailable`, so a link to the tab lands on Profile for everyone
who cannot use it.

**Visibility.** The tab exists only when the feature is on *and* the user personally holds a
flagged metering point. The frontend asks `GET /metering/supplementary/sources/eligible/` (added in
PR 5; `useEnergyDataEligibility` in `lib/supplementary.ts`): `404` means the feature is off, an
empty list means nothing to connect. It returns, for the signed-in user only (an admin gets `[]`),
the flagged meters they hold personally today in an enabled ZEV, each with its `source` id or
`null`: `{metering_point, meter_id, zev, zev_name, participant, source}`.

- Query: `useQuery({ queryKey: queryKeys.metering.supplementarySources(), queryFn: listSupplementarySources })`,
  joined to the eligible list by metering point.
- Per flagged metering point: if no source, an explanation and **Connect**; otherwise the card:
  status chip, last sync, covered range, reconciliation state, and actions **Test**, **Sync
  now**, **Replace key**, **Disconnect** (keeps data), **Delete data**, **Remove source**.
- Modal (create): provider choice; consent checkbox with the data-use text (what is stored: four
  values per quarter hour; who can see it: you, and the ZEV's managers see status and your
  figures; what it is *not* used for: billing); for Solar Manager `smId` and API key fields (key
  is write-only, input type `password`, never echoed), with a link to where to create the key;
  for Push/File a one-time token display with a copy button, the endpoint URL, the CSV column
  list, and the Home Assistant recipe link.
- Mutations invalidate `metering.supplementarySources` and the dashboard queries.

### 7.2 Owner: metering-point list

**File:** `frontend/src/features/meteringPoints/MeteringPointsList.tsx`; new
`SupplementarySourceStatus.tsx` (a button-styled badge, `badge-button` in `index.css`, and the panel).

Flagged metering points show a status chip from `supplementary_source_status`, and an owner can
open a read-only panel (status, last sync, coverage, reconciliation) with **Disable**,
**Delete data** and **Remove source** (manager actions only). No credential field is shown to
an owner.

### 7.3 Statistics surfaces

- `ParticipantDashboardBody.tsx`: a net-metered participant with `gross_energy` sees
  `components/dashboard/GrossEnergyCard.tsx` (production, consumption, import, export, self-consumption,
  the two rates, coverage and "based on data from … to …", a production-vs-export timeline) in
  place of the `—` hint; without a source they see a call to action linking to the Energy data
  tab (only shown when the tab exists: feature on). Rates are labelled "reported by your own system".
  `ManagementDashboardBody` shows the same card for the selected participant
  (`selected_gross_energy`), and, as a permanent block under the ZEV figures, the manager's own
  (`own_gross_energy`, or the call to action when they hold an unconnected flagged meter in this
  community). The own row is marked "You" in the table and the dropdown; selecting oneself shows the
  block once. Selecting the selected table row again clears the selection.
- `components/dashboard/ParticipantTableCard.tsx`: the per-participant rate cell of a net-metered
  participant is `NetMeteredRate` (shared with the annual report): the gross rate with an info
  marker when `gross_energy` is present, else `—` as today (with the withheld reason as a tooltip).
  A participant who is not net-metered is untouched.
- `features/reports/AnnualReportSection.tsx`: same rule per participant row.
- Fallback rule everywhere: `rates_withheld_reason` set → `—` plus a short reason
  (insufficient coverage / no data).
- All text through `react-i18next`, keys under `supplementary.*`, in `de`, `fr`, `it`, `en`.
  Colours via design tokens only (`scripts/check-frontend-hex.mjs` must pass).

### TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export type SupplementaryProvider = 'solar_manager' | 'push'
export type SupplementaryStatus = 'pending' | 'ok' | 'error' | 'reconnect_required' | 'disabled'

export interface SupplementaryReconciliation {
    checked_at?: string
    days_compared?: number
    export_deviation_pct?: number
    import_deviation_pct?: number
    best_shift_intervals?: number
    state?: 'ok' | 'warn' | 'insufficient'
}

export interface SupplementarySource {
    id: string
    metering_point: string
    metering_point_meter_id: string
    participant: string
    participant_name: string
    provider: SupplementaryProvider
    label: string
    external_id: string
    enabled: boolean
    status: SupplementaryStatus
    consented_at: string
    last_sync_at: string | null
    last_success_at: string | null
    last_error: string
    synced_through: string | null
    covers_from: string | null
    reconciliation: SupplementaryReconciliation
    has_credential: boolean
    push_token_prefix: string | null
    created_at: string
    updated_at: string
}

export interface GrossEnergyPoint {
    bucket: string
    production_kwh: number
    consumption_kwh: number
    import_kwh: number
    export_kwh: number
    self_consumption_kwh: number
}

export interface GrossEnergy {
    source_provider: SupplementaryProvider
    covered_from: string | null
    covered_to: string | null
    coverage_pct: number
    production_kwh: number
    consumption_kwh: number
    import_kwh: number
    export_kwh: number
    self_consumption_kwh: number
    self_consumption_rate: number | null
    self_sufficiency_rate: number | null
    rates_withheld_reason: 'low_coverage' | 'no_data' | null
    timeline?: GrossEnergyPoint[]
}
```

`ParticipantDashboardSummary`, the owner `participant_stats[]` entry, the annual-report
participant row and `MeteringPoint` gain `gross_energy: GrossEnergy | null` /
`supplementary_source_status: SupplementaryStatus | null`.

### API client functions

**File:** `frontend/src/lib/api/supplementary.ts`

| Function | Method | Endpoint |
|---|---|---|
| `listSupplementarySources()` | GET | `/metering/supplementary/sources/` |
| `createSupplementarySource()` | POST | `/metering/supplementary/sources/` |
| `updateSupplementarySource()` | PATCH | `/metering/supplementary/sources/{id}/` |
| `deleteSupplementarySource()` | DELETE | `/metering/supplementary/sources/{id}/` |
| `disconnectSupplementarySource()` | POST | `/metering/supplementary/sources/{id}/disconnect/` |
| `purgeSupplementaryReadings()` | POST | `/metering/supplementary/sources/{id}/purge/` |
| `testSupplementarySource()` | POST | `/metering/supplementary/sources/{id}/test/` |
| `syncSupplementarySource()` | POST | `/metering/supplementary/sources/{id}/sync/` |
| `rotateSupplementaryPushToken()` | POST | `/metering/supplementary/sources/{id}/rotate-push-token/` |
| `importSupplementaryCsv()` | POST | `/metering/supplementary/sources/{id}/import-csv/` (`?dry_run=true` to check) |
| `listEligibleMeteringPoints()` / `fetchEligibleOrNull()` | GET | `/metering/supplementary/sources/eligible/` (`null` on `404`) |
| `fetchSupplementaryReconciliation()` | GET | `/metering/supplementary/sources/{id}/reconciliation/` (client only; no screen yet) |

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Supplementary data reaches billing | High | Separate tables; import-isolation test; invoice-amount-invariance test; only `metering/supplementary/stats.py` reads it (ADR 0030) |
| Interval timestamp convention differs from `MeterReading` | High (a silent 15-minute shift, wrong curves) | Verified as interval start against a real meter day (§6.2); provider constant; reconciliation detects shifts continuously |
| Rotated refresh token lost → participant locked out of their own key | High | Persist before use; row lock; `reconnect_required` state and re-entry flow; failure to save = failed refresh |
| Two workers refresh concurrently and invalidate each other | Medium | `select_for_update` plus per-source lease |
| A rate shown from partial data reads as a real figure | Medium | Coverage threshold, `covered_from/to` shown, rates `null` below it |
| Vendor changes or removes the API (v1 already deprecated) | Medium | One provider module, fixed v3 contract, `error` state surfaces failures, tests against a fixture shaped like the real response |
| Privacy: household profile retained after the tenant leaves | High | Consent bound to the holder; daily orphan job disconnects at assignment end; purge and delete actions; participant delete cascades |
| Credential leaked via logs, audit, errors, backups | High | Write-only field; redacted audit metadata; safe error text; dedicated key, ciphertext only in backups (ADR 0031) |
| Push endpoint abused or token leaked | Medium | Hashed token, per-token throttle, one source per token, rotate action, strict validation, 2000-row cap |
| Unit mistakes in a push client (Wh sent as kWh) | Medium | Reconciliation deviation shows it; user-guide recipe states units; values are rejected only if non-numeric/negative |
| Vendor rate limit/range unknown | Low | Day-sized chunks, `Retry-After`, sequential per source, hourly cadence |
| Another table doubles the backup/transfer surface | Low | Registry coverage test forces a decision; readings are ~35 000 rows per source per year |

## 9. Test plan

All counts are targets for the implementing PRs and are updated to the real numbers when
each lands.

### Backend — foundation (PR 1: 59 tests)

**`metering/test_supplementary_models.py`: `SupplementaryModelTests`** (15):

| Test | Asserts |
|---|---|
| `test_source_requires_flagged_metering_point` | `full_clean()` rejects an unflagged meter |
| `test_source_participant_must_share_zev` | cross-ZEV participant rejected |
| `test_external_id_rules_per_provider` | Solar Manager id format; a push source must have none |
| `test_one_source_per_metering_point` | second source violates the one-to-one |
| `test_clearing_flag_blocked_while_source_exists` | `MeteringPoint.clean()` rejects |
| `test_clearing_flag_blocked_through_the_api` | `PATCH` answers 400 and the flag stays set |
| `test_flag_can_be_cleared_once_the_source_is_gone` | the guard lifts with the source |
| `test_reading_unique_per_metering_point_and_timestamp` | constraint |
| `test_reading_rejects_negative_values` | check constraint, each of the four columns |
| `test_deleting_a_source_deletes_its_readings` | cascade |
| `test_credential_roundtrip_stores_only_ciphertext` | encrypt/decrypt; plaintext absent from the column |
| `test_set_credential_without_key_raises` | `ValidationError` naming the setting |
| `test_status_transitions` | `pending`, `ok`, `error`, `reconnect_required`, `disabled`, back to `pending` |
| `test_disconnect_disables_and_wipes_secrets_but_keeps_readings` | §6.3 consent boundary |
| `test_last_error_is_truncated` | 500 characters |

**`metering/test_supplementary_crypto.py`** (12): `CryptoTests` (4: round trip, no key refuses both
directions, a prepended key keeps old tokens readable, an unknown key raises `IntegrationKeyError`),
`RotateIntegrationKeyTests` (5: nothing to do, re-encrypt and idempotent, sources without a
credential left alone, an unreadable credential rolls everything back, no key is a
`CommandError`), `IntegrationKeyCheckTests` (3: silent unless forced on, warns without a key,
silent with one).

**`metering/test_supplementary_stats.py`** (20): `SelfConsumptionTests` (1) and
`GrossEnergyTests` (19): hand-computed rates, zero denominators, clamped self-sufficiency, no
source, a source that never ingested, 95 % coverage accepted, 90 % withheld, the minimum as a
setting, no rows is `no_data`, only the synced range is expected, window clipped to the personal
assignment, a later holder does not inherit the earlier holder's data, community assignments
excluded, back-to-back assignments merge, a gap stays a gap, a disconnected source still counts,
several flagged meters summed, timeline buckets, no timeline unless asked.

**`metering/test_supplementary_isolation.py`** (4): `SupplementaryIsolationTests` (2: no billing
module mentions supplementary data; the scanned file list covers the known modules) and
`InvoiceInvariantTests` (2: identical invoice amounts and items with and without supplementary
data, and ingest never touches `MeterReading`).

**`backups/test_supplementary_backup.py`** (8): `SupplementaryArchiveTests` (3: the
`supplementary` section holds the source before its readings, the credential travels as
ciphertext and the key never does, the manifest records key fingerprints only) and
`IntegrationKeyWarningTests` (5). `backups/fixtures.build_world` now includes a flagged meter
with a source and two readings, so every existing backup and restore round trip covers them.

### Backend — sources, push and CSV (PR 2: 70 tests)

**`metering/test_supplementary_api.py`** (41): `FeatureFlagTests` (1: everything is `404` while
the flag is off), `CreatePushSourceTests` (13: holder creates and gets the token once; consent
required; unflagged meter refused; one source per meter; a manager gets `403`; a participant who
does not hold it gets `400`; a community holder `403`; a stranger cannot even name the meter; an
admin creates on behalf of the holder and must name one who holds it; a push source takes no id or
key; a disabled ZEV refuses; the audit event never carries the token),
`CreateSolarManagerSourceTests` (7, against a fake provider: key verified and the rotated
credential stored encrypted; `503` naming the setting without a key; a rejected key and an
unreachable vendor save nothing; id and key required; an unregistered provider refused; the key
never reaches the audit log), `ReadScopingTests` (5: owner, manager, viewer and admin see it;
other participants, strangers and other ZEVs' managers do not; no secret is serialized; filter by
metering point), `UpdateAndRemoveTests` (14: owner edits and the diff is audited; a manager may only
switch it on or off; viewers and other participants cannot write; participant and provider are
immutable; disconnect wipes the token and keeps readings; purge all or by civil-date range and
rejects a backwards range; delete cascades; rotate is owner-only; a disabled ZEV is read-only;
replacing the key verifies it, resets the status and is audited; a new Solar Manager id needs the
key again) and `ClearingTheFlagTests` (1).

**`metering/test_supplementary_ingest.py`** (29): `PushIngestTests` (12: stored and coverage
advanced; redelivery updates; coverage never shrinks; four-decimal rounding; offsets to UTC;
eleven kinds of bad row rejected individually with their reasons; row limit; empty or malformed
body; tenancy clipping with the dropped count; community holders drop everything; `MeterReading`
untouched; no per-push audit), `PushAuthenticationTests` (9: no token `401`; wrong secret, prefix
and garbage are one message; rotation takes effect at once; disabled `403`; disconnected `401`; a
user session and a push token each cannot use the other's endpoints; flag off `404`; per-token
throttle) and `CsvImportTests` (8: valid and audited; semicolons, BOM and decimal commas;
`dry_run`; all-or-nothing; missing columns, empty and too many rows; not UTF-8; owner or admin
only; disabled source).

### Backend — Solar Manager, sync and reconciliation (PR 3: 122 tests)

All against a local stand-in for the vendor (`StubSolarManager` in `supplementary/testing.py`: a
real HTTP server that rotates refresh tokens, includes the boundary interval, and can be told to
answer `429`, 5xx, redirects, oversized or malformed bodies). The values are synthetic: no
household's real consumption profile is committed to the repository.

**`metering/test_supplementary_solar_manager.py`** (42): `ClientTests` (15: the refresh grant and
the rotated token; a vendor that does not rotate; a rejected or malformed key is an auth error
that never echoes the key; interval 900 and the bearer header; Wh to kWh with the interval start
kept; a malformed `smId` never reaches the network; `429` with, without and with an absurd
`Retry-After`; 5xx is transient; 403 and 404 are auth errors; redirects, oversized and garbage
bodies refused; an unreachable host gives a safe message), `MapPointsTests` (8: a row missing a
flow is a gap; null and non-numeric skipped; noise versus a real negative; out-of-window and junk
rows ignored; duplicates; `T_MARKS_INTERVAL`; offsets to UTC), `CivilDaysTests` (4: cut at Swiss
midnight; 92 and 100 interval DST days; partial and empty windows) and `ProviderTests` (15:
`verify` rotates and fails before any data request; the rotated key is persisted before data is
requested; the next fetch spends the new key; a save failure is a failed refresh and the bearer
token is never used; a non-rotating vendor leaves the ciphertext alone; one request per civil
day, lazily; the access token is renewed; an undecryptable or wiped credential asks for a
reconnect; `check`; registry).

**`metering/test_supplementary_sync.py`** (59): `SyncStorageTests` (13: first sync stores the
tenancy and marks the source ok; values in kWh; nothing before the tenancy or the backfill limit;
only complete intervals; a second sync re-fetches only the overlap; revised values are upserted;
`backfill`; each day stored before the next so a failure keeps the earlier days; vendor values
that fail validation are rejected without failing the sync; an empty run still succeeds; the
rotated key stored; `MeterReading` untouched), `SyncFailureTests` (8: a rejected or undecryptable
key is `reconnect_required` and not retried; transient failure sets `error` and retries; `429`
waits at least its `Retry-After`; a concurrent disconnect is never overwritten and stops the run),
`SyncSkipTests` (8: flag off, disabled, `reconnect_required`, push, deleted, busy lease, no
tenancy, community mode), `FanOutTests` (4), `OrphanTests` (5: tenancy ended, current, future end,
community mode, flag off), `SyncAuditTests` (5: no token in the audit; failure outcome; a broken
audit write or reconciliation does not fail a sync; the result is stored), `ActionTests` (11:
`test` and `sync` roles, cooldown, refusals for push, disconnected and `reconnect_required`;
`reconciliation` visibility; flag off) and `QueueOnWriteTests` (5: backfill after create, none for
push, new key, re-enable, broker outage).

**`metering/test_supplementary_reconcile.py`** (17): `ReconcileTests` (15: matching series are ok;
deviation above and below the tolerance, and the tolerance as a setting; a shift of +1 and of -2
intervals is detected; fewer than two comparable days, no official data and no source data are
`insufficient`; a half-empty day is skipped; the newest days win; the lookback; the per-day view;
nothing is modified; zero totals) and `StoreTests` (2).

**`accounts/test_system_health.py`** (+4): the `supplementary` probe is `unknown` with the flag
off, `degraded` without a key, reports counts and the oldest success, and flags a source that has
stopped syncing but not one that needs a reconnect.

### Backend — surfaces (PR 4: 41 tests)

**`metering/test_supplementary_surfaces.py`** (37; a synthetic three-day profile with known rates,
75 % self-sufficiency and 25 % self-consumption): `WindowAndBucketTests` (3: civil-date window, open
window, and the bucket labels equal the dashboard's own across both DST changes for day, month and
hour), `ParticipantDashboardTests` (10: own figures and timeline; the dashboard's own numbers are
byte-identical with and without the source; the date range bounds the figures; a range before the
data is `null`; low coverage withholds the rates with the reason and still reports the energy; no
source is `null`; other participants never see the figures; a disconnected source keeps its
history; flag off; a tenancy that ended does not leak into the next holder's view),
`OwnerDashboardTests` (7: per-participant block without a timeline; selected participant with one;
no source is `null`; viewers and admins; flag off; the billing-shaped numbers are unchanged),
`AnnualReportTests` (4: the row gains `gross_energy` while the meter-based rate stays `null`;
coverage judged on the synced range; everything else unchanged; participants without a source),
`AnnualStatementTests` (9: covered months show the rate and others `—`; the year total follows its
own coverage and shows when the year is fully covered; the note in all four languages; the plain
note stays without enough data; no source; flag off; not net-metered; the catalog lists the new
key) and `MeteringPointStatusTests` (4: owner, manager, viewer and admin see it; another participant
does not; no source; flag off).

**`mcp_server/tests/test_tools.py`** (+4): gross figures per participant and in the selected
participant's totals, `null` without a source and while the feature is off. The existing exact-keys
test now lists the three new keys.

### Backend — operations

`backups/test_registry.py` coverage passes with the new section; `test_archive`/restore round-trip
of sources and readings; manifest fingerprint; restore warns on a missing key.
`test_rotate_integration_key` idempotent. System check and health entry.

### Frontend (PR 5: 50 unit tests, 7 backend)

CI runs `npm run lint`, `npm run lint:style`, `node ../scripts/check-frontend-hex.mjs`,
`npm run test:unit` and `npm run build`.

- **`tests/supplementary-helpers.test.ts`** (10): `grossRate` never shows a withheld rate and keeps
  a real zero; the withheld reason keys; status tones; the push address for a relative and an
  absolute API base.
- **`tests/gross-energy-card.test.ts`** (9): both rates and the "reported by your own system" label;
  a dash and the reason for low coverage and no data while the energy is still shown; the
  participant's name for an owner; the call to action links to the tab; `NetMeteredRate` with a
  rate, without a source and withheld.
- **`tests/energy-data-section.test.ts`** (18): connect offered per meter; the modal's write-only
  key field, consent gate and consent text; the create payload; a vendor rejection next to the key
  field; a push source ends on a one-time token screen; the card per status (ok, reconnect required,
  disconnected, push); test, sync (cooldown), replace key, disconnect, delete data, remove and
  rotate, the destructive ones behind a confirmation; CSV check, import and row errors.
- **`tests/supplementary-owner-status.test.ts`** (9): no chip without a source; the chip as a
  button with its tone; the panel shows status and comparison but no credential field; a manager
  can switch off, delete data and remove behind confirmations; a viewer has no actions; the
  participant table's rate cell with a rate, without one, withheld, and for a non-net-metered row.
- **`tests/account-tabs.test.ts`** (+4): the tab resolves only when available; four tabs for a
  participant with a flagged meter; Profile while the check runs; no extra tab without the feature.
- **Backend** `metering/test_supplementary_api.py::EligibleMeteringPointTests` (7): the holder gets
  their flagged meter and, once connected, the source id; nobody else gets anything, an admin
  included; unflagged, community and ended tenancies and a disabled ZEV are not offered; `404` while
  the flag is off; anonymous `401`.
- Dev stack (throwaway ZEV, removed afterwards): the tab, the dashboard card with figures checked
  by hand (53.4 % = 1 − 58.95 / 126.56), the owner chip and panel, the owner table cell and the
  selected-participant card, at 1280 px and 400 px. The 400 px check found the long meter id and the
  action buttons overflowing; fixed. The three user-guide screenshots (`24-energy-data-*`) were
  captured from that scenario with `npm run shot`; they are **not** part of
  `npm run screenshots`, because the demo seed has no net-metered participant.

### Acceptance criteria

- [x] A participant who personally holds a flagged metering point can connect Solar Manager with
      their own API key and explicit consent; a wrong key never leaves a stored source behind.
      (Verified against a stub vendor; not yet against the real one.)
- [ ] The same participant can instead create a push source, receive its token once, and deliver
      readings by push or CSV; the 2026-07-01 sample reproduces ~55 % self-sufficiency and ~14 %
      self-consumption. (Push and CSV are tested; the real sample is not committed, so its figures
      were checked once by hand and are not a test.)
- [x] Their dashboard, the owner dashboard, the annual report, the annual statement PDF and MCP
      show the gross figures labelled as reported by their own system, and show `—` with a reason
      where coverage is below 95 %.
- [x] Invoices, allocation and invoice PDFs are identical in every amount with and without
      supplementary data; no billing module imports the supplementary package.
- [x] A manager sees status and can disable, disconnect, purge and delete, but can neither
      create a source nor read or set a credential.
- [x] Ingestion stops, and the credential is wiped, when the participant no longer holds the
      metering point; the readings are kept.
- [x] A rotated Solar Manager token is persisted before use and concurrent syncs never reuse it.
- [x] Reconciliation flags a source whose export deviates from the meter by more than 10 % or
      whose timestamps look shifted.
- [x] Backups round-trip both models; a restore on an instance without the key warns, naming the
      key fingerprint, and the affected sources become `reconnect_required` at their first sync.
- [x] With the feature flag off the product behaves exactly as in 1.21.0.
- [x] All user-facing text is translated in de/fr/it/en; the user guide is updated.

## 10. Implementation plan

Six PRs, in order, each independently green on `ruff check .`, `manage.py check`, `pytest -q`,
and for frontend work the lint/test/build set. Each updates this spec's status and test counts.

**Phase 0: Verify before building. Done 2026-10-08.** The timestamp convention was checked
against real meter data for the metering point behind the sample response (§6.2): `t` marks the
interval start, shift 0, day totals within 0.05 % (export) and 0.4 % (import). Still unmeasured,
and to be observed during PR 3: rate limits and the maximum `from`/`to` range per call.

**PR 1: Foundation** (backend, no user-visible change; implemented, see the test list in §9)
- Models and migrations (`SupplementarySource`, `SupplementaryReading`), constraints, the
  `has_behind_meter_generation` guard.
- `FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED`; settings (§4.5); `INTEGRATION_ENCRYPTION_KEYS`
  in `.env.example`, `.env.production.example`, Helm values.
- `metering/supplementary/crypto.py`, `rotate_integration_key`, system check.
- `metering/supplementary/stats.py`: `gross_energy`, coverage, assignment clipping.
- Backup registry section and manifest fingerprint; `SupplementaryIsolationTests`.
- Tests: `SupplementaryModelTests`, `GrossEnergyMathTests`, `SupplementaryIsolationTests`.

**PR 2: Sources, push and CSV** (backend; implemented, see the test list in §9)
- Permissions, serializers, the source viewset and the actions of §5 that need no provider
  (create, edit, delete, disconnect, purge, rotate token, CSV import), audit events. `test`, `sync`
  and `reconciliation` come with the provider in PR 3.
- `SupplementaryPushAuthentication`, `ozs_` tokens (a namespace parameter on
  `accounts.api_keys.generate_key` and `split_key`), the per-token throttle, and the shared ingest
  and CSV validation in `metering/supplementary/ingest.py`.
- A provider registry (`metering/supplementary/providers.py`), empty until PR 3 registers
  Solar Manager, so a half-built integration cannot be connected.
- Tests: `test_supplementary_api.py`, `test_supplementary_ingest.py`.

**PR 3: Solar Manager and reconciliation** (backend, async; implemented, see the test list in §9)
- `providers.py`, `solar_manager.py`, the sync tasks, orphan job, beat entries, create-time
  key check, `test` and `sync` actions.
- `reconcile.py`, system-health probe (the panel UI comes with the frontend).
- Tests: `test_supplementary_solar_manager.py`, `test_supplementary_sync.py`,
  `test_supplementary_reconcile.py`, against a stub vendor server with synthetic values shaped like
  the real response (all the fields, the boundary interval included). No household's real
  consumption profile is committed to the repository.

**PR 4: Statistics surfaces** (backend; implemented, see the test list in §9)
- `gross_energy` on the participant and owner dashboards, annual report, annual statement
  (context, template, translations, field catalog) and MCP; `supplementary_source_status` on the
  metering point.
- Tests: surface tests; flag-off parity with 1.21.0. The TypeScript types for the new payload
  fields land with it (`GrossEnergy`, the dashboard, annual report and metering point fields, and
  the catalog description in four languages); the UI that renders them is PR 5.

**PR 5: Frontend and docs** (implemented, see the test list in §9)
- Types, API client, query keys, Account tab, modal, owner status panel, gross card, rate
  cells, `AnnualReportSection`, i18n in four languages.
- User guide chapter (connect Solar Manager; the Home Assistant push recipe; what the numbers
  mean; privacy), screenshots regenerated, baseline specs updated (§11).

**PR 6: Transfer archive and hardening** (implemented, see §9)
- Transfer archive format 7: the opt-in `supplementary_data` section. Sources travel by `meter_id` and
  archive `participant_id` without credential, push token, `reconciliation` or any live state, and
  are imported **disconnected** (`enabled = false`, which the model shows as `disabled`; a status of
  `reconnect_required` would not survive `SupplementarySource.save()`, and "disconnected" is what the
  participant sees and fixes anyway). Readings travel as one CSV per source. The `SchemaParityTests`
  entry for `SUPPLEMENTARY_SOURCE_FIELDS` lists what is excluded and why. Older archives import
  without it. It is opt-in everywhere (backend default, UI default) because it is raw household data
  that managers otherwise see only as statistics.
- Hardening found while doing it: a source in a **disabled ZEV** no longer accepts pushes (`403 "This
  ZEV is disabled."`), is skipped by the sync (`zev_disabled`) and is not queued by the fan-out.
- ADRs 0030 and 0031 accepted, the spec marked implemented, `AGENTS.md` lists it.
- **Not done, on purpose:** the feature flag still ships off; the demo seed has no net-metered
  participant (so the guide screenshots are not part of `npm run screenshots`); the reconciliation
  day-by-day view has an API client function but no screen; there is no automatic retention (§12);
  the Solar Manager rate limit and maximum range per call are still unmeasured, and the client has
  never talked to the real vendor in a test run.

## 11. Documentation to update

Done in PR 5, except the transfer archive (PR 6) and the `AGENTS.md` entry, which waits until the
feature has shipped.

- Baseline `2026-03-metering-point-management.md`: the `has_behind_meter_generation` guard and
  `supplementary_source_status`.
- `2026-03-metering-import-and-quality.md`: the dashboard payloads' `gross_energy` blocks.
- `2026-09-annual-zev-report.md`: the participant row's `gross_energy`, TS types, tests.
- Annual statement documentation (`2026-03-invoice-lifecycle-and-communication.md`): the new
  context key and note.
- `2026-09-mcp-server.md`: `consumption_summary` shape.
- `2026-09-backup-and-restore.md`: the new section, manifest fingerprint, restore behaviour.
- `2026-08-zev-transfer-archive.md`: the new sections and exclusions (PR 6).
- `2026-09-behind-the-meter-generation.md`: replace the "possible follow-up" line with a link
  to this spec.
- `AGENTS.md`: add this spec to the completed-feature-spec list once shipped.
- User guide: the metering-point, account, energy-balance and reports chapters; a new "Connect
  your own energy data" page.

## 12. Open decisions

Defaults are what this spec implements; each can be changed before PR 2 without reshaping the
model.

1. **Can a ZEV owner connect a source for a participant?** Default **no**: the account is the
   participant's, so the credential stays theirs. An owner can disable, disconnect and delete.
   Revisit if participants without an account (no `Participant.user`) are common.
2. **Notify the participant when a source needs reconnecting?** Default **status banner only**
   in v1. An email on `reconnect_required` is a small follow-up using the existing email
   infrastructure.
3. **Resolution to keep.** Default **15 minutes**, matching the official data and the existing
   hourly-profile charts. Storing only daily aggregates would reduce sensitivity but would drop
   the profile charts.
4. **Automatic retention.** Default **none** beyond the explicit purge/delete actions and the
   disconnect-at-assignment-end rule. A retention window can be added as an `AppSettings` field.
5. **Batteries and EVs.** Default **out**; the rates are battery-agnostic because they use
   import/export. Add `battery_charge_kwh` / `battery_discharge_kwh` only if a chart needs them.
6. **A second source per metering point** (e.g. Solar Manager and a Home Assistant push).
   Default **one**; the one-to-one can become a foreign key with a priority later.
7. **Home Assistant pull.** Default **not built**; revisit for self-hosted deployments where HA
   is reachable from the server.

## 13. Follow-up: a manager's own figures (after PR 6)

`own_gross_energy` on the owner dashboard (7 backend tests, `OwnBlockTests`) and the permanent
"Your own system" block in `ManagementDashboardBody`, with the "You" marker and the call to action;
the "Per participant" table now clears its selection on a second click and exposes it as
`aria-pressed` (`tests/dashboard-behavior.test.ts`, 8 tests). `GrossEnergyCard` uses `useId` for its
heading, because two of them can be on one page.
