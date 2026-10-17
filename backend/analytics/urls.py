from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AnalyticsTokenViewSet, SeriesView

router = DefaultRouter()
router.register("tokens", AnalyticsTokenViewSet, basename="analytics-token")

urlpatterns = [
    path("series/", SeriesView.as_view(), name="analytics-series"),
    path("", include(router.urls)),
]
