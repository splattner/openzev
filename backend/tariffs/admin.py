from django.contrib import admin
from django.db import transaction

from .dynamic.models import DynamicPricePoint, DynamicTariffSource
from .models import Tariff, TariffPeriod


class TariffPeriodInline(admin.TabularInline):
    model = TariffPeriod
    extra = 1


@admin.register(Tariff)
class TariffAdmin(admin.ModelAdmin):
    list_display = ("name", "zev", "category", "billing_mode", "energy_type", "fixed_price_chf", "valid_from", "valid_to")
    list_filter = ("category", "billing_mode", "energy_type", "zev", "split_key")
    inlines = [TariffPeriodInline]

    def get_inlines(self, request, obj=None):
        if obj is not None and obj.dynamic_source_id:
            return []
        return self.inlines


@admin.register(TariffPeriod)
class TariffPeriodAdmin(admin.ModelAdmin):
    list_display = ("tariff", "period_type", "price_chf_per_kwh", "time_from", "time_to")


@admin.register(DynamicTariffSource)
class DynamicTariffSourceAdmin(admin.ModelAdmin):
    list_display = (
        "label", "tariff_type", "tariff_name", "api_version",
        "last_fetch_status", "last_success_at", "covers_from", "covers_to",
    )
    list_filter = ("api_version", "tariff_type", "last_fetch_status")
    search_fields = ("label", "url", "tariff_name")
    readonly_fields = (
        "last_fetch_status", "last_fetch_at", "last_success_at", "last_fetch_error",
        "covers_from", "covers_to", "created_at", "updated_at",
        "recovery_from",
    )

    def get_readonly_fields(self, request, obj=None):
        identity = ("url", "api_version", "tariff_type", "tariff_name") if obj else ()
        return self.readonly_fields + identity

    def has_delete_permission(self, request, obj=None):
        # Maintenance goes through the audited API and its source-row lock.
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change:
            return
        from .tasks import fetch_dynamic_prices

        source_id = str(obj.pk)
        transaction.on_commit(
            lambda: fetch_dynamic_prices.delay(source_id, backfill=True),
            robust=True,
        )


@admin.register(DynamicPricePoint)
class DynamicPricePointAdmin(admin.ModelAdmin):
    list_display = ("source", "valid_from", "valid_to", "price_chf_per_kwh")
    list_filter = ("source",)
    # A year of one series is 35 000 rows, so the default "show me everything"
    # changelist is not a useful entry point — arrive by date.
    date_hierarchy = "valid_from"
    readonly_fields = ("source", "valid_from", "valid_to", "price_chf_per_kwh")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
