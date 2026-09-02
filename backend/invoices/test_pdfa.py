"""Regression tests guarding the PDF/A output format.

All document PDFs are rendered through ``invoices.pdf_render.render_pdf`` which
emits PDF/A-3b. WeasyPrint writes the PDF/A identification (XMP ``pdfaid``), the
sRGB ``OutputIntent`` and embedded font subsets automatically — these tests make
sure nobody silently drops the ``pdf_variant`` argument.
"""
import re
import zlib
from datetime import date
from decimal import Decimal

from django.test import TestCase

import pytest

from accounts.models import User, UserRole
from tariffs.models import TariffCategory
from zev.models import Participant, Zev
from .models import Invoice, InvoiceItem
from .pdf import generate_pdf
from .pdf_render import render_pdf


def _inflate_all(pdf_bytes: bytes) -> bytes:
    """Return the raw bytes plus every zlib-inflated stream.

    PDF/A-3b stores metadata in compressed object streams, so the markers are
    only visible after decompression.
    """
    blob = pdf_bytes
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf_bytes, re.S):
        try:
            blob += zlib.decompress(match.group(1))
        except zlib.error:
            continue
    return blob


def assert_is_pdfa(test: TestCase, pdf_bytes: bytes) -> None:
    test.assertTrue(pdf_bytes.startswith(b"%PDF-1.7"), "expected a PDF-1.7 header")
    whole = _inflate_all(pdf_bytes)
    test.assertIn(b"pdfaid", whole, "missing PDF/A identification metadata")
    test.assertIn(b"OutputIntent", whole, "missing PDF/A OutputIntent")


class RenderPdfVariantTests(TestCase):
    def test_render_pdf_emits_pdfa(self):
        html = (
            "<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'>"
            "<title>T</title></head><body><p>Rechnung Zürich</p></body></html>"
        )
        assert_is_pdfa(self, render_pdf(html))


class InvoicePdfaTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="pdfa_owner", password="pass1234", role=UserRole.ZEV_OWNER
        )
        self.zev = Zev.objects.create(
            name="PDFA ZEV",
            owner=self.owner,
            zev_type="vzev",
            start_date=date(2026, 1, 1),
            billing_interval="monthly",
            invoice_prefix="Q",
            bank_iban="CH9300762011623852957",
            invoice_language="de",
        )
        Participant.objects.create(
            zev=self.zev,
            user=self.owner,
            first_name="Test",
            last_name="Owner",
            email="owner@example.com",
            address_line1="Bahnhofstrasse 1",
            postal_code="8001",
            city="Zürich",
            valid_from=date(2026, 1, 1),
        )
        self.participant = Participant.objects.create(
            zev=self.zev,
            first_name="Alice",
            last_name="Müster",
            email="alice@example.com",
            address_line1="Musterweg 3",
            postal_code="3000",
            city="Bern",
            valid_from=date(2026, 1, 1),
        )

    @pytest.mark.slow
    def test_generated_invoice_pdf_is_pdfa(self):
        invoice = Invoice.objects.create(
            invoice_number="Q-00001",
            zev=self.zev,
            participant=self.participant,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            total_chf=Decimal("42.00"),
            total_local_kwh=Decimal("100"),
            total_grid_kwh=Decimal("50"),
            due_date=date(2026, 2, 28),
        )
        InvoiceItem.objects.create(
            invoice=invoice,
            item_type=InvoiceItem.ItemType.LOCAL_ENERGY,
            tariff_category=TariffCategory.ENERGY,
            description="Energie",
            quantity_kwh=Decimal("100"),
            unit="kWh",
            unit_price_chf=Decimal("0.20"),
            total_chf=Decimal("20.00"),
        )

        assert_is_pdfa(self, generate_pdf(invoice))
