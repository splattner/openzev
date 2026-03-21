from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import AppSettings, User, VatRate

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (
        ("OpenZEV", {"fields": ("role", "must_change_password")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("OpenZEV", {"fields": ("role", "email", "first_name", "last_name")}),
    )


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    list_display = ("date_format_short", "date_format_long", "date_time_format", "updated_at")


@admin.register(VatRate)
class VatRateAdmin(admin.ModelAdmin):
    list_display = ("rate", "valid_from", "valid_to", "updated_at")
    ordering = ("-valid_from", "-created_at")
