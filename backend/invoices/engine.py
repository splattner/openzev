"""
Invoice calculation engine for OpenZEV.

Algorithm:
1. Collect participant IN readings and participant OUT production readings in period.
2. For each timestamp, compute ZEV total consumption and production.
3. Allocate local energy per timestamp (not only per-period) using participant share of that timestamp.
4. Price local/grid energy consumption and producer compensation per timestamp (HT/NT aware).
5. Build invoice totals and line items.
"""
import logging
from datetime import date, datetime, timezone as tz, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, NamedTuple

from django.db import models, transaction
from django.utils import timezone

from billiard.exceptions import SoftTimeLimitExceeded

from accounts.models import VatRate
from allocation.read_model import (
    CONSUMPTION_METER_TYPES,
    PRODUCTION_METER_TYPES,
    community_totals_by_timestamp,
)
from allocation.validity import active_during, period_window
from allocation.split import split_consumption, split_production
from allocation.windows import AssignmentWindows
from zev.models import AllocationMode, Zev, Participant, MeteringPoint, MeteringPointAssignment, VatMode
from tariffs.models import BillingMode, EnergyType, PeriodType, SplitKey, Tariff, TariffCategory
from tariffs.periods import months_of, weekdays_of
from metering.models import MeterReading, ReadingDirection
from .models import Invoice, InvoiceItem, InvoiceStatus

logger = logging.getLogger(__name__)


# ─── Allocation ───────────────────────────────────────────────────────────────
#
# How the community's solar output is divided between its members at a single
# timestamp lives in ``allocation.split`` (ADR 0013); the imports above keep
# existing importers working.


# ─── Gathering ────────────────────────────────────────────────────────────────


class PeriodReadings(NamedTuple):
    """Everything the pricing loops need to read, fetched once per invoice.

    The two ``*_by_ts`` maps are community-wide totals per timestamp; the four
    querysets are the individual participant's own readings and the ZEV's
    community-allocated readings. ``assignment_windows`` is ZEV-wide (not
    participant-scoped) so it can resolve *any* window at a given timestamp —
    the participant's own, another participant's, or a community one — which
    is what lets the pricing loops tell a true gap apart from energy that
    simply belongs to somebody, or something, else (§7.3).

    ``weight_sum_by_date`` is the community's date-granular allocation-weight
    denominator for the invoice period, used to turn a community reading's
    price into this participant's share. There is deliberately no month-
    granular twin here: the fixed-fee denominators are clamped to each
    tariff's own validity, so they are built inside ``_price_fixed_fees``
    from one shared membership fetch rather than precomputed per invoice.
    """

    participant_consumption: models.QuerySet
    participant_production: models.QuerySet
    community_consumption: models.QuerySet
    community_production: models.QuerySet
    zev_consumption_by_ts: dict
    zev_production_by_ts: dict
    weight_sum_by_date: dict
    assignment_windows: AssignmentWindows


def _assigned_metering_points(zev, meter_types, period_start, period_end, participant=None, allocation_mode=None):
    """Metering points of ``meter_types`` assigned during the period.

    An assignment counts if it began on or before the period ended and had not
    already finished before it began. Passing ``participant`` narrows this to
    one member; omitting it covers the whole community. Passing
    ``allocation_mode`` narrows to metering points with at least one matching
    assignment in the period — the per-reading gate still decides whether a
    *specific* reading's window actually matches, since one meter's mode can
    change mid-period (§7.3).

    Bidirectional points appear in both the consumption and production sets,
    which is how a single meter can feed the pool and draw from it.
    """
    filters = {
        "zev": zev,
        "meter_type__in": meter_types,
    }
    if participant is not None:
        filters["assignments__participant"] = participant
    if allocation_mode is not None:
        filters["assignments__allocation_mode"] = allocation_mode
    # Overlap predicate on the assignments relation (not the row itself,
    # so active_during() does not apply).
    filters["assignments__valid_from__lte"] = period_end
    return MeteringPoint.objects.filter(**filters).filter(
        models.Q(assignments__valid_to__isnull=True)
        | models.Q(assignments__valid_to__gte=period_start)
    ).distinct()


def _readings_in_period(metering_points, start_dt, end_dt, direction):
    return MeterReading.objects.filter(
        metering_point__in=metering_points,
        timestamp__gte=start_dt,
        timestamp__lt=end_dt,
        direction=direction,
    )


def _gather_period_readings(participant, period_start, period_end) -> PeriodReadings:
    """Fetch the participant's own readings and the community-wide totals."""
    zev = participant.zev
    start_dt, end_dt = period_window(period_start, period_end)

    def own_points(meter_types):
        return _assigned_metering_points(
            zev, meter_types, period_start, period_end,
            participant=participant,
        )

    def community_points(meter_types):
        return _assigned_metering_points(
            zev, meter_types, period_start, period_end,
            allocation_mode=AllocationMode.COMMUNITY,
        )

    # Physical community pool totals per timestamp — every metering point of
    # the ZEV regardless of assignment (ADR 0013): a never-assigned meter still
    # feeds the community pool, even though its readings are billed to nobody.
    zev_consumption_by_ts, zev_production_by_ts = community_totals_by_timestamp(
        zev, start_dt, end_dt
    )

    return PeriodReadings(
        participant_consumption=_readings_in_period(
            own_points(CONSUMPTION_METER_TYPES), start_dt, end_dt, ReadingDirection.IN),
        participant_production=_readings_in_period(
            own_points(PRODUCTION_METER_TYPES), start_dt, end_dt, ReadingDirection.OUT),
        community_consumption=_readings_in_period(
            community_points(CONSUMPTION_METER_TYPES), start_dt, end_dt, ReadingDirection.IN),
        community_production=_readings_in_period(
            community_points(PRODUCTION_METER_TYPES), start_dt, end_dt, ReadingDirection.OUT),
        zev_consumption_by_ts=zev_consumption_by_ts,
        zev_production_by_ts=zev_production_by_ts,
        weight_sum_by_date=_allocation_weight_sum_by_date(zev, period_start, period_end),
        # ZEV-wide, not participant-scoped: the personal loops must be able to
        # resolve *any* window at a reading's timestamp — another
        # participant's, or a community one — to tell a true gap apart from
        # energy that simply belongs to somebody, or something, else (§7.3).
        assignment_windows=AssignmentWindows.for_zev(zev, period_start, period_end),
    )


def _discard_replaceable_invoices(participant, period_start, period_end) -> None:
    """Clear the way for a regeneration, or refuse to.

    A draft or cancelled invoice overlapping this period is replaced; anything
    further along its lifecycle has been sent to somebody and must not be
    silently rewritten.
    """
    overlapping = Invoice.objects.filter(
        participant=participant,
        period_start__lte=period_end,
        period_end__gte=period_start,
    )
    locked = overlapping.exclude(
        status__in=[InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED]
    ).first()
    if locked:
        raise ValueError(
            f"Invoice {locked.invoice_number} already has status '{locked.status}' and cannot be regenerated."
        )
    overlapping.filter(status__in=[InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED]).delete()


# ─── Pricing state ────────────────────────────────────────────────────────────


