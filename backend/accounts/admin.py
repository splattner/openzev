from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (
        ("OpenZEV", {"fields": ("role", "phone", "address_line1", "address_line2", "postal_code", "city")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("OpenZEV", {"fields": ("role", "email", "first_name", "last_name")}),
    )
