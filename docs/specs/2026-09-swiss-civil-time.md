# Feature Spec: Swiss civil time for billing, analytics and import

- Spec ID: SPEC-2026-swiss-civil-time
- Status: In Progress
- Scope: Major
- Type: Change
- Owners: Sebastian Plattner
- Created: 2026-09-29
- Target Release: next minor
- Related Issues: —
- Related ADRs: [0026](../adr/0026-swiss-civil-time-for-billing.md) (supersedes [0007](../adr/0007-timezone-policy.md)), 0002, 0013, 0018, 0019
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

Readings are stored as UTC instants, but every "which day / hour / weekday /
month" question is answered on the UTC components of the timestamp, and
offset-less CSV/Excel timestamps are stamped as UTC. Offset-less files (Swiss
local time) happen to bill correctly; SDAT-CH files and offset-carrying CSV do
not. The result, reproduced by `tariffs/test_band_timezone.py`:

| Symptom | Affected data | Error |
|---|---|---|
| HT/NT band boundaries | SDAT, CSV with offset | 1 h (winter) / 2 h (summer) at each boundary, every day |
| Weekday bands (weekend tariffs) | SDAT, CSV with offset | Saturday/Monday start 1–2 h early |
| Seasonal bands | SDAT, CSV with offset | Season flips 1–2 h early at month boundaries |
| Dynamic price per reading (VSE v1/v2, BFE) | offset-less CSV | Reading priced at the interval 1–2 h later |
| Local allocation per timestamp | ZEV mixing SDAT and offset-less CSV | Production and consumption series 1–2 h apart |
| Billing period, move-in/out, tariff validity | SDAT, CSV with offset | Boundaries 1–2 h before local midnight |
| Charts, hourly profile, PDFs, MCP profile | SDAT, CSV with offset | Hours shown 1–2 h early (solar peak at 11:00 in summer) |
| DST weekends | offset-less CSV | Autumn hour rejected as duplicates, spring hour reported as a gap |

**Outcome:** storage stays UTC; every calendar question is answered in
`Europe/Zurich` through one helper module; the import reads offset-less values
in a declared zone (default `Europe/Zurich`) with explicit DST rules; existing
offset-less data is re-anchored by an opt-in command; the frontend shows
instants in `Europe/Zurich`.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Civil-time helpers | `allocation.validity` gains the business timezone and civil-date helpers; `period_start_dt`/`period_end_exclusive_dt`/`period_window` return local-midnight bounds (§4.1) |
| Billing engine | Band resolution on local wall clock; assignment/tariff validity on the local civil date (§4.2) |
| Allocation, readiness, analytics, PDFs, annual statement | Every UTC civil-date or UTC-hour derivation replaced by the helpers (§4.3) |
| Chart and summary endpoints | Day/month buckets truncated in `Europe/Zurich`, hour buckets stay UTC-truncated (§5.1) |
| Import-log bulk delete | Selects `created_at` by Zurich days (§5.2) |
| CSV/Excel import | `timestamp_timezone` setting (`Europe/Zurich` default, `UTC`), DST rules, day-length-aware daily profiles (§6.1) |
| SDAT-CH import | Offset-less timestamps read explicitly as `Europe/Zurich` (§6.2) |
| `ImportLog` | New `timestamp_timezone` field recording how offset-less values were read (§4.4) |
| Existing data | `reanchor_readings` management command (§6.3) |
| Dynamic tariffs | `local_civil_day_window` folds into `period_window`; `_last_fully_covered_day` uses civil dates (§4.3) |
| Demo data | `seed_demo` and `generate_metering_data` generate on the Swiss wall clock (§6.4) |
| Frontend | Business-timezone formatting for instants and metering buckets; import timezone field; bulk-delete preview in Zurich days (§7) |
| Docs | ADR 0026, baseline spec updates (§10), user guide (§10) |

### Out of scope

- Per-ZEV or per-installation configurable business timezone. `Europe/Zurich`
  comes from `settings.TIME_ZONE` and is fixed.
- Changing issued invoices. They are frozen; only drafts regenerate.
- Dynamic-tariff fetch *transport* windows (UTC today ± buffers,
  `tariffs/dynamic/fetch.py`). They are deliberately wider than any civil day
  and stay as they are.
- Rewriting evidence rows (`InvoiceDynamicSourceEvidence`) written before the
  change; their UTC-midnight windows remain valid protected ranges.
- Automatic migration of existing readings (ADR 0026, alternative 3).

## 3. Actors, permissions, and ZEV scope

No permission changes.

