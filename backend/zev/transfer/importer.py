"""Import a transfer archive as a new ZEV.

Two rules shape everything here.

**Import always creates a new ZEV with new ids.** It therefore cannot overwrite
or collide with live billing data by construction, which is what makes the
feature safe to hand to a ZEV owner rather than admins only. The price is that
this is a *copy*, not a restore: anything holding an old id — audit events,
external references, bookmarked URLs — does not follow. The manifest keeps the
original ids so an in-place restore stays available as a later feature.

**The whole import is one transaction.** The issue asked for all-or-nothing per
section; this goes further because the sections share a ZEV. A tariff section
that failed after participants had been committed would leave a half-populated
community behind that somebody then has to notice and delete. Every failure
from every section is still collected and reported in one response, so an
archive with several problems takes one round trip to diagnose.
"""

import csv
import io
import json
import logging
import uuid
import zipfile
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.conf import settings
from django.db import DataError, IntegrityError, transaction

from invoices.models import Invoice, InvoiceItem
from metering.importers.csv_importer import _parse_datetime_utc, _parse_decimal
from metering.importers.limits import (
    MAX_REPORTED_ERRORS,
    MAX_UPLOAD_BYTES,
    mb,
    reject_unsafe_member_path,
    validate_zip,
)
from metering.models import ImportLog, ImportSource, MeterReading, ReadingDirection, ReadingResolution
from tariffs.models import Tariff, TariffPeriod
from zev.models import MeteringPoint, MeteringPointAssignment, Participant, Zev

logger = logging.getLogger(__name__)

from .schema import (
    ASSIGNMENT_FIELDS,
    INVOICE_FIELDS,
    INVOICE_ITEM_FIELDS,
    MANIFEST_NAME,
    METERING_POINT_FIELDS,
    PARTICIPANT_FIELDS,
    READINGS_DIR,
    SECTION_FILES,
    SECTION_INVOICES,
    SECTION_METERING_POINTS,
    SECTION_PARTICIPANTS,
    SECTION_READINGS,
    SECTION_TARIFFS,
    SECTION_ZEV,
    SECTIONS,
    TARIFF_FIELDS,
    TARIFF_PERIOD_FIELDS,
    ZEV_FIELDS,
    ArchiveError,
    check_dependencies,
    check_format_version,
    normalise_sections,
)

READING_BATCH_SIZE = 2000

# ``MeterReading.energy_kwh`` is a DecimalField(max_digits=12, decimal_places=4):
# the largest representable value is 99999999.9999. ``_parse_decimal`` rounds to
# four decimal places, so 99999999.99995 becomes 100000000.0000 and would fail
# at the database as a DataError — after the whole batch had been submitted.
# The per-row check below has to catch that, not the database.
MAX_ENERGY_KWH = Decimal("99999999.9999")

# A malformed readings file can produce one error per row. The response has to
# stay a response, so the list is capped and the true total reported alongside.

# Upload hardening limits — rationale: docs/specs/2026-03-metering-import-and-quality.md §4.4.
MAX_TRANSFER_DECOMPRESSED_BYTES = getattr(settings, "TRANSFER_MAX_DECOMPRESSED_MB", 500) * 1024 * 1024
MAX_TRANSFER_MEMBERS = 500
MAX_TRANSFER_COMPRESSED_BYTES = MAX_UPLOAD_BYTES
MAX_TRANSFER_RATIO = 500


def open_archive(fileobj):
    """Open a transfer archive, validating limits first.

    Raises ``ArchiveError`` when the file is too large, has too many members,
    exceeds decompressed-size or compression-ratio limits, or contains unsafe
    member paths.
    """
    fileobj.seek(0)
    size_hint = getattr(fileobj, "size", None)
    if size_hint is not None and size_hint > MAX_TRANSFER_COMPRESSED_BYTES:
        raise ArchiveError(
            f"Archive too large ({mb(size_hint)}). Maximum compressed size is {mb(MAX_TRANSFER_COMPRESSED_BYTES)}."
        )
    try:
        zf = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile as exc:
        raise ArchiveError("The uploaded file is not a valid ZIP archive.") from exc
    try:
        infos = validate_zip(
            zf,
            label="Archive",
            max_members=MAX_TRANSFER_MEMBERS,
            max_total_bytes=MAX_TRANSFER_DECOMPRESSED_BYTES,
            max_ratio=MAX_TRANSFER_RATIO,
            error_cls=ArchiveError,
        )
        for info in infos:
            reject_unsafe_member_path(info.filename, error_cls=ArchiveError)
    except BaseException:
        zf.close()
        raise
    return zf


