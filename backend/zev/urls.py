from django.urls import path
from rest_framework.routers import DefaultRouter
from .views_access import ZevAccessDetailView, ZevAccessListView, ZevAccessResendInvitationView
from .views import (
    GridOperatorListView,
    GridOperatorSuggestionView,
    ParticipantGeocodingEnabledView,
    ZevViewSet,
    ParticipantViewSet,
    BuildingViewSet,
    PartyViewSet,
    ZevPartyRoleViewSet,
    MeteringPointViewSet,
    MeteringPointAssignmentViewSet,
)

router = DefaultRouter()
router.register("zevs", ZevViewSet, basename="zev")
router.register("participants", ParticipantViewSet, basename="participant")
router.register("buildings", BuildingViewSet, basename="building")
router.register("parties", PartyViewSet, basename="party")
router.register("party-roles", ZevPartyRoleViewSet, basename="partyrole")
router.register("metering-points", MeteringPointViewSet, basename="meteringpoint")
router.register("metering-point-assignments", MeteringPointAssignmentViewSet, basename="meteringpointassignment")

urlpatterns = [
    path("grid-operators/", GridOperatorListView.as_view(), name="grid-operator-list"),
    path("grid-operators/suggest/", GridOperatorSuggestionView.as_view(), name="grid-operator-suggest"),
    path("zevs/<uuid:zev_id>/access/", ZevAccessListView.as_view(), name="zev-access-list"),
    path("zevs/<uuid:zev_id>/access/<uuid:pk>/", ZevAccessDetailView.as_view(), name="zev-access-detail"),
    path(
        "zevs/<uuid:zev_id>/access/<uuid:pk>/resend-invitation/",
        ZevAccessResendInvitationView.as_view(),
        name="zev-access-resend-invitation",
    ),
    path(
        "participants/geocoding-enabled/",
        ParticipantGeocodingEnabledView.as_view(),
        name="participant-geocoding-enabled",
    ),
] + router.urls