class TariffResolver:
    """Answers "which tariffs apply on this day" without rescanning the list.

    The pricing loops ask that question once per reading, so the tariffs are
    bucketed by billing mode and energy type up front and the per-day validity
    filter is memoised. Only the two energy-priced modes are bucketed; fixed
    fees are handled separately and once, not per reading.
    """

    def __init__(self, tariffs: Iterable[Tariff]):
        self._energy: dict[str, list[Tariff]] = {}
        self._percentage: dict[str, list[Tariff]] = {}
        for tariff in tariffs:
            if tariff.billing_mode == BillingMode.ENERGY:
                self._energy.setdefault(tariff.energy_type, []).append(tariff)
            elif tariff.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY and tariff.percentage:
                self._percentage.setdefault(tariff.energy_type, []).append(tariff)
        self._active_cache: dict[tuple[str, str, date], list[Tariff]] = {}

    def _active(self, bucket: str, buckets: dict, energy_type: str, day: date) -> list[Tariff]:
        key = (bucket, energy_type, day)
        if key not in self._active_cache:
            self._active_cache[key] = [
                tariff for tariff in buckets.get(energy_type, []) if _tariff_is_active(tariff, day)
            ]
        return self._active_cache[key]

    def energy(self, energy_type: str, day: date) -> list[Tariff]:
        """Tariffs priced per kWh of ``energy_type`` and valid on ``day``."""
        return self._active("energy", self._energy, energy_type, day)

    def percentage(self, energy_type: str, day: date) -> list[Tariff]:
        """Tariffs charging a percentage of the grid rate, valid on ``day``."""
        return self._active("pct", self._percentage, energy_type, day)


class ItemAccumulator:
    """Collects priced quantities per tariff until the invoice is written.

    One tariff can produce more than one invoice line: a participant with a
    bidirectional meter is charged for what they drew and credited for what
    they sold under the same tariff, which is what ``bucket`` separates.

    Iteration yields entries in the order they were first seen, which the
    caller's stable sort relies on to break ties.
    """

    def __init__(self):
        self._entries: dict[str, dict] = {}

    def add(
        self,
        *,
        tariff: Tariff,
        quantity: Decimal,
        total: Decimal,
        unit: str,
        base_total: Decimal | None = None,
        bucket: str = "default",
    ) -> None:
        if quantity == 0 and total == 0:
            return
        key = f"{tariff.id}:{bucket}"
        entry = self._entries.get(key)
        if entry is None:
            entry = self._entries[key] = {
                "tariff": tariff,
                "quantity": Decimal("0"),
                "total": Decimal("0"),
                "unit": unit,
                "base_total": Decimal("0"),
                "bucket": bucket,
            }
        entry["quantity"] += quantity
        entry["total"] += total
        if base_total is not None:
            entry["base_total"] += base_total

    def __iter__(self):
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


CATEGORY_SORT_ORDER = {
    TariffCategory.ENERGY: 100,
    TariffCategory.GRID_FEES: 200,
    TariffCategory.LEVIES: 300,
}

ENERGY_TYPE_SORT_ORDER = {
    EnergyType.LOCAL: 10,
    EnergyType.GRID: 20,
    EnergyType.FEED_IN: 30,
    None: 40,
}


def _tariff_is_active(tariff: Tariff, day: date) -> bool:
    return tariff.valid_from <= day and (tariff.valid_to is None or tariff.valid_to >= day)


def _get_tariff_price(tariff: Tariff, ts: datetime) -> Decimal | None:
    """Find the applicable price for a given tariff and timestamp."""
    periods = list(tariff.periods.all())
    if not periods:
        return None

    # The month is checked before anything else, the flat case included: a
    # winter-only flat band that short-circuited on period_type would bill its
    # winter price in July. Bands with no months set match every month, which
    # is every band that predates seasonal support.
    in_season = [period for period in periods if ts.month in months_of(period)]

    # Any number of timed bands is fine here: a band is matched by its window,
    # not by its name, so three or five of them resolve exactly as two do.
    # A flat band short-circuits without looking at the window, which is only
    # safe because a flat band may not share its months with a timed one
    # (TariffPeriodSerializer._reject_flat_beside_timed_bands).
    t_time = ts.time()
    weekday = ts.weekday()  # 0 = Monday
    for period in in_season:
        if period.period_type == PeriodType.FLAT:
            return period.price_chf_per_kwh
        if period.time_from and period.time_to:
            if weekday in weekdays_of(period) and period.time_from <= t_time < period.time_to:
                return period.price_chf_per_kwh

    # Nothing matched the hour, so the bands leave part of the day unpriced.
    # The rule is "the day's first band in this season": TariffPeriod.Meta
    # orders by start time with nulls placed explicitly, so this is the same
    # band on every database rather than whatever the backend happened to
    # return first. Preferring an in-season band matters once seasons exist —
    # billing a January night at the summer rate would be the worse guess.
    return (in_season or periods)[0].price_chf_per_kwh


def _active_vat_rate(period_end: date) -> Decimal:
    active_rate = VatRate.active_for_day(period_end)
    return Decimal(active_rate.rate) if active_rate else Decimal("0")


def _resolve_vat_rate(zev: Zev, period_end: date) -> Decimal:
    """The rate charged *on top of* the subtotal — REGISTERED only.

    NOT_REGISTERED bills prices as entered; INCLUSIVE folds VAT into the line
    totals instead of adding a line, so both return 0 here.
    """
    if zev.vat_mode != VatMode.REGISTERED:
        return Decimal("0")
    return _active_vat_rate(period_end)


# Categories a non-registered ZEV pays non-recoverable VAT on: the grid
# operator bills Netznutzung, SDL, the Netzzuschlag, the cantonal/communal
# levies and the metering charge with VAT, and grid energy is bought from a
# supplier with VAT. The ZEV's own local (solar) energy and the feed-in
# credit it pays participants carry no input VAT.
_VAT_BEARING_CATEGORIES = frozenset({
    TariffCategory.GRID_FEES,
    TariffCategory.LEVIES,
    TariffCategory.METERING,
})


def _tariff_bears_input_vat(tariff: Tariff) -> bool:
    """Whether this tariff's cost reaches an unregistered ZEV carrying VAT."""
    if tariff.category in _VAT_BEARING_CATEGORIES:
        return True
    if tariff.category == TariffCategory.ENERGY:
        return tariff.energy_type == EnergyType.GRID
    return False


def _month_start(day: date) -> date:
    return date(day.year, day.month, 1)


def _next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _count_intersecting_months(start: date, end: date) -> int:
    """How many calendar months touch ``start``..``end`` (same walk as
    ``_months_between``, which owns the cursor loop)."""
    return sum(1 for _ in _months_between(start, end))


def _count_billable_months(tariff: Tariff, period_start: date, period_end: date) -> int:
    overlap_start = max(period_start, tariff.valid_from)
    overlap_end = min(period_end, tariff.valid_to or period_end)
    return _count_intersecting_months(overlap_start, overlap_end)


