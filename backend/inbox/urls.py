from rest_framework.routers import DefaultRouter

from .views import DocumentViewSet

router = DefaultRouter()
router.register("documents", DocumentViewSet, basename="inbox-document")

urlpatterns = router.urls
