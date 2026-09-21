# Feature Spec: Metering import and data quality

- Spec ID: SPEC-2026-metering-import-quality
- Status: Approved
- Scope: Major
- Type: Feature
- Owners: Core maintainers
- Created: 2026-03-24
- Target Release: Ongoing baseline
- Related Issues: n/a (baseline)
- Related ADRs: 0005, 0007
- Impacted Areas: backend, frontend, async jobs

## 1. Problem and outcome

Metering data quality determines billing correctness.  Operators need safe
imports, transparent validation, and actionable quality visibility.

**Outcome:** a reliable import pipeline with preview-first validation,
configurable column mapping, two format profiles, two file format importers
(CSV/Excel and SDAT-CH), role-scoped analytics endpoints, and per-metering-point
data quality monitoring.  This spec is sufficient to re-implement the metering
import and quality features from scratch.

---

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Data model | `MeterReading`, `ImportLog`, reading directions, resolutions, import sources |
| CSV/Excel import | Standard (one row per reading) and daily 15-min profile formats |
| SDAT-CH import | Swiss ebIX XML metering data format |
| Preview workflow | Dry-run import that validates mapping and reports meter accessibility |
| Write modes | Skip-existing (default), overwrite-existing (explicit opt-in) |
| Import audit log | Per-import log with counts, errors, batch tracking |
| Chart data | Per-metering-point aggregated energy pivoted by direction |
| Raw data | Per-metering-point daily-grouped individual readings |
| Dashboard summary | Role-aware ZEV/participant energy analytics with local/grid split |
| Data quality | Per-metering-point gap detection with severity thresholds |

### Out of scope

- Real-time streaming metering ingestion
- Utility-specific protocols beyond CSV/Excel and SDAT-CH
- Metering point and assignment management — see `SPEC-2026-metering-point-management`

---

## 3. Data model reference

### 3.1 MeterReading

| Field | Type | Description |
|---|---|---|
| `id` | `UUIDField` (PK) | Auto-generated |
| `metering_point` | FK → `MeteringPoint` (`CASCADE`) | Source meter |
| `timestamp` | `DateTimeField` | Start of measurement interval (UTC) |
| `energy_kwh` | `Decimal(12,4)` | Energy value in kWh |
| `direction` | `ReadingDirection` | `in` (consumption) or `out` (production/feed-in) |
| `resolution` | `ReadingResolution` | `15min`, `hourly`, or `daily` |
| `import_source` | `ImportSource` | `csv`, `sdatch`, or `manual` |
| `import_batch` | `UUIDField` (nullable) | Groups readings from the same import |
| `created_at` | `DateTimeField` (auto) | Creation timestamp |

Ordering: `["metering_point", "timestamp"]`.

**Database constraints:**

| Constraint | Fields | Effect |
|---|---|---|
| `unique_reading_per_point_time_direction` | `metering_point`, `timestamp`, `direction` | Prevents duplicate readings |

### 3.2 Enumerations

**ReadingDirection:**

| Value | Label |
|---|---|
| `in` | Consumption (IN) |
| `out` | Production / Feed-in (OUT) |

**ReadingResolution:**

| Value | Label |
|---|---|
| `15min` | 15 minutes |
| `hourly` | Hourly |
| `daily` | Daily |

**ImportSource:**

| Value | Label |
|---|---|
| `csv` | CSV Upload |
| `sdatch` | SDAT-CH (ebIX XML) |
| `manual` | Manual entry |

### 3.3 ImportLog

| Field | Type | Description |
|---|---|---|
| `id` | `UUIDField` (PK) | Auto-generated |
| `batch_id` | `UUIDField` | Groups this log with its readings |
| `zev` | FK → `Zev` (`CASCADE`, nullable in DB for legacy rows) | Required target ZEV for every current import (CSV/SDAT-CH assign `zev` at creation; `null` only for pre-migration rows) |
| `imported_by` | FK → `User` (`SET_NULL`, nullable) | User who triggered the import |
| `source` | `ImportSource` | `csv` or `sdatch` |
| `filename` | `CharField(255)` | Original upload filename |
| `rows_total` | `IntegerField` | Total rows in file |
| `rows_imported` | `IntegerField` | Successfully imported count |
| `rows_overwritten` | `PositiveIntegerField` (default `0`) | CSV writes that replaced an existing reading (also included in `rows_imported`); nonzero protects the import from deletion |
| `rows_skipped` | `IntegerField` | Skipped/duplicate count |
| `errors` | `JSONField` (default `[]`) | Array of error objects: CSV uses `{row, meter_id?, error}` (`meter_id` attached whenever the row names a meter), SDAT-CH uses `{meter_id?, error}` or `{error}` |
| `warnings` | `JSONField` (default `[]`) | Informational notes, never failures: CSV overwrite reports `{row: null, warning: "Overwrote N existing readings."}` here so success toasts stay success |
| `created_at` | `DateTimeField` (auto) | Import timestamp |

Ordering: `["-created_at", "id"]` (matches `metering/models.py:ImportLog.Meta.ordering`).

**ZEV assignment:** CSV import and preview require `zev_id`. `log.zev` is
the validated target at creation (not inferred). `backend/metering/views.py:
_resolve_import_target_zev` rejects missing (400), malformed UUID (400),
unknown ZEV (404), or foreign-owned ZEV (403, non-admin) before parsing.
The resolver returns the ZEV object even on 403 so denied preview/upload
audits keep `target`/`target_id`/`zev` attribution with a DENIED status.
Cross-ZEV meters are per-row "not found or not accessible" errors.

---

## 4. Import pipeline

### 4.1 CSV / Excel importer

**Supported file types:** `.csv` (stdlib `csv`), `.xlsx` (`openpyxl`). Legacy `.xls`
is rejected with an explicit error asking for `.xlsx` or CSV.

**Format profiles:**

| Profile | Row layout | Required columns |
|---|---|---|
| `standard` | One reading per row | `meter_id`, `timestamp`, `energy_kwh`, optional `direction` |
| `daily_15min` | One day per row, 96 interval values | `meter_id`, `timestamp` (date), columns starting at `energy_start` position |

**Configuration parameters:**

| Parameter | Default | Description |
|---|---|---|
| `column_map` | `{}` | Overrides for column name/index mapping; keys sent as `col_{name}` form fields |
| `has_header` | `true` | Whether file has a header row |
| `delimiter` | `,` | Column separator for CSV |
| `format_profile` | `standard` | `standard` or `daily_15min` |
| `timestamp_format` | auto-detect | Python `strftime` format string |
| `interval_minutes` | `15` | Interval duration for `daily_15min` profile |
| `values_count` | `96` | Number of interval columns per row in `daily_15min` profile |
| `overwrite_existing` | `false` | Replace existing readings vs skip duplicates |

**Default column map:**

```python
{
    "meter_id": "meter_id",
    "timestamp": "timestamp",
    "energy_kwh": "energy_kwh",
    "direction": "direction",
    "energy_start": "4",       # column index for daily_15min profile
}
```

**Column resolution:** columns are resolved by name first; if the reference is
a numeric string, it is used as a zero-based column index.  Out-of-range
indices raise a column error that terminates the import with all rows skipped.
Internally a reference resolves to a column *position*, so named columns and the
positional `daily_15min` interval slots are read the same way.

**Parsing semantics:**

