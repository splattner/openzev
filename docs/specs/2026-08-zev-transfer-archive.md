# Baseline Spec: ZEV Transfer Archive

- Spec ID: SPEC-2026-08-zev-transfer-archive
- Status: Approved
- Scope: Major
- Type: Feature
- Owners: splattner
- Created: 2026-08-05
- Target Release: post-#410
- Related Issues: PR #410
- Related ADRs: none
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

A community (ZEV) must be movable between OpenZEV instances as one self-contained
archive: its settings, participants, metering points and assignments, tariffs,
meter readings, and billing history. The previous tariff-only JSON transfer is
replaced — an export with only the Tariffs section selected does what it used to
do. An import always creates a **new** ZEV with new internal identifiers; it is a
copy, not an in-place restore (see `docs/user-guide/17-zev-transfer.md`).

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Backend | Archive format (manifest, JSON sections, readings CSVs), export builder, import runner, section dependency graph, manifest count verification, audit events, endpoint trio |
| Frontend | Export/import dialogs with section picker, transfer-sections query, structure-only export default |
| Docs | User guide chapter 17, this baseline spec |

### Out of scope

- SHA-256 per-member checksums in the manifest (decided: not needed — CRC32 is
  validated by the ZIP container itself).
- In-place restore; audit events / import logs do not travel.
- Account references (`owner`, participant `user` link) — never exported.
- Generated invoice PDFs — regenerable, deliberately not archived.
- Email/PDF templates from the admin console (instance-wide, not ZEV data).

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | `import-archive` (creates a ZEV — admin-only), `inspect-archive` |
| `zev_owner` | `transfer-sections`, `export` on owned ZEVs only (ZEV-scoped queryset) |
| `participant` | nothing — neither endpoint is exposed to participants |

Backend: `ZevViewSet` in `backend/zev/views.py` has `permission_classes =
[IsAuthenticated, ZevManagementPermission]`. `export_archive` is a detail action
so `get_object()` scopes it via `ZevScopedQuerySetMixin` — an admin exports any
ZEV, an owner only their own. `import_archive_action` and
`inspect_archive_action` are POST actions, which `ZevManagementPermission`
restricts to admins — the same rule as `create()`. Frontend shows the transfer
UI under ProtectedRoute roles `admin` / `zev_owner` on `ZevSettingsPage.tsx`.

## 4. Data model

No new models or migrations. The archive reads and writes existing models:
`zev.models.Zev`, `zev.models.Participant`, `zev.models.MeteringPoint`,
`zev.models.MeteringPointAssignment`, `tariffs.models.Tariff`,
`tariffs.models.TariffPeriod`, `invoices.models.Invoice`,
`invoices.models.InvoiceItem`, `metering.models.MeterReading`.

Relevant constraints the import must respect:

- `MeteringPoint.meter_id` is `unique=True` **instance-wide** — the most common
  rejection (importing a community back into the instance it came from).
- `MeterReading` has `UniqueConstraint(fields=["metering_point", "timestamp",
  "direction"])` and `energy_kwh = DecimalField(max_digits=12, decimal_places=4)`
  — both enforced at the DB level; the importer converts violations into
  per-row errors instead of letting them crash the batch.
- `Invoice` has `UniqueConstraint(fields=["zev", "invoice_number"])`; the
  imported ZEV's `invoice_counter` is pushed past the highest imported number.
- `Tariff.save()` runs `full_clean()` (overlap/series validation).

### Import logging

Meter readings imported through the archive are recorded via
`metering`'s import-log mechanism (same plumbing as the CSV importer): a
successful archive import with readings creates an import log entry, asserted by
`test_readings_are_recorded_as_an_import_log`.

## 5. API contracts

All under `ZevViewSet` (`/api/v1/zevs/...`):

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `GET /api/v1/zevs/transfer-sections/` | GET | any authenticated | `{"sections": [{"name": str, "requires": [str]}]}` — the section list and dependency graph, ordered as `SECTIONS`. Served so the rule lives in one place. |
| `GET /api/v1/zevs/{pk}/export/?sections=zev,participants,...` | GET | ZEV owner / admin | Builds the archive into a `SpooledTemporaryFile(max_size=8 MiB)`, returns it as `FileResponse` (`application/zip`, `as_attachment`, filename from `archive_filename(zev, today)` in `export.py`: `openzev-export-<community>-<date>.zip`). `sections` query param is a comma-separated list; absent = all sections. Errors (`ValueError` from `build_archive`) → 400 `{"detail": str}` with a FAILED audit event. |
| `POST /api/v1/zevs/inspect-archive/` | POST multipart | admin | Reads the manifest only (`inspect_archive`); `ArchiveError`/`ValueError` → 400. Creates nothing. |
| `POST /api/v1/zevs/import-archive/` | POST multipart | admin | Fields: `file` (required, else 400 `{"detail": "A ZIP archive is required."}`), `sections` (repeated form field, comma-separated values, or absent = all), `name` (optional override). On failure: 400 with `{"detail", "errors", "total_errors"}` (ImportFailed) or `{"detail"}` (ArchiveError/ValueError) plus a FAILED audit event. On success: 201 with `{"zev_id", "zev_name", "sections", "counts"}` and a SUCCESS audit event. |