| Actor | Capability |
|---|---|
| `admin` | Sets the import timezone for any ZEV's import; runs `reanchor_readings` (shell access) |
| `zev_owner` | Sets the import timezone for imports into own ZEV (same permission as today's import) |
| `participant` | Sees charts and invoices in Swiss civil time; no new capability |
| `guest` | No change |

`reanchor_readings` is a management command, so it is only available to whoever
operates the server. It does not go through the API or `IsAdmin`.

## 4. Data model and core helpers

### 4.1 Civil-time helpers — `allocation/validity.py`

This module stays the single place that converts between civil dates and UTC
instants. It already depends only on the stdlib and Django; it adds
`django.conf.settings` and `zoneinfo`.

| Name | Signature | Behaviour |
|---|---|---|
| `business_tz` | `() -> ZoneInfo` | `ZoneInfo(settings.TIME_ZONE)`, cached with `functools.cache` |
| `period_start_dt` | `(day: date) -> datetime` | **Changed.** `datetime(day.year, day.month, day.day, tzinfo=business_tz()).astimezone(timezone.utc)`. Swiss DST changes happen at 02:00/03:00, so local midnight is never ambiguous or missing |
| `period_end_exclusive_dt` | `(day: date) -> datetime` | **Changed.** `period_start_dt(day + timedelta(days=1))` — *not* `+ 24 h`, because a DST day is 23 or 25 hours |
| `period_window` | `(start: date, end: date) -> tuple[datetime, datetime]` | Unchanged signature; now `[local start 00:00, local end+1 00:00)` in UTC |
| `civil_date` | `(ts: datetime) -> date` | `ts.astimezone(business_tz()).date()`. Raises `ValueError` for a naive `ts` — every timestamp reaching it comes from the ORM or an importer and is aware |
| `wall_clock` | `(ts: datetime) -> datetime` | `ts.astimezone(business_tz())`; naive `ts` returned unchanged (callers that work on synthetic naive datetimes, see §4.2) |
| `day_length` | `(day: date) -> timedelta` | `period_end_exclusive_dt(day) - period_start_dt(day)`: 23 h, 24 h or 25 h |

`invoices.engine._utc_date` is removed; all its call sites use `civil_date`.
`tariffs.dynamic.services.local_civil_day_window` is removed; its callers use
`period_window`, which now computes the same thing.

### 4.2 Tariff band resolution — `tariffs/periods.py`

`resolve_band(periods, ts)` converts first: `ts = wall_clock(ts)`. Month
(step 1), time and weekday (step 3) are then read from the Swiss wall clock.
The in-window, flat-band and fallback rules (tariffs spec §3.2) are unchanged.

A naive `ts` is used as-is. That keeps `average_percentage`, which walks a
synthetic naive reference year, and the existing naive-datetime band tests
(`test_midnight_bands.py`, `test_seasonal_periods.py`,
`test_multi_band_periods.py`) valid: a naive value there already *is* a wall
clock.

On the autumn DST day the two 02:00 hours both resolve at 02:xx local; on the
spring day no reading exists at 02:xx local. Both are correct.

### 4.3 Call sites converted to the helpers

Every site below currently derives a civil date or hour from UTC. Each is
changed as stated; no other behaviour changes.

| File | Function | Today | After |
|---|---|---|---|
| `invoices/engine.py` | `_billable_energy_types_by_timestamp`, `preflight_dynamic_prices._bills_nonzero_percentage_at` and the per-reading loops in `generate_invoice` | `_utc_date(ts)` | `civil_date(ts)` |
| `allocation/windows.py` | `AssignmentWindows.participant_at`, `.assignment_at` | `ts.astimezone(timezone.utc).date()` | `civil_date(ts)`; module docstring rewritten for ADR 0026 |
| `metering/analytics.py` | `_distribute_reading` | UTC date | `civil_date(ts)` |
| `metering/analytics.py` | `compute_hourly_profile` | `ts.hour` (UTC) | `wall_clock(ts).hour`. The autumn DST day adds two hours to bucket 2 and the spring day none to it; the per-day average keeps dividing by the number of civil days |
| `metering/analytics.py` | `compute_data_quality_status` | UTC date | `civil_date(ts)` |
| `invoices/pdf_stats.py` | `_entry` (both) | UTC date | `civil_date(reading.timestamp)` |
| `invoices/pdf_charts.py` | `_build_hourly_profile_chart_svg` | UTC date, `ts.hour` | `civil_date(ts)`, `wall_clock(ts).hour` |
| `invoices/annual_statement.py` | `_compute_monthly_data` | `datetime(year, 1, 1, tzinfo=utc)` bounds | `period_window(date(year, 1, 1), date(year, 12, 31))` |
| `invoices/annual_statement.py` | `_participant_share` | UTC date | `civil_date(ts)` |
| `invoices/readiness.py` | `_dynamic_uncovered_days_by_source` | `gap_start.date()`, `(gap_end - 1 µs).date()` | `civil_date(...)` on both |
| `invoices/readiness.py` | `_load_bulk` | `ts.date()` | `civil_date(ts)` |
| `invoices/period_overview.py` | `compute_period_overview` | `timestamp.date()` | `civil_date(timestamp)` |
| `tariffs/dynamic/pricing.py` | `_last_fully_covered_day` | `(covers_to - 1 µs).date()` | `civil_date(covers_to - 1 µs)`; the docstring's "22:00 or 23:00 UTC" case disappears, since a local month boundary is now a civil-day boundary |
| `tariffs/dynamic/services.py`, `tariffs/views.py` | `local_civil_day_window` (removed) and its caller, the price-history action | local window | `period_window`, which now computes the same window |
| `metering/importers/sdatch_importer.py` | `_parse_ts` | bare `astimezone` | §6.2 |
| `metering/views.py` | `chart_data`, `raw_data`, `dashboard_summary`, `_scope_by_role`, `bulk_delete` | UTC truncation and UTC days | §5.1–5.2; `_bucket_trunc(bucket)` picks the truncation |

The rule from ADR 0007 still applies: no `timestamp__date` lookups. Any
remaining `.date()` on a reading timestamp outside `allocation.validity` is a
bug.

### 4.4 `ImportLog.timestamp_timezone`

**Model:** `metering.models.ImportLog`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `timestamp_timezone` | `CharField(max_length=40, blank=True)` | `""` | Zone offset-less timestamps in this batch were read in: `"Europe/Zurich"` or `"UTC"`. `""` = written before this change (legacy: offset-less values were stamped as UTC). SDAT imports record `"Europe/Zurich"`. |

Migration: `metering/migrations/00xx_importlog_timestamp_timezone.py`, adds the
column with default `""`. No data migration — existing rows stay `""`, which is
exactly how `reanchor_readings` finds legacy batches (§6.3).

**Serializer:** `ImportLogSerializer` uses `fields = "__all__"`, so the field is
included and read-only by virtue of never being writable through the log API.

## 5. API contracts

### 5.1 Metering chart and summary endpoints — `metering/views.py`

| Endpoint | Change |
|---|---|
| `GET /api/v1/metering/readings/chart-data/` (`chart_data`) | `bucket=day`/`month`: `TruncDay`/`TruncMonth(..., tzinfo=business_tz())`. `bucket=hour`: unchanged `TruncHour(..., tzinfo=timezone.utc)`. `date_from`/`date_to` bounds come from `period_start_dt`/`period_end_exclusive_dt` (already the case; their meaning changes) |
| `GET /api/v1/metering/readings/raw-data/` (`raw_data`) | Day grouping `TruncDay(..., tzinfo=business_tz())`; the row key is the Zurich civil date. Detail mode (`?date=`) returns the readings in `period_window(day, day)`, i.e. the local day, 92–100 rows |
| `GET /api/v1/metering/readings/dashboard-summary/` (`dashboard_summary`) | Same bucket rule as `chart_data` |
| `GET /api/v1/metering/readings/hourly-profile/` (`hourly_profile`) | Hours are Zurich wall-clock hours (§4.3) |
| Participant scoping (`_scope_by_role`) | `TruncDate("timestamp", tzinfo=business_tz())` for the per-day assignment correlation |

Response shapes are unchanged. Bucket values are ISO-8601 datetimes carrying
the offset of the zone they were truncated in: a day bucket serializes as
`2026-07-01T00:00:00+02:00`, an hour bucket stays UTC (`2026-07-01T02:00:00Z`,
labelled 04:00 by the frontend). Consumers must parse the offset and must not
read the string's date part as a date.

### 5.2 Import-log bulk delete — `POST /api/v1/metering/import-logs/bulk-delete/`

`mode=period` selects `created_at` in `period_window(date_from, date_to)` —
Zurich days — instead of UTC days. The response field `timezone` and the audit
metadata's `timezone` change from `"UTC"` to `str(business_tz())`
(`"Europe/Zurich"`). Permission (`IsAdmin`) and all other behaviour are
unchanged.

### 5.3 `POST /api/v1/metering-points/{id}/delete-readings/`

`date_from`/`date_to` become inclusive **Zurich** civil dates (via
`period_window`). No code change beyond §4.1; documentation only.

### 5.4 CSV preview and import

`POST /api/v1/metering/import/preview-csv/` and `POST /api/v1/metering/import/csv/` (`ImportView`)
accept one new form field:

| Field | Values | Default | Behaviour |
|---|---|---|---|
| `timestamp_timezone` | `Europe/Zurich`, `UTC` | `Europe/Zurich` | Zone for offset-less timestamps and daily-profile dates (§6.1). Any other value → `400 {"error": "timestamp_timezone must be one of Europe/Zurich, UTC."}` |

The view passes `request.data.get("timestamp_timezone") or None`, so an empty
value means the default. Validation errors are `ImportFileError`s, which both
views already turn into the `400` above.

The preview response gains two top-level keys, on every path including the
early return for column or format errors:

| Key | Type | Meaning |
|---|---|---|
| `timestamp_timezone` | `"Europe/Zurich" \| "UTC"` | The zone the preview applied |
| `rows_skipped_dst_gap` | `int` | Standard rows skipped under §6.1 rule 4 (zero energy in the spring DST gap); not counted in `errors` |

The preview audit event (`import.preview_csv`) adds `timestamp_timezone` from the
payload; the successful-import audit event (`import.upload`) adds
`log.timestamp_timezone` (`"Europe/Zurich"` for SDAT). The import stores the
zone on `ImportLog.timestamp_timezone`, including on the failed-attempt log.
The CSV detect endpoint (`POST /api/v1/metering/import/detect-csv/`) does not
guess it; it returns `"timestamp_timezone": "Europe/Zurich"` in `settings`
(`csv_detect._result`, from `DEFAULT_TIMESTAMP_TIMEZONE`) so the wizard has a
value to prefill.

## 6. Async and integration behavior

### 6.1 CSV/Excel importer — `metering/importers/csv_importer.py`

`preview_csv` and `import_csv` gain `timestamp_timezone="Europe/Zurich"`
(`DEFAULT_TIMESTAMP_TIMEZONE`), validated by `_coerce_timestamp_timezone`
against the keys of `TIMESTAMP_TIMEZONES = {"Europe/Zurich": ZoneInfo("Europe/Zurich"), "UTC": timezone.utc}`;
an empty value means the default, anything else raises `ImportFileError`.

All timestamp interpretation goes through one class, **`TimestampReader(timestamp_format, zone_name)`**:

| Member | Behaviour |
|---|---|
| `is_local` | `True` unless the zone is UTC |
| `parse(raw)` | An aware UTC datetime for a value with an offset (ISO `+01:00`/`Z`, a `%z` format, an aware cell); a **naive wall clock** otherwise. Uses `timestamp_format` via `strptime` when set, else `_parse_flexible` (ISO first, then `dateutil`). Unparsable → `ValueError("Invalid timestamp value '…'.")` |
| `resolve(parsed, series_key)` | The UTC instant. Aware values pass through; naive values are localized in the zone (UTC: `replace(tzinfo=utc)`, i.e. the legacy behaviour). Raises `NonexistentLocalTime` inside the spring gap; applies the autumn rule below |
| `day_window(raw_day)` | A `DayWindow(day, start, end)`: the row's civil date and its `[local midnight, next local midnight)` as UTC. ISO dates parse as ISO, other text day-first (`07.01.2026`) — unchanged |

The autumn rule keeps per-file state, so **every pass over a file uses a fresh
reader** and visits rows in file order: the existing-data prefetch, the preview
loop and the import loop each create their own. `_parse_row_timestamp` and
`_build_day_start` are removed. `_parse_datetime_utc` stays, unchanged, for the
transfer-archive importer, whose timestamps always carry an offset.

**Standard profile** (`_interpret_standard_row(row, *, resolved_cols, reader, meter_type, series_key)`,
shared by prefetch, preview and import; callers pass the meter id as `series_key`):

1. A value with an offset is converted as written. `timestamp_timezone` is
   ignored.
2. An offset-less value (text or an Excel `datetime` cell) is a wall-clock time
   in `timestamp_timezone`. With `UTC` this is the pre-ADR-0026 behaviour
   exactly.
3. **Autumn DST** (a wall-clock time whose `fold=0` and `fold=1` offsets differ,
   02:00–02:59 on the last Sunday of October): per `(series_key, direction)` in
   file order, the first occurrence is `fold=0` (CEST), later ones `fold=1`
   (CET). A third occurrence lands on the second's instant and reports the
   usual intra-file duplicate error. A file that lists the hour once gets
   summer time for it, and the missing winter hour is a normal data gap.
4. **Spring DST** (a wall-clock time that does not round-trip, 02:00–02:59 on
   the last Sunday of March): with energy `0` the row returns a
   `DstGapSkip(day)` instead of an error string. The import counts it as
   skipped and adds one warning per day,
   `"Skipped {n} rows at {date} 02:00–02:59: that hour does not exist in Swiss time (DST start)."`;
   the preview counts it in `rows_skipped_dst_gap`. With non-zero energy it is
   a row error, `"Timestamp {value} does not exist in Swiss time (DST start)."`

Rules 3–4 only arise when `timestamp_timezone = Europe/Zurich`.

**Daily profile** (daily branches of `preview_csv` and `_import_table_rows`):

1. `reader.day_window(date)` gives the row's civil day. Slot `i` is
   `window.start + i × interval_minutes` in UTC arithmetic, so a Zurich row
   starts at Swiss midnight and a `UTC` row at UTC midnight.
2. After `_parse_daily_values` succeeds and the row is not empty,
   `_fit_daily_values(values, window, interval_minutes, reader.is_local)` fits
   the values to the day. `UTC` rows, and intervals that do not tile the day,
   pass through unchanged. For Zurich, with `L` the day's slot count (92, 96 or
   100 for 15-minute data) and `n = values_count`:
   - `n > L`: trailing empty values are dropped down to `L`. If still too many
     on a DST-start day and the surplus is exactly one hour, the slots of the
     missing hour (positions `2h/interval` to `3h/interval`, the 9th–12th value
     for 15-minute data) are dropped when all empty or `0`. Still too many →
     row error `"{date} has {L} intervals in Swiss time (DST start), but the row has {n} values."`
     (`(DST end)` or no suffix depending on the day's length).
   - `L > n ≥ 24 h / interval` (a 25-hour day given an ordinary day's values):
     row error `"{date} has {L} intervals in Swiss time (DST end), but the row has {n} values."`
   - `n < 24 h / interval`: kept as is. Partial days stay allowed.
   A file from a DST-aware exporter with 100 columns sets `values_count=100`;
   its four trailing columns are empty on ordinary days and dropped.
3. The existing-data prefetch (`_prefetch_daily_existing(..., reader)`) collects
   the rows' `DayWindow`s and merges adjacent ones (`_contiguous_day_ranges`,
   which now takes windows and merges `start <= previous end`), then runs one
   `_fetch_existing_daily_set` range query per block. The preview's per-row
   `existing_data` flag checks `window.start <= ts < window.end`, and the
   preview row's `timestamp` is `window.day`.

### 6.2 SDAT-CH importer — `metering/importers/sdatch_importer.py`

`_parse_ts`: `Z` and explicit offsets unchanged. An offset-less value is
localized in `business_tz()` (`fold=0`) instead of going through bare
`astimezone()` (which silently depended on the process timezone). The import
writes `ImportLog.timestamp_timezone = "Europe/Zurich"`. Interval positions stay
`start + resolution × i` in UTC arithmetic, which is already DST-correct.

### 6.3 `reanchor_readings` management command

**File:** `metering/management/commands/reanchor_readings.py`

Moves readings written from offset-less files before this change from
"Swiss wall clock labelled UTC" to the real instant.

```
python manage.py reanchor_readings --list [--zev <zev_id>]
python manage.py reanchor_readings --batch <batch_id> [--batch <batch_id> ...] [--apply] [--allow-invoiced]
```

| Option | Behaviour |
|---|---|
| `--list` | Lists legacy batches (`legacy_batches()`: `ImportLog` with `source="csv"` and `timestamp_timezone=""`), oldest first, with batch id, ZEV, filename, `created_at` (Zurich), readings still carrying the batch id, and first/last reading. Read-only |
| `--batch` | Batches to re-anchor, planned **together** (below). Each must be a legacy CSV batch; an unknown id, an SDAT batch ("carry offsets and are already correct") or one already read in a zone ("already read as …") is refused by id and nothing is written |
| (no `--apply`) | Dry run: per batch the readings to move and zero-energy spring-gap readings to delete, one example move, then non-existent times with energy, collisions and affected invoices (first 20 of each). Writes nothing |
| `--apply` | Performs the whole selection in one transaction |
| `--allow-invoiced` | Required when an approved, sent or paid invoice of a participant ever assigned to one of the metering points overlaps the civil dates between the earliest target and the latest source instant. Such invoices are listed and never modified |

**Transformation** (`reanchored(ts)`): the UTC components are the wall clock;
localize them in `Europe/Zurich` with `fold=0` and convert to UTC. An autumn
wall-clock time is read as summer time (the legacy import could only store it
once). A wall-clock time in the spring gap has no instant: such a reading is
**deleted** when its energy is `0` (the import's rule 4) and otherwise
**refuses** the selection — it cannot stay where it is, because the reading two
hours later moves onto its slot.

**Planning** (`SelectionPlan(logs)`): all readings of all selected batches are
planned as one unit, in ascending timestamp order. Every reading moves to an
earlier instant, so a month's first hours can take the previous month's last
hours when that month's batch is in the same selection. A target
`(metering_point, timestamp, direction)` is a collision if two moved readings
share it, or if a reading *outside* the selection holds it; any collision
refuses the selection, and nothing is written.

**Apply:** inside one `transaction.atomic()`: delete the zero-energy spring-gap
readings, update each moved reading by primary key in ascending source order
(so each target was vacated before it is taken), then for each batch set
`ImportLog.timestamp_timezone = "Europe/Zurich"` — which makes a second run
refuse it — and record its audit event.

**Audit:** one `record_audit_event` per batch, category `IMPORT`,
`action_type="import.readings_reanchored"`, target `metering.ImportLog`,
`zev=log.zev`, `source=MANAGEMENT_COMMAND`, metadata
`{batch_id, zev_id, moved, dropped_nonexistent, allow_invoiced}`. Dry runs are
not audited.

Readings that no longer carry their original batch id (overwritten by a later
import, which re-stamps `import_batch`) belong to the later batch and move with
it or not at all.

### 6.4 Demo and synthetic data

`zev/management/commands/seed_demo.py` and
`metering/management/commands/generate_metering_data.py` generate readings on
the Swiss wall clock: iterate civil days via `period_window`, compute load/PV
curves from `wall_clock(ts).hour`, and store UTC instants. Demo import logs
record `timestamp_timezone="Europe/Zurich"`. `seed_demo`'s UTC-midnight
`timestamp__gte/__lt` filters switch to `period_window`.

## 7. Frontend

### 7.1 Business-timezone formatting — `frontend/src/lib/dates.ts`, `lib/appSettings.tsx`

- New constant `BUSINESS_TIME_ZONE = 'Europe/Zurich'` in `lib/dates.ts`. It
  mirrors `settings.TIME_ZONE`; a unit test pins the value.
- New helper `zonedParts(value: Date): { year, month, day, hours, minutes }`
  built on `Intl.DateTimeFormat('en-CA', { timeZone: BUSINESS_TIME_ZONE,
  hourCycle: 'h23', ... }).formatToParts`.
- New helper `formatBusinessIsoDate(value: Date): string` — an instant's civil
  date in `Europe/Zurich` as `YYYY-MM-DD`.
- New helper `businessDayStartMs(isoDate: string): number` — the epoch ms of
  00:00 `Europe/Zurich` on that date, the same instant as the backend's
  `period_start_dt`. Two passes: the offset read at UTC midnight can differ
  from the one at local midnight on a DST day, so the second pass reads the
  offset at the first estimate.
- New helper `nextIsoDate(isoDate: string): string` — the following civil date.
- `formatDateTime`, `formatShortDate` and the other instant formatters in
  `lib/appSettings.tsx` read components from `zonedParts` instead of local
  getters. Date-only strings (`YYYY-MM-DD`) keep the existing no-timezone path
  (`new Date(y, m-1, d)`), so billing-period dates are unaffected.
- `formatDateParts` takes a `ParsedDateValue { date, dateOnly }` from
  `parseDateValue`; month names for instants use
  `timeZone: BUSINESS_TIME_ZONE`.
- `formatIsoDate`, `formatUtcIsoDate`, `daysInPeriod` and
  `lib/billingPeriod.ts` stay as they are: they operate on date strings, not
  instants. `todayLocalIso` is renamed `todayBusinessIso()` (today's date in
  `Europe/Zurich`, matching the backend's `timezone.localdate()`), with every
  call site updated.

### 7.2 Metering bucket labels — `frontend/src/lib/meteringLabels.ts`

`utcParts` is replaced by `zonedParts`; `formatUtcShortDate`,
`formatUtcDateTime` and `formatUtcMonthYear` become `formatBucketShortDate`,
`formatBucketDateTime`, `formatBucketMonthYear`, and the month name uses
`timeZone: BUSINESS_TIME_ZONE`. `formatMeteringBucketLabel`'s signature is
unchanged. The module comment is rewritten for ADR 0026. Consumers
(`DashboardPage.tsx`, `MeteringChartPage.tsx`) need no change.

### 7.3 Other instant sites

| File | Line today | Change |
|---|---|---|
| `components/RawMeteringTable.tsx` | UTC `getUTCHours()`/`getUTCMinutes()` in `formatTimeOnly` and `buildHourGrid` | `zonedParts`; a detail day lists 92–100 rows, and in the hour grid the autumn day's two 02:00 hours add up in one cell |
| `pages/MeteringChartPage.tsx` | `formatUtcIsoDate(new Date(mp.first_reading_at))` / `last_reading_at` | Business-zone date of the instant (`formatBusinessIsoDate`, new in `lib/dates.ts`) |
| `pages/ImportsPage.tsx` | bulk-delete visible count from `T00:00:00Z` bounds | `businessDayStartMs(from)` … `businessDayStartMs(nextIsoDate(to))`, matching §5.2 |
| `features/tariffs/DynamicPriceHistoryModal.tsx` | `formatDateTime(new Date(value).toISOString(), ...)` | Unchanged call; now renders in `Europe/Zurich` via §7.1 |
| `features/zev/ZevImportModal.tsx` | archive `exported_at` via `new Date(...).toLocaleString()` (browser zone and locale) | `formatDateTime(manifest.exported_at, settings)`: Swiss time in the user's date-time format |

### 7.4 Import wizard — `frontend/src/features/imports/ImportWizardModal.tsx`

- New select **"Timestamps without an offset are"** with options
  `Europe/Zurich` ("Swiss time (CET/CEST)") and `UTC`, default `Europe/Zurich`,
  in the format section of the CSV settings step, after the date/time format
  field. Hint text below it: "Timestamps with an offset such as +01:00 or Z are
  always read as written."
- Props `timestampTimezone` / `onTimestampTimezoneChange`; the state lives in
  `pages/ImportsPage.tsx` (`useState<ImportTimestampTimezone>('Europe/Zurich')`),
  is reset by `resetWizard`, set from detection, sent with preview and upload,
  and is part of `PreviewStamp`, so changing it invalidates a loaded preview.
- Prefilled from `CsvDetectResult.settings.timestamp_timezone`
  (`settingsFromDetection` in `features/imports/importUtils.ts` gains
  `timestampTimezone`).
- `uploadMeteringFile` and `previewCsvImport` in `lib/api/metering.ts` append
  `timestamp_timezone`; `UploadMeteringFilePayload` and
  `PreviewCsvImportPayload` (same file) gain `timestampTimezone?`.
- The import protocol modal (`ImportProtocolModal.tsx`) shows the batch's zone
  for CSV imports, reusing the wizard's option labels; legacy batches (`""`)
  show "UTC (imported before October 2026)".
- The bulk-delete modal (`BulkDeleteModal.tsx`) drops "(UTC)" from the date
  labels and confirmation messages, and its note says the period uses Swiss
  calendar days of the import time.

i18n, in `de.ts`, `en.ts`, `fr.ts`, `it.ts`: new keys
`pages.imports.wizard.timestampTimezone`, `…timestampTimezoneZurich`,
`…timestampTimezoneUtc`, `…timestampTimezoneHint`,
`pages.imports.protocol.timestampTimezone` and `…timestampTimezoneLegacy`;
`pages.imports.delete.dateFrom`, `dateTo`, `utcNote`, `bulkPeriodMessage` and
`bulkPeriodMessageAll` lose their UTC wording.

### TypeScript types — `frontend/src/types/api.ts`

```typescript
export type ImportTimestampTimezone = 'Europe/Zurich' | 'UTC'

interface ImportLog {
    // ...existing fields
    /** '' for batches imported before ADR 0026 (offset-less values read as UTC). */
    timestamp_timezone?: ImportTimestampTimezone | ''
}

interface ImportPreviewResult {
    // ...existing fields
    timestamp_timezone: ImportTimestampTimezone
    /** Zero-energy rows at a time that does not exist in Swiss time (DST start); skipped, not errors. */
    rows_skipped_dst_gap: number
}

interface CsvDetectResult {
    settings: {
        // ...existing fields
        timestamp_timezone: ImportTimestampTimezone
    }
}

```

**File:** `frontend/src/lib/api/metering.ts`

```typescript
export type UploadMeteringFilePayload = {
    // ...existing fields
    timestampTimezone?: ImportTimestampTimezone
}

export type PreviewCsvImportPayload = {
    // ...existing fields
    timestampTimezone?: ImportTimestampTimezone
}
```

The bulk-delete response type's `timezone` becomes `'Europe/Zurich'`.

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Operators regenerate drafts before re-anchoring legacy CSV data, so readings bill 1–2 h late | High | Release notes lead with the step; `reanchor_readings --list` makes the affected batches visible; the readiness cockpit already flags draft regeneration |
| A legacy batch actually had offsets and gets re-anchored | High | Command is opt-in per batch with a dry run showing the first/last target instants; the protocol modal shows the batch's zone |
| A day assumed to be 24 h / 96 intervals somewhere not listed in §4.3 | Medium | `day_length` helper; DST-day tests for every changed module (§9); review rule: no `timedelta(days=1)` added to an instant |
| Chart consumers read bucket strings as UTC dates | Medium | Buckets carry offsets (§5.1); frontend formats via `zonedParts`; MCP tools consume the same endpoints and return dates only |
| Hourly chart on the autumn DST day shows 02:00 twice | Low | Intended: two distinct hours. Tooltip uses the full date-time label |
| Frontend constant drifts from `settings.TIME_ZONE` | Low | Unit test pins both to `Europe/Zurich` |
| Existing tests hard-code UTC-midnight boundaries | Medium | Updated in the same PR; readings at 12:00Z in fixtures are unaffected |

## 9. Test plan

### Backend — `tariffs/test_band_timezone.py`

**`BandsResolveInSwissLocalTimeTests`** (5 tests, written before the fix and failing then):

| Test | Asserts |
|---|---|
| `test_summer_morning_after_six_is_ht` | 06:30 CEST (04:30Z) resolves to HT |
| `test_summer_evening_after_ten_is_nt` | 22:30 CEST (20:30Z) resolves to NT |
| `test_winter_morning_after_six_is_ht` | 06:30 CET (05:30Z) resolves to HT |
| `test_weekday_is_the_swiss_one` | Saturday 00:30 CET (Friday 23:30Z) resolves to the weekend band |
| `test_month_is_the_swiss_one` | 1 April 00:30 CEST (31 March 22:30Z) resolves to the summer band |

### Backend — `allocation/test_civil_time.py`

**`CivilTimeHelperTests`** (6 tests):

| Test | Asserts |
|---|---|
| `test_period_start_is_local_midnight_in_winter_and_summer` | `period_start_dt(2026-01-15)` = 2026-01-14T23:00Z; `(2026-07-15)` = 2026-07-14T22:00Z |
| `test_dst_days_are_23_and_25_hours` | `day_length` of 2026-03-29 = 23 h, 2026-10-25 = 25 h, 2026-06-01 = 24 h |
| `test_period_window_spans_whole_local_month` | January window = [2025-12-31T23:00Z, 2026-01-31T23:00Z) |
| `test_civil_date_near_midnight` | 21:45Z on 30 June → 30 June; 22:30Z → 1 July |
| `test_civil_date_rejects_naive` | Naive datetime raises `ValueError` |
| `test_wall_clock_converts_aware_and_keeps_naive` | 04:30Z in July → hour 6; a naive value is returned unchanged |

### Backend — `invoices/test_civil_time_billing.py`

5 module-level pytest tests:

| Test | Asserts |
|---|---|
| `test_reading_before_local_midnight_bills_in_previous_month` | 2026-01-31T22:45Z (23:45 CET) is in January's invoice, 23:00Z in February's |
| `test_ht_nt_split_for_sdat_day` | 24 hourly instants over the Swiss day 1 July bill 16 h at HT and 8 h at NT (CHF 5.60) |
| `test_move_out_applies_at_local_midnight` | Assignment ending 2026-06-30: 21:45Z stays with the leaver, 22:15Z goes to the next holder |
| `test_dynamic_price_matches_offsetless_csv_reading` | CSV `2026-07-01 12:00` (Zurich) is stored at 10:00Z and priced with the 12:00+02:00 interval |
| `test_mixed_sdat_and_csv_allocate_on_same_instant` | SDAT production at 12:00+02:00 and Zurich-read CSV consumption at 12:00 share one timestamp and the consumption is covered locally |

### Backend — `metering/test_import_timezone.py`

**`ImportTimezoneTests`** (18 tests): `test_csv_offsetless_default_is_zurich`,
`test_csv_utc_option_keeps_legacy_behaviour`,
`test_csv_offset_ignores_timezone_setting`,
`test_csv_autumn_hour_imports_both_occurrences`,
`test_csv_autumn_hour_is_per_direction`,
`test_csv_spring_hour_zero_rows_skipped_with_warning`,
`test_csv_spring_hour_nonzero_row_errors`,
`test_preview_counts_spring_gap_rows_instead_of_reporting_errors`,
`test_invalid_timestamp_timezone_rejected`,
`test_daily_profile_starts_at_swiss_midnight`,
`test_daily_profile_utc_option_starts_at_utc_midnight`,
`test_daily_profile_dst_start_accepts_92_of_96_with_empty_missing_hour`,
`test_daily_profile_dst_start_accepts_trailing_empty_columns`,
`test_daily_profile_dst_start_rejects_96_filled_values`,
`test_daily_profile_dst_end_requires_100`,
`test_daily_profile_dst_end_imports_100_values`,
`test_daily_profile_100_columns_on_an_ordinary_day_drops_trailing_empties`,
`test_daily_profile_existing_check_uses_the_civil_day` — the rules of §5.4 and §6.1.

**`SdatTimestampTests`** (2 tests):
`test_sdat_offsetless_timestamp_is_zurich_whatever_the_process_tz` (with
`TZ=America/New_York`), `test_sdat_offsets_are_kept`.

### Backend — `metering/test_reanchor_readings.py`

12 module-level pytest tests: `test_list_shows_only_legacy_csv_batches`,
`test_dry_run_writes_nothing`, `test_apply_moves_winter_and_summer_readings`,
`test_apply_marks_batch_and_second_run_is_refused`,
`test_sdat_batch_is_refused`, `test_collision_outside_batch_refuses_batch`,
`test_zero_energy_spring_gap_reading_is_dropped`,
`test_nonexistent_spring_time_with_energy_refuses_batch`,
`test_invoiced_period_requires_allow_invoiced`,
`test_apply_records_audit_event`,
`test_adjacent_batches_are_planned_together`,
`test_selecting_only_the_later_batch_collides_with_the_earlier_one` — §6.3.

### Backend — updated tests

Tests that encoded UTC days or hours now express the same intent in Swiss time:

- `invoices/test_pdf.py`: `test_hourly_profile_buckets_by_stored_hour_not_localtime`
  → `test_hourly_profile_buckets_by_swiss_hour`;
  `test_period_window_uses_utc_not_local_tz` → `test_period_window_uses_swiss_civil_days`.
- `allocation/tests.py`: shared `TS` is Zurich-aware;
  `test_matching_uses_the_utc_civil_date_of_the_timestamp` →
  `test_matching_uses_the_swiss_civil_date_of_the_timestamp`.
- `metering/tests.py`: `DashboardUtcBucketingTests` → `DashboardCivilDayBucketingTests`
  (`test_late_evening_reading_stays_in_its_civil_day_bucket`);
  `test_daily_bucket_uses_the_same_civil_day_as_raw_data`,
  `test_month_bucket_does_not_cross_the_civil_month_boundary`.
- `metering/test_import_csv_characterization.py`: `test_naive_timestamp_is_read_as_swiss_time`,
  `test_date_only_timestamp_becomes_swiss_midnight`,
  `test_standard_profile_with_timestamp_format_reads_swiss_time`,
  `test_xlsx_native_datetime_cell_is_read_as_swiss_time`, plus Zurich
  expectations in the daily-profile and xlsx tests.
- `invoices/test_dynamic_evidence.py`: `test_tariff_evidence_guard_uses_utc_billing_days_not_local_history_days`
  → `test_tariff_evidence_guard_uses_civil_billing_days`.
- `invoices/test_dynamic_tariff_pricing.py`: a BFE quarter ending at Swiss
  midnight now reports `reference_to` 30 June (previously 29 June).
- Fixtures moved to Zurich-aware timestamps in `metering/test_reading_visibility.py`,
  `metering/test_import_csv.py` (daily-profile tests), `invoices/test_engine_pricing.py`,
  `invoices/test_engine_band_itemisation.py`, `invoices/test_readiness.py`
  (dynamic coverage series), `tariffs/test_dynamic_fetch.py`,
  `mcp_server/tests/test_tools.py` and `zev/tests.py` (seed-demo history).
- `metering/test_import_logs.py`: the daily-profile overwrite fixture declares
  `timestamp_timezone=UTC`, since its seeded reading sits at UTC midnight.

### Frontend

- `tests/date-utils.test.ts` (under `TZ=America/New_York`): `BUSINESS_TIME_ZONE`,
  `zonedParts` in winter and summer, `businessDayStartMs` on ordinary and both
  DST days, `nextIsoDate` across month and year ends, `todayBusinessIso`.
- `tests/metering-labels.test.ts` (under `TZ=America/New_York`): day and month
  buckets with offsets label as the Swiss day/month; UTC hour buckets label as
  the Swiss hour; both 02:00 hours of the autumn change label 02:00.
- `tests/metering-chart-page-period.test.ts`: first/last reading dates in Swiss time.
- `tests/import-warning-modals.test.ts`: the ZEV archive's export time shows as Swiss time under `TZ=America/New_York`.
- `tests/imports-wizard.test.ts`: detection prefill carries `timestampTimezone`;
  the select defaults to `Europe/Zurich` and a changed zone is sent with the preview.
- `npm run lint`, `npm run lint:style`, `node ../scripts/check-frontend-hex.mjs`,
  `npm run test:unit`, `npm run build`.

### Acceptance criteria

- [ ] All five tests in `tariffs/test_band_timezone.py` pass.
- [ ] No reading-timestamp civil date or hour is derived outside
      `allocation.validity` (grep for `.astimezone(`, `.date()` and `.hour` on
      timestamps in the §4.3 modules returns only helper calls).
- [ ] An SDAT file and the same data as an offset-less CSV (Zurich) produce
      identical stored timestamps and identical invoices.
- [ ] A January invoice covers exactly [2025-12-31T23:00Z, 2026-01-31T23:00Z).
- [ ] Importing a Zurich-time CSV spanning both 2026 DST changes produces no
      duplicate errors and no data gaps.
- [ ] `reanchor_readings` dry run and apply behave as §6.3 on a copy of the demo
      data.
- [ ] Charts, raw table, PDFs and the MCP hourly profile show the solar peak
      around 13:00 in summer for seeded demo data.
- [ ] Frontend shows the same times with the browser set to `America/New_York`.

## 10. Documentation updates in the same PR

| Document | Sections |
|---|---|
| `docs/specs/2026-03-metering-import-and-quality.md` | §4.1 `MeterReading.timestamp`, import settings table (timestamp row), timestamp normalisation list, daily-profile anchoring, participant scoping `TruncDate`, bucket boundaries, §7 timezone section, bulk delete (`timezone` response), risks row, tests |
| `docs/specs/2026-03-tariffs-and-billing-engine.md` | §3.2 period matching rules (wall clock), reading windows table (`period_start 00:00 Europe/Zurich`), assignment matching (`civil_date`), worked example timestamps, tests |
| `docs/specs/2026-03-metering-point-management.md` | delete-readings date semantics, assignment matching paragraph |
| `docs/specs/2026-03-invoice-lifecycle-and-communication.md` | assignment-on-reading-date sentence |
| `docs/specs/2026-09-dynamic-tariffs.md` | civil-day windows, `local_civil_day_window` removal, transport-buffer paragraph |
| `docs/specs/2026-09-bfe-reference-market-price.md` | note that local month starts now align with billing periods |
| `docs/specs/2026-09-mcp-server.md` | hourly/day buckets are Swiss civil time |
| `docs/user-guide/05-metering-import.md` | "Timestamp Handling" rewritten: timezone setting, DST rules, re-anchoring legacy batches |
| `docs/user-guide/06-metering-analysis.md` | days and hours are Swiss time |
| `docs/user-guide/15-glossary.md` | **Timezone** entry |
| Tariff chapter of the user guide | band hours are Swiss time for every import source |