def _last_overlapping_window(windows: list[tuple], month_start: date, month_end: date):
    """The window that owns one metering point's fee for a month.

    ``windows`` is ``(valid_from, valid_to, allocation_mode, participant_id)``
    for a single metering point; ``month_start``/``month_end`` are the part of
    the calendar month actually billed (already clamped to the tariff/period
    overlap).  Returns ``(valid_from, mode, participant_id)`` of the window
    with the latest ``valid_from`` among those overlapping that range, or
    ``None`` if none overlaps it.

    The non-overlap rule (``MeteringPointAssignment._validate_no_overlap``)
    allows at most one window per metering point at any date, so "last to
    start" is unambiguous.  This is the tie-break that keeps the personal
    and community per-metering-point counts disjoint when a mode switch — or
    a holder change — falls inside a month: the last window to start owns
    the whole month, billed on whichever side it names.  §4.6.1 already
    commits to a tie-break of this shape — months are never prorated, so one
    side always gets the full month.
    """
    best: tuple[date, object, object] | None = None
    for valid_from, valid_to, mode, participant_id in windows:
        if valid_from > month_end or (valid_to is not None and valid_to < month_start):
            continue
        if best is None or valid_from > best[0]:
            best = (valid_from, mode, participant_id)
    return best

def _count_billable_metering_points_by_month(participant: Participant, tariff: Tariff, period_start: date, period_end: date) -> int:
    """How many of the participant's own metering points each billed month covers.

    A metering point counts for a month only if the assignment owning that
    month is the participant's own and ``PERSONAL``
    (``_last_overlapping_window``) — the same per-window care as the
    mode-aware gate in ``generate_invoice`` (§7.3/§7.5): a meter personal in
    one month and community the next counts in the first month and is
    excluded from the second.  The ownership rule also keeps this count
    disjoint from the community count (§4.6.4) when a mode switch falls
    inside a month: the month belongs to exactly one side.  A community
    meter's fee is charged separately, split by weight, in
    ``_price_fixed_fees``.

    ``MeteringPoint.is_active`` is deliberately *not* consulted (#408). It is
    a present-state boolean, and reading it here let an operator action taken
    today rewrite what a past period cost: deactivating a meter in December
    silently reduced the fee already invoiced for January.  Every other input
    to this function is resolved against the billed month, and the fact the
    flag was standing in for — "this meter stopped being billable on date X" —
    is what ``MeteringPointAssignment.valid_to`` already records, per month
    and without rewriting history.  Ending billing means closing the
    assignment; the flag is an inventory status for the meter list, and #406
    removed it from the energy pool for the same reason.
    """
    overlap_start = max(period_start, tariff.valid_from)
    overlap_end = min(period_end, tariff.valid_to or period_end)
    if overlap_start > overlap_end:
        return 0

    # Two fetches, however many months are billed: first the participant's
    # own assignments (which metering points are "theirs" at all), then the
    # FULL window history of those metering points.  Ownership needs every
    # window: a later COMMUNITY window held by the same participant must
    # supersede an earlier PERSONAL one, and a window held by somebody else
    # must be visible too, or the two counters would bill the month twice.
    own_mp_ids = set(
        MeteringPointAssignment.objects.filter(
            participant=participant,
        ).values_list("metering_point_id", flat=True)
    )
    if not own_mp_ids:
        return 0
    windows_by_mp: dict = {}
    for mp_id, vf, vt, mode, pid in MeteringPointAssignment.objects.filter(
        metering_point_id__in=own_mp_ids,
    ).values_list("metering_point_id", "valid_from", "valid_to", "allocation_mode", "participant_id"):
        windows_by_mp.setdefault(mp_id, []).append((vf, vt, mode, pid))

    total_metering_points = 0
    for _month, month_start, month_end in _months_between(overlap_start, overlap_end):
        for mp_id in own_mp_ids:
            owner = _last_overlapping_window(windows_by_mp.get(mp_id, []), month_start, month_end)
            if owner is not None and owner[1] == AllocationMode.PERSONAL and owner[2] == participant.id:
                total_metering_points += 1

    return total_metering_points


def _count_community_metering_points_by_month(zev: Zev, tariff: Tariff, period_start: date, period_end: date) -> dict[date, int]:
    """Metering points whose owning window is ``COMMUNITY``, per month.

    Mirrors ``_count_billable_metering_points_by_month`` — including its
    deliberate blindness to ``MeteringPoint.is_active`` (#408) — but is
    ZEV-wide rather than participant-scoped.  All modes are fetched on purpose —
    dropping the ``COMMUNITY`` filter lets the ownership pick see a
    superseding ``PERSONAL`` window: a meter whose mode switches mid-month
    is billed by whichever side owns the month
    (``_last_overlapping_window``), never by both.

    Feeds the per-metering-point community contribution (§7.5): each
    community meter's fee is charged once per month, then divided between
    eligible participants by weight. Keyed by the first day of the month; a
    month with no community meter is absent, not zero.
    """
    overlap_start = max(period_start, tariff.valid_from)
    overlap_end = min(period_end, tariff.valid_to or period_end)
    if overlap_start > overlap_end:
        return {}

    windows_by_mp: dict = {}
    for mp_id, vf, vt, mode, pid in MeteringPointAssignment.objects.filter(
        metering_point__zev=zev,
    ).values_list("metering_point_id", "valid_from", "valid_to", "allocation_mode", "participant_id"):
        windows_by_mp.setdefault(mp_id, []).append((vf, vt, mode, pid))

    counts: dict[date, int] = {}
    for month, month_start, month_end in _months_between(overlap_start, overlap_end):
        count = sum(
            1
            for _mp_id, windows in windows_by_mp.items()
            if (owner := _last_overlapping_window(windows, month_start, month_end)) is not None
            and owner[1] == AllocationMode.COMMUNITY
        )
        if count:
            counts[month] = count

    return counts


def _overlaps(valid_from: date, valid_to: date | None, start: date, end: date) -> bool:
    """Whether a ``valid_from``/``valid_to`` window touches ``start``..``end``."""
    return valid_from <= end and (valid_to is None or valid_to >= start)


def _months_between(overlap_start: date, overlap_end: date):
    """Yield ``(month, billed_from, billed_to)`` across ``overlap_start``..``overlap_end``.

    ``month`` is the first of the month and identifies it; the other two are
    clamped to the part of it actually covered, which is what membership is
    tested against.
    """
    if overlap_start > overlap_end:
        return

    cursor = _month_start(overlap_start)
    last_month = _month_start(overlap_end)
    while cursor <= last_month:
        next_month = _next_month(cursor)
        yield (
            cursor,
            max(cursor, overlap_start),
            min(next_month - timedelta(days=1), overlap_end),
        )
        cursor = next_month


def _billable_months(tariff: Tariff, period_start: date, period_end: date):
    """Yield ``(month, billed_from, billed_to)`` for each month the fee covers.

    Clamped to the overlap of the invoice period and the tariff's own validity,
    so a period opening mid-month — or a tariff version starting mid-month —
    bills only from that day.
    """
    yield from _months_between(
        max(period_start, tariff.valid_from),
        min(period_end, tariff.valid_to or period_end),
    )