class ImportFailed(Exception):
    """Collected failures; the transaction is rolled back and nothing is created."""

    def __init__(self, errors, *, total_errors=None):
        self.errors = errors
        self.total_errors = total_errors if total_errors is not None else len(errors)
        super().__init__(self.summary)

    @property
    def summary(self):
        shown = len(self.errors)
        if self.total_errors > shown:
            return f"Import rejected: {self.total_errors} problems found (showing the first {shown})."
        return f"Import rejected: {self.total_errors} problem(s) found."


class _Collector:
    """Accumulates per-entry failures, keeping only the first MAX_REPORTED_ERRORS."""

    def __init__(self):
        self.errors = []
        self.total = 0

    def add(self, section, position, label, detail):
        self.total += 1
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(
                {
                    "section": section,
                    "position": position,
                    "label": label,
                    "errors": _normalise(detail),
                }
            )

    def __bool__(self):
        return self.total > 0


def _normalise(detail):
    if isinstance(detail, DjangoValidationError):
        if hasattr(detail, "message_dict"):
            return detail.message_dict
        return {"__all__": list(detail.messages)}
    if isinstance(detail, dict):
        return detail
    return {"__all__": [str(detail)]}


# ── Reading the archive ────────────────────────────────────────────────────


def _read_member(archive, name):
    """Read one member, turning zip-level failures into ``ArchiveError``.

    ``ZipFile.read`` raises ``BadZipFile`` for members whose payload fails its
    CRC check — a truncated or corrupted upload — and that is not a subclass of
    the exceptions the callers otherwise translate, so without this a damaged
    archive would surface as an unhandled 500 instead of a readable message.
    """
    try:
        return archive.read(name)
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"{name} is corrupt or truncated: {exc}") from exc


def _load_json_document(archive, name, *, missing_message):
    """Read and JSON-parse one member, or raise ``ArchiveError``.

    Missing members and members whose payload fails its CRC check
    (``BadZipFile``) or is not UTF-8 JSON become readable errors rather than
    unhandled exceptions.
    """
    try:
        raw = _read_member(archive, name)
    except KeyError as exc:
        raise ArchiveError(missing_message) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveError(f"{name} is not readable JSON: {exc}") from exc


def read_manifest(archive):
    manifest = _load_json_document(
        archive,
        MANIFEST_NAME,
        missing_message=f"This ZIP file is not an OpenZEV export: it has no {MANIFEST_NAME}.",
    )
    if not isinstance(manifest, dict):
        raise ArchiveError(f"{MANIFEST_NAME} must contain a JSON object.")

    check_format_version(manifest.get("format_version"))

    sections = manifest.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ArchiveError(f"{MANIFEST_NAME} does not list any sections.")
    manifest["sections"] = list(normalise_sections(sections))

    # ``counts`` is the manifest's integrity record: an archive without it can
    # quietly import missing section contents, defeating the verification step.
    # It must be present, a plain object of non-negative integers, and account
    # for every declared section. ``zev`` is the one exemption because the
    # exporter counts sections that hold lists - the settings section is a
    # single object and carries no count.
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise ArchiveError(f"{MANIFEST_NAME} must record section counts as a JSON object.")
    for key, value in counts.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ArchiveError(
                f"{MANIFEST_NAME} count for '{key}' must be a non-negative integer."
            )
    for section in manifest["sections"]:
        if section == SECTION_ZEV:
            continue
        if section not in counts:
            raise ArchiveError(
                f"{MANIFEST_NAME} does not record a count for section '{section}'."
            )

    source_zev = manifest.get("source_zev")
    if source_zev is not None and not isinstance(source_zev, dict):
        raise ArchiveError(f"{MANIFEST_NAME} 'source_zev' must be a JSON object.")

    return manifest


