"""Shared WeasyPrint rendering helper.

All document PDFs (invoices, annual statements, financial summaries, contracts)
are rendered through :func:`render_pdf` so they share a single output format.

We emit **PDF/A-3b**: a long-term-archival format (relevant for Swiss GeBüV
retention) whose ``3`` level also permits embedding structured attachments,
keeping the door open for e-invoicing payloads (eBill / Factur-X style) next to
the existing QR-Rechnung. WeasyPrint adds the required XMP identification,
sRGB OutputIntent (with embedded ICC profile) and font subsets automatically.
"""
import threading

from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration
from weasyprint.urls import URLFetcher

# PDF/A-3b — see module docstring for the rationale behind this variant.
PDF_VARIANT = "pdf/a-3b"

# Every shipped PDF template is fully self-contained — inline CSS, inline SVG,
# no external references — so document rendering never needs a protocol beyond
# embedded data: URIs. Restricting the fetcher closes local-file reads
# (explicit file: URLs and relative URLs resolved against base_url) and
# outbound network calls (http/https/ftp) from admin-editable template content,
# for stored documents and the stateless preview alike. A rejected resource
# degrades like a missing one: WeasyPrint logs it and renders without it.
ALLOWED_URL_PROTOCOLS = ("data",)

class _ReusableFontConfiguration(FontConfiguration):
    """Track document font rules so they cannot leak into the next render."""

    has_document_fonts = False

    def add_font_face(self, rule_descriptors, url_fetcher):
        super().add_font_face(rule_descriptors, url_fetcher)
        # A new font invalidates fallback metrics cached by earlier documents.
        self.strut_layouts.clear()
        self.has_document_fonts = True


# Reuse system font caches; serialize access to the native Pango font map.
_process_font_config: _ReusableFontConfiguration | None = None
_font_lock = threading.Lock()


def render_pdf(html_string: str, *, base_url: str = ".") -> bytes:
    """Render an HTML string to PDF/A bytes."""
    global _process_font_config
    with _font_lock:
        if _process_font_config is None:
            _process_font_config = _ReusableFontConfiguration()
        font_config = _process_font_config
        try:
            return HTML(
                string=html_string,
                base_url=base_url,
                url_fetcher=URLFetcher(allowed_protocols=ALLOWED_URL_PROTOCOLS),
            ).write_pdf(pdf_variant=PDF_VARIANT, font_config=font_config)
        finally:
            # Admin-editable templates (including previews) may install
            # @font-face rules even though the shipped templates do not.
            if font_config.has_document_fonts:
                _process_font_config = None
