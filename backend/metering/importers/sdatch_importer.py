"""Strict SDAT-CH E66 imports (metering import and quality spec §4.2).

Validate the offline schema and billing profile before committing a complete
file. Billable and held observations have independent freshness. Reading
changes, invoice impacts and the outcome log commit together.
"""

import gzip
import io
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from itertools import islice
from threading import Lock
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from lxml import etree

from metering.models import (
    ImportLog,
    ImportSource,
    MeterReading,
    QuarantinedReading,
    ReadingChangeKind,
    ReadingDirection,
    ReadingResolution,
    SdatResultStatus,
)
from metering.importers.limits import MAX_UPLOAD_BYTES, add_error, mb
from metering.importers.reading_changes import READING_CHANGE_CAP, ReadingChangeRecorder
from metering.locks import lock_billing_inputs as _lock_zev_imports
from zev.models import AmbiguousMeterIdentity, MeteringPointType, resolve_metering_point

logger = logging.getLogger(__name__)

MAX_SDAT_BYTES = MAX_UPLOAD_BYTES
MAX_SDAT_DECOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ISSUES = 200
PERSIST_BATCH_SIZE = 1000

SDAT_NS = "http://www.strom.ch"
STRICT_ROOT = "ValidatedMeteredData_16"

PRODUCT_WIRKENERGIE = "8716867000030"
PRODUCT_BLINDENERGIE = "8716867000047"
REACTIVE_PRODUCTS = {PRODUCT_BLINDENERGIE, "8716867000139", "8716867000146"}
PRODUCT_LEG_ENERGIE = "2404050010123"
PRODUCT_LEG_RESTENERGIE = "2404050010124"
UNIT_KWH = "KWH"

REASON_BILLING = "E88"
REASON_INFO = "C38"
CONDITION_TEMPORARY = "21"
CONDITION_ESTIMATED = "56"

STATUS_ORIGINAL = "9"
STATUS_REPLACE = "5"
STATUS_CANCELLATION = "1"

RESOLUTION_MINUTES = 15
RESOLUTION_LABEL = ReadingResolution.FIFTEEN_MIN

MAX_ENERGY_KWH = Decimal("99999999.9999")

# Stable issue codes (see the import baseline spec). Do not rename them.
ISSUE_UNSUPPORTED_ROOT = "unsupported_root"
ISSUE_UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
ISSUE_SCHEMA_INVALID = "schema_invalid"
ISSUE_VALIDATION_UNAVAILABLE = "validation_unavailable"
ISSUE_UNSUPPORTED_FEATURE = "unsupported_feature"
ISSUE_CANCELLATION_REJECTED = "cancellation_rejected"
ISSUE_UNSUPPORTED_STATUS = "unsupported_status"
ISSUE_UNSUPPORTED_DOCUMENT_TYPE = "unsupported_document_type"
ISSUE_MISSING_CREATION = "missing_creation"
ISSUE_INVALID_CREATION = "invalid_creation"
ISSUE_MISSING_REASON = "missing_reason"
ISSUE_UNSUPPORTED_REASON = "unsupported_reason"
ISSUE_INVALID_HEADER = "invalid_header"
ISSUE_UNKNOWN_METER = "unknown_meter"
ISSUE_AMBIGUOUS_METER = "ambiguous_meter"
ISSUE_MISSING_INTERVAL = "missing_interval"
ISSUE_INVALID_INTERVAL = "invalid_interval"
ISSUE_UNALIGNED_INTERVAL = "unaligned_interval"
ISSUE_MISSING_RESOLUTION = "missing_resolution"
ISSUE_UNSUPPORTED_RESOLUTION = "unsupported_resolution"
ISSUE_MISSING_METER_POINT = "missing_meter_point"
ISSUE_UNKNOWN_PRODUCT = "unknown_product"
ISSUE_UNSUPPORTED_UNIT = "unsupported_unit"
ISSUE_INVALID_POSITION = "invalid_position"
ISSUE_MISSING_POSITION = "missing_position"
ISSUE_DUPLICATE_POSITION = "duplicate_position"
ISSUE_CONFLICTING_POSITION = "conflicting_position"
ISSUE_INVALID_VOLUME = "invalid_volume"
ISSUE_UNKNOWN_CONDITION = "unknown_condition"
ISSUE_NAIVE_TIMESTAMP = "naive_timestamp"
ISSUE_EQUAL_CREATION_CONFLICT = "equal_creation_conflict"
ISSUE_SOURCE_CONFLICT = "source_conflict"
ISSUE_FILE_TOO_LARGE = "file_too_large"
ISSUE_DECOMPRESSED_TOO_LARGE = "decompressed_too_large"
ISSUE_GZIP_ERROR = "gzip_error"
ISSUE_MALFORMED_XML = "malformed_xml"
ISSUE_EMPTY_DELIVERY = "empty_delivery"
ISSUE_REACTIVE_EXCLUDED = "reactive_excluded"
ISSUE_LEG_EXCLUDED = "leg_excluded"
ISSUE_EXCHANGE_EXCLUDED = "exchange_excluded"
ISSUE_STALE_SUPERSEDED = "stale_superseded"
ISSUE_DUPLICATE_DELIVERY = "duplicate_delivery"
ISSUE_TOO_MANY_ISSUES = "too_many_issues"
ISSUE_INTERNAL_ERROR = "internal_error"
ISSUE_INVALID_REPORT_PERIOD = "invalid_report_period"
ISSUE_OUTSIDE_REPORT_PERIOD = "outside_report_period"
ISSUE_METER_DIRECTION_MISMATCH = "meter_direction_mismatch"
ISSUE_CONCURRENT_WRITE_CONFLICT = "concurrent_write_conflict"
ISSUE_ORIGINAL_EXISTS = "original_exists"

COUNT_KEYS = (
    "created",
    "overwritten",
    "held",
    "promoted",
    "duplicate",
    "original_existing",
    "stale",
    "excluded",
    "rejected",
    "quarantine_overwritten",
)



def _qname(local: str) -> str:
    return f"{{{SDAT_NS}}}{local}"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _text(elem, local: str) -> str:
    child = elem.find(_qname(local)) if elem is not None else None
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _code(elem, local: str) -> str:
    """Read a nested ebIX/VSE code."""
    if elem is None:
        return ""
    child = elem.find(_qname(local))
    if child is None:
        return ""
    return _text(child, "ebIXCode") or _text(child, "VSENationalCode")


