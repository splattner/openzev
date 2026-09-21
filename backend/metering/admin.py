from django.contrib import admin
from .models import MeterReading, ImportLog


@admin.register(MeterReading)
class MeterReadingAdmin(admin.ModelAdmin):
    list_display = ("metering_point", "timestamp", "direction", "energy_kwh", "resolution", "import_source")
    list_filter = ("direction", "resolution", "import_source")
    search_fields = ("metering_point__meter_id",)
    date_hierarchy = "timestamp"


@admin.register(ImportLog)
class ImportLogAdmin(admin.ModelAdmin):
    # Import logs are operational history: deletion (with its overwrite
    # protection and batch cleanup) happens through the application's
    # protected workflow, not through the admin.
    list_display = ("zev", "source", "filename", "rows_imported", "rows_skipped", "created_at")
    list_filter = ("source", "zev")
    readonly_fields = (
        "zev",
        "imported_by",
        "source",
        "filename",
        "batch_id",
        "rows_total",
        "rows_imported",
        "rows_overwritten",
        "rows_skipped",
        "errors",
        "warnings",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
