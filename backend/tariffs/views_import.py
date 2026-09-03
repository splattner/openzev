"""
Preview and apply endpoints for the VSE/AES tariff import.

Two steps on purpose. A grid operator's document describes every customer
group it serves — the example this was built against carries 23 published
tariffs and yields 35 OpenZEV candidates — of which a given ZEV needs three or
four. Writing tariffs straight from a URL would quietly reprice every invoice
the community issues, so nothing is created until the user has seen each
candidate, its status against what already exists, and what could not be
represented.

The apply step re-fetches and re-parses the document rather than accepting
tariff data from the client: the browser sends back only which candidates were
ticked, plus the digest of the document it was shown, so a document that
changed between the two steps is refused instead of half-applied.
"""
from __future__ import annotations

import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone

from accounts.permissions import IsZevOwnerOrAdmin
from audit.models import AuditActionCategory
from audit.services import record_audit_event
from zev.models import Zev

from .importers.planner import PlannedCandidate, Selection, apply_import, plan_import
from .importers.remote import TariffFetchError, fetch_tariff_document
from .importers.vse_json import ParsedDocument, TariffDocumentError, parse_document
from .serializers import (
    VseTariffImportApplyRequestSerializer,
    VseTariffImportPreviewRequestSerializer,
    VseTariffImportPreviewSerializer,
    VseTariffImportResultSerializer,
)


logger = logging.getLogger(__name__)


def _fetch_failed(exc, zev) -> Response:
    """Turn a fetch/parse failure into a 400 the user can act on.

    The full detail — a resolved address, a socket error, whatever the
    operator's server actually said — is logged here and only here.
    ``str(exc)`` is safe to return by construction: every message these two
    exceptions carry is either a literal or built from what the user typed
    (see ``TariffFetchError``).
    """
    logger.warning(
        "VSE tariff import failed for ZEV %s: %s",
        zev.pk, getattr(exc, "log_detail", exc), exc_info=True,
    )
    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


def _resolve_zev(request, zev_id) -> Zev:
    """The ZEV being imported into, or a 404/403.

    ``IsZevOwnerOrAdmin`` only checks the role, so ownership is checked here —
    otherwise any ZEV owner could write tariffs into any other ZEV.
    """
    zev = Zev.objects.filter(pk=zev_id).first()
    if zev is None:
        raise NotFound("ZEV not found.")
    if not request.user.is_admin and zev.owner_id != request.user.id:
        raise PermissionDenied("You do not own this ZEV.")
    return zev


def _source_url(zev: Zev, requested: str) -> str:
    """The URL to fetch: what the user typed, else the one saved on the ZEV."""
    url = (requested or "").strip() or (zev.tariff_source_url or "").strip()
    if not url:
        raise TariffFetchError(
            "No tariff URL is set for this ZEV. Enter the address at which your grid "
            "operator publishes its machine-readable tariffs."
        )
    return url


def _load(zev: Zev, requested_url: str) -> tuple[str, ParsedDocument, str]:
    url = _source_url(zev, requested_url)
    payload, digest = fetch_tariff_document(url)
    return url, parse_document(payload), digest


def _candidate_payload(planned: PlannedCandidate) -> dict:
    candidate = planned.candidate
    return {
        "key": candidate.key,
        "name": candidate.name,
        "category": candidate.category,
        "billing_mode": candidate.billing_mode,
        "billing_mode_options": list(candidate.billing_mode_options),
        "energy_type": candidate.energy_type,
        "fixed_price_chf": candidate.fixed_price_chf,
        "valid_from": candidate.valid_from,
        "valid_to": candidate.valid_to,
        "notes": candidate.notes,
        "periods": [
            {
                "period_type": period.period_type,
                "price_chf_per_kwh": period.price_chf_per_kwh,
                "time_from": period.time_from,
                "time_to": period.time_to,
                "weekdays": period.weekdays,
                "months": period.months,
            }
            for period in candidate.periods
        ],
        "source_tariff_name": candidate.source_tariff_name,
        "source_tariff_type": candidate.source_tariff_type,
        "source_customer_type": candidate.source_customer_type,
        "source_voltage_level": candidate.source_voltage_level,
        "standard_basegroup": candidate.standard_basegroup,
        "status": planned.status,
        "detail": planned.detail,
        "warnings": candidate.warnings,
        # Only ever pre-tick something that is both the operator's own default
        # product and actually applicable to this ZEV right now.
        "recommended": candidate.recommended and planned.is_applicable,
        "effective_valid_to": planned.effective_valid_to,
    }


class VseTariffImportPreviewView(APIView):
    """Fetch the operator's document and report what importing it would do."""

    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    @extend_schema(
        request=VseTariffImportPreviewRequestSerializer,
        responses=VseTariffImportPreviewSerializer,
    )
    def post(self, request):
        payload = VseTariffImportPreviewRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        zev = _resolve_zev(request, payload.validated_data["zev"])

        try:
            url, document, digest = _load(zev, payload.validated_data.get("url", ""))
        except (TariffFetchError, TariffDocumentError) as exc:
            return _fetch_failed(exc, zev)

        planned = plan_import(zev.id, document)
        return Response(
            VseTariffImportPreviewSerializer({
                "dso_name": document.dso_name,
                "dso_number": document.dso_number,
                "source_url": url,
                "document_digest": digest,
                "candidates": [_candidate_payload(item) for item in planned],
                "errors": document.errors,
            }).data
        )


class VseTariffImportApplyView(APIView):
    """Create the tariffs the user selected in the preview."""

    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    @extend_schema(
        request=VseTariffImportApplyRequestSerializer,
        responses=VseTariffImportResultSerializer,
    )
    def post(self, request):
        payload = VseTariffImportApplyRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        zev = _resolve_zev(request, data["zev"])

        try:
            url, document, digest = _load(zev, data.get("url", ""))
        except (TariffFetchError, TariffDocumentError) as exc:
            return _fetch_failed(exc, zev)

        if digest != data["document_digest"]:
            return Response(
                {"detail": "The operator's document changed since the preview. "
                           "Run the preview again and check what you are importing."},
                status=status.HTTP_409_CONFLICT,
            )

        selections = [
            Selection(key=item["key"], billing_mode=item.get("billing_mode") or None)
            for item in data["selections"]
        ]
        report, created = apply_import(
            zev=zev,
            document=document,
            selections=selections,
            source_url=url,
            imported_on=timezone.localdate(),
        )

        if data.get("remember_url", True) and zev.tariff_source_url != url:
            zev.tariff_source_url = url
            zev.save(update_fields=["tariff_source_url", "updated_at"])

        record_audit_event(
            request=request,
            action_category=AuditActionCategory.IMPORT,
            action_type="tariff.import_vse",
            target_type="zev.Zev",
            target=zev,
            target_id=str(zev.pk),
            target_display=zev.name,
            zev=zev,
            summary=(
                f"Imported {len(report.created)} tariff(s) from the tariff publication "
                f"of {document.dso_name}."
            ),
            metadata={
                "source_url": url,
                "document_digest": digest,
                "dso_name": document.dso_name,
                "dso_number": document.dso_number,
                "selected": len(selections),
                "created": [
                    {"name": tariff.name, "billing_mode": tariff.billing_mode}
                    for tariff in created
                ],
                "skipped": len(report.skipped),
                "errors": len(report.errors),
            },
        )

        return Response(
            VseTariffImportResultSerializer({
                "created": report.created,
                "skipped": report.skipped,
                "errors": report.errors,
            }).data,
            status=status.HTTP_201_CREATED if report.created else status.HTTP_200_OK,
        )
