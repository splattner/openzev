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
import logging
import zipfile
from datetime import MAXYEAR, MINYEAR, date

from allocation.read_model import community_totals_by_timestamp, eligible_participant_shares
from allocation.validity import active_during, period_window
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserRole
from accounts.permissions import IsZevOwnerOrAdmin
from zev.models import Participant, Zev

from .annual_statement import generate_annual_statement_pdf
from .financial_summary import generate_financial_summary_pdf
from .tariff_overview import generate_tariff_overview_pdf


logger = logging.getLogger(__name__)

# ZIP entry names must stay well under the 255-byte filesystem limit: both
# name fields allow 100 chars, so two maximal names plus the UUID would
# otherwise produce a >260-byte entry that fails to extract.
_ZIP_ENTRY_BYTE_BUDGET = 180


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """Truncate ``value`` to at most ``max_bytes`` UTF-8 bytes, keeping whole characters."""
    return value.encode("utf-8")[:max(0, max_bytes)].decode("utf-8", "ignore")


# Characters Windows forbids in file names; the fixed prefix plus UUID/".pdf"
# suffix already rule out reserved device names and trailing dots/spaces.
_WINDOWS_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def _annual_statement_zip_name(participant, year: int) -> str:
    """One ZIP entry name for a participant's annual statement.

    The pk is always kept in full (it disambiguates duplicate names); only
    the readable ``last_first`` portion is truncated to fit the byte budget.
    Unicode names pass through; Windows-invalid punctuation and control
    characters become underscores.
    """
    prefix = f"annual-statement-{year}-"
    suffix = f"-{participant.pk}.pdf"
    safe_name = f"{participant.last_name}_{participant.first_name}".replace(" ", "_")
    safe_name = "".join(
        "_"
        if character in _WINDOWS_INVALID_FILENAME_CHARS or ord(character) < 32
        else character
        for character in safe_name
    )
    readable_budget = _ZIP_ENTRY_BYTE_BUDGET - len(prefix.encode("utf-8")) - len(suffix.encode("utf-8"))
    safe_name = _truncate_utf8(safe_name, readable_budget)
    return f"{prefix}{safe_name}{suffix}"


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


def _parse_as_of(as_of_raw: str | None) -> tuple[date | None, Response | None]:
    """Return ``(date, None)`` or ``(None, error response)``.

    ``None`` for ``as_of_raw`` is a valid result (the caller then defaults to
    today) — only an unparseable value is an error.
    """
    if not as_of_raw:
        return None, None
    try:
        return date.fromisoformat(as_of_raw), None
    except ValueError:
        return None, Response(
            {"error": "as_of must be YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST
        )


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

        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        participants = list(
            active_during(zev.participants, year_start, year_end)
            .order_by("last_name", "first_name")
        )

        if not participants:
            return Response(
                {"error": "No participants found for this ZEV and year."},
                status=status.HTTP_404_NOT_FOUND,
            )

        buf = io.BytesIO()
        share_windows = [
            (p.id, p.valid_from, p.valid_to, p.allocation_weight)
            for p in participants
        ]
        # Annual-statement ZIPs are the pool's only caller (see ADR 0017).
        from .pdf_pool import render_statements_parallel

        shares_by_date = None
        zev_totals_by_ts = None
        parallel_results = None
        try:
            parallel_results = render_statements_parallel(
                participants, zev, year, share_windows=share_windows,
            )
        except TimeoutError:
            # The time budget — including time queued behind another batch —
            # is exhausted and serial rendering is slower, so a deadline
            # expiry fails fast instead of retrying.
            logger.exception(
                "Annual-statement batch deadline exceeded for ZEV %s and year %s",
                zev.id,
                year,
            )
            return Response(
                {"error": "Could not generate annual statements."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception:
            # Fail fast without a serial retry (see ADR 0017).
            logger.exception(
                "Annual-statement batch failed for ZEV %s and year %s",
                zev.id,
                year,
            )
            return Response(
                {"error": "Could not generate annual statements."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if parallel_results is None:
            try:
                shares_by_date = eligible_participant_shares(
                    zev,
                    year_start,
                    year_end,
                    windows=share_windows,
                )
                year_start_dt, year_end_dt = period_window(year_start, year_end)
                zev_totals_by_ts = community_totals_by_timestamp(
                    zev, year_start_dt, year_end_dt,
                )
            except Exception:
                logger.exception(
                    "Annual-statement shared-data calculation failed for ZEV %s and year %s",
                    zev.id,
                    year,
                )
                return Response(
                    {"error": "Could not generate annual statements."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # One iterator covers both paths; parallel rows arrive in participant
        # input order, so zip() pairs each row with its participant.
        def _statement_documents():
            if parallel_results is not None:
                for participant, (_pid, pdf_bytes, error) in zip(participants, parallel_results, strict=True):
                    if pdf_bytes is None:
                        logger.warning(
                            "Annual statement omitted for participant %s: %s",
                            participant.pk, error,
                        )
                    else:
                        yield participant, pdf_bytes
                return
            for participant in participants:
                try:
                    yield participant, generate_annual_statement_pdf(
                        participant,
                        zev,
                        year,
                        shares_by_date=shares_by_date,
                        zev_totals_by_ts=zev_totals_by_ts,
                    )
                except Exception:
                    logger.exception(
                        "Annual statement omitted for participant %s", participant.pk,
                    )

        generated = set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for participant, pdf_bytes in _statement_documents():
                generated.add(participant.pk)
                zf.writestr(_annual_statement_zip_name(participant, year), pdf_bytes)
            omitted = [p for p in participants if p.pk not in generated]
            if omitted:
                # A partial archive must be distinguishable from a complete one
                # even after the ZIP has left the server. IDs stay first and
                # machine-readable; names let an admin map them without a lookup.
                entries = "\n".join(
                    f"- {p.pk} ({p.last_name}, {p.first_name})"
                    for p in sorted(omitted, key=lambda p: str(p.pk))
                )
                zf.writestr(
                    "omitted.txt",
                    "The following participants were omitted because their annual "
                    f"statement could not be generated:\n{entries}\n",
                )

        if not generated:
            logger.error(
                "Every annual statement failed for ZEV %s and year %s", zev.id, year,
            )
            return Response(
                {"error": "Could not generate annual statements."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

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


class TariffOverviewView(APIView):
    """Every tariff of a ZEV, as of a date, as a printable PDF.

    Owner/admin only — see docs/specs/2026-09-tariff-overview-pdf.md §3. There
    is no self-service branch: unlike an invoice or a financial summary, this
    document is not addressed to one participant, and the Tariffs page it is
    downloaded from is itself owner/admin only.
    """

    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    def get(self, request, *args, **kwargs):
        zev_id = request.query_params.get("zev_id")
        if not zev_id:
            return Response({"error": "zev_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        zev, error = _get_authorised_zev(request, zev_id)
        if error:
            return error

        as_of, error = _parse_as_of(request.query_params.get("as_of"))
        if error:
            return error
        as_of = as_of or timezone.localdate()

        scope = request.query_params.get("scope", "valid")
        if scope not in ("valid", "all"):
            return Response(
                {"error": "scope must be 'valid' or 'all'."}, status=status.HTTP_400_BAD_REQUEST
            )

        return _pdf_response(
            generate_tariff_overview_pdf(zev, as_of, scope),
            f"tariff-overview-{as_of.isoformat()}.pdf",
            disposition="attachment",
        )
