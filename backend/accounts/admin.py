from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm
from .models import AppSettings, User, VatRate
from .passwords import recover_password


class IndependentPasswordChangeForm(AdminPasswordChangeForm):
    """Trusted recovery on save(); commit=False only stages Django's password write."""

    def save(self, commit=True):
        if commit:
            password = (
                self.cleaned_data["password1"] if self.cleaned_data["set_usable_password"] else None
            )
            self.user = recover_password(self.user, password)
            return self.user
        return super().save(commit=False)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    change_password_form = IndependentPasswordChangeForm
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
