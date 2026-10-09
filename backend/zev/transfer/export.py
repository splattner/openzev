"""Build a transfer archive for one ZEV.

The archive builder is deliberately a plain function over a file object rather
than a view helper. Readings are the part that does not fit in memory — the
demo ZEV alone holds ~35k rows for three meters over four months, and a
twenty-meter community over three years is on the order of two million — so
every reading query is iterated and streamed straight into the ZIP member, and
the caller supplies somewhere to put the result (a temporary file today, object
storage from a Celery task later). Moving this off the request path is then a
change of caller, not a rewrite.
"""

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.models import Prefetch

from invoices.models import Invoice
from metering.models import MeterReading, SupplementaryReading, SupplementarySource
from tariffs.models import Tariff, TariffPeriod
from zev.models import Building, MeteringPoint, MeteringPointAssignment, Participant, Party, ZevPartyRole

from .schema import (
    ASSIGNMENT_FIELDS,
    DYNAMIC_SOURCE_FIELDS,
    FORMAT_VERSION,
    INVOICE_FIELDS,
    INVOICE_ITEM_FIELDS,
    INVOICE_PDFS_DIR,
    MANIFEST_NAME,
    BUILDING_FIELDS,
    BUILDINGS_FILE,
    METERING_POINT_FIELDS,
    PARTICIPANT_FIELDS,
    PARTIES_FILE,
    PARTY_FIELDS,
    PARTY_ROLE_FIELDS,
    PARTY_ROLES_FILE,
    READING_CSV_COLUMNS,
    READINGS_DIR,
    SECTION_FILES,
    SECTION_INVOICE_PDFS,
    SECTION_INVOICES,
    SECTION_METERING_POINTS,
    SECTION_PARTICIPANTS,
    SECTION_READINGS,
    SECTION_SUPPLEMENTARY,
    SECTION_TARIFFS,
    SECTION_ZEV,
    SUPPLEMENTARY_READING_CSV_COLUMNS,
    SUPPLEMENTARY_READINGS_DIR,
    SUPPLEMENTARY_SOURCE_FIELDS,
    TARIFF_FIELDS,
    TARIFF_PERIOD_FIELDS,
    ZEV_FIELDS,
    check_dependencies,
    normalise_sections,
)

# Rows pulled from the database at a time while streaming readings out.
READING_CHUNK_SIZE = 5000


def _fields(instance, names):
    return {name: getattr(instance, name) for name in names}


def _dump(payload):
    return json.dumps(payload, cls=DjangoJSONEncoder, indent=2, ensure_ascii=False).encode("utf-8")


def _reading_csv_name(meter_id):
    """A ZIP member name derived from a meter id, safe on every filesystem.

    ``meter_id`` is free text: real Swiss ids are alphanumeric, but nothing in
    the model stops a slash or a backslash, and either would make the extracted
    archive write outside ``readings/``.

    Sanitising alone is not enough: two distinct ids such as ``A/B`` and
    ``A_B`` sanitise to the same string, and writing a second ZIP member under
    the same name would silently drop the first meter's readings from the
    archive — the worst failure mode for a backup feature. Appending a short
    hash of the raw id makes the member name a lossless function of the id, so
    every meter always gets its own file. (Importers read ``meter_id`` from the
    CSV rows, never from the member name, so renaming is safe on round-trip.)
    """
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in meter_id)
    digest = hashlib.sha1(meter_id.encode("utf-8")).hexdigest()[:8]
    return f"{READINGS_DIR}/{safe or 'meter'}-{digest}.csv"


def _supplementary_csv_name(meter_id):
    """The member of a source's readings: ``_reading_csv_name`` for the other directory."""
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in meter_id)
    digest = hashlib.sha1(meter_id.encode("utf-8")).hexdigest()[:8]
    return f"{SUPPLEMENTARY_READINGS_DIR}/{safe or 'meter'}-{digest}.csv"


def pdf_member_name(invoice_number):
    """A ZIP member name derived from an invoice number, same construction as
    ``_reading_csv_name`` and for the same reason: ``invoice_prefix`` is free
    text, so two distinct numbers can sanitise to the same string, and a
    binary PDF has no internal field the importer could use to notice a
    collision the way a reading CSV's own rows do. The importer recomputes
    this from the same ``invoice_number`` rather than reading it from a
    manifest — deterministic on both sides, so nothing needs to be stored
    twice.
    """
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in invoice_number)
    digest = hashlib.sha1(invoice_number.encode("utf-8")).hexdigest()[:8]
    return f"{INVOICE_PDFS_DIR}/{safe or 'invoice'}-{digest}.pdf"