def _sequence(obs) -> str:
    """Position sequence of an observation (nested Position/Sequence)."""
    return _text(obs.find(_qname("Position")), "Sequence")


_SCHEMA_16 = None
_SCHEMA_LOCK = Lock()


class _NormalizedCoreSchema(etree.Resolver):
    def resolve(self, url, public_id, context):
        if os.path.basename(url) != "ValidatedMeteredData_CoreComponents_1p6.xsd":
            return None
        doc = etree.parse(url)
        # libxml2 rejects children on prohibited attributes; keep vendor bytes pristine.
        for attr in doc.iter("{http://www.w3.org/2001/XMLSchema}attribute"):
            if attr.get("use") == "prohibited":
                for child in list(attr):
                    attr.remove(child)
        return self.resolve_string(etree.tostring(doc), context, base_url=url)


def _load_schema_16():
    """Compile the offline bundle, normalizing only the incompatible core schema."""
    global _SCHEMA_16
    with _SCHEMA_LOCK:
        if _SCHEMA_16 is None:
            parser = etree.XMLParser(no_network=True)
            parser.resolvers.add(_NormalizedCoreSchema())
            entry = os.path.join(os.path.dirname(__file__), "sdat_xsd", "ValidatedMeteredData_1p6.xsd")
            _SCHEMA_16 = etree.XMLSchema(etree.parse(entry, parser))
    return _SCHEMA_16


def _has_tz_designator(value: str) -> bool:
    """Whether a timestamp carries an explicit zone (``Z`` or ``±hh:mm``)."""
    text = (value or "").strip()
    return text.endswith("Z") or bool(re.search(r"[+-]\d{2}:?\d{2}$", text))


def _parse_ts_strict(value: str) -> datetime:
    """Parse an SDAT-CH timestamp to an aware UTC datetime.

    The 1.6 schema type ``EnergyDateTimeType`` requires an explicit ``Z``
    suffix (UTC exclusively); offset-less wall-clock timestamps are not part
    of the strict profile and are rejected rather than reinterpreted.
    """
    text = (value or "").strip()
    if not text:
        raise ValueError("empty timestamp")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without timezone offset: '{text}'")
    return parsed.astimezone(timezone.utc)


@dataclass
class _PlannedObservation:
    meter_id: str
    metering_point: object
    timestamp: datetime
    direction: str
    energy: Decimal
    condition: str
    billable: bool
    block_id: str


@dataclass
class _PlanBlock:
    document_id: str
    product: str
    unit: str
    observations: list = field(default_factory=list)


class _FileRejected(Exception):
    """Abort a file with structured issues."""

    def __init__(self, issues):
        super().__init__(issues[0]["message"] if issues else "SDAT-CH file rejected.")
        self.issues = list(issues)


def _issue(code, message, *, severity="error", **params):
    entry = {"code": code, "severity": severity, "message": message}
    entry.update(params)
    return entry


def _xml_error_params(exc):
    """Expose parser locations and machine codes without parsing diagnostic prose."""
    error_log = getattr(exc, "error_log", None)
    error = error_log.last_error if error_log is not None else None
    if error is None:
        return {}
    return {
        key: value
        for key, value in (
            ("xml_line", error.line),
            ("xml_column", error.column),
            ("xml_path", error.path),
            ("xml_error_type", error.type_name),
        )
        if value is not None and value != ""
    }


def _zero_counts():
    return {key: 0 for key in COUNT_KEYS}


class _ImportRun:
    """Accumulates one file's parse state, counters and structured issues."""

    def __init__(self):
        self.rows_total = 0
        self.counts = _zero_counts()
        self._issues = []
        self.warnings = []
        self.delivery = {}
        self.affected_slots = {}

    @property
    def issues(self):
        return list(self._issues)

    def add_issue(self, code, message, *, severity="error", **params):
        if len(self._issues) < MAX_ISSUES:
            self._issues.append(_issue(code, message, severity=severity, **params))
        elif len(self._issues) == MAX_ISSUES:
            self._issues.append(_issue(
                ISSUE_TOO_MANY_ISSUES,
                f"Showing first {MAX_ISSUES} issues; further details truncated.",
                severity="info",
            ))

    def add_issues(self, issues):
        for issue in issues:
            self.add_issue(**issue)

    def legacy_errors(self):
        """Error-severity issues in the legacy ImportLog.errors shape."""
        errors = []
        for issue in self.issues:
            if issue.get("severity") != "error":
                continue
            entry = {"error": issue["message"]}
            if issue.get("meter_id"):
                entry["meter_id"] = issue["meter_id"]
            add_error(errors, entry)
        return errors

    def legacy_warnings(self):
        return list(self.warnings)


def _fail_log(log, run):
    """Persist a rejected outcome without observation writes."""
    excluded = run.counts["excluded"]
    run.counts = _zero_counts()
    run.counts.update(excluded=excluded, rejected=run.rows_total - excluded)
    run.warnings = []
    _add_legacy_warnings(run)
    log.rows_total = run.rows_total
    log.rows_imported = 0
    log.rows_overwritten = 0
    log.rows_skipped = run.counts["excluded"]
    log.errors = run.legacy_errors() or [{"error": "SDAT-CH file rejected."}]
    log.warnings = run.legacy_warnings()
    log.result_status = SdatResultStatus.REJECTED
    log.result_counts = run.counts
    log.issues = run.issues
    log.reading_changes = []
    log.source_delivery = run.delivery
    log.save()
    return log


def _finalize_log(log, run, *, status, changes, changes_truncated):
    log.rows_total = run.rows_total
    log.rows_imported = run.counts["created"]
    log.rows_overwritten = run.counts["overwritten"]
    log.rows_skipped = (
        run.counts["duplicate"] + run.counts["original_existing"] + run.counts["stale"] + run.counts["excluded"]
    )
    log.errors = run.legacy_errors()
    log.warnings = run.legacy_warnings()
    log.result_status = status
    counts = dict(run.counts)
    counts["reading_changes_truncated"] = bool(changes_truncated)
    log.result_counts = counts
    log.issues = run.issues
    log.reading_changes = changes
    log.source_delivery = run.delivery
    log.save()
    return log


