"""Readiness and attention endpoints (contract: nav-regroup spec §7)."""

import re
import uuid
from datetime import date as date_type

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsZevOwnerOrAdmin
from zev.models import Zev

from .readiness import (
    HISTORY_FLOOR,
    MAX_SUPPORTED_DATE,
    MIN_SUPPORTED_DATE,
    compute_attention,
    compute_period_list,
    compute_readiness,
    first_run_setup,
    is_ended,
    period_end,
    period_starts,
    resolve_cockpit_period,
    _has_master_data,
)

# Explicit ranges must stay small enough for the per-day readiness checks.
MAX_EXPLICIT_RANGE_DAYS = 366 * 5


def _resolve_zev(request) -> tuple[Zev | None, Response | None]:
    zev_id = request.query_params.get("zev_id")
    if not zev_id:
        return None, Response(
            {"error": "zev_id is a required query parameter."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        zev_id = uuid.UUID(str(zev_id))
    except (ValueError, AttributeError, TypeError):
        return None, Response(
            {"error": "zev_id must be a valid UUID."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        zev = Zev.objects.get(pk=zev_id)
    except Zev.DoesNotExist:
        return None, Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)
    if not request.user.is_admin and zev.owner_id != request.user.id:
        return None, Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)
    return zev, None


def _parse_period(request) -> tuple[date_type | None, date_type | None, Response | None]:
    start_raw = request.query_params.get("period_start")
    end_raw = request.query_params.get("period_end")
    if not start_raw and not end_raw:
        return None, None, None
    if not start_raw or not end_raw:
        return None, None, Response(
            {"error": "period_start and period_end must be given together."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    # Contract: strict YYYY-MM-DD. Python's fromisoformat() also accepts
    # compact forms like 20260801, so the documented format is enforced first.
    iso_day = "^\\d{4}-\\d{2}-\\d{2}$"
    if not (re.match(iso_day, start_raw) and re.match(iso_day, end_raw)):
        return None, None, Response(
            {"error": "period_start/period_end must be YYYY-MM-DD."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        start = date_type.fromisoformat(start_raw)
        end = date_type.fromisoformat(end_raw)
    except ValueError:
        return None, None, Response(
            {"error": "period_start/period_end must be YYYY-MM-DD."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if start > end:
        return None, None, Response(
            {"error": "period_start must be on or before period_end."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if (end - start).days + 1 > MAX_EXPLICIT_RANGE_DAYS:
        return None, None, Response(
            {
                "error": (
                    "period_start/period_end may span at most "
                    f"{MAX_EXPLICIT_RANGE_DAYS} days."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    # Dates must not reach period arithmetic past Python's representable edge.
    if not (MIN_SUPPORTED_DATE <= start <= MAX_SUPPORTED_DATE) or not (
        MIN_SUPPORTED_DATE <= end <= MAX_SUPPORTED_DATE
    ):
        return None, None, Response(
            {
                "error": (
                    f"period dates must be between {MIN_SUPPORTED_DATE.isoformat()} "
                    f"and {MAX_SUPPORTED_DATE.isoformat()}."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return start, end, None


def _no_period_response(zev, today: date_type) -> Response:
    """The parameterless cockpit form when no period needs work.

    Three ``period: null`` states are distinguished so the dashboard picks the
    right message: setup (master data empty, ``setup`` block present),
    awaiting_first_period (nothing has ended yet — still carrying ``setup`` so
    incomplete assignment/IBAN guidance shows before the first period ends),
    caught_up (no open work; the newest ended period is shown — trailing steps
    may remain).
    """
    if not _has_master_data(zev):
        return Response(
            {
                "zev_id": str(zev.id),
                "period": None,
                "steps": [],
                "next_action": "none",
                "setup": first_run_setup(zev),
            }
        )
    anchor = max(zev.start_date, HISTORY_FLOOR)
    ended = [
        start
        for start in period_starts(anchor, zev.billing_interval, today=today)
        if is_ended(period_end(start, zev.billing_interval), today)
    ]
    if not ended:
        return Response(
            {
                "zev_id": str(zev.id),
                "period": None,
                "steps": [],
                "next_action": "none",
                "setup": first_run_setup(zev, today),
                "awaiting_first_period": True,
            }
        )
    start = ended[0]
    end = period_end(start, zev.billing_interval)
    payload = compute_readiness(zev, start, end)
    payload["zev_id"] = str(zev.id)
    setup = first_run_setup(zev, today)
    payload["setup"] = setup
    payload["caught_up"] = bool(setup["complete"])
    return Response(payload)


class ReadinessView(APIView):
    """GET /api/v1/invoices/invoices/readiness/

    Parameterless: the resolved cockpit period, or one of the three
    ``period: null`` forms. With ``period_start`` + ``period_end``: one
    explicit period. With ``periods=all``: the full bounded history, reporting
    ``total_periods`` / ``truncated`` instead of silently capping it.
    """

    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    def get(self, request):
        zev, error = _resolve_zev(request)
        if error:
            return error

        if request.query_params.get("periods") == "all":
            anchor = max(zev.start_date, HISTORY_FLOOR)
            entries = compute_period_list(zev)
            return Response(
                {
                    "zev_id": str(zev.id),
                    "periods": entries,
                    "history_from": anchor.isoformat(),
                    "total_periods": len(entries),
                    # True when the ZEV predates the documented history floor
                    # and its earliest periods are not part of this list.
                    "truncated": zev.start_date < HISTORY_FLOOR,
                }
            )

        start, end, period_error = _parse_period(request)
        if period_error:
            return period_error

        explicit = start is not None
        if not explicit:
            cockpit = resolve_cockpit_period(zev)
            if cockpit is None:
                return _no_period_response(zev, date_type.today())
            start, end = cockpit

        payload = compute_readiness(zev, start, end)
        payload["zev_id"] = str(zev.id)
        if not explicit:
            payload["setup"] = first_run_setup(zev)
        return Response(payload)


class AttentionView(APIView):
    """GET /api/v1/invoices/invoices/attention/ — ZEV-level cross-period items."""

    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    def get(self, request):
        zev, error = _resolve_zev(request)
        if error:
            return error
        return Response({"zev_id": str(zev.id), "items": compute_attention(zev)})
