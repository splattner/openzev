from django.contrib import admin

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


@admin.register(TariffPeriod)
class TariffPeriodAdmin(admin.ModelAdmin):
    list_display = ("tariff", "period_type", "price_chf_per_kwh", "time_from", "time_to")


@admin.register(DynamicTariffSource)
class DynamicTariffSourceAdmin(admin.ModelAdmin):
    list_display = (
        "label", "tariff_type", "tariff_name", "adapter",
        "last_fetch_status", "last_success_at", "covers_from", "covers_to",
    )
    list_filter = ("adapter", "tariff_type", "last_fetch_status")
    search_fields = ("label", "url", "tariff_name")
    readonly_fields = (
        "last_fetch_status", "last_fetch_at", "last_success_at", "last_fetch_error",
        "covers_from", "covers_to", "created_at", "updated_at",
    )


@admin.register(DynamicPricePoint)
class DynamicPricePointAdmin(admin.ModelAdmin):
    list_display = ("source", "valid_from", "valid_to", "price_chf_per_kwh")
    list_filter = ("source",)
    # A year of one series is 35 000 rows, so the default "show me everything"
    # changelist is not a useful entry point — arrive by date.
    date_hierarchy = "valid_from"