def _sender_identity(header):
    """Best-effort sender/receiver identity: identifier text plus role."""

    def _party(local):
        elem = header.find(_qname(local)) if header is not None else None
        if elem is None:
            return "", ""
        ident = elem.find(_qname("ID"))
        code = ""
        if ident is not None:
            for child in list(ident):
                if child.text and child.text.strip():
                    code = child.text.strip()
                    break
        return code, _text(elem, "Role")

    sender_id, sender_role = _party("Sender")
    receiver_id, receiver_role = _party("Receiver")
    return sender_id, sender_role, receiver_id, receiver_role


def _validate_header(run, root):
    """Validate the delivery header; returns delivery, reason, Creation, replacement status and ReportPeriod.

    Raises _FileRejected before any observation is touched.
    """
    header = root.find(_qname("ValidatedMeteredData_HeaderInformation"))
    if header is None:
        raise _FileRejected(
            [_issue(ISSUE_INVALID_HEADER, "Missing ValidatedMeteredData_HeaderInformation.",
                    element="ValidatedMeteredData_HeaderInformation")]
        )
    instance = header.find(_qname("InstanceDocument"))
    if instance is None:
        raise _FileRejected(
            [_issue(ISSUE_INVALID_HEADER, "Missing InstanceDocument header.", element="InstanceDocument")]
        )
    delivery_id = _text(instance, "DocumentID")
    doc_type = _code(instance, "DocumentType")
    if doc_type != "E66":
        raise _FileRejected(
            [
                _issue(
                    ISSUE_UNSUPPORTED_DOCUMENT_TYPE,
                    f"DocumentType is not E66 (ValidatedMeteredData): '{doc_type or '?'}'.",
                    document_type=doc_type,
                )
            ]
        )
    status = _text(instance, "Status")
    if status not in (STATUS_ORIGINAL, STATUS_REPLACE):
        raise _FileRejected(
            [
                _issue(
                    ISSUE_UNSUPPORTED_STATUS,
                    f"Document Status '{status or '?'}' is not supported for import (expected 9 original or 5 replacement).",
                    status=status,
                )
            ]
        )
    creation_raw = _text(instance, "Creation")
    if not creation_raw:
        raise _FileRejected(
            [_issue(ISSUE_MISSING_CREATION, "Missing InstanceDocument Creation; delivery order cannot be verified.")]
        )
    try:
        creation = _parse_ts_strict(creation_raw)
    except ValueError:
        raise _FileRejected(
            [_issue(ISSUE_INVALID_CREATION, f"Invalid Creation timestamp '{creation_raw}'.", creation=creation_raw)]
        )
    scope = header.find(_qname("BusinessScopeProcess"))
    reason = _code(scope, "BusinessReasonType")
    if not reason:
        raise _FileRejected(
            [_issue(ISSUE_MISSING_REASON, "Missing BusinessReasonType; the delivery profile is unknown.")]
        )
    if reason not in (REASON_BILLING, REASON_INFO):
        raise _FileRejected(
            [
                _issue(
                    ISSUE_UNSUPPORTED_REASON,
                    f"BusinessReason {reason} is not supported for ZEV billing import; "
                    f"supported reasons are E88 (billing) and C38 (information).",
                    reason=reason,
                )
            ]
        )
    report = scope.find(_qname("ReportPeriod"))
    report_start_raw = _text(report, "StartDateTime")
    report_end_raw = _text(report, "EndDateTime")
    try:
        report_start = _parse_ts_strict(report_start_raw)
        report_end = _parse_ts_strict(report_end_raw)
        if report_end <= report_start:
            raise ValueError("ReportPeriod end must follow its start")
    except ValueError:
        raise _FileRejected([_issue(
            ISSUE_INVALID_REPORT_PERIOD, "ReportPeriod must be a valid, non-empty UTC interval.",
            interval_start=report_start_raw, interval_end=report_end_raw,
        )]) from None
    sender_id, sender_role, receiver_id, receiver_role = _sender_identity(header)
    run.delivery = {
        "delivery_id": delivery_id,
        "creation": creation.isoformat(),
        "status": status,
        "reason": reason,
        "sender_id": sender_id,
        "sender_role": sender_role,
        "receiver_id": receiver_id,
        "receiver_role": receiver_role,
    }
    return run.delivery, reason, creation, status == STATUS_REPLACE, (report_start, report_end)


