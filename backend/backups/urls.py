from django.urls import path

from .views import (
    BackupDestinationDetailView,
    BackupDestinationListCreateView,
    BackupDestinationTestView,
    BackupJobDetailView,
    BackupJobDownloadView,
    BackupJobListCreateView,
    BackupStatusView,
)

urlpatterns = [
    path("destinations/", BackupDestinationListCreateView.as_view(), name="backup-destination-list"),
    path("destinations/<uuid:pk>/", BackupDestinationDetailView.as_view(), name="backup-destination-detail"),
    path("destinations/<uuid:pk>/test/", BackupDestinationTestView.as_view(), name="backup-destination-test"),
    path("jobs/", BackupJobListCreateView.as_view(), name="backup-job-list"),
    path("jobs/<uuid:pk>/", BackupJobDetailView.as_view(), name="backup-job-detail"),
    path("jobs/<uuid:pk>/download/", BackupJobDownloadView.as_view(), name="backup-job-download"),
    path("status/", BackupStatusView.as_view(), name="backup-status"),
]