| Aspect | Behaviour |
|---|---|
| Encoding | UTF-8, BOM tolerated (`utf-8-sig`). Anything else is rejected with a 400 asking for a UTF-8 re-export |
| Delimiter | Exactly one character. `\t` may be written as the two-character escape, since the UI field is free text. Multi-character delimiters are rejected with a 400 |
| Blank lines | CSV blank lines are skipped and do **not** consume a row number |
| Excel blank rows | Trailing all-empty rows are dropped; mid-file blank rows are kept and reported as rows with a missing `meter_id` |
| Excel sheet | The first sheet is read, regardless of which sheet was active when the workbook was saved |
| Ragged rows | Short rows are padded; extra trailing fields are ignored |
| Missing values | An absent cell reports "Missing …"; a whitespace-only cell reports "Empty …" |
| Numbers | Comma decimal separators are accepted. Non-finite values (`nan`, `inf`) are rejected. Unparseable numbers report `Invalid numeric value '<input>'` rather than leaking `decimal` conversion codes. Magnitudes above `99999999.9999` kWh (the `DecimalField(max_digits=12, decimal_places=4)` bound) are rejected with an actionable error in both preview and import, so no `DataError` can escape the import transaction on PostgreSQL |
| Timestamps | `timestamp_format` (a `strptime` string) wins if supplied and is interpreted as UTC: a parsed offset is converted to UTC (`astimezone`), never discarded — except native Excel datetime cells, which are used as-is (assumed UTC when naive, converted when aware). Otherwise ISO-8601 is parsed first, falling back to a lenient parser; naive values are assumed UTC. For `daily_15min`, non-ISO dates are parsed day-first to suit European exports |
| Truncated daily rows | Missing interval columns or an invalid slot value reject the whole row atomically (one error, one `rows_skipped`, zero `rows_imported`); preview shares `_parse_daily_values` so both report the identical message. A row with no interval values at all is skipped with a "no interval values" error in both paths |
| Daily duplicates / gap-fill | Without overwrite, existing slots are skipped per slot and missing slots imported: a partially duplicate row imports its new slots with no row error; a fully duplicate row (all slots in DB or earlier in the file) is skipped with one `Duplicate reading` error. Preview sets `existing_data` for partial and full duplicates without returning blocking errors. Fully existing daily rows increment `summary.rows_skipped_existing` (including intra-file duplicates tracked by the written-set); the wizard shows a localized skip notice and permits merge re-imports. With overwrite, all slots upsert and the skip count is zero while `existing_data` remains set |
| Standard duplicates | Standard rows are interpreted by the shared `_interpret_standard_row` helper, so preview and import validate timestamps, values and directions identically. Preview prefetches existing `(metering_point, timestamp, direction)` pairs with chunked exact-timestamp queries (no range scan) and sets `existing_data` for rows matching the database or an earlier row in the same file; duplicates without overwrite increment `summary.rows_skipped_existing` without blocking errors, mirroring the daily contract. `summary.readings_existing` counts exact matching reading keys across the whole file — one per duplicate standard row, one per duplicate daily slot, including repeated writes within the file (validation failures excluded; data may change before execution) — and feeds the overwrite confirmation count |

Unreadable files (wrong format, bad encoding, invalid delimiter) return **400**
before any `ImportLog` row is created, so a failed read leaves no orphan log.

**Direction inference logic:**

```python
def _infer_direction_and_energy(meter_type, energy, explicit_direction=None):
    if explicit_direction in {"in", "out"}:
        return explicit_direction, abs(energy)
    if meter_type == "production":
        return "out", abs(energy)
    if meter_type == "bidirectional":
        return ("in" if energy >= 0 else "out"), abs(energy)
    return "in", abs(energy)       # consumption default
```

**Decimal parsing:** values are parsed via `Decimal`, with comma → dot
substitution, quantized to 4 decimal places.

**Timestamp handling:**
- Explicit `timestamp_format` → `strptime` + UTC. A parsed offset is converted to UTC (`astimezone`); naive results are stamped UTC. The format must contain `%` and capture the full calendar date: year-less formats (e.g. `%d.%m`) are rejected up front, otherwise data would silently land in 1900; day-of-year (`%Y-%j`) and week-based (`%U`/`%W`/`%V`) patterns count as month+day. The frontend `isValidTimestampFormat` mirrors this (year + (month+day | `%j` | week)). The validation probe is timezone-aware so offset-bearing formats (`%z`/`%Z`) round-trip. Unparseable timestamps report `Invalid timestamp value '<input>'` (standard) / `Invalid date value '<input>'` (daily), never dateutil internals.
- Timezone-aware timestamps → normalized to UTC.
- Naive timestamps → assume UTC.
- `daily_15min` profile → the declared calendar day wins: parse the date's
  year/month/day and anchor it at midnight UTC, then offset each slot by
  `interval_minutes × slot_index` (an offset-bearing value does not shift the
  billing day).

**Write modes:**

| Mode | Behavior | DB operation |
|---|---|---|
| Default (skip) | Skip if `(metering_point, timestamp, direction)` already exists | Standard: `get_or_create`; daily: per-day `create` inside `transaction.atomic()` |
| Overwrite | Update existing reading's energy value in place | `update_or_create` |

Duplicate detection for `daily_15min` batches the day's existing `(metering_point, timestamp, direction)` pairs into one range query per contiguous block of file days (so sparse files do not query the full earliest-to-latest span), then checks in memory; slots written earlier in the same file are tracked in a written-set so intra-file duplicates report the same slot-level error. Standard rows batch existing pairs with chunked exact-timestamp `__in` queries (500 per chunk, below SQLite/PostgreSQL parameter limits) and intersect in memory. Preview uses the same `_prefetch_daily_existing` source (no earliest→latest range scan) and the same `_parse_daily_values` validator, so empty rows, missing columns and invalid numerics agree; its `existing_data` flag is day-level (any reading that day with overlapping direction) while duplicate skip notices use exact slots. The write is atomic per row for validation failures: `imported` counts only committed slots (counted after the row savepoint succeeds, so a rolled-back row contributes zero). A concurrent duplicate used to roll back the row's savepoint and report one row-level duplicate error with no partial day; the write path now retries per slot after such a collision, so surviving slots commit and only a fully collided row reports the duplicate error. Absorbed late collisions are not counted in `rows_skipped` (the row succeeded). Overwrite reports as a `warnings` note: `"Overwrote N existing readings."` (never in `errors`, so the UI success path stays success).

**Meter visibility:** meters are scoped to role **and** the validated
target ZEV (`_meter_queryset_for_user(user, zev)`): `admin` → all meters in the
ZEV; `zev_owner` → that ZEV when owned (403 otherwise); `participant` → no
import access. A file with meters from multiple ZEVs imports only rows for
the target ZEV; preview uses the same ZEV-scoped lookup.

### 4.2 SDAT-CH (ebIX XML) importer

Parses the Swiss SDAT-CH MeteringData XML format delivered by VNBs.

**Required parameter:** `zev_id` (explicit ZEV selection in request body).

**Parsing logic:**
1. Parse XML via `lxml.etree`.  Malformed XML → log error and return.
2. Iterate `<MeteringPoint>` elements; extract `<MeteringPointID>` or `<ID>`.
3. Look up meter in the provided ZEV's metering points.  Unknown meters →
   error per meter, skip.
4. For each `<Interval>`: extract start timestamp and resolution.
5. Resolution mapping: `PT15M → 15`, `PT30M → 30`, `PT60M/PT1H → 60`;
   default `15` min.
6. For each `<Observation>`: extract `<Volume>`/`<Quantity>` and optional
   `<Direction>`/`<EnergyFlowDirection>`.
7. Direction: default `in`; `"OUT"` in direction text → `out`.
8. Timestamps: each observation offset = `start + resolution × observation_index`.
9. Write via `get_or_create` (skip existing; no overwrite mode).

**Permission:** ZEV owner must match `zev.owner == request.user` for non-admin.

### 4.3 Preview workflow

**Endpoint:** `POST /api/v1/metering/import/preview-csv/` — requires
`zev_id` (same validation as import, §3.3) and does not write data.

**Coverage:** missing-meter counts cover the whole file as unique meter IDs,
not rows in the first `max_rows` (display rows stay capped at 30).

**Row-level validation:** preview validates every data row before display:
missing/empty `meter_id`, missing/invalid timestamp (honoring
`timestamp_format`), missing/invalid `energy_kwh` (including comma decimals
and non-finite values), invalid `direction`, and for `daily_15min` missing/invalid
date, missing interval columns, and the first failing slot's energy error —
one error per daily row, mirroring import, so a single bad 96-slot row cannot
burn the whole error budget. Blank `meter_id`
cells are validation errors, not "missing meters." Fields are validated
whether or not the meter exists — a file of unknown meters cannot hide
errors the import would surface. Once the error list reaches
`MAX_REPORTED_ERRORS`, row validation stops early (with the truncation
sentinel) but the whole-file meter-ID scan continues, so summary counts stay
exact. Errors are returned in `errors` and block `Start Import` in the
wizard. Preview `existing_data` for `daily_15min` is otherwise unchanged.

**Advisory contract:** preview is a UI aid, not a server-side gate. The wizard
requires a fresh, clean preview before import, but the upload endpoint accepts
direct uploads and runs the identical server-side validation — no preview
token is required or checked.

**Response shape:**

```json
{
  "rows_total": 100,
  "preview_rows": [
    {
      "row": 2,
      "meter_id": "CH-12345",
      "metering_point_exists": true,
      "meter_type": "consumption",
      "timestamp": "2026-01-01T00:00:00+00:00",
      "energy": "1.5000"
    }
  ],
  "summary": {
    "existing_metering_points": 8,
    "missing_metering_points": 2,
    "rows_previewed": 30,
    "rows_skipped_existing": 0
  },
  "missing_meter_ids": ["CH-MISSING-1", "CH-MISSING-2"],
  "errors": []
}
```

