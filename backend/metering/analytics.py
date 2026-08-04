"""
Pure analytics functions extracted from MeterReadingViewSet.

These functions receive pre-filtered querysets / parameters and return plain
dicts that views can hand straight to Response().  No HTTP or permission logic
lives here, which makes the calculations independently unit-testable.
"""
from collections import defaultdict
from datetime import date as date_type, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Max, Min, Q, Sum

from allocation.errors import OverlappingAssignmentWindowsError
from allocation.read_model import CONSUMPTION_METER_TYPES, community_totals_by_timestamp
from allocation.split import split_consumption, split_production
from allocation.windows import AssignmentWindows
from zev.models import (
    Participant,
    MeteringPoint,
    MeteringPointAssignment,
)
from .models import MeterReading


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _qs_bounds(qs, today: date_type) -> tuple[date_type, date_type]:
    """The date window covered by a readings queryset."""
    bounds = qs.aggregate(first=Min("timestamp"), last=Max("timestamp"))
    start = bounds["first"].date() if bounds["first"] else today
    end = bounds["last"].date() if bounds["last"] else today
    return start, end


def _assignment_windows_for_readings(qs, start: date_type, end: date_type) -> AssignmentWindows:
    """AssignmentWindows for every metering point in ``qs``, overlapping ``start``..``end``.

    Readings are attributed to the participant whose assignment is active at
    the reading's timestamp (ADR 0013); period-level overlap would attribute
    pre-assignment readings to the current holder.
    """
    metering_point_ids = qs.values_list("metering_point_id", flat=True).distinct()
    rows = MeteringPointAssignment.objects.filter(
        metering_point_id__in=metering_point_ids,
        valid_from__lte=end,
    ).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=start)
    ).values_list("metering_point_id", "valid_from", "valid_to", "participant_id")
    return AssignmentWindows(rows)


def _participant_names(participant_ids) -> dict[str, str]:
    """``{participant_id: "First Last"}`` for the given participant ids."""
    names = {}
    for participant in Participant.objects.filter(id__in=participant_ids):
        names[str(participant.id)] = f"{participant.first_name} {participant.last_name}".strip()
    return names


# ---------------------------------------------------------------------------
# Owner / admin dashboard
# ---------------------------------------------------------------------------

