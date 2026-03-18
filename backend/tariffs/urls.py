from rest_framework.routers import DefaultRouter
from .views import TariffViewSet, TariffPeriodViewSet

router = DefaultRouter()
router.register("tariffs", TariffViewSet, basename="tariff")
router.register("periods", TariffPeriodViewSet, basename="tariff-period")

urlpatterns = router.urls