def _export_zev(zev):
    return _fields(zev, ZEV_FIELDS)


def _export_parties(zev):
    return [
        {"id": str(party.id), **_fields(party, PARTY_FIELDS)}
        for party in Party.objects.filter(zev=zev).order_by("sort_name", "first_name", "id")
    ]


def _export_party_roles(zev):
    return [
        {
            "party_id": str(row.party_id),
            "building_id": str(row.building_id) if row.building_id else None,
            **_fields(row, PARTY_ROLE_FIELDS),
        }
        for row in ZevPartyRole.objects.filter(zev=zev).order_by("role", "valid_from", "id")
    ]


def _export_participants(zev):
    return [
        {"id": str(participant.id), "party_id": str(participant.party_id), **_fields(participant, PARTICIPANT_FIELDS)}
        for participant in Participant.objects.filter(zev=zev).order_by("party__sort_name", "party__first_name", "id")
    ]


def _export_buildings(zev):
    return [
        {"id": str(building.id), **_fields(building, BUILDING_FIELDS)}
        for building in Building.objects.filter(zev=zev).order_by("name", "id")
    ]


def _export_metering_points(zev):
    points = list(MeteringPoint.objects.filter(zev=zev).order_by("meter_id"))
    assignments_by_point = {}
    for assignment in (
        MeteringPointAssignment.objects.filter(metering_point__zev=zev)
        .order_by("metering_point_id", "valid_from")
    ):
        assignments_by_point.setdefault(assignment.metering_point_id, []).append(assignment)

    return [
        {
            "id": str(point.id),
            "building_id": str(point.building_id),
            **_fields(point, METERING_POINT_FIELDS),
            "assignments": [
                {
                    "id": str(assignment.id),
                    # The archive's own reference, remapped on import. Exporting
                    # the participant id rather than a name is what makes the
                    # link survive two participants who share one.
                    "participant_id": str(assignment.participant_id),
                    **_fields(assignment, ASSIGNMENT_FIELDS),
                }
                for assignment in assignments_by_point.get(point.id, [])
            ],
        }
        for point in points
    ]


def _export_tariffs(zev):
    # The Prefetch pins the period ordering, so ``periods.all()`` below serves
    # from the prefetch cache instead of re-querying per tariff (a plain
    # prefetch_related("periods") is defeated by the order_by).
    tariffs = Tariff.objects.filter(zev=zev).select_related("dynamic_source").prefetch_related(
        Prefetch("periods", queryset=TariffPeriod.objects.order_by("period_type", "id"))
    ).order_by("name", "valid_from")
    return [
        {
            "id": str(tariff.id),
            **_fields(tariff, TARIFF_FIELDS),
            # By natural key, not by id: the source is shared across communities
            # and its surrogate id is meaningless on another instance.
            "dynamic_source": (
                _fields(tariff.dynamic_source, DYNAMIC_SOURCE_FIELDS)
                if tariff.dynamic_source_id else None
            ),
            "periods": [
                {"id": str(period.id), **_fields(period, TARIFF_PERIOD_FIELDS)}
                for period in tariff.periods.all()
            ],
        }
        for tariff in tariffs
    ]


def _export_invoices(zev):
    return [
        {
            "id": str(invoice.id),
            "participant_id": str(invoice.participant_id),
            **_fields(invoice, INVOICE_FIELDS),
            "items": [
                {"id": str(item.id), **_fields(item, INVOICE_ITEM_FIELDS)}
                for item in invoice.items.all()
            ],
            "dynamic_evidence": [
                {
                    "dynamic_source": _fields(evidence.source, DYNAMIC_SOURCE_FIELDS),
                    "tariff_id_snapshot": str(evidence.tariff_id_snapshot),
                    "evidence_from": evidence.evidence_from.isoformat(),
                    "evidence_to": evidence.evidence_to.isoformat(),
                }
                for evidence in invoice.dynamic_evidence.all()
            ],
        }
        # ``pdf_file`` is absent from INVOICE_FIELDS: PDFs are regenerable from
        # the data and would dominate the archive size. See the issue's note —
        # a regenerated PDF uses today's template, so this is not the right
        # answer if original documents have to be retained.
        for invoice in Invoice.objects.filter(zev=zev).prefetch_related("items", "dynamic_evidence__source").order_by("period_start", "invoice_number")
    ]


