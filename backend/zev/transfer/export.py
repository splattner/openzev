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
import io
import json
import zipfile
from datetime import datetime, timezone

from django.core.serializers.json import DjangoJSONEncoder

from invoices.models import Invoice
from metering.models import MeterReading
from tariffs.models import Tariff
from zev.models import MeteringPoint, MeteringPointAssignment, Participant

from .schema import (
    ASSIGNMENT_FIELDS,
    FORMAT_VERSION,
    INVOICE_FIELDS,
    INVOICE_ITEM_FIELDS,
    MANIFEST_NAME,
    METERING_POINT_FIELDS,
    PARTICIPANT_FIELDS,
    READING_CSV_COLUMNS,
    READINGS_DIR,
    SECTION_FILES,
    SECTION_INVOICES,
    SECTION_METERING_POINTS,
    SECTION_PARTICIPANTS,
    SECTION_READINGS,
    SECTION_TARIFFS,
    SECTION_ZEV,
    TARIFF_FIELDS,
    TARIFF_PERIOD_FIELDS,
    ZEV_FIELDS,
    check_dependencies,
    normalise_sections,
)

# Rows pulled from the database at a time while streaming readings out. Large
# enough that the per-query overhead disappears, small enough that a chunk is
# never a memory problem.
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
    """
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in meter_id)
    return f"{READINGS_DIR}/{safe or 'meter'}.csv"


def _export_zev(zev):
    return _fields(zev, ZEV_FIELDS)


def _export_participants(zev):
    return [
        {"id": str(participant.id), **_fields(participant, PARTICIPANT_FIELDS)}
        for participant in Participant.objects.filter(zev=zev).order_by("last_name", "first_name", "id")
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
    return [
        {
            "id": str(tariff.id),
            **_fields(tariff, TARIFF_FIELDS),
            "periods": [
                {"id": str(period.id), **_fields(period, TARIFF_PERIOD_FIELDS)}
                for period in tariff.periods.all().order_by("period_type", "id")
            ],
        }
        for tariff in Tariff.objects.filter(zev=zev).prefetch_related("periods").order_by("name", "valid_from")
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
        }
        # ``pdf_file`` is absent from INVOICE_FIELDS: PDFs are regenerable from
        # the data and would dominate the archive size. See the issue's note —
        # a regenerated PDF uses today's template, so this is not the right
        # answer if original documents have to be retained.
        for invoice in Invoice.objects.filter(zev=zev).prefetch_related("items").order_by("period_start", "invoice_number")
    ]


def _write_readings(archive, zev):
    """Stream every reading of the ZEV into ``readings/<meter>.csv``.

    Returns the per-meter row counts for the manifest. A meter with no readings
    still gets a header-only file, so the archive says "no data" rather than
    leaving the importer to guess between that and a dropped file.
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

    counts = {}
    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as archive:
        if SECTION_ZEV in sections:
            archive.writestr(SECTION_FILES[SECTION_ZEV], _dump(_export_zev(zev)))

        if SECTION_PARTICIPANTS in sections:
            participants = _export_participants(zev)
            counts[SECTION_PARTICIPANTS] = len(participants)
            archive.writestr(SECTION_FILES[SECTION_PARTICIPANTS], _dump(participants))

        if SECTION_METERING_POINTS in sections:
            points = _export_metering_points(zev)
            counts[SECTION_METERING_POINTS] = len(points)
            counts["assignments"] = sum(len(point["assignments"]) for point in points)
            archive.writestr(SECTION_FILES[SECTION_METERING_POINTS], _dump(points))

        if SECTION_TARIFFS in sections:
            tariffs = _export_tariffs(zev)
            counts[SECTION_TARIFFS] = len(tariffs)
            archive.writestr(SECTION_FILES[SECTION_TARIFFS], _dump(tariffs))

        if SECTION_READINGS in sections:
            per_meter = _write_readings(archive, zev)
            counts[SECTION_READINGS] = sum(per_meter.values())

        if SECTION_INVOICES in sections:
            invoices = _export_invoices(zev)
            counts[SECTION_INVOICES] = len(invoices)
            archive.writestr(SECTION_FILES[SECTION_INVOICES], _dump(invoices))

        # Written last so its counts are the ones actually produced, but read
        # first on import — ZIP central directories are order-independent.
        manifest = {
            "format_version": FORMAT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_instance": instance_name,
            "sections": list(sections),
            "counts": counts,
            # Kept so an in-place restore that preserves identity stays possible
            # as a later feature rather than a re-export. Nothing reads these
            # today: the importer always mints new ids.
            "source_zev": {"id": str(zev.id), "name": zev.name},
        }
        archive.writestr(MANIFEST_NAME, _dump(manifest))

    return manifest


def archive_filename(zev, *, today):
    slug = "".join(char if char.isalnum() else "-" for char in zev.name.lower()).strip("-")
    slug = "-".join(part for part in slug.split("-") if part) or "zev"
    return f"openzev-export-{slug}-{today.isoformat()}.zip"
