from django.contrib import admin
from .models import Zev, Participant, MeteringPoint


class ParticipantInline(admin.TabularInline):
    model = Participant
    extra = 0
    show_change_link = True
    fields = ("first_name", "last_name", "email", "valid_from", "valid_to")


class MeteringPointInline(admin.TabularInline):
    model = MeteringPoint
    extra = 0
    fields = ("meter_id", "meter_type", "is_active", "valid_from", "valid_to")


@admin.register(Zev)
class ZevAdmin(admin.ModelAdmin):
    list_display = ("name", "zev_type", "owner", "billing_interval")
    list_filter = ("zev_type", "billing_interval")
    search_fields = ("name", "grid_operator")
    inlines = [ParticipantInline]


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("full_name", "zev", "email", "valid_from", "valid_to")
    list_filter = ("zev",)
    search_fields = ("first_name", "last_name", "email")
    inlines = [MeteringPointInline]


@admin.register(MeteringPoint)
class MeteringPointAdmin(admin.ModelAdmin):
    list_display = ("meter_id", "participant", "meter_type", "is_active")
    list_filter = ("meter_type", "is_active")
    search_fields = ("meter_id",)
