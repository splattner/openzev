from datetime import date as date_type, datetime, timedelta, timezone as dt_timezone

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDay, TruncHour, TruncMonth
from django.utils.dateparse import parse_date
from rest_framework import mixins, viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from accounts.permissions import IsZevOwnerOrAdmin
from accounts.throttling import ApiKeyRateThrottle, ImportThrottle
from zev.models import Zev, Participant, MeteringPoint
from .models import MeterReading, ImportLog
from zev.scoping import ZevScopedQuerySetMixin
from .serializers import MeterReadingSerializer, ImportLogSerializer
from .importers.csv_importer import ImportFileError, import_csv, preview_csv
from .importers.sdatch_importer import import_sdatch
from .analytics import (
    owner_dashboard_summary,
    participant_dashboard_summary,
    compute_hourly_profile,
    compute_data_quality_status,
)
from audit.models import AuditActionCategory, AuditEventStatus
from audit.services import record_audit_event


class MeterReadingViewSet(ZevScopedQuerySetMixin, viewsets.ModelViewSet):
    serializer_class = MeterReadingSerializer
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]
    zev_owner_filter = "metering_point__zev__owner"
    participant_filter = "metering_point__assignments__participant__user"
    participant_distinct = True
    scope_parent_path = ("metering_point", "zev")

    def get_queryset(self):
        return self.scope_queryset(MeterReading.objects.select_related("metering_point__zev"))

    @action(detail=False, methods=["get"], url_path="chart-data",
            permission_classes=[IsAuthenticated])
    def chart_data(self, request):
        """
        Return aggregated energy readings (kWh) grouped by time bucket.

        Query params:
          metering_point  – UUID of the metering point (required)
          date_from       – YYYY-MM-DD (optional)
          date_to         – YYYY-MM-DD (optional)
          bucket          – day | hour | month  (default: day)
        """
        mp_id = request.query_params.get("metering_point")
        if not mp_id:
            return Response({"error": "metering_point query parameter is required."}, status=400)

        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        bucket = request.query_params.get("bucket", "day")

        trunc_fn = {"day": TruncDay, "hour": TruncHour, "month": TruncMonth}.get(bucket, TruncDay)

        qs = self.get_queryset().filter(metering_point_id=mp_id)
        if date_from:
            # Use explicit UTC bounds so Django doesn't shift the date into Europe/Zurich first.
            qs = qs.filter(timestamp__gte=datetime.combine(date_type.fromisoformat(date_from), datetime.min.time(), tzinfo=dt_timezone.utc))
        if date_to:
            qs = qs.filter(timestamp__lt=datetime.combine(date_type.fromisoformat(date_to), datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(days=1))

        rows = (
            qs.annotate(bucket=trunc_fn("timestamp"))
            .values("bucket", "direction")
            .annotate(total_kwh=Sum("energy_kwh"))
            .order_by("bucket")
        )

        pivot: dict = {}
        for row in rows:
            key = row["bucket"].isoformat()
            if key not in pivot:
                pivot[key] = {"bucket": key, "in_kwh": 0.0, "out_kwh": 0.0}
            direction = row["direction"]
            if direction == "in":
                pivot[key]["in_kwh"] = float(row["total_kwh"])
            elif direction == "out":
                pivot[key]["out_kwh"] = float(row["total_kwh"])

        return Response(sorted(pivot.values(), key=lambda x: x["bucket"]))

    @action(detail=False, methods=["get"], url_path="raw-data", permission_classes=[IsAuthenticated])
    def raw_data(self, request):
        """
        Raw metering readings for one metering point, in one of two modes:

          - summary (default): one aggregated row per UTC day
            ({date, in_kwh, out_kwh, readings_count}), for a compact overview
            table. The individual readings are deliberately omitted so the
            payload stays small even over long periods.
          - detail (``date=YYYY-MM-DD``): the individual readings for that single
            day, fetched lazily when a day row is expanded.

        Days are bucketed in UTC to match how the importer stores timestamps
        (a naive CSV timestamp is stamped as UTC), so day boundaries here line up
        with the times shown in the UI.
        """
        mp_id = request.query_params.get("metering_point")
        if not mp_id:
            return Response({"error": "metering_point query parameter is required."}, status=400)

        qs = self.get_queryset().filter(metering_point_id=mp_id)

        # ── Detail mode: one day's individual readings ─────────────────────────
        detail_date = request.query_params.get("date")
        if detail_date:
            day_start = datetime.combine(
                date_type.fromisoformat(detail_date), datetime.min.time(), tzinfo=dt_timezone.utc
            )
            readings = qs.filter(
                timestamp__gte=day_start, timestamp__lt=day_start + timedelta(days=1)
            ).order_by("timestamp")
            return Response([
                {
                    "timestamp": reading.timestamp.isoformat(),
                    "direction": reading.direction,
                    "energy_kwh": float(reading.energy_kwh),
                    "resolution": reading.resolution,
                    "import_source": reading.import_source,
                }
                for reading in readings
            ])

        # ── Summary mode: one aggregated row per UTC day ───────────────────────
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            # Explicit UTC bounds — timestamp__date__ applies Europe/Zurich and would drop 23:xx UTC readings.
            qs = qs.filter(timestamp__gte=datetime.combine(date_type.fromisoformat(date_from), datetime.min.time(), tzinfo=dt_timezone.utc))
        if date_to:
            qs = qs.filter(timestamp__lt=datetime.combine(date_type.fromisoformat(date_to), datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(days=1))

        rows = (
            qs.annotate(day=TruncDay("timestamp", tzinfo=dt_timezone.utc))
            .values("day", "direction")
            .annotate(total_kwh=Sum("energy_kwh"), reading_count=Count("id"))
            .order_by("day")
        )

        day_map: dict = {}
        for row in rows:
            key = row["day"].date().isoformat()
            day = day_map.setdefault(
                key, {"date": key, "in_kwh": 0.0, "out_kwh": 0.0, "readings_count": 0}
            )
            day["readings_count"] += row["reading_count"]
            if row["direction"] == "in":
                day["in_kwh"] = float(row["total_kwh"])
            elif row["direction"] == "out":
                day["out_kwh"] = float(row["total_kwh"])

        return Response(sorted(day_map.values(), key=lambda row: row["date"]))

    @action(detail=False, methods=["get"], url_path="dashboard-summary", permission_classes=[IsAuthenticated])
    def dashboard_summary(self, request):
        """Role-based metering dashboard summary for ZEV owners and participants."""
        user = request.user
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        bucket = request.query_params.get("bucket", "day")
        zev_id = request.query_params.get("zev_id")
        selected_participant_id = request.query_params.get("participant_id")
        trunc_fn = {"day": TruncDay, "hour": TruncHour, "month": TruncMonth}.get(bucket, TruncDay)

        qs = self.get_queryset()
        if date_from:
            qs = qs.filter(timestamp__gte=datetime.combine(date_type.fromisoformat(date_from), datetime.min.time(), tzinfo=dt_timezone.utc))
        if date_to:
            qs = qs.filter(timestamp__lt=datetime.combine(date_type.fromisoformat(date_to), datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(days=1))

        if user.is_admin or user.role == "zev_owner":
            selected_zev_id = None
            if zev_id:
                if not user.is_admin and not Zev.objects.filter(id=zev_id, owner=user).exists():
                    return Response({"error": "Permission denied for selected ZEV."}, status=403)
                qs = qs.filter(metering_point__zev_id=zev_id)
                selected_zev_id = zev_id
            else:
                owner_zevs = Zev.objects.all() if user.is_admin else Zev.objects.filter(owner=user)
                if owner_zevs.count() == 1:
                    selected_zev = owner_zevs.first()
                    qs = qs.filter(metering_point__zev=selected_zev)
                    selected_zev_id = str(selected_zev.id)
                else:
                    return Response({"error": "zev_id query parameter is required."}, status=400)

            if selected_participant_id and selected_zev_id and not Participant.objects.filter(
                id=selected_participant_id,
                zev_id=selected_zev_id,
            ).exists():
                return Response({"error": "Participant not found for selected ZEV."}, status=404)

            result = owner_dashboard_summary(qs, trunc_fn, selected_participant_id)
            result["bucket"] = bucket
            return Response(result)

        # participant path
        # Derived from the participant's own membership, not from qs: a
        # participant whose only stake in a ZEV is a community-allocated
        # share (no personally held metering point) has an empty qs, which
        # would otherwise make the whole ZEV invisible to them here — the
        # zev-wide section below is unscoped by literal holdership on
        # purpose (shared metering points, #387).
        zev_ids = Participant.objects.filter(user=user).values_list("zev_id", flat=True).distinct()
        zev_qs = MeterReading.objects.filter(metering_point__zev_id__in=zev_ids)
        if date_from:
            zev_qs = zev_qs.filter(timestamp__gte=datetime.combine(date_type.fromisoformat(date_from), datetime.min.time(), tzinfo=dt_timezone.utc))
        if date_to:
            zev_qs = zev_qs.filter(timestamp__lt=datetime.combine(date_type.fromisoformat(date_to), datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(days=1))

        result = participant_dashboard_summary(qs, zev_qs, trunc_fn, user, zev_ids)
        result["bucket"] = bucket
        return Response(result)

    @action(detail=False, methods=["get"], url_path="hourly-profile", permission_classes=[IsAuthenticated])
    def hourly_profile(self, request):
        """
        Return a 24-hour average daily consumption profile for a participant,
        split into local ZEV energy and grid import.

        Query params:
          date_from      – YYYY-MM-DD (required)
          date_to        – YYYY-MM-DD (required)
          zev_id         – UUID (optional, required for admin/owner)
          participant_id – UUID (optional, for admin/owner to view a specific participant)
        """
        user = request.user
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if not date_from or not date_to:
            return Response({"error": "date_from and date_to are required."}, status=400)

        ps = date_type.fromisoformat(date_from)
        pe = date_type.fromisoformat(date_to)
        start_dt = datetime.combine(ps, datetime.min.time(), tzinfo=dt_timezone.utc)
        end_dt = datetime.combine(pe, datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(days=1)

        zev_id = request.query_params.get("zev_id")
        participant_id = request.query_params.get("participant_id")

        if user.role == "participant":
            zev_ids = list(
                Participant.objects.filter(user=user).values_list("zev_id", flat=True).distinct()
            )
            if not zev_ids:
                return Response({"hourly_profile": None})
            participant_ids = list(
                Participant.objects.filter(user=user, zev_id__in=zev_ids).values_list("id", flat=True)
            )
            selected_zev_id = zev_ids[0]
        elif user.is_admin or user.role == "zev_owner":
            if not zev_id:
                owner_zevs = Zev.objects.all() if user.is_admin else Zev.objects.filter(owner=user)
                if owner_zevs.count() == 1:
                    selected_zev_id = str(owner_zevs.first().id)
                else:
                    return Response({"error": "zev_id query parameter is required."}, status=400)
            else:
                if not user.is_admin and not Zev.objects.filter(id=zev_id, owner=user).exists():
                    return Response({"error": "Permission denied for selected ZEV."}, status=403)
                selected_zev_id = zev_id

            if participant_id:
                if not Participant.objects.filter(id=participant_id, zev_id=selected_zev_id).exists():
                    return Response({"error": "Participant not found for selected ZEV."}, status=404)
                participant_ids = [participant_id]
            else:
                return Response({"hourly_profile": None})
        else:
            return Response({"hourly_profile": None})

        return Response(compute_hourly_profile(selected_zev_id, participant_ids, start_dt, end_dt, ps, pe))

    @action(detail=False, methods=["get"], url_path="data-quality-status", permission_classes=[IsAuthenticated])
    def data_quality_status(self, request):
        """
        Detect missing daily readings per metering point over a date range.

        Query params:
          date_from  – YYYY-MM-DD (default: 30 days ago)
          date_to    – YYYY-MM-DD (default: today)
          zev_id     – UUID (optional, for filtering)

        Returns array of metering points with gaps and data completeness.
        """
        date_from_str = request.query_params.get("date_from")
        date_to_str = request.query_params.get("date_to")

        today = date_type.today()
        date_from = date_type.fromisoformat(date_from_str) if date_from_str else today - timedelta(days=30)
        date_to = date_type.fromisoformat(date_to_str) if date_to_str else today

        # ``zev_id`` is already applied by ``scope_queryset``.
        qs = self.get_queryset()
        mp_ids = qs.values_list("metering_point_id", flat=True).distinct()
        metering_points = MeteringPoint.objects.filter(id__in=mp_ids)

        result = compute_data_quality_status(metering_points, date_from, date_to, today)
        return Response({
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "metering_points": result,
        })


class ImportLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = ImportLogSerializer
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return ImportLog.objects.all()
        return ImportLog.objects.filter(Q(zev__owner=user) | Q(imported_by=user)).distinct()

    def _delete_import_logs(self, queryset):
        batch_ids = set(queryset.exclude(batch_id__isnull=True).values_list("batch_id", flat=True))
        deleted_logs = queryset.count()

        with transaction.atomic():
            if batch_ids:
                deleted_readings, _ = MeterReading.objects.filter(import_batch__in=batch_ids).delete()
            else:
                deleted_readings = 0
            queryset.delete()

        return {
            "deleted_logs": deleted_logs,
            "deleted_readings": deleted_readings,
        }

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        result = self._delete_import_logs(self.get_queryset().filter(pk=instance.pk))
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.METERING,
            action_type="import_log.delete",
            target_type="metering.ImportLog",
            target_id=str(instance.pk),
            target_display=str(instance.batch_id),
            summary=f"Deleted import log {instance.pk} and related readings.",
            metadata=result,
        )
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        mode = request.data.get("mode", "all")
        queryset = self.get_queryset()

        zev_id = request.data.get("zev_id")
        if zev_id:
            queryset = queryset.filter(zev_id=zev_id)

        if mode == "period":
            date_from = parse_date(request.data.get("date_from") or "")
            date_to = parse_date(request.data.get("date_to") or "")
            if not date_from or not date_to:
                return Response({"error": "date_from and date_to are required for period deletion."}, status=status.HTTP_400_BAD_REQUEST)
            if date_to < date_from:
                return Response({"error": "date_to must be on or after date_from."}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
        elif mode != "all":
            return Response({"error": "Unsupported deletion mode."}, status=status.HTTP_400_BAD_REQUEST)

        result = self._delete_import_logs(queryset)
        result["mode"] = mode
        record_audit_event(
            request=request,
            action_category=AuditActionCategory.METERING,
            action_type="import_log.bulk_delete",
            target_type="metering.ImportLog",
            summary="Bulk deleted import logs and related readings.",
            metadata={
                "mode": mode,
                "zev_id": zev_id,
                "date_from": str(request.data.get("date_from") or ""),
                "date_to": str(request.data.get("date_to") or ""),
                **result,
            },
        )
        return Response(result, status=status.HTTP_200_OK)


class ImportView(viewsets.ViewSet):
    """Handles CSV and SDAT-CH file uploads for metering data."""
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]
    parser_classes = [MultiPartParser, FormParser]
    # ImportThrottle bounds bulk uploads per user; ApiKeyRateThrottle stays so
    # view-level lists (which replace DEFAULT_THROTTLE_CLASSES) keep counting
    # key-authenticated requests against the key budget.
    throttle_classes = [ApiKeyRateThrottle, ImportThrottle]

    @action(detail=False, methods=["post"], url_path="csv")
    def upload_csv(self, request):
        return self._do_import(request, source="csv")

    @action(detail=False, methods=["post"], url_path="sdatch")
    def upload_sdatch(self, request):
        return self._do_import(request, source="sdatch")

    @action(detail=False, methods=["post"], url_path="preview-csv")
    def preview_csv_import(self, request):
        file = request.FILES.get("file")
        if not file:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.IMPORT,
                action_type="import.preview_csv",
                target_type="metering.ImportLog",
                summary="CSV import preview failed: no file provided.",
                status=AuditEventStatus.FAILED,
            )
            return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        column_map_raw = {k: v for k, v in request.data.items() if k.startswith("col_")}
        column_map = {k[4:]: v for k, v in column_map_raw.items()} if column_map_raw else None
        has_header_raw = request.data.get("has_header", "true")
        has_header = str(has_header_raw).strip().lower() in {"1", "true", "yes", "on"}
        delimiter = request.data.get("delimiter", ",")
        format_profile = request.data.get("format_profile", "standard")
        timestamp_format = request.data.get("timestamp_format") or None
        interval_minutes = request.data.get("interval_minutes", 15)
        values_count = request.data.get("values_count", 96)

        try:
            payload = preview_csv(
                file,
                request.user,
                column_map=column_map,
                timestamp_format=timestamp_format,
                has_header=has_header,
                delimiter=delimiter,
                format_profile=format_profile,
                interval_minutes=interval_minutes,
                values_count=values_count,
            )
        except ImportFileError as exc:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.IMPORT,
                action_type="import.preview_csv",
                target_type="metering.ImportLog",
                summary="CSV import preview failed: file could not be read.",
                status=AuditEventStatus.FAILED,
                metadata={"error": str(exc), "filename": file.name},
            )
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.IMPORT,
                action_type="import.preview_csv",
                target_type="metering.ImportLog",
                summary="CSV import preview failed.",
                status=AuditEventStatus.FAILED,
                metadata={"error": str(exc), "filename": file.name},
            )
            raise

        record_audit_event(
            request=request,
            action_category=AuditActionCategory.IMPORT,
            action_type="import.preview_csv",
            target_type="metering.ImportLog",
            summary="Generated CSV import preview.",
            metadata={
                "filename": file.name,
                "format_profile": format_profile,
                # The preview succeeded, so both values are int-coercible.
                "interval_minutes": int(interval_minutes),
                "values_count": int(values_count),
            },
        )
        return Response(payload)

    def _do_import(self, request, source):
        file = request.FILES.get("file")
        if not file:
            record_audit_event(
                request=request,
                action_category=AuditActionCategory.IMPORT,
                action_type="import.upload",
                target_type="metering.ImportLog",
                summary=f"{source.upper()} import failed: no file provided.",
                status=AuditEventStatus.FAILED,
                metadata={"source": source},
            )
            return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        if source == "csv":
            column_map_raw = {k: v for k, v in request.data.items() if k.startswith("col_")}
            column_map = {k[4:]: v for k, v in column_map_raw.items()} if column_map_raw else None
            has_header_raw = request.data.get("has_header", "true")
            has_header = str(has_header_raw).strip().lower() in {"1", "true", "yes", "on"}
            delimiter = request.data.get("delimiter", ",")
            format_profile = request.data.get("format_profile", "standard")
            timestamp_format = request.data.get("timestamp_format") or None
            interval_minutes = request.data.get("interval_minutes", 15)
            values_count = request.data.get("values_count", 96)
            overwrite_existing_raw = request.data.get("overwrite_existing", "false")
            overwrite_existing = str(overwrite_existing_raw).strip().lower() in {"1", "true", "yes", "on"}

            try:
                log = import_csv(
                    file,
                    request.user,
                    zev=None,
                    column_map=column_map,
                    timestamp_format=timestamp_format,
                    has_header=has_header,
                    delimiter=delimiter,
                    format_profile=format_profile,
                    interval_minutes=interval_minutes,
                    values_count=values_count,
                    overwrite_existing=overwrite_existing,
                )
            except ImportFileError as exc:
                record_audit_event(
                    request=request,
                    action_category=AuditActionCategory.IMPORT,
                    action_type="import.upload",
                    target_type="metering.ImportLog",
                    summary="CSV import failed: file could not be read.",
                    status=AuditEventStatus.FAILED,
                    metadata={"error": str(exc), "filename": file.name, "source": source},
                )
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            zev_id = request.data.get("zev_id")
            try:
                zev = Zev.objects.get(pk=zev_id)
            except Zev.DoesNotExist:
                record_audit_event(
                    request=request,
                    action_category=AuditActionCategory.IMPORT,
                    action_type="import.upload",
                    target_type="zev.Zev",
                    target_id=str(zev_id or ""),
                    target_display=str(zev_id or ""),
                    summary="SDAT-CH import failed: ZEV not found.",
                    status=AuditEventStatus.FAILED,
                    metadata={"source": source, "filename": file.name},
                )
                return Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)

            if not request.user.is_admin and zev.owner != request.user:
                record_audit_event(
                    request=request,
                    action_category=AuditActionCategory.IMPORT,
                    action_type="import.upload",
                    target_type="zev.Zev",
                    target=zev,
                    target_id=str(zev.id),
                    target_display=zev.name,
                    summary="Denied SDAT-CH import due to tenant scope.",
                    status=AuditEventStatus.DENIED,
                    metadata={"source": source, "filename": file.name},
                )
                return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

            log = import_sdatch(file, zev, request.user)

        record_audit_event(
            request=request,
            action_category=AuditActionCategory.IMPORT,
            action_type="import.upload",
            target_type="metering.ImportLog",
            target=log,
            target_id=str(log.id),
            target_display=str(log.batch_id),
            summary=f"Completed {source.upper()} import for {log.rows_imported} rows.",
            metadata={
                "source": source,
                "filename": log.filename,
                "rows_total": log.rows_total,
                "rows_imported": log.rows_imported,
                "rows_skipped": log.rows_skipped,
            },
        )

        return Response(ImportLogSerializer(log).data, status=status.HTTP_201_CREATED)
