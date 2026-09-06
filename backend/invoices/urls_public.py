"""Unauthenticated routes, mounted at ``/api/v1/public/``.

Kept in their own module and under their own URL prefix so that "this is
served without a login" is visible in the routing table, rather than a
property you discover by opening the view and reading its permission class.
"""
from django.urls import path

from .views_public import (
    magic_link_consume,
    magic_link_request,
    public_invoice,
    public_invoice_pdf,
)

urlpatterns = [
    path("invoices/<str:prefix>/", public_invoice, name="public-invoice"),
    path("invoices/<str:prefix>/pdf/", public_invoice_pdf, name="public-invoice-pdf"),
    path("magic-link/request/", magic_link_request, name="magic-link-request"),
    path("magic-link/consume/", magic_link_consume, name="magic-link-consume"),
]