def _parse_block(md, *, reason, report_period):
    """Parse one MeteringData block.

    Returns ("block", _PlanBlock), ("excluded", count, note-issue) or raises
    _FileRejected for any invalid supported billing data.
    """
    doc_id = _text(md, "DocumentID") or "?"

    def reject(code, message, **params):
        raise _FileRejected([_issue(code, message, **params)])

    point_elem = None
    direction = None
    for local_name, flow in (
        ("ConsumptionMeteringPoint", ReadingDirection.IN),
        ("ProductionMeteringPoint", ReadingDirection.OUT),
    ):
        found = md.find(_qname(local_name))
        if found is not None:
            point_elem = found
            direction = flow
            break
    observations = list(md.iter(_qname("Observation")))
    if point_elem is None:
        if md.find(_qname("ExchangeMeteringPoint")) is not None:
            return ("excluded", len(observations), _issue(
                ISSUE_EXCHANGE_EXCLUDED,
                "Exchange metering points (grid interconnections) are not imported: no customer meter.",
                block_id=doc_id,
            ))
        reject(ISSUE_MISSING_METER_POINT, f"Block '{doc_id}' names no metering point.", block_id=doc_id)

    meter_id = _text(point_elem, "VSENationalID")
    product_elem = md.find(_qname("Product"))
    product = _code(product_elem, "ID")
    measure_unit = (_text(product_elem, "MeasureUnit") or "").strip().upper() if product_elem is not None else ""
    if product in REACTIVE_PRODUCTS:
        return ("excluded", len(observations), _issue(
            ISSUE_REACTIVE_EXCLUDED,
            f"Skipped reactive energy observations (product {product}): OpenZEV bills active energy (kWh).",
            block_id=doc_id,
            product=product,
        ))
    if product in (PRODUCT_LEG_ENERGIE, PRODUCT_LEG_RESTENERGIE):
        return ("excluded", len(observations), _issue(
            ISSUE_LEG_EXCLUDED,
            f"Skipped LEG observations (product {product}): LEG energy billing is not supported yet.",
            block_id=doc_id,
            product=product,
        ))
    if product != PRODUCT_WIRKENERGIE:
        reject(
            ISSUE_UNKNOWN_PRODUCT,
            f"Unknown product '{product or '?'}' in block '{doc_id}'.",
            block_id=doc_id,
            meter_id=meter_id or None,
            product=product or None,
        )
    if measure_unit != UNIT_KWH:
        reject(
            ISSUE_UNSUPPORTED_UNIT,
            f"Unsupported MeasureUnit '{measure_unit or '?'}' for active energy in block '{doc_id}'; only KWH is billed, without conversion.",
            block_id=doc_id,
            meter_id=meter_id or None,
            product=product,
            unit=measure_unit or None,
        )


    interval = md.find(_qname("Interval"))
    if interval is None:
        reject(ISSUE_MISSING_INTERVAL, f"Block '{doc_id}' has no Interval.", block_id=doc_id)
    start_raw = _text(interval, "StartDateTime")
    end_raw = _text(interval, "EndDateTime")
    interval_params = {"block_id": doc_id, "interval_start": start_raw, "interval_end": end_raw}
    for raw_ts in (start_raw, end_raw):
        if not _has_tz_designator(raw_ts):
            reject(
                ISSUE_NAIVE_TIMESTAMP,
                f"Block '{doc_id}' carries an offset-less Interval timestamp; strict SDAT-CH 1.6 uses UTC exclusively.",
                **interval_params,
            )
    try:
        start_ts = _parse_ts_strict(start_raw)
        end_ts = _parse_ts_strict(end_raw)
    except ValueError as exc:
        reject(ISSUE_INVALID_INTERVAL, f"Invalid Interval timestamps in block '{doc_id}': {exc}.",
               detail_code="invalid_timestamp", **interval_params)
    if end_ts <= start_ts:
        reject(ISSUE_INVALID_INTERVAL, f"Empty Interval in block '{doc_id}'.",
               detail_code="empty_interval", **interval_params)
    if start_ts < report_period[0] or end_ts > report_period[1]:
        reject(
            ISSUE_OUTSIDE_REPORT_PERIOD,
            f"Block '{doc_id}' extends outside the delivery's ReportPeriod.",
            **interval_params,
        )
    span = end_ts - start_ts
    if span.microseconds or span.seconds % 60:
        reject(ISSUE_INVALID_INTERVAL, f"Block '{doc_id}' Interval is not a whole-minute span.",
               detail_code="non_minute_interval", **interval_params)
    if (
        start_ts.second
        or start_ts.microsecond
        or end_ts.second
        or end_ts.microsecond
        or (start_ts.minute % RESOLUTION_MINUTES)
        or (end_ts.minute % RESOLUTION_MINUTES)
    ):
        reject(
            ISSUE_UNALIGNED_INTERVAL,
            f"Block '{doc_id}' Interval is not aligned to the 15-minute grid.",
            **interval_params,
        )
    span_minutes = int(span.total_seconds() // 60)
    if span_minutes % RESOLUTION_MINUTES:
        reject(
            ISSUE_UNALIGNED_INTERVAL,
            f"Block '{doc_id}' Interval spans {span_minutes} minutes, not divisible into 15-minute positions.",
            **interval_params,
        )
    expected = span_minutes // RESOLUTION_MINUTES

    res_elem = md.find(_qname("Resolution"))
    if res_elem is None:
        reject(
            ISSUE_MISSING_RESOLUTION,
            f"Block '{doc_id}' has no Resolution; the strict SDAT-CH 1.6 profile fixes Resolution 15/MIN.",
            block_id=doc_id,
        )
    resolution_raw = (_text(res_elem, "Resolution") or "").strip()
    try:
        res_value = int(resolution_raw)
    except ValueError:
        res_value = None
    unit = (_text(res_elem, "Unit") or "").strip().upper()
    if res_value != RESOLUTION_MINUTES or unit != "MIN":
        reject(
            ISSUE_UNSUPPORTED_RESOLUTION,
            f"Block '{doc_id}' Resolution is '{res_value or '?'}'/'{unit or '?'}'; only 15/MIN is supported for billing import.",
            block_id=doc_id,
            resolution=resolution_raw,
            resolution_unit=unit,
        )

    seqs = []
    for obs in observations:
        seq_raw = _sequence(obs)
        try:
            seq = int(seq_raw)
        except (TypeError, ValueError):
            seq = None
        if seq is None or seq < 1 or seq > expected:
            reject(
                ISSUE_INVALID_POSITION,
                f"Position '{seq_raw or '?'}' in block '{doc_id}' is outside the declared interval (1..{expected}).",
                block_id=doc_id,
                meter_id=meter_id or None,
                position=seq_raw or None,
                expected_positions=expected,
            )
        seqs.append(seq)
    if len(set(seqs)) != len(seqs):
        seen = set()
        for seq in seqs:
            if seq in seen:
                dup = seq
                break
            seen.add(seq)
        # Same slot with a different value is a conflict, not a duplicate.
        values = {}
        for obs, seq in zip(observations, seqs):
            if seq == dup:
                values.setdefault((_text(obs, "Volume") or "").strip(), []).append(obs)
        if len(values) > 1:
            reject(
                ISSUE_CONFLICTING_POSITION,
                f"Position {dup} in block '{doc_id}' carries conflicting values.",
                block_id=doc_id,
                meter_id=meter_id or None,
                position=dup,
            )
        reject(
            ISSUE_DUPLICATE_POSITION,
            f"Position {dup} in block '{doc_id}' is delivered twice.",
            block_id=doc_id,
            meter_id=meter_id or None,
            position=dup,
        )
    if len(seqs) != expected:
        present = set(seqs)
        missing_count = expected - len(seqs)
        missing = list(islice((position for position in range(1, expected + 1) if position not in present), 50))
        shown = ", ".join(str(m) for m in missing[:10])
        suffix = "" if missing_count <= 10 else f" (+{missing_count - 10} more)"
        reject(
            ISSUE_MISSING_POSITION,
            f"Block '{doc_id}' is missing positions {shown}{suffix} of {expected}.",
            block_id=doc_id,
            meter_id=meter_id or None,
            missing=missing[:50],
            missing_count=missing_count,
            expected_positions=expected,
        )

    by_seq = {}
    for obs, seq in zip(observations, seqs):
        by_seq[seq] = obs
    planned = []
    for seq in range(1, expected + 1):
        obs = by_seq[seq]
        feature = _text(obs, "Feature")
        if feature:
            reject(ISSUE_UNSUPPORTED_FEATURE,
                   f"Tariff-band observation '{feature}' cannot be imported as interval total energy.",
                   block_id=doc_id, meter_id=meter_id, position=seq, feature=feature)
        qty_raw = (_text(obs, "Volume") or "").strip()
        try:
            energy = Decimal(qty_raw)
        except (InvalidOperation, ValueError, AttributeError):
            energy = None
        if energy is None or not energy.is_finite():
            reject(
                ISSUE_INVALID_VOLUME,
                f"Invalid numeric value '{qty_raw or '?'}' at position {seq} in block '{doc_id}'.",
                detail_code="invalid_number",
                volume=qty_raw,
                block_id=doc_id,
                meter_id=meter_id or None,
                position=seq,
            )
        if energy < 0:
            reject(
                ISSUE_INVALID_VOLUME,
                f"Negative volume '{qty_raw}' at position {seq} in block '{doc_id}' is not valid interval energy.",
                detail_code="negative_volume",
                volume=qty_raw,
                block_id=doc_id,
                meter_id=meter_id or None,
                position=seq,
            )
        if abs(energy) > MAX_ENERGY_KWH:
            reject(
                ISSUE_INVALID_VOLUME,
                f"Volume '{qty_raw}' at position {seq} in block '{doc_id}' exceeds the storable range.",
                detail_code="volume_out_of_range",
                volume=qty_raw,
                volume_limit=str(MAX_ENERGY_KWH),
                block_id=doc_id,
                meter_id=meter_id or None,
                position=seq,
            )
        energy = energy.quantize(Decimal("0.0001"))
        condition = _text(obs, "Condition")
        if condition not in ("", CONDITION_TEMPORARY, CONDITION_ESTIMATED):
            reject(
                ISSUE_UNKNOWN_CONDITION,
                f"Unknown Condition '{condition}' at position {seq} in block '{doc_id}'.",
                condition=condition,
                block_id=doc_id,
                meter_id=meter_id or None,
                position=seq,
            )
        ts = start_ts + timedelta(minutes=RESOLUTION_MINUTES * (seq - 1))
        billable = reason == REASON_BILLING and condition in ("", CONDITION_ESTIMATED)
        planned.append(
            _PlannedObservation(
                meter_id=meter_id,
                metering_point=None,
                timestamp=ts,
                direction=direction,
                energy=energy,
                condition=condition,
                billable=billable,
                block_id=doc_id,
            )
        )
    return (
        "block",
        _PlanBlock(
            document_id=doc_id,
            product=product,
            unit=measure_unit,
            observations=planned,
        ),
    )


def _fetch_existing(blocks):
    """Lock delivered intervals without loading gaps between sparse blocks."""
    by_point = {}
    for block in blocks:
        first = block.observations[0]
        key = (first.metering_point.pk, first.direction)
        timestamps = [obs.timestamp for obs in block.observations]
        by_point.setdefault(key, []).append((min(timestamps), max(timestamps)))
    intervals = []
    for (point_id, direction), ranges in sorted(by_point.items()):
        merged = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1] + timedelta(minutes=RESOLUTION_MINUTES):
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        intervals.extend((point_id, direction, start, end) for start, end in merged)
    streams = []
    for model in (MeterReading, QuarantinedReading):
        existing = {}
        for offset in range(0, len(intervals), 200):
            scope = Q()
            for point_id, direction, start, end in intervals[offset:offset + 200]:
                scope |= Q(metering_point_id=point_id, direction=direction,
                           timestamp__gte=start, timestamp__lte=end)
            for row in model.objects.filter(scope).order_by("metering_point_id", "timestamp", "direction").select_for_update():
                existing[(row.metering_point_id, row.timestamp, row.direction)] = row
        streams.append(existing)
    return streams


