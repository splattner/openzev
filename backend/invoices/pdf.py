"""
PDF invoice generation using WeasyPrint.
The HTML template is rendered via Django's template engine, then
converted to PDF. Optionally embeds a Swiss QR-Rechnung.
"""
import io
import logging
from datetime import date

from accounts.models import AppSettings
from django.conf import settings
from django.core.files.base import ContentFile
from django.template import Context, Template
from django.template.loader import render_to_string
from tariffs.models import TariffCategory

from .dates import format_date_value
from .description_utils import strip_period_suffix
from .pdf_charts import (
    _build_energy_chart_svg,
    _build_energy_flow_svg,
    _build_hourly_profile_chart_svg,
)
from .pdf_render import render_pdf
from .pdf_stats import _build_energy_summary, _build_savings_data
from .pdf_translations import INVOICE_TRANSLATIONS

logger = logging.getLogger(__name__)

TEMPLATE_NAME = "invoices/invoice_pdf.html"


# Kept as an alias so existing callers (annual_statement, tasks,
# financial_summary) keep importing ``_format_date_value`` from here. The
# implementation is shared with the contract PDF via invoices/dates.py.
_format_date_value = format_date_value


def _normalize_text(value: str | None) -> str:
    return (value or "").strip()


def _build_qr_party(*, name: str | None, line1: str | None, postal_code: str | None, city: str | None, role: str):
    normalized = {
        "name": _normalize_text(name),
        "line1": _normalize_text(line1),
        "postal_code": _normalize_text(postal_code),
        "city": _normalize_text(city),
    }
    missing = [field for field, value in normalized.items() if not value]
    if missing:
        logger.warning(
            "Skipping QR-Rechnung generation: missing %s fields: %s",
            role,
            ", ".join(missing),
        )
        return None

    return {
        "name": normalized["name"],
        "street": normalized["line1"],
        "house_num": "",
        "pcode": normalized["postal_code"],
        "city": normalized["city"],
        "country": "CH",
    }


def _group_items_by_category(items, period_start: date, period_end: date, tr: dict):
    labels = {
        TariffCategory.ENERGY: tr["cat_energy"],
        TariffCategory.GRID_FEES: tr["cat_grid_fees"],
        TariffCategory.LEVIES: tr["cat_levies"],
        TariffCategory.METERING: tr["cat_metering"],
    }
    ordered_categories = [
        TariffCategory.ENERGY,
        TariffCategory.GRID_FEES,
        TariffCategory.LEVIES,
        TariffCategory.METERING,
    ]
    grouped = []
    for category in ordered_categories:
        category_items = [item for item in items if item.tariff_category == category]
        if not category_items:
            continue
        prepared_items = []
        for item in category_items:
            if item.unit == "month":
                unit_key = "unit_month_sg" if item.quantity_kwh == 1 else "unit_month_pl"
                unit_label = tr[unit_key]
            else:
                unit_label = item.unit
            prepared_items.append(
                {
                    "description": strip_period_suffix(item.description, period_start, period_end),
                    "quantity_kwh": item.quantity_kwh,
                    "unit": item.unit,
                    "unit_label": unit_label,
                    "unit_price_chf": item.unit_price_chf,
                    "total_chf": item.total_chf,
                }
            )
        grouped.append({
            "key": category,
            "label": labels[category],
            "items": prepared_items,
            "subtotal": sum(item.total_chf for item in category_items),
        })
    return grouped


def _build_qr_svg(invoice) -> str | None:
    """Generate the Swiss QR-Rechnung SVG if IBAN and required addresses are configured."""
    iban = _normalize_text(invoice.zev.bank_iban).replace(" ", "")
    if not iban:
        return None

    owner_participant = invoice.zev.participants.filter(user=invoice.zev.owner).first()
    creditor = _build_qr_party(
        name=owner_participant.full_name if owner_participant else invoice.zev.name,
        line1=owner_participant.address_line1 if owner_participant else "",
        postal_code=owner_participant.postal_code if owner_participant else "",
        city=owner_participant.city if owner_participant else "",
        role="creditor",
    )
    debtor = _build_qr_party(
        name=invoice.participant.full_name,
        line1=invoice.participant.address_line1,
        postal_code=invoice.participant.postal_code,
        city=invoice.participant.city,
        role="debtor",
    )
    if not creditor or not debtor:
        return None

    lang = invoice.zev.invoice_language or "de"

    try:
        from qrbill import QRBill
        bill = QRBill(
            account=iban,
            creditor=creditor,
            debtor=debtor,
            amount=str(invoice.total_chf),
            currency="CHF",
            language=lang,
            additional_information=invoice.invoice_number or "",
        )

        svg_binary = io.BytesIO()
        try:
            bill.as_svg(svg_binary)
            return svg_binary.getvalue().decode("utf-8")
        except TypeError:
            svg_text = io.StringIO()
            bill.as_svg(svg_text)
            return svg_text.getvalue()
    except Exception as exc:
        logger.warning("Skipping QR-Rechnung generation due to invalid QR data: %s", exc)
        return None