def inspect_archive(fileobj):
    """Read an archive's manifest without importing anything.

    Lets the UI show what an archive contains and pre-select its sections
    before the user commits to creating a ZEV.
    """
    with open_archive(fileobj) as archive:
        return read_manifest(archive)


def _load_json(archive, name, *, expect_list=True):
    payload = _load_json_document(
        archive,
        name,
        missing_message=f"The archive is missing {name}, which its manifest says it contains.",
    )
    if expect_list and not isinstance(payload, list):
        raise ArchiveError(f"{name} must contain a JSON array.")
    if not expect_list and not isinstance(payload, dict):
        raise ArchiveError(f"{name} must contain a JSON object.")
    return payload


def _pick(raw, names, position, section):
    if not isinstance(raw, dict):
        raise ArchiveError(f"Entry {position} in the {section} section is not a JSON object.")
    return {name: raw.get(name) for name in names if raw.get(name) is not None}


# ── Section importers ──────────────────────────────────────────────────────


def _import_participants(archive, zev, collector):
    """Create every participant, returning ``archive id -> new participant``.

    Accounts are deliberately not re-linked. The archive carries no ``user``
    reference, and matching on the email address instead would let anyone who
    can edit a JSON file inside a ZIP grant an existing account access to an
    imported community's data. Participants arrive unlinked and an admin
    connects them by hand.
    """
    id_map = {}
    seen_ids = set()
    for position, raw in enumerate(_load_json(archive, SECTION_FILES[SECTION_PARTICIPANTS]), start=1):
        fields = _pick(raw, PARTICIPANT_FIELDS, position, SECTION_PARTICIPANTS)
        label = f"{fields.get('first_name', '')} {fields.get('last_name', '')}".strip() or f"#{position}"
        source_id = str(raw["id"]) if raw.get("id") else None
        if source_id is not None and source_id in seen_ids:
            # Two entries sharing an archive id would silently rewire every
            # assignment and invoice to whichever participant came last - reject
            # the duplicate before anything dependent can resolve to it.
            collector.add(
                SECTION_PARTICIPANTS,
                position,
                label,
                {"id": [f"Duplicate participant source id '{source_id}'."]},
            )
            continue
        participant = Participant(zev=zev, **fields)
        try:
            with transaction.atomic():  # savepoint: one rejection must not poison the rest
                participant.full_clean(exclude=["zev", "user"])
                participant.save()
        except (DjangoValidationError, ValueError, TypeError) as exc:
            collector.add(SECTION_PARTICIPANTS, position, label, exc)
            continue
        if source_id is not None:
            seen_ids.add(source_id)
            id_map[source_id] = participant
    return id_map


def _preflight_meter_ids(entries):
    """Report meter ids already taken on this instance, by name.

    ``MeteringPoint.meter_id`` is unique instance-wide, not per ZEV, so
    importing a community into an instance that already holds its physical
    meters collides. Checking up front turns a per-row constraint violation
    into one message naming exactly which meters are in the way.
    """
    wanted = [str(raw.get("meter_id")) for raw in entries if isinstance(raw, dict) and raw.get("meter_id")]
    if not wanted:
        return []
    taken = set(
        MeteringPoint.objects.filter(meter_id__in=wanted).values_list("meter_id", flat=True)
    )
    return sorted(taken)