def _is_protected_source(row):
    return row is not None and row.import_source != ImportSource.SDATCH


def _same_observation(row, obs, reason):
    return (row.energy_kwh == obs.energy and row.condition == obs.condition
            and row.resolution == RESOLUTION_LABEL and row.business_reason == reason)


def _decide_slot(obs, *, existing, quarantined, is_replace, creation, reason):
    """Decide one slot. Returns (action, payload).

    Actions: create-billable, overwrite-billable, skip (counter name),
    hold (create/update quarantine), reject-source, reject-conflict.
    Promotion (deleting the matching quarantine row) is handled by the
    caller whenever a billable write actually commits.
    """
    if obs.billable:
        if existing is not None and _is_protected_source(existing):
            return ("reject-source", existing)
        # Informational freshness must not block validated billing.
        if existing is None:
            return ("create-billable", None)
        existing_creation = existing.source_creation
        if existing_creation is not None and creation < existing_creation:
            return ("skip", "stale")
        if existing_creation is not None and creation == existing_creation:
            if _same_observation(existing, obs, reason):
                return ("skip", "duplicate")
            return ("reject-conflict", existing)
        if not is_replace:
            # Originals never overwrite: skip-existing, even when newer.
            return ("skip", "original_existing")
        return ("overwrite-billable", None)
    if existing is not None and _is_protected_source(existing):
        return ("reject-source", existing)
    if quarantined is None:
        if (
            existing is not None
            and existing.source_creation is not None
            and existing.source_creation >= creation
        ):
            # A stale info delivery must not shadow validated billing data.
            return ("skip", "stale")
        return ("hold", "create")
    quar_creation = quarantined.source_creation
    if quar_creation is not None and creation < quar_creation:
        return ("skip", "stale")
    if quar_creation is not None and creation == quar_creation:
        if _same_observation(quarantined, obs, reason):
            return ("skip", "duplicate")
        return ("reject-conflict", quarantined)
    if not is_replace:
        return ("skip", "original_existing")
    return ("hold", "update")


