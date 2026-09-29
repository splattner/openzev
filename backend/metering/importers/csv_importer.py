"""
CSV / Excel metering data importer.

Supported formats:
    1) standard: one reading per row (meter_id, timestamp, energy_kwh, optional direction)
    2) daily_15min: one day per row (meter_id, date, then 96 quarter-hour energy values)

Both formats support header-based mapping and index-based mapping for headerless files.
"""

import csv
import io
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation

import openpyxl
from dateutil import parser as dateutil_parser
from django.conf import settings
from django.db import IntegrityError, transaction

from metering.importers.limits import (
    MAX_REPORTED_ERRORS,
    MAX_UPLOAD_BYTES,
    TRUNCATION_NOTE,
    add_error,
    mb,
    validate_zip,
)
from metering.models import ImportLog, ImportSource, MeterReading
from zev.models import MeteringPoint

# Upload hardening limits — rationale: docs/specs/2026-03-metering-import-and-quality.md §4.4.
MAX_CSV_BYTES = MAX_UPLOAD_BYTES
MAX_CSV_ROWS = getattr(settings, "IMPORT_MAX_ROWS", 200_000)
MAX_CSV_COLUMNS = 1_500
MAX_VALUES_COUNT = 1440  # one value per minute per day
# Timestamp __in chunk size for the standard-profile existence prefetch:
# well below SQLite's 999 and PostgreSQL's 32767 parameter limits.
_STANDARD_PREFETCH_CHUNK = 500
MAX_ENERGY_KWH = Decimal("99999999.9999")  # MeterReading.energy_kwh bound (max_digits=12, decimal_places=4)
MAX_XLSX_DECOMPRESSED_BYTES = 50 * 1024 * 1024  # decompressed budget, deliberately not aliased to MAX_UPLOAD_BYTES
MAX_XLSX_MEMBERS = 200
MAX_XLSX_RATIO = 500

DEFAULT_COLUMN_MAP = {
    "meter_id": "meter_id",
    "timestamp": "timestamp",
    "energy_kwh": "energy_kwh",
    "direction": "direction",
    "energy_start": "4",
}


class ImportFileError(ValueError):
    """The uploaded file could not be read at all (bad format, encoding or delimiter)."""


# Zones an offset-less timestamp may be declared in (ADR 0026). Swiss sources
# export Swiss local time; UTC is for the few that export UTC without saying so.
TIMESTAMP_TIMEZONES = {"Europe/Zurich": ZoneInfo("Europe/Zurich"), "UTC": timezone.utc}
DEFAULT_TIMESTAMP_TIMEZONE = "Europe/Zurich"


class NonexistentLocalTime(ValueError):
    """A wall-clock time inside the spring DST gap (02:00–02:59 on the switch day)."""


@dataclass(frozen=True)
class DstGapSkip:
    """A zero-energy row at a non-existent local time: skipped with a warning."""

    day: date


@dataclass(frozen=True)
class DayWindow:
    """A daily-profile row's civil day and its [start, end) as UTC instants."""

    day: date
    start: datetime
    end: datetime


class TimestampReader:
    """Reads one file's timestamps into UTC instants (ADR 0026).

    A value with an offset is converted as written. An offset-less value is a
    wall-clock time in the declared zone. In Europe/Zurich the autumn DST hour
    occurs twice: per series (meter and direction), in file order, the first
    occurrence is summer time and the second winter time. The spring hour does
    not exist at all and raises ``NonexistentLocalTime``.

    The repeated-hour rule keeps state, so every pass over a file (prefetch,
    preview, import) uses a fresh reader and visits the rows in file order.
    """

    def __init__(self, timestamp_format=None, zone_name=DEFAULT_TIMESTAMP_TIMEZONE):
        self.timestamp_format = timestamp_format
        self.zone = TIMESTAMP_TIMEZONES[zone_name]
        self._occurrences: dict = {}

    @property
    def is_local(self):
        return self.zone is not timezone.utc

    def parse(self, raw_value):
        """Aware UTC datetime for a value with an offset; naive wall clock otherwise."""
        if isinstance(raw_value, datetime):
            return raw_value.astimezone(timezone.utc) if raw_value.tzinfo else raw_value
        text = "" if raw_value is None else str(raw_value).strip()
        try:
            if self.timestamp_format:
                parsed = datetime.strptime(text, self.timestamp_format)
            else:
                parsed = _parse_flexible(text)
        except (ValueError, TypeError, OverflowError):
            preview = text[:100] + ("…" if len(text) > 100 else "")
            raise ValueError(f"Invalid timestamp value '{preview}'.") from None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed

    def resolve(self, parsed, series_key=None):
        """The UTC instant for a value from ``parse``."""
        if parsed.tzinfo is not None:
            return parsed
        if not self.is_local:
            return parsed.replace(tzinfo=timezone.utc)
        summer = parsed.replace(tzinfo=self.zone, fold=0)
        instant = summer.astimezone(timezone.utc)
        if instant.astimezone(self.zone).replace(tzinfo=None) != parsed:
            raise NonexistentLocalTime(parsed)
        winter = parsed.replace(tzinfo=self.zone, fold=1)
        if summer.utcoffset() != winter.utcoffset():
            key = (series_key, parsed)
            seen = self._occurrences.get(key, 0)
            self._occurrences[key] = seen + 1
            if seen:
                return winter.astimezone(timezone.utc)
        return instant

    def day_window(self, raw_day):
        """The civil day a daily-profile row covers."""
        if isinstance(raw_day, datetime):
            day = raw_day.date()
        else:
            text = "" if raw_day is None else str(raw_day).strip()
            try:
                if self.timestamp_format:
                    day = datetime.strptime(text, self.timestamp_format).date()
                else:
                    # Preserve unambiguous ISO dates; fall back to day-first parsing for
                    # European CSV exports such as 07.01.2026 or 07/01/2026.
                    iso_like = text[:10].count("-") == 2 and text[:4].isdigit()
                    day = _parse_flexible(text, dayfirst=not iso_like).date()
            except (ValueError, TypeError, OverflowError):
                preview = text[:100] + ("…" if len(text) > 100 else "")
                raise ValueError(f"Invalid date value '{preview}'.") from None
        next_day = day + timedelta(days=1)
        start = datetime(day.year, day.month, day.day, tzinfo=self.zone)
        end = datetime(next_day.year, next_day.month, next_day.day, tzinfo=self.zone)
        return DayWindow(day, start.astimezone(timezone.utc), end.astimezone(timezone.utc))


