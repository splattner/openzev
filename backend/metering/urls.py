from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import MeterReadingViewSet, QuarantinedReadingViewSet, ImportLogViewSet, ImportView
from .live.views import LiveCurveView, LiveIngestView, LiveMeView, LiveSnapshotView
from .supplementary.views import SupplementaryIngestView, SupplementarySourceViewSet

router = DefaultRouter()
router.register("readings", MeterReadingViewSet, basename="meterreading")
router.register("held-readings", QuarantinedReadingViewSet, basename="quarantinedreading")
router.register("import-logs", ImportLogViewSet, basename="importlog")
router.register("import", ImportView, basename="import")
router.register("supplementary/sources", SupplementarySourceViewSet, basename="supplementary-source")

urlpatterns = [
    path("supplementary/ingest/", SupplementaryIngestView.as_view(), name="supplementary-ingest"),
    path("live/ingest/", LiveIngestView.as_view(), name="live-ingest"),
    path("live/me/", LiveMeView.as_view(), name="live-me"),
    path("live/zevs/<uuid:zev_id>/", LiveSnapshotView.as_view(), name="live-snapshot"),
    path("live/zevs/<uuid:zev_id>/curve/", LiveCurveView.as_view(), name="live-curve"),
    *router.urls,
]