- `missing_meter_ids` is the sorted distinct missing set, capped at 50
  (truncated with +N). A meter appearing 30× counts as 1.

For `daily_15min` profile, each preview row includes `interval_minutes` and
`values_count` instead of `energy`. `existing_data` is direction-aware and
uses one range query per contiguous block of file days: it flags any stored
reading on the row's UTC day with a direction that row would import. It also
flags exact duplicate slots earlier in the file. The flag remains visible in
overwrite mode. In skip mode, fully duplicate daily rows contribute to
`summary.rows_skipped_existing` instead of blocking errors. This count covers
validated rows (validation stops at the error cap); it is zero for standard
profiles, overwrite mode, and invalid configuration. New days in the same file
remain importable without overwrite. Upload still records skipped fully
duplicate rows in the import protocol; the preview notice is advisory.

### 4.4 Hardening and limits (C+ — 2026-08)

All import paths enforce app-level and nginx-level limits; the parser is pinned to prevent version drift.

**Nginx body limits:**
- Global `client_max_body_size 10m` (`docker/fullstack-nginx.conf`, `frontend/nginx.conf`).
- Per-location `50m` on `/api/v1/metering/import/` (CSV/SDAT) and `/api/v1/zev/zevs/(import|inspect)-archive` (transfer) — the paths include the `/api/v1/` prefix the Django router mounts. The Helm chart sets `nginx.ingress.kubernetes.io/proxy-body-size: "50m"` on the ingress (ingress-nginx defaults to 1m, which would block even small uploads).
- `error_page 413` returns JSON `{"detail":"File too large."}` rather than HTML.

**SDAT-CH XML parser (pinned):**
```python
parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)
tree = etree.parse(file, parser)
```
On lxml 6.1.1 the default is `resolve_entities='internal'` with a libxml2 amplification ceiling (~100x, `huge_tree=False`), so Billion Laughs does not reach GB-scale — explicit flags pin behaviour against future `huge_tree=True` drift. See `backend/metering/importers/sdatch_importer.py`. An oversized SDAT file is reported as an ImportLog error (HTTP 201) — the SDAT importer always reports through its log — unlike CSV, whose oversize files return HTTP 400.

**CSV / Excel streaming and caps (`backend/metering/importers/csv_importer.py`):**
- `MAX_CSV_BYTES 50 MB` enforced via the upload's `size` attribute (nginx rejects oversized bodies earlier with 413); `MAX_XLSX_DECOMPRESSED_BYTES 50 MB`, `MAX_CSV_ROWS 200k` (env `IMPORT_MAX_ROWS`, `backend/config/settings.py`), `MAX_CSV_COLUMNS 1500`. The row cap counts data rows — a header row does not consume it. Headroom by profile: `standard` (one reading per row) is the tight case at ~5.7 meter-years of 15-minute data (35,040 rows/meter-year); `daily_15min` (one row per meter-day) has ~548 meter-years of headroom. Raise `IMPORT_MAX_ROWS` for larger standard-profile exports.
- `MAX_XLSX_MEMBERS 200`, `MAX_XLSX_RATIO 500:1` (XLSX is a ZIP; `openpyxl` with `read_only=True` still materializes shared strings, so the ZIP is validated before inflation). The ratio is a heuristic, deliberately loose: legitimate sparse sheets compress far beyond 100:1, and the decompressed-size sum is the hard bound. Sheet row caps are enforced *during* iteration and the column cap on *every* row, so an oversized sheet is rejected before it is materialized and a wide row cannot hide behind a narrow first row.
- `MAX_VALUES_COUNT 1440` (values per `daily_15min` row) — prevents CPU bomb via `values_count=100000`; both `preview_csv` and `import_csv` validate `1..1440` through `_coerce_values_count`, and `interval_minutes >= 1` through `_coerce_interval_minutes`. Validation is single-layer: the coercers raise `ImportFileError` on non-integer input (no silent defaults), which the views map to a 400.
- Streaming via `TextIOWrapper` over the uploaded file (`detach()` in a `finally` keeps the underlying upload readable on error paths); `file.read().decode` whole-file buffering removed.
- `MAX_REPORTED_ERRORS 50` (shared across importers from `backend/metering/importers/limits.py`) — further per-row errors are truncated with a sentinel error. SDAT-CH reuses the same `add_error` helper, capping during the parse loop. The overwrite note lives in `warnings`, never in `errors`, so it cannot push the error list past its cap.

