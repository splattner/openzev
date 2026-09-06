"""Regression tests guarding the PDF/A output format.

All document PDFs are rendered through ``invoices.pdf_render.render_pdf`` which
emits PDF/A-3b. WeasyPrint writes the PDF/A identification (XMP ``pdfaid``), the
sRGB ``OutputIntent`` and embedded font subsets automatically — these tests make
sure nobody silently drops the ``pdf_variant`` argument.
"""
import base64
import re
import zlib
from datetime import date
from decimal import Decimal
from pathlib import Path

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


@pytest.mark.slow
def _test_font_data_url():
    """A real TTF embedded as a data: URL for the font-isolation test."""
    candidates = (
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            encoded = base64.b64encode(Path(candidate).read_bytes()).decode("ascii")
            return f"data:font/ttf;base64,{encoded}"
    pytest.skip("no system TTF font available for the font-isolation test")


@pytest.mark.slow
@pytest.mark.parametrize("fonttools_subset", [False, True], ids=["default", "fonttools"])
def test_custom_font_does_not_change_other_documents(monkeypatch, fonttools_subset):
    """Installing an @font-face must invalidate cached strut metrics.

    Strut layouts are cached per font style, so a key stored while the
    family was unknown would keep serving fallback metrics after the font
    arrives — shifting line positions in the font document itself. Plain
    documents before and after must render identically, and the warmed-cache
    font document must match a fresh-cache one.
    """
    from weasyprint.pdf import fonts

    from . import pdf_render

    if fonttools_subset:
        monkeypatch.setattr(fonts, "harfbuzz_subset", None)

    # FontTools timestamps embedded subsets at save time. Pin that metadata
    # so renders crossing a wall-clock second still compare byte-for-byte.
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1704067200")
    data_url = _test_font_data_url()
    plain = (
        "<style>p {font-family: ReviewFont, monospace}</style>"
        "<p>Invoice 123<br>second line<br>third line</p>"
    )
    font_doc = (
        "<style>@font-face {font-family: ReviewFont; "
        f'src: url("{data_url}")}}</style>' + plain
    )

    monkeypatch.setattr(pdf_render, "_process_font_config", None)
    first_plain = render_pdf(plain)
    warmed_font_doc = render_pdf(font_doc)
    assert pdf_render._process_font_config is None
    assert render_pdf(plain) == first_plain

    monkeypatch.setattr(pdf_render, "_process_font_config", None)
    assert render_pdf(font_doc) == warmed_font_doc
    assert render_pdf(plain) == first_plain
