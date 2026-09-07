from django.urls import path

from .views import ExportJobDownloadView, ExportJobStatusView, ExportJobView

urlpatterns = [
    path("jobs/", ExportJobView.as_view(), name="export-job-create"),
    path("jobs/<uuid:pk>/", ExportJobStatusView.as_view(), name="export-job-status"),
    path("jobs/<uuid:pk>/download/", ExportJobDownloadView.as_view(), name="export-job-download"),
]