def _write_readings(archive, zev):
    """Stream every reading of the ZEV into ``readings/<meter>.csv``.

    Returns the per-meter row counts; the manifest's readings count is their
    sum. A meter with no readings still gets a header-only file, so the archive
    says "no data" rather than leaving the importer to guess between that and a
    dropped file.
    """
    counts = {}
    for point in MeteringPoint.objects.filter(zev=zev).order_by("meter_id"):
        rows = 0
        with archive.open(_reading_csv_name(point.meter_id), "w") as member:
            # ZipFile members are binary; readings are ASCII once serialised.
            text = io.TextIOWrapper(member, encoding="utf-8", newline="")
            writer = csv.writer(text)
            writer.writerow(READING_CSV_COLUMNS)
            queryset = (
                MeterReading.objects.filter(metering_point=point)
                .order_by("timestamp", "direction")
                .values_list("timestamp", "energy_kwh", "direction", "resolution", "import_source")
            )
            for timestamp, energy_kwh, direction, resolution, import_source in queryset.iterator(
                chunk_size=READING_CHUNK_SIZE
            ):
                writer.writerow(
                    [
                        point.meter_id,
                        timestamp.astimezone(timezone.utc).isoformat(),
                        energy_kwh,
                        direction,
                        resolution,
                        import_source,
                    ]
                )
                rows += 1
            text.flush()
            # Detach before the member closes: TextIOWrapper closes what it
            # wraps on garbage collection, and the ZipFile owns that.
            text.detach()
        counts[point.meter_id] = rows
    return counts


def _export_supplementary_sources(zev):
    """The ZEV's energy data sources, by ``meter_id`` and archive ``participant_id``. No secret, no state."""
    return [
        {
            "id": str(source.id),
            "meter_id": source.metering_point.meter_id,
            "participant_id": str(source.participant_id),
            **_fields(source, SUPPLEMENTARY_SOURCE_FIELDS),
        }
        for source in SupplementarySource.objects.filter(metering_point__zev=zev)
        .select_related("metering_point")
        .order_by("metering_point__meter_id")
    ]


def _write_supplementary_readings(archive, zev):
    """Stream every source's readings into ``supplementary_readings/<meter>.csv``; returns the row total."""
    total = 0
    for source in (
        SupplementarySource.objects.filter(metering_point__zev=zev)
        .select_related("metering_point")
        .order_by("metering_point__meter_id")
    ):
        meter_id = source.metering_point.meter_id
        with archive.open(_supplementary_csv_name(meter_id), "w") as member:
            text = io.TextIOWrapper(member, encoding="utf-8", newline="")
            writer = csv.writer(text)
            writer.writerow(SUPPLEMENTARY_READING_CSV_COLUMNS)
            queryset = (
                SupplementaryReading.objects.filter(source=source)
                .order_by("timestamp")
                .values_list("timestamp", "consumption_kwh", "production_kwh", "import_kwh", "export_kwh")
            )
            for timestamp, consumption, production, imported, exported in queryset.iterator(
                chunk_size=READING_CHUNK_SIZE
            ):
                writer.writerow(
                    [meter_id, timestamp.astimezone(timezone.utc).isoformat(), consumption, production, imported, exported]
                )
                total += 1
            text.flush()
            text.detach()
    return total


def _write_invoice_pdfs(archive, zev):
    """Copy every issued invoice's stored PDF bytes into the archive.

    Only invoices that actually have a rendered document contribute a
    member — an invoice with none simply has no corresponding file, the same
    "absence means absence" rule ``_write_readings`` uses a header-only file
    to avoid needing for CSVs (a PDF has no header row to write instead).
    Returns the count written, for the manifest.
    """
    written = 0
    for invoice in (
        Invoice.objects.filter(zev=zev).exclude(pdf_file="").exclude(pdf_file__isnull=True)
        .order_by("invoice_number")
    ):
        with invoice.pdf_file.open("rb") as source:
            archive.writestr(pdf_member_name(invoice.invoice_number), source.read())
        written += 1
    return written