**Shared limits module (`backend/metering/importers/limits.py`):**
- `MAX_UPLOAD_BYTES 50 MB` (aliased as `MAX_CSV_BYTES`, `MAX_SDAT_BYTES`, `MAX_TRANSFER_COMPRESSED_BYTES`), `MAX_REPORTED_ERRORS 50`, the `mb()` formatter, `add_error()`, and `validate_zip()` — one ZIP validator (member count, declared decompressed sum, ratio with a 1 MB decompressed floor) used by both `_read_xlsx_table` and `open_archive`, parameterized by limits and error class. `reject_unsafe_member_path()` rejects absolute paths, `..` traversal on `/`- or `\`-separated paths, and Windows drive letters.

**Transfer archive ZIP caps (`backend/zev/transfer/importer.py:open_archive`):**
- `MAX_TRANSFER_COMPRESSED_BYTES 50 MB`, `MAX_TRANSFER_DECOMPRESSED_BYTES 500 MB` (env `TRANSFER_MAX_DECOMPRESSED_MB`, `backend/config/settings.py`), `MAX_TRANSFER_MEMBERS 500`, `MAX_TRANSFER_RATIO 500:1`.
- The decompressed cap is derived from the archive scale the feature documents: 2M readings ≈ 150 MB of CSV (`docs/specs/2026-08-zev-transfer-archive.md`). Decompressed members are streamed, never materialised, so the cap is a trust bound rather than a memory bound; a guard test (`zev/test_transfer_limits.py:TransferArchiveLimitTests`) fails if it is lowered below that scale. The compressed cap pairs with nginx's 50m location and is not tunable.
- Checked inside `open_archive`, which validates the opened `ZipFile` through the shared `validate_zip` before returning it (no second open); unsafe member paths (traversal, absolute, drive letters) are rejected.

**Throttling (worker exhaustion, not just OOM):**
- `backend/accounts/throttling.py:ImportThrottle` (`UserRateThrottle` subclass, `60/hour` per-user) on `POST /import/csv`, `/import/sdatch`, `/import/preview-csv` (`backend/metering/views.py`); `backend/accounts/throttling.py:TransferArchiveThrottle` (`UserRateThrottle` subclass, `20/hour` per-user) on `POST /zev/zevs/import-archive` and `inspect-archive` (`backend/zev/views.py`).
- Both views list `ApiKeyRateThrottle` alongside their specific throttle: view-level `throttle_classes` *replace* `DEFAULT_THROTTLE_CLASSES`, so without it key-authenticated requests would stop counting against the API-key budget. These endpoints are authenticated (DRF checks permissions before throttles), so per-user keying always applies.
- Rates in `backend/config/settings.py` (`REST_FRAMEWORK.DEFAULT_THROTTLE_RATES`) with env overrides `IMPORT_THROTTLE_RATE`, `TRANSFER_IMPORT_THROTTLE_RATE`; disabled in tests (`backend/config/settings_test.py` → `None`). The env-tunable volume caps (`IMPORT_MAX_ROWS`, `TRANSFER_MAX_DECOMPRESSED_MB`) are pinned to their defaults there.
- Rationale: sync gunicorn workers tie up on parse duration even for legal-sized files; size caps alone do not bound concurrency.

**Frontend error shapes:** the import UI reads `error` (app 400s) with `detail` as a fallback — the proxy's 413 body (`{"detail":"File too large."}`) — and treats a 201 whose log has `rows_imported == 0` with errors as a failure (the SDAT-CH oversize path reports through its log).

---

## 5. API endpoints

All metering endpoints are routed under `/api/v1/metering/` via DRF routers.

### 5.1 Readings CRUD

| Method | URL | Permission | Description |
|---|---|---|---|
| `GET` | `/readings/` | `IsAuthenticated`, `IsZevOwnerOrAdmin` | List readings (role-scoped) |
| `POST` | `/readings/` | `IsZevOwnerOrAdmin` | Create single reading |
| `GET` | `/readings/{id}/` | `IsZevOwnerOrAdmin` | Retrieve single reading |
| `PUT/PATCH` | `/readings/{id}/` | `IsZevOwnerOrAdmin` | Update reading |
| `DELETE` | `/readings/{id}/` | `IsZevOwnerOrAdmin` | Delete reading |

### 5.2 Chart data

| Method | URL | Permission | Query params |
|---|---|---|---|
| `GET` | `/readings/chart-data/` | `IsAuthenticated` | `metering_point` (required), `date_from`, `date_to`, `bucket` |

**Bucket options:** `day` (default), `hour`, `month`.

**Response:** array of `{bucket, in_kwh, out_kwh}` objects, pivoted by
direction within each time bucket.

**Participant visibility:** filter each reading by an assignment belonging to
the caller that covers the reading's UTC civil date, before aggregation
(§6.1). Selecting a meter does not grant access to its previous or next
holder's readings, even when no date bounds are supplied.

**Date bounds:** explicit UTC start/end construction (via
`allocation.validity.period_window`) to avoid Django timezone conversion
artifacts (ADR 0007).

**Bucket boundaries:** `TruncHour`, `TruncDay`, and `TruncMonth` receive UTC
explicitly. Response bucket timestamps therefore use `+00:00`; daily and
monthly buckets cannot move across the filtered UTC date range, and the two
distinct UTC hours during a local DST fallback remain separate. Presentation
code may format those timestamps for the user's locale, but it must not change
the aggregation boundary (ADR 0007).

### 5.3 Raw data

| Method | URL | Permission | Query params |
|---|---|---|---|
| `GET` | `/readings/raw-data/` | `IsAuthenticated` | `metering_point` (required), `date_from`, `date_to` |

Both the daily summary and single-day detail (`date=YYYY-MM-DD`) apply the
assignment-date visibility rule in §6.1. Unauthorized readings are omitted;
a day with no visible readings returns an empty array with HTTP 200.

**Response:** array of daily-grouped objects:

```json
{
  "date": "2026-01-01",
  "in_kwh": 12.5,
  "out_kwh": 3.0,
  "readings_count": 96,
  "readings": [
    {
      "timestamp": "2026-01-01T00:00:00+00:00",
      "direction": "in",
      "energy_kwh": 0.125,
      "resolution": "15min",
      "import_source": "csv"
    }
  ]
}
```

### 5.4 Dashboard summary

| Method | URL | Permission | Query params |
|---|---|---|---|
| `GET` | `/readings/dashboard-summary/` | `IsAuthenticated` | `zev_id`, `participant_id`, `date_from`, `date_to`, `bucket` |

Returns role-differentiated response shapes:

**ZEV owner / admin response:**

```json
{
  "role": "zev_owner",
  "bucket": "day",
  "totals": {
    "produced_kwh": 500.0,
    "consumed_kwh": 800.0,
    "imported_kwh": 300.0,
    "exported_kwh": 0.0
  },
  "timeline": [{"bucket": "...", "consumed_kwh": ..., "produced_kwh": ..., "imported_kwh": ..., "exported_kwh": ...}],
  "participant_stats": [
    {
      "participant_id": "...",
      "participant_name": "Alice Muster",
      "total_consumed_kwh": 200.0,
      "total_produced_kwh": 0.0,
      "from_zev_kwh": 150.0,
      "from_grid_kwh": 50.0
    }
  ],
  "selected_participant_id": null,
  "selected_participant_name": null
}
```

When `participant_id` is provided, `totals` and `timeline` are narrowed to that
participant's readings and the response includes `selected_participant_name`.
The narrowed `totals.exported_kwh` is the participant's true grid export — the
surplus fed to the grid (`exported(t) = max(produced − consumed, 0)`, see
"ZEV-level aggregates" below) — not their total production. (Earlier revisions
reported total production here; corrected alongside the per-holder attribution
routing, ADR 0013.)

**Participant response:**

```json
{
  "role": "participant",
  "bucket": "day",
  "totals": {
    "consumed_from_zev_kwh": 150.0,
    "imported_from_grid_kwh": 50.0,
    "total_consumed_kwh": 200.0
  },
  "timeline": [{"bucket": "...", "consumed_from_zev_kwh": ..., "imported_from_grid_kwh": ..., "total_consumed_kwh": ...}]
}
```

**Local/grid energy split algorithm (timestamp-level):**

For each timestamp $t$:

0. Attribute the reading to the participant whose assignment is active on
   $t$'s UTC civil date (`ts.date()`, ADR 0013/0007 — timestamps are always
   UTC, so the UTC date is also the period and tariff day). Readings with no
   active assignment (gap readings) are excluded from per-participant totals
   and the timeline, but remain in the ZEV-level aggregates (§"ZEV-level
   aggregates" below).
1. $\text{local\_pool}(t) = \min(\text{total\_produced}(t),\; \text{total\_consumed}(t))$
2. If $\text{total\_consumed}(t) > 0$ and $\text{local\_pool}(t) > 0$:

$$\text{from\_zev}_i(t) = \text{local\_pool}(t) \times \frac{\text{consumed}_i(t)}{\text{total\_consumed}(t)}$$

3. $\text{from\_grid}_i(t) = \text{consumed}_i(t) - \text{from\_zev}_i(t)$

This is identical to the billing engine's proportional allocation but computed
at dashboard query time rather than per-billing-period. All arithmetic is
`Decimal` end to end (fail-fast on non-`Decimal`, negative, or inconsistent
totals — see the billing-engine spec §4.3); floats appear only at JSON
serialization (hourly profile values are rounded to 4 decimals).

**ZEV-level aggregates:**

For each timestamp $t$:
- $\text{imported}(t) = \max(\text{consumed}(t) - \text{produced}(t),\; 0)$
- $\text{exported}(t) = \max(\text{produced}(t) - \text{consumed}(t),\; 0)$

These are aggregated per bucket for the timeline. They are physical pool
totals over every reading in the range — gap readings are included here even
though no participant is charged for them.

**ZEV selection logic:**
- If `zev_id` provided → validate ownership for non-admin users.
- If omitted and user owns exactly 1 ZEV → auto-select.
- If omitted and user owns multiple ZEVs → return 400 requiring selection.

### 5.5 Data quality status

| Method | URL | Permission | Query params |
|---|---|---|---|
| `GET` | `/readings/data-quality-status/` | `IsAuthenticated` | `date_from` (default: 30 days ago), `date_to` (default: today), `zev_id` (optional) |

**Response:**

```json
{
  "date_from": "2026-01-01",
  "date_to": "2026-01-31",
  "metering_points": [
    {
      "id": "...",
      "meter_id": "CH-12345",
      "participant_name": "Alice Muster",
      "severity": "yellow",
      "data_completeness": 85,
      "days_with_data": 26,
      "total_days": 31,
      "gaps": [
        {
          "start_date": "2026-01-15",
          "end_date": "2026-01-17",
          "duration_days": 3
        }
      ],
      "unassigned_days": 0,
      "unassigned_readings": 0,
      "assignment_overlap": false
    }
  ]
}
```

**Gap detection algorithm:**

1. Enumerate all calendar days in `[date_from, date_to]`.
2. Query readings for each metering point; extract unique days with data.
3. Compute `missing_days = all_days - days_with_data`.
4. Group consecutive missing days into gap spans with `start_date`, `end_date`,
   `duration_days`.
5. Compute `data_completeness = floor(100 × days_with_data / total_days)`.

**Severity thresholds:**

| Completeness | Severity |
|---|---|
| 100% | `green` |
| 50–99% | `yellow` |
| 0–49% | `red` |

`severity` reflects daily *completeness* only. Holder-less readings and
overlapping assignment windows are surfaced by the amber row warnings below,
not by the severity cell: a fully-complete meter with no holder is still
`green` on completeness while its warning says its readings are unbilled.

**Participant resolution:** the current participant assignment (active today)
is looked up for display (one batched query); meters with no current
assignment show `"Unassigned"`.

**Unassigned-holder detection:** a reading whose metering point has no
assignment active at the reading's UTC civil date is billed to nobody but
still inflates the ZEV pool (ADR 0013); that is always a misconfiguration,
not a valid state. Such readings are counted per metering point as
`unassigned_readings` plus the distinct `unassigned_days` they fall on, so
an operator can assign the meter (e.g. to an *Allgemein* / community
participant) or confirm the exclusion. Holders are resolved through the
shared `AssignmentWindows` with the same UTC-civil-date semantics as billing
(`AssignmentWindows.participant_on`), once per distinct day rather than once
per reading — assignment validity is date-granular, so day-level resolution
is exactly equivalent. `unassigned_readings` counts reading *rows*: a
bidirectional meter with `in` and `out` readings at one timestamp
contributes 2.

**Overlapping-window flagging:** `AssignmentWindows` fails fast on
overlapping windows (only possible via direct-DB edits once the model
`save()` guard rejects them). The status check catches that per metering
point, so one corrupt meter degrades to one flagged row
(`assignment_overlap: true`) while every other meter still reports — the
page never 400s wholesale. For a flagged meter, `unassigned_days` /
`unassigned_readings` are 0 (holders cannot be resolved); gap detection and
severity are unaffected.

**Frontend routes:** chart and quality are routes, not
query state — `/metering/chart` (all roles) and `/metering/quality`
(`admin`/`zev_owner`, same `MeteringChartPage` mounted with `tab`). Both
share the `ProtectedRoute` shell so tab switches don't remount the page
(period/resolution persist); legacy `/metering-data?tab=quality` redirects
to the guarded quality route with `tab` stripped. The quality query only
fires on the quality tab (`enabled: tab === 'quality'`) with
`zev_id` for managed roles.

**URL period state:** `MeteringChartPage` initialises its selected period
from canonical `?period_start` + `?period_end` parameters. Legacy metering
links using `?from` + `?to` remain readable when neither canonical key is
present; if either canonical key is present, that pair takes precedence and
the two formats are never mixed. Every selector change writes the canonical
pair back into the URL (`replace`) and removes the legacy keys. The URL is
authoritative for any calendar-valid, ordered range — cockpit/attention links
arrive as whole aligned periods, while user-picked custom ranges (including
dates not aligned to the billing interval) survive navigation and
metering-point changes verbatim. Only malformed input falls back: missing,
non-ISO, impossible dates (e.g. `2026-02-30`) or a reversed range reset to the
current period. The community's earliest billable period (see the
navigation-regroup spec §7 floor rule) disables the previous-period button at
the boundary, so a selection can never flash a pre-start period and jump away.

Import history is the third tab of the same hub —
`/metering/imports` renders `MeteringChartPage tab="imports"`, which
mounts `ImportsPage embedded` (header stripped, `PeriodSelector` hidden on
that tab); `admin`/`zev_owner` only. The standalone nav entry is gone; the
legacy `/imports` alias still redirects with its query preserved.

### 5.6 Import endpoints

| Method | URL | Permission | Description |
|---|---|---|---|
| `POST` | `/import/csv/` | `IsAuthenticated, IsZevOwnerOrAdmin` | CSV/Excel import (multipart form data) |
| `POST` | `/import/sdatch/` | `IsAuthenticated, IsZevOwnerOrAdmin` | SDAT-CH XML import (multipart, requires `zev_id`) |
| `POST` | `/import/preview-csv/` | `IsAuthenticated, IsZevOwnerOrAdmin` | CSV preview (no data write) |

All import endpoints use `MultiPartParser` and `FormParser`.

**CSV import form fields:**

| Field | Required | Description |
|---|---|---|
| `file` | Yes | Upload file |
| `zev_id` | **Yes** | Target ZEV UUID (validated before parsing; missing → 400, bad UUID → 400, unknown → 404, foreign-owned for non-admin → 403) |
| `col_meter_id` | No | Column name/index for meter_id |
| `col_timestamp` | No | Column name/index for timestamp |
| `col_energy_kwh` | No | Column name/index for energy |
| `col_direction` | No | Column name/index for direction |
| `col_energy_start` | No | Column name/index for first energy value (`daily_15min`) |
| `has_header` | No | `true`/`false` (default `true`) |
| `delimiter` | No | CSV separator (default `,`) |
| `format_profile` | No | `standard` or `daily_15min` |
| `timestamp_format` | No | Python strftime string |
| `interval_minutes` | No | Minutes per interval (default `15`) |
| `values_count` | No | Interval columns per row (default `96`) |
| `overwrite_existing` | No | `true`/`false` (default `false`) |

**CSV preview form fields:** same form fields as CSV import, including
the required `zev_id` and optional `overwrite_existing` (default `false`).
With overwrite enabled, daily duplicate rows remain valid; malformed values
and missing meters still block the wizard.

**SDAT-CH import form fields:**

| Field | Required | Description |
|---|---|---|
| `file` | Yes | Upload file |
| `zev_id` | Yes | Target ZEV UUID |

**Response:** `201` with `ImportLog` serialized as JSON.

### 5.7 Import logs

| Method | URL | Permission | Description |
|---|---|---|---|
| `GET` | `/import-logs/` | `IsAuthenticated, IsZevOwnerOrAdmin` | List import logs |
| `GET` | `/import-logs/{id}/` | `IsAuthenticated, IsZevOwnerOrAdmin` | Retrieve single import log |
| `DELETE` | `/import-logs/{id}/` | `IsAuthenticated, IsZevOwnerOrAdmin` | Delete a single import log and all readings in its `batch_id` |
| `POST` | `/import-logs/bulk-delete/` | `IsAuthenticated, IsZevOwnerOrAdmin` | Delete all visible import logs in a selected created-at period or delete all visible logs |

**Queryset scoping:**
- `admin` → all import logs.
- `zev_owner` → logs where `zev.owner == user` OR `imported_by == user`.

**Deletion semantics:**
- Imports with `rows_overwritten > 0` cannot be deleted. Both endpoints return **400** with `{code: "overwrite_import_protected", error: "Imports that overwrote readings cannot be deleted. No imports were deleted."}` when any selected log is protected. The entire bulk operation is rejected without deleting any log or reading; this is not a rollback API and previous values are not restored.
- CSV import runs in one transaction, publishing its readings and finalized overwrite count together. The successful log is created inside that transaction, so no half-finished import is ever visible or deletable. An unexpected failure rolls everything back and is then recorded as a separate failed-attempt log outside the transaction, before an `ImportFileError` propagates (400 with an actionable message, never an untraced 500). Deletion freezes the visible selection, locks its logs in primary-key order, checks protection, and deletes only that selection in one transaction.
- Migration `0005_importlog_rows_overwritten` backfills the count from exact `Overwrote N existing readings.` notes in both legacy `errors` and newer `warnings`; other logs keep zero. The field is exposed by the import-log serializer and represented by `ImportLog.rows_overwritten: number` in TypeScript. Counts include repeated writes within the same file, so those overwrite imports are conservatively protected too.
- The frontend disables the protected row's delete action, explains the policy in its protocol and bulk-delete dialog, and maps server rejections to the same localized message. The bulk dialog additionally lists the blocking protected imports (filename + creation time) and disables review/confirmation while any is in scope; the server stays authoritative. Correct a protected import by uploading corrected readings with overwrite enabled.
- `ImportLog` is read-only in Django admin (no add/change/delete): deletion, with its overwrite protection and batch cleanup, happens only through the application's protected workflow. Whole-ZEV deletion still removes the community's meters, readings and logs together.
- An unprotected single-log delete removes the selected `ImportLog` and all `MeterReading` rows with `import_batch == batch_id`.
- Bulk delete operates on the same scoped queryset as the list endpoint.
- Bulk delete accepts `mode = all | period`.
- `mode = period` requires `date_from` and `date_to` and filters with the half-open UTC range `[date_from 00:00Z, date_to + 1 day 00:00Z)` on `ImportLog.created_at`. History timestamps render in local time; the delete dialog labels the range as UTC so display, selection and deletion stay consistent.
- Bulk delete validates an optional `zev_id` as a UUID before filtering. Invalid calendar dates, non-string dates, reversed ranges, and `date_to=9999-12-31` return 400 rather than overflowing the exclusive end bound.
- History table filename/source filters are client-side only and never narrow bulk delete: the UI copy names the selected ZEV (or "all visible ZEVs" when none is selected), and the count uses the same half-open UTC instants as the backend.
- Delete responses return counts for both deleted logs and deleted readings; bulk deletion also returns `timezone: "UTC"`; the frontend invalidates both import-log and metering queries so charts/quality refresh.

---

## 6. Actors, permissions, and ZEV scope

### 6.1 Readings queryset scoping

| Role | Visible readings |
|---|---|
| `admin` | All readings |
| `zev_owner` | Readings for meters in `zev__owner = user` |
| `participant` | Readings with an assignment for the same meter whose `participant.user = user` and whose validity window contains the reading's UTC civil date |

`MeterReadingViewSet._scope_by_role()` delegates admin/owner scoping to
`ZevScopedQuerySetMixin`. For non-manager callers, it aliases `reading_day`
with `TruncDate("timestamp", tzinfo=UTC)` and filters using a correlated
`Exists` over `MeteringPointAssignment`: `metering_point_id` equals the outer
reading's meter, `participant__user` equals the caller, `valid_from <=
reading_day`, and `valid_to IS NULL OR valid_to >= reading_day`. All conditions
must match the same assignment. This avoids implicit Zurich date conversion
and avoids multiplying aggregate sums or reading counts when a holder has
multiple assignments to one meter.

Both assignment bounds are inclusive; a null end is open-ended. Readings
before/after the caller's windows and in assignment gaps are excluded.
Multiple noncontiguous windows authorize only their union, without granting
access to intervening holders. Assignment allocation mode does not change
holder access. The shared `scope_queryset()` still applies `?zev_id=` after
role scoping, so that filter can only narrow visibility. Readings CRUD remains
owner/admin-only; raw-data and chart-data retain their response shapes.

### 6.2 Permission summary

| Action | `admin` | `zev_owner` | `participant` |
|---|---|---|---|
| List/read readings (CRUD routes) | All | Own ZEV | No (403) |
| CRUD readings | Yes | Yes | No (403) |
| Chart data, raw data | Yes | Yes | Only readings within own assignment windows |
| Dashboard summary | Yes (with `zev_id`) | Yes (own ZEV) | Yes (own data, different response shape) |
| Data quality status | Yes | Yes | Yes (own meters) |
| CSV/SDAT-CH import | Yes | Yes | No (403) |
| Preview CSV | Yes | Yes | No (403) |
| List import logs | Yes | Own ZEV / own imports | No (403) |

---

## 7. Timezone policy

Per ADR 0007, all metering timestamps are stored and queried in UTC.

**Query boundary construction:** date parameters (`date_from`, `date_to`) are
converted to explicit UTC bounds via `allocation.validity`:

```python
start, end = period_window(date_from, date_to)
# Filter: timestamp >= start AND timestamp < end
```

A lone `date_from`/`date_to` still filters one-sided
(`period_start_dt`/`period_end_exclusive_dt`); both parameters are optional
wherever the endpoint documents them as such. This avoids Django's `__date`
lookup which applies `USE_TZ` / `TIME_ZONE` conversion and can
drop/duplicate readings near midnight boundaries.

**Import normalization:**
- Timezone-aware timestamps → converted to UTC.
- Naive timestamps → assumed UTC.
- SDAT-CH timestamps → ISO 8601 with `Z` or offset → parsed to UTC.

---

## 8. Serialization

### 8.1 MeterReadingSerializer

| Fields | Mode | Notes |
|---|---|---|
| All model fields | Read/write | `fields = "__all__"` |
| `id`, `created_at`, `import_batch` | Read-only | Auto-generated |

### 8.2 ImportLogSerializer

| Fields | Mode | Notes |
|---|---|---|
| All model fields | Read/write | `fields = "__all__"` |
| `id`, `created_at`, `batch_id` | Read-only | Auto-generated |
| `zev_name` | Read-only | `zev.name`, for history/protocol display |
| `imported_by_display` | Read-only | `get_full_name() or username or email`, for history/protocol display |

The list endpoint uses `select_related("zev", "imported_by")` so the display
fields cost no extra queries.

### 8.3 Frontend types

```typescript
interface ImportLog {
  id: string
  batch_id?: string
  zev?: string                   // always the validated target on import
  zev_name?: string | null       // display field from the serializer
  imported_by?: number | null
  imported_by_display?: string | null  // display field from the serializer
  filename: string
  rows_total?: number
  rows_imported: number
  rows_skipped: number
  source: string
  errors?: Array<{ row: number | null; error: string; meter_id?: string | null }>
  created_at: string
}

