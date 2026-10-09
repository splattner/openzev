"""Endpoints for supplementary energy data sources (SPEC §5).

Everything answers ``404`` while the feature flag is off. Reads are scoped like the
rest of the ZEV (``ZevScopedQuerySetMixin``): a participant sees only their own
sources, a manager or viewer those of their ZEVs. Writes are decided per action in
``permissions``; the mixin's manager-only write scoping is bypassed on purpose,
because the owner of a source is a participant.
"""

from __future__ import annotations

import csv
import io

from django.core.cache import cache
from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings
from drf_spectacular.utils import extend_schema

from allocation.validity import period_end_exclusive_dt, period_start_dt
from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import build_diff, build_instance_snapshot, record_audit_event
from zev.scoping import ZevScopedQuerySetMixin

from ..models import SupplementaryProvider, SupplementarySource, SupplementaryStatus
from ..tasks import queue_sync, sync_supplementary_source
from . import ingest as ingest_service
from . import reconcile as reconcile_service
from . import sync as sync_service
from .authentication import IsPushSource, SupplementaryPushAuthentication, SupplementaryPushThrottle
from .permissions import SupplementarySourcePermission, require_feature
from .providers import PROVIDERS, ProviderAuthError, ProviderError
from .serializers import (
    CsvUploadSerializer,
    IngestResultSerializer,
    IngestSerializer,
    PurgeSerializer,
    SupplementarySourceSerializer,
)

AUDIT_TARGET = "metering.SupplementarySource"
TRACKED_FIELDS = ["label", "enabled", "external_id"]
CSV_MAX_BYTES = 8 * 1024 * 1024
SYNC_COOLDOWN_S = 5 * 60


class FeatureGatedMixin:
    def initial(self, request, *args, **kwargs):
        require_feature()
        super().initial(request, *args, **kwargs)


def _audit(request, action_type, source, summary, *, metadata=None, changes=None, target_display=None):
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.METERING,
        action_type=f"supplementary_source.{action_type}",
        target_type=AUDIT_TARGET,
        target=source,
        target_id=str(source.pk),
        target_display=target_display or source.metering_point.meter_id,
        summary=summary,
        status=AuditEventStatus.SUCCESS,
        metadata=metadata or {},
        changes=changes,
    )


