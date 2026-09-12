"""Unauthenticated routes, mounted at ``/api/v1/public/``.

See ``invoices/urls_public.py`` for why these are kept in their own module.
"""
from django.urls import path

from .views_public import onboarding_consume

urlpatterns = [
    path("onboarding/consume/", onboarding_consume, name="onboarding-consume"),
]