All audit events via `_record_transfer_audit(request, **kwargs)`: a try/except
wrapper that logs `logger.exception` and never lets an audit failure fail the
operation (export audit fires before the streamed response, import audit after
commit — a failed audit must not cause a duplicate import on client retry).

## 6. Archive format (`backend/zev/transfer/schema.py`)

`FORMAT_VERSION = 1`, `SUPPORTED_FORMAT_VERSIONS = {1}` — a version this instance
does not read is refused outright (`ArchiveError`, a `ValueError` subclass).

Sections (order = write and import order, a correctness constraint):

```python
SECTIONS = ("zev", "participants", "metering_points", "tariffs", "readings", "invoices")
SECTION_DEPENDENCIES = {
    "zev": (),
    "participants": (),
    "metering_points": ("participants",),   # assignments point at participants
    "tariffs": (),
    "readings": ("metering_points",),
    "invoices": ("participants",),          # deliberately NOT tariffs
}
```

File layout:

```
openzev-export-<community>-<date>.zip
  manifest.json          format_version, exported_at, instance_name, sections, counts
  zev.json               {"id", <ZEV_FIELDS>}  (a single object, not a list)
  participants.json      [{"id", <PARTICIPANT_FIELDS>}]
  metering_points.json   [{"id", <METERING_POINT_FIELDS>,
                           "assignments": [{"id", "participant_id", <ASSIGNMENT_FIELDS>}]}]
  tariffs.json           [{"id", <TARIFF_FIELDS>,
                           "periods": [{"id", <TARIFF_PERIOD_FIELDS>}]}]
  invoices.json          [{"id", "participant_id", <INVOICE_FIELDS>,
                           "items": [{"id", <INVOICE_ITEM_FIELDS>}]}]
  readings/<meter>.csv   one file per meter
```

Field lists (`ZEV_FIELDS`, `PARTICIPANT_FIELDS`, `METERING_POINT_FIELDS`,
`ASSIGNMENT_FIELDS`, `TARIFF_FIELDS`, `TARIFF_PERIOD_FIELDS`, `INVOICE_FIELDS`,
`INVOICE_ITEM_FIELDS`) are hand-written in `schema.py` — a file format with a
version, not a mirror of the serializers. `owner` (Zev) and `user` (Participant)
are absent by design; imported participants arrive unlinked. `pdf_file` is absent
from `INVOICE_FIELDS`. `READING_CSV_COLUMNS = ("meter_id", "timestamp",
"energy_kwh", "direction", "resolution", "import_source")` — the same layout the
normal CSV metering import reads, plus `resolution`/`import_source` so nothing is
lost in a round trip.

**Reading member names**: `readings/<sanitised>-<digest>.csv` where `<sanitised>`
is the meter id with anything outside `[A-Za-z0-9_.-]` replaced by `_`, and
`<digest>` is `sha1(meter_id)[:8]`. The digest is what makes two meter ids that
sanitise to the same name (e.g. `A/B` and `A_B`) still get separate members — a
collision would otherwise silently merge one meter's readings into the other's
file (ZIP resolves duplicate member names to the last writer).

**Counts and verification**: the manifest's `counts` carry, per section, the
number of entries written (for readings: rows across all CSVs; for
`metering_points`: the point count *and* `assignments`). `counts` is
**required**: `read_manifest` rejects an archive without it, with a value that
is not a non-negative integer, or that fails to record a count for every declared
section except `zev` (the settings section is a single object and carries no
count). `source_zev` must also be an object when present. On import,
`_verify_manifest_counts` compares each imported section's produced count
against the manifest; a mismatch is a hard rejection (the archive is corrupt or
inconsistent), except that a section that already has per-entry errors is not
re-checked — the errors speak for themselves.

## 7. Export behavior (`backend/zev/transfer/export.py`)

`build_archive(zev, sections, fileobj, *, instance_name="")`:

1. `normalise_sections(sections)` + `check_dependencies(sections)` — an
   incomplete selection fails before writing (raised as `ValueError`).
