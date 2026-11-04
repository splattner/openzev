import uuid

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification
from .serializers import NotificationSerializer
from .visibility import visible_to


class NotificationPagination(PageNumberPagination):
    page_size = 20


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


class _Own:
    """The caller's own notifications, as far as they may still see them (``visibility.visible_to``)."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        queryset = visible_to(self.request.user).select_related("zev")
        zev = self.request.query_params.get("zev")
        if zev:
            queryset = queryset.filter(zev_id=zev) if _is_uuid(zev) else queryset.none()
        return queryset


@extend_schema(parameters=[OpenApiParameter("unread", bool), OpenApiParameter("zev", str)])
class NotificationListView(_Own, ListAPIView):
    """The caller's notifications, newest first."""

    pagination_class = NotificationPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("unread", "").lower() in {"1", "true", "yes"}:
            queryset = queryset.filter(read_at__isnull=True)
        return queryset


class NotificationUnreadCountView(_Own, GenericAPIView):
    @extend_schema(responses={200: {"type": "object", "properties": {"count": {"type": "integer"}}}})
    def get(self, request):
        return Response({"count": self.get_queryset().filter(read_at__isnull=True).count()})


class NotificationReadView(_Own, GenericAPIView):
    @extend_schema(request=None, responses={200: NotificationSerializer})
    def post(self, request, pk):
        notification = get_object_or_404(self.get_queryset(), pk=pk)
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(self.get_serializer(notification).data)


class NotificationReadAllView(_Own, GenericAPIView):
    @extend_schema(request=None, responses={200: {"type": "object", "properties": {"updated": {"type": "integer"}}}})
    def post(self, request):
        ids = list(self.get_queryset().filter(read_at__isnull=True).values_list("pk", flat=True))
        updated = Notification.objects.filter(pk__in=ids, read_at__isnull=True).update(read_at=timezone.now())
        return Response({"updated": updated})
