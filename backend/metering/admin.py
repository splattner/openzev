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
    list_display = ("zev", "source", "filename", "rows_imported", "rows_skipped", "created_at")
    list_filter = ("source", "zev")
    readonly_fields = ("batch_id", "errors", "created_at")
