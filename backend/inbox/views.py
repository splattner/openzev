"""Participant inbox and manager outbox (SPEC-2026-11-participant-document-inbox §5.1)."""

import uuid

from django.db.models import Q
from django.http import FileResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from config.http import sanitize_filename
from zev.scoping import ZevScopedQuerySetMixin

from .models import DeliveredDocument, DocumentKind
from .serializers import DeliveredDocumentSerializer

_TRUE = {"1", "true", "yes"}


class DocumentViewSet(
    ZevScopedQuerySetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """What was delivered to the caller (a participant), or by the ZEVs they manage (the outbox).

    One access rule instead of per-resource exceptions: the inbox follows the
    participant row, has no end date, and survives a disabled ZEV (ADR 0045).
    """

    serializer_class = DeliveredDocumentSerializer
    permission_classes = [IsAuthenticated]
    zev_lookup = "zev"
    participant_path = "participant"
    participant_access_survives_end = True
    participant_survives_disabled_zev = True
    # A participant never sees a withdrawn document; grants and admins do.
    participant_visible = Q(withdrawn_at__isnull=True)

    def get_queryset(self):
        queryset = DeliveredDocument.objects.select_related(
            "zev", "participant__party", "invoice", "delivered_by"
        )
        return self.filter_documents(self.scope_queryset(queryset))

    def filter_documents(self, queryset):
        """Narrow-only filters; they never widen what ``scope_queryset`` allows."""
        if getattr(self, "action", None) != "list":
            return queryset
        params = self.request.query_params
        kinds = [value for raw in params.getlist("kind") for value in raw.split(",") if value]
        if kinds:
            unknown = [kind for kind in kinds if kind not in DocumentKind.values]
            if unknown:
                raise ValidationError({"kind": [f"Unknown kind(s): {', '.join(unknown)}."]})
            queryset = queryset.filter(kind__in=kinds)
        if participant_id := params.get("participant_id"):
            try:
                participant_uuid = uuid.UUID(str(participant_id))
            except ValueError:
                raise ValidationError({"participant_id": ["Must be a valid UUID."]}) from None
            queryset = queryset.filter(participant_id=participant_uuid)
        if year := params.get("year"):
            if not year.isdigit():
                raise ValidationError({"year": ["Must be a year."]})
            queryset = queryset.filter(
                Q(period_start__year=int(year)) | Q(period_start__isnull=True, delivered_at__year=int(year))
            )
        if params.get("include_superseded", "true").lower() not in _TRUE:
            queryset = queryset.filter(superseded_at__isnull=True)
        if params.get("include_withdrawn", "").lower() not in _TRUE:
            queryset = queryset.filter(withdrawn_at__isnull=True)
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", str, many=True),
            OpenApiParameter("participant_id", str),
            OpenApiParameter("zev_id", str),
            OpenApiParameter("year", int),
            OpenApiParameter("include_superseded", bool),
            OpenApiParameter("include_withdrawn", bool),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"], url_path="file")
    def file(self, request, pk=None):
        document = self.get_object()
        response = FileResponse(
            document.open_file(),
            content_type=document.content_type,
            as_attachment=True,
            filename=sanitize_filename(document.file_name or f"{document.title}.pdf"),
        )
        # A delivered document is personal: never cached, never sniffed into something else.
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response
