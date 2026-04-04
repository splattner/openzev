from datetime import date as date_type, datetime, timedelta, timezone as dt_timezone

from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import TruncDay, TruncHour, TruncMonth
from django.utils.dateparse import parse_date
from decimal import Decimal
from rest_framework import mixins, viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from accounts.permissions import IsZevOwnerOrAdmin
from zev.models import Zev, Participant, MeteringPointAssignment
from .models import MeterReading, ImportLog
from .serializers import MeterReadingSerializer, ImportLogSerializer
from .importers.csv_importer import import_csv, preview_csv
from .importers.sdatch_importer import import_sdatch


class MeterReadingViewSet(viewsets.ModelViewSet):
    serializer_class = MeterReadingSerializer
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        qs = MeterReading.objects.select_related("metering_point__zev")
        if user.is_admin:
            return qs
        if user.is_zev_owner:
            return qs.filter(metering_point__zev__owner=user)
        return qs.filter(metering_point__assignments__participant__user=user).distinct()

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

            today = date_type.today()

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
                base.filter(
                    direction="in",
                    metering_point__assignments__valid_from__lte=today,
                )
                .filter(
                    Q(metering_point__assignments__valid_to__isnull=True)
                    | Q(metering_point__assignments__valid_to__gte=today)
                )
                .values(
                    "metering_point__assignments__participant_id",
                    "metering_point__assignments__participant__first_name",
                    "metering_point__assignments__participant__last_name",
                    "timestamp",
                    "bucket",
                )
                .annotate(consumed_kwh=Sum("energy_kwh"))
                .order_by("metering_point__assignments__participant_id", "timestamp")
            )

            participant_production_rows = (
                base.filter(
                    direction="out",
                    metering_point__assignments__valid_from__lte=today,
                )
                .filter(
                    Q(metering_point__assignments__valid_to__isnull=True)
                    | Q(metering_point__assignments__valid_to__gte=today)
                )
                .values(
                    "metering_point__assignments__participant_id",
                    "metering_point__assignments__participant__first_name",
                    "metering_point__assignments__participant__last_name",
                    "timestamp",
                    "bucket",
                )
                .annotate(produced_kwh=Sum("energy_kwh"))
                .order_by("metering_point__assignments__participant_id", "timestamp")
            )

            participant_map = {}
            for row in participant_rows:
                pid = str(row["metering_point__assignments__participant_id"])
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
                            f"{row['metering_point__assignments__participant__first_name']} "
                            f"{row['metering_point__assignments__participant__last_name']}"
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
                pid = str(row["metering_point__assignments__participant_id"])
                bucket_key = row["bucket"].isoformat()
                produced = row["produced_kwh"] or Decimal("0")

                if pid not in participant_map:
                    participant_map[pid] = {
                        "participant_id": pid,
                        "participant_name": (
                            f"{row['metering_point__assignments__participant__first_name']} "
                            f"{row['metering_point__assignments__participant__last_name']}"
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
                "zev_totals": zev_wide_totals,
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

        # ── ZEV-wide totals & per-participant stats (for Sankey chart) ──
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

        today = date_type.today()
        all_consumption_rows = (
            zev_qs.annotate(bucket=trunc_fn("timestamp"))
            .filter(
                direction="in",
                metering_point__assignments__valid_from__lte=today,
            )
            .filter(
                Q(metering_point__assignments__valid_to__isnull=True)
                | Q(metering_point__assignments__valid_to__gte=today)
            )
            .values(
                "metering_point__assignments__participant_id",
                "metering_point__assignments__participant__first_name",
                "metering_point__assignments__participant__last_name",
                "timestamp",
            )
            .annotate(consumed_kwh=Sum("energy_kwh"))
            .order_by("metering_point__assignments__participant_id", "timestamp")
        )
        all_production_rows = (
            zev_qs.annotate(bucket=trunc_fn("timestamp"))
            .filter(
                direction="out",
                metering_point__assignments__valid_from__lte=today,
            )
            .filter(
                Q(metering_point__assignments__valid_to__isnull=True)
                | Q(metering_point__assignments__valid_to__gte=today)
            )
            .values(
                "metering_point__assignments__participant_id",
                "metering_point__assignments__participant__first_name",
                "metering_point__assignments__participant__last_name",
            )
            .annotate(produced_kwh=Sum("energy_kwh"))
            .order_by("metering_point__assignments__participant_id")
        )

        all_p_map = {}
        for row in all_consumption_rows:
            pid = str(row["metering_point__assignments__participant_id"])
            ts = row["timestamp"]
            consumed = row["consumed_kwh"] or Decimal("0")
            zev_at_ts = zev_pivot.get(ts, {})
            total_consumed = zev_at_ts.get("consumed", Decimal("0"))
            total_produced = zev_at_ts.get("produced", Decimal("0"))
            local_pool = min(total_produced, total_consumed)
            if total_consumed > 0 and local_pool > 0:
                from_zev = min(consumed, local_pool * (consumed / total_consumed))
            else:
                from_zev = Decimal("0")
            from_grid = max(consumed - from_zev, Decimal("0"))
            if pid not in all_p_map:
                all_p_map[pid] = {
                    "participant_id": pid,
                    "participant_name": (
                        f"{row['metering_point__assignments__participant__first_name']} "
                        f"{row['metering_point__assignments__participant__last_name']}"
                    ).strip(),
                    "total_consumed_kwh": Decimal("0"),
                    "total_produced_kwh": Decimal("0"),
                    "from_zev_kwh": Decimal("0"),
                    "from_grid_kwh": Decimal("0"),
                }
            all_p_map[pid]["total_consumed_kwh"] += consumed
            all_p_map[pid]["from_zev_kwh"] += from_zev
            all_p_map[pid]["from_grid_kwh"] += from_grid

        for row in all_production_rows:
            pid = str(row["metering_point__assignments__participant_id"])
            produced = row["produced_kwh"] or Decimal("0")
            if pid not in all_p_map:
                all_p_map[pid] = {
                    "participant_id": pid,
                    "participant_name": (
                        f"{row['metering_point__assignments__participant__first_name']} "
                        f"{row['metering_point__assignments__participant__last_name']}"
                    ).strip(),
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

        current_participant_ids = list(
            Participant.objects.filter(user=user, zev_id__in=zev_ids)
            .values_list("id", flat=True)
        )

        return Response({
            "role": "participant",
            "bucket": bucket,
            "totals": {k: float(v) for k, v in totals.items()},
            "timeline": timeline,
            "zev_totals": {k: float(v) for k, v in zev_totals.items()},
            "zev_participant_stats": zev_participant_stats,
            "current_participant_id": str(current_participant_ids[0]) if current_participant_ids else None,
        })

    @action(detail=False, methods=["get"], url_path="hourly-profile", permission_classes=[IsAuthenticated])
    def hourly_profile(self, request):
        """
        Return a 24-hour average daily consumption profile for a participant,
        split into local ZEV energy and grid import.

        Query params:
          date_from  – YYYY-MM-DD (required)
          date_to    – YYYY-MM-DD (required)
          zev_id     – UUID (optional, required for admin/owner)
          participant_id – UUID (optional, for admin/owner to view a specific participant)
        """
        from zev.models import MeteringPoint, MeteringPointType

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

        # Determine participant and ZEV
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

        # Participant consumption readings (sub-daily only)
        consumption_mps = MeteringPoint.objects.filter(
            zev_id=selected_zev_id,
            meter_type__in=[MeteringPointType.CONSUMPTION, MeteringPointType.BIDIRECTIONAL],
            assignments__participant_id__in=participant_ids,
            assignments__valid_from__lte=pe,
        ).filter(
            Q(assignments__valid_to__isnull=True) | Q(assignments__valid_to__gte=ps)
        ).distinct()

        participant_readings = list(
            MeterReading.objects.filter(
                metering_point__in=consumption_mps,
                timestamp__gte=start_dt,
                timestamp__lt=end_dt,
                direction="in",
            ).order_by("timestamp")
        )

        if not participant_readings:
            return Response({"hourly_profile": None})

        resolutions = {r.resolution for r in participant_readings}
        if resolutions == {"daily"}:
            return Response({"hourly_profile": None})

        # ZEV-level production and consumption by timestamp
        all_prod_mps = MeteringPoint.objects.filter(
            zev_id=selected_zev_id,
            meter_type__in=[MeteringPointType.PRODUCTION, MeteringPointType.BIDIRECTIONAL],
            assignments__valid_from__lte=pe,
        ).filter(
            Q(assignments__valid_to__isnull=True) | Q(assignments__valid_to__gte=ps)
        ).distinct()

        zev_prod_by_ts = {
            row["timestamp"]: float(row["total_kwh"] or 0)
            for row in MeterReading.objects.filter(
                metering_point__in=all_prod_mps,
                timestamp__gte=start_dt,
                timestamp__lt=end_dt,
                direction="out",
            ).values("timestamp").annotate(total_kwh=Sum("energy_kwh"))
        }

        all_cons_mps = MeteringPoint.objects.filter(
            zev_id=selected_zev_id,
            meter_type__in=[MeteringPointType.CONSUMPTION, MeteringPointType.BIDIRECTIONAL],
            assignments__valid_from__lte=pe,
        ).filter(
            Q(assignments__valid_to__isnull=True) | Q(assignments__valid_to__gte=ps)
        ).distinct()

        zev_cons_by_ts = {
            row["timestamp"]: float(row["total_kwh"] or 0)
            for row in MeterReading.objects.filter(
                metering_point__in=all_cons_mps,
                timestamp__gte=start_dt,
                timestamp__lt=end_dt,
                direction="in",
            ).values("timestamp").annotate(total_kwh=Sum("energy_kwh"))
        }

        # Accumulate local/grid per hour-of-day
        hourly_local = [0.0] * 24
        hourly_grid = [0.0] * 24

        for reading in participant_readings:
            ts = reading.timestamp
            hour = ts.hour
            p_kwh = float(reading.energy_kwh)
            zev_cons = zev_cons_by_ts.get(ts, 0.0)
            zev_prod = zev_prod_by_ts.get(ts, 0.0)
            local_pool = min(zev_prod, zev_cons)

            if zev_cons > 0 and local_pool > 0:
                r_local = min(p_kwh, local_pool * p_kwh / zev_cons)
            else:
                r_local = 0.0
            r_grid = max(p_kwh - r_local, 0.0)

            hourly_local[hour] += r_local
            hourly_grid[hour] += r_grid

        total_days = (pe - ps).days + 1
        hourly_local = [v / total_days for v in hourly_local]
        hourly_grid = [v / total_days for v in hourly_grid]

        profile = [
            {
                "hour": h,
                "from_zev_kwh": round(hourly_local[h], 4),
                "from_grid_kwh": round(hourly_grid[h], 4),
            }
            for h in range(24)
        ]

        return Response({"hourly_profile": profile})

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
        # Parse dates (default to last 30 days)
        date_from_str = request.query_params.get("date_from")
        date_to_str = request.query_params.get("date_to")
        zev_id = request.query_params.get("zev_id")

        today = date_type.today()
        date_from = date_type.fromisoformat(date_from_str) if date_from_str else today - timedelta(days=30)
        date_to = date_type.fromisoformat(date_to_str) if date_to_str else today

        # Get metering points based on user role
        qs = self.get_queryset()
        if zev_id:
            qs = qs.filter(metering_point__zev_id=zev_id)
        
        # Group by metering point
        mp_ids = qs.values_list("metering_point_id", flat=True).distinct()
        from zev.models import MeteringPoint
        metering_points = MeteringPoint.objects.filter(id__in=mp_ids)

        result = []
        for mp in metering_points:
            # Get all readings for this metering point in date range
            readings = (
                MeterReading.objects
                .filter(metering_point=mp)
                .filter(timestamp__gte=datetime.combine(date_from, datetime.min.time(), tzinfo=dt_timezone.utc))
                .filter(timestamp__lt=datetime.combine(date_to, datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(days=1))
                .values_list("timestamp", flat=True)
            )

            # Extract unique days with data
            days_with_data = set()
            for ts in readings:
                days_with_data.add(ts.date())

            # Generate all expected days
            all_days = set()
            current = date_from
            while current <= date_to:
                all_days.add(current)
                current = current + timedelta(days=1)

            # Find gaps (consecutive missing days)
            missing_days = sorted(all_days - days_with_data)
            gaps = []
            if missing_days:
                gap_start = missing_days[0]
                gap_end = missing_days[0]
                for day in missing_days[1:]:
                    if day == gap_end + timedelta(days=1):
                        gap_end = day
                    else:
                        gaps.append({
                            "start_date": gap_start.isoformat(),
                            "end_date": gap_end.isoformat(),
                            "duration_days": (gap_end - gap_start).days + 1,
                        })
                        gap_start = day
                        gap_end = day
                gaps.append({
                    "start_date": gap_start.isoformat(),
                    "end_date": gap_end.isoformat(),
                    "duration_days": (gap_end - gap_start).days + 1,
                })

            # Calculate severity and completeness
            data_completeness = int(100 * len(days_with_data) / len(all_days)) if all_days else 0
            if data_completeness == 100:
                severity = "green"
            elif data_completeness >= 50:
                severity = "yellow"
            else:
                severity = "red"

            # Get participant name
            participant = (
                mp.assignments.filter(valid_from__lte=today)
                .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
                .order_by("-valid_from")
                .first()
            )
            participant_name = participant.participant.full_name if participant else "Unassigned"

            result.append({
                "id": str(mp.id),
                "meter_id": mp.meter_id,
                "participant_name": participant_name,
                "severity": severity,
                "data_completeness": data_completeness,
                "days_with_data": len(days_with_data),
                "total_days": len(all_days),
                "gaps": gaps,
            })

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
        return Response(result, status=status.HTTP_200_OK)


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
