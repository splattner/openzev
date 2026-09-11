"""Pure computation for the readiness and attention endpoints (spec §7).

Mirrors ``period_overview.py``: query logic without a request layer, so it can
be unit-tested independently of DRF.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Exists, F, OuterRef, Q, Subquery, Window
from django.db.models.functions import RowNumber

from allocation.validity import period_window
from metering.models import MeterReading
from tariffs.dynamic.fetch import coverage_gaps
from tariffs.dynamic.models import DynamicTariffSource
from tariffs.models import BillingMode, EnergyType, Tariff, TariffCategory
from zev.models import MeteringPoint, MeteringPointAssignment, Participant

from .models import EmailLog, Invoice, InvoiceStatus


# Billing-period alignment

INTERVAL_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "semi_annual": 6,
    "annual": 12,
}

HISTORY_FLOOR = date(2020, 1, 1)
MIN_SUPPORTED_DATE = date(1900, 1, 1)
MAX_SUPPORTED_DATE = date(9998, 12, 31)


def period_starts(
    start: date, interval: str, months: int | None = None, today: date | None = None
) -> list[date]:
    """Aligned period starts, newest first, each on or after ``start``.

    A partial first period (start off an aligned boundary) is skipped;
    ``months`` caps the walkback; ``today`` pins "now" for tests.
    """
    step = INTERVAL_MONTHS[interval]
    # A mid-period start skips its partial containing period.
    anchor_month = (start.year * 12 + start.month - 1) - ((start.month - 1) % step)
    aligned = start.day == 1 and start.month - 1 == anchor_month % 12
    first_month = anchor_month if aligned else anchor_month + step
    first_year, first_mon = divmod(first_month, 12)
    first_start = date(first_year, first_mon + 1, 1)

    today = today or date.today()
    current_month = today.year * 12 + today.month - 1
    current_anchor_month = current_month - ((today.month - 1) % step)
    current_year, current_mon = divmod(current_anchor_month, 12)
    current_start = date(current_year, current_mon + 1, 1)

    starts: list[date] = []
    cursor = current_start
    while months is None or len(starts) < months:
        if cursor >= first_start:
            starts.append(cursor)
        month_index = cursor.year * 12 + cursor.month - 1 - step
        if month_index < first_month:
            break
        year, mon = divmod(month_index, 12)
        cursor = date(year, mon + 1, 1)
    return starts


def period_end(start: date, interval: str) -> date:
    months = INTERVAL_MONTHS[interval]
    month_index = start.year * 12 + start.month - 1 + months
    year, mon = divmod(month_index, 12)
    return date(year, mon + 1, 1) - timedelta(days=1)


def is_ended(end: date, today: date | None = None) -> bool:
    today = today or date.today()
    return end < today



# Cockpit period resolution


def _overlaps(valid_from: date, valid_to: date | None, start: date, end: date) -> bool:
    return valid_from <= end and (valid_to is None or valid_to >= start)


def _spans_cover(
    periods: list[tuple[date, date]], start: date, end: date
) -> bool:
    """True when the day-union of ``periods`` fully covers [start, end]."""
    cursor = start
    for period_start, period_end in sorted(periods):
        if period_start > cursor:
            break
        if period_end >= cursor:
            cursor = period_end + timedelta(days=1)
        if cursor > end:
            return True
    return cursor > end


def _history_anchor(zev) -> date:
    """Oldest billing period considered for the ZEV (``start_date`` floor)."""
    return max(zev.start_date, HISTORY_FLOOR)


def _eligible_assignment_rows(
    participants: dict[int, "Participant"],
    assignments: list[tuple[int, int, date, date | None]],
    period_start: date,
    period_end: date,
) -> list[tuple[int, int, date, date]]:
    """(participant, meter point, effective start, effective end) for
    assignments whose holder is active in the period (the period-overview
    row membership)."""
    rows = []
    for pid, mp_id, vf, vt in assignments:
        participant = participants.get(pid)
        if participant is None:
            continue
        if not _overlaps(participant.valid_from, participant.valid_to, period_start, period_end):
            continue
        if not _overlaps(vf, vt, period_start, period_end):
            continue
        effective_start = max(period_start, vf)
        effective_end = min(period_end, vt if vt is not None else period_end)
        if effective_start <= effective_end:
            rows.append((pid, mp_id, effective_start, effective_end))
    return rows


def _billable_participant_ids_from(
    participants: dict[int, "Participant"],
    assignments: list[tuple[int, int, date, date | None]],
    period_start: date,
    period_end: date,
) -> set[int]:
    """Ids of the participants Generate must invoice for the period."""
    return {
        pid
        for pid, _mp_id, _start, _end in _eligible_assignment_rows(
            participants, assignments, period_start, period_end
        )
    }


def resolve_cockpit_period(zev, today: date | None = None) -> tuple[date, date] | None:
    """Most recent ENDED period with open work: a draft/approved invoice, or
    a billable participant missing one (partial batches stay open)."""
    today = today or date.today()
    if not _has_master_data(zev):
        return None
    interval = zev.billing_interval
    ended = [
        (start, period_end(start, interval))
        for start in period_starts(_history_anchor(zev), interval, today=today)
        if is_ended(period_end(start, interval), today)
    ]

    participants = {
        p.id: (p.valid_from, p.valid_to)
        for p in Participant.objects.filter(zev=zev).only("id", "valid_from", "valid_to")
    }
    assignments: dict[int, list[tuple[date, date | None]]] = {}
    for pid, valid_from, valid_to in (
        MeteringPointAssignment.objects.filter(metering_point__zev=zev)
        .values_list("participant_id", "valid_from", "valid_to")
    ):
        assignments.setdefault(pid, []).append((valid_from, valid_to))

    # Invoices cover only their exact (start, end) — a January invoice must
    # not count for the Jan–Mar quarter after an interval change — unless the
    # whole period is already settled by sent/paid sub-period invoices.
    # Cancelled invoices are not work: they neither cover a period nor gate it.
    # One query feeds all three structures below (was three full-table scans).
    generated_by_period: dict[tuple[date, date], set[int]] = {}
    pending_periods: set[tuple[date, date]] = set()
    settled_spans: dict[int, list[tuple[date, date]]] = {}
    for pid, start, end, status in (
        Invoice.objects.filter(zev=zev).values_list(
            "participant_id", "period_start", "period_end", "status"
        ).iterator()
    ):
        if status == InvoiceStatus.CANCELLED or start is None or end is None:
            continue
        generated_by_period.setdefault((start, end), set()).add(pid)
        if status in (InvoiceStatus.DRAFT, InvoiceStatus.APPROVED):
            pending_periods.add((start, end))
        if status in (InvoiceStatus.SENT, InvoiceStatus.PAID):
            settled_spans.setdefault(pid, []).append((start, end))

    candidates: list[tuple[date, date]] = []
    for start, end in ended:
        if (start, end) in pending_periods:
            candidates.append((start, end))
            continue
        eligible = [
            pid
            for pid, (valid_from, valid_to) in participants.items()
            if _overlaps(valid_from, valid_to, start, end)
            and any(
                _overlaps(vf, vt, start, end)
                for vf, vt in assignments.get(pid, ())
            )
        ]
        have = generated_by_period.get((start, end), set())
        open_participants = [
            pid
            for pid in eligible
            if pid not in have
            and not _spans_cover(settled_spans.get(pid, ()), start, end)
        ]
        if open_participants:
            candidates.append((start, end))
    # A leftover draft from an earlier interval never aligns to the current
    # one, so ended pending periods join the candidates explicitly.
    candidates.extend(
        (ps, pe)
        for ps, pe in pending_periods
        if ps is not None and pe is not None and pe < today
    )
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p[1], p[0]))


def _has_master_data(zev) -> bool:
    return MeteringPoint.objects.filter(zev=zev).exists() and Participant.objects.filter(zev=zev).exists()


# Readiness steps

@dataclass
class StepResult:
    key: str
    status: str  # ok | warn | todo | done
    count: int
    total: int | None = None
    failed: int | None = None
    detail: str | None = None
    link: str | None = None
    # Structured fields the UI localizes from; `detail` is the English fallback.
    detail_data: dict = field(default_factory=dict)


def _tariff_active_on(tariff: Tariff, day: date) -> bool:
    return tariff.valid_from <= day and (tariff.valid_to is None or tariff.valid_to >= day)


def _load_energy_tariffs(zev) -> list[Tariff]:
    """Energy-mode and percentage tariffs with their price bands."""
    return list(
        Tariff.objects.filter(
            zev=zev,
            category=TariffCategory.ENERGY,
            billing_mode__in=[BillingMode.ENERGY, BillingMode.PERCENTAGE_OF_ENERGY],
        ).prefetch_related("periods")
    )


def _dynamic_uncovered_days_by_source(
    source_ids: set, start: date, end: date
) -> dict:
    """Days in ``[start, end]`` each dynamic source's series has a gap in.

    One ``coverage_gaps`` query per source for the *whole* span — this is the
    span-wide preload ``_load_bulk`` does once, not something recomputed per
    period when ``compute_readiness_many`` reuses one ``BulkData`` across many.

    A day counts as uncovered if the series has a gap anywhere inside it.
    Never derived from an interval count: a quarter-hourly day is 92, 96 or
    100 intervals depending on daylight saving, so counting would flag a
    perfectly priced DST day as broken twice a year.
    """
    if not source_ids:
        return {}
    span_start, span_end = period_window(start, end)
    uncovered_by_source: dict = {}
    for source in DynamicTariffSource.objects.filter(pk__in=source_ids):
        uncovered: set[date] = set()
        for gap_start, gap_end in coverage_gaps(source, span_start, span_end):
            day = gap_start.date()
            last_day = (gap_end - timedelta(microseconds=1)).date()
            while day <= last_day:
                uncovered.add(day)
                day += timedelta(days=1)
        uncovered_by_source[source.pk] = uncovered
    return uncovered_by_source


def _tariff_is_priced_on(tariff: Tariff, day: date, dynamic_uncovered: dict) -> bool:
    """Whether ``tariff`` has an actual price to bill with on ``day``.

    A static tariff needs at least one price band — the engine falls back to
    the season's first band once any band exists, so the mere presence of a
    band (any season, any window) counts as coverage. A dynamic tariff instead
    needs its fetched series to have no gap that day: a band existing tells
    you nothing about whether a series was ever fetched, and the engine
    refuses to bill a gap rather than falling back to anything (#530).
    """
    if tariff.dynamic_source_id:
        return day not in dynamic_uncovered.get(tariff.dynamic_source_id, ())
    return len(tariff.periods.all()) > 0


def _uncovered_tariff_days(
    energy_tariffs: list[Tariff],
    pct_tariffs: list[Tariff],
    start: date,
    end: date,
    dynamic_uncovered: dict | None = None,
) -> list[date]:
    """Days the billing engine cannot price end-to-end.

    Every configured energy type — direct or percentage — must be priced every
    day: a priced tariff of one type must not mask a missing one of another.
    A percentage tariff prices its own energy type through the grid rate, so
    it needs a priced grid tariff on the days it applies.
    """
    dynamic_uncovered = dynamic_uncovered or {}
    needed_types = {t.energy_type for t in energy_tariffs} | {
        t.energy_type for t in pct_tariffs
    }
    if not needed_types:
        return []
    uncovered: list[date] = []
    day = start
    while day <= end:
        covered = {
            t.energy_type
            for t in energy_tariffs
            if _tariff_active_on(t, day) and _tariff_is_priced_on(t, day, dynamic_uncovered)
        }
        pct_active = [
            t
            for t in pct_tariffs
            if t.percentage and _tariff_active_on(t, day)
        ]
        # A percentage tariff prices its own type through the grid rate: when
        # the grid is priced it covers its type, otherwise the grid itself
        # becomes an additional missing type for that day.
        day_needed = needed_types
        if pct_active and EnergyType.GRID in covered:
            covered = covered | {t.energy_type for t in pct_active}
        elif pct_active:
            day_needed = needed_types | {EnergyType.GRID}
        if day_needed - covered:
            uncovered.append(day)
        day += timedelta(days=1)
    return uncovered


def _tariffs_step_from_list(
    energy: list[Tariff],
    pct: list[Tariff],
    period_start: date,
    period_end: date,
    dynamic_uncovered: dict | None = None,
) -> StepResult:
    tariffs_link = "/tariffs"
    if not energy and not pct:
        return StepResult(
            "tariffs",
            "todo",
            0,
            total=(period_end - period_start).days + 1,
            detail="No energy tariff configured",
            link=tariffs_link,
        )

    uncovered_days = _uncovered_tariff_days(energy, pct, period_start, period_end, dynamic_uncovered)
    if not uncovered_days:
        return StepResult("tariffs", "ok", 0)
    ranges: list[dict] = []
    range_start = prev = uncovered_days[0]
    for day in uncovered_days[1:]:
        if day == prev + timedelta(days=1):
            prev = day
            continue
        ranges.append({"from": range_start.isoformat(), "to": prev.isoformat()})
        range_start = prev = day
    ranges.append({"from": range_start.isoformat(), "to": prev.isoformat()})

    visible = ranges[:4]
    extra = max(0, len(ranges) - len(visible))
    detail = "No energy tariff covers: " + ", ".join(
        _fmt_range_str(r["from"], r["to"]) for r in visible
    ) + ("…" if extra else "")
    return StepResult(
        "tariffs",
        "warn",
        len(uncovered_days),
        total=(period_end - period_start).days + 1,
        detail=detail,
        detail_data={"ranges": visible, "more_ranges": extra},
        link=tariffs_link,
    )


def _fmt_range_str(from_iso: str, to_iso: str) -> str:
    if from_iso == to_iso:
        return from_iso
    return f"{from_iso}..{to_iso}"


NEXT_ACTION_BY_STEP = {
    "metering": "fix_metering",
    "assignments": "fix_assignments",
    "tariffs": "fix_tariffs",
    "generated": "generate",
    "generation_conflicts": "review_generation_conflicts",
    "approved": "approve",
    "sent": "send",
    "paid": "track_payments",
}


def _select_next_action(steps: list[StepResult]) -> str:
    for step in steps:
        if step.status in ("warn", "todo"):
            return NEXT_ACTION_BY_STEP.get(step.key, "none")
    return "none"


def compute_readiness(zev, period_start: date, period_end: date) -> dict:
    """The readiness payload for one period (frozen contract, spec §7).

    Loads the bounded period dataset and runs the same step computations
    as the bulk path, so single and bulk results match structurally.
    """
    data = _load_bulk(zev, period_start, period_end)
    return _bulk_period_readiness(zev, data, period_start, period_end)


def step_to_dict(step: StepResult) -> dict:
    data = {
        "key": step.key,
        "status": step.status,
        "count": step.count,
    }
    if step.total is not None:
        data["total"] = step.total
    if step.failed is not None:
        data["failed"] = step.failed
    if step.detail is not None:
        data["detail"] = step.detail
    if step.detail_data:
        data["detail_data"] = step.detail_data
    if step.link is not None:
        data["link"] = step.link
    return data


@dataclass
class BulkData:
    meter_id_by_mp: dict[int, str]
    participants: dict[int, "Participant"]
    assignments: list[tuple[int, int, date, date | None]]  # (pid, mp, vf, vt)
    readings: dict[int, dict[date, int]]  # meter -> {day: reading count}
    energy: list[Tariff]
    pct: list[Tariff]
    dynamic_uncovered: dict  # dynamic source id -> {uncovered day, ...}, span-wide
    invoice_rows: list[tuple[int, int, date, date, str, str]]  # (id, pid, ps, pe, status, number)
    latest_email_status: dict[int, str]  # per invoice id


def _newest_email_logs_qs(zev):
    """The newest email log per invoice (statuses of live invoices only)."""
    return (
        EmailLog.objects.filter(invoice__zev=zev)
        .exclude(invoice__status__in=[InvoiceStatus.PAID, InvoiceStatus.CANCELLED])
        .annotate(
            _attempt_rank=Window(
                expression=RowNumber(),
                partition_by=[F("invoice_id")],
                order_by=["-created_at", "-id"],
            )
        )
        .filter(_attempt_rank=1)
    )


def _load_bulk(zev, span_start: date, span_end: date) -> BulkData:
    meter_id_by_mp = dict(
        MeteringPoint.objects.filter(zev=zev).values_list("id", "meter_id")
    )
    mp_ids = list(meter_id_by_mp)
    participants = {
        p.id: p
        for p in Participant.objects.filter(zev=zev).only(
            "id", "valid_from", "valid_to", "first_name", "last_name"
        )
    }
    assignments = list(
        MeteringPointAssignment.objects.filter(metering_point_id__in=mp_ids)
        .values_list("participant_id", "metering_point_id", "valid_from", "valid_to")
    )
    start_dt, end_dt = period_window(span_start, span_end)
    readings: dict[int, dict[date, int]] = {}
    if mp_ids:
        # Stream the rows instead of materialising the whole history in memory;
        # only the per-meter/day counts are kept.
        reading_rows = MeterReading.objects.filter(
            metering_point_id__in=mp_ids,
            timestamp__gte=start_dt,
            timestamp__lt=end_dt,
        ).values_list("metering_point_id", "timestamp")
        for mp_id, ts in reading_rows.iterator():
            day = ts.date()
            counts = readings.setdefault(mp_id, {})
            counts[day] = counts.get(day, 0) + 1
    tariffs = _load_energy_tariffs(zev)
    energy = [t for t in tariffs if t.billing_mode == BillingMode.ENERGY]
    pct = [t for t in tariffs if t.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY]
    dynamic_source_ids = {t.dynamic_source_id for t in tariffs if t.dynamic_source_id}
    dynamic_uncovered = _dynamic_uncovered_days_by_source(dynamic_source_ids, span_start, span_end)
    # Newest first per participant so `_bulk_invoice_steps` picks the same
    # invoice as the single-period path when duplicates exist. Bounded to the
    # requested span so old ZEVs don't load their entire invoice history.
    invoices = list(
        Invoice.objects.filter(
            zev=zev, period_start__lte=span_end, period_end__gte=span_start
        )
        .order_by("participant_id", "-created_at", "-id")
        .values_list("id", "participant_id", "period_start", "period_end", "status", "invoice_number")
    )
    latest_email_status: dict[int, str] = {}
    for invoice_id, status in _newest_email_logs_qs(zev).values_list(
        "invoice_id", "status"
    ):
        latest_email_status.setdefault(invoice_id, status)
    return BulkData(
        meter_id_by_mp=meter_id_by_mp,
        participants=participants,
        assignments=assignments,
        readings=readings,
        energy=energy,
        pct=pct,
        dynamic_uncovered=dynamic_uncovered,
        invoice_rows=invoices,
        latest_email_status=latest_email_status,
    )


def _bulk_metering(data: BulkData, period_start: date, period_end: date) -> StepResult:
    eligible = [
        (mp_id, eff_start, eff_end)
        for _pid, mp_id, eff_start, eff_end in _eligible_assignment_rows(
            data.participants, data.assignments, period_start, period_end
        )
    ]
    if not eligible:
        return StepResult("metering", "ok", 0)

    windows_by_mp: dict[int, list[tuple[date, date]]] = {}
    for mp_id, eff_start, eff_end in eligible:
        windows_by_mp.setdefault(mp_id, []).append((eff_start, eff_end))

    meter_gaps: list[dict] = []
    missing_days_total = 0
    for mp_id in sorted(windows_by_mp):
        expected: set[date] = set()
        for eff_start, eff_end in windows_by_mp[mp_id]:
            day = eff_start
            while day <= eff_end:
                expected.add(day)
                day += timedelta(days=1)
        covered = {
            day
            for day in expected
            if day in data.readings.get(mp_id, ())
        }
        missing = sorted(expected - covered)
        if missing:
            meter_gaps.append(
                {
                    "meter_id": data.meter_id_by_mp.get(mp_id, str(mp_id)),
                    "missing_days": len(missing),
                    "from": missing[0].isoformat(),
                    "to": missing[-1].isoformat(),
                }
            )
            missing_days_total += len(missing)

    total_points = len(windows_by_mp)
    if not meter_gaps:
        return StepResult("metering", "ok", 0, total=total_points)
    visible = meter_gaps[:3]
    extra = max(0, len(meter_gaps) - len(visible))
    detail_meters = ", ".join(
        f"{g['meter_id']}: {g['missing_days']} day(s) missing" for g in visible
    ) + (", …" if extra else "")
    return StepResult(
        "metering",
        "warn",
        len(meter_gaps),
        total=total_points,
        detail=(
            f"{len(meter_gaps)} point(s) with gaps totalling "
            f"{missing_days_total} day(s)"
            + (f"; {detail_meters}" if detail_meters else "")
        ),
        detail_data={
            "missing_days": missing_days_total,
            "meters": visible,
            "more_meters": extra,
        },
        link=f"/metering/quality?period_start={period_start.isoformat()}&period_end={period_end.isoformat()}",
    )


def _bulk_assignments(data: BulkData, period_start: date, period_end: date) -> StepResult:
    windows_by_mp: dict[int, list[tuple[date, date | None]]] = {}
    for _pid, mp_id, vf, vt in data.assignments:
        windows_by_mp.setdefault(mp_id, []).append((vf, vt))
    unassigned_days: set[date] = set()
    unassigned_readings = 0
    for mp_id, days in data.readings.items():
        for day, count in days.items():
            if day < period_start or day > period_end:
                continue
            windows = windows_by_mp.get(mp_id, ())
            if not any(vf <= day and (vt is None or vt >= day) for vf, vt in windows):
                unassigned_readings += count
                unassigned_days.add(day)
    if unassigned_readings == 0:
        return StepResult("assignments", "ok", 0)
    return StepResult(
        "assignments",
        "warn",
        unassigned_readings,
        detail=f"{unassigned_readings} reading(s) on days with no assignment holder",
        detail_data={
            "unassigned_readings": unassigned_readings,
            "unassigned_days": len(unassigned_days),
        },
        link=f"/metering/quality?period_start={period_start.isoformat()}&period_end={period_end.isoformat()}",
    )


def _covered_participant_ids(
    data: BulkData, billable: set[int], period_start: date, period_end: date
) -> set[int]:
    """Billable participants needing no generation: exact-period invoice, or
    full coverage by sent/paid sub-period invoices (regeneration would overlap
    locked invoices)."""
    covered = {
        pid
        for _inv_id, pid, ps, pe, status, _number in data.invoice_rows
        if (ps, pe) == (period_start, period_end)
        and status != InvoiceStatus.CANCELLED
    }
    if billable - covered:
        settled_spans: dict[int, list[tuple[date, date]]] = {}
        for _inv_id, pid, ps, pe, status, _number in data.invoice_rows:
            if status not in (InvoiceStatus.SENT, InvoiceStatus.PAID):
                continue
            if ps > period_end or pe < period_start:
                continue
            settled_spans.setdefault(pid, []).append((ps, pe))
        covered |= {
            pid
            for pid, rows in settled_spans.items()
            if _spans_cover(rows, period_start, period_end)
        }
    return covered


def _bulk_invoice_steps(data: BulkData, period_start: date, period_end: date) -> list[StepResult]:
    invoice_map: dict[int, tuple[int, date, date, str]] = {}
    for inv_id, pid, ps, pe, status, _number in data.invoice_rows:
        if (ps, pe) != (period_start, period_end):
            continue
        invoice_map.setdefault(pid, (inv_id, ps, pe, status))
    pool = [inv for inv in invoice_map.values() if inv[3] != InvoiceStatus.CANCELLED]
    by_status = Counter(inv[3] for inv in pool)
    draft = by_status.get(InvoiceStatus.DRAFT, 0)
    approved = by_status.get(InvoiceStatus.APPROVED, 0)
    sent = by_status.get(InvoiceStatus.SENT, 0)
    paid = by_status.get(InvoiceStatus.PAID, 0)
    pool_size = len(pool)

    failed_emails = {
        inv_id
        for inv_id, _pid, ps, pe, status, _number in data.invoice_rows
        if (ps, pe) == (period_start, period_end)
        and status not in (InvoiceStatus.PAID, InvoiceStatus.CANCELLED)
        and data.latest_email_status.get(inv_id) == EmailLog.Status.FAILED
    }

    link = f"/billing/invoices?period_start={period_start.isoformat()}&period_end={period_end.isoformat()}"

    # billable participant ids (active + assignment overlap)
    billable = _billable_participant_ids_from(
        data.participants, data.assignments, period_start, period_end
    )
    covered = _covered_participant_ids(data, billable, period_start, period_end)
    uncovered = billable - covered
    # Conflicted participants are not ordinary generation work: their remedy
    # is the generation_conflicts step, so they leave the missing set.
    conflicted = set(
        _locked_overlap_by_pid(data, uncovered, period_start, period_end)
    )
    missing_ids = sorted(uncovered - conflicted)
    generated_count = len(billable & covered)
    if not billable:
        generated = StepResult("generated", "done", 0, total=0)
    elif missing_ids:
        missing_names = [
            data.participants[pid].full_name
            for pid in sorted(
                missing_ids,
                key=lambda pid: (
                    data.participants[pid].last_name,
                    data.participants[pid].first_name,
                ),
            )
        ]
        generated = StepResult(
            "generated",
            "todo",
            generated_count,
            total=len(billable),
            detail=(
                f"{len(missing_ids)} of {len(billable)} participant(s) still "
                "have no invoice for this period"
            ),
            detail_data={
                "missing": len(missing_ids),
                "missing_participants": missing_names[:3],
                "more_missing": max(0, len(missing_names) - 3),
            },
            link=link,
        )
    else:
        generated = StepResult("generated", "done", generated_count, total=len(billable))

    if draft:
        approved_step = StepResult(
            "approved", "todo", draft, total=pool_size,
            detail=f"{draft} draft invoice(s) awaiting approval", link=link,
        )
    else:
        approved_step = StepResult("approved", "done", 0, total=pool_size)

    awaiting_send = approved
    if not pool:
        sent_step = StepResult("sent", "done", 0, total=0)
    elif awaiting_send or failed_emails:
        detail = (
            (f"{awaiting_send} approved invoice(s) not sent" if awaiting_send else "")
            + (
                f"; {len(failed_emails)} failed email delivery"
                + ("s" if len(failed_emails) != 1 else "")
                if failed_emails
                else ""
            )
        )
        sent_step = StepResult(
            "sent", "todo", awaiting_send, total=pool_size,
            failed=len(failed_emails) or None,
            detail=detail or None,
            link=link if (awaiting_send or failed_emails) else None,
        )
    elif draft:
        sent_step = StepResult("sent", "todo", 0, total=pool_size)
    else:
        sent_step = StepResult("sent", "done", 0, total=pool_size)

    unpaid_active = pool_size - paid
    if unpaid_active:
        paid_step = StepResult(
            "paid", "todo", sent, total=pool_size,
            detail=(
                f"{sent} sent invoice(s) awaiting payment"
                if sent
                else f"{unpaid_active} invoice(s) not yet paid"
            ),
            detail_data={"unpaid": unpaid_active},
            link=link if sent else None,
        )
    else:
        paid_step = StepResult("paid", "done", 0, total=pool_size)

    return [generated, approved_step, sent_step, paid_step]


def _locked_overlap_by_pid(
    data: BulkData, missing: set[int], period_start: date, period_end: date
) -> dict[int, list[dict]]:
    """Locked (approved/sent/paid) invoices overlapping the period per
    uncovered billable participant — the engine's replaceability rule."""
    locked_by_pid: dict[int, list[dict]] = {}
    for inv_id, pid, ps, pe, status, number in data.invoice_rows:
        if pid not in missing:
            continue
        if status in (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED):
            continue
        if ps > period_end or pe < period_start:
            continue
        locked_by_pid.setdefault(pid, []).append(
            {
                "id": str(inv_id),
                "number": number,
                "status": status,
                "start": ps.isoformat(),
                "end": pe.isoformat(),
            }
        )
    return locked_by_pid


def _bulk_generation_conflicts(
    data: BulkData, period_start: date, period_end: date
) -> StepResult:
    """Billable participants whose generation is blocked by locked overlapping
    invoices (same overlap/replaceability rule as the engine's
    ``locked_overlapping_invoices``): partial locked coverage is an explicit
    conflict, not ordinary generation. Draft/cancelled overlaps stay
    replaceable and never conflict."""
    link = f"/billing/invoices?period_start={period_start.isoformat()}&period_end={period_end.isoformat()}"
    billable = _billable_participant_ids_from(
        data.participants, data.assignments, period_start, period_end
    )
    missing = billable - _covered_participant_ids(
        data, billable, period_start, period_end
    )
    locked_by_pid = _locked_overlap_by_pid(data, missing, period_start, period_end)
    ordered = sorted(
        locked_by_pid,
        key=lambda pid: (
            data.participants[pid].last_name,
            data.participants[pid].first_name,
        ),
    )
    if not ordered:
        return StepResult("generation_conflicts", "ok", 0)
    conflicts = [
        {
            "participant_id": str(pid),
            "participant_name": data.participants[pid].full_name,
            "invoices": sorted(
                locked_by_pid[pid], key=lambda inv: (inv["start"], inv["end"], inv["id"])
            ),
        }
        for pid in ordered
    ]
    visible = conflicts[:3]
    extra = len(conflicts) - len(visible)
    names = ", ".join(c["participant_name"] for c in visible) + ("…" if extra else "")
    return StepResult(
        "generation_conflicts",
        "warn",
        len(conflicts),
        detail=(
            f"{len(conflicts)} participant(s) blocked by locked overlapping "
            f"invoices: {names}"
        ),
        detail_data={
            "conflict_count": len(conflicts),
            "conflicts": visible,
            "more_conflicts": extra,
        },
        link=link,
    )


def _bulk_period_readiness(
    zev, data: BulkData, period_start: date, period_end: date
) -> dict:
    invoice_steps = _bulk_invoice_steps(data, period_start, period_end)
    steps = [
        _bulk_metering(data, period_start, period_end),
        _bulk_assignments(data, period_start, period_end),
        _tariffs_step_from_list(data.energy, data.pct, period_start, period_end, data.dynamic_uncovered),
        _bulk_generation_conflicts(data, period_start, period_end),
        *invoice_steps,
    ]
    next_action = _select_next_action(steps)
    return {
        "period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "interval": zev.billing_interval,
        },
        "steps": [step_to_dict(step) for step in steps],
        "next_action": next_action,
    }