def _conflict_issue(obs, row, *, creation, delivery_id):
    return _issue(
        ISSUE_EQUAL_CREATION_CONFLICT,
        f"Equal-Creation conflict at {obs.timestamp.isoformat()} ({obs.direction}): "
        f"incoming block '{obs.block_id}' of delivery '{delivery_id}' (Creation {creation.isoformat()}) disagrees with "
        f"stored document '{row.source_document_id or '?'}'.",
        meter_id=obs.meter_id,
        position_timestamp=obs.timestamp.isoformat(),
        direction=obs.direction,
        incoming_document_id=obs.block_id,
        incoming_delivery_id=delivery_id,
        stored_document_id=row.source_document_id or None,
        stored_delivery_id=row.source_delivery_id or None,
        creation=creation.isoformat(),
    )


READING_UPDATE_FIELDS = (
    "energy_kwh", "resolution", "import_source", "import_batch", "source_creation",
    "source_document_id", "source_delivery_id", "business_reason", "condition",
    "source_product", "source_unit", "source_meter_id",
)


def _reading_values(obs, block, *, batch_id, reason, creation, delivery_id):
    return {
        "energy_kwh": obs.energy, "resolution": RESOLUTION_LABEL,
        "import_source": ImportSource.SDATCH, "import_batch": batch_id,
        "source_creation": creation, "source_document_id": obs.block_id,
        "source_delivery_id": delivery_id, "business_reason": reason,
        "condition": obs.condition, "source_product": block.product,
        "source_unit": block.unit, "source_meter_id": obs.meter_id,
    }


def _apply_plan(*, batch_id, blocks, reason, creation, delivery_id, is_replace, run):
    """Compare + write every planned slot inside the caller's transaction."""
    by_key_billable, by_key_quarantine = _fetch_existing(blocks)

    new_billable = []
    update_billable = []
    new_quarantine = []
    update_quarantine = []
    drop_quarantine = []
    change_log = ReadingChangeRecorder(cap=READING_CHANGE_CAP)

    def record_change(obs, *, kind, old, new, promoted=False):
        change_log.record(
            metering_point=obs.metering_point,
            timestamp=obs.timestamp,
            direction=obs.direction,
            kind=kind,
            old=old,
            new=new,
            promoted=promoted,
            source_document_id=obs.block_id,
        )

    def promote(obs, quarantined):
        if quarantined is None or (
            quarantined.source_creation is not None and quarantined.source_creation > creation
        ):
            return False
        drop_quarantine.append(quarantined)
        del by_key_quarantine[(obs.metering_point.pk, obs.timestamp, obs.direction)]
        run.counts["promoted"] += 1
        return True

    for block in blocks:
        for obs in block.observations:
            key = (obs.metering_point.pk, obs.timestamp, obs.direction)
            existing = by_key_billable.get(key)
            quarantined = by_key_quarantine.get(key)
            action, payload = _decide_slot(
                obs,
                existing=existing,
                quarantined=quarantined,
                is_replace=is_replace,
                creation=creation,
                reason=reason,
            )
            if action == "reject-source":
                raise _FileRejected(
                    [
                        _issue(
                            ISSUE_SOURCE_CONFLICT,
                            f"Overlapping non-SDAT reading at {obs.timestamp.isoformat()} "
                            f"({obs.direction}, meter '{obs.meter_id}'): overlaps protected CSV/manual data.",
                            meter_id=obs.meter_id,
                            position_timestamp=obs.timestamp.isoformat(),
                            direction=obs.direction,
                            block_id=obs.block_id,
                        )
                    ]
                )
            if action == "reject-conflict":
                raise _FileRejected([_conflict_issue(obs, payload, creation=creation, delivery_id=delivery_id)])
            if action == "skip":
                run.counts[payload] += 1
                continue
            values = _reading_values(
                obs, block, batch_id=batch_id, reason=reason,
                creation=creation, delivery_id=delivery_id,
            )
            if action == "create-billable":
                row = MeterReading(metering_point=obs.metering_point, timestamp=obs.timestamp,
                                   direction=obs.direction, **values)
                new_billable.append(row)
                by_key_billable[key] = row
                run.counts["created"] += 1
                record_change(obs, kind=ReadingChangeKind.AVAILABILITY, old=None, new=obs.energy,
                              promoted=promote(obs, quarantined))
            elif action == "overwrite-billable":
                old_energy = existing.energy_kwh
                input_changed = old_energy != obs.energy or existing.resolution != RESOLUTION_LABEL
                for field, value in values.items():
                    setattr(existing, field, value)
                update_billable.append(existing)
                run.counts["overwritten"] += 1
                record_change(obs, kind=ReadingChangeKind.VALUE if input_changed else ReadingChangeKind.METADATA,
                              old=old_energy, new=obs.energy, promoted=promote(obs, quarantined))
            elif payload == "create":
                new_quarantine.append(QuarantinedReading(
                    metering_point=obs.metering_point, timestamp=obs.timestamp,
                    direction=obs.direction, **values,
                ))
                run.counts["held"] += 1
            else:
                for field, value in values.items():
                    setattr(quarantined, field, value)
                update_quarantine.append(quarantined)
                run.counts["held"] += 1
                run.counts["quarantine_overwritten"] += 1

    for model, new, updated in (
        (MeterReading, new_billable, update_billable),
        (QuarantinedReading, new_quarantine, update_quarantine),
    ):
        if new:
            model.objects.bulk_create(new, batch_size=PERSIST_BATCH_SIZE)
        # Locked rows remain present; PK upserts avoid CASE-expression construction.
        for start in range(0, len(updated), PERSIST_BATCH_SIZE):
            model.objects.bulk_create(
                updated[start:start + PERSIST_BATCH_SIZE],
                update_conflicts=True, unique_fields=["pk"], update_fields=READING_UPDATE_FIELDS,
            )
    for start in range(0, len(drop_quarantine), PERSIST_BATCH_SIZE):
        batch = drop_quarantine[start:start + PERSIST_BATCH_SIZE]
        QuarantinedReading.objects.filter(pk__in=[row.pk for row in batch]).delete()
    run.affected_slots = change_log.affected_slots
    return change_log.changes, change_log.truncated


def _fail_early(log, code, message, **params):
    run = _ImportRun()
    run.add_issue(code, message, **params)
    return _fail_log(log, run)