def _count_active_participants_by_month(zev: Zev, tariff: Tariff, period_start: date, period_end: date) -> dict[date, int]:
    """How many participants each billed month is shared between.

    Keyed by the first day of the month. A month with nobody active is absent
    rather than zero, so the caller cannot divide by it.

    Counted per month, not once over the period: somebody joining in February
    must not retroactively dilute January's share. This is also what makes the
    fee reconcile against ``generate_invoices_for_zev``, which invoices anyone
    active at *any* point in the period — a member who left in January is
    charged for January alone, and the months after that are divided between
    the members who remain.

    The count comes from the ZEV rather than from whichever invoices happen to
    exist, so generating one participant's invoice on its own yields the same
    share as a full run.
    """
    # Single fetch, then month-by-month in Python — same shape as the
    # per-metering-point count above.
    windows = list(
        Participant.objects.filter(zev=zev).values_list("valid_from", "valid_to")
    )

    counts: dict[date, int] = {}
    for month, billed_from, billed_to in _billable_months(tariff, period_start, period_end):
        # Membership is tested against the billed part of the month, so someone
        # who left before the period opened is not counted into the first
        # month's denominator — they receive no invoice, and counting them
        # would leave the community short.
        active = sum(
            1 for valid_from, valid_to in windows
            if _overlaps(valid_from, valid_to, billed_from, billed_to)
        )
        if active:
            counts[month] = active

    return counts


def _participant_weight_windows(zev: Zev) -> list[tuple[date, date | None, Decimal]]:
    """``(valid_from, valid_to, allocation_weight)`` for every participant of ``zev``.

    Fetched once and resolved in Python by the weight-sum helpers below —
    the same "single fetch, then Python" shape the rest of this module uses.
    Callers pricing several tariffs in one invoice should fetch once and pass
    the result down rather than re-querying per tariff.
    """
    return list(
        Participant.objects.filter(zev=zev).values_list("valid_from", "valid_to", "allocation_weight")
    )


def _allocation_weight_sum_by_month(
    zev: Zev,
    period_start: date,
    period_end: date,
    tariff: Tariff | None = None,
    *,
    windows: list | None = None,
) -> dict[date, Decimal]:
    """Sum of ``Participant.allocation_weight`` active in each billed month.

    The weight-keyed counterpart of ``_count_active_participants_by_month``,
    and it must clamp its months exactly the same way, because
    ``_price_fixed_fees`` pairs this denominator with a numerator loop driven
    by ``_billable_months(tariff, ...)``. Passing ``tariff`` clamps to the
    overlap of the invoice period and that tariff's validity; omitting it
    covers the whole period.

    **Pass the tariff whenever one is in play.** Without it, a tariff clipped
    inside the period — a version starting mid-month, say — would count a
    participant who is a member of the calendar month but not of the part of
    it the tariff actually bills. They would sit in the denominator while
    their own numerator loop skips them, so the community would recover less
    than the full fee (issue #465).

    Counted per month, not once over the period: a joiner in February must not
    dilute January's share. Read from ZEV membership, never from sibling
    invoices, so generating one participant's invoice alone yields the same
    share as a full run. A month with no eligible participant is absent, not
    zero, so a caller cannot divide by it.
    """
    if windows is None:
        windows = _participant_weight_windows(zev)

    months = (
        _billable_months(tariff, period_start, period_end)
        if tariff is not None
        else _months_between(period_start, period_end)
    )

    sums: dict[date, Decimal] = {}
    for month, billed_from, billed_to in months:
        total = sum(
            (weight for valid_from, valid_to, weight in windows
             if _overlaps(valid_from, valid_to, billed_from, billed_to)),
            Decimal("0"),
        )
        if total > 0:
            sums[month] = total

    return sums


def _allocation_weight_sum_by_date(zev: Zev, period_start: date, period_end: date) -> dict[date, Decimal]:
    """Sum of ``Participant.allocation_weight`` active on each calendar date.

    Date-granular, matching ``participant_on``: feeds shared energy, levies
    and credits, so a mid-period joiner's share starts exactly on their join
    date rather than at the start of the month. A date with no eligible
    participant is absent, not zero.
    """
    windows = list(
        Participant.objects.filter(zev=zev).values_list("valid_from", "valid_to", "allocation_weight")
    )

    sums: dict[date, Decimal] = {}
    cursor = period_start
    while cursor <= period_end:
        total = sum(
            (weight for valid_from, valid_to, weight in windows
             if valid_from <= cursor and (valid_to is None or valid_to >= cursor)),
            Decimal("0"),
        )
        if total > 0:
            sums[cursor] = total
        cursor += timedelta(days=1)

    return sums


_ENERGY_BILLING_MODES = {BillingMode.ENERGY, BillingMode.PERCENTAGE_OF_ENERGY}
_SHARED_BILLING_MODES = {BillingMode.SHARED_MONTHLY_FEE, BillingMode.SHARED_YEARLY_FEE}


def _get_item_type(tariff: Tariff) -> str:
    if tariff.billing_mode not in _ENERGY_BILLING_MODES:
        return InvoiceItem.ItemType.CREDIT if (tariff.fixed_price_chf or Decimal("0")) < 0 else InvoiceItem.ItemType.FEE
    if tariff.energy_type == EnergyType.FEED_IN:
        return InvoiceItem.ItemType.FEED_IN
    if tariff.energy_type == EnergyType.GRID:
        return InvoiceItem.ItemType.GRID_ENERGY
    return InvoiceItem.ItemType.LOCAL_ENERGY


# Translations for billing mode description suffixes used in invoice line items.
# Each language maps singular/plural forms for each billing mode.
DESCRIPTION_TRANSLATIONS: dict[str, dict] = {
    "de": {
        "yearly_fee_sg": "monatliche Rate der Jahresgebühr",
        "yearly_fee_pl": "monatliche Raten der Jahresgebühr",
        "mp_yearly_sg": "monatliche Rate pro Messpunkt",
        "mp_yearly_pl": "monatliche Raten pro Messpunkt",
        "mp_monthly_sg": "Messpunkt-Monat",
        "mp_monthly_pl": "Messpunkt-Monate",
        "monthly_sg": "Monat",
        "monthly_pl": "Monate",
        "shared_monthly_sg": "Monat, Gemeinschaftskosten anteilig",
        "shared_monthly_pl": "Monate, Gemeinschaftskosten anteilig",
        "shared_yearly_sg": "monatliche Rate der Jahresgebühr, Gemeinschaftskosten anteilig",
        "shared_yearly_pl": "monatliche Raten der Jahresgebühr, Gemeinschaftskosten anteilig",
        "pct_of": "von CHF",
        "community_marker": "Gemeinschaftsanteil",
    },
    "fr": {
        "yearly_fee_sg": "mensualité de la redevance annuelle",
        "yearly_fee_pl": "mensualités de la redevance annuelle",
        "mp_yearly_sg": "mensualité par point de mesure",
        "mp_yearly_pl": "mensualités par point de mesure",
        "mp_monthly_sg": "mois-point de mesure",
        "mp_monthly_pl": "mois-points de mesure",
        "monthly_sg": "mois",
        "monthly_pl": "mois",
        "shared_monthly_sg": "mois, quote-part des frais communs",
        "shared_monthly_pl": "mois, quote-part des frais communs",
        "shared_yearly_sg": "mensualité de la redevance annuelle, quote-part des frais communs",
        "shared_yearly_pl": "mensualités de la redevance annuelle, quote-part des frais communs",
        "pct_of": "de CHF",
        "community_marker": "Part communautaire",
    },
    "it": {
        "yearly_fee_sg": "rata mensile della tariffa annuale",
        "yearly_fee_pl": "rate mensili della tariffa annuale",
        "mp_yearly_sg": "rata mensile per punto di misurazione",
        "mp_yearly_pl": "rate mensili per punto di misurazione",
        "mp_monthly_sg": "mese-punto di misurazione",
        "mp_monthly_pl": "mesi-punto di misurazione",
        "monthly_sg": "mese",
        "monthly_pl": "mesi",
        "shared_monthly_sg": "mese, quota dei costi comuni",
        "shared_monthly_pl": "mesi, quota dei costi comuni",
        "shared_yearly_sg": "rata mensile della tariffa annuale, quota dei costi comuni",
        "shared_yearly_pl": "rate mensili della tariffa annuale, quota dei costi comuni",
        "pct_of": "di CHF",
        "community_marker": "Quota comunitaria",
    },
    "en": {
        "yearly_fee_sg": "monthly installment of annual fee",
        "yearly_fee_pl": "monthly installments of annual fee",
        "mp_yearly_sg": "monthly installment per metering point",
        "mp_yearly_pl": "monthly installments per metering point",
        "mp_monthly_sg": "metering-point month",
        "mp_monthly_pl": "metering-point months",
        "monthly_sg": "month",
        "monthly_pl": "months",
        "shared_monthly_sg": "month, share of community costs",
        "shared_monthly_pl": "months, share of community costs",
        "shared_yearly_sg": "monthly installment of annual fee, share of community costs",
        "shared_yearly_pl": "monthly installments of annual fee, share of community costs",
        "pct_of": "of CHF",
        "community_marker": "Community share",
    },
}