def compute_readiness_many(zev, starts: list[date]) -> list[dict]:
    """Readiness for a run of periods from one dataset (constant queries)."""
    if not starts:
        return []
    interval = zev.billing_interval
    span_start = min(starts)
    span_end = period_end(max(starts), interval)
    data = _load_bulk(zev, span_start, span_end)
    return [
        _bulk_period_readiness(zev, data, start, period_end(start, interval))
        for start in starts
    ]


def invoice_exact_periods(
    zev, anchor: date, today: date
) -> list[tuple[date, date]]:
    """Exact invoice (start, end) pairs inside the supported history, any
    status: cancellation must not erase historical navigation."""
    rows = (
        Invoice.objects.filter(
            zev=zev, period_start__gte=anchor, period_end__lte=today
        )
        .exclude(period_start__isnull=True)
        .exclude(period_end__isnull=True)
        .values_list("period_start", "period_end")
        .distinct()
    )
    return sorted(set(rows))


def list_periods(zev, today: date | None = None) -> list[tuple[date, date, str]]:
    """Union of current-calendar periods and exact invoice periods within the
    supported history, deduplicated by both dates, newest first by
    (end, start) — so a January monthly row coexists with its Jan–Mar
    quarter after an interval switch."""
    today = today or date.today()
    anchor = _history_anchor(zev)
    interval = zev.billing_interval
    calendar = {
        (start, period_end(start, interval))
        for start in period_starts(anchor, interval, today=today)
    }
    entries = [(start, end, "calendar") for start, end in calendar]
    entries.extend(
        (start, end, "invoice")
        for start, end in invoice_exact_periods(zev, anchor, today)
        if (start, end) not in calendar
    )
    entries.sort(key=lambda entry: (entry[1], entry[0]), reverse=True)
    return entries


