"""
Pure query logic for the invoice period overview.

Extracted from InvoiceViewSet.period_overview so the data-assembly
logic can be tested and reasoned about independently of the DRF
request/response layer.
"""

from datetime import date as date_type

from django.db.models import OuterRef, Subquery

from allocation.validity import active_during, period_window
from zev.models import Participant, MeteringPointAssignment
from metering.models import MeterReading
from .models import EmailLog, Invoice, InvoiceStatus
from .readiness import _spans_cover
from .serializers import InvoiceSerializer


def compute_period_overview(*, zev, period_start: date_type, period_end: date_type, request) -> list[dict]:
    """Return one row per participant for *zev* over the billing period.

    Each row contains:
    - participant identity fields
    - the participant's invoice for the period (or None)
    - metering completeness flags and gap details

    Participants with at least one metering point assignment active during the
    period are included; a participant whose assignment was later removed but
    who still holds an invoice for the period keeps its row, so attention
    links (retry email / mark paid) never land on an empty table.
    """
    period_start_dt, period_end_exclusive_dt = period_window(period_start, period_end)

    participants = list(
        active_during(
            Participant.objects.filter(zev=zev), period_start, period_end
        ).order_by("last_name", "first_name")
    )

    # Newest invoice wins per participant (deterministic across readiness and
    # overview), and the queryset carries the prefetch + annotation the list
    # view uses so full serialization of every row stays at one query each.
    invoice_rows = Invoice.objects.filter(
        zev=zev,
        period_start=period_start,
        period_end=period_end,
    ).select_related("participant", "zev").order_by("-created_at", "-id")
    invoice_rows = invoice_rows.prefetch_related("items", "email_logs").annotate(
        last_email_status=Subquery(
            EmailLog.objects.filter(invoice=OuterRef("pk")).order_by("-created_at", "-id").values("status")[:1]
        )
    )
    invoice_map: dict[int, Invoice] = {}
    for invoice in invoice_rows:
        invoice_map.setdefault(invoice.participant_id, invoice)

    # Generation eligibility for rows without a usable exact-period invoice,
    # from one bounded overlap query (no per-participant lookups): locked
    # (approved/sent/paid) overlap blocks generation exactly as the engine's
    # replaceability rule, while full day-cover by sent/paid subperiods means
    # already billed. Draft/cancelled overlaps stay regenerable.
    overlap_by_pid: dict[int, list[tuple]] = {}
    for pid, ps, pe, status, inv_id, number in (
        Invoice.objects.filter(
            zev=zev, period_start__lte=period_end, period_end__gte=period_start
        )
        .exclude(period_start=period_start, period_end=period_end)
        .order_by("participant_id", "period_start", "period_end", "id")
        .values_list(
            "participant_id", "period_start", "period_end", "status", "id",
            "invoice_number",
        )
    ):
        overlap_by_pid.setdefault(pid, []).append((ps, pe, status, inv_id, number))

    invoice_participant_ids = set(invoice_map)
    participant_ids = {p.id for p in participants}
    if invoice_participant_ids - participant_ids:
        participants += list(
            Participant.objects.filter(
                zev=zev, id__in=invoice_participant_ids - participant_ids
            ).order_by("last_name", "first_name")
        )

    rows = []
    assignments_by_participant: dict = {p.id: [] for p in participants}
    for assignment in active_during(
        MeteringPointAssignment.objects.filter(
            participant_id__in=assignments_by_participant.keys()
        ),
        period_start,
        period_end,
    ).select_related("metering_point"):
        assignments_by_participant[assignment.participant_id].append(assignment)

    all_mp_ids = {
        a.metering_point_id
        for assignments in assignments_by_participant.values()
        for a in assignments
    }
    readings_by_metering_point: dict[int, set] = {}
    for metering_point_id, timestamp in MeterReading.objects.filter(
        metering_point_id__in=all_mp_ids,
        timestamp__gte=period_start_dt,
        timestamp__lt=period_end_exclusive_dt,
    ).values_list("metering_point_id", "timestamp"):
        readings_by_metering_point.setdefault(metering_point_id, set()).add(timestamp.date())

    for participant in participants:
        assignments = assignments_by_participant[participant.id]
        invoice = invoice_map.get(participant.id)

        if not assignments and not invoice:
            continue

        eligibility = None
        if invoice is None or invoice.status == InvoiceStatus.CANCELLED:
            overlaps = overlap_by_pid.get(participant.id, [])
            settled = [
                (ps, pe) for ps, pe, status, _inv_id, _number in overlaps
                if status in (InvoiceStatus.SENT, InvoiceStatus.PAID)
            ]
            if settled and _spans_cover(settled, period_start, period_end):
                covering = next(
                    (inv_id, number)
                    for ps, pe, status, inv_id, number in overlaps
                    if status in (InvoiceStatus.SENT, InvoiceStatus.PAID)
                )
                eligibility = {
                    "state": "covered",
                    "invoice_id": str(covering[0]),
                    "invoice_number": covering[1],
                }
            else:
                locked = next(
                    (
                        (inv_id, number)
                        for ps, pe, status, inv_id, number in overlaps
                        if status
                        not in (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)
                    ),
                    None,
                )
                if locked is None:
                    eligibility = {
                        "state": "eligible",
                        "invoice_id": None,
                        "invoice_number": None,
                    }
                else:
                    eligibility = {
                        "state": "blocked",
                        "invoice_id": str(locked[0]),
                        "invoice_number": locked[1],
                    }

        missing_meter_ids = []
        missing_meter_details = []
        for assignment in assignments:
            mp = assignment.metering_point
            effective_start = max(period_start, assignment.valid_from)
            effective_end = min(
                period_end,
                assignment.valid_to if assignment.valid_to is not None else period_end,
            )

            if effective_start > effective_end:
                continue

            reading_days = readings_by_metering_point.get(mp.id, set())
            expected_days = (effective_end - effective_start).days + 1
            covered_days = sum(1 for d in reading_days if effective_start <= d <= effective_end)
            missing_days = expected_days - covered_days

            if missing_days > 0:
                missing_meter_ids.append(mp.meter_id)
                missing_meter_details.append({"meter_id": mp.meter_id, "missing_days": missing_days})

        total_metering_points = len(assignments)
        metering_points_with_data = total_metering_points - len(missing_meter_ids)
        metering_data_complete = total_metering_points > 0 and metering_points_with_data == total_metering_points

        rows.append(
            {
                "participant_id": str(participant.id),
                "participant_name": participant.full_name,
                "participant_email": participant.email,
                "invoice": InvoiceSerializer(invoice, context={"request": request}).data if invoice else None,
                "generation_eligibility": eligibility,
                "metering_data_complete": metering_data_complete,
                "metering_points_total": total_metering_points,
                "metering_points_with_data": metering_points_with_data,
                "missing_meter_ids": missing_meter_ids,
                "missing_meter_details": missing_meter_details,
            }
        )

    return rows
