from django.urls import path

from .views import FeasibilityCalculateView, FeasibilityPrefillView, feasibility_calculator_enabled

urlpatterns = [
    path("enabled/", feasibility_calculator_enabled, name="feasibility-enabled"),
    path("calculate/", FeasibilityCalculateView.as_view(), name="feasibility-calculate"),
    path("prefill/<uuid:zev_id>/", FeasibilityPrefillView.as_view(), name="feasibility-prefill"),
]