# Billing mode -> (singular key, plural key) into DESCRIPTION_TRANSLATIONS.
# Module-level so the per-line render below is a lookup, not a rebuilt table.
# Only the per-metering-point variants take the community marker; the shared
# modes already name the community cost and plain fees never carry it.
_TIME_FEE_UNIT_KEYS = {
    BillingMode.YEARLY_FEE: ("yearly_fee_sg", "yearly_fee_pl"),
    BillingMode.PER_METERING_POINT_YEARLY_FEE: ("mp_yearly_sg", "mp_yearly_pl"),
    BillingMode.PER_METERING_POINT_MONTHLY_FEE: ("mp_monthly_sg", "mp_monthly_pl"),
    BillingMode.SHARED_MONTHLY_FEE: ("shared_monthly_sg", "shared_monthly_pl"),
    BillingMode.SHARED_YEARLY_FEE: ("shared_yearly_sg", "shared_yearly_pl"),
    BillingMode.MONTHLY_FEE: ("monthly_sg", "monthly_pl"),
}


def _build_description(
    tariff: Tariff,
    period_start: date,
    period_end: date,
    quantity: Decimal,
    lang: str = "de",
    *,
    base_rate: Decimal | None = None,
    bucket: str = "default",
) -> str:
    t = DESCRIPTION_TRANSLATIONS.get(lang, DESCRIPTION_TRANSLATIONS["de"])
    # Every "shared" bucket ("shared", "shared_producer_credit") is a
    # community-metering-point line (§7.6) — distinct from the pre-existing
    # SHARED_MONTHLY_FEE/SHARED_YEARLY_FEE wording above, which already names
    # itself as a community cost and is never tagged with this marker.
    community = bucket.startswith("shared")
    marker = t["community_marker"]

    if tariff.billing_mode == BillingMode.ENERGY:
        return f"{tariff.name} ({marker})" if community else tariff.name
    if tariff.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY:
        pct = tariff.percentage or Decimal("0")
        # Format: remove trailing zeros (50.00 → 50, 33.50 → 33.5)
        pct_str = f"{pct:f}".rstrip("0").rstrip(".")
        suffix = f", {marker}" if community else ""
        if base_rate is not None:
            base_str = f"{base_rate:f}".rstrip("0").rstrip(".")
            return f"{tariff.name} ({pct_str}% {t['pct_of']} {base_str}/kWh{suffix})"
        return f"{tariff.name} ({pct_str}%{suffix})"

    months = int(quantity)

    sg_key, pl_key = _TIME_FEE_UNIT_KEYS.get(
        tariff.billing_mode, ("monthly_sg", "monthly_pl")
    )
    suffix = t[sg_key] if months == 1 else t[pl_key]
    if community and tariff.billing_mode in (
        BillingMode.PER_METERING_POINT_YEARLY_FEE,
        BillingMode.PER_METERING_POINT_MONTHLY_FEE,
    ):
        suffix = f"{suffix}, {marker}"
    return f"{tariff.name} ({months} {suffix})"


def _build_sort_order(tariff: Tariff) -> int:
    category_rank = CATEGORY_SORT_ORDER.get(tariff.category, 900)
    energy_rank = ENERGY_TYPE_SORT_ORDER.get(tariff.energy_type, 40)
    mode_rank = {
        BillingMode.ENERGY: 0,
        BillingMode.PERCENTAGE_OF_ENERGY: 1,
        BillingMode.MONTHLY_FEE: 2,
        BillingMode.YEARLY_FEE: 3,
        BillingMode.PER_METERING_POINT_MONTHLY_FEE: 4,
        BillingMode.PER_METERING_POINT_YEARLY_FEE: 5,
        BillingMode.SHARED_MONTHLY_FEE: 6,
        BillingMode.SHARED_YEARLY_FEE: 7,
    }.get(tariff.billing_mode, 9)
    return category_rank + energy_rank + mode_rank