def _coerce_timestamp_timezone(value):
    """Validate the declared zone for offset-less timestamps; default Europe/Zurich."""
    name = DEFAULT_TIMESTAMP_TIMEZONE if value in (None, "") else str(value).strip()
    if name not in TIMESTAMP_TIMEZONES:
        raise ImportFileError(f"timestamp_timezone must be one of {', '.join(TIMESTAMP_TIMEZONES)}.")
    return name


def _day_length_error(window, slots, provided):
    length = window.end - window.start
    kind = ""
    if length < timedelta(hours=24):
        kind = " (DST start)"
    elif length > timedelta(hours=24):
        kind = " (DST end)"
    return (
        f"{window.day.isoformat()} has {slots} intervals in Swiss time{kind}, "
        f"but the row has {provided} values."
    )


def _fit_daily_values(values, window, interval_minutes, local):
    """The row's values for the slots its civil day really has.

    Returns ``(values, error)``. A Swiss day has 92, 96 or 100 quarter-hours.
    Surplus trailing empty columns are dropped (a 100-column file on an
    ordinary day); on the spring DST day a row that still lists the missing
    02:00 hour may leave it empty or zero, and it is dropped. A 25-hour day
    needs all its values. Rows shorter than an ordinary day are kept as they
    are — partial days are allowed. UTC files keep their values unchanged.
    """
    if not local:
        return values, None
    interval = timedelta(minutes=interval_minutes)
    length = window.end - window.start
    if length % interval:
        return values, None
    slots = length // interval
    provided = len(values)
    if provided > slots:
        fitted = list(values)
        while len(fitted) > slots and fitted[-1] is None:
            fitted.pop()
        hour = timedelta(hours=1)
        if len(fitted) > slots and length < timedelta(hours=24) and not hour % interval:
            per_hour = hour // interval
            first = 2 * per_hour
            missing = fitted[first:first + per_hour]
            if len(fitted) - slots == per_hour and all(v is None or v == 0 for v in missing):
                fitted = fitted[:first] + fitted[first + per_hour:]
        if len(fitted) > slots:
            return None, _day_length_error(window, slots, provided)
        return fitted, None
    if slots > provided >= timedelta(hours=24) // interval:
        return None, _day_length_error(window, slots, provided)
    return values, None


@dataclass
class Table:
    """A parsed spreadsheet: column labels plus rows of raw cell values.

    Rows are padded to ``width`` so positional access is always safe. Labels are
    kept as read — strings for a headered file, integers for a headerless one.
    """

    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)

    @property
    def width(self):
        return len(self.columns)


def _to_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalise_delimiter(delimiter):
    if not delimiter:
        return ","
    # The UI exposes a free-text delimiter field, where a tab cannot be typed.
    if delimiter == "\\t":
        return "\t"
    if len(delimiter) != 1:
        raise ImportFileError(
            f"Delimiter must be a single character (got {delimiter!r}). Use '\\t' for a tab."
        )
    return delimiter


def _build_table(raw_rows, *, has_header):
    if not raw_rows:
        return Table()
    if has_header:
        columns, data = list(raw_rows[0]), raw_rows[1:]
    else:
        # Like pandas, the column count is fixed by the first row.
        columns, data = list(range(len(raw_rows[0]))), raw_rows
    width = len(columns)
    rows = [
        list(row) + [None] * (width - len(row)) if len(row) < width else list(row)
        for row in data
    ]
    return Table(columns=columns, rows=rows)


def _read_csv_table(file, *, has_header, delimiter, limit=None):
    # The file is decoded incrementally (no up-front read().decode() pass);
    # blank rows are skipped the way pandas does.
    size_hint = getattr(file, "size", None)
    if size_hint is not None and size_hint > MAX_CSV_BYTES:
        raise ImportFileError(f"File too large ({mb(size_hint)}). Maximum is {mb(MAX_CSV_BYTES)}.")

    file.seek(0)
    # Unwrap Django UploadedFile to the underlying stream for TextIOWrapper.
    binary = getattr(file, "file", file)

    rows = []
    # The header is not a data row, so a headered file may carry one extra row.
    row_cap = MAX_CSV_ROWS + (1 if has_header else 0)
    text_wrapper = None
    try:
        text_wrapper = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
        reader = csv.reader(text_wrapper, delimiter=delimiter)
        for row in reader:
            if not row:
                continue
            if limit is not None and len(rows) >= limit:
                break
            if len(row) > MAX_CSV_COLUMNS:
                raise ImportFileError(
                    f"Row {len(rows) + 1} has too many columns ({len(row)} > {MAX_CSV_COLUMNS})."
                )
            if len(rows) >= row_cap:
                raise ImportFileError(f"File has too many rows (exceeds {MAX_CSV_ROWS}).")
            rows.append(row)
    except UnicodeDecodeError as exc:
        raise ImportFileError(
            "File is not valid UTF-8. Re-export it as UTF-8 (in Excel: 'CSV UTF-8') and try again."
        ) from exc
    except csv.Error as exc:
        raise ImportFileError(f"CSV parse error: {exc}") from exc
    finally:
        # Detach (not close): the finalizer of a TextIOWrapper closes the
        # underlying stream, and the caller may still want to read the file.
        if text_wrapper is not None:
            text_wrapper.detach()

    return _build_table(rows, has_header=has_header)


def _read_xlsx_table(file, *, has_header, limit=None):
    # XLSX is a ZIP: validate members / decompressed size / ratio before
    # openpyxl inflates anything (sharedStrings.xml alone can be a bomb).
    file.seek(0)
    try:
        with zipfile.ZipFile(file) as zf:
            validate_zip(
                zf,
                label="Excel file",
                max_members=MAX_XLSX_MEMBERS,
                max_total_bytes=MAX_XLSX_DECOMPRESSED_BYTES,
                max_ratio=MAX_XLSX_RATIO,
                error_cls=ImportFileError,
            )
    except ImportFileError:
        raise
    except zipfile.BadZipFile as exc:
        raise ImportFileError(f"Could not read the Excel file: {exc}") from exc
    except Exception as exc:
        raise ImportFileError(f"Could not validate Excel archive: {exc}") from exc

    file.seek(0)
    try:
        workbook = openpyxl.load_workbook(file, read_only=True, data_only=True, keep_links=False)
    except Exception as exc:  # openpyxl raises a variety of types for bad files
        raise ImportFileError(f"Could not read the Excel file: {exc}") from exc
    try:
        # pandas reads sheet index 0, which is not necessarily the sheet that was
        # selected when the workbook was saved (openpyxl's ``active``).
        sheet = workbook.worksheets[0]
        # A headered sheet carries one extra row beyond the data-row cap.
        row_cap = MAX_CSV_ROWS + (1 if has_header else 0)
        raw_rows = []
        for row in sheet.iter_rows(values_only=True):
            if limit is not None and len(raw_rows) >= limit:
                break
            if len(raw_rows) >= row_cap:
                raise ImportFileError(
                    f"Excel sheet has too many rows (exceeds {MAX_CSV_ROWS})."
                )
            if len(row) > MAX_CSV_COLUMNS:
                raise ImportFileError(
                    f"Excel sheet has too many columns ({len(row)} > {MAX_CSV_COLUMNS})."
                )
            raw_rows.append(list(row))
    finally:
        workbook.close()

    # pandas trims trailing all-empty rows but keeps mid-file ones.
    while raw_rows and all(cell is None for cell in raw_rows[-1]):
        raw_rows.pop()
    return _build_table(raw_rows, has_header=has_header)


