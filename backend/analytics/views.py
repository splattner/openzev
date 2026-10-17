from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.api_keys import generate_key
from accounts.authentication import ApiKeyAuthentication, CookieJWTAuthentication
from accounts.throttling import ApiKeyRateThrottle
from audit.models import AuditActionCategory
from audit.services import record_audit_event
from zev import access
from zev.models import Zev

from .authentication import AnalyticsTokenAuthentication, AnalyticsTokenThrottle, tokens_enabled
from .dataset import COLUMNS, DatasetError, SeriesQuery, build_series
from .models import TOKEN_NAMESPACE, AnalyticsToken
from .renderers import SeriesCsvRenderer
from .scope import resolve_visibility
from .serializers import AnalyticsTokenCreateSerializer, AnalyticsTokenSerializer, SeriesQuerySerializer


class CanReadAnalytics(BasePermission):
    """A signed-in account, or a valid analytics token."""

    def has_permission(self, request, view):
        return isinstance(request.auth, AnalyticsToken) or bool(request.user and request.user.is_authenticated)


class SeriesView(APIView):
    """The scoped analytics dataset (SPEC-2026-analytics-dataset-api).

    Reads only. What the caller may see is decided by :func:`analytics.scope.resolve_visibility`
    and enforced inside :func:`analytics.dataset.build_series`.
    """

    authentication_classes = [AnalyticsTokenAuthentication, CookieJWTAuthentication, ApiKeyAuthentication]
    permission_classes = [CanReadAnalytics]
    throttle_classes = [ApiKeyRateThrottle, AnalyticsTokenThrottle]
    renderer_classes = [JSONRenderer, SeriesCsvRenderer]

    @extend_schema(
        summary="Scoped analytics series",
        description=(
            "Long-format energy rows per time bucket (Europe/Zurich), split into local, grid and "
            "feed-in energy exactly as invoices are. Use `?format=csv` for CSV."
        ),
        parameters=[
            OpenApiParameter("zev", str, description="ZEV id. Optional with an analytics token."),
            OpenApiParameter("from", str, required=True, description="First day, YYYY-MM-DD (inclusive)."),
            OpenApiParameter("to", str, required=True, description="Last day, YYYY-MM-DD (inclusive)."),
            OpenApiParameter("granularity", str, enum=["15min", "hour", "day", "week", "month", "year"]),
            OpenApiParameter("group_by", str, enum=["metering_point", "participant", "zev"]),
            OpenApiParameter("direction", str, enum=["in", "out"]),
            OpenApiParameter("participant", str, description="Only this participant's rows."),
            OpenApiParameter("metering_point", str, description="Only this metering point's rows."),
        ],
        responses={200: OpenApiResponse(description=f"`results` rows with columns: {', '.join(COLUMNS)}.")},
    )
    def get(self, request):
        params = SeriesQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data

        token = request.auth if isinstance(request.auth, AnalyticsToken) else None
        zev_id = data.get("zev") or (token.zev_id if token else None)
        if zev_id is None:
            return Response({"zev": ["This query parameter is required."]}, status=status.HTTP_400_BAD_REQUEST)
        try:
            zev = Zev.objects.get(pk=zev_id)
        except Zev.DoesNotExist:
            raise Http404("ZEV not found.") from None

        visibility = resolve_visibility(request, zev)
        query = SeriesQuery(
            zev=zev,
            start=data["from"],
            end=data["to"],
            granularity=data["granularity"],
            group_by=data["group_by"],
            directions=frozenset([data["direction"]] if "direction" in data else ["in", "out"]),
            participant_id=data.get("participant"),
            metering_point_id=data.get("metering_point"),
        )
        try:
            series = build_series(query, visibility)
        except DatasetError as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=exc.status)
        return Response({"meta": series.meta, "results": series.rows})


def _audit(request, action_type, token, summary, metadata):
    record_audit_event(
        request=request,
        action_category=AuditActionCategory.AUTH,
        action_type=f"analytics_token.{action_type}",
        target_type="analytics.AnalyticsToken",
        target=token,
        target_id=str(token.pk),
        target_display=token.name,
        zev=token.zev,
        summary=summary,
        metadata=metadata,
    )


class AnalyticsTokenViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet,
):
    """Create, list and revoke analytics tokens.

    Session-authenticated only: a token or API key cannot mint further credentials,
    so revoking a leaked one achieves something. Answers ``404`` while
    ``analytics_tokens_enabled`` is off.
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = AnalyticsTokenSerializer
    pagination_class = None

    def initial(self, request, *args, **kwargs):
        if not tokens_enabled():
            raise Http404
        super().initial(request, *args, **kwargs)

    def get_queryset(self):
        qs = AnalyticsToken.objects.filter(revoked_at__isnull=True).select_related(
            "zev", "participant", "participant__party", "created_by",
        )
        user = self.request.user
        if user.is_admin:
            return qs
        return qs.filter(Q(created_by=user) | Q(zev_id__in=access.managed_zev_ids(user)))

    @extend_schema(request=AnalyticsTokenCreateSerializer, responses={201: AnalyticsTokenSerializer})
    def create(self, request, *args, **kwargs):
        serializer = AnalyticsTokenCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        full_key, prefix, hashed_key = generate_key(TOKEN_NAMESPACE)
        with transaction.atomic():
            token = AnalyticsToken.objects.create(
                name=data["name"],
                zev=data["zev"],
                participant=data.get("participant"),
                created_by=request.user,
                prefix=prefix,
                hashed_key=hashed_key,
                expires_at=data.get("expires_at"),
            )
            _audit(
                request, "create", token, f"Created analytics token '{token.name}'.",
                {
                    "prefix": prefix,
                    "zev_id": str(token.zev_id),
                    "participant_id": str(token.participant_id) if token.participant_id else None,
                    "expires_at": token.expires_at,
                },
            )
        # The only response that carries the secret; it cannot be retrieved again.
        body = AnalyticsTokenSerializer(token).data
        body["token"] = full_key
        return Response(body, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        """Revoke rather than delete, so an audit event still resolves to a name."""
        with transaction.atomic():
            instance.revoked_at = timezone.now()
            instance.save(update_fields=["revoked_at"])
            _audit(request=self.request, action_type="revoke", token=instance,
                   summary=f"Revoked analytics token '{instance.name}'.", metadata={"prefix": instance.prefix})
