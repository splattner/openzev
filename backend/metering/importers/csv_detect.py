"""Best-effort detection of CSV/Excel import settings from the file itself.

The wizard's settings (delimiter, header row, row layout, column mapping,
timestamp format, interval) are all visible in the data, so the wizard asks
for them only when the guess is wrong. Detection reads a bounded sample of the
file, never touches the database, and is advisory: the result pre-fills the
wizard, the preview stays the gate before anything is imported.
"""

import csv
import io
import re
from collections import Counter
from datetime import date, datetime
from decimal import InvalidOperation

from .csv_importer import (
    _OBIS_RE,
    _check_timestamp_format,
    _is_missing,
    _parse_decimal,
    _read_table,
)

SAMPLE_ROWS = 60
SNIFF_BYTES = 64 * 1024
DELIMITER_CANDIDATES = (";", ",", "\t", "|")
# A row this wide can only be one-day-per-row interval data.
MIN_DAILY_VALUES = 12
# Slot counts of a full day at the usual resolutions (60, 30, 15, 10, 5, 1 min).
_DAY_SLOT_COUNTS = {24, 48, 96, 144, 288, 1440}

_DATE_RE = re.compile(
    r"^\d{1,4}[-./]\d{1,2}[-./]\d{1,4}"
    r"(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# Header labels, matched case-insensitively. Hints only rank candidates that
# the cell contents already allow, so a misleading label cannot pick a column
# of the wrong kind.
_METER_HINT = re.compile(r"meter|z[äa]e?hl|mess?punkt|metering|\bmp\b|\bpod\b|\bean\b")
_TIMESTAMP_HINT = re.compile(r"time|date|datum|zeit|stamp|\btag\b|\bday\b")
_ENERGY_HINT = re.compile(r"kwh|energy|energie|wert|value|verbrauch|menge|consum|reading")

# Timestamp formats tried against the sampled cells, most specific first.
# ISO-8601 is not listed: the importer's default parser reads it, so it is
# reported as "" (auto-detect) rather than pinned to one variant.
_TIMESTAMP_FORMATS = (
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    "%d.%m.%y %H:%M:%S",
    "%d.%m.%y %H:%M",
    "%d.%m.%y",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
)


def _text(cell):
    return "" if _is_missing(cell) else str(cell).strip()


def _kind(cell):
    """Classify one cell: empty/date/time/direction/number/text."""
    if isinstance(cell, (datetime, date)):
        return "date"
    text = _text(cell)
    if not text:
        return "empty"
    if _DATE_RE.match(text):
        return "date"
    if _TIME_RE.match(text):
        return "time"
    lowered = text.lower()
    if lowered in {"in", "out"}:
        return "direction"
    match = _OBIS_RE.match(text)
    if match is not None and text.count(".") >= 2:
        return "direction"
    try:
        _parse_decimal(cell)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return "text"
    return "number"


def _is_integer_text(cell):
    return _text(cell).isdigit()


def _sniff_delimiter(file):
    """Pick the delimiter whose split is the widest and most consistent."""
    file.seek(0)
    raw = getattr(file, "file", file).read(SNIFF_BYTES)
    file.seek(0)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", errors="ignore")
    lines = [line for line in raw.splitlines() if line.strip()][:30]
    if len(lines) > 1 and len(raw) >= SNIFF_BYTES:
        lines = lines[:-1]  # the last line of a truncated read may be cut off
    best, best_score = ",", (0, 0)
    for delimiter in DELIMITER_CANDIDATES:
        try:
            counts = [len(row) for row in csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter) if row]
        except csv.Error:
            continue
        if not counts:
            continue
        modal, freq = Counter(counts).most_common(1)[0]
        if modal < 2 or freq / len(counts) < 0.8:
            continue
        # Widest split wins: with decimal commas a ";" file also splits on ","
        # but always into fewer columns.
        score = (modal, 1 if delimiter == ";" else 0)
        if score > best_score:
            best, best_score = delimiter, score
    return best


def _looks_like_header(rows):
    first = rows[0]
    kinds = [_kind(cell) for cell in first]
    if "date" in kinds:
        return False
    numbers = [cell for cell, kind in zip(first, kinds) if kind == "number"]
    # Numeric column labels ("1", "2", …) are fine; a decimal value is data.
    return all(_is_integer_text(cell) for cell in numbers)


def _dominant_kinds(data, width):
    """Per column: (dominant kind or None, share of non-empty cells)."""
    result = []
    for position in range(width):
        kinds = Counter(_kind(row[position]) for row in data if position < len(row))
        kinds.pop("empty", None)
        total = sum(kinds.values())
        if not total:
            result.append((None, 0))
            continue
        kind, count = kinds.most_common(1)[0]
        result.append((kind if count / total >= 0.8 else None, total))
    return result


def _detect_timestamp_format(cells):
    """Return ``(format, known)``: "" means the importer's auto-parser copes."""
    samples = [cell for cell in cells if not _is_missing(cell)]
    if not samples or all(isinstance(cell, (datetime, date)) for cell in samples):
        return "", True
    texts = [_text(cell) for cell in samples]
    if all(_ISO_RE.match(text) for text in texts):
        try:
            for text in texts:
                datetime.fromisoformat(text)
            return "", True
        except ValueError:
            pass
    for candidate in _TIMESTAMP_FORMATS:
        try:
            for text in texts:
                datetime.strptime(text, candidate)
        except ValueError:
            continue
        if _check_timestamp_format(candidate) is None:
            return candidate, True
    return "", False


def _pick(candidates, hint, labels):
    """First candidate whose header label matches ``hint``, else the first."""
    if not candidates:
        return None
    if labels:
        for position in candidates:
            if hint.search(labels[position]):
                return position
    return candidates[0]