def _read_table(file, *, has_header=True, delimiter=",", limit=None):
    name = (getattr(file, "name", "") or "").lower()
    if name.endswith(".xls"):
        raise ImportFileError(
            "Legacy .xls files are not supported. Please save the file as .xlsx or CSV."
        )
    if name.endswith(".xlsx"):
        return _read_xlsx_table(file, has_header=has_header, limit=limit)
    return _read_csv_table(
        file, has_header=has_header, delimiter=_normalise_delimiter(delimiter), limit=limit
    )


def _is_missing(value):
    """True for cells pandas would have reported as NA.

    Note that whitespace-only cells are *not* missing: callers distinguish an
    absent value from a blank one (``Missing`` vs ``Empty`` errors).
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    return isinstance(value, float) and value != value


def _cell(row, position):
    """Positional access that returns None on a miss, like ``Series.get``."""
    if position is None or position < 0 or position >= len(row):
        return None
    return row[position]


def _csv_error(row_number, meter_id, error):
    """Row error payload; meter_id is attached when the row names a meter."""
    payload = {"row": row_number, "error": error}
    if meter_id is not None:
        payload["meter_id"] = meter_id
    return payload


def _parse_flexible(text, *, dayfirst=False):
    """Parse a date/datetime string, preferring ISO-8601 then falling back to dateutil."""
    if not dayfirst:
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
    return dateutil_parser.parse(text, dayfirst=dayfirst)


def _parse_datetime_utc(raw_value):
    """Parse a timestamp that is UTC unless it says otherwise (transfer archives)."""
    parsed = _parse_flexible(str(raw_value).strip())
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _interpret_standard_row(row, *, resolved_cols, reader, meter_type, series_key=None):
    """Shared standard-row interpretation for preview and import.

    Returns ``(timestamp, direction, energy, error)`` — error is None on
    success, a ``DstGapSkip`` for a zero-energy row inside the spring DST gap,
    otherwise the exact user-facing message both paths report, so preview and
    import agree on every standard row by construction. ``series_key`` (the
    meter id) scopes the autumn repeated-hour rule, together with the
    direction.
    """
    raw_ts = row[resolved_cols["timestamp"]]
    if _is_missing(raw_ts):
        return None, None, None, "Missing timestamp value."
    try:
        parsed = reader.parse(raw_ts)
    except (ValueError, TypeError, OverflowError) as exc:
        return None, None, None, str(exc)
    try:
        energy_raw = _parse_decimal(row[resolved_cols["energy_kwh"]])
    except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
        return None, None, None, str(exc)
    explicit_direction, direction_error = _row_direction(row, resolved_cols)
    if direction_error is not None:
        return None, None, None, direction_error
    direction, energy = _infer_direction_and_energy(meter_type, energy_raw, explicit_direction)
    try:
        ts = reader.resolve(parsed, (series_key, direction))
    except NonexistentLocalTime:
        if energy == 0:
            return None, direction, energy, DstGapSkip(parsed.date())
        return None, None, None, f"Timestamp {str(raw_ts).strip()[:100]} does not exist in Swiss time (DST start)."
    return ts, direction, energy, None


def _resolve_column(table, ref):
    """Resolve a column reference to a *position*.

    A reference is either a literal column label or a decimal index. Returning a
    position rather than a label keeps row access uniform for both the named
    columns and the positional interval slots.
    """
    if ref is None:
        return None
    key = str(ref).strip()
    if not key:
        return None
    if key in table.columns:
        return table.columns.index(key)
    if key.isdigit():
        idx = int(key)
        if idx < 0 or idx >= table.width:
            raise KeyError(f"Column index {idx} is out of range (0..{table.width - 1}).")
        return idx
    raise KeyError(f"Column '{key}' not found.")


def _parse_decimal(raw_value):
    if _is_missing(raw_value):
        raise InvalidOperation("Missing numeric value")
    value_str = str(raw_value).strip()
    if not value_str:
        raise InvalidOperation("Empty numeric value")
    value_str = value_str.replace(",", ".")
    try:
        value = Decimal(value_str).quantize(Decimal("0.0001"))
    except InvalidOperation:
        # Otherwise the raw conversion code ("[<class 'decimal.ConversionSyntax'>]")
        # leaks into user-facing error lists.
        raise InvalidOperation(f"Invalid numeric value '{value_str}'") from None
    # Decimal happily accepts "nan"/"NaN", which would otherwise reach the
    # database as a non-finite value. ("inf" already fails in quantize.)
    if not value.is_finite():
        raise InvalidOperation(f"Invalid numeric value '{value_str}'")
    # MeterReading.energy_kwh is max_digits=12/decimal_places=4 (at most
    # 99999999.9999). Reject larger magnitudes here — shared by preview and
    # import — so no DataError can escape the import transaction on
    # PostgreSQL (SQLite does not enforce the bound).
    if abs(value) > MAX_ENERGY_KWH:
        raise InvalidOperation(f"Numeric value '{value_str}' exceeds the maximum of 99999999.9999 kWh.")
    return value


# OBIS identifiers as VNB exports write them: an optional medium/channel prefix
# ("1-1:"), the C.D.E value groups, and an optional tariff suffix ("*255") —
# e.g. "1-1:1.29.0*255". The C group carries the flow direction for active
# energy: 1 = positive (grid import / consumption), 2 = negative (feed-in).
# Reactive energy (3/4) and every other group are rejected rather than guessed.
_OBIS_RE = re.compile(r"^(?:\d+-\d+:)?(\d+)\.(\d+)\.(\d+)(?:\*\d+)?$")
_OBIS_DIRECTIONS = {"1": "in", "2": "out"}
_DIRECTION_HINT = "Expected 'in', 'out', or an OBIS code such as 1.29.0 (in) or 2.29.0 (out)."


def _parse_direction_token(raw):
    """Map one direction cell to ``in``/``out``.

    Returns ``(direction, error)``; exactly one is None. Accepts the literal
    ``in``/``out`` and the OBIS identifiers VNB profile exports carry in their
    own column, so a file whose only consumption/feed-in discriminator is the
    OBIS code imports without renaming columns.
    """
    token = str(raw).strip()
    if not token:
        return None, None
    lowered = token.lower()
    if lowered in {"in", "out"}:
        return lowered, None
    match = _OBIS_RE.match(token)
    if match is not None:
        direction = _OBIS_DIRECTIONS.get(match.group(1))
        if direction is not None:
            return direction, None
    return None, f"Invalid direction '{token}'. {_DIRECTION_HINT}"


def _row_direction(row, resolved_cols):
    """Explicit direction for a row, from the mapped direction column.

    ``(None, None)`` when no column is mapped or the cell is empty — the
    caller then falls back to meter-type inference.
    """
    direction_col = resolved_cols.get("direction")
    if direction_col is None:
        return None, None
    raw = _cell(row, direction_col)
    if _is_missing(raw):
        return None, None
    return _parse_direction_token(raw)


def _infer_direction_and_energy(meter_type, energy, explicit_direction=None):
    if explicit_direction in {"in", "out"}:
        return explicit_direction, abs(energy)

    if meter_type == "production":
        return "out", abs(energy)
    if meter_type == "bidirectional":
        return ("in" if energy >= 0 else "out"), abs(energy)
    return "in", abs(energy)


def _meter_queryset_for_user(user, zev):
    qs = MeteringPoint.objects.select_related("zev").filter(zev=zev)
    if user.is_admin:
        return qs
    if user.is_zev_owner:
        return qs.filter(zev__owner=user)
    if zev.owner_id is not None and zev.owner_id == user.id:
        return qs
    return qs.none()


def _resolve_columns(table, col, required_keys):
    missing_mapping_keys = [key for key in required_keys if key not in col or not col.get(key)]
    if missing_mapping_keys:
        return None, f"Missing required column mappings for: {', '.join(missing_mapping_keys)}"

    resolved_cols = {}
    try:
        for key in required_keys:
            resolved_cols[key] = _resolve_column(table, col[key])
    except KeyError as exc:
        return None, str(exc)

    direction_ref = col.get("direction")
    try:
        resolved_cols["direction"] = _resolve_column(table, direction_ref) if direction_ref else None
    except KeyError as exc:
        # The default reference is lenient: most files carry no direction
        # column, and falling back to meter-type inference is correct there.
        # A reference the caller chose is not — silently dropping it sends a
        # feed-in file to `in` and collides with the consumption file for the
        # same metering point, so report it as the configuration error it is.
        if str(direction_ref).strip() != DEFAULT_COLUMN_MAP["direction"]:
            return None, str(exc)
        resolved_cols["direction"] = None

    return resolved_cols, None


def _check_timestamp_format(timestamp_format):
    if not timestamp_format:
        return None
    if "%" not in str(timestamp_format):
        return f"Invalid timestamp format '{timestamp_format}'."
    try:
        fmt = str(timestamp_format)
        # Probe with a timezone-aware datetime so offset-bearing formats
        # (%z/%Z) round-trip instead of being rejected by an empty offset.
        probe = datetime(2000, 1, 2, 3, 4, 5, tzinfo=timezone.utc).strftime(fmt)
        parsed = datetime.strptime(probe, fmt)
        # The format must capture the full calendar date: a year-less
        # format (e.g. "%d.%m") parses to 1900 and would silently shift data.
        if (parsed.year, parsed.month, parsed.day) != (2000, 1, 2):
            return f"Invalid timestamp format '{timestamp_format}'."
    except (ValueError, TypeError):
        return f"Invalid timestamp format '{timestamp_format}'."
    return None


def _coerce_values_count(values_count):
    """Bounds the per-row slot loop."""
    try:
        values_count = int(values_count)
    except (TypeError, ValueError):
        raise ImportFileError(f"values_count must be an integer (got {values_count!r}).")
    if values_count < 1 or values_count > MAX_VALUES_COUNT:
        raise ImportFileError(
            f"values_count must be between 1 and {MAX_VALUES_COUNT} (got {values_count})."
        )
    return values_count


def _coerce_interval_minutes(interval_minutes):
    """Timestamps are spaced by this many minutes."""
    try:
        interval_minutes = int(interval_minutes)
    except (TypeError, ValueError):
        raise ImportFileError(f"interval_minutes must be an integer (got {interval_minutes!r}).")
    if interval_minutes < 1:
        raise ImportFileError("interval_minutes must be at least 1.")
    return interval_minutes


def _upsert_reading(mp, ts, direction, energy, batch_id, overwrite_existing):
    """Create the reading row, or update it when overwriting. True if created."""
    method = (
        MeterReading.objects.update_or_create
        if overwrite_existing
        else MeterReading.objects.get_or_create
    )
    _, created = method(
        metering_point=mp,
        timestamp=ts,
        direction=direction,
        defaults={
            "energy_kwh": energy,
            "import_source": ImportSource.CSV,
            "import_batch": batch_id,
        },
    )
    return created


def _contiguous_day_ranges(windows):
    """Coalesce day windows into half-open [start, end) ranges.

    Adjacent civil days share a boundary (one day's end is the next day's
    start), so contiguous blocks merge whatever each day's length.
    """
    ranges = []
    for window in sorted(windows, key=lambda w: w.start):
        if ranges and window.start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], window.end))
        else:
            ranges.append((window.start, window.end))
    return ranges


def _parse_daily_values(row, start_pos, values_count, width):
    """Shared daily-slot validation for preview and import.

    Returns ``(values, row_error)`` where values is a list of Decimal|None
    (None = missing slot) and row_error is a missing-column or invalid-numeric
    message. Empty rows are NOT an error here; callers check
    ``all(v is None)`` so preview and import agree on the empty-row message.
    """
    required_end = start_pos + values_count
    if required_end > width:
        return None, (
            f"Missing interval column at position {width} "
            f"(slot {width - start_pos + 1}/{values_count})."
        )
    values: list = []
    for slot in range(values_count):
        raw_energy = row[start_pos + slot]
        if _is_missing(raw_energy) or str(raw_energy).strip() == "":
            values.append(None)
            continue
        try:
            values.append(_parse_decimal(raw_energy))
        except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
            return None, str(exc)
    return values, None


def _daily_row_directions(row, start_pos, values_count, width, meter_type, explicit_direction=None):
    """Directions a daily row would import, for direction-aware existence checks."""
    directions: set[str] = set()
    for slot in range(values_count):
        col_pos = start_pos + slot
        if col_pos >= width:
            break
        raw_energy = row[col_pos] if col_pos < len(row) else None
        if _is_missing(raw_energy) or str(raw_energy).strip() == "":
            continue
        try:
            energy_raw = _parse_decimal(raw_energy)
        except InvalidOperation:
            continue
        direction, _ = _infer_direction_and_energy(meter_type, energy_raw, explicit_direction)
        directions.add(direction)
    return directions


def _fetch_existing_daily_set(mp_ids, min_start, max_end):
    """One range query for daily duplicate/existing checks: (mp_id, ts, direction)."""
    if not mp_ids or min_start is None or max_end is None:
        return set()
    rows = MeterReading.objects.filter(
        metering_point_id__in=list(mp_ids),
        timestamp__gte=min_start,
        timestamp__lt=max_end,
    ).values_list("metering_point_id", "timestamp", "direction")
    return set(rows)


def _prefetch_daily_existing(table, resolved_cols, meter_lookup, reader):
    """Fetch existing daily readings in one query per contiguous file-day block.

    Sparse files must not turn their earliest/latest dates into a large range
    query. Rows with unresolvable meters or dates are skipped here; the main
    loop reports them individually.
    """
    windows = set()
    mp_ids = set()
    for row in table.rows:
        try:
            raw_meter = row[resolved_cols["meter_id"]]
            raw_day = row[resolved_cols["timestamp"]]
        except (IndexError, TypeError):
            continue
        if _is_missing(raw_meter):
            continue
        meter_id = str(raw_meter).strip()
        mp = meter_lookup.get(meter_id) if meter_id else None
        if mp is None:
            continue
        try:
            window = reader.day_window(raw_day)
        except (ValueError, TypeError, OverflowError):
            continue
        mp_ids.add(mp.id)
        windows.add(window)
    if not mp_ids or not windows:
        return set()

    existing = set()
    for start, end in _contiguous_day_ranges(windows):
        existing.update(_fetch_existing_daily_set(mp_ids, start, end))
    return existing


def _prefetch_standard_existing(table, resolved_cols, meter_lookup, reader):
    """Fetch existing standard readings for one upload in bounded queries.

    Standard rows carry exact timestamps, so candidates are matched with
    timestamp ``__in`` filters (chunked to stay below DB parameter limits)
    and intersected in memory against the exact ``(mp_id, ts, direction)``
    keys. Rows with unresolvable meters or values are skipped here; the main
    loop reports them individually.
    """
    mp_ids: set = set()
    timestamps: set = set()
    directions: set = set()
    for row in table.rows:
        try:
            raw_meter = row[resolved_cols["meter_id"]]
        except (IndexError, TypeError):
            continue
        if _is_missing(raw_meter):
            continue
        meter_id = str(raw_meter).strip()
        mp = meter_lookup.get(meter_id) if meter_id else None
        if mp is None:
            continue
        ts, direction, _, error = _interpret_standard_row(
            row,
            resolved_cols=resolved_cols,
            reader=reader,
            meter_type=mp.meter_type,
            series_key=meter_id,
        )
        if error is not None:
            continue
        mp_ids.add(mp.id)
        timestamps.add(ts)
        directions.add(direction)
    if not mp_ids or not timestamps:
        return set()

    existing = set()
    ordered_timestamps = sorted(timestamps)
    for chunk_start in range(0, len(ordered_timestamps), _STANDARD_PREFETCH_CHUNK):
        chunk = ordered_timestamps[chunk_start : chunk_start + _STANDARD_PREFETCH_CHUNK]
        rows = MeterReading.objects.filter(
            metering_point_id__in=list(mp_ids),
            timestamp__in=chunk,
            direction__in=list(directions),
        ).values_list("metering_point_id", "timestamp", "direction")
        existing.update(rows)
    return existing


def preview_csv(
    file,
    user,
    *,
    zev,
    column_map=None,
    timestamp_format=None,
    has_header=True,
    delimiter=",",
    format_profile="standard",
    interval_minutes=15,
    values_count=96,
    max_rows=30,
    overwrite_existing=False,
    timestamp_timezone=DEFAULT_TIMESTAMP_TIMEZONE,
):
    col = {**DEFAULT_COLUMN_MAP, **(column_map or {})}
    has_header = _to_bool(has_header, default=True)
    overwrite_existing = _to_bool(overwrite_existing, default=False)
    interval_minutes = _coerce_interval_minutes(interval_minutes)
    values_count = _coerce_values_count(values_count)
    timestamp_timezone = _coerce_timestamp_timezone(timestamp_timezone)
    table = _read_table(file, has_header=has_header, delimiter=delimiter)

    required_keys = ["meter_id", "timestamp", "energy_kwh"] if format_profile == "standard" else ["meter_id", "timestamp", "energy_start"]
    resolved_cols, column_error = _resolve_columns(table, col, required_keys)
    format_error = _check_timestamp_format(timestamp_format)
    if column_error or format_error:
        return {
            "rows_total": len(table.rows),
            "preview_rows": [],
            "summary": {"existing_metering_points": 0, "missing_metering_points": 0, "rows_previewed": 0, "rows_skipped_existing": 0, "readings_existing": 0},
            "missing_meter_ids": [],
            "errors": [{"row": None, "error": error} for error in (column_error, format_error) if error],
            "timestamp_timezone": timestamp_timezone,
            "rows_skipped_dst_gap": 0,
        }

    meter_lookup = {mp.meter_id: mp for mp in _meter_queryset_for_user(user, zev)}
    preview_rows: list[dict] = []
    existing_ids: set[str] = set()
    missing_ids: set[str] = set()
    errors: list[dict] = []
    meter_pos = resolved_cols["meter_id"]
    # Bounded duplicate source for daily rows: contiguous day blocks, never a
    # single earliest→latest range (sparse files must not load years of data).
    # Also backs intra-file duplicate detection so preview agrees with import.
    preexisting_daily: set = set()
    if format_profile == "daily_15min":
        preexisting_daily = _prefetch_daily_existing(
            table, resolved_cols, meter_lookup, TimestampReader(timestamp_format, timestamp_timezone),
        )
    # Day-level index for the existing_data flag: any reading that day with an
    # overlapping direction warns, even when no exact slot collides (e.g. an
    # hourly 06:00 reading vs a midnight daily slot). Exact-slot sets above
    # still drive duplicate errors and gap-fill decisions.
    preexisting_by_mp_dir: dict = {}
    for mp_id, ts, direction in preexisting_daily:
        preexisting_by_mp_dir.setdefault((mp_id, direction), []).append(ts)
    preview_written: set = set()
    # Exact-match duplicate source for standard rows (chunked __in query, no
    # range scan). Backs the existing_data flag and intra-file duplicate
    # detection so preview agrees with import for both profiles.
    preexisting_standard: set = set()
    if format_profile == "standard":
        preexisting_standard = _prefetch_standard_existing(
            table, resolved_cols, meter_lookup, TimestampReader(timestamp_format, timestamp_timezone),
        )
    preview_written_standard: set = set()
    reader = TimestampReader(timestamp_format, timestamp_timezone)
    dst_gap_skipped = 0

    skipped_existing = 0
    # Exact reading keys already present (database or earlier in this file).
    # For standard rows each duplicate is one reading; for daily rows each
    # duplicate slot is one reading. This is the overwrite confirmation
    # count, so it must be readings, not file rows.
    readings_existing = 0
    truncated = False
    for idx, row in enumerate(table.rows):
        row_number = idx + (2 if has_header else 1)
        # Rows are padded to table width, so positional access is safe.
        raw_meter = row[meter_pos]
        raw_timestamp = row[resolved_cols["timestamp"]]
        meter_id = None
        mp = None
        window = None
        # Directions this row would import, surfaced in the preview so a
        # misconfigured direction column is visible before the write.
        row_directions: list = []
        # After the error cap, keep scanning meter IDs so summary counts stay exact.
        deep = len(errors) < MAX_REPORTED_ERRORS
        if not deep:
            truncated = True
        if _is_missing(raw_meter):
            if deep:
                add_error(errors, _csv_error(row_number, None, "Missing meter_id value."))
        elif not str(raw_meter).strip():
            if deep:
                add_error(errors, _csv_error(row_number, None, "Empty meter_id value."))
        else:
            meter_id = str(raw_meter).strip()
            mp = meter_lookup.get(meter_id)
            if mp is None:
                missing_ids.add(meter_id)
            else:
                existing_ids.add(meter_id)
        # Fields are validated whether or not the meter exists, so a file of
        # unknown meters cannot hide errors the import would surface.
        # Shared with import_csv via _parse_daily_values: empty rows, missing
        # columns and invalid numerics report identically in both paths.
        preview_existing_data = False
        if format_profile == "daily_15min":
            if _is_missing(raw_timestamp):
                if deep:
                    add_error(errors, _csv_error(row_number, meter_id, "Missing date value for daily profile."))
            elif deep:
                try:
                    window = reader.day_window(raw_timestamp)
                except (ValueError, TypeError, OverflowError) as exc:
                    add_error(errors, _csv_error(row_number, meter_id, str(exc)))
                else:
                    start_pos = resolved_cols["energy_start"]
                    # Meter type only affects direction inference for the
                    # duplicate check; numeric validation runs regardless.
                    probe_type = mp.meter_type if mp is not None else "consumption"
                    # A mapped direction column (literal in/out, or the OBIS
                    # code VNB profile exports carry) wins over meter-type
                    # inference, so two files that differ only in OBIS code
                    # land in different directions on the same metering point.
                    explicit_direction, direction_error = _row_direction(row, resolved_cols)
                    # Existing-data flag runs even on invalid rows (e.g.
                    # truncated daily rows): it reflects day-level DB presence,
                    # not validation success.
                    if direction_error is None:
                        day_directions = _daily_row_directions(
                            row, start_pos, values_count, table.width, probe_type, explicit_direction
                        )
                        row_directions = sorted(day_directions)
                        if mp is not None and day_directions:
                            preview_existing_data = any(
                                window.start <= ts < window.end
                                for direction in day_directions
                                for ts in preexisting_by_mp_dir.get((mp.id, direction), ())
                            )
                    values, row_error = _parse_daily_values(row, start_pos, values_count, table.width)
                    if row_error is None and not all(v is None for v in values):
                        values, row_error = _fit_daily_values(values, window, interval_minutes, reader.is_local)
                    if row_error is not None:
                        add_error(errors, _csv_error(row_number, meter_id, row_error))
                    elif all(v is None for v in values):
                        add_error(errors, _csv_error(row_number, meter_id, "Row contains no interval values."))
                    elif direction_error is not None:
                        # Reported after the value checks, matching the order
                        # _interpret_standard_row uses for standard rows.
                        add_error(errors, _csv_error(row_number, meter_id, direction_error))
                    elif mp is not None:
                        slot_keys = []
                        for slot, value in enumerate(values):
                            if value is None:
                                continue
                            direction, _ = _infer_direction_and_energy(probe_type, value, explicit_direction)
                            ts = window.start + timedelta(minutes=interval_minutes * slot)
                            slot_keys.append((mp.id, ts, direction))
                        duplicates = sum(
                            1 for key in slot_keys if key in preexisting_daily or key in preview_written
                        )
                        # Exact-slot matches feed the overwrite confirmation
                        # count (readings, not rows), in both modes.
                        readings_existing += duplicates
                        if slot_keys:
                            # Exact duplicates also imply day-level data.
                            if duplicates > 0:
                                preview_existing_data = True
                            for key in slot_keys:
                                if key not in preexisting_daily and key not in preview_written:
                                    preview_written.add(key)
                            if duplicates == len(slot_keys) and not overwrite_existing:
                                skipped_existing += 1
        elif deep:
            # Shared with import_csv via _interpret_standard_row: timestamps,
            # values and directions report identically in both paths.
            probe_type = mp.meter_type if mp is not None else "consumption"
            ts, direction, _, row_error = _interpret_standard_row(
                row,
                resolved_cols=resolved_cols,
                reader=reader,
                meter_type=probe_type,
                series_key=meter_id,
            )
            if isinstance(row_error, DstGapSkip):
                # Not an error: the import skips it with a warning.
                dst_gap_skipped += 1
            elif row_error is not None:
                add_error(errors, _csv_error(row_number, meter_id, row_error))
            else:
                row_directions = [direction]
            if row_error is None and mp is not None:
                key = (mp.id, ts, direction)
                if key in preexisting_standard or key in preview_written_standard:
                    preview_existing_data = True
                    # One standard row is one reading.
                    readings_existing += 1
                    if not overwrite_existing:
                        skipped_existing += 1
                else:
                    preview_written_standard.add(key)
        if idx < max_rows:
            exists = mp is not None
            if format_profile == "daily_15min":
                date_value = None
                if not _is_missing(raw_timestamp):
                    try:
                        candidate = window or TimestampReader(timestamp_format, timestamp_timezone).day_window(raw_timestamp)
                        date_value = candidate.day.isoformat()
                    except (ValueError, TypeError, OverflowError):
                        date_value = str(raw_timestamp)
                preview_rows.append(
                    {
                        "row": row_number,
                        "meter_id": meter_id,
                        "metering_point_exists": exists,
                        "meter_type": mp.meter_type if mp else None,
                        "timestamp": date_value,
                        "existing_data": preview_existing_data,
                        "directions": row_directions,
                        "interval_minutes": interval_minutes,
                        "values_count": values_count,
                    }
                )
            else:
                preview_rows.append(
                    {
                        "row": row_number,
                        "meter_id": meter_id,
                        "metering_point_exists": exists,
                        "meter_type": mp.meter_type if mp else None,
                        "timestamp": None if _is_missing(raw_timestamp) else str(raw_timestamp),
                        "energy": None if _is_missing(row[resolved_cols["energy_kwh"]]) else str(row[resolved_cols["energy_kwh"]]),
                        "existing_data": preview_existing_data,
                        "directions": row_directions,
                    }
                )

    if truncated and len(errors) == MAX_REPORTED_ERRORS:
        errors.append({"row": None, "error": TRUNCATION_NOTE})

    return {
        "rows_total": len(table.rows),
        "preview_rows": preview_rows,
        "summary": {
            "existing_metering_points": len(existing_ids),
            "missing_metering_points": len(missing_ids),
            "rows_previewed": len(preview_rows),
            "rows_skipped_existing": skipped_existing,
            # Exact matching reading keys across the whole file, including
            # repeated writes within the file. Estimate only: data can change
            # between preview and import. Feeds the overwrite confirmation.
            "readings_existing": readings_existing,
        },
        "missing_meter_ids": sorted(missing_ids)[:MAX_REPORTED_ERRORS],
        "errors": errors,
        "timestamp_timezone": timestamp_timezone,
        "rows_skipped_dst_gap": dst_gap_skipped,
    }


def import_csv(
    file,
    user,
    *,
    zev,
    column_map=None,
    timestamp_format=None,
    has_header=True,
    delimiter=",",
    format_profile="standard",
    interval_minutes=15,
    values_count=96,
    overwrite_existing=False,
    timestamp_timezone=DEFAULT_TIMESTAMP_TIMEZONE,
):
    """Import metering readings from a CSV or Excel file and return an ImportLog instance.

    The successful log is created inside the same transaction as the readings,
    so no half-finished import is ever visible or deletable: readings and the
    finalized log (including the overwrite count that drives deletion
    protection) commit together. An unexpected failure rolls everything back
    and is then recorded as a separate failed-attempt log outside the
    transaction, before an ImportFileError propagates to the caller.
    """
    col = {**DEFAULT_COLUMN_MAP, **(column_map or {})}
    batch_id = uuid.uuid4()

    has_header = _to_bool(has_header, default=True)
    overwrite_existing = _to_bool(overwrite_existing, default=False)
    interval_minutes = _coerce_interval_minutes(interval_minutes)
    values_count = _coerce_values_count(values_count)
    timestamp_timezone = _coerce_timestamp_timezone(timestamp_timezone)
    table = _read_table(file, has_header=has_header, delimiter=delimiter)
    filename = getattr(file, "name", "upload")

    required_keys = ["meter_id", "timestamp", "energy_kwh"] if format_profile == "standard" else ["meter_id", "timestamp", "energy_start"]

    try:
        with transaction.atomic():
            log = ImportLog.objects.create(
                batch_id=batch_id,
                zev=zev,
                imported_by=user,
                source=ImportSource.CSV,
                filename=filename,
                rows_total=len(table.rows),
                timestamp_timezone=timestamp_timezone,
            )
            resolved_cols, column_error = _resolve_columns(table, col, required_keys)
            format_error = _check_timestamp_format(timestamp_format)
            if column_error or format_error:
                log.rows_imported = 0
                log.rows_skipped = len(table.rows)
                log.errors = [{"row": None, "error": error} for error in (column_error, format_error) if error]
                log.save()
                return log
            _import_table_rows(
                table,
                log,
                user,
                zev,
                batch_id,
                resolved_cols,
                timestamp_format,
                timestamp_timezone,
                has_header,
                format_profile,
                interval_minutes,
                values_count,
                overwrite_existing,
            )
            return log
    except ImportFileError:
        raise
    except Exception as exc:
        # The transaction rolled back the readings and the in-transaction log
        # alike. Record the failed attempt as a separate log outside the
        # transaction and report an actionable error instead of an
        # unexplained server failure with no trace of the attempt.
        ImportLog.objects.create(
            batch_id=batch_id,
            zev=zev,
            imported_by=user,
            source=ImportSource.CSV,
            filename=filename,
            rows_total=len(table.rows),
            rows_imported=0,
            rows_overwritten=0,
            rows_skipped=len(table.rows),
            errors=[{"row": None, "error": f"Import failed: {exc}"}],
            warnings=[],
            timestamp_timezone=timestamp_timezone,
        )
        raise ImportFileError(f"Import failed: {exc}") from exc


def _import_table_rows(
    table,
    log,
    user,
    zev,
    batch_id,
    resolved_cols,
    timestamp_format,
    timestamp_timezone,
    has_header,
    format_profile,
    interval_minutes,
    values_count,
    overwrite_existing,
):
    """Row loop of import_csv; runs inside the import transaction."""
    meter_lookup = {mp.meter_id: mp for mp in _meter_queryset_for_user(user, zev)}

    imported = 0
    skipped = 0
    overwritten = 0
    errors: list[dict] = []
    # Batched duplicate pre-check for daily rows (one range query per upload,
    # not per row). Slots written earlier in this same file are tracked in
    # written_daily so intra-file duplicates report the same slot-level error.
    preexisting_daily: set = set()
    written_daily: set = set()
    if format_profile == "daily_15min" and not overwrite_existing:
        preexisting_daily = _prefetch_daily_existing(
            table, resolved_cols, meter_lookup, TimestampReader(timestamp_format, timestamp_timezone),
        )
    reader = TimestampReader(timestamp_format, timestamp_timezone)
    # Zero-energy rows inside the spring DST gap, per civil day.
    dst_gap_skipped: dict = {}

    for idx, row in enumerate(table.rows):
        row_number = idx + (2 if has_header else 1)
        meter_id = None
        try:
            if _is_missing(row[resolved_cols["meter_id"]]):
                skipped += 1
                add_error(errors, _csv_error(row_number, None, "Missing meter_id value."))
                continue

            meter_id = str(row[resolved_cols["meter_id"]]).strip()
            if not meter_id:
                skipped += 1
                add_error(errors, _csv_error(row_number, None, "Empty meter_id value."))
                continue

            mp = meter_lookup.get(meter_id)
            if mp is None:
                skipped += 1
                add_error(
                    errors,
                    _csv_error(
                        row_number,
                        meter_id,
                        f"Metering point '{meter_id}' not found or not accessible.",
                    ),
                )
                continue

            if format_profile == "daily_15min":
                raw_day = row[resolved_cols["timestamp"]]
                if _is_missing(raw_day):
                    skipped += 1
                    add_error(errors, _csv_error(row_number, meter_id, "Missing date value for daily profile."))
                    continue

                window = reader.day_window(raw_day)
                start_pos = resolved_cols["energy_start"]

                # Shared validation with preview_csv: missing columns and
                # invalid numerics reject the whole row (atomic); existing
                # readings are skipped per slot so gap-filling keeps working
                # without overwrite.
                values, row_error = _parse_daily_values(row, start_pos, values_count, table.width)
                if row_error is None and not all(value is None for value in values):
                    values, row_error = _fit_daily_values(values, window, interval_minutes, reader.is_local)
                if row_error is not None:
                    skipped += 1
                    add_error(errors, _csv_error(row_number, meter_id, row_error))
                    continue
                if all(value is None for value in values):
                    skipped += 1
                    add_error(errors, _csv_error(row_number, meter_id, "Row contains no interval values."))
                    continue
                # Mapped direction column (literal in/out, or an OBIS code)
                # wins over meter-type inference — see preview_csv.
                explicit_direction, direction_error = _row_direction(row, resolved_cols)
                if direction_error is not None:
                    skipped += 1
                    add_error(errors, _csv_error(row_number, meter_id, direction_error))
                    continue
                slots: list = []
                for slot, value in enumerate(values):
                    if value is None:
                        slots.append(None)
                        continue
                    direction, energy = _infer_direction_and_energy(mp.meter_type, value, explicit_direction)
                    ts = window.start + timedelta(minutes=interval_minutes * slot)
                    if not overwrite_existing and (
                        (mp.id, ts, direction) in preexisting_daily
                        or (mp.id, ts, direction) in written_daily
                    ):
                        slots.append(None)
                        continue
                    slots.append((ts, direction, energy))
                new_entries = [entry for entry in slots if entry is not None]
                if not new_entries:
                    skipped += 1
                    add_error(
                        errors,
                        _csv_error(
                            row_number,
                            meter_id,
                            "Duplicate reading for metering_point + timestamp + direction.",
                        ),
                    )
                    continue
                if overwrite_existing:
                    row_imported = 0
                    row_overwritten = 0
                    with transaction.atomic():
                        for entry in slots:
                            if entry is None:
                                continue
                            ts, direction, energy = entry
                            if _upsert_reading(mp, ts, direction, energy, batch_id, True):
                                row_imported += 1
                            else:
                                row_overwritten += 1
                    imported += row_imported
                    overwritten += row_overwritten
                else:
                    # Fast path: one savepoint for the row, no per-slot
                    # SELECTs — the batched prefetch above stays sufficient.
                    # A late collision (a concurrent import winning a slot
                    # after the prefetch) aborts the row savepoint; the
                    # per-slot retry below then commits every slot that is
                    # still free instead of losing the row's other new slots.
                    # Whole-row validation rejects above stay atomic per row.
                    row_imported = 0
                    try:
                        with transaction.atomic():
                            for entry in slots:
                                if entry is None:
                                    continue
                                ts, direction, energy = entry
                                MeterReading.objects.create(
                                    metering_point=mp,
                                    timestamp=ts,
                                    direction=direction,
                                    energy_kwh=energy,
                                    import_source=ImportSource.CSV,
                                    import_batch=batch_id,
                                )
                                row_imported += 1
                    except IntegrityError:
                        row_imported = 0
                        for entry in slots:
                            if entry is None:
                                continue
                            ts, direction, energy = entry
                            try:
                                with transaction.atomic():
                                    MeterReading.objects.create(
                                        metering_point=mp,
                                        timestamp=ts,
                                        direction=direction,
                                        energy_kwh=energy,
                                        import_source=ImportSource.CSV,
                                        import_batch=batch_id,
                                    )
                            except IntegrityError:
                                # Absorbed late collision: the row still
                                # succeeds with its surviving slots.
                                continue
                            row_imported += 1
                            written_daily.add((mp.id, ts, direction))
                    else:
                        for entry in slots:
                            if entry is not None:
                                ts, direction, _ = entry
                                written_daily.add((mp.id, ts, direction))
                    if row_imported == 0:
                        # Nothing survived (every remaining slot collided
                        # after the prefetch): same duplicate report as a
                        # fully existing row.
                        skipped += 1
                        add_error(
                            errors,
                            _csv_error(
                                row_number,
                                meter_id,
                                "Duplicate reading for metering_point + timestamp + direction.",
                            ),
                        )
                    else:
                        imported += row_imported
                continue

            # Shared with preview_csv via _interpret_standard_row: timestamps,
            # values and directions validate identically in both paths.
            ts, direction, energy, row_error = _interpret_standard_row(
                row,
                resolved_cols=resolved_cols,
                reader=reader,
                meter_type=mp.meter_type,
                series_key=meter_id,
            )
            if isinstance(row_error, DstGapSkip):
                skipped += 1
                dst_gap_skipped[row_error.day] = dst_gap_skipped.get(row_error.day, 0) + 1
                continue
            if row_error is not None:
                skipped += 1
                add_error(errors, _csv_error(row_number, meter_id, row_error))
                continue

            created = _upsert_reading(mp, ts, direction, energy, batch_id, overwrite_existing)
            if created:
                imported += 1
            elif overwrite_existing:
                overwritten += 1
            else:
                skipped += 1
                add_error(
                    errors,
                    _csv_error(
                        row_number,
                        meter_id,
                        "Duplicate reading for metering_point + timestamp + direction.",
                    ),
                )
        except IntegrityError:
            # A concurrent standard-profile insert can win between the
            # get_or_create read and insert. Treat it like any other duplicate.
            add_error(
                errors,
                _csv_error(
                    row_number,
                    meter_id,
                    "Duplicate reading for metering_point + timestamp + direction.",
                ),
            )
            skipped += 1
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            add_error(errors, _csv_error(row_number, meter_id, str(exc)))
            skipped += 1

    log.rows_imported = imported + overwritten
    log.rows_overwritten = overwritten
    log.rows_skipped = skipped
    warnings: list[dict] = []
    if overwritten > 0:
        warnings.append({"row": None, "warning": f"Overwrote {overwritten} existing readings."})
    for day, count in sorted(dst_gap_skipped.items()):
        warnings.append({
            "row": None,
            "warning": (
                f"Skipped {count} rows at {day.isoformat()} 02:00–02:59: "
                "that hour does not exist in Swiss time (DST start)."
            ),
        })
    log.errors = errors
    log.warnings = warnings
    log.save()
    return log
