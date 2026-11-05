from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import DocumentViewSet, IssueAnnualStatementView, IssueFinancialSummaryView, IssueTariffOverviewView

router = DefaultRouter()
router.register("documents", DocumentViewSet, basename="inbox-document")

urlpatterns = [
    path("issue/annual-statement/", IssueAnnualStatementView.as_view(), name="inbox-issue-annual-statement"),
    path("issue/financial-summary/", IssueFinancialSummaryView.as_view(), name="inbox-issue-financial-summary"),
    path("issue/tariff-overview/", IssueTariffOverviewView.as_view(), name="inbox-issue-tariff-overview"),
    *router.urls,
]