def _import_metering_points(archive, zev, participants_by_archive_id, collector):
    entries = _load_json(archive, SECTION_FILES[SECTION_METERING_POINTS])

    clashes = _preflight_meter_ids(entries)
    if clashes:
        raise ImportFailed(
            [
                {
                    "section": SECTION_METERING_POINTS,
                    "position": None,
                    "label": meter_id,
                    "errors": {
                        "meter_id": [
                            f"Metering point '{meter_id}' already exists on this instance. "
                            "Meter ids are unique instance-wide, so this ZEV cannot be imported "
                            "alongside the one that already holds this meter."
                        ]
                    },
                }
                for meter_id in clashes
            ]
        )

    points_by_meter_id = {}
    assignment_count = 0
    for position, raw in enumerate(entries, start=1):
        fields = _pick(raw, METERING_POINT_FIELDS, position, SECTION_METERING_POINTS)
        label = str(fields.get("meter_id") or f"#{position}")
        point = MeteringPoint(zev=zev, **fields)
        try:
            with transaction.atomic():
                point.full_clean(exclude=["zev"])
                point.save()
        except (DjangoValidationError, ValueError, TypeError) as exc:
            collector.add(SECTION_METERING_POINTS, position, label, exc)
            continue
        points_by_meter_id[point.meter_id] = point

        for assignment_position, raw_assignment in enumerate(raw.get("assignments") or [], start=1):
            if _import_assignment(
                point,
                raw_assignment,
                participants_by_archive_id,
                collector,
                label=f"{label} #{assignment_position}",
                position=position,
            ):
                assignment_count += 1

    return points_by_meter_id, assignment_count


def _import_assignment(point, raw, participants_by_archive_id, collector, *, label, position):
    """Import one assignment; True when it was created."""
    if not isinstance(raw, dict):
        raise ArchiveError(f"Assignment {label} is not a JSON object.")
    participant = participants_by_archive_id.get(str(raw.get("participant_id")))
    if participant is None:
        # Either the participant section was not selected, or its entry failed
        # earlier. Both leave the assignment with nothing to point at.
        collector.add(
            SECTION_METERING_POINTS,
            position,
            label,
            {"participant_id": ["No imported participant matches this assignment."]},
        )
        return False

    fields = _pick(raw, ASSIGNMENT_FIELDS, position, SECTION_METERING_POINTS)
    assignment = MeteringPointAssignment(metering_point=point, participant=participant, **fields)
    try:
        with transaction.atomic():
            # full_clean() carries the rules that matter here: the assignment
            # window must sit inside the participant's validity window, and no
            # two assignments of one meter may overlap.
            assignment.full_clean(exclude=["metering_point", "participant"])
            assignment.save()
    except (DjangoValidationError, ValueError, TypeError) as exc:
        collector.add(SECTION_METERING_POINTS, position, label, exc)
        return False
    return True


def _import_tariffs(archive, zev, collector):
    count = 0
    for position, raw in enumerate(_load_json(archive, SECTION_FILES[SECTION_TARIFFS]), start=1):
        fields = _pick(raw, TARIFF_FIELDS, position, SECTION_TARIFFS)
        label = str(fields.get("name") or f"#{position}")
        try:
            with transaction.atomic():
                # Tariff.save() calls full_clean() itself, so the overlap and
                # series-coherence rules run without asking for them.
                tariff = Tariff.objects.create(zev=zev, **fields)
                for raw_period in raw.get("periods") or []:
                    period_fields = _pick(raw_period, TARIFF_PERIOD_FIELDS, position, SECTION_TARIFFS)
                    period = TariffPeriod(tariff=tariff, **period_fields)
                    period.full_clean(exclude=["tariff"])
                    period.save()
        except (DjangoValidationError, ValueError, TypeError) as exc:
            collector.add(SECTION_TARIFFS, position, label, exc)
            continue
        count += 1
    return count


def _import_invoices(archive, zev, participants_by_archive_id, collector):
    """Create invoices and their line items, and return the highest number seen.

    The caller uses that to push ``Zev.invoice_counter`` past the imported
    history, so the next billing run cannot mint a number that already exists.
    """
    count = 0
    highest = 0
    for position, raw in enumerate(_load_json(archive, SECTION_FILES[SECTION_INVOICES]), start=1):
        fields = _pick(raw, INVOICE_FIELDS, position, SECTION_INVOICES)
        label = str(fields.get("invoice_number") or f"#{position}")
        participant = participants_by_archive_id.get(str(raw.get("participant_id")))
        if participant is None:
            collector.add(
                SECTION_INVOICES,
                position,
                label,
                {"participant_id": ["No imported participant matches this invoice."]},
            )
            continue

        try:
            with transaction.atomic():
                invoice = Invoice(zev=zev, participant=participant, **fields)
                invoice.full_clean(exclude=["zev", "participant", "pdf_file"])
                invoice.save()
                items = []
                for raw_item in raw.get("items") or []:
                    item_fields = _pick(raw_item, INVOICE_ITEM_FIELDS, position, SECTION_INVOICES)
                    item = InvoiceItem(invoice=invoice, **item_fields)
                    item.full_clean(exclude=["invoice"])
                    items.append(item)
                InvoiceItem.objects.bulk_create(items)
        except (DjangoValidationError, ValueError, TypeError, IntegrityError) as exc:
            collector.add(SECTION_INVOICES, position, label, exc)
            continue

        count += 1
        highest = max(highest, _trailing_number(invoice.invoice_number))
    return count, highest