def _price_fixed_fees(participant, tariffs, period_start, period_end, accumulator) -> None:
    """Charge the tariffs that bill by time rather than by energy.

    Counted once per invoice, not once per reading: a fee applies to every
    calendar month the period touches, and the per-metering-point variants
    multiply that by how many points the participant held in those months.
    Yearly fees are charged as twelfths.

    The ``SHARED_*`` modes divide one community-wide amount between the
    members active in each month, so their total is built month by month
    rather than as ``quantity * unit_price``. The per-metering-point modes
    bill personal and community metering points separately (§7.5): month
    ownership (``_last_overlapping_window``) makes the two counts disjoint
    even when a mode switch or holder change falls inside a month, and each
    community-owned meter-month contributes a weight-split ``bucket="shared"``
    share — ``split_key`` plays no part here, since a community meter's cost
    always allocates by weight.

    Both weight-split paths share one fetch of the ZEV's participant windows,
    resolved per tariff in Python: the denominator's *months* are
    tariff-specific but the underlying membership rows are not, so querying
    per tariff would be an N+1 over the ZEV's tariff list.
    """
    weight_windows: list | None = None

    def weight_sums_for(tariff: Tariff) -> dict[date, Decimal]:
        nonlocal weight_windows
        if weight_windows is None:
            weight_windows = _participant_weight_windows(participant.zev)
        return _allocation_weight_sum_by_month(
            participant.zev, period_start, period_end, tariff, windows=weight_windows,
        )

    for tariff in tariffs:
        if tariff.billing_mode in _ENERGY_BILLING_MODES:
            continue
        month_count = _count_billable_months(tariff, period_start, period_end)
        if month_count <= 0:
            continue

        per_metering_point = tariff.billing_mode in (
            BillingMode.PER_METERING_POINT_MONTHLY_FEE,
            BillingMode.PER_METERING_POINT_YEARLY_FEE,
        )
        shared = tariff.billing_mode in _SHARED_BILLING_MODES
        yearly = tariff.billing_mode in (
            BillingMode.YEARLY_FEE,
            BillingMode.PER_METERING_POINT_YEARLY_FEE,
            BillingMode.SHARED_YEARLY_FEE,
        )

        unit_price = tariff.fixed_price_chf or Decimal("0")
        if yearly:
            unit_price = unit_price / Decimal("12")

        if per_metering_point:
            # Personal and community metering points are counted, and billed,
            # separately (§7.5): the split_key mechanism above is only for
            # SHARED_* fees, since the cost being divided here belongs to a
            # community *meter*, which always allocates by weight.
            quantity = Decimal(_count_billable_metering_points_by_month(
                participant, tariff, period_start, period_end))
            if quantity > 0:
                accumulator.add(
                    tariff=tariff, quantity=quantity, total=quantity * unit_price, unit="month",
                )

            community_counts = _count_community_metering_points_by_month(
                participant.zev, tariff, period_start, period_end)
            if community_counts:
                weight_sums = weight_sums_for(tariff)
                shared_total = Decimal("0")
                shared_months = 0
                for month, billed_from, billed_to in _billable_months(tariff, period_start, period_end):
                    count = community_counts.get(month)
                    denominator = weight_sums.get(month)
                    if not count or not denominator or not _overlaps(
                        participant.valid_from, participant.valid_to, billed_from, billed_to
                    ):
                        continue
                    shared_total += unit_price * Decimal(count) * participant.allocation_weight / denominator
                    shared_months += 1
                if shared_months > 0 and not _is_zero_chf(shared_total):
                    accumulator.add(
                        tariff=tariff, quantity=Decimal(shared_months), total=shared_total,
                        unit="month", bucket="shared",
                    )
            continue

        quantity = Decimal(month_count)

        if shared:
            # split_key picks the denominator: WEIGHT normalizes by
            # allocation_weight (community-meter allocation always uses
            # weight; this is what lets a SHARED_* fee opt into the same
            # key). EQUAL is today's headcount split — the numerator is 1
            # and the denominator is the same participant count, so it is
            # arithmetically identical to the pre-split_key behaviour.
            # Both branches clamp their months to this tariff's validity, so
            # the two keys agree exactly when every weight is 1.
            if tariff.split_key == SplitKey.WEIGHT:
                shares = weight_sums_for(tariff)
                numerator = participant.allocation_weight
            else:
                shares = _count_active_participants_by_month(
                    participant.zev, tariff, period_start, period_end)
                numerator = Decimal("1")
            total = Decimal("0")
            charged_months = 0
            for month, billed_from, billed_to in _billable_months(tariff, period_start, period_end):
                denominator = shares.get(month)
                # Only the months this participant was actually a member of:
                # the denominator is community-wide, but the numerator is not.
                # Charging every month the fee was live would bill a mid-period
                # joiner for the months before they arrived.
                if not denominator or not _overlaps(
                    participant.valid_from, participant.valid_to, billed_from, billed_to
                ):
                    continue
                total += unit_price * numerator / denominator
                charged_months += 1
            # Skip months without membership, and shares that round to
            # CHF 0.00 — a zero-weight member of a WEIGHT-split fee would
            # otherwise get a "N Monate / CHF 0.00" line, and a shared fee
            # configured at CHF 0.00 (either split key) would print a zero
            # share of nothing (§4.6.3).  Plain, non-shared fees keep their
            # CHF 0.00 line: there the point of the line is to show the fee
            # exists, and they never reach this branch.
            if charged_months == 0 or _is_zero_chf(total):
                continue
            # Quantity is the months this participant is charged for, so
            # the line reads "2 months" and the derived unit price comes
            # out as their average monthly share — the figure they want
            # to see.
            quantity = Decimal(charged_months)
        else:
            total = quantity * unit_price

        accumulator.add(
            tariff=tariff,
            quantity=quantity,
            total=total,
            unit="month",
        )


def _build_item_payloads(
    accumulator, *, gross_rate: Decimal = Decimal("0")
) -> tuple[list, Decimal, Decimal]:
    """Turn accumulated totals into rounded line-item payloads plus the subtotal.

    Each line is rounded to the centime and the subtotal is the sum of those
    rounded lines, so an invoice adds up to what is printed on it rather than
    to a more precise figure rounded once at the end.

    ``gross_rate`` is non-zero only for a ZEV on ``VatMode.INCLUSIVE``: each
    VAT-bearing line (grid energy, grid fees, levies, metering) has its raw
    total multiplied by ``1 + gross_rate`` before rounding, so the derived
    unit price comes out gross too. The third return value is the
    non-recoverable VAT thus folded in, summed over those lines.
    """
    payloads = []
    subtotal = Decimal("0")
    embedded_vat = Decimal("0")
    for entry in accumulator:
        quantity = Decimal(entry["quantity"])
        total = Decimal(entry["total"])
        if quantity == 0 and total == 0:
            continue

        grossed = bool(gross_rate) and total > 0 and _tariff_bears_input_vat(entry["tariff"])
        if grossed:
            total = total * (Decimal("1") + gross_rate)

        quantized_total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        subtotal += quantized_total
        if grossed:
            net = (quantized_total / (Decimal("1") + gross_rate)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            embedded_vat += quantized_total - net
        if quantity != 0:
            unit_price = (total / quantity).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
        else:
            unit_price = Decimal("0")

        raw_base_total = entry.get("base_total", Decimal("0"))
        payloads.append({
            "tariff": entry["tariff"],
            "quantity": quantity.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "unit": str(entry["unit"]),
            "unit_price": unit_price,
            "total": quantized_total,
            "base_rate": (raw_base_total / quantity).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP) if quantity and raw_base_total else None,
            "bucket": entry["bucket"],
        })

    return (
        payloads,
        subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        embedded_vat.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    )