def compute_period_list(zev, today: date | None = None) -> list[dict]:
    """Full history entries from one dataset: explicit-period rules per entry,
    with current-calendar versus historical provenance. An invoice entry only
    carries the configured interval when its dates align to the current
    calendar; custom ranges stay exact-dated without a false interval."""
    today = today or date.today()
    pairs = list_periods(zev, today)
    if not pairs:
        return []
    interval = zev.billing_interval
    calendar = {
        (start, period_end(start, interval))
        for start in period_starts(
            _history_anchor(zev), interval, today=today
        )
    }
    data = _load_bulk(zev, min(s for s, _e, _src in pairs), max(e for _s, e, _src in pairs))
    result = []
    for start, end, source in pairs:
        payload = _bulk_period_readiness(zev, data, start, end)
        payload["period"] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "interval": interval if (start, end) in calendar else None,
            "source": source,
            "ended": is_ended(end, today),
        }
        result.append(payload)
    return result


# First-run setup block

def first_run_setup(zev, today: date | None = None) -> dict:
    """Setup/completeness state, independent of any billing period.

    ``complete`` is False only for actionable setup omissions: no master data
    at all, or active participants with no current-or-future billable
    assignment (readings-independent, so first-run ZEVs are caught before any
    metering exists). Historical zero-billable periods are not setup gaps —
    they never reach this block. A blank IBAN stays advisory: reported via
    ``billing_settings_complete`` (mirrored in the legacy
    ``settings_complete`` flag) without failing ``complete`` or gating
    generation. The IBAN is the one billing setting that is blank-able on the
    model yet required to issue a payable QR-Rechnung — payment terms default
    to 30 days and VAT registration is enforced by Zev.clean().
    """
    today = today or date.today()
    meter_count = MeteringPoint.objects.filter(zev=zev).count()
    participant_count = Participant.objects.filter(zev=zev).count()
    tariff_count = Tariff.objects.filter(zev=zev).count()
    billing_settings_complete = bool((zev.bank_iban or "").strip())
    billing_link = "/zev-settings/billing" if not billing_settings_complete else None
    if not meter_count or not participant_count:
        return {
            "complete": False,
            "reason": "no_master_data",
            "assignment_link": "/metering/points",
            "billing_settings_complete": billing_settings_complete,
            "billing_settings_link": billing_link,
            "settings_complete": billing_settings_complete,
            "metering_points": meter_count,
            "participants": participant_count,
            "tariffs": tariff_count,
        }
    active_ids = set(
        Participant.objects.filter(zev=zev)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
        .values_list("id", flat=True)
    )
    has_current_assignment = (
        MeteringPointAssignment.objects.filter(
            metering_point__zev=zev, participant_id__in=active_ids
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
        .exists()
        if active_ids
        else True
    )
    complete = has_current_assignment
    return {
        "complete": complete,
        "reason": None if complete else "no_billable_assignment",
        "assignment_link": "/metering/points" if not complete else None,
        "billing_settings_complete": billing_settings_complete,
        "billing_settings_link": billing_link,
        "settings_complete": billing_settings_complete,
        "metering_points": meter_count,
        "participants": participant_count,
        "tariffs": tariff_count,
    }


# Attention items (ZEV-level, cross-period)

def compute_attention(zev, today: date | None = None) -> list[dict]:
    """ZEV-level cross-period operator attention with stable type-prefixed ids.

    Only items the readiness cockpit cannot show live here: unresolved failed
    emails (per-recipient), overdue invoices and participant-validity endings.
    Period-scoped gaps (tariff/metering/assignment coverage) and setup state
    are cockpit-step concerns and must not be duplicated here.
    """
    today = today or date.today()
    items: list[dict] = []

    # 1. Failed email deliveries whose newest attempt failed (any period) —
    #    a later successful delivery or an in-flight retry clears the item.
    #    Invoices whose newest attempt failed are selected in SQL; only one
    #    (newest) log row per failed invoice is loaded via the ranked query,
    #    so retry history never all lands in Python.
    latest_status = Subquery(
        EmailLog.objects.filter(invoice_id=OuterRef("invoice_id"))
        .order_by("-created_at", "-id")
        .values("status")[:1]
    )
    live_logs = EmailLog.objects.filter(invoice__zev=zev).exclude(
        invoice__status__in=[InvoiceStatus.PAID, InvoiceStatus.CANCELLED]
    )
    failed_invoice_ids = list(
        live_logs.annotate(_latest_status=latest_status)
        .filter(_latest_status=EmailLog.Status.FAILED)
        .values_list("invoice_id", flat=True)
        .distinct()
    )
    unresolved: list[EmailLog] = []
    if failed_invoice_ids:
        # One row per failed invoice (its newest attempt), newest by attempt
        # time — the 20-item cap applies after sorting by recency.
        unresolved = list(
            _newest_email_logs_qs(zev)
            .filter(invoice_id__in=failed_invoice_ids)
            .select_related("invoice")
            .order_by("-created_at", "-id")[:20]
        )
    _interval = zev.billing_interval
    for log in unresolved:
        inv = log.invoice
        items.append(
            {
                "type": "email_failed",
                "id": f"email_failed:{inv.id}",
                "invoice_id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "recipient": log.recipient,
                "period": _invoice_period(inv, _interval),
                "link": _invoice_period_link(inv),
                "label": f"{inv.invoice_number} — email to {log.recipient} failed",
            }
        )

    # 2. Overdue sent invoices, most overdue first.
    overdue = Invoice.objects.filter(
        zev=zev,
        status=InvoiceStatus.SENT,
        due_date__lt=today,
    ).order_by("due_date")[:20]
    for inv in overdue:
        items.append(
            {
                "type": "invoice_overdue",
                "id": f"invoice_overdue:{inv.id}",
                "invoice_id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
                "period": _invoice_period(inv, _interval),
                "link": _invoice_period_link(inv),
                "label": f"{inv.invoice_number} overdue since {inv.due_date.isoformat()}",
            }
        )

    # 3. Participant ending (or ended) while still holding assignments,
    #    including finite ones running on past the participant's valid_to.
    #    One Exists annotation answers the assignment question for everyone.
    holds_assignments = Exists(
        MeteringPointAssignment.objects.filter(
            participant_id=OuterRef("id")
        ).filter(Q(valid_to__isnull=True) | Q(valid_to__gt=OuterRef("valid_to")))
    )
    expiring = Participant.objects.filter(
        zev=zev, valid_to__isnull=False
    ).annotate(_holds_assignments=holds_assignments)
    for participant in expiring:
        valid_to = participant.valid_to
        expired = valid_to < today
        if not expired and valid_to > today + timedelta(days=60):
            continue
        if not participant._holds_assignments:
            continue
        items.append(
            {
                "type": "participant_validity",
                "id": f"participant_validity:{participant.id}",
                "participant_id": str(participant.id),
                "participant_name": participant.full_name,
                "valid_to": valid_to.isoformat(),
                "expired": expired,
                "period": None,
                "link": f"/participants?focus={participant.id}&field=valid_to",
                "label": (
                    f"{participant.full_name} ended {valid_to.isoformat()} but still holds meter assignments"
                    if expired
                    else f"{participant.full_name} ends {valid_to.isoformat()} — check meter assignments"
                ),
            }
        )

    return items


def _invoice_period(invoice: Invoice, interval: str | None = None) -> dict | None:
    """The invoice's period; ``interval`` avoids a per-invoice ZEV lookup."""
    if invoice.period_start is None:
        return None
    return {
        "start": invoice.period_start.isoformat(),
        "end": invoice.period_end.isoformat(),
        "interval": interval or invoice.zev.billing_interval,
    }


def _invoice_period_link(invoice: Invoice) -> str:
    """The billing page for the invoice's period (retry/mark-paid live there),
    falling back to the detail route when it has no period dates."""
    if invoice.period_start is None:
        return f"/billing/invoices/{invoice.id}"
    return (
        f"/billing/invoices?period_start={invoice.period_start.isoformat()}"
        f"&period_end={invoice.period_end.isoformat()}"
    )
