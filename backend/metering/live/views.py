"""Live energy endpoints (SPEC-2026-live-energy-data §5).

Everything answers ``404`` while the live flag is not effective. Nothing here writes to the
database except ``SupplementarySource.live_last_seen_at`` (at coarse resolution, status only) and
nothing is audited per sample.
"""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from allocation.validity import active_on, civil_date, period_end_exclusive_dt
from zev import access
from zev.models import AllocationMode, MeteringPointAssignment, Zev

from ..models import SourceHolder, SourceTarget, SupplementarySource
from ..supplementary.authentication import IsPushSource, SupplementaryPushAuthentication
from ..supplementary.permissions import personally_held_today
from . import store
from .curve import earliest_day_start, zev_curve
from .permissions import LiveEnergyPermission, LiveFeatureMixin, LivePushThrottle, LiveReadThrottle
from .serializers import LiveIngestResultSerializer, LiveIngestSerializer
from .snapshot import zev_snapshot


def _holder_gone(source: SupplementarySource, today: date) -> bool:
    """Has the person this source was consented by lost the right to its meter (SPEC §5.1)?

    A participant-held source needs its participant to hold the metering point personally today. A
    ZEV-held one stops when somebody does: a household's live value must not keep flowing to the
    manager without its consent. The connection point has no holder to lose.
    """
    if source.target == SourceTarget.CONNECTION_POINT:
        return False
    if source.held_by == SourceHolder.ZEV:
        return personally_held_today(source.metering_point, today)
    return not active_on(
        MeteringPointAssignment.objects.filter(
            metering_point_id=source.metering_point_id,
            participant_id=source.participant_id,
            allocation_mode=AllocationMode.PERSONAL,
        ),
        today,
    ).exists()


def _touch_last_seen(source: SupplementarySource, now) -> None:
    last = source.live_last_seen_at
    if last is not None and (now - last).total_seconds() < settings.LIVE_LAST_SEEN_RESOLUTION_S:
        return
    SupplementarySource.objects.filter(pk=source.pk).update(live_last_seen_at=now)
    source.live_last_seen_at = now


class LiveIngestView(LiveFeatureMixin, APIView):
    """``POST /api/v1/metering/live/ingest/``: one sample of current power for the token's source."""

    authentication_classes = [SupplementaryPushAuthentication]
    permission_classes = [IsPushSource]
    throttle_classes = [LivePushThrottle]
    parser_classes = [JSONParser]

    @extend_schema(request=LiveIngestSerializer, responses={202: LiveIngestResultSerializer})
    def post(self, request):
        source = request.auth
        if not source.provides_live:
            raise PermissionDenied("This source does not provide live data.")
        now = timezone.now()
        if _holder_gone(source, civil_date(now)):
            raise PermissionDenied("This source's metering point is no longer held by its owner.")

        serializer = LiveIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # After validation, so a rejected request does not use up the slot.
        wait = store.claim_push_slot(source.pk, now)
        if wait:
            raise Throttled(wait=wait)

        store.put_sample(
            store.LiveSample(
                source_id=str(source.pk),
                timestamp=data.get("timestamp", now),
                received_at=now,
                meter_power_w=data["meter_power_w"],
                production_w=data.get("production_w"),
                consumption_w=data.get("consumption_w"),
            )
        )
        _touch_last_seen(source, now)
        return Response({"accepted": True}, status=status.HTTP_202_ACCEPTED)


class LiveReadView(LiveFeatureMixin, APIView):
    permission_classes = [LiveEnergyPermission]
    throttle_classes = [LiveReadThrottle]
    zev: Zev  # set by LiveEnergyPermission


class LiveSnapshotView(LiveReadView):
    """``GET /api/v1/metering/live/zevs/{zev_id}/``: the ZEV snapshot, narrowed by role."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, zev_id):
        return Response(zev_snapshot(self.zev, now=timezone.now(), viewer=request.user))


class LiveCurveView(LiveReadView):
    """``GET /api/v1/metering/live/zevs/{zev_id}/curve/?date=YYYY-MM-DD``: 5-minute buckets of a civil day."""

    @extend_schema(
        parameters=[OpenApiParameter("date", OpenApiTypes.DATE, description="Civil day, default today.")],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, zev_id):
        now = timezone.now()
        raw = request.query_params.get("date")
        if raw:
            try:
                day = date.fromisoformat(raw)
            except ValueError:
                raise ValidationError({"date": ["Use the format YYYY-MM-DD."]}) from None
        else:
            day = civil_date(now)
        if day > civil_date(now):
            raise ValidationError({"date": ["The date is in the future."]})
        if period_end_exclusive_dt(day) <= earliest_day_start(now):
            raise ValidationError(
                {"date": [f"Live values are kept for {settings.LIVE_CURVE_RETENTION_H} hours only."]}
            )
        return Response(zev_curve(self.zev, day, now=now, viewer=request.user))


class LiveMeView(LiveFeatureMixin, APIView):
    """``GET /api/v1/metering/live/me/``: a compact snapshot per ZEV the caller participates in.

    Flat keys, for a Home Assistant ``rest`` sensor or an n8n flow. Works with a personal API key,
    a ``read_only`` one included.
    """

    throttle_classes = [LiveReadThrottle]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        now = timezone.now()
        zevs = Zev.objects.filter(pk__in=access.participant_zev_ids(request.user)).order_by("name")
        if not request.user.is_admin:
            zevs = zevs.filter(disabled_at__isnull=True)
        entries = []
        for zev in zevs:
            snapshot = zev_snapshot(zev, now=now, viewer=request.user)
            own = snapshot["own"] or {}
            entries.append(
                {
                    "zev_id": snapshot["zev_id"],
                    "zev_name": zev.name,
                    "tier": snapshot["tier"],
                    "as_of": snapshot["as_of"],
                    "production_w": snapshot["production_w"],
                    "surplus_w": snapshot["surplus_w"],
                    "local_share_pct": snapshot["local_share_pct"],
                    "own_consumption_w": own.get("consumption_w"),
                    "own_local_w": own.get("local_w"),
                    "forecast_next_peak": None,  # arrives with the forecast (SPEC §10, PR 5)
                }
            )
        return Response({"zevs": entries})