def _trailing_number(invoice_number):
    """The numeric tail of ``INV-00042`` — 42 — or 0 when there is not one.

    Matches how ``Zev.next_invoice_number()`` composes them: prefix, dash,
    zero-padded counter.
    """
    tail = ""
    for char in reversed(str(invoice_number)):
        if not char.isdigit():
            break
        tail = char + tail
    return int(tail) if tail else 0


# ── Readings ───────────────────────────────────────────────────────────────

_VALID_DIRECTIONS = {value for value, _ in ReadingDirection.choices}
_VALID_RESOLUTIONS = {value for value, _ in ReadingResolution.choices}
_VALID_SOURCES = {value for value, _ in ImportSource.choices}


def _import_readings(archive, points_by_meter_id, collector, *, batch_id):
    """Load every ``readings/*.csv`` member into the imported metering points.

    Rows are validated then written with ``bulk_create``. The metering app's
    importer is row-at-a-time ``get_or_create`` — right for a user-supplied
    file that may collide with existing data, wrong here: the metering points
    were created moments ago and hold nothing, so there is nothing to collide
    with, and two million round trips is not a thing to do on purpose. Its
    field parsers are reused, so the two agree on what a timestamp and a
    decimal are.
    """
    total = 0
    members = [
        name
        for name in archive.namelist()
        if name.startswith(f"{READINGS_DIR}/") and name.lower().endswith(".csv")
    ]

    # (meter, timestamp, direction) already written for this import. The unique
    # constraint would catch a duplicate anyway, but only as an IntegrityError
    # that takes the whole batch down with it and names nothing useful. The set
    # spans every member, not just this file: two members naming the same meter
    # are as much a duplicate as two rows in one file.
    seen = set()

    for name in sorted(members):
        try:
            with archive.open(name) as member:
                text = io.TextIOWrapper(member, encoding="utf-8", newline="")
                reader = csv.DictReader(text)
                missing = {"meter_id", "timestamp", "energy_kwh"} - set(reader.fieldnames or [])
                if missing:
                    collector.add(
                        SECTION_READINGS,
                        None,
                        name,
                        {"__all__": [f"Missing column(s): {', '.join(sorted(missing))}."]},
                    )
                    text.detach()
                    continue

                pending = []
                for row_number, row in enumerate(reader, start=2):
                    reading = _build_reading(row, points_by_meter_id, batch_id)
                    if isinstance(reading, dict):
                        collector.add(SECTION_READINGS, row_number, name, reading)
                        continue

                    key = (reading.metering_point_id, reading.timestamp, reading.direction)
                    if key in seen:
                        collector.add(
                            SECTION_READINGS,
                            row_number,
                            name,
                            {"__all__": ["Duplicate reading for this metering point, timestamp and direction."]},
                        )
                        continue
                    seen.add(key)

                    pending.append(reading)
                    if len(pending) >= READING_BATCH_SIZE:
                        total += _bulk_create_readings(pending, name, collector)
                        pending = []

                if pending:
                    total += _bulk_create_readings(pending, name, collector)
                text.detach()
        except (zipfile.BadZipFile, UnicodeDecodeError, csv.Error) as exc:
            # A member whose payload failed its CRC check, or whose text
            # cannot be decoded (a NUL byte, say) must not take the whole
            # import down with an unhandled exception — one file is reported
            # and the rest still gets its chance.
            collector.add(
                SECTION_READINGS,
                None,
                name,
                {"__all__": [f"Unreadable readings file: {exc}"]},
            )

    return total


