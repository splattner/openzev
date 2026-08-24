"""Shared WeasyPrint rendering helper.

All document PDFs (invoices, annual statements, financial summaries, contracts)
are rendered through :func:`render_pdf` so they share a single output format.

We emit **PDF/A-3b**: a long-term-archival format (relevant for Swiss GeBüV
retention) whose ``3`` level also permits embedding structured attachments,
keeping the door open for e-invoicing payloads (eBill / Factur-X style) next to
the existing QR-Rechnung. WeasyPrint adds the required XMP identification,
sRGB OutputIntent (with embedded ICC profile) and font subsets automatically.
"""
from weasyprint import HTML
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


def render_pdf(html_string: str, *, base_url: str = ".") -> bytes:
    """Render an HTML string to PDF/A bytes."""
    # A fresh fetcher per call: URLFetcher keeps transient per-request state,
    # so one shared instance would race across concurrent renders.
    fetcher = URLFetcher(allowed_protocols=ALLOWED_URL_PROTOCOLS)
    return HTML(string=html_string, base_url=base_url, url_fetcher=fetcher).write_pdf(pdf_variant=PDF_VARIANT)