def _build_template_context(invoice) -> dict:
    qr_svg = _build_qr_svg(invoice)
    items = list(invoice.items.all())
    app_settings = AppSettings.load()
    owner_participant = invoice.zev.participants.filter(user=invoice.zev.owner).first()

    lang = invoice.zev.invoice_language or "de"
    # Copied rather than used in place: INVOICE_TRANSLATIONS is a module-level
    # constant shared by every invoice; notes_question (formatted with the
    # support e-mail) is resolved below, and writing it back into the shared
    # dict would mutate the constant for every later invoice in the process.
    tr = dict(INVOICE_TRANSLATIONS.get(lang, INVOICE_TRANSLATIONS["de"]))
    try:
        tr["notes_question"] = tr["notes_question"].format(email=settings.DEFAULT_FROM_EMAIL)
    except (KeyError, ValueError):
        pass  # keep the raw string if a translator removed the placeholder
    savings_data = _build_savings_data(invoice, tr)
    energy_summary = _build_energy_summary(invoice)

    # Split at the last hyphen so the numeric counter portion renders bold.
    # The hyphen stays with the prefix (e.g. "Q-00001" → prefix "Q-", suffix "00001").
    invoice_number = invoice.invoice_number or ""
    if "-" in invoice_number:
        raw_prefix, invoice_number_suffix = invoice_number.rsplit("-", 1)
        invoice_number_prefix = raw_prefix + "-"
    else:
        invoice_number_prefix = invoice_number
        invoice_number_suffix = ""

    grouped_items = _group_items_by_category(items, invoice.period_start, invoice.period_end, tr)
    # Total rendered rows: category headers + item rows (+ subtotals are one per group)
    total_table_rows = len(grouped_items) * 2 + len(items)

    # ── Content-based height estimate for inline QR decision ───────────────
    # These mm values are derived from the template CSS and serve as a fast
    # pre-filter only.  They assume single-line table rows, so wrapping
    # descriptions can make the real layout taller than estimated.  That drift
    # is harmless: generate_pdf() re-checks the *actual* rendered layout and
    # downgrades to the dedicated payment page if the body would overflow the
    # single page that inline mode requires (otherwise the running QR slip
    # would be duplicated on every body page).
    _HEADER_MM = 25
    _SUMMARY_SAVINGS_MM = 39
    _SUMMARY_NO_SAVINGS_MM = 34
    _TABLE_ROW_MM = 6.5
    _TABLE_HEADER_MM = 6.4
    _CLOSING_MM = 23
    _PAYMENT_MM = 14
    _AVAILABLE_MM = 176  # 297 - 12 (top pad) - 106 (QR) - 3 (safety)

    summary_mm = _SUMMARY_SAVINGS_MM if savings_data else _SUMMARY_NO_SAVINGS_MM
    content_mm = (
        _HEADER_MM + summary_mm + _TABLE_HEADER_MM
        + _TABLE_ROW_MM * total_table_rows
        + _CLOSING_MM + _PAYMENT_MM
    )

    return {
        "invoice": invoice,
        "invoice_number_prefix": invoice_number_prefix,
        "invoice_number_suffix": invoice_number_suffix,
        "grouped_items": grouped_items,
        "zev": invoice.zev,
        "owner_participant": owner_participant,
        "participant": invoice.participant,
        "qr_svg": qr_svg,
        # A short, note-free invoice can share its first page with the standard
        # QR payment part.  Larger invoices retain a separate final payment page
        # so their line items can never overlap the payment slip.  The height
        # estimate accounts for savings-card size and category row count.
        "inline_qr_payment": bool(
            qr_svg
            and content_mm <= _AVAILABLE_MM
            and not _normalize_text(invoice.notes)
        ),
        "energy_chart_svg": _build_energy_chart_svg(invoice, tr),
        "energy_flow_svg": _build_energy_flow_svg(invoice, tr),
        "hourly_profile_chart_svg": _build_hourly_profile_chart_svg(invoice, tr),
        "savings_data": savings_data,
        "energy_summary": energy_summary,
        "tr": tr,
        "status_display": tr.get("status_values", {}).get(invoice.status, invoice.status),
        "formatted_dates": {
            "invoice_date": _format_date_value(invoice.created_at, app_settings.date_format_short),
            "period_start": _format_date_value(invoice.period_start, app_settings.date_format_short),
            "period_end": _format_date_value(invoice.period_end, app_settings.date_format_short),
            "due_date": _format_date_value(invoice.due_date, app_settings.date_format_short),
        },
    }


