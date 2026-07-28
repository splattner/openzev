from rest_framework.routers import DefaultRouter
from .views import MeterReadingViewSet, ImportLogViewSet, ImportView

router = DefaultRouter()
router.register("readings", MeterReadingViewSet, basename="meterreading")
router.register("import-logs", ImportLogViewSet, basename="importlog")
router.register("import", ImportView, basename="import")

urlpatterns = router.urls
