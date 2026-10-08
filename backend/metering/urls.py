from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import MeterReadingViewSet, ImportLogViewSet, ImportView
from .supplementary.views import SupplementaryIngestView, SupplementarySourceViewSet

router = DefaultRouter()
router.register("readings", MeterReadingViewSet, basename="meterreading")
router.register("import-logs", ImportLogViewSet, basename="importlog")
router.register("import", ImportView, basename="import")
router.register("supplementary/sources", SupplementarySourceViewSet, basename="supplementary-source")

urlpatterns = [
    path("supplementary/ingest/", SupplementaryIngestView.as_view(), name="supplementary-ingest"),
    *router.urls,
]
