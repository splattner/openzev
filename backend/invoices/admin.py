from django.contrib import admin
from .models import Credit, Invoice, InvoiceItem, EmailLog, Payment


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    readonly_fields = ("total_chf",)


class EmailLogInline(admin.TabularInline):
    model = EmailLog
    extra = 0
    readonly_fields = ("sent_at", "status", "error_message")


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("amount_chf", "paid_on", "note", "source", "created_by", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        # Payments go through the workflow, which keeps the status in step.
        return False


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "participant", "zev", "period_start", "period_end", "total_chf", "status")
    list_filter = ("status", "zev")
    search_fields = ("invoice_number", "participant__party__first_name", "participant__party__last_name", "participant__party__organisation_name")
    inlines = [InvoiceItemInline, PaymentInline, EmailLogInline]
    readonly_fields = ("invoice_number", "approved_at", "created_at", "updated_at")
    date_hierarchy = "period_end"


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ("invoice", "item_type", "quantity_kwh", "unit_price_chf", "total_chf")


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ("invoice", "recipient", "status", "sent_at")
    readonly_fields = ("created_at",)


@admin.register(Credit)
class CreditAdmin(admin.ModelAdmin):
    """Credit notes are issued by the correction workflow and never edited."""

    list_display = ("credit_number", "kind", "participant", "zev", "source_invoice", "amount_chf", "created_at")
    list_filter = ("kind", "zev")
    search_fields = ("credit_number", "source_invoice__invoice_number")
    date_hierarchy = "created_at"

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