interface ImportPreviewRow {
  row: number
  meter_id: string | null
  metering_point_exists: boolean
  meter_type?: string | null
  timestamp?: string | null
  energy?: string | null
  existing_data?: boolean
  interval_minutes?: number
  values_count?: number
}

interface ImportPreviewResult {
  rows_total: number
  preview_rows: ImportPreviewRow[]
  summary: {
    existing_metering_points: number  // unique meters over the whole file that exist in the target ZEV
    missing_metering_points: number   // unique meters over the whole file that are missing in the target ZEV
    rows_previewed: number            // display-row cap (max_rows, currently 30)
  }
  missing_meter_ids: string[]         // sorted distinct missing IDs over the whole file, capped at 50
  errors: Array<{ row: number | null; error: string }>
}

interface ChartDataPoint {
  bucket: string
  in_kwh: number
  out_kwh: number
}

interface RawMeteringDailyRow {
  date: string
  in_kwh: number
  out_kwh: number
  readings_count: number
  readings: RawMeteringReading[]
}

type DataQualitySeverity = 'green' | 'yellow' | 'red'

interface MeteringPointDataQuality {
  id: string
  meter_id: string
  participant_name: string
  severity: DataQualitySeverity
  data_completeness: number
  days_with_data: number
  total_days: number
  gaps: Array<{ start_date: string; end_date: string; duration_days: number }>
}

