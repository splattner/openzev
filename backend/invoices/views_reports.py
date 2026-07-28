"""Participant-facing PDF reports: annual statements and financial summaries.

The third and last group extracted from ``InvoiceViewSet``. Like the template
and dashboard endpoints before it, none of this is invoice-domain code — the
reports are keyed on a participant, a ZEV and a year, and none of them touch
the viewset's invoice queryset.

The three handlers repeated the same three preambles (parse the year, resolve
and authorise the ZEV, find the caller's own participant record), so those live
here as module functions. What the handlers do *not* share is which parameters
they require and which errors they raise for a missing one, and that is left
spelled out in each handler rather than folded into a parameterised helper.
"""

import io
import zipfile
from datetime import MAXYEAR, MINYEAR

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import IsZevOwnerOrAdmin
from zev.models import Participant, Zev

from .annual_statement import generate_annual_statement_pdf
from .financial_summary import generate_financial_summary_pdf


def _parse_year(year_raw: str | None) -> tuple[int | None, Response | None]:
    """Return ``(year, None)`` or ``(None, error response)``.

    The upper bound is ``MAXYEAR - 1`` because the report builders construct
    ``datetime(year + 1, 1, 1)`` as the exclusive end of the period. Without
    the range check an out-of-range year reaches that call and raises
    ValueError from inside PDF generation, i.e. a 500 on a query parameter.
    """
    if not year_raw:
        return None, Response({"error": "year is required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        year = int(year_raw)
    except ValueError:
        return None, Response({"error": "year must be a number."}, status=status.HTTP_400_BAD_REQUEST)

    if not MINYEAR <= year <= MAXYEAR - 1:
        return None, Response(
            {"error": f"year must be between {MINYEAR} and {MAXYEAR - 1}."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return year, None


def _get_authorised_zev(request, zev_id) -> tuple[Zev | None, Response | None]:
    """Fetch ``zev_id`` and confirm the caller may read it.

    Returns ``(zev, None)`` or ``(None, error response)``. Admins may read any
    ZEV; everyone else only the ones they own.
    """
    try:
        zev = Zev.objects.get(pk=zev_id)
    except (Zev.DoesNotExist, ValidationError):
        # ValidationError is what the UUID primary key raises for a malformed
        # id; to a caller that is indistinguishable from naming one that does
        # not exist, so report it the same way rather than crashing.
        return None, Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)

    if not request.user.is_admin and zev.owner != request.user:
        return None, Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

    return zev, None


def _get_participant_in_zev(participant_id, zev) -> tuple[Participant | None, Response | None]:
    """Fetch ``participant_id`` scoped to ``zev``.

    Scoping to the ZEV is what stops a caller authorised for one ZEV from
    naming a participant of another. A malformed id is reported as not-found
    for the same reason as in :func:`_get_authorised_zev`.
    """
    try:
        return Participant.objects.get(pk=participant_id, zev=zev), None
    except (Participant.DoesNotExist, ValidationError):
        return None, Response({"error": "Participant not found."}, status=status.HTTP_404_NOT_FOUND)


def _is_self_service(request) -> bool:
    """True when the caller is a plain participant fetching their own report."""
    return request.user.role == UserRole.PARTICIPANT and not request.user.is_admin


def _own_participant(request) -> Participant | None:
    return Participant.objects.filter(user=request.user).first()


def _pdf_response(pdf_bytes: bytes, filename: str, *, disposition: str) -> HttpResponse:
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response


class AnnualStatementView(APIView):
    """Annual statement PDF for one participant.

    A participant gets their own; an owner or admin must name both the ZEV and
    the participant.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        year, error = _parse_year(request.query_params.get("year"))
        if error:
            return error

        if _is_self_service(request):
            participant = _own_participant(request)
            if not participant:
                return Response({"error": "Participant not found."}, status=status.HTTP_404_NOT_FOUND)
            zev = participant.zev
        else:
            participant_id = request.query_params.get("participant_id")
            zev_id = request.query_params.get("zev_id")
            if not participant_id or not zev_id:
                return Response(
                    {"error": "participant_id and zev_id are required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            zev, error = _get_authorised_zev(request, zev_id)
            if error:
                return error
            participant, error = _get_participant_in_zev(participant_id, zev)
            if error:
                return error

        return _pdf_response(
            generate_annual_statement_pdf(participant, zev, year),
            f"annual-statement-{year}-{participant.last_name}.pdf",
            disposition="inline",
        )


class AnnualStatementsZipView(APIView):
    """Annual statements for every participant of a ZEV, as one ZIP."""

    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    def get(self, request, *args, **kwargs):
        year_raw = request.query_params.get("year")
        zev_id = request.query_params.get("zev_id")

        if not year_raw or not zev_id:
            return Response(
                {"error": "year and zev_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        year, error = _parse_year(year_raw)
        if error:
            return error

        zev, error = _get_authorised_zev(request, zev_id)
        if error:
            return error

        participants = list(
            zev.participants.filter(valid_from__year__lte=year)
            .exclude(valid_to__year__lt=year)
            .order_by("last_name", "first_name")
        )

        if not participants:
            return Response(
                {"error": "No participants found for this ZEV and year."},
                status=status.HTTP_404_NOT_FOUND,
            )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for participant in participants:
                try:
                    pdf_bytes = generate_annual_statement_pdf(participant, zev, year)
                    safe_name = f"{participant.last_name}_{participant.first_name}".replace(" ", "_")
                    zf.writestr(f"annual-statement-{year}-{safe_name}.pdf", pdf_bytes)
                except Exception:
                    # Best effort: one participant's missing data must not sink
                    # the whole archive.
                    continue

        buf.seek(0)
        response = HttpResponse(buf.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="annual-statements-{year}.zip"'
        return response


class FinancialSummaryView(APIView):
    """Annual financial summary PDF for a producer participant.

    A participant gets their own. An owner or admin must name the ZEV, and may
    name the participant; without one it falls back to their own record in that
    ZEV, then to the ZEV owner's.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        year, error = _parse_year(request.query_params.get("year"))
        if error:
            return error

        if _is_self_service(request):
            participant = _own_participant(request)
            if not participant:
                return Response({"error": "Participant not found."}, status=status.HTTP_404_NOT_FOUND)
            zev = participant.zev
        else:
            zev_id = request.query_params.get("zev_id")
            if not zev_id:
                return Response({"error": "zev_id is required."}, status=status.HTTP_400_BAD_REQUEST)

            zev, error = _get_authorised_zev(request, zev_id)
            if error:
                return error

            participant_id = request.query_params.get("participant_id")
            if participant_id:
                participant, error = _get_participant_in_zev(participant_id, zev)
                if error:
                    return error
            else:
                # Default to the caller's own record in this ZEV, then the owner's.
                participant = Participant.objects.filter(user=request.user, zev=zev).first()
                if not participant and zev.owner:
                    participant = Participant.objects.filter(user=zev.owner, zev=zev).first()
                if not participant:
                    return Response(
                        {"error": "participant_id is required (no default participant found)."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        return _pdf_response(
            generate_financial_summary_pdf(zev, participant, year),
            f"financial-summary-{year}-{participant.last_name}.pdf",
            disposition="attachment",
        )