def _resolve_plan(blocks, zev, run):
    """Resolve and lock current points, then reject incompatible or overlapping slots."""
    failed = False

    def reject(code, message, **params):
        nonlocal failed
        failed = True
        run.add_issue(code, message, **params)

    for block in sorted(blocks, key=lambda block: block.observations[0].meter_id):
        observed = block.observations[0].meter_id if block.observations else ""
        try:
            point = resolve_metering_point(zev, observed, for_update=True)
        except AmbiguousMeterIdentity as exc:
            reject(
                ISSUE_AMBIGUOUS_METER,
                f"Meter identity '{exc.identity}' matches several metering points; "
                f"observations cannot be attributed.",
                meter_id=exc.identity,
                block_id=block.document_id,
            )
            continue
        if point is None:
            reject(
                ISSUE_UNKNOWN_METER,
                f"Metering point '{observed or '?'}' not found in this ZEV.",
                meter_id=observed or "?",
                block_id=block.document_id,
            )
            continue
        direction = block.observations[0].direction
        allowed = (MeteringPointType.BIDIRECTIONAL,
                   MeteringPointType.CONSUMPTION if direction == ReadingDirection.IN else MeteringPointType.PRODUCTION)
        if point.meter_type not in allowed:
            reject(
                ISSUE_METER_DIRECTION_MISMATCH,
                f"Meter '{observed}' is configured as {point.meter_type} and cannot import {direction} readings.",
                meter_id=observed, block_id=block.document_id, direction=direction,
                meter_type=point.meter_type,
            )
            continue
        for obs in block.observations:
            obs.metering_point = point
    if failed:
        raise _FileRejected([])
    seen_slots = {}
    for block in blocks:
        for obs in block.observations:
            key = (obs.metering_point.pk, obs.timestamp, obs.direction)
            previous = seen_slots.get(key)
            if previous is not None:
                prev_block, prev_energy = previous
                if prev_energy != obs.energy:
                    raise _FileRejected(
                        [
                            _issue(
                                ISSUE_CONFLICTING_POSITION,
                                f"Slot {obs.timestamp.isoformat()} ({obs.direction}) for meter '{obs.meter_id}' "
                                f"is delivered twice with conflicting values (blocks '{prev_block}' and "
                                f"'{obs.block_id}').",
                                meter_id=obs.meter_id,
                                position_timestamp=obs.timestamp.isoformat(),
                                direction=obs.direction,
                                block_id=obs.block_id,
                                other_block_id=prev_block,
                            )
                        ]
                    )
                raise _FileRejected(
                    [
                        _issue(
                            ISSUE_DUPLICATE_POSITION,
                            f"Slot {obs.timestamp.isoformat()} ({obs.direction}) for meter '{obs.meter_id}' "
                            f"is delivered twice (blocks '{prev_block}' and '{obs.block_id}').",
                            meter_id=obs.meter_id,
                            position_timestamp=obs.timestamp.isoformat(),
                            direction=obs.direction,
                            block_id=obs.block_id,
                            other_block_id=prev_block,
                        )
                    ]
                )
            seen_slots[key] = (obs.block_id, obs.energy)


