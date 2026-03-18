"""
CSV / Excel metering data importer.

Supported formats:
    1) standard: one reading per row (meter_id, timestamp, energy_kwh, optional direction)
    2) daily_15min: one day per row (meter_id, date, then 96 quarter-hour energy values)

Both formats support header-based mapping and index-based mapping for headerless files.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import pandas as pd

from metering.models import ImportLog, ImportSource, MeterReading
from zev.models import MeteringPoint, Zev

DEFAULT_COLUMN_MAP = {
    "meter_id": "meter_id",
    "timestamp": "timestamp",
    "energy_kwh": "energy_kwh",
    "direction": "direction",
    "energy_start": "4",
}


def _to_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _read_dataframe(file, *, has_header=True, delimiter=","):
    if hasattr(file, "name") and file.name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file, header=0 if has_header else None)
    return pd.read_csv(file, sep=delimiter, header=0 if has_header else None)


def _resolve_column(df, ref):
    if ref is None:
        return None
    key = str(ref).strip()
    if not key:
        return None
    if key in df.columns:
        return key
    if key.isdigit():
        idx = int(key)
        if idx < 0 or idx >= len(df.columns):
            raise KeyError(f"Column index {idx} is out of range (0..{len(df.columns)-1}).")
        return df.columns[idx]
    raise KeyError(f"Column '{key}' not found.")


def _parse_decimal(raw_value):
    if pd.isna(raw_value):
        raise InvalidOperation("Missing numeric value")
    value_str = str(raw_value).strip()
    if not value_str:
        raise InvalidOperation("Empty numeric value")
    value_str = value_str.replace(",", ".")
    return Decimal(value_str).quantize(Decimal("0.0001"))


def _infer_direction_and_energy(meter_type, energy, explicit_direction=None):
    if explicit_direction in {"in", "out"}:
        return explicit_direction, abs(energy)

    if meter_type == "production":
        return "out", abs(energy)
    if meter_type == "bidirectional":
        return ("in" if energy >= 0 else "out"), abs(energy)
    return "in", abs(energy)


def _meter_queryset_for_user(user, zev=None):
    qs = MeteringPoint.objects.select_related("zev")
    if zev is not None:
        return qs.filter(zev=zev)
    if user.is_admin:
        return qs
    if user.is_zev_owner:
        return qs.filter(zev__owner=user)
    return qs.none()


def _resolve_columns(df, col, required_keys):
    missing_mapping_keys = [key for key in required_keys if key not in col or not col.get(key)]
    if missing_mapping_keys:
        return None, f"Missing required column mappings for: {', '.join(missing_mapping_keys)}"

    resolved_cols = {}
    try:
        for key in required_keys:
            resolved_cols[key] = _resolve_column(df, col[key])
    except KeyError as exc:
        return None, str(exc)

    try:
        direction_ref = col.get("direction")
        resolved_cols["direction"] = _resolve_column(df, direction_ref) if direction_ref else None
    except KeyError:
        resolved_cols["direction"] = None

    return resolved_cols, None


def _build_day_start(raw_day, timestamp_format):
    if timestamp_format:
        day_dt = datetime.strptime(str(raw_day).strip(), timestamp_format)
    else:
        day_dt = pd.to_datetime(raw_day, dayfirst=True).to_pydatetime()
    return datetime(day_dt.year, day_dt.month, day_dt.day, tzinfo=timezone.utc)


def _infer_log_zev(explicit_zev, touched_metering_points):
    if explicit_zev is not None:
        return explicit_zev
    zev_ids = {mp.zev_id for mp in touched_metering_points}
    if len(zev_ids) == 1:
        return Zev.objects.filter(id=next(iter(zev_ids))).first()
    return None


def preview_csv(
    file,
    user,
    *,
    zev=None,
    column_map=None,
    timestamp_format=None,
    has_header=True,
    delimiter=",",
    format_profile="standard",
    interval_minutes=15,
    values_count=96,
    max_rows=30,
):
    col = {**DEFAULT_COLUMN_MAP, **(column_map or {})}
    has_header = _to_bool(has_header, default=True)
    df = _read_dataframe(file, has_header=has_header, delimiter=delimiter or ",")

    required_keys = ["meter_id", "timestamp", "energy_kwh"] if format_profile == "standard" else ["meter_id", "timestamp", "energy_start"]
    resolved_cols, column_error = _resolve_columns(df, col, required_keys)
    if column_error:
        return {
            "rows_total": len(df),
            "preview_rows": [],
            "summary": {"existing_metering_points": 0, "missing_metering_points": 0, "rows_previewed": 0},
            "errors": [{"row": None, "error": column_error}],
        }

    meter_lookup = {mp.meter_id: mp for mp in _meter_queryset_for_user(user, zev=zev)}
    preview_rows = []
    existing_mps = 0
    missing_mps = 0

    for idx, row in df.head(max_rows).iterrows():
        row_number = idx + (2 if has_header else 1)
        meter_id = None if pd.isna(row[resolved_cols["meter_id"]]) else str(row[resolved_cols["meter_id"]]).strip()
        mp = meter_lookup.get(meter_id or "")
        exists = mp is not None
        if exists:
            existing_mps += 1
        else:
            missing_mps += 1

        if format_profile == "daily_15min":
            date_value = None
            existing_data = False
            if exists and not pd.isna(row[resolved_cols["timestamp"]]):
                try:
                    day_start = _build_day_start(row[resolved_cols["timestamp"]], timestamp_format)
                    day_end = day_start + timedelta(days=1)
                    existing_data = MeterReading.objects.filter(
                        metering_point=mp,
                        timestamp__gte=day_start,
                        timestamp__lt=day_end,
                    ).exists()
                    date_value = day_start.date().isoformat()
                except Exception:
                    date_value = str(row[resolved_cols["timestamp"]])
            elif not pd.isna(row[resolved_cols["timestamp"]]):
                date_value = str(row[resolved_cols["timestamp"]])

            preview_rows.append(
                {
                    "row": row_number,
                    "meter_id": meter_id,
                    "metering_point_exists": exists,
                    "meter_type": mp.meter_type if mp else None,
                    "timestamp": date_value,
                    "existing_data": existing_data,
                    "interval_minutes": interval_minutes,
                    "values_count": values_count,
                }
            )
            continue

        timestamp_value = None if pd.isna(row[resolved_cols["timestamp"]]) else str(row[resolved_cols["timestamp"]])
        energy_value = None if pd.isna(row[resolved_cols["energy_kwh"]]) else str(row[resolved_cols["energy_kwh"]])
        preview_rows.append(
            {
                "row": row_number,
                "meter_id": meter_id,
                "metering_point_exists": exists,
                "meter_type": mp.meter_type if mp else None,
                "timestamp": timestamp_value,
                "energy": energy_value,
            }
        )

    return {
        "rows_total": len(df),
        "preview_rows": preview_rows,
        "summary": {
            "existing_metering_points": existing_mps,
            "missing_metering_points": missing_mps,
            "rows_previewed": len(preview_rows),
        },
        "errors": [],
    }


def import_csv(
    file,
    user,
    *,
    zev=None,
    column_map=None,
    timestamp_format=None,
    has_header=True,
    delimiter=",",
    format_profile="standard",
    interval_minutes=15,
    values_count=96,
    overwrite_existing=False,
):
    """Import metering readings from a CSV or Excel file and return an ImportLog instance."""
    col = {**DEFAULT_COLUMN_MAP, **(column_map or {})}
    batch_id = uuid.uuid4()

    has_header = _to_bool(has_header, default=True)
    overwrite_existing = _to_bool(overwrite_existing, default=False)
    df = _read_dataframe(file, has_header=has_header, delimiter=delimiter or ",")

    log = ImportLog.objects.create(
        batch_id=batch_id,
        zev=zev,
        imported_by=user,
        source=ImportSource.CSV,
        filename=getattr(file, "name", "upload"),
        rows_total=len(df),
    )

    required_keys = ["meter_id", "timestamp", "energy_kwh"] if format_profile == "standard" else ["meter_id", "timestamp", "energy_start"]
    resolved_cols, column_error = _resolve_columns(df, col, required_keys)
    if column_error:
        log.rows_imported = 0
        log.rows_skipped = len(df)
        log.errors = [{"row": None, "error": column_error}]
        log.save()
        return log

    meter_lookup = {mp.meter_id: mp for mp in _meter_queryset_for_user(user, zev=zev)}

    imported = 0
    skipped = 0
    overwritten = 0
    errors = []
    touched_metering_points = set()

    for idx, row in df.iterrows():
        row_number = idx + (2 if has_header else 1)
        try:
            if pd.isna(row[resolved_cols["meter_id"]]):
                skipped += 1
                errors.append({"row": row_number, "error": "Missing meter_id value."})
                continue

            meter_id = str(row[resolved_cols["meter_id"]]).strip()
            if not meter_id:
                skipped += 1
                errors.append({"row": row_number, "error": "Empty meter_id value."})
                continue

            mp = meter_lookup.get(meter_id)
            if mp is None:
                skipped += 1
                errors.append(
                    {
                        "row": row_number,
                        "error": f"Metering point '{meter_id}' not found or not accessible.",
                    }
                )
                continue

            touched_metering_points.add(mp)

            if format_profile == "daily_15min":
                raw_day = row[resolved_cols["timestamp"]]
                if pd.isna(raw_day):
                    skipped += 1
                    errors.append({"row": row_number, "error": "Missing date value for daily profile."})
                    continue

                day_start = _build_day_start(raw_day, timestamp_format)
                start_pos = list(df.columns).index(resolved_cols["energy_start"])

                for slot in range(values_count):
                    col_pos = start_pos + slot
                    if col_pos >= len(df.columns):
                        skipped += 1
                        errors.append(
                            {
                                "row": row_number,
                                "error": (
                                    f"Missing interval column at position {col_pos} "
                                    f"(slot {slot + 1}/{values_count})."
                                ),
                            }
                        )
                        continue

                    raw_energy = row.iloc[col_pos]
                    if pd.isna(raw_energy) or str(raw_energy).strip() == "":
                        continue

                    energy_raw = _parse_decimal(raw_energy)
                    direction, energy = _infer_direction_and_energy(mp.meter_type, energy_raw)
                    ts = day_start + timedelta(minutes=interval_minutes * slot)

                    if overwrite_existing:
                        _, created = MeterReading.objects.update_or_create(
                            metering_point=mp,
                            timestamp=ts,
                            direction=direction,
                            defaults={
                                "energy_kwh": energy,
                                "import_source": ImportSource.CSV,
                                "import_batch": batch_id,
                            },
                        )
                        if created:
                            imported += 1
                        else:
                            overwritten += 1
                    else:
                        _, created = MeterReading.objects.get_or_create(
                            metering_point=mp,
                            timestamp=ts,
                            direction=direction,
                            defaults={
                                "energy_kwh": energy,
                                "import_source": ImportSource.CSV,
                                "import_batch": batch_id,
                            },
                        )
                        if created:
                            imported += 1
                        else:
                            skipped += 1
                            errors.append(
                                {
                                    "row": row_number,
                                    "error": (
                                        "Duplicate reading for metering_point + timestamp + direction "
                                        f"(slot {slot + 1}/{values_count})."
                                    ),
                                }
                            )
                continue

            raw_ts = row[resolved_cols["timestamp"]]
            if pd.isna(raw_ts):
                skipped += 1
                errors.append({"row": row_number, "error": "Missing timestamp value."})
                continue

            if timestamp_format:
                ts = datetime.strptime(str(raw_ts), timestamp_format).replace(tzinfo=timezone.utc)
            elif isinstance(raw_ts, datetime):
                ts = raw_ts if raw_ts.tzinfo else raw_ts.replace(tzinfo=timezone.utc)
            else:
                ts = pd.to_datetime(raw_ts, utc=True).to_pydatetime()

            energy_raw = _parse_decimal(row[resolved_cols["energy_kwh"]])

            explicit_direction = None
            direction_col = resolved_cols.get("direction")
            if direction_col is not None:
                raw_direction = row.get(direction_col)
                if not pd.isna(raw_direction):
                    explicit_direction = str(raw_direction).strip().lower()
                    if explicit_direction and explicit_direction not in {"in", "out"}:
                        skipped += 1
                        errors.append(
                            {
                                "row": row_number,
                                "error": f"Invalid direction '{explicit_direction}'. Expected 'in' or 'out'.",
                            }
                        )
                        continue

            direction, energy = _infer_direction_and_energy(mp.meter_type, energy_raw, explicit_direction)

            if overwrite_existing:
                _, created = MeterReading.objects.update_or_create(
                    metering_point=mp,
                    timestamp=ts,
                    direction=direction,
                    defaults={
                        "energy_kwh": energy,
                        "import_source": ImportSource.CSV,
                        "import_batch": batch_id,
                    },
                )
                if created:
                    imported += 1
                else:
                    overwritten += 1
            else:
                _, created = MeterReading.objects.get_or_create(
                    metering_point=mp,
                    timestamp=ts,
                    direction=direction,
                    defaults={
                        "energy_kwh": energy,
                        "import_source": ImportSource.CSV,
                        "import_batch": batch_id,
                    },
                )
                if created:
                    imported += 1
                else:
                    skipped += 1
                    errors.append(
                        {
                            "row": row_number,
                            "error": "Duplicate reading for metering_point + timestamp + direction.",
                        }
                    )
        except (KeyError, InvalidOperation, ValueError) as exc:
            errors.append({"row": row_number, "error": str(exc)})
            skipped += 1

    log.zev = _infer_log_zev(zev, touched_metering_points)
    log.rows_imported = imported + overwritten
    log.rows_skipped = skipped
    if overwritten > 0:
        errors.insert(0, {"row": None, "error": f"Overwrote {overwritten} existing readings."})
    log.errors = errors
    log.save()
    return log