2. Wraps `_write_archive` in `transaction.atomic(durable=True)`, and — when
   `connection.vendor == "postgresql"` — first executes
   `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ` inside that transaction.
   Why: sections are read at different moments (readings can stream for
   minutes); READ COMMITTED (what `atomic()` alone buys on PostgreSQL) would
   let a concurrent edit leave an archive that never existed as a state, with
   manifest counts disagreeing with the CSVs. `durable=True` makes the block
   the outermost transaction: called inside an existing transaction it fails
   loudly with a `RuntimeError` instead of degrading to a savepoint where
   `SET TRANSACTION ISOLATION LEVEL` would raise Postgres 25001. The `vendor`
   guard keeps the SQLite test suite green (SQLite transactions are already
   serialised). The export endpoint also holds everything in
   `SpooledTemporaryFile(8 MiB)` so structure-only exports never touch the
   disk.
3. Writes members in `SECTIONS` order, manifest last (its counts are the ones
   actually produced; ZIP central directories are order-independent).
4. `_export_tariffs` uses `Prefetch("periods", queryset=TariffPeriod.objects
   .order_by("period_type", "id"))` — a plain `prefetch_related("periods")` is
   defeated by the per-tariff `order_by` in the loop, so the Prefetch pins the
   ordering and avoids one query per tariff (N+1).

Reading export streams `queryset.iterator()` in `_write_readings`, chunked rows
of `READING_CSV_COLUMNS`, one member per meter (header-only file when a meter
has no readings).

## 8. Import behavior (`backend/zev/transfer/importer.py`)

- `open_archive` → `read_manifest` (member read through `_read_member`, which
  turns `BadZipFile`/CRC failures into `ArchiveError` instead of a 500), then
  `check_format_version`, then per-section `_load_json`.
- The whole import runs in one transaction — nothing is created unless
  everything validates. Failures are collected in a `_Collector` (the first
  `MAX_REPORTED_ERRORS = 50` stored, the true total counted alongside) and
  raised as `ImportFailed(errors, total_errors=...)`; the response lists every
  problem by section, entry and reason.
- `_preflight_meter_ids` rejects meter ids already on the instance, by name,
  before any creation.
- `read_manifest` validates the manifest structure up front: `counts` (dict of
  non-negative integers covering every declared section except `zev`) and
  `source_zev` (object when present) are each type-checked, so a malformed
  value is a readable `ArchiveError` (400), never an unhandled `AttributeError`
  (500).
- A non-object entry inside a point's `assignments` (e.g. `[null]` or a string)
  raises `ArchiveError` rather than crashing on `raw.get(...)`.
- Duplicate participant source ids are rejected (reported per entry) instead of
  silently rewiring every assignment and invoice to the last match.
- Duplicate invoice numbers — invisible to `full_clean(exclude=["zev", ...])`
  because the `(zev, invoice_number)` constraint spans the excluded `zev` — are
  caught at `save()` as an `IntegrityError` and reported per entry.
- Readings (`_import_readings`, batches of `READING_BATCH_SIZE = 2000` via
  `_bulk_create_readings`): duplicate rows — including duplicates spanning two
  CSV members — are rejected by name; a bad `direction`/`resolution`/`source`
  names the row and line; energy values beyond the column width
  (`MAX_ENERGY_KWH = Decimal("99999999.9999")`; rounding to 4 dp must stay
  within `max_digits=12`) are rejected per row rather than crashing the batch;
  unreadable members (`BadZipFile`, `UnicodeDecodeError`, `csv.Error` — e.g. a
  corrupt CRC or binary garbage) are reported as one "Unreadable readings file"
  error instead of a 500; a batch the database itself rejects (a future
  constraint, a value overflowing a column) is reported with a generic
  sentence — "The database rejected a batch of readings; the batch was
  skipped" — and the exception detail goes to the server log, never the
  response.
- `_import_invoices` returns the highest numeric tail (`_trailing_number`) of
  imported invoice numbers; the ZEV counter is set past it.
- The importing admin becomes `owner` of the new ZEV; `name_override` renames it.

## 9. Frontend

### `frontend/src/features/zev/ZevExportModal.tsx`

- Export button opens `TransferSectionPicker` bound to `selected`
  (`useState<TransferSectionName[]>(INITIAL_SELECTION)`). The modal stays
  mounted while closed, so `selected` is reset back to the structure-only
  default on every open (a `useEffect` keyed on `isOpen`).
- `INITIAL_SELECTION = ['zev', 'participants', 'metering_points', 'tariffs']` —
  **structure-only by default**; readings and invoices are the bulk of a zip
  (and readings alone can stream for minutes), so opting into data sections is
  deliberate. All boxes still selectable via `toggleSection` (which pulls
  prerequisites in and drops dependents, `frontend/src/features/zev/
  transferSections.ts`).
- `exportZevArchive(zevId, selected)` → blob download
  `t('zevTransfer.exportSuccess')` toast; 400 bodies arrive as blobs and are
  read with `readBlobError`.

### `frontend/src/features/zev/ZevImportModal.tsx`

