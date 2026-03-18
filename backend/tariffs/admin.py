from django.contrib import admin
from .models import Tariff, TariffPeriod


class TariffPeriodInline(admin.TabularInline):
    model = TariffPeriod
    extra = 1


@admin.register(Tariff)
class TariffAdmin(admin.ModelAdmin):
    list_display = ("name", "zev", "category", "billing_mode", "energy_type", "fixed_price_chf", "valid_from", "valid_to")
    list_filter = ("category", "billing_mode", "energy_type", "zev")
    inlines = [TariffPeriodInline]


@admin.register(TariffPeriod)
class TariffPeriodAdmin(admin.ModelAdmin):
    list_display = ("tariff", "period_type", "price_chf_per_kwh", "time_from", "time_to")