class SupplementarySourceViewSet(
    FeatureGatedMixin,
    ZevScopedQuerySetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = SupplementarySourceSerializer
    permission_classes = [IsAuthenticated, SupplementarySourcePermission]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    zev_lookup = "metering_point__zev"
    participant_path = "participant"
    # The owner is a participant, so writes are scoped like reads and decided per action
    # in SupplementarySourcePermission instead of by the mixin's manager-only write scope.
    viewer_allowed_actions = frozenset(
        {"create", "partial_update", "destroy", "disconnect", "purge", "test", "sync",
         "rotate_push_token", "import_csv"}
    )
    scope_parent_path = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SupplementarySource.objects.none()
        qs = self.scope_queryset(
            SupplementarySource.objects.select_related("metering_point", "metering_point__zev", "participant")
        )
        metering_point = self.request.query_params.get("metering_point")
        if metering_point:
            try:
                qs = qs.filter(metering_point_id=metering_point)
            except (ValueError, TypeError):
                raise ValidationError({"metering_point": ["Must be a valid UUID."]}) from None
        return qs

    def _refuse_if_zev_disabled(self, source):
        self.assert_target_not_disabled(source)

    # ---- create / update / delete ----

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._refuse_if_target_zev_disabled(serializer.validated_data["metering_point"])
        with transaction.atomic():
            source = serializer.save()
            _audit(
                request, "create", source,
                f"Connected a {source.get_provider_display()} energy data source to {source.metering_point.meter_id}.",
                metadata={
                    "zev_id": str(source.metering_point.zev_id),
                    "provider": source.provider,
                    "participant_id": str(source.participant_id),
                    "created_by_admin": request.user.is_admin and source.participant.user_id != request.user.pk,
                },
            )
        queue_sync(source, backfill=True)
        data = self.get_serializer(source).data
        push_token = getattr(serializer, "push_token", None)
        body = {**data, **({"push_token": push_token} if push_token else {})}
        return Response(body, status=status.HTTP_201_CREATED)

    def _refuse_if_target_zev_disabled(self, metering_point):
        if not self.request.user.is_admin and metering_point.zev.disabled_at is not None:
            raise ValidationError({"detail": "This ZEV is disabled. Ask an admin to re-enable it first."})

    def partial_update(self, request, *args, **kwargs):
        source = self.get_object()
        self._refuse_if_zev_disabled(source)
        serializer = self.get_serializer(source, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        before = build_instance_snapshot(source, TRACKED_FIELDS)
        was_enabled = source.enabled
        with transaction.atomic():
            source = serializer.save()
            changes = build_diff(before, build_instance_snapshot(source, TRACKED_FIELDS), TRACKED_FIELDS)
            _audit(
                request, "update", source, f"Updated energy data source for {source.metering_point.meter_id}.",
                changes=changes, metadata={"credential_changed": bool(getattr(serializer, "credential_changed", False))},
            )
            if source.enabled and (getattr(serializer, "credential_changed", False) or not was_enabled):
                # A fresh key, or a source switched back on: pick up where it left off now, not at the next tick.
                queue_sync(source)
        return Response(self.get_serializer(source).data)

    def update(self, request, *args, **kwargs):
        # PUT is not offered (http_method_names); keep UpdateModelMixin from routing it.
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        source = self.get_object()
        self._refuse_if_zev_disabled(source)
        readings = source.readings.count()
        display = source.metering_point.meter_id
        zev_id = str(source.metering_point.zev_id)
        with transaction.atomic():
            _audit(
                request, "delete", source, f"Deleted the energy data source for {display} and its {readings} reading(s).",
                metadata={"zev_id": zev_id, "readings_deleted": readings, "provider": source.provider},
            )
            source.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ---- actions ----

    @action(detail=True, methods=["post"])
    def disconnect(self, request, pk=None):
        """Stop syncing and drop the credential or token; the readings are kept."""
        source = self.get_object()
        self._refuse_if_zev_disabled(source)
        with transaction.atomic():
            source.disconnect()
            source.save()
            _audit(
                request, "disconnect", source, f"Disconnected the energy data source for {source.metering_point.meter_id}.",
                metadata={"reason": "requested"},
            )
        return Response(self.get_serializer(source).data)

    @action(detail=True, methods=["post"])
    def purge(self, request, pk=None):
        """Delete readings, all of them or a range of civil dates."""
        source = self.get_object()
        self._refuse_if_zev_disabled(source)
        serializer = PurgeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        start, end = serializer.validated_data.get("date_from"), serializer.validated_data.get("date_to")
        readings = source.readings.all()
        if start:
            readings = readings.filter(timestamp__gte=period_start_dt(start))
        if end:
            readings = readings.filter(timestamp__lt=period_end_exclusive_dt(end))
        with transaction.atomic():
            deleted, _ = readings.delete()
            if not source.readings.exists():
                # Nothing is left to be missing from.
                source.covers_from = None
                source.synced_through = None
                source.save(update_fields=["covers_from", "synced_through", "updated_at"])
            _audit(
                request, "purge", source, f"Deleted {deleted} reading(s) of the energy data source for "
                f"{source.metering_point.meter_id}.",
                metadata={"readings_deleted": deleted, "date_from": start, "date_to": end},
            )
        return Response({"deleted": deleted})

    def _pull_provider(self, source):
        provider = PROVIDERS.get(source.provider)
        if source.provider == SupplementaryProvider.PUSH or provider is None:
            raise ValidationError({"detail": "Only sources that pull from a vendor can do this."})
        return provider

    @action(detail=True, methods=["post"])
    def test(self, request, pk=None):
        """Exchange the stored key and read an hour of data. Never echoes a credential or a vendor response."""
        source = self.get_object()
        self._refuse_if_zev_disabled(source)
        provider = self._pull_provider(source)
        if not source.enabled:
            raise ValidationError({"detail": "This source is disconnected."})
        try:
            provider.check(source)
        except ProviderAuthError as exc:
            sync_service.record_failure(source, SupplementaryStatus.RECONNECT_REQUIRED, str(exc))
            raise ValidationError({"detail": str(exc)}) from None
        except ProviderError as exc:
            raise ValidationError({"detail": str(exc)}) from None
        return Response({"ok": True})

    @action(detail=True, methods=["post"])
    def sync(self, request, pk=None):
        """Queue a sync now. At most one request per source every five minutes."""
        source = self.get_object()
        self._refuse_if_zev_disabled(source)
        self._pull_provider(source)
        if not source.enabled:
            raise ValidationError({"detail": "This source is disconnected."})
        if source.status == SupplementaryStatus.RECONNECT_REQUIRED:
            raise ValidationError({"detail": "Enter the API key again before syncing."})
        if not cache.add(f"supplementary-sync-requested:{source.pk}", 1, timeout=SYNC_COOLDOWN_S):
            response = Response({"detail": "A sync was requested a moment ago. Try again in a few minutes."},
                                status=status.HTTP_429_TOO_MANY_REQUESTS)
            response["Retry-After"] = str(SYNC_COOLDOWN_S)
            return response
        sync_supplementary_source.delay(str(source.pk))
        return Response({"queued": True}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"])
    def reconciliation(self, request, pk=None):
        """Day-by-day comparison with the official meter for the newest 14 comparable days."""
        source = self.get_object()
        return Response(reconcile_service.reconcile(source, days=14, include_days=True))

    @action(detail=True, methods=["post"], url_path="rotate-push-token")
    def rotate_push_token(self, request, pk=None):
        """Issue a new push token, returned once. The old one stops working at once."""
        source = self.get_object()
        self._refuse_if_zev_disabled(source)
        if source.provider != "push":
            raise ValidationError({"detail": "Only push sources have a push token."})
        with transaction.atomic():
            token = source.issue_push_token()
            if not source.enabled:
                # Asking for a fresh token is asking to receive again.
                source.enabled = True
            source.save()
            _audit(
                request, "rotate_push_token", source,
                f"Issued a new push token for the energy data source of {source.metering_point.meter_id}.",
            )
        return Response({"push_token": token, "push_token_prefix": source.push_token_prefix})

    @action(detail=True, methods=["post"], url_path="import-csv", parser_classes=[MultiPartParser, FormParser])
    def import_csv(self, request, pk=None):
        """Upload readings as CSV. All-or-nothing; ``?dry_run=true`` validates only."""
        source = self.get_object()
        self._refuse_if_zev_disabled(source)
        if not source.enabled:
            raise PermissionDenied("Source is disabled.")
        upload = CsvUploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        dry_run = request.query_params.get("dry_run", "").lower() in ("1", "true", "yes")
        rows = parse_csv(upload.validated_data["file"])

        result = ingest_service.ingest(source, rows, dry_run=True)
        if result.rejected:
            return Response(
                {"detail": "The file has invalid rows; nothing was imported.", **result.as_dict(), "accepted": 0},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not dry_run:
            result = ingest_service.ingest(source, rows)
            _audit(
                request, "import_csv", source,
                f"Imported {result.accepted} reading(s) from CSV for {source.metering_point.meter_id}.",
                metadata={"accepted": result.accepted, "updated": result.updated,
                          "dropped_outside_assignment": result.dropped_outside_assignment},
            )
        return Response(result.as_dict())


def parse_csv(upload) -> list[dict]:
    """Rows of a ``timestamp,consumption_kwh,production_kwh,import_kwh,export_kwh`` CSV file."""
    if upload.size > CSV_MAX_BYTES:
        raise ValidationError({"file": [f"The file is larger than {CSV_MAX_BYTES // (1024 * 1024)} MB."]})
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError({"file": ["The file must be UTF-8 text."]}) from None
    sample = text[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    required = {"timestamp", *ingest_service.VALUE_FIELDS}
    header = {(name or "").strip().lower() for name in (reader.fieldnames or [])}
    missing = sorted(required - header)
    if missing:
        raise ValidationError({"file": [f"Missing column(s): {', '.join(missing)}."]})
    rows = []
    for row in reader:
        rows.append({(key or "").strip().lower(): value for key, value in row.items()})
        if len(rows) > settings.SUPPLEMENTARY_CSV_MAX_ROWS:
            raise ValidationError({"file": [f"The file has more than {settings.SUPPLEMENTARY_CSV_MAX_ROWS} rows."]})
    if not rows:
        raise ValidationError({"file": ["The file has no rows."]})
    return rows


class SupplementaryIngestView(FeatureGatedMixin, APIView):
    """``POST /api/v1/metering/supplementary/ingest/``: push readings for one source."""

    authentication_classes = [SupplementaryPushAuthentication]
    permission_classes = [IsPushSource]
    throttle_classes = [SupplementaryPushThrottle]
    parser_classes = [JSONParser]

    @extend_schema(request=IngestSerializer, responses={200: IngestResultSerializer})
    def post(self, request):
        serializer = IngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = serializer.validated_data["readings"]
        if len(rows) > settings.SUPPLEMENTARY_INGEST_MAX_ROWS:
            raise ValidationError(
                {"readings": [f"At most {settings.SUPPLEMENTARY_INGEST_MAX_ROWS} readings per request."]}
            )
        source = request.auth
        return Response(ingest_service.ingest(source, rows).as_dict())