- Uploads the zip, calls `inspect-archive` first, shows per-section row counts
  and a name field, then submits `import-archive` with the chosen sections;
  per-entry errors are listed from the response body.

### Types and API client

- No `frontend/src/types/api.ts` changes: the transfer endpoints consume
  `FormData` and return shapes typed inside the modal files / `zevTransfer.ts`.
- `frontend/src/lib/api/zevTransfer.ts`: `fetchTransferSections`,
  `exportZevArchive`, `inspectArchive`, `importZevArchive`.

## 10. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Large exports hold the request open / use memory | Medium | `SpooledTemporaryFile(8 MiB)` spills to disk; builder streams readings; offloading to a task + artefact URL is a documented future option |
| Concurrent edits during a long export | Medium | Repeatable-read transaction on PostgreSQL; manifest counts written last and verified on import |
| A long repeatable-read snapshot pins a connection and delays vacuum cleanup at the 2M-row scale | Low | Export is admin-triggered and bounded by the request; moving it to a Celery task with an artefact URL is the documented future option |
| Corrupt/foreign archives cause 500s | Medium | `_read_member` maps ZIP/CRC failures to `ArchiveError`; per-member and per-row handling in readings; manifest count verification rejects inconsistent archives |
| N+1 tariff-period queries on export | Low | `Prefetch` pins ordering, one query |
| Format drift vs models | Medium | `SchemaParityTests` equality test with maintained `FIELDS_EXCLUDED_FROM_ARCHIVE` set |

## 11. Test plan

### Backend — `backend/zev/test_transfer.py`

**`SectionDependencyTests`**: readings require metering points, assignments
require participants, complete selections have no gaps, export refuses
incomplete selections, and export refuses to run inside an outer transaction
(the `durable=True` guard).

**`ArchiveShapeTests`**: manifest + one CSV per meter; manifest keeps source
ids; no account reference travels; one-section exports leave the others out; a
meter id with a path separator cannot escape `readings/`
(`test_a_meter_id_with_a_path_separator_cannot_escape_the_readings_folder`);
collision-safe member names (`test_two_meter_ids_that_sanitise_to_one_name_
still_get_separate_members`).

**`RoundTripTests`**: every section arrives; assignments follow the right
participant; participants arrive unlinked; readings keep resolution and values;
tariff periods round-trip; invoice items travel but PDFs do not; the counter is
pushed past imported numbering; readings are recorded as an import log;
importing twice collides on meter ids; a structure-only archive can be imported
twice; a subset can be imported from a full archive; a name override renames the
imported ZEV; a structure-only archive still names the ZEV.

**`RejectedArchiveTests`**: non-zip refused; missing manifest refused;
unknown format version fails loudly; manifest promising a missing file refused;
absent sections cannot be selected; colliding meter id reported by name; nothing
created when any entry fails; every bad entry reported in one response;
assignment pointing at nothing reported; bad reading row names its line;
duplicated reading named rather than crashing the batch; readings file missing a
column reported once per file; corrupt manifest refused cleanly; corrupt
readings member reported, not crashed; binary-garbage member reported once;
energy beyond the column width rejected by row; duplicate across two members
rejected; archive with readings missing from the zip rejected; error list capped
at 50 but the total is not; non-object assignment refused, not a crash;
duplicate invoice numbers reported, not a crash; manifest missing counts
refused; manifest with a non-integer count refused; manifest missing a count
for a declared section refused; manifest with a non-object
`source_zev` refused; duplicate participant source ids rejected.

**`SchemaParityTests`**: `test_field_lists_match_their_models_exactly` —
`assertEqual(set(<section fields>), {model._meta.fields names} -
FIELDS_EXCLUDED_FROM_ARCHIVE[section])` for all eight section/model pairs
(exclusions: `id`, `owner`, `user`, `zev`/parent FKs, `created_at`,
`updated_at`, `pdf_file`); `test_reading_csv_columns_exist_on_the_reading_model`.

**`TransferEndpointTests`**: owner can export own ZEV; owner cannot export
another's; section selection accepted; incomplete selection rejected with a
reason; unknown section rejected; dependency graph served; admin can import;
zev_owner cannot import; import reports every failure in the body; import
without a file says so; import accepts repeated-sections fields; export accepts
repeated-sections query params; inspect returns the manifest without creating
anything; inspect refuses a non-archive.

### Frontend

- Build and type checks: `npm run build`
- Unit tests: `npm run test:unit`

### Acceptance criteria

- [x] All transfer tests pass; full backend suite green; ruff clean on changed files
- [x] Frontend `npm run build` and `npm run test:unit` green
- [x] Collision-safe reading member names verified by test
- [x] Corrupt archives yield 400s with readable errors, never 500s
- [x] Manifest counts verified on import
- [x] Export default is structure-only in the UI