def _bulk_create_readings(rows, member_name, collector):
    """Insert one batch, converting database-level failures into collected errors.

    The rows were validated individually, so a failure here is something the
    per-row checks did not cover — a future constraint, a value that overflowed
    the column width. It must not take the whole import down: the batch is
    reported by file, and whatever comes next still gets its chance. The insert
    runs in a savepoint so a rejected batch leaves the surrounding transaction
    usable on PostgreSQL. Returns the number of rows actually inserted, so the
    manifest count check does not count a rejected batch as imported data.
    """
    try:
        with transaction.atomic():
            MeterReading.objects.bulk_create(rows)
    except (IntegrityError, DataError) as exc:
        # The exception text can carry database internals (constraint names,
        # column dumps); the admin-facing response gets a generic sentence and
        # the detail goes to the log.
        logger.exception(
            "Database rejected a batch of %s readings from archive member %r",
            len(rows), member_name, exc_info=exc,
        )
        collector.add(
            SECTION_READINGS,
            None,
            member_name,
            {"__all__": ["The database rejected a batch of readings; the batch was skipped. See the server log for details."]},
        )
        return 0
    return len(rows)


def _build_reading(row, points_by_meter_id, batch_id):
    """A ``MeterReading`` for ``row``, or a dict of errors describing why not."""
    meter_id = (row.get("meter_id") or "").strip()
    point = points_by_meter_id.get(meter_id)
    if point is None:
        return {"meter_id": [f"No imported metering point named '{meter_id}'."]}

    try:
        timestamp = _parse_datetime_utc(row.get("timestamp"))
    except (ValueError, TypeError, OverflowError) as exc:
        return {"timestamp": [f"Unreadable timestamp: {exc}"]}

    try:
        energy = _parse_decimal(row.get("energy_kwh"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        return {"energy_kwh": [f"Unreadable energy value: {exc}"]}

    if abs(energy) > MAX_ENERGY_KWH:
        return {
            "energy_kwh": [
                f"Energy value {energy} exceeds the maximum representable value ({MAX_ENERGY_KWH} kWh)."
            ]
        }

    direction = (row.get("direction") or ReadingDirection.IN).strip().lower()
    if direction not in _VALID_DIRECTIONS:
        return {"direction": [f"Invalid direction '{direction}'. Expected one of: {', '.join(sorted(_VALID_DIRECTIONS))}."]}

    resolution = (row.get("resolution") or ReadingResolution.FIFTEEN_MIN).strip()
    if resolution not in _VALID_RESOLUTIONS:
        return {"resolution": [f"Invalid resolution '{resolution}'. Expected one of: {', '.join(sorted(_VALID_RESOLUTIONS))}."]}

    source = (row.get("import_source") or ImportSource.CSV).strip()
    if source not in _VALID_SOURCES:
        return {"import_source": [f"Invalid import source '{source}'."]}

    return MeterReading(
        metering_point=point,
        timestamp=timestamp,
        energy_kwh=energy,
        direction=direction,
        resolution=resolution,
        import_source=source,
        import_batch=batch_id,
    )


# ── Entry point ────────────────────────────────────────────────────────────


def import_archive(fileobj, *, owner, sections=None, name_override=""):
    """Create a new ZEV from ``fileobj`` and return a summary dict.

    Raises ``ArchiveError`` when the file cannot be read at all, ``ValueError``
    for an incoherent section selection, and ``ImportFailed`` when the archive
    reads but its contents do not validate. Nothing is created in any of those
    cases.
    """
    with open_archive(fileobj) as archive:
        manifest = read_manifest(archive)
        available = manifest["sections"]

        sections = normalise_sections(sections, available=available) if sections else tuple(available)
        if not sections:
            raise ValueError("Select at least one section to import.")
        check_dependencies(sections)

        batch_id = uuid.uuid4()
        collector = _Collector()

        with transaction.atomic():
            summary = _run_import(
                archive,
                manifest,
                sections,
                owner=owner,
                name_override=name_override,
                collector=collector,
                batch_id=batch_id,
            )
            # Raised inside the atomic block on purpose: it is what rolls the
            # whole import back, so a rejected archive leaves no ZEV behind.
            if collector:
                raise ImportFailed(collector.errors, total_errors=collector.total)

        return summary


def _run_import(archive, manifest, sections, *, owner, name_override, collector, batch_id):
    zev_fields = {}
    if SECTION_ZEV in sections:
        zev_fields = {
            key: value
            for key, value in _load_json(archive, SECTION_FILES[SECTION_ZEV], expect_list=False).items()
            if key in ZEV_FIELDS and value is not None
        }

    # A name is needed whether or not the settings section travels, so it falls
    # back to what the manifest recorded about the source ZEV.
    source_name = (manifest.get("source_zev") or {}).get("name") or "Imported ZEV"
    zev_fields["name"] = name_override.strip() or zev_fields.get("name") or source_name
    zev_fields.pop("invoice_counter", None)  # set from the imported invoices below

    zev = Zev(owner=owner, **zev_fields)
    try:
        zev.full_clean(exclude=["owner"])
    except DjangoValidationError as exc:
        raise ImportFailed([{"section": SECTION_ZEV, "position": None, "label": zev_fields["name"], "errors": _normalise(exc)}])
    zev.save()

    summary = {
        "zev_id": str(zev.id),
        "zev_name": zev.name,
        "sections": list(sections),
        "counts": {},
    }

    participants_by_archive_id = {}
    if SECTION_PARTICIPANTS in sections:
        participants_by_archive_id = _import_participants(archive, zev, collector)
        summary["counts"][SECTION_PARTICIPANTS] = len(participants_by_archive_id)

    points_by_meter_id = {}
    if SECTION_METERING_POINTS in sections:
        points_by_meter_id, assignment_count = _import_metering_points(
            archive, zev, participants_by_archive_id, collector
        )
        summary["counts"][SECTION_METERING_POINTS] = len(points_by_meter_id)
        summary["counts"]["assignments"] = assignment_count

    if SECTION_TARIFFS in sections:
        summary["counts"][SECTION_TARIFFS] = _import_tariffs(archive, zev, collector)

    if SECTION_READINGS in sections:
        imported = _import_readings(archive, points_by_meter_id, collector, batch_id=batch_id)
        summary["counts"][SECTION_READINGS] = imported
        ImportLog.objects.create(
            batch_id=batch_id,
            zev=zev,
            imported_by=owner,
            source=ImportSource.CSV,
            filename=f"ZEV import ({zev.name})",
            rows_total=imported,
            rows_imported=imported,
            rows_skipped=0,
        )

    if SECTION_INVOICES in sections:
        count, highest = _import_invoices(archive, zev, participants_by_archive_id, collector)
        summary["counts"][SECTION_INVOICES] = count
        # Past the imported history, so the next billing run cannot mint a
        # number this ZEV already carries.
        next_counter = max(highest + 1, zev.invoice_counter)
        if next_counter != zev.invoice_counter:
            zev.invoice_counter = next_counter
            zev.save(update_fields=["invoice_counter"])

    _verify_manifest_counts(manifest, summary, collector)

    return summary


def _verify_manifest_counts(manifest, summary, collector):
    """Where the manifest and what the importer produced disagree, the archive
    is corrupt or tampered (a readings member dropped out of a truncated ZIP,
    say), and a backup feature must not report such an import as a success."""
    declared = manifest.get("counts") or {}
    for key, expected in declared.items():
        if key not in summary["counts"]:
            continue  # a section the user chose not to import
        # ``assignments`` is counted under the metering-points section.
        section = key if key in SECTIONS else SECTION_METERING_POINTS
        # Entry-level failures already explain a shortfall for that section —
        # re-reporting it as an integrity problem would just be noise. The
        # check exists for the *unexplained* discrepancy: a readings member
        # that dropped out of a truncated ZIP, say.
        if any(e["section"] == section for e in collector.errors):
            continue
        actual = summary["counts"][key]
        if actual != expected:
            name = key[:-1] if expected == 1 and key.endswith("s") else key
            collector.add(
                section,
                None,
                "manifest",
                {
                    "__all__": [
                        f"The archive declares {expected} {name}, but the import produced {actual}. "
                        "The archive is corrupt or was modified; nothing was imported."
                    ]
                },
            )
