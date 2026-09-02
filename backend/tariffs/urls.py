from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import TariffViewSet, TariffPeriodViewSet
from .views_import import VseTariffImportApplyView, VseTariffImportPreviewView

router = DefaultRouter()
router.register("tariffs", TariffViewSet, basename="tariff")
router.register("periods", TariffPeriodViewSet, basename="tariff-period")

# Listed before the router so the import paths are not shadowed by the
# viewsets' detail routes.
urlpatterns = [
    path("imports/vse/preview/", VseTariffImportPreviewView.as_view(), name="vse-tariff-import-preview"),
    path("imports/vse/apply/", VseTariffImportApplyView.as_view(), name="vse-tariff-import-apply"),
] + router.urls