def owner_dashboard_summary(qs, trunc_fn, selected_participant_id):
    """
    Compute ZEV-owner/admin dashboard summary.

    qs              – MeterReading queryset already filtered to the desired ZEV
                      and date range.
    trunc_fn        – Django ORM truncation class (TruncDay / TruncHour / …).
    selected_participant_id – optional UUID str to scope totals & timeline.

    Returns a dict matching the existing API response shape.  The caller
    should add the ``"bucket"`` key before returning to the client.
    """
    today = date_type.today()
    base = qs.annotate(bucket=trunc_fn("timestamp"))

    # --- ZEV-wide pivot by timestamp ---
    zev_ts_rows = (
        base.values("bucket", "timestamp", "direction")
        .annotate(total_kwh=Sum("energy_kwh"))
        .order_by("timestamp")
    )
    ts_pivot = {}
    for row in zev_ts_rows:
        ts = row["timestamp"]
        if ts not in ts_pivot:
            ts_pivot[ts] = {
                "bucket": row["bucket"].isoformat(),
                "consumed_kwh": Decimal("0"),
                "produced_kwh": Decimal("0"),
            }
        if row["direction"] == "in":
            ts_pivot[ts]["consumed_kwh"] = row["total_kwh"] or Decimal("0")
        elif row["direction"] == "out":
            ts_pivot[ts]["produced_kwh"] = row["total_kwh"] or Decimal("0")

    # --- Bucket-level aggregation and totals ---
    bucket_pivot = {}
    totals = {
        "produced_kwh": Decimal("0"),
        "consumed_kwh": Decimal("0"),
        "imported_kwh": Decimal("0"),
        "exported_kwh": Decimal("0"),
    }
    for _, data in sorted(ts_pivot.items(), key=lambda item: item[0]):
        bucket_key = data["bucket"]
        consumed = data["consumed_kwh"]
        produced = data["produced_kwh"]
        imported = max(consumed - produced, Decimal("0"))
        exported = max(produced - consumed, Decimal("0"))

        if bucket_key not in bucket_pivot:
            bucket_pivot[bucket_key] = {
                "bucket": bucket_key,
                "consumed_kwh": Decimal("0"),
                "produced_kwh": Decimal("0"),
                "imported_kwh": Decimal("0"),
                "exported_kwh": Decimal("0"),
            }
        bucket_pivot[bucket_key]["consumed_kwh"] += consumed
        bucket_pivot[bucket_key]["produced_kwh"] += produced
        bucket_pivot[bucket_key]["imported_kwh"] += imported
        bucket_pivot[bucket_key]["exported_kwh"] += exported

        totals["produced_kwh"] += produced
        totals["consumed_kwh"] += consumed
        totals["imported_kwh"] += imported
        totals["exported_kwh"] += exported

    timeline = [
        {
            "bucket": item["bucket"],
            "consumed_kwh": float(item["consumed_kwh"]),
            "produced_kwh": float(item["produced_kwh"]),
            "imported_kwh": float(item["imported_kwh"]),
            "exported_kwh": float(item["exported_kwh"]),
        }
        for _, item in sorted(bucket_pivot.items(), key=lambda entry: entry[0])
    ]

    # --- Per-participant breakdown ---
    # Readings are attributed to the participant whose assignment is active at
    # the reading's timestamp (ADR 0013), not to whoever holds it today.
    window_start, window_end = _qs_bounds(qs, today)
    windows = _assignment_windows_for_readings(qs, window_start, window_end)
    names = _participant_names(windows.participant_ids)

    participant_rows = (
        base.filter(direction="in")
        .values(
            "metering_point_id",
            "timestamp",
            "bucket",
        )
        .annotate(consumed_kwh=Sum("energy_kwh"))
        .order_by("metering_point_id", "timestamp")
    )

    participant_production_rows = (
        base.filter(direction="out")
        .values(
            "metering_point_id",
            "timestamp",
            "bucket",
        )
        .annotate(produced_kwh=Sum("energy_kwh"))
        .order_by("metering_point_id", "timestamp")
    )

    participant_map = {}
    for row in participant_rows:
        pid = windows.participant_at(row["metering_point_id"], row["timestamp"])
        if pid is None:
            # Reading fell outside every assignment (gap): it belongs to no one.
            continue
        pid = str(pid)
        ts = row["timestamp"]
        bucket_key = row["bucket"].isoformat()
        consumed = row["consumed_kwh"] or Decimal("0")

        zev_at_ts = ts_pivot.get(ts, {})
        total_consumed = zev_at_ts.get("consumed_kwh", Decimal("0"))
        total_produced = zev_at_ts.get("produced_kwh", Decimal("0"))
        from_zev, from_grid = split_consumption(consumed, total_consumed, total_produced)

        if pid not in participant_map:
            participant_map[pid] = {
                "participant_id": pid,
                "participant_name": names.get(pid, ""),
                "total_consumed_kwh": Decimal("0"),
                "total_produced_kwh": Decimal("0"),
                "from_zev_kwh": Decimal("0"),
                "from_grid_kwh": Decimal("0"),
                "total_exported_kwh": Decimal("0"),
                "timeline_map": {},
            }
        participant_map[pid]["total_consumed_kwh"] += consumed
        participant_map[pid]["from_zev_kwh"] += from_zev
        participant_map[pid]["from_grid_kwh"] += from_grid

        if bucket_key not in participant_map[pid]["timeline_map"]:
            participant_map[pid]["timeline_map"][bucket_key] = {
                "bucket": bucket_key,
                "consumed_kwh": Decimal("0"),
                "produced_kwh": Decimal("0"),
                "imported_kwh": Decimal("0"),
                "exported_kwh": Decimal("0"),
            }
        participant_map[pid]["timeline_map"][bucket_key]["consumed_kwh"] += consumed
        participant_map[pid]["timeline_map"][bucket_key]["imported_kwh"] += from_grid

    for row in participant_production_rows:
        pid = windows.participant_at(row["metering_point_id"], row["timestamp"])
        if pid is None:
            continue
        pid = str(pid)
        bucket_key = row["bucket"].isoformat()
        produced = row["produced_kwh"] or Decimal("0")

        # Exported per timestamp = the producer's share of what the ZEV could
        # not consume locally — mirrors what the engine bills as feed-in
        # (ADR 0013), so the chart reconciles with the invoice.
        ts = row["timestamp"]
        zev_at_ts = ts_pivot.get(ts, {})
        _, exported = split_production(
            produced,
            zev_at_ts.get("produced_kwh", Decimal("0")),
            zev_at_ts.get("consumed_kwh", Decimal("0")),
        )

        if pid not in participant_map:
            participant_map[pid] = {
                "participant_id": pid,
                "participant_name": names.get(pid, ""),
                "total_consumed_kwh": Decimal("0"),
                "total_produced_kwh": Decimal("0"),
                "from_zev_kwh": Decimal("0"),
                "from_grid_kwh": Decimal("0"),
                "total_exported_kwh": Decimal("0"),
                "timeline_map": {},
            }
        participant_map[pid]["total_produced_kwh"] += produced
        participant_map[pid]["total_exported_kwh"] += exported

        if bucket_key not in participant_map[pid]["timeline_map"]:
            participant_map[pid]["timeline_map"][bucket_key] = {
                "bucket": bucket_key,
                "consumed_kwh": Decimal("0"),
                "produced_kwh": Decimal("0"),
                "imported_kwh": Decimal("0"),
                "exported_kwh": Decimal("0"),
            }
        participant_map[pid]["timeline_map"][bucket_key]["produced_kwh"] += produced
        participant_map[pid]["timeline_map"][bucket_key]["exported_kwh"] += exported

    participant_stats = sorted(
        [
            {
                "participant_id": item["participant_id"],
                "participant_name": item["participant_name"],
                "total_consumed_kwh": float(item["total_consumed_kwh"]),
                "total_produced_kwh": float(item["total_produced_kwh"]),
                "from_zev_kwh": float(item["from_zev_kwh"]),
                "from_grid_kwh": float(item["from_grid_kwh"]),
            }
            for item in participant_map.values()
        ],
        key=lambda x: x["total_consumed_kwh"],
        reverse=True,
    )

    response_totals = {k: float(v) for k, v in totals.items()}
    zev_wide_totals = dict(response_totals)
    response_timeline = timeline
    selected_participant_name = None

    if selected_participant_id and selected_participant_id in participant_map:
        selected = participant_map[selected_participant_id]
        selected_participant_name = selected["participant_name"]
        response_totals = {
            "produced_kwh": float(selected["total_produced_kwh"]),
            "consumed_kwh": float(selected["total_consumed_kwh"]),
            "imported_kwh": float(selected["from_grid_kwh"]),
            "exported_kwh": float(selected["total_exported_kwh"]),
        }
        response_timeline = [
            {
                "bucket": item["bucket"],
                "consumed_kwh": float(item["consumed_kwh"]),
                "produced_kwh": float(item["produced_kwh"]),
                "imported_kwh": float(item["imported_kwh"]),
                "exported_kwh": float(item["exported_kwh"]),
            }
            for _, item in sorted(selected["timeline_map"].items(), key=lambda entry: entry[0])
        ]

    return {
        "role": "zev_owner",
        "totals": response_totals,
        "zev_totals": zev_wide_totals,
        "timeline": response_timeline,
        "participant_stats": participant_stats,
        "selected_participant_id": selected_participant_id,
        "selected_participant_name": selected_participant_name,
    }


