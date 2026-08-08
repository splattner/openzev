from django.urls import path

from .views import AuditEventDetailView, AuditEventFilterOptionsView, AuditEventListView


urlpatterns = [
    path("events/", AuditEventListView.as_view(), name="audit-event-list"),
    path("events/filter-options/", AuditEventFilterOptionsView.as_view(), name="audit-event-filter-options"),
    path("events/<uuid:pk>/", AuditEventDetailView.as_view(), name="audit-event-detail"),
]
