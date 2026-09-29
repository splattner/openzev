"""
SDAT-CH (ebIX XML) metering data importer.

Parses the Swiss SDAT-CH MeteringData XML format delivered by VNBs.
The format is based on the ebIX standard with Swiss extensions.

Reference: SDAT-CH specification, swisseldex / Edirom
"""
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from lxml import etree

from allocation.validity import business_tz

from zev.models import MeteringPoint
from metering.models import MeterReading, ImportLog, ImportSource
from metering.importers.limits import MAX_UPLOAD_BYTES, add_error, mb

MAX_SDAT_BYTES = MAX_UPLOAD_BYTES


def _parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 datetime string to a UTC datetime.

    SDAT-CH timestamps carry ``Z`` or an offset. One without is read as Swiss
    local time explicitly (ADR 0026) — a bare ``astimezone()`` would silently
    use the process timezone instead.
    """
    value = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=business_tz())
    return parsed.astimezone(timezone.utc)


def import_sdatch(file, zev, user):
    """
    Import metering readings from a SDAT-CH / ebIX XML file.

    Returns an ImportLog instance.
    """
    batch_id = uuid.uuid4()
    filename = getattr(file, "name", "upload.xml")

    log = ImportLog.objects.create(
        batch_id=batch_id,
        zev=zev,
        imported_by=user,
        source=ImportSource.SDATCH,
        filename=filename,
        timestamp_timezone=str(business_tz()),
    )

    # App-level size cap (nginx enforces 413 earlier).
    size_hint = getattr(file, "size", None)
    if size_hint is not None and size_hint > MAX_SDAT_BYTES:
        log.rows_total = 0
        log.rows_imported = 0
        log.rows_skipped = 0
        log.errors = [{"error": f"File too large ({mb(size_hint)}). Maximum is {mb(MAX_SDAT_BYTES)}."}]
        log.save()
        return log

    try:
        parser = etree.XMLParser(
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            huge_tree=False,
        )
        tree = etree.parse(file, parser)
        root = tree.getroot()
    except Exception as exc:
        log.rows_total = 0
        log.rows_imported = 0
        log.rows_skipped = 0
        log.errors = [{"error": f"Malformed SDAT-CH XML: {exc}"}]
        log.save()
        return log

    meter_lookup = {
        mp.meter_id: mp
        for mp in MeteringPoint.objects.filter(zev=zev)
    }

    rows_total = 0
    imported = 0
    skipped = 0
    errors = []

    # Each MeteringData document may contain multiple MeteringPoint sections
    for mp_elem in root.iter("{*}MeteringPoint"):
        meter_id_elem = mp_elem.find("{*}MeteringPointID")
        if meter_id_elem is None:
            meter_id_elem = mp_elem.find("{*}ID")
        if meter_id_elem is None:
            continue
        meter_id = (meter_id_elem.text or "").strip()
        mp = meter_lookup.get(meter_id)
        if mp is None:
            add_error(errors, {"meter_id": meter_id, "error": "Metering point not found in ZEV."})
            continue

        for interval in mp_elem.iter("{*}Interval"):
            # Determine start timestamp and resolution
            start_elem = interval.find("{*}Start")
            if start_elem is None:
                start_elem = interval.find("{*}StartDateTime")
            resolution_elem = interval.find("{*}Resolution")
            if resolution_elem is None:
                resolution_elem = interval.find("{*}Duration")
            if start_elem is None:
                continue

            try:
                start_ts = _parse_ts(start_elem.text.strip())
            except Exception as exc:
                add_error(errors, {"error": f"Invalid timestamp {start_elem.text}: {exc}"})
                continue

            # Resolution in minutes (default 15)
            res_minutes = 15
            if resolution_elem is not None and resolution_elem.text:
                txt = resolution_elem.text.strip().upper()
                if "PT15M" in txt:
                    res_minutes = 15
                elif "PT30M" in txt:
                    res_minutes = 30
                elif "PT60M" in txt or "PT1H" in txt:
                    res_minutes = 60

            for i, obs in enumerate(interval.iter("{*}Observation")):
                rows_total += 1
                qty_elem = obs.find("{*}Volume")
                if qty_elem is None:
                    qty_elem = obs.find("{*}Quantity")
                dir_elem = obs.find("{*}Direction")
                if dir_elem is None:
                    dir_elem = obs.find("{*}EnergyFlowDirection")
                if qty_elem is None:
                    skipped += 1
                    continue
                try:
                    energy = Decimal(qty_elem.text.strip()).quantize(Decimal("0.0001"))
                    direction = "out" if (dir_elem is not None and "OUT" in (dir_elem.text or "").upper()) else "in"
                    ts = start_ts + timedelta(minutes=res_minutes * i)
                    _, created = MeterReading.objects.get_or_create(
                        metering_point=mp,
                        timestamp=ts,
                        direction=direction,
                        defaults={
                            "energy_kwh": energy,
                            "import_source": ImportSource.SDATCH,
                            "import_batch": batch_id,
                        },
                    )
                    if created:
                        imported += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    skipped += 1
                    add_error(errors, {"error": str(exc)})
    log.rows_total = rows_total
    log.rows_imported = imported
    log.rows_skipped = skipped
    log.errors = errors
    log.save()
    return log