// Dashboard responses discriminated by role:
type MeteringDashboardSummary =
  | ZevOwnerDashboardSummary    // role: "zev_owner"
  | ParticipantDashboardSummary // role: "participant"
```

---

## 9. Observability, auditability, and security

- **Import audit trail:** every import creates an `ImportLog` with batch ID,
  row counts, per-row errors, filename, and user.
- **Batch grouping:** `import_batch` UUID on each reading links it back to its
  import log for traceability.
- **Scope enforcement:** reading visibility is enforced via queryset scoping;
  import endpoints require `IsZevOwnerOrAdmin`.
- **Non-destructive defaults:** imports skip duplicates by default; overwrite
  must be explicitly opted into.
- **Error isolation:** malformed rows in CSV generate per-row errors without
  aborting the remaining rows.  Malformed XML in SDAT-CH generates a
  top-level error and returns an empty import log.

---

## 10. Rollout and rollback

- New import parsing rules should be backward-compatible with existing file
  formats or gated behind a new `format_profile` value.
- Removing an unprotected import deletes its currently linked readings through the import-log endpoints. Protected overwrite imports cannot be deleted; previous values have no stored version and cannot be rolled back.
- Import logs are never automatically deleted; they serve as permanent audit
  records.
- The preview endpoint can be used to verify a new format without any write
  risk.

---

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Incorrect column mapping producing wrong readings | High | Preview-first validation with meter existence check and row-level feedback (§4.3) |
| Timezone misalignment causing off-by-one-day errors | High | Explicit UTC boundary construction in all date queries (§7, ADR 0007) |
| Partial import writes with mixed valid/invalid rows | Medium | Per-row error handling; failed rows are skipped; successful rows are written (§4.1) |
| Duplicate readings inflating billing totals | High | Unique constraint `(metering_point, timestamp, direction)` + skip-existing default (§3.1) |
| Overwrite mode silently changing billing-critical data | Medium | Overwrite requires explicit `overwrite_existing=true`; `warnings` reports the count of overwrites |
| Concurrent standard-profile duplicate | Medium | A unique-constraint `IntegrityError` is treated as the standard duplicate skip, not an uncaught 500 |
| Overwrite has no version history | Medium | Previous values cannot be restored automatically. Overwrite imports are protected from single and bulk deletion; correct values through another overwrite import. |
| Duplicate race errors lose exact cause | Low | Race `IntegrityError`s are currently reported using the same duplicate message as ordinary duplicates; improve classification if operational distinction is needed |
| SDAT-CH XML format variations across VNBs | Medium | Graceful fallback for missing elements; per-meter error reporting (§4.2) |
| Data quality severity thresholds misleading operators | Low | Deterministic integer-percent completeness with documented thresholds (§5.5) |

---

## 12. Test plan

### Backend (`metering/tests.py`)

| Test class | Validates |
|---|---|
| `DashboardSummaryAlignmentTests` | §5.4: timestamp-level local/grid split for participant view; owner participant-filter produces correct totals; multi-participant filtering exclusion |
| `DashboardMidPeriodTransferTests` | §5.4: readings attributed per assignment timestamp for owner stats, participant totals/timeline, ZEV-wide stats, and the hourly profile; post-transfer readings excluded |
| `ParticipantImportRestrictionTests` | §6.2: participant cannot list import logs, preview CSV, or upload CSV (all 403) |
| `ImportParserRobustnessTests` | §4.1: malformed CSV reported without crash; malformed SDAT-CH reported without crash; timezone offset normalized to UTC; duplicate rows skipped; idempotent re-import; overwrite mode updates value without creating new row |
| `MeteringRawDataEndpointTests` | §5.3: owner gets daily-grouped raw rows with correct direction sums; participant can read own metering point's raw data |
| `ChartDataEndpointTests` | §5.2: direction aggregates; UTC day/month boundaries agree with raw data; hourly buckets stay distinct across both DST transitions |
| `DataQualityStatusTests` | §5.5: owner sees gaps and severity; participant sees own meters; default 30-day range; fully assigned readings report no unassigned; holder-less meter flags every reading; assignment-gap readings flagged unassigned; overlapping windows flag only the corrupt meter (others still report) |

### Backend (`metering/test_import_csv.py`, `metering/test_import_csv_characterization.py`, `metering/test_import_limits.py`)

| Test module / class | Validates |
|---|---|
| `metering/test_import_csv.py::CsvImportTests` | §4.1/4.3/5.6/8.3: malformed CSV reported without crash; concurrent standard-profile duplicate races are skipped; timezone offset normalized (default parsing and explicit `%z` format); direct upload without preview valid (advisory contract); duplicate rows skipped; idempotent re-import; overwrite (`overwrite_existing=true`) updates in place and returns the overwrite note in `warnings` (never in `errors`); headerless positional mapping; `daily_15min` with `energy_start`/`values_count`; invalid/missing timestamp/energy handling; daily atomic rollback leaks no `imported` count on `IntegrityError`; empty daily rows skipped with an error; daily existence checks batched per contiguous file-day block (query-bound regression test); ZEV scoping (target-ZEV required, missing → 400, bad UUID → 400, unknown → 404, foreign-owned for owner → 403; admin can target any ZEV; mixed-ZEV file scoped to target with per-row errors; `log.zev` equals the requested target); preview (existing/missing meters without writing, unique counts, `missing_meter_ids` capped at 50, rows-beyond-cap still blocking, preview cap, no-write, field validation on missing-meter rows, clean invalid-number messages, single error per truncated/invalid daily row, validation stop at the error cap with whole-file coverage intact; ZEV rejections: missing → 400, bad UUID → 400, unknown → 404, foreign → 403); import (truncated daily row writes nothing and counts one skip with zero readings; CSV errors carry `meter_id` when the row names a meter); same-owner multi-ZEV scoping (a meter from the owner's other ZEV is missing/skipped when targeting the first, for both import and preview); combined row-level field errors (bad timestamp, bad energy, bad direction, blank `meter_id`, missing timestamp/energy); column-mapping failure shape (200, empty `preview_rows`, single `row: null` error); exactly-50 missing IDs with no overflow remainder; audit events recorded for foreign-ZEV preview and import rejections; invalid `timestamp_format` rejected up front on preview (200 with a `row: null` error) and import (201 log, nothing written); year-less formats rejected on preview and upload; invalid timestamps report `Invalid timestamp value` without dateutil internals; daily `existing_data` is direction-aware; `test_daily_overwrite_preview_allows_duplicates_without_writing` covers skip/overwrite parity, invalid-value rejection, unchanged readings/logs during preview, and the final overwrite |
| `metering/test_import_csv_characterization.py` | §4.1/4.3 parsing semantics (BOM, blank lines, ragged rows, Excel first-sheet and blank rows, empty-vs-missing, comma decimals, etc.), plus ZEV-required calls (every `upload_csv`/`preview_csv` passes `zev_id`; helper injects it by default), the unique preview summary (`"existing_metering_points" == 1` not 30), atomic daily validation (truncated/invalid rows write nothing: one error, one skip, zero readings) with per-slot gap-fill for partial duplicates, native Excel datetimes bypassing `timestamp_format` (standard and daily), and `meter_id` on CSV errors |
| `metering/test_import_limits.py::CsvLimitTests` / `XlsxZipLimitTests` / `BackendUploadCapTests` | §4.4/§8.3: size/row/col caps, `values_count`/`interval_minutes` bounds on both import and preview (with `zev_id`), error truncation with sentinel; overwrite note lives in `warnings`, XLSX ZIP limits; characterization also exercises preview with `zev_id` |
| `metering/testing.py` | Shared `upload_csv`/`preview_csv` helpers used by all three modules (always exercise the required-`zev_id` path) |
| `metering/test_import_logs.py::ImportLogDeletionTests` | §3.3/§5.7/§8.2: deletion/rollback plus list-payload identity (`zev_name`, `imported_by_display`, `batch_id` alongside the raw IDs); bulk delete without `zev_id` covers all visible ZEVs but never foreign ones |

### Backend (`metering/test_reading_visibility.py`)

72 parametrized API cases cover raw summaries, raw single-day details, and
day/hour/month chart buckets:

| Test function | Cases | Validates |
|---|---|---|
| `test_only_assignment_days_are_visible_without_duplicate_totals` | 35 | Before/after-transfer exclusion, inclusive UTC boundaries, gaps, returning-holder windows, open-ended assignments through DST, and unduplicated IN/OUT totals |
| `test_next_holder_can_read_their_own_readings` | 5 | The next holder retains access during their own window |
| `test_unbounded_requests_only_aggregate_owned_readings` | 2 | Requests without date bounds aggregate only owned readings, including exact raw reading counts |
| `test_assignment_to_one_meter_does_not_grant_access_to_another` | 5 | Assignment correlation includes the meter, not only caller/date |
| `test_zev_filter_cannot_widen_participant_visibility` | 5 | Foreign meter access is denied and a mismatched ZEV filter excludes an otherwise authorized meter |
| `test_participant_without_assignments_sees_no_readings` | 5 | ZEV membership alone grants no raw/chart access |
| `test_managers_can_read_assignment_gaps` | 10 | Admin/owner access does not depend on assignments |
| `test_owner_cannot_read_another_zevs_meter` | 5 | Owner tenant isolation remains enforced |

### Backend (`metering/test_import_limits.py`, `metering/test_import_sdatch.py`)

| Test class | Validates |
|---|---|
| `CsvLimitTests` | §4.4: CSV over the size cap, row cap, or column cap is rejected with a 400 before parsing (CSV path requires `zev_id`); the header row does not consume the row cap, and headerless files get the full budget; `values_count` outside `1..1440`, `interval_minutes < 1`, and non-integer `interval_minutes`/`values_count` rejected on import and preview, `values_count` at maximum accepted; per-row error list capped at 50 with a truncation sentinel, and the overwrite `warnings` entry never touches the error cap |
| `XlsxZipLimitTests` | §4.4: XLSX ZIP with too many members or a high-ratio member is rejected before openpyxl inflates it; a non-ZIP `.xlsx` is rejected; a sheet whose width appears only after the first row is rejected (column cap holds per row) |
| `SdatchLimitTests` | §4.4: SDAT-CH file over the size cap produces an ImportLog error without parsing; the per-row error list is capped at 50 with a truncation sentinel during the parse loop |
| `SdatchImportTests` (ZEV validation) | §4.2/5.6: SDAT-CH import rejects missing `zev_id` (400), malformed UUID (400), and unknown ZEV (404); foreign-owned ZEV → 403; admin can target any ZEV |

### Backend (`metering/test_generate_metering_data.py`)

| Test class | Validates |
|---|---|
| `GenerateMeteringDataResolutionTests` | `generate_metering_data` writes only `ReadingResolution` choices: 15-minute intervals write the 15-minute resolution (not `"QH"`), hourly intervals write hourly |

### Backend (`accounts/test_throttling.py`)

| Test class | Validates |
|---|---|
| `UploadEndpointThrottleTests` | §4.4: import endpoints and transfer-archive endpoints each return 429 past their per-user budget; the two budgets are independent; key-authenticated import requests still count against the API-key budget |

### Backend (`zev/test_transfer_limits.py`)

| Test class | Validates |
|---|---|
| `TransferArchiveLimitTests` | §4.4: transfer archives with traversal member paths (`/`- and `\`-separated, plus Windows drive letters), absolute paths, too many members, over the compressed or decompressed caps, or a high-ratio member are rejected; non-ZIP archives are rejected; the decompressed cap cannot drop below the documented 2M-row archive scale |

Deletion policy regressions in `ImportLogDeletionTests` cover both CSV profiles, retaining the replacement when the predecessor is deleted, all-or-nothing rejection of period/all bulk deletion, backfilling legacy error/warning notes, and invalid date bounds.

### Frontend

- Import wizard: ZEV taken from the global header selector for both CSV and SDAT-CH (step 2 shows it as a disabled read-only display, not a picker; the wizard cannot advance past step 1 or load a preview without one — `selectZevFirst` hint names the header selector), file summary card with size/extension feedback (legacy `.xls` rejected with the backend guidance, 50 MB cap; Remove clears the native file input so the same file can be re-picked; switching source clears file/preview and resets to step 1), string-kept numeric config with inline range validation (`valuesCount` 1–1440, `intervalMinutes` ≥ 1, tab-aware delimiter (`\t` escape accepted, mirroring the backend), full-date timestamp preflight incl. `%Y-%j` and week formats with a weekday plus matching calendar/ISO year (the backend round-trip probe remains authoritative); preview and import stay disabled until fixed), fingerprint-guarded preview (the stamp includes overwrite mode; every file selection clears the preview even for identical metadata, and closing the wizard or replacing a file invalidates in-flight preview callbacks; stale preview table, banners, and error list are suppressed while `previewOutdated`; the stamp normalizes numeric strings so "096" equals "96" but strictly rejects non-numeric input like "96foo"), bounded `missing_meter_ids` list with a pluralized +N overflow (`andMore_one`/`andMore_other`, hidden when the count is exact) plus copy/download and a Metering Points CTA, profile-aware defaults factory `csvConfigFor(hasHeader, profile)` (headed daily resolves `meter_id/date/00:00` against the daily sample; headed standard resolves `meter_id/timestamp/energy_kwh`; switching profile or header re-derives mappings and clears the preview), error- and missing-gated Start Import, overwrite confirmation dialog (stacked above the wizard: Escape/Tab belong only to the top-most dialog; confirmation has its own dialog semantics and focus trap, and cancellation restores focus to its opener), full wizard reset on success, protocol auto-open on errors or warnings (warnings alone stay success with a success toast), single-state bulk-delete modal with an armed confirmation step, shared `CivilDateInput` selectors with explicit UTC day labels plus a UTC note, and a backend-scoped count (0 until both period dates parse; table search never narrows deletion; count uses the half-open UTC range; copy names the selected ZEV or "all visible ZEVs" when none is selected), and metering + import-log query invalidation on success and after deletion — `frontend/src/pages/ImportsPage.tsx`, covered by `frontend/tests/imports-wizard.test.ts`.
- Import history shows localized source labels plus serializer `zev_name`/`imported_by_display`; the protocol shows ZEV, imported-by, batch ID, and per-error meter IDs. Sample files live in `frontend/public/samples/` and are linked from wizard step 1. History offers filename search and source filtering using the API values `csv` and `sdatch` with raw-value sorting (`created_at`, `filename`, `rows_total` accessors + display cells, `created_at` desc default); row actions use a compact Protocol button plus an `ActionMenu` delete. The protocol renders errors in a `DataTable` (row/meter/reason). Upload and preview map HTTP 413/429 to localized `importTooLarge`/`importThrottled` messages. `previewLoadedWithIssues` and `deleteSuccess` use `_one`/`_other` plural pairs (the latter keyed on the log count).
- Types: `frontend/src/types/api.ts:ImportPreviewResult.missing_meter_ids: string[]` and preview `zevId` required payload in `frontend/src/lib/api/metering.ts:previewCsvImport`.
- Chart data and raw data display
- Dashboard summary role-differentiated behavior
- Data quality severity indicators and gap display
- Locale parity: every new `pages.imports.*` leaf exists in `frontend/src/i18n/locales/{en,de,fr,it}.ts` (`selectZevForCsv`, `selectZevFirst`, `previewOutdated`, `overwriteConfirm*`, `preview.missingIdsLabel`, `preview.andMore_one`, `preview.andMore_other`, `wizard.fileSummary*`/`supportedExtensions`/`sizeLimit`/`sample*`/`xlsRejected`/`fileTooLarge`/`*Invalid` config keys, `messages.fixConfigFirst`/`importSuccessWithIssues`, `preview.copy*`/`downloadMissingIds`/`createMetersCta`, `columns.zev`/`importedBy`, `protocol.zev`/`importedBy`/`batchId`/`meter`, `delete.reviewAction`/`visibleImpact`/`readingImpactUnknown`, `delete.bulkDescriptionAll`/`bulkPeriodMessageAll`/`bulkAllMessageAll`, `sdatchNoPreview`, `history.searchFilename`/`filterSource`/`allSources`, `actions.rowActions`, `messages.importTooLarge`/`importThrottled`, `messages.previewLoadedWithIssues_one`/`_other`, `messages.deleteSuccess_one`/`_other`) — `frontend/tests/locale-parity.test.ts` enforces it; `frontend/tests/dead-i18n-keys.test.ts` guards against orphaned keys (e.g. the retired stacked-confirm `bulkTitle`). Wizard behavior is covered by `frontend/tests/imports-wizard.test.ts` (gating, reset, overwrite confirm, file feedback, config validation including year-less timestamp formats, tab delimiter escape and `%Y-%j` acceptance, and overwrite-warning success, protocol auto-open, bulk-delete armed flow including the all-ZEV copy, history search/filter/sort, row action menu, 413/429 mapping); `FormModal` dialog semantics, Escape, top-most-only Escape for stacked dialogs, top-most-only Tab/Escape traps, Shift+Tab wrap from outside, confirmation focus trap + dialog semantics, focus restoration, and focus stability across re-renders with a fresh `onClose` are covered by `frontend/tests/form-modal.test.ts` and `frontend/tests/modal-stack.test.ts` (inner close returns focus to the outer dialog; background modal stays inert under a confirmation); `importUtils` stamp strictness and the timestamp-format rule are covered by `frontend/tests/imports-samples.test.ts`. The page composes `frontend/src/features/imports/` presentational components (`ImportWizardModal`, `ImportHistoryTable`, `ImportProtocolModal`, `BulkDeleteModal`) with shared config in `importUtils.ts`; repeated layout patterns use shared CSS (`.field-error`, `.imports-history-filters`, `.actions-row`).
- Build and type checks: `npm run build`

The unassigned-holder and overlapping-window warning renders are conditional
JSX in `MeteringChartPage` backed by the `MeteringPointDataQuality` type; they
are covered by backend tests plus the manual check below (no frontend
component test infra exists).

### Manual verification

- Upload standard CSV, daily 15-min CSV, and SDAT-CH XML files; verify import
  log counts and per-row errors.
- Preview a file with missing meters and verify accessible meters are flagged.
- Import same file twice; verify duplicates are skipped (no overwrite).
- Import with `overwrite_existing=true`; verify values updated and count
  reported.
- Check dashboard summary for ZEV owner vs participant; verify local/grid
  split matches timestamp-level calculation.
- Verify data quality severity thresholds: 100% → green, 50–99% → yellow,
  0–49% → red.
- Create a metering point with no assignment and import readings; verify the
  Data Quality table shows the amber "no assignment holder" warning with the
  reading/day counts.
- Inject overlapping assignment windows via the DB (bypassing the model
  guard); verify only the affected meter shows the overlap warning and all
  other meters still report.

---

## 13. Acceptance criteria

- [x] CSV import supports both `standard` and `daily_15min` profiles with configurable column mapping; requires `zev_id` and scopes meters to the target ZEV intersection (§4.1, §5.6)
- [x] SDAT-CH import parses Swiss ebIX XML and skips unknown metering points with per-meter errors; requires `zev_id` (§4.2, §5.6). No preview step: malformed/oversized files return a 201 log with errors, and the UI explains this upfront and auto-opens the protocol when the log contains errors
- [x] Preview endpoint requires `zev_id`, returns row-level validation without writing data, covers the whole file as unique meters with bounded `missing_meter_ids`, keeps display rows capped at `max_rows`, validates fields regardless of meter existence, stops row validation at the error cap while keeping whole-file meter coverage, and reports truncated daily rows once — matching import (§4.3, §5.6). Daily import validation is atomic for truncated/invalid rows (no readings); duplicates gap-fill per slot, fully duplicate rows write no readings
- [x] Default write mode gap-fills per slot and skips duplicates; overwrite mode is opt-in, confirmed in the UI, and reports the count in `warnings`; import `log.zev` is always the validated target (§4.1, §8.3)
- [x] Import log captures filename, batch ID, row counts, and per-row errors for every import (§3.3)
- [ ] Chart data endpoint returns direction-pivoted aggregates with configurable time buckets (§5.2)
- [ ] Raw data endpoint returns daily-grouped individual readings (§5.3)
- [ ] Dashboard summary returns role-differentiated response with correct local/grid split (§5.4)
- [ ] Dashboard readings are attributed per assignment timestamp; gap readings appear in ZEV aggregates but on no participant's totals (§5.4)
- [ ] Data quality status returns per-metering-point gap detection with severity thresholds (§5.5)
- [ ] Data quality status flags holder-less readings and overlapping windows per metering point without failing the whole response (§5.5)
- [ ] All date queries use explicit UTC boundary construction (§7)
- [ ] Participants cannot import or access import logs (§6.2)
- [ ] Metering data filters and date ranges behave consistently across all endpoints (§7)