# ---------------------------------------------------------------------------
# Participant dashboard
# ---------------------------------------------------------------------------

def participant_dashboard_summary(participant_qs, zev_qs, trunc_fn, user, zev_ids):
    """
    Compute participant dashboard summary.

    participant_qs  – MeterReading queryset filtered to the participant's own
                      readings, already date-filtered.
    zev_qs          – MeterReading queryset for all ZEV readings, date-filtered.
    trunc_fn        – Django ORM truncation class.
    user            – request.user (used to find current_participant_ids).
    zev_ids         – queryset / list of ZEV UUIDs the participant belongs to.

    Returns a dict matching the existing API response shape.  The caller
    should add the ``"bucket"`` key before returning to the client.
    """
    today = date_type.today()
    base = participant_qs.annotate(bucket=trunc_fn("timestamp"))

    # Attribution windows for the participant's own metering points.
    window_start, window_end = _qs_bounds(participant_qs, today)
    windows = _assignment_windows_for_readings(participant_qs, window_start, window_end)
    current_participant_ids = set(
        Participant.objects.filter(user=user, zev_id__in=zev_ids)
        .order_by("id")
        .values_list("id", flat=True)
    )

    participant_rows = (
        base.filter(direction="in")
        .values("metering_point_id", "bucket", "timestamp")
        .annotate(consumed_kwh=Sum("energy_kwh"))
        .order_by("timestamp")
    )

    zev_rows = (
        zev_qs.annotate(bucket=trunc_fn("timestamp"))
        .values("bucket", "timestamp", "direction")
        .annotate(total_kwh=Sum("energy_kwh"))
        .order_by("timestamp")
    )

    zev_pivot = {}
    for row in zev_rows:
        key = row["timestamp"]
        if key not in zev_pivot:
            zev_pivot[key] = {"consumed": Decimal("0"), "produced": Decimal("0")}
        if row["direction"] == "in":
            zev_pivot[key]["consumed"] = row["total_kwh"] or Decimal("0")
        elif row["direction"] == "out":
            zev_pivot[key]["produced"] = row["total_kwh"] or Decimal("0")

    timeline_map = {}
    totals = {
        "consumed_from_zev_kwh": Decimal("0"),
        "imported_from_grid_kwh": Decimal("0"),
        "total_consumed_kwh": Decimal("0"),
    }

    for row in participant_rows:
        pid = windows.participant_at(row["metering_point_id"], row["timestamp"])
        if pid is None or pid not in current_participant_ids:
            # Reading predates this participant's assignment (or sits in a gap,
            # or belongs to a different participant after a transfer).
            continue
        bucket_key = row["bucket"].isoformat()
        ts = row["timestamp"]
        participant_consumed = row["consumed_kwh"] or Decimal("0")
        zev_consumed = zev_pivot.get(ts, {}).get("consumed", Decimal("0"))
        zev_produced = zev_pivot.get(ts, {}).get("produced", Decimal("0"))
        consumed_from_zev, imported_from_grid = split_consumption(
            participant_consumed, zev_consumed, zev_produced
        )

        totals["consumed_from_zev_kwh"] += consumed_from_zev
        totals["imported_from_grid_kwh"] += imported_from_grid
        totals["total_consumed_kwh"] += participant_consumed

        if bucket_key not in timeline_map:
            timeline_map[bucket_key] = {
                "bucket": bucket_key,
                "consumed_from_zev_kwh": Decimal("0"),
                "imported_from_grid_kwh": Decimal("0"),
                "total_consumed_kwh": Decimal("0"),
            }
        timeline_map[bucket_key]["consumed_from_zev_kwh"] += consumed_from_zev
        timeline_map[bucket_key]["imported_from_grid_kwh"] += imported_from_grid
        timeline_map[bucket_key]["total_consumed_kwh"] += participant_consumed

    timeline = [
        {
            "bucket": item["bucket"],
            "consumed_from_zev_kwh": float(item["consumed_from_zev_kwh"]),
            "imported_from_grid_kwh": float(item["imported_from_grid_kwh"]),
            "total_consumed_kwh": float(item["total_consumed_kwh"]),
        }
        for _, item in sorted(timeline_map.items(), key=lambda entry: entry[0])
    ]

    # ZEV-wide totals & per-participant stats (Sankey data)
    zev_totals = {
        "produced_kwh": Decimal("0"),
        "consumed_kwh": Decimal("0"),
        "imported_kwh": Decimal("0"),
        "exported_kwh": Decimal("0"),
    }
    for _, data in zev_pivot.items():
        consumed = data["consumed"]
        produced = data["produced"]
        zev_totals["produced_kwh"] += produced
        zev_totals["consumed_kwh"] += consumed
        zev_totals["imported_kwh"] += max(consumed - produced, Decimal("0"))
        zev_totals["exported_kwh"] += max(produced - consumed, Decimal("0"))

    # ZEV-wide per-participant stats (Sankey data), attributed per timestamp.
    zev_window_start, zev_window_end = _qs_bounds(zev_qs, today)
    zev_windows = _assignment_windows_for_readings(zev_qs, zev_window_start, zev_window_end)
    zev_names = _participant_names(zev_windows.participant_ids)

    all_consumption_rows = (
        zev_qs.annotate(bucket=trunc_fn("timestamp"))
        .filter(direction="in")
        .values(
            "metering_point_id",
            "timestamp",
        )
        .annotate(consumed_kwh=Sum("energy_kwh"))
        .order_by("metering_point_id", "timestamp")
    )
    all_production_rows = (
        zev_qs.annotate(bucket=trunc_fn("timestamp"))
        .filter(direction="out")
        .values(
            "metering_point_id",
            "timestamp",
        )
        .annotate(produced_kwh=Sum("energy_kwh"))
        .order_by("metering_point_id", "timestamp")
    )

    all_p_map = {}
    for row in all_consumption_rows:
        pid = zev_windows.participant_at(row["metering_point_id"], row["timestamp"])
        if pid is None:
            continue
        pid = str(pid)
        ts = row["timestamp"]
        consumed = row["consumed_kwh"] or Decimal("0")
        zev_at_ts = zev_pivot.get(ts, {})
        total_consumed = zev_at_ts.get("consumed", Decimal("0"))
        total_produced = zev_at_ts.get("produced", Decimal("0"))
        from_zev, from_grid = split_consumption(consumed, total_consumed, total_produced)
        if pid not in all_p_map:
            all_p_map[pid] = {
                "participant_id": pid,
                "participant_name": zev_names.get(pid, ""),
                "total_consumed_kwh": Decimal("0"),
                "total_produced_kwh": Decimal("0"),
                "from_zev_kwh": Decimal("0"),
                "from_grid_kwh": Decimal("0"),
            }
        all_p_map[pid]["total_consumed_kwh"] += consumed
        all_p_map[pid]["from_zev_kwh"] += from_zev
        all_p_map[pid]["from_grid_kwh"] += from_grid

    for row in all_production_rows:
        pid = zev_windows.participant_at(row["metering_point_id"], row["timestamp"])
        if pid is None:
            continue
        pid = str(pid)
        produced = row["produced_kwh"] or Decimal("0")
        if pid not in all_p_map:
            all_p_map[pid] = {
                "participant_id": pid,
                "participant_name": zev_names.get(pid, ""),
                "total_consumed_kwh": Decimal("0"),
                "total_produced_kwh": Decimal("0"),
                "from_zev_kwh": Decimal("0"),
                "from_grid_kwh": Decimal("0"),
            }
        all_p_map[pid]["total_produced_kwh"] += produced

    zev_participant_stats = sorted(
        [
            {
                "participant_id": item["participant_id"],
                "participant_name": item["participant_name"],
                "total_consumed_kwh": float(item["total_consumed_kwh"]),
                "total_produced_kwh": float(item["total_produced_kwh"]),
                "from_zev_kwh": float(item["from_zev_kwh"]),
                "from_grid_kwh": float(item["from_grid_kwh"]),
            }
            for item in all_p_map.values()
        ],
        key=lambda x: x["total_consumed_kwh"],
        reverse=True,
    )

    return {
        "role": "participant",
        "totals": {k: float(v) for k, v in totals.items()},
        "timeline": timeline,
        "zev_totals": {k: float(v) for k, v in zev_totals.items()},
        "zev_participant_stats": zev_participant_stats,
        "current_participant_id": (
            str(next(iter(current_participant_ids))) if current_participant_ids else None
        ),
    }