def _utc_date(ts: datetime) -> date:
    """UTC civil date of a reading timestamp.

    Assignment matching, tariff lookup, and completeness all key on this
    (ADR 0007). Importers write UTC-aware timestamps; a naive datetime is
    taken as UTC (bare ``astimezone`` would assume the host timezone).
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=tz.utc)
    return ts.astimezone(tz.utc).date()


def _is_zero_chf(total: Decimal) -> bool:
    """Whether ``total`` renders as CHF 0.00 under §5 rounding."""
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == 0


def _price_energy(acc, tariffs, energy_type, quantity, ts, day, *, sign, bucket="default"):
    """Price one (energy_type, quantity) at a timestamp. sign=-1 for credits."""
    for tariff in tariffs.energy(energy_type, day):
        price = _get_tariff_price(tariff, ts) or Decimal("0")
        acc.add(
            tariff=tariff,
            quantity=quantity,
            total=sign * (quantity * price),
            unit="kWh",
            bucket=bucket,
        )
    pct_tariffs = tariffs.percentage(energy_type, day)
    if not pct_tariffs:
        return
    grid_base = sum(
        (_get_tariff_price(t, ts) or Decimal("0"))
        for t in tariffs.energy(EnergyType.GRID, day)
    )
    for tariff in pct_tariffs:
        effective_price = grid_base * (tariff.percentage / Decimal("100"))
        acc.add(
            tariff=tariff,
            quantity=quantity,
            total=sign * (quantity * effective_price),
            unit="kWh",
            # base_total is a magnitude for the printed base rate, not a credit.
            base_total=quantity * grid_base,
            bucket=bucket,
        )


@transaction.atomic
def generate_invoice(participant: Participant, period_start: date, period_end: date) -> Invoice:
    """
    Generate (or regenerate) an invoice for a participant for the given period.
    Existing DRAFT invoice for the same period will be replaced.
    Raises ValueError if a non-draft, non-cancelled invoice already exists.
    """
    zev = participant.zev

    _discard_replaceable_invoices(participant, period_start, period_end)

    readings = _gather_period_readings(participant, period_start, period_end)
    zev_consumption_by_ts = readings.zev_consumption_by_ts
    zev_production_by_ts = readings.zev_production_by_ts

    # ─── 6. Fetch applicable tariffs ─────────────────────────────────────
    tariffs_list = list(
        Tariff.objects.filter(zev=zev).prefetch_related("periods")
    )
    tariffs = TariffResolver(tariffs_list)
    # ─── 7. Per-reading HT/NT-aware pricing with timestamp allocation ─────
    local_kwh_acc = Decimal("0")
    grid_kwh_acc = Decimal("0")

    skipped_consumption_readings = 0
    skipped_consumption_kwh = Decimal("0")
    # Reading ids already counted as personal gaps: a mixed-mode meter is in
    # both the personal and the community queryset, and its gap readings must
    # be counted exactly once, so the community loops skip them.  The set
    # holds only gap readings — bounded by the assignment gaps in the period,
    # not by the reading volume: even a year-long unassigned stretch at
    # 15-minute resolution is ~35k UUIDs (~4 MB) — which is why the loops can
    # stream everything else with ``.iterator()`` and still deduplicate here.
    personal_gap_reading_ids: set = set()

    items_accumulator = ItemAccumulator()

    for reading in readings.participant_consumption.order_by("timestamp").iterator():
        ts = reading.timestamp
        resolution = readings.assignment_windows.assignment_at(reading.metering_point_id, ts)
        if resolution is None:
            # A true gap: no assignment covers this timestamp. Belongs to
            # nobody in this billing run.
            personal_gap_reading_ids.add(reading.id)
            skipped_consumption_readings += 1
            skipped_consumption_kwh += reading.energy_kwh
            continue
        if resolution.allocation_mode != AllocationMode.PERSONAL or resolution.holder_id != participant.id:
            # Community energy (billed in the community loop below) or
            # somebody else's meter (billed on their own invoice) — neither
            # is a gap, so the skip counters must not count it (§7.3).
            continue
        participant_kwh = reading.energy_kwh
        zev_consumption_at_ts = zev_consumption_by_ts.get(ts, Decimal("0"))
        zev_production_at_ts = zev_production_by_ts.get(ts, Decimal("0"))

        r_local, r_grid = split_consumption(
            participant_kwh, zev_consumption_at_ts, zev_production_at_ts
        )

        local_kwh_acc += r_local
        grid_kwh_acc += r_grid

        day = _utc_date(ts)

        for energy_type, quantity in ((EnergyType.LOCAL, r_local), (EnergyType.GRID, r_grid)):
            if quantity <= 0:
                continue
            _price_energy(items_accumulator, tariffs, energy_type, quantity, ts, day, sign=1)

    exported_kwh_acc = Decimal("0")

    skipped_production_readings = 0
    skipped_production_kwh = Decimal("0")

    for reading in readings.participant_production.order_by("timestamp").iterator():
        ts = reading.timestamp
        resolution = readings.assignment_windows.assignment_at(reading.metering_point_id, ts)
        if resolution is None:
            personal_gap_reading_ids.add(reading.id)
            skipped_production_readings += 1
            skipped_production_kwh += reading.energy_kwh
            continue
        if resolution.allocation_mode != AllocationMode.PERSONAL or resolution.holder_id != participant.id:
            continue
        produced_kwh = reading.energy_kwh

        zev_production_at_ts = zev_production_by_ts.get(ts, Decimal("0"))
        zev_consumption_at_ts = zev_consumption_by_ts.get(ts, Decimal("0"))

        local_sold_kwh, exported_kwh = split_production(
            produced_kwh, zev_production_at_ts, zev_consumption_at_ts
        )

        exported_kwh_acc += exported_kwh

        day = _utc_date(ts)

        if local_sold_kwh > 0:
            _price_energy(
                items_accumulator, tariffs, EnergyType.LOCAL, local_sold_kwh, ts, day,
                sign=-1, bucket="producer_credit",
            )

        if exported_kwh > 0:
            for tariff in tariffs.energy(EnergyType.FEED_IN, day):
                price = _get_tariff_price(tariff, ts) or Decimal("0")
                items_accumulator.add(
                    tariff=tariff,
                    quantity=exported_kwh,
                    total=-(exported_kwh * price),
                    unit="kWh",
                )

    # ─── Community-allocated energy (§7.4) ─────────────────────────────────
    # Price once, allocate second: each community reading is priced with the
    # ordinary tariff resolution and split against the same physical ZEV
    # totals used above (which already include community meters), then the
    # resulting kWh/CHF are divided by this participant's date-granular
    # weight share. Fed into the same open accumulators as the personal
    # loops, so total_local_kwh/total_grid_kwh/total_feed_in_kwh include
    # shared energy.
    skipped_community_consumption_readings = 0
    skipped_community_consumption_kwh = Decimal("0")
    for reading in readings.community_consumption.order_by("timestamp").iterator():
        ts = reading.timestamp
        resolution = readings.assignment_windows.assignment_at(reading.metering_point_id, ts)
        if resolution is None:
            # A true gap: no assignment covers this timestamp — belongs to
            # nobody. Counted here only if the personal loops did not already
            # count it (a mixed-mode meter appears in both querysets).
            if reading.id not in personal_gap_reading_ids:
                skipped_community_consumption_readings += 1
                skipped_community_consumption_kwh += reading.energy_kwh
            continue
        if resolution.allocation_mode != AllocationMode.COMMUNITY:
            continue  # personal window — billed in the personal loop above
        day = _utc_date(ts)
        if not _overlaps(participant.valid_from, participant.valid_to, day, day):
            continue  # a mid-period joiner/leaver pays no share outside their own membership
        weight_sum = readings.weight_sum_by_date.get(day)
        if not weight_sum:
            continue
        share = participant.allocation_weight / weight_sum

        zev_consumption_at_ts = zev_consumption_by_ts.get(ts, Decimal("0"))
        zev_production_at_ts = zev_production_by_ts.get(ts, Decimal("0"))
        r_local, r_grid = split_consumption(
            reading.energy_kwh, zev_consumption_at_ts, zev_production_at_ts
        )
        shared_local = r_local * share
        shared_grid = r_grid * share

        local_kwh_acc += shared_local
        grid_kwh_acc += shared_grid

        for energy_type, quantity in ((EnergyType.LOCAL, shared_local), (EnergyType.GRID, shared_grid)):
            if quantity <= 0:
                continue
            _price_energy(
                items_accumulator, tariffs, energy_type, quantity, ts, day,
                sign=1, bucket="shared",
            )

    skipped_community_production_readings = 0
    skipped_community_production_kwh = Decimal("0")
    for reading in readings.community_production.order_by("timestamp").iterator():
        ts = reading.timestamp
        resolution = readings.assignment_windows.assignment_at(reading.metering_point_id, ts)
        if resolution is None:
            if reading.id not in personal_gap_reading_ids:
                skipped_community_production_readings += 1
                skipped_community_production_kwh += reading.energy_kwh
            continue
        if resolution.allocation_mode != AllocationMode.COMMUNITY:
            continue
        day = _utc_date(ts)
        if not _overlaps(participant.valid_from, participant.valid_to, day, day):
            continue
        weight_sum = readings.weight_sum_by_date.get(day)
        if not weight_sum:
            continue
        share = participant.allocation_weight / weight_sum

        zev_production_at_ts = zev_production_by_ts.get(ts, Decimal("0"))
        zev_consumption_at_ts = zev_consumption_by_ts.get(ts, Decimal("0"))
        local_sold_kwh, exported_kwh = split_production(
            reading.energy_kwh, zev_production_at_ts, zev_consumption_at_ts
        )
        shared_local_sold = local_sold_kwh * share
        shared_exported = exported_kwh * share

        exported_kwh_acc += shared_exported

        if shared_local_sold > 0:
            _price_energy(
                items_accumulator, tariffs, EnergyType.LOCAL, shared_local_sold, ts, day,
                sign=-1, bucket="shared_producer_credit",
            )

        if shared_exported > 0:
            for tariff in tariffs.energy(EnergyType.FEED_IN, day):
                price = _get_tariff_price(tariff, ts) or Decimal("0")
                items_accumulator.add(
                    tariff=tariff,
                    quantity=shared_exported,
                    total=-(shared_exported * price),
                    unit="kWh",
                    bucket="shared",
                )

    _price_fixed_fees(participant, tariffs_list, period_start, period_end, items_accumulator)

    if skipped_consumption_readings or skipped_production_readings or \
       skipped_community_consumption_readings or skipped_community_production_readings:
        logger.warning(
            "Invoice for participant %s (period %s..%s) excluded %d personal consumption "
            "reading(s) / %s kWh, %d personal production reading(s) / %s kWh, "
            "%d community consumption reading(s) / %s kWh and "
            "%d community production reading(s) / %s kWh "
            "that fall in assignment gaps within the period",
            participant.id,
            period_start,
            period_end,
            skipped_consumption_readings,
            skipped_consumption_kwh,
            skipped_production_readings,
            skipped_production_kwh,
            skipped_community_consumption_readings,
            skipped_community_consumption_kwh,
            skipped_community_production_readings,
            skipped_community_production_kwh,
        )

    local_kwh = local_kwh_acc.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    grid_kwh = grid_kwh_acc.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # INCLUSIVE folds non-recoverable VAT into the line totals; the other
    # modes leave prices untouched here (REGISTERED adds a line below).
    gross_rate = _active_vat_rate(period_end) if zev.vat_mode == VatMode.INCLUSIVE else Decimal("0")
    item_payloads, subtotal, embedded_vat_chf = _build_item_payloads(
        items_accumulator, gross_rate=gross_rate
    )

    vat_rate = _resolve_vat_rate(zev, period_end)
    vat_chf = (subtotal * vat_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_chf = subtotal + vat_chf

    # ─── 8. Create invoice ────────────────────────────────────────────────
    invoice_number = zev.next_invoice_number()
    invoice = Invoice.objects.create(
        invoice_number=invoice_number,
        zev=zev,
        participant=participant,
        period_start=period_start,
        period_end=period_end,
        status=InvoiceStatus.DRAFT,
        total_local_kwh=local_kwh,
        total_grid_kwh=grid_kwh,
        total_feed_in_kwh=exported_kwh_acc.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        subtotal_chf=subtotal,
        vat_rate=vat_rate,
        vat_chf=vat_chf,
        embedded_vat_chf=embedded_vat_chf if zev.vat_mode == VatMode.INCLUSIVE else None,
        total_chf=total_chf,
        due_date=timezone.localdate() + timedelta(days=zev.payment_term_days),
    )

    # ─── 9. Create line items ─────────────────────────────────────────────
    items = []
    for payload in sorted(item_payloads, key=lambda entry: (_build_sort_order(entry["tariff"]), entry["tariff"].name.lower())):
        tariff = payload["tariff"]
        lang = participant.zev.invoice_language or "de"
        items.append(InvoiceItem(
            invoice=invoice,
            item_type=_get_item_type(tariff),
            tariff_category=tariff.category,
            description=_build_description(
                tariff, period_start, period_end, payload["quantity"], lang,
                base_rate=payload.get("base_rate"), bucket=payload["bucket"],
            ),
            quantity_kwh=payload["quantity"],
            unit=payload["unit"],
            unit_price_chf=payload["unit_price"],
            total_chf=payload["total"],
            sort_order=_build_sort_order(tariff),
        ))
    InvoiceItem.objects.bulk_create(items)

    logger.info("Generated invoice %s for %s: %s CHF", invoice_number, participant.full_name, total_chf)
    return invoice


class BulkGenerationResult(NamedTuple):
    """Outcome of a ZEV-wide invoice run: the invoices generated plus one
    entry per participant whose invoice failed."""

    invoices: list[Invoice]
    failures: list[dict]


def generate_invoices_for_zev(zev: Zev, period_start: date, period_end: date) -> BulkGenerationResult:
    """Generate invoices for ALL active participants in a ZEV.

    Failures are isolated per participant (see ADR 0011) and returned in
    ``failures`` as ``{"participant_id": ..., "participant_name": ..., "error": ...}``.
    """
    participants = active_during(zev.participants, period_start, period_end)
    invoices = []
    failures = []
    for participant in participants:
        try:
            invoices.append(generate_invoice(participant, period_start, period_end))
        except SoftTimeLimitExceeded:
            # A soft time limit must abort the whole run, not be recorded as one
            # participant's failure; swallowing it would let the loop run into the
            # hard limit and drop the audit event entirely.
            raise
        except Exception as exc:
            logger.exception("Invoice generation failed for participant %s", participant.full_name)
            # next_invoice_number() bumps zev.invoice_counter in memory; the
            # savepoint rollback restores the row but not the instance, and every
            # participant shares the same zev object (p.zev is zev). Re-sync so the
            # next participant reuses the number the failed one gave back instead of
            # skipping it and then colliding on a stale +1.
            try:
                zev.refresh_from_db(fields=["invoice_counter"])
            except Exception:
                # Don't mask the original failure; if we cannot re-sync, subsequent
                # participants will fail early on the (likely unreachable) DB anyway.
                logger.exception(
                    "Could not re-sync invoice counter after failure for participant %s",
                    participant.full_name,
                )
            failures.append({
                "participant_id": str(participant.id),
                "participant_name": participant.full_name,
                "error": str(exc),
            })
    return BulkGenerationResult(invoices, failures)