def _find_qr_clip_rect(page):
    """Return the QR-Rechnung clip rect on a PDF page, or ``None``.

    Both the inline (``position: running``) and the dedicated payment-page
    layouts emit a full-width ``re`` + ``W`` clip pair for the 106 mm slip at
    the bottom of the page.  Coordinates are CSS px at 96 DPI with WeasyPrint's
    standard 0.75 scale and Y-flip.  Shared by the runtime guard below and the
    integration tests so the detection logic lives in one place.
    """
    content = page.get_contents()
    if content is None:
        return None
    ops = content.operations
    mediabox = page.mediabox
    page_h_css = (float(mediabox[3]) - float(mediabox[1])) / 0.75

    for i, (params, op) in enumerate(ops):
        if op != b"re" or len(params) < 4:
            continue
        _x, y, w, h = (float(p) for p in params[:4])
        # QR rect is full-width (≥700 CSS px) and full slip height (≥300 CSS px)
        if w < 700 or h < 300:
            continue
        # QR rect must sit in the lower half of the page
        if y < page_h_css / 2:
            continue
        if i + 1 >= len(ops) or ops[i + 1][1] != b"W":
            continue
        return y, h, page_h_css
    return None


def _count_qr_slips(pdf_bytes: bytes) -> int:
    """Count pages that carry a QR-Rechnung slip in the rendered PDF."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return sum(1 for page in reader.pages if _find_qr_clip_rect(page) is not None)


def _render_template(template_name: str, context: dict) -> str:
    """Render a template from DB if customized, otherwise from the on-disk default."""
    # Import here to avoid circular imports at module load time
    from .models import PdfTemplate
    record = PdfTemplate.objects.filter(template_name=template_name).first()
    if record:
        return Template(record.content).render(Context(context))
    return render_to_string(template_name, context)


def generate_pdf(invoice) -> bytes:
    """Render the invoice to PDF bytes.

    The inline-QR layout reserves the 106 mm payment slip in the bottom margin
    of *every* page the invoice body spans.  Inline mode is therefore only
    valid when the body fits on a single page.  The height estimate in
    :func:`_build_template_context` is a fast pre-filter but can under-count
    when line-item descriptions wrap onto multiple lines; in that case the
    body overflows and the running slip would be duplicated.  We detect that
    on the real rendered layout (slip on more than one page) and fall back to
    the dedicated payment page, which always places a single slip on its own
    final page regardless of body length.
    """
    context = _build_template_context(invoice)
    html_string = _render_template(TEMPLATE_NAME, context)
    pdf_bytes = render_pdf(html_string)

    if context.get("inline_qr_payment") and _count_qr_slips(pdf_bytes) > 1:
        logger.info(
            "Invoice %s: inline QR would duplicate across pages; "
            "falling back to dedicated payment page",
            invoice.invoice_number,
        )
        context["inline_qr_payment"] = False
        html_string = _render_template(TEMPLATE_NAME, context)
        pdf_bytes = render_pdf(html_string)

    return pdf_bytes


def save_invoice_pdf(invoice) -> None:
    """Generate PDF and attach it to the Invoice model."""
    pdf_bytes = generate_pdf(invoice)
    filename = f"invoice_{invoice.invoice_number}.pdf"
    invoice.pdf_file.save(filename, ContentFile(pdf_bytes), save=True)
    logger.info("Saved PDF for invoice %s", invoice.invoice_number)
