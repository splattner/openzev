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
| `zev` | FK → `Zev` (`CASCADE`, nullable) | Inferred or explicit target ZEV |
| `imported_by` | FK → `User` (`SET_NULL`, nullable) | User who triggered the import |
| `source` | `ImportSource` | `csv` or `sdatch` |
| `filename` | `CharField(255)` | Original upload filename |
| `rows_total` | `IntegerField` | Total rows in file |
| `rows_imported` | `IntegerField` | Successfully imported count |
| `rows_skipped` | `IntegerField` | Skipped/duplicate count |
| `errors` | `JSONField` (default `[]`) | Array of error objects; shape varies by source: CSV uses `{row, error}`, SDAT-CH uses `{meter_id?, error}` or `{error}` |
| `created_at` | `DateTimeField` (auto) | Import timestamp |

Ordering: `["-created_at"]`.

**ZEV inference:** if no explicit ZEV is provided on CSV import, the log's ZEV
is inferred from the metering points that were actually touched.  If all
touched meters belong to the same ZEV, that ZEV is stored; otherwise `null`.

---

## 4. Import pipeline

### 4.1 CSV / Excel importer

**Supported file types:** `.csv`, `.xlsx`, `.xls` (via pandas).

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
- Explicit `timestamp_format` → `strptime` + UTC.
- Timezone-aware timestamps → normalized to UTC.
- Naive timestamps → assume UTC.
- `daily_15min` profile → date parsed to midnight UTC, then each slot offset
  by `interval_minutes × slot_index`.

**Write modes:**

| Mode | Behavior | DB operation |
|---|---|---|
| Default (skip) | Skip if `(metering_point, timestamp, direction)` already exists | `get_or_create` |
| Overwrite | Update existing reading's energy value in place | `update_or_create` |

Overwrite reports as a summary error: `"Overwrote N existing readings."`.

**Meter visibility:** meters are scoped to the importing user's role:
- `admin` → all meters (optionally filtered by ZEV).
- `zev_owner` → only meters in owned ZEVs.
- `participant` → no import access (blocked at view permission level).

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

**Endpoint:** `POST /api/v1/metering/import/preview-csv/`