# ---------------------------------------------------------------------------
# Hourly profile
# ---------------------------------------------------------------------------

def compute_hourly_profile(selected_zev_id, participant_ids, start_dt, end_dt, ps, pe):
    """
    Compute 24-hour average daily consumption profile for the given participants.

    selected_zev_id  – ZEV UUID string.
    participant_ids  – list of Participant UUIDs to scope consumption.
    start_dt / end_dt – UTC-aware datetimes bounding the query window.
    ps / pe          – date objects (period start / end) for assignment validity
                       checks and day-count averaging.

    Returns ``{"hourly_profile": list}`` or ``{"hourly_profile": None}``.
    """
    consumption_mps = MeteringPoint.objects.filter(
        zev_id=selected_zev_id,
        meter_type__in=CONSUMPTION_METER_TYPES,
        assignments__participant_id__in=participant_ids,
        assignments__valid_from__lte=pe,
    ).filter(
        Q(assignments__valid_to__isnull=True) | Q(assignments__valid_to__gte=ps)
    ).distinct()

    participant_readings_qs = MeterReading.objects.filter(
        metering_point__in=consumption_mps,
        timestamp__gte=start_dt,
        timestamp__lt=end_dt,
        direction="in",
    )
    participant_readings = list(participant_readings_qs.order_by("timestamp"))

    if not participant_readings:
        return {"hourly_profile": None}

    resolutions = {r.resolution for r in participant_readings}
    if resolutions == {"daily"}:
        return {"hourly_profile": None}

    # Per-timestamp attribution: a reading only counts while one of the
    # selected participants held the metering point at its timestamp (ADR 0013).
    participant_ids_set = {str(pid) for pid in participant_ids}
    windows = _assignment_windows_for_readings(
        participant_readings_qs, ps, pe
    )

    # The pool covers every metering point of the ZEV regardless of assignment
    # (ADR 0013), matching the engine and the PDFs. Shared read-model helper:
    # one definition of the physical per-timestamp pool across all consumers.
    zev_cons_by_ts, zev_prod_by_ts = community_totals_by_timestamp(
        selected_zev_id, start_dt, end_dt
    )

    # Decimal arithmetic end to end (the billing contract); floats only at
    # serialization.
    hourly_local = [Decimal("0")] * 24
    hourly_grid = [Decimal("0")] * 24

    for reading in participant_readings:
        ts = reading.timestamp
        holder = windows.participant_at(reading.metering_point_id, ts)
        if holder is None or str(holder) not in participant_ids_set:
            # Reading predates the selected participant's assignment (or falls
            # in a gap): it must not shape their profile.
            continue
        hour = ts.hour
        p_kwh = reading.energy_kwh
        zev_cons = zev_cons_by_ts.get(ts, Decimal("0"))
        zev_prod = zev_prod_by_ts.get(ts, Decimal("0"))
        r_local, r_grid = split_consumption(p_kwh, zev_cons, zev_prod)
        hourly_local[hour] += r_local
        hourly_grid[hour] += r_grid

    total_days = (pe - ps).days + 1
    hourly_local = [v / total_days for v in hourly_local]
    hourly_grid = [v / total_days for v in hourly_grid]

    profile = [
        {
            "hour": h,
            "from_zev_kwh": float(hourly_local[h].quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            "from_grid_kwh": float(hourly_grid[h].quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
        }
        for h in range(24)
    ]
    return {"hourly_profile": profile}


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------

def compute_data_quality_status(metering_points, date_from, date_to, today):
    """
    Detect missing daily readings per metering point, and readings that have
    no assignment holder at their timestamp.

    metering_points – MeteringPoint queryset.
    date_from / date_to – date objects defining the inspection window.
    today           – date object (passed in so callers can control "now").

    A reading whose metering point has no assignment active at the reading's
    UTC civil date is billed to nobody but still inflates the ZEV pool (ADR
    0013); that is always a misconfiguration, so such readings are counted
    per metering point as ``unassigned_readings`` / ``unassigned_days``.
    Holders are resolved once per distinct day (assignment validity is
    date-granular), and the per-meter ``assignment_overlap`` flag marks
    metering points whose windows overlap, so one corrupt meter degrades to
    one bad row instead of failing the whole status page.

    Returns a list of status dicts, one per metering point.
    """
    all_days = set()
    current = date_from
    while current <= date_to:
        all_days.add(current)
        current += timedelta(days=1)

    assignment_rows = MeteringPointAssignment.objects.filter(
        metering_point__in=metering_points,
        valid_from__lte=date_to,
    ).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=date_from)
    ).values_list("metering_point_id", "valid_from", "valid_to", "participant_id")

    windows_by_mp: dict = {}
    for row in assignment_rows:
        windows_by_mp.setdefault(row[0], []).append(row)

    current_holders = {}
    for assignment in MeteringPointAssignment.objects.filter(
        metering_point__in=metering_points,
        valid_from__lte=today,
    ).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=today)
    ).order_by("-valid_from").select_related("participant"):
        current_holders.setdefault(assignment.metering_point_id, assignment.participant.full_name)

    result = []
    for mp in metering_points:
        try:
            windows = AssignmentWindows(windows_by_mp.get(mp.id, ()))
        except OverlappingAssignmentWindowsError:
            windows = None

        readings_ts = MeterReading.objects.filter(
            metering_point=mp,
            timestamp__gte=datetime.combine(date_from, datetime.min.time(), tzinfo=dt_timezone.utc),
            timestamp__lt=datetime.combine(date_to, datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(days=1),
        ).values_list("timestamp", flat=True)

        days_with_data = set()
        readings_per_day = defaultdict(int)
        for ts in readings_ts:
            day = ts.astimezone(dt_timezone.utc).date()
            days_with_data.add(day)
            readings_per_day[day] += 1

        missing_days = sorted(all_days - days_with_data)
        gaps = []
        if missing_days:
            gap_start = gap_end = missing_days[0]
            for day in missing_days[1:]:
                if day == gap_end + timedelta(days=1):
                    gap_end = day
                else:
                    gaps.append({
                        "start_date": gap_start.isoformat(),
                        "end_date": gap_end.isoformat(),
                        "duration_days": (gap_end - gap_start).days + 1,
                    })
                    gap_start = gap_end = day
            gaps.append({
                "start_date": gap_start.isoformat(),
                "end_date": gap_end.isoformat(),
                "duration_days": (gap_end - gap_start).days + 1,
            })

        data_completeness = int(100 * len(days_with_data) / len(all_days)) if all_days else 0
        if data_completeness == 100:
            severity = "green"
        elif data_completeness >= 50:
            severity = "yellow"
        else:
            severity = "red"

        unassigned_days = set()
        unassigned_readings = 0
        if windows is not None:
            for day in days_with_data:
                if windows.participant_on(mp.id, day) is None:
                    unassigned_days.add(day)
                    unassigned_readings += readings_per_day[day]

        result.append({
            "id": str(mp.id),
            "meter_id": mp.meter_id,
            "participant_name": current_holders.get(mp.id, "Unassigned"),
            "severity": severity,
            "data_completeness": data_completeness,
            "days_with_data": len(days_with_data),
            "total_days": len(all_days),
            "gaps": gaps,
            "unassigned_days": len(unassigned_days),
            "unassigned_readings": unassigned_readings,
            "assignment_overlap": windows is None,
        })

    return result