def build_archive(zev, sections, fileobj, *, instance_name=""):
    """Write a transfer archive for ``zev`` into ``fileobj``.

    ``sections`` is validated first: an incomplete selection (readings without
    metering points, say) fails here rather than producing an archive that
    cannot be imported.
    """
    sections = normalise_sections(sections)
    if not sections:
        raise ValueError("Select at least one section to export.")
    check_dependencies(sections)

    # durable=True rejects application nesting and handles Django's TestCase
    # exception itself. Set isolation only when we open a new transaction.
    starts_transaction = not connection.in_atomic_block

    # One transaction so the whole archive is a snapshot: sections are read at
    # different moments (readings alone can stream for minutes on a large
    # community), and without a repeatable-read snapshot a concurrent edit can
    # leave an archive that never existed as a state, with manifest counts that
    # disagree with the CSV contents.
    with transaction.atomic(durable=True):
        if connection.vendor == "postgresql" and starts_transaction:
            # transaction.atomic() alone only buys READ COMMITTED on
            # PostgreSQL; the export needs every statement to see the same
            # committed state, so pin the transaction to REPEATABLE READ.
            # durable=True means this block must be the outermost transaction:
            # inside an outer atomic it fails loudly with a RuntimeError
            # instead of degrading to a savepoint where SET TRANSACTION
            # ISOLATION LEVEL would blow up as Postgres 25001.
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        return _write_archive(zev, sections, fileobj, instance_name=instance_name)


def _write_archive(zev, sections, fileobj, *, instance_name=""):
    """The actual writer, inside ``build_archive``'s transaction."""
    counts = {}
    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as archive:
        if SECTION_ZEV in sections:
            archive.writestr(SECTION_FILES[SECTION_ZEV], _dump(_export_zev(zev)))

        if SECTION_PARTICIPANTS in sections:
            parties, roles = _export_parties(zev), _export_party_roles(zev)
            counts["parties"], counts["party_roles"] = len(parties), len(roles)
            archive.writestr(PARTIES_FILE, _dump(parties))
            archive.writestr(PARTY_ROLES_FILE, _dump(roles))
            participants = _export_participants(zev)
            counts[SECTION_PARTICIPANTS] = len(participants)
            archive.writestr(SECTION_FILES[SECTION_PARTICIPANTS], _dump(participants))

        if SECTION_METERING_POINTS in sections:
            buildings = _export_buildings(zev)
            counts["buildings"] = len(buildings)
            archive.writestr(BUILDINGS_FILE, _dump(buildings))
            points = _export_metering_points(zev)
            counts[SECTION_METERING_POINTS] = len(points)
            counts["assignments"] = sum(len(p["assignments"]) for p in points)
            archive.writestr(SECTION_FILES[SECTION_METERING_POINTS], _dump(points))

        if SECTION_TARIFFS in sections:
            tariffs = _export_tariffs(zev)
            counts[SECTION_TARIFFS] = len(tariffs)
            archive.writestr(SECTION_FILES[SECTION_TARIFFS], _dump(tariffs))

        if SECTION_READINGS in sections:
            per_meter = _write_readings(archive, zev)
            counts[SECTION_READINGS] = sum(per_meter.values())

        if SECTION_SUPPLEMENTARY in sections:
            sources = _export_supplementary_sources(zev)
            counts[SECTION_SUPPLEMENTARY] = len(sources)
            archive.writestr(SECTION_FILES[SECTION_SUPPLEMENTARY], _dump(sources))
            counts["supplementary_readings"] = _write_supplementary_readings(archive, zev)

        if SECTION_INVOICES in sections:
            invoices = _export_invoices(zev)
            counts[SECTION_INVOICES] = len(invoices)
            archive.writestr(SECTION_FILES[SECTION_INVOICES], _dump(invoices))

        if SECTION_INVOICE_PDFS in sections:
            counts[SECTION_INVOICE_PDFS] = _write_invoice_pdfs(archive, zev)

        # Written last so its counts are the ones actually produced.
        manifest = {
            "format_version": FORMAT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_instance": instance_name,
            "sections": list(sections),
            "counts": counts,
            # Kept so an in-place restore that preserves identity stays possible
            # as a later feature rather than a re-export. The importer never
            # reads the id — it always mints new ids — but falls back to the
            # name when the settings section does not travel.
            "source_zev": {"id": str(zev.id), "name": zev.name},
        }
        archive.writestr(MANIFEST_NAME, _dump(manifest))

    return manifest


def archive_filename(zev, *, today):
    slug = "".join(char if char.isalnum() else "-" for char in zev.name.lower()).strip("-")
    slug = "-".join(part for part in slug.split("-") if part) or "zev"
    return f"openzev-export-{slug}-{today.isoformat()}.zip"
