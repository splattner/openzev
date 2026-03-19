from datetime import date as date_type, datetime, timedelta, timezone as dt_timezone

from django.db.models import Q, Sum
from django.db.models.functions import TruncDay, TruncHour, TruncMonth
from decimal import Decimal
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from accounts.permissions import IsZevOwnerOrAdmin
from zev.models import Zev, Participant
from .models import MeterReading, ImportLog
from .serializers import MeterReadingSerializer, ImportLogSerializer
from .importers.csv_importer import import_csv, preview_csv
from .importers.sdatch_importer import import_sdatch


class MeterReadingViewSet(viewsets.ModelViewSet):
    serializer_class = MeterReadingSerializer
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        qs = MeterReading.objects.select_related("metering_point__zev", "metering_point__participant")
        if user.is_admin:
            return qs
        if user.is_zev_owner:
            return qs.filter(metering_point__zev__owner=user)
        return qs.filter(
            Q(metering_point__participant__user=user)
            | Q(metering_point__assignments__participant__user=user)
        ).distinct()

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
        """Return raw metering readings grouped by day for one metering point."""
        mp_id = request.query_params.get("metering_point")
        if not mp_id:
            return Response({"error": "metering_point query parameter is required."}, status=400)

        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        qs = self.get_queryset().filter(metering_point_id=mp_id).order_by("timestamp")
        if date_from:
            # Use explicit UTC bounds — timestamp__date__ applies Europe/Zurich and would drop 23:xx UTC readings.
            qs = qs.filter(timestamp__gte=datetime.combine(date_type.fromisoformat(date_from), datetime.min.time(), tzinfo=dt_timezone.utc))
        if date_to:
            qs = qs.filter(timestamp__lt=datetime.combine(date_type.fromisoformat(date_to), datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(days=1))

        day_map = {}
        for reading in qs:
            day_key = reading.timestamp.date().isoformat()
            if day_key not in day_map:
                day_map[day_key] = {
                    "date": day_key,
                    "in_kwh": 0.0,
                    "out_kwh": 0.0,
                    "readings_count": 0,
                    "readings": [],
                }

            energy = float(reading.energy_kwh)
            day_map[day_key]["readings_count"] += 1
            if reading.direction == "in":
                day_map[day_key]["in_kwh"] += energy
            elif reading.direction == "out":
                day_map[day_key]["out_kwh"] += energy

            day_map[day_key]["readings"].append(
                {
                    "timestamp": reading.timestamp.isoformat(),
                    "direction": reading.direction,
                    "energy_kwh": energy,
                    "resolution": reading.resolution,
                    "import_source": reading.import_source,
                }
            )

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

        base = qs.annotate(bucket=trunc_fn("timestamp"))

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

            base = qs.annotate(bucket=trunc_fn("timestamp"))

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

            participant_rows = (
                base.filter(direction="in", metering_point__participant__isnull=False)
                .values(
                    "metering_point__participant_id",
                    "metering_point__participant__first_name",
                    "metering_point__participant__last_name",
                    "timestamp",
                    "bucket",
                )
                .annotate(consumed_kwh=Sum("energy_kwh"))
                .order_by("metering_point__participant_id", "timestamp")
            )

            participant_production_rows = (
                base.filter(direction="out", metering_point__participant__isnull=False)
                .values(
                    "metering_point__participant_id",
                    "metering_point__participant__first_name",
                    "metering_point__participant__last_name",
                    "timestamp",
                    "bucket",
                )
                .annotate(produced_kwh=Sum("energy_kwh"))
                .order_by("metering_point__participant_id", "timestamp")
            )

            participant_map = {}
            for row in participant_rows:
                pid = str(row["metering_point__participant_id"])
                ts = row["timestamp"]
                bucket_key = row["bucket"].isoformat()
                consumed = row["consumed_kwh"] or Decimal("0")

                zev_at_ts = ts_pivot.get(ts, {})
                total_consumed = zev_at_ts.get("consumed_kwh", Decimal("0"))
                total_produced = zev_at_ts.get("produced_kwh", Decimal("0"))
                local_pool = min(total_produced, total_consumed)

                if total_consumed > 0 and local_pool > 0:
                    from_zev = min(consumed, local_pool * (consumed / total_consumed))
                else:
                    from_zev = Decimal("0")
                from_grid = max(consumed - from_zev, Decimal("0"))

                if pid not in participant_map:
                    participant_map[pid] = {
                        "participant_id": pid,
                        "participant_name": (
                            f"{row['metering_point__participant__first_name']} "
                            f"{row['metering_point__participant__last_name']}"
                        ).strip(),
                        "total_consumed_kwh": Decimal("0"),
                        "total_produced_kwh": Decimal("0"),
                        "from_zev_kwh": Decimal("0"),
                        "from_grid_kwh": Decimal("0"),
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
                pid = str(row["metering_point__participant_id"])
                bucket_key = row["bucket"].isoformat()
                produced = row["produced_kwh"] or Decimal("0")

                if pid not in participant_map:
                    participant_map[pid] = {
                        "participant_id": pid,
                        "participant_name": (
                            f"{row['metering_point__participant__first_name']} "
                            f"{row['metering_point__participant__last_name']}"
                        ).strip(),
                        "total_consumed_kwh": Decimal("0"),
                        "total_produced_kwh": Decimal("0"),
                        "from_zev_kwh": Decimal("0"),
                        "from_grid_kwh": Decimal("0"),
                        "timeline_map": {},
                    }

                participant_map[pid]["total_produced_kwh"] += produced

                if bucket_key not in participant_map[pid]["timeline_map"]:
                    participant_map[pid]["timeline_map"][bucket_key] = {
                        "bucket": bucket_key,
                        "consumed_kwh": Decimal("0"),
                        "produced_kwh": Decimal("0"),
                        "imported_kwh": Decimal("0"),
                        "exported_kwh": Decimal("0"),
                    }

                participant_map[pid]["timeline_map"][bucket_key]["produced_kwh"] += produced
                participant_map[pid]["timeline_map"][bucket_key]["exported_kwh"] += produced

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
            response_timeline = timeline
            selected_participant_name = None

            if selected_participant_id and selected_participant_id in participant_map:
                selected = participant_map[selected_participant_id]
                selected_participant_name = selected["participant_name"]
                response_totals = {
                    "produced_kwh": float(selected["total_produced_kwh"]),
                    "consumed_kwh": float(selected["total_consumed_kwh"]),
                    "imported_kwh": float(selected["from_grid_kwh"]),
                    "exported_kwh": float(selected["total_produced_kwh"]),
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

            return Response({
                "role": "zev_owner",
                "bucket": bucket,
                "totals": response_totals,
                "timeline": response_timeline,
                "participant_stats": participant_stats,
                "selected_participant_id": selected_participant_id,
                "selected_participant_name": selected_participant_name,
            })

        # participant analytics
        participant_rows = (
            base.filter(direction="in")
            .values("bucket", "timestamp")
            .annotate(consumed_kwh=Sum("energy_kwh"))
            .order_by("timestamp")
        )

        zev_ids = qs.values_list("metering_point__zev_id", flat=True).distinct()
        zev_qs = MeterReading.objects.filter(metering_point__zev_id__in=zev_ids)
        if date_from:
            zev_qs = zev_qs.filter(timestamp__gte=datetime.combine(date_type.fromisoformat(date_from), datetime.min.time(), tzinfo=dt_timezone.utc))
        if date_to:
            zev_qs = zev_qs.filter(timestamp__lt=datetime.combine(date_type.fromisoformat(date_to), datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(days=1))

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
            bucket_key = row["bucket"].isoformat()
            ts = row["timestamp"]
            participant_consumed = row["consumed_kwh"] or Decimal("0")
            zev_consumed = zev_pivot.get(ts, {}).get("consumed", Decimal("0"))
            zev_produced = zev_pivot.get(ts, {}).get("produced", Decimal("0"))
            local_pool = min(zev_produced, zev_consumed)
            if zev_consumed > 0 and local_pool > 0:
                consumed_from_zev = min(participant_consumed, local_pool * (participant_consumed / zev_consumed))
            else:
                consumed_from_zev = Decimal("0")
            imported_from_grid = max(participant_consumed - consumed_from_zev, Decimal("0"))

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

        return Response({
            "role": "participant",
            "bucket": bucket,
            "totals": {k: float(v) for k, v in totals.items()},
            "timeline": timeline,
        })


class ImportLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ImportLogSerializer
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return ImportLog.objects.all()
        return ImportLog.objects.filter(Q(zev__owner=user) | Q(imported_by=user)).distinct()


class ImportView(viewsets.ViewSet):
    """Handles CSV and SDAT-CH file uploads for metering data."""
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]
    parser_classes = [MultiPartParser, FormParser]

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
            return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        column_map_raw = {k: v for k, v in request.data.items() if k.startswith("col_")}
        column_map = {k[4:]: v for k, v in column_map_raw.items()} if column_map_raw else None
        has_header_raw = request.data.get("has_header", "true")
        has_header = str(has_header_raw).strip().lower() in {"1", "true", "yes", "on"}
        delimiter = request.data.get("delimiter", ",")
        format_profile = request.data.get("format_profile", "standard")
        timestamp_format = request.data.get("timestamp_format") or None
        interval_minutes = int(request.data.get("interval_minutes", 15))
        values_count = int(request.data.get("values_count", 96))

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
        return Response(payload)

    def _do_import(self, request, source):
        file = request.FILES.get("file")
        if not file:
            return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        if source == "csv":
            column_map_raw = {k: v for k, v in request.data.items() if k.startswith("col_")}
            column_map = {k[4:]: v for k, v in column_map_raw.items()} if column_map_raw else None
            has_header_raw = request.data.get("has_header", "true")
            has_header = str(has_header_raw).strip().lower() in {"1", "true", "yes", "on"}
            delimiter = request.data.get("delimiter", ",")
            format_profile = request.data.get("format_profile", "standard")
            timestamp_format = request.data.get("timestamp_format") or None
            interval_minutes = int(request.data.get("interval_minutes", 15))
            values_count = int(request.data.get("values_count", 96))
            overwrite_existing_raw = request.data.get("overwrite_existing", "false")
            overwrite_existing = str(overwrite_existing_raw).strip().lower() in {"1", "true", "yes", "on"}

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
        else:
            zev_id = request.data.get("zev_id")
            try:
                zev = Zev.objects.get(pk=zev_id)
            except Zev.DoesNotExist:
                return Response({"error": "ZEV not found."}, status=status.HTTP_404_NOT_FOUND)

            if not request.user.is_admin and zev.owner != request.user:
                return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

            log = import_sdatch(file, zev, request.user)

        return Response(ImportLogSerializer(log).data, status=status.HTTP_201_CREATED)