def _runs(positions):
    """Split sorted positions into runs of consecutive integers."""
    runs, current = [], []
    for position in positions:
        if current and position != current[-1] + 1:
            runs.append(current)
            current = []
        current.append(position)
    if current:
        runs.append(current)
    return runs


def _reference(table_labels, position, has_header):
    """Column reference the importer resolves: label when unique, else index."""
    if position is None:
        return None
    if has_header:
        label = table_labels[position]
        if label and table_labels.count(label) == 1:
            return label
    return str(position)


def detect_csv_settings(file):
    """Detect import settings from ``file`` (CSV or XLSX).

    Returns a dict with ``settings`` (same names the import endpoints take),
    ``undetected`` (settings that could not be determined and hold defaults)
    and ``detected`` (False when the file cannot be imported without manual
    mapping). Raises ``ImportFileError`` for an unreadable file.
    """
    name = (getattr(file, "name", "") or "").lower()
    delimiter = "," if name.endswith(".xlsx") else _sniff_delimiter(file)
    table = _read_table(file, has_header=False, delimiter=delimiter, limit=SAMPLE_ROWS + 1)
    rows = table.rows
    if len(rows) < 2:
        return _result(delimiter, undetected=["file"], detected=False)

    has_header = _looks_like_header(rows)
    labels = [_text(cell) for cell in rows[0]] if has_header else []
    data = rows[1:] if has_header else rows
    width = table.width
    lowered_labels = [label.lower() for label in labels]
    dominant = _dominant_kinds(data, width)
    kinds = [kind for kind, _ in dominant]

    date_position = _pick([i for i, k in enumerate(kinds) if k == "date"], _TIMESTAMP_HINT, lowered_labels)
    direction_position = next((i for i, k in enumerate(kinds) if k == "direction"), None)

    meter_candidates = [
        i for i, k in enumerate(kinds)
        if i != date_position and i != direction_position
        and (k == "text" or (k == "number" and all(_is_integer_text(row[i]) for row in data if not _is_missing(row[i]))))
    ]
    # Text ids first: an all-digit column is a meter id only when nothing else fits.
    text_candidates = [i for i in meter_candidates if kinds[i] == "text"]
    meter_position = _pick(text_candidates or meter_candidates, _METER_HINT, lowered_labels)

    taken = {date_position, direction_position, meter_position}
    number_positions = [i for i, k in enumerate(kinds) if k == "number" and i not in taken]
    time_labels = [
        i for i, label in enumerate(labels) if _TIME_RE.match(label) and i not in taken
    ]

    profile, energy_position, energy_start_position = "standard", None, None
    values_count, interval_minutes = 96, 15
    daily_block = None
    if len(time_labels) >= MIN_DAILY_VALUES:
        daily_block = max(_runs(time_labels), key=len)
    else:
        long_runs = [run for run in _runs(number_positions) if len(run) >= MIN_DAILY_VALUES]
        if long_runs:
            daily_block = max(long_runs, key=len)
            if len(daily_block) not in _DAY_SLOT_COUNTS and len(daily_block) - 1 in _DAY_SLOT_COUNTS:
                daily_block = daily_block[:-1]  # trailing day-total column

    if daily_block:
        profile = "daily_15min"
        energy_start_position = daily_block[0]
        values_count = len(daily_block)
        interval_minutes = _interval_minutes(labels, daily_block, values_count)
    else:
        energy_position = _pick(number_positions, _ENERGY_HINT, lowered_labels)

    timestamp_format, format_known = (
        _detect_timestamp_format([row[date_position] for row in data]) if date_position is not None else ("", True)
    )

    undetected = []
    if meter_position is None:
        undetected.append("meter_id")
    if date_position is None:
        undetected.append("timestamp")
    if profile == "standard" and energy_position is None:
        undetected.append("energy_kwh")
    if not format_known:
        undetected.append("timestamp_format")

    column_labels = labels if has_header else []
    return _result(
        delimiter,
        has_header=has_header,
        format_profile=profile,
        timestamp_format=timestamp_format,
        interval_minutes=interval_minutes,
        values_count=values_count,
        column_map={
            "meter_id": _reference(column_labels, meter_position, has_header),
            "timestamp": _reference(column_labels, date_position, has_header),
            "energy_kwh": _reference(column_labels, energy_position, has_header),
            "direction": _reference(column_labels, direction_position, has_header),
            "energy_start": _reference(column_labels, energy_start_position, has_header),
        },
        undetected=undetected,
        detected=not [key for key in undetected if key != "timestamp_format"],
    )


def _interval_minutes(labels, block, values_count):
    """Minutes per slot: from the time labels when present, else from a full day."""
    if labels and len(block) >= 2:
        first, second = _TIME_RE.match(labels[block[0]]), _TIME_RE.match(labels[block[1]])
        if first and second:
            step = (int(second.group(1)) * 60 + int(second.group(2))) - (int(first.group(1)) * 60 + int(first.group(2)))
            if step > 0:
                return step
    if 1440 % values_count == 0:
        return 1440 // values_count
    return 15


def _result(delimiter, *, has_header=True, format_profile="standard", timestamp_format="",
            interval_minutes=15, values_count=96, column_map=None, undetected=(), detected=True):
    return {
        "detected": detected,
        "undetected": list(undetected),
        "settings": {
            "has_header": has_header,
            "delimiter": delimiter,
            "format_profile": format_profile,
            "timestamp_format": timestamp_format,
            "interval_minutes": interval_minutes,
            "values_count": values_count,
            "column_map": column_map or {
                "meter_id": None,
                "timestamp": None,
                "energy_kwh": None,
                "direction": None,
                "energy_start": None,
            },
        },
    }