def import_sdatch(file, zev, user):
    """Commit a validated delivery or persist a rejected log without changing readings."""
    from allocation.validity import business_tz

    batch_id = uuid.uuid4()
    filename = getattr(file, "name", "upload.xml")

    log = ImportLog(
        batch_id=batch_id,
        zev=zev,
        imported_by=user,
        source=ImportSource.SDATCH,
        filename=filename,
        timestamp_timezone=str(business_tz()),
    )
    run = _ImportRun()

    # Size hints may be missing or wrong; actual byte counts are enforced below.
    size_hint = getattr(file, "size", None)
    if size_hint is not None and size_hint > MAX_SDAT_BYTES:
        return _fail_early(
            log,
            ISSUE_FILE_TOO_LARGE,
            f"File too large ({mb(size_hint)}). Maximum is {mb(MAX_SDAT_BYTES)}.",
            size_bytes=size_hint,
            limit_bytes=MAX_SDAT_BYTES,
        )

    try:
        raw = file.read(MAX_SDAT_BYTES + 1)
    except Exception:
        logger.exception("SDAT upload stream failed for import %s", log.pk)
        return _fail_early(log, ISSUE_INTERNAL_ERROR, "Could not read the upload. Contact support with the import log ID.",
                           import_log_id=str(log.pk))
    if len(raw) > MAX_SDAT_BYTES:
        return _fail_early(
            log,
            ISSUE_FILE_TOO_LARGE,
            f"File too large ({mb(len(raw))}). Maximum is {mb(MAX_SDAT_BYTES)}.",
            limit_bytes=MAX_SDAT_BYTES,
        )

    if filename.lower().endswith(".gz"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
                raw = gz.read(MAX_SDAT_DECOMPRESSED_BYTES + 1)
        except Exception as exc:
            return _fail_early(log, ISSUE_GZIP_ERROR, f"Could not decompress gzip file: {exc}")
        if len(raw) > MAX_SDAT_DECOMPRESSED_BYTES:
            return _fail_early(
                log,
                ISSUE_DECOMPRESSED_TOO_LARGE,
                f"Decompressed file too large. Maximum is {mb(MAX_SDAT_DECOMPRESSED_BYTES)}.",
                limit_bytes=MAX_SDAT_DECOMPRESSED_BYTES,
            )

    try:
        parser = etree.XMLParser(
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            huge_tree=False,
        )
        root = etree.fromstring(raw, parser)
    except Exception as exc:
        return _fail_early(log, ISSUE_MALFORMED_XML, f"Malformed SDAT-CH XML: {exc}", **_xml_error_params(exc))

    root_name = _local(root.tag)
    root_ns = root.tag.rsplit("}", 1)[0][1:] if "}" in root.tag else ""

    # Strict policy: only the current schema version is parsed; anything else is a named rejection.
    if root_name == STRICT_ROOT and root_ns == SDAT_NS:
        pass
    elif root_name == STRICT_ROOT:
        return _fail_early(
            log,
            ISSUE_UNSUPPORTED_ROOT,
            f"Wrong XML namespace '{root_ns or '?'}'; expected '{SDAT_NS}'.",
            detail_code="wrong_namespace", root_element=root_name, namespace=root_ns,
        )
    elif root_name.startswith("ValidatedMeteredData_"):
        return _fail_early(
            log,
            ISSUE_UNSUPPORTED_SCHEMA_VERSION,
            f"Schema version {root_name} is not supported; only {STRICT_ROOT} (SDAT-CH 2025, 15-minute active energy) is imported.",
            root_element=root_name,
        )
    elif root_name.startswith("AggregatedMeteredData_"):
        detail = "AggregatedMeteredData holds grid-area/balance-group sums, not per-meter data."
        return _fail_early(
            log,
            ISSUE_UNSUPPORTED_ROOT,
            f"Not a ValidatedMeteredData (E66) file. {detail}",
            detail_code="aggregated_data", root_element=root_name,
        )
    elif root_name.startswith("ImbalanceData_"):
        detail = "ImbalanceData holds balance-settlement series, not per-meter data."
        return _fail_early(
            log,
            ISSUE_UNSUPPORTED_ROOT,
            f"Not a ValidatedMeteredData (E66) file. {detail}",
            detail_code="imbalance_data", root_element=root_name,
        )
    else:
        detail = f"Unsupported root element '{root_name}'."
        return _fail_early(
            log,
            ISSUE_UNSUPPORTED_ROOT,
            f"Not a ValidatedMeteredData (E66) file. {detail}",
            root_element=root_name,
        )

    try:
        schema = _load_schema_16()
    except Exception:
        logger.exception("SDAT schema unavailable for import %s", log.pk)
        return _fail_early(log, ISSUE_VALIDATION_UNAVAILABLE,
                           "Schema validation is unavailable. Contact support with the import log ID.",
                           import_log_id=str(log.pk))

    # Cancellations are detected before schema validation (the E66 schema only permits 9/5).
    pre_header = root.find(_qname("ValidatedMeteredData_HeaderInformation"))
    pre_instance = pre_header.find(_qname("InstanceDocument")) if pre_header is not None else None
    if pre_instance is not None and _text(pre_instance, "Status") == STATUS_CANCELLATION:
        return _fail_early(
            log, ISSUE_CANCELLATION_REJECTED, "Document Status is 1 (cancellation). Cancellations are not imported."
        )
    try:
        schema.assertValid(root)
    except etree.DocumentInvalid as exc:
        return _fail_early(log, ISSUE_SCHEMA_INVALID, f"Schema validation failed: {exc}", **_xml_error_params(exc))

    try:
        delivery, reason, creation, is_replace, report_period = _validate_header(run, root)
    except _FileRejected as rejected:
        run.add_issues(rejected.issues)
        return _fail_log(log, run)

    delivery_id = delivery["delivery_id"]

    # Phase 1: parse every block (no writes, no DB reads yet).
    run.rows_total = sum(1 for _ in root.iter(_qname("Observation")))
    blocks = []
    excluded_notes = []
    try:
        for md in root.iter(_qname("MeteringData")):
            outcome = _parse_block(md, reason=reason, report_period=report_period)
            if outcome[0] == "excluded":
                _, count, note = outcome
                run.counts["excluded"] += count
                excluded_notes.append(note)
            else:
                _, block = outcome
                blocks.append(block)
    except _FileRejected as rejected:
        run.add_issues(rejected.issues)

        return _fail_log(log, run)
    for note in excluded_notes:
        run.add_issue(note["code"], note["message"], severity="info",
                      **{k: v for k, v in note.items() if k not in ("code", "severity", "message")})

    if not blocks and not excluded_notes:
        run.add_issue(ISSUE_EMPTY_DELIVERY, "Delivery carries no MeteringData blocks.")
        return _fail_log(log, run)

    # Resolve current identities and commit under the billing-input lock.
    try:
        with transaction.atomic():
            _lock_zev_imports(zev)
            _resolve_plan(blocks, zev, run)
            changes, changes_truncated = _apply_plan(
                batch_id=batch_id,
                blocks=blocks,
                reason=reason,
                creation=creation,
                delivery_id=delivery_id,
                is_replace=is_replace,
                run=run,
            )
            if run.counts["created"] + run.counts["overwritten"] > 0:
                status = SdatResultStatus.ACCEPTED
            elif run.counts["held"] > 0:
                status = SdatResultStatus.HELD
            else:
                status = SdatResultStatus.UNCHANGED
                if run.counts["stale"] > 0:
                    run.add_issue(
                        ISSUE_STALE_SUPERSEDED,
                        f"Skipped {run.counts['stale']} observations superseded by newer deliveries; nothing changed.",
                        severity="info",
                        stale=run.counts["stale"],
                    )
                elif run.counts["duplicate"] > 0:
                    run.add_issue(
                        ISSUE_DUPLICATE_DELIVERY,
                        f"Skipped {run.counts['duplicate']} observations already imported; nothing changed.",
                        severity="info",
                        duplicate=run.counts["duplicate"],
                    )
            if run.counts["original_existing"] > 0:
                run.add_issue(
                    ISSUE_ORIGINAL_EXISTS,
                    "Original delivery overlaps existing readings; request a replacement delivery to correct them.",
                    severity="info", original_existing=run.counts["original_existing"],
                )
            _add_legacy_warnings(run)
            _finalize_log(log, run, status=status, changes=changes, changes_truncated=changes_truncated)
            # Invoice flags join the same transaction: flags and reading
            # changes commit or roll back together.
            from invoices.reading_impact import flag_import_impacts

            flag_import_impacts(
                zev=zev,
                import_log=log,
                changes_truncated=changes_truncated,
                delivery=run.delivery,
                affected_slots=run.affected_slots,
            )
        return log
    except _FileRejected as rejected:
        run.add_issues(rejected.issues)
        return _fail_log(log, run)
    except Exception:  # noqa: BLE001 — persist the failed-attempt log after rollback.
        logger.exception("SDAT import %s failed", log.pk)
        run.add_issue(ISSUE_INTERNAL_ERROR, "Import failed. Contact support with the import log ID.",
                      import_log_id=str(log.pk))

        return _fail_log(log, run)


def _add_legacy_warnings(run):
    """Human-readable summary notes kept for the existing protocol display."""
    held = run.counts["held"]
    promoted = run.counts["promoted"]
    if held or promoted:
        run.warnings.append(
            {
                "warning": (
                    f"Quarantined {held} info-only/temporary observations "
                    f"(not billable); promoted {promoted} to billing."
                )
            }
        )
    for issue in run.issues:
        if issue.get("severity") == "info" and issue.get("code") in (
            ISSUE_REACTIVE_EXCLUDED,
            ISSUE_LEG_EXCLUDED,
            ISSUE_EXCHANGE_EXCLUDED,
        ):
            run.warnings.append({"warning": issue["message"]})
