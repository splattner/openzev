from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    GridOperatorListView,
    GridOperatorSuggestionView,
    ParticipantGeocodingEnabledView,
    ZevViewSet,
    ParticipantViewSet,
    MeteringPointViewSet,
    MeteringPointAssignmentViewSet,
)

router = DefaultRouter()
router.register("zevs", ZevViewSet, basename="zev")
router.register("participants", ParticipantViewSet, basename="participant")
router.register("metering-points", MeteringPointViewSet, basename="meteringpoint")
router.register("metering-point-assignments", MeteringPointAssignmentViewSet, basename="meteringpointassignment")

urlpatterns = [
    path("grid-operators/", GridOperatorListView.as_view(), name="grid-operator-list"),
    path("grid-operators/suggest/", GridOperatorSuggestionView.as_view(), name="grid-operator-suggest"),
    path(
        "participants/geocoding-enabled/",
        ParticipantGeocodingEnabledView.as_view(),
        name="participant-geocoding-enabled",
    ),
] + router.urls
