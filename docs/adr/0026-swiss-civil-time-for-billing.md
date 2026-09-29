# ADR 0026: Readings are UTC instants; every calendar question is answered in Swiss civil time

- Status: Proposed
- Date: 2026-09-29
- Supersedes: ADR 0007

## Context

ADR 0007 stores metering timestamps in UTC and builds every period and date
filter from UTC midnights. That settled *how instants are stored*, but it also
made "UTC" the answer to a different question: *which day, hour, weekday and
month does a reading belong to?* Over time the code answered that question on
the UTC components of the stored timestamp everywhere:

- tariff bands (`tariffs.periods.resolve_band`) read `ts.time()`,
  `ts.weekday()` and `ts.month` from the UTC-aware datetime the ORM returns;
- billing periods, assignment validity and tariff validity key on the UTC date
  (`allocation.validity.period_window`, `invoices.engine._utc_date`,
  `allocation.windows`);
- charts, the hourly profile, PDF statistics and the annual statement bucket by
  UTC day and hour, and the frontend formats those buckets with UTC getters
  (`frontend/src/lib/meteringLabels.ts`).

At the same time, the CSV/Excel importer stamps offset-less timestamps as UTC.
Swiss sources almost always export Swiss local time without an offset, so for
that data the UTC components *are* the Swiss wall clock and the rules above
happen to give the right answer. A test says as much ("Readings are stored as
wall-clock UTC", `invoices/test_pdf.py`). For data that carries an offset —
every SDAT-CH file, and CSV files with `+01:00`/`+02:00` — the stored instant is
correct, and the same rules are then wrong by one hour in winter and two in
summer.

The code therefore holds two meanings for one column, and the places that meet
across them produce wrong invoices:

- **HT/NT and weekday/season bands** are shifted for offset-carrying data: an
  SDAT reading at 06:30 Swiss summer time bills at NT, 22:30 bills at HT, and
  Saturday 00:30 is treated as Friday (`tariffs/test_band_timezone.py`).
- **Dynamic prices** (VSE v1/v2, BFE reference market price) are true instants.
  Offset-less CSV readings are matched to the price 1–2 hours later than the
  moment they were measured.
- **Local allocation** matches production and consumption per timestamp. A ZEV
  that imports SDAT for one meter and offset-less CSV for another has the two
  series 1–2 hours apart.
- **Period boundaries** are UTC midnight. With SDAT data a January invoice holds
  the last hour of 31 December and misses the last hour of 31 January; move-in,
  move-out and tariff changes take effect an hour or two off.

Everything a user or a grid operator names — a billing month, a tariff band, a
move-in date, a day on a chart — is Swiss civil time. The grid operator bills on
Swiss local days, and SDAT-CH files cover Swiss local days.

## Decision

Separate the two questions ADR 0007 merged.

- **Storage stays UTC.** `MeterReading.timestamp`, dynamic price intervals,
  evidence windows and every other `DateTimeField` hold real instants in UTC,
  exactly as today. Nothing changes in the schema for this.
- **Every calendar question is answered in the business timezone,
  `Europe/Zurich`** (`settings.TIME_ZONE`): the civil date of a reading, the
  hour and weekday a tariff band is matched on, the month a seasonal band is
  matched on, the bounds of a billing period, the day and month a chart bucket
  belongs to, and the day a `created_at` filter selects. One helper module,
  `allocation.validity`, is the single place that converts between the two, and
  no other code builds day bounds or civil dates by hand.
- **A civil date's bounds are local midnights.** A period `[start, end]` covers
  `[start 00:00 Europe/Zurich, end+1 00:00 Europe/Zurich)`, converted to UTC for
  the query. Days are 23, 24 or 25 hours long; nothing may assume 24 hours or
  96 quarter-hours per day.
- **Hour buckets keep UTC truncation.** Zurich's offset is a whole number of
  hours, so UTC hour boundaries are local hour boundaries, and truncating in UTC
  keeps the two 02:00 hours of the autumn DST change apart. Day and month
  buckets truncate in `Europe/Zurich`. All buckets are labelled in
  `Europe/Zurich`.
- **Offset-less import timestamps are read in a declared zone.** The CSV/Excel
  import gets a timezone setting, `Europe/Zurich` by default, with `UTC` for the
  sources that really export UTC without an offset. Timestamps with an offset
  ignore it. The daylight-saving edge cases (the repeated autumn hour, the
  missing spring hour, 92/100-interval days in daily profiles) follow explicit
  rules instead of failing as duplicates or gaps. An offset-less SDAT-CH
  timestamp is read as `Europe/Zurich` explicitly, not through the process
  timezone.
- **Existing data is not moved automatically.** Readings imported from
  offset-less files before this change are stored as "Swiss wall clock labelled
  UTC", and the database does not record which CSV imports had offsets. An
  opt-in management command re-anchors selected import batches, with a dry run,
  and marks each batch so it can never be shifted twice.
- **The frontend displays instants in `Europe/Zurich`,** not the viewer's
  browser zone, so what a user abroad sees matches the invoice. Date-only values
  (`YYYY-MM-DD`) stay timezone-free strings, as today.

The implementation is specified in
[`docs/specs/2026-09-swiss-civil-time.md`](../specs/2026-09-swiss-civil-time.md).

## Consequences

Positive:
- HT/NT, weekday and seasonal bands bill the hour the tariff sheet means, for
  every import source.
- Dynamic prices, allocation and billing periods agree on one timeline whatever
  mix of SDAT and CSV a ZEV imports.
- Invoice periods, charts and completeness reports use the same days as the grid
  operator and the user.
- Importing Swiss local-time files no longer turns every DST weekend into
  duplicate errors and data gaps.

Trade-offs:
- It is a cross-cutting change touching the engine, allocation, readiness,
  analytics, PDFs, importers and the frontend at once. Doing only part of it
  moves the inconsistency rather than removing it: converting only the band
  lookup to local time would break HT/NT for existing offset-less CSV data,
  which bills correctly today by accident.
- Draft invoices regenerated after the release can differ from before; issued
  invoices are frozen and stay as they are. Operators with offset-less CSV
  history must run the re-anchor command before regenerating drafts, or those
  readings bill an hour or two late.
- Code must never use naive "one day = 24 h" arithmetic on instants, and
  `__date` lookups still convert with the connection timezone — both need care
  in review.
- The business timezone is a single fixed zone for the whole installation. A
  ZEV outside Switzerland is not supported by this decision.

## Alternatives considered

1. Keep ADR 0007 and make offset-less imports "Swiss wall clock labelled UTC"
   explicitly (floating local time).
   - Makes offset-less CSV and bands consistent, but every true instant (SDAT,
     offset-carrying CSV, dynamic prices, BFE prices, `created_at`) would need
     converting *into* the fake timeline, the autumn DST hour cannot be
     represented at all, and the stored values stop being instants. Rejected.
2. Convert only `resolve_band` to local time.
   - Fixes HT/NT for SDAT but breaks it for existing offset-less CSV data and
     leaves periods, allocation across sources and dynamic prices misaligned.
     Rejected as a partial fix.
3. Automatically shift every CSV-sourced reading in a data migration.
   - Wrong for the CSV files that did carry offsets, which the database cannot
     tell apart, and not reversible afterwards. Rejected in favour of an opt-in,
     per-batch command.
4. Store readings in local time.
   - Rejected for the reasons ADR 0007 gave: ambiguous autumn hour, and every
     external source already speaks in instants.

## Notes

- ADR 0007's rule "never use `timestamp__date__` lookups" still holds; the
  reason is now that they depend on the connection timezone instead of the
  explicit helper.
- ADR 0013 (shared allocation service) and ADR 0019 (frozen dynamic price
  evidence) are unaffected in structure. Evidence rows written before the change
  keep their UTC-midnight windows; they remain valid protected ranges.