Preview parses up to `max_rows` (default 30) rows and returns:

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
    "rows_previewed": 30
  },
  "errors": []
}
```

For `daily_15min` profile, each preview row includes `interval_minutes` and
`values_count` instead of `energy`, and `existing_data` checks whether readings
already exist for that day.

Preview accepts the same configuration parameters as CSV import (column map,
header, delimiter, profile, timestamp format, interval, values count) but does
**not** write any data.

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

**Date bounds:** explicit UTC start/end construction
(`datetime.combine(..., tzinfo=utc)`) to avoid Django timezone conversion
artifacts (ADR 0007).

### 5.3 Raw data

| Method | URL | Permission | Query params |
|---|---|---|---|
| `GET` | `/readings/raw-data/` | `IsAuthenticated` | `metering_point` (required), `date_from`, `date_to` |

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

1. $\text{local\_pool}(t) = \min(\text{total\_produced}(t),\; \text{total\_consumed}(t))$
2. If $\text{total\_consumed}(t) > 0$ and $\text{local\_pool}(t) > 0$:

$$\text{from\_zev}_i(t) = \min\!\left(\text{consumed}_i(t),\; \text{local\_pool}(t) \times \frac{\text{consumed}_i(t)}{\text{total\_consumed}(t)}\right)$$

3. $\text{from\_grid}_i(t) = \max(\text{consumed}_i(t) - \text{from\_zev}_i(t),\; 0)$

This is identical to the billing engine's proportional allocation but computed
at dashboard queryuery time rather than per-billing-period.

**ZEV-level aggregates:**

For each timestamp $t$:
- $\text{imported}(t) = \max(\text{consumed}(t) - \text{produced}(t),\; 0)$
- $\text{exported}(t) = \max(\text{produced}(t) - \text{consumed}(t),\; 0)$

These are aggregated per bucket for the timeline.

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
      ]
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

**Participant resolution:** the current participant assignment (active today)
is looked up for display; meters with no current assignment show
`"Unassigned"`.

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
- Single-log delete removes the selected `ImportLog` and all `MeterReading` rows with `import_batch == batch_id`.
- Bulk delete operates on the same scoped queryset as the list endpoint.
- Bulk delete accepts `mode = all | period`.
- `mode = period` requires `date_from` and `date_to` and filters by `ImportLog.created_at::date` inclusively.
- Bulk delete may additionally be narrowed with `zev_id`.
- Delete responses return counts for both deleted logs and deleted readings.

---

## 6. Actors, permissions, and ZEV scope

### 6.1 Readings queryset scoping

| Role | Visible readings |
|---|---|
| `admin` | All readings |
| `zev_owner` | Readings for meters in `zev__owner = user` |
| `participant` | Readings for meters assigned to them via `assignments__participant__user = user` |

### 6.2 Permission summary

| Action | `admin` | `zev_owner` | `participant` |
|---|---|---|---|
| List/read readings | All | Own ZEV | Own assigned meters |
| CRUD readings | Yes | Yes | No (403) |
| Chart data, raw data | Yes | Yes | Yes (read-only from own) |
| Dashboard summary | Yes (with `zev_id`) | Yes (own ZEV) | Yes (own data, different response shape) |
| Data quality status | Yes | Yes | Yes (own meters) |
| CSV/SDAT-CH import | Yes | Yes | No (403) |
| Preview CSV | Yes | Yes | No (403) |
| List import logs | Yes | Own ZEV / own imports | No (403) |

---

## 7. Timezone policy

Per ADR 0007, all metering timestamps are stored and queried in UTC.

**Query boundary construction:** date parameters (`date_from`, `date_to`) are
converted to explicit UTC bounds:

```python
start = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
end   = datetime.combine(date_to, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
# Filter: timestamp >= start AND timestamp < end
```

This avoids Django's `__date` lookup which applies `USE_TZ` / `TIME_ZONE`
conversion and can drop/duplicate readings near midnight boundaries.

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

### 8.3 Frontend types

```typescript
interface ImportLog {
  id: string
  batch_id?: string
  zev?: string
  imported_by?: number | null
  filename: string
  rows_total?: number
  rows_imported: number
  rows_skipped: number
  source: string
  errors?: Array<{ row: number | null; error: string }>
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
    existing_metering_points: number
    missing_metering_points: number
    rows_previewed: number
  }
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
- Rollback of readings: filter by `import_batch` UUID and bulk-delete.
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
| Overwrite mode silently changing billing-critical data | Medium | Overwrite requires explicit `overwrite_existing=true`; summary error reports count of overwrites |
| SDAT-CH XML format variations across VNBs | Medium | Graceful fallback for missing elements; per-meter error reporting (§4.2) |
| Data quality severity thresholds misleading operators | Low | Deterministic integer-percent completeness with documented thresholds (§5.5) |

---

## 12. Test plan

### Backend (`metering/tests.py`)

| Test class | Validates |
|---|---|
| `DashboardSummaryAlignmentTests` | §5.4: timestamp-level local/grid split for participant view; owner participant-filter produces correct totals; multi-participant filtering exclusion |
| `ParticipantImportRestrictionTests` | §6.2: participant cannot list import logs, preview CSV, or upload CSV (all 403) |
| `ImportParserRobustnessTests` | §4.1: malformed CSV reported without crash; malformed SDAT-CH reported without crash; timezone offset normalized to UTC; duplicate rows skipped; idempotent re-import; overwrite mode updates value without creating new row |
| `MeteringRawDataEndpointTests` | §5.3: owner gets daily-grouped raw rows with correct direction sums; participant can read own metering point's raw data |
| `DataQualityStatusTests` | §5.5: owner sees gaps and severity; participant sees own meters; default 30-day range |

### Frontend

- Import wizard form fields and preview rendering
- Chart data and raw data display
- Dashboard summary role-differentiated behavior
- Data quality severity indicators and gap display
- Build and type checks: `npm run build`

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

---

## 13. Acceptance criteria

- [ ] CSV import supports both `standard` and `daily_15min` profiles with configurable column mapping (§4.1)
- [ ] SDAT-CH import parses Swiss ebIX XML and skips unknown metering points with per-meter errors (§4.2)
- [ ] Preview endpoint returns row-level validation without writing data (§4.3)
- [ ] Default write mode skips duplicates; overwrite mode is opt-in and reports count (§4.1)
- [ ] Import log captures filename, batch ID, row counts, and per-row errors for every import (§3.3)
- [ ] Chart data endpoint returns direction-pivoted aggregates with configurable time buckets (§5.2)
- [ ] Raw data endpoint returns daily-grouped individual readings (§5.3)
- [ ] Dashboard summary returns role-differentiated response with correct local/grid split (§5.4)
- [ ] Data quality status returns per-metering-point gap detection with severity thresholds (§5.5)
- [ ] All date queries use explicit UTC boundary construction (§7)
- [ ] Participants cannot import or access import logs (§6.2)
- [ ] Metering data filters and date ranges behave consistently across all endpoints (§7)
