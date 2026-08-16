from django.urls import path, re_path
from rest_framework.routers import DefaultRouter
from rest_framework.urlpatterns import format_suffix_patterns

from .annual_statement import ANNUAL_STATEMENT_TEMPLATE
from .contract_pdf import CONTRACT_TEMPLATE_NAME
from .pdf import TEMPLATE_NAME
from .views import InvoiceViewSet
from .views_dashboard import InvoiceDashboardView
from .views_reports import (
    AnnualStatementsZipView,
    AnnualStatementView,
    FinancialSummaryView,
)
from .views_templates import (
    EmailTemplateListView,
    EmailTemplateView,
    PdfTemplatePreviewView,
    PdfTemplateView,
)

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")

# These endpoints used to be @action methods on InvoiceViewSet. They are listed
# explicitly here — ahead of router.urls, so they win over the viewset's
# `invoices/<pk>/` detail route — which keeps their URLs byte-identical to what
# the router generated for them.
extracted_urlpatterns = [
    path("invoices/dashboard/", InvoiceDashboardView.as_view(), name="invoice-dashboard"),
    path("invoices/annual-statement/", AnnualStatementView.as_view(), name="invoice-annual-statement"),
    path("invoices/annual-statements-zip/", AnnualStatementsZipView.as_view(), name="invoice-annual-statements-zip"),
    path("invoices/financial-summary/", FinancialSummaryView.as_view(), name="invoice-financial-summary"),
    path(
        "invoices/pdf-template/",
        PdfTemplateView.as_view(
            template_name=TEMPLATE_NAME, audit_action_prefix="template.invoice_pdf", template_type="invoice"
        ),
        name="invoice-pdf-template",
    ),
    path(
        "invoices/contract-pdf-template/",
        PdfTemplateView.as_view(
            template_name=CONTRACT_TEMPLATE_NAME,
            audit_action_prefix="template.contract_pdf",
            template_type="contract",
        ),
        name="invoice-contract-pdf-template",
    ),
    path(
        "invoices/annual-statement-pdf-template/",
        PdfTemplateView.as_view(
            template_name=ANNUAL_STATEMENT_TEMPLATE,
            audit_action_prefix="template.annual_statement_pdf",
            template_type="annual_statement",
        ),
        name="invoice-annual-statement-pdf-template",
    ),
    path("invoices/preview-pdf-template/", PdfTemplatePreviewView.as_view(), name="invoice-preview-pdf-template"),
    path("invoices/email-templates/", EmailTemplateListView.as_view(), name="invoice-email-templates"),
    re_path(
        r"^invoices/email-template/(?P<template_key>[a-z_]+)/$",
        EmailTemplateView.as_view(),
        name="invoice-email-template",
    ),
]

# format_suffix_patterns restores the `.json`/`.api` variants the router used to
# generate for these endpoints, so the extraction removes no URL at all.
urlpatterns = format_suffix_patterns(extracted_urlpatterns) + router.urls
