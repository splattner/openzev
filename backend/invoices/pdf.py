"""
PDF invoice generation using WeasyPrint.
The HTML template is rendered via Django's template engine, then
converted to PDF. Optionally embeds a Swiss QR-Rechnung.
"""
import io
import logging
from pathlib import Path
from datetime import date, datetime

from django.template.loader import render_to_string
from django.core.files.base import ContentFile
from django.utils import timezone
from accounts.models import AppSettings
from weasyprint import HTML, CSS
from tariffs.models import TariffCategory
from .description_utils import strip_period_suffix

logger = logging.getLogger(__name__)

TEMPLATE_NAME = "invoices/invoice_pdf.html"


def _format_date_value(value: date | datetime | None, pattern: str) -> str:
    if value is None:
        return ""

    if isinstance(value, datetime):
        value = timezone.localtime(value).date() if timezone.is_aware(value) else value.date()

    day = f"{value.day:02d}"
    month = f"{value.month:02d}"
    year = str(value.year)

    if pattern == AppSettings.SHORT_DATE_DD_MM_YYYY:
        return f"{day}.{month}.{year}"
    if pattern == AppSettings.SHORT_DATE_DD_SLASH_MM_SLASH_YYYY:
        return f"{day}/{month}/{year}"
    if pattern == AppSettings.SHORT_DATE_MM_SLASH_DD_SLASH_YYYY:
        return f"{month}/{day}/{year}"
    if pattern == AppSettings.SHORT_DATE_YYYY_MM_DD:
        return f"{year}-{month}-{day}"
    return value.isoformat()


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


def _group_items_by_category(items, period_start: date, period_end: date):
    labels = {
        TariffCategory.ENERGY: "Energy",
        TariffCategory.GRID_FEES: "Grid Fees",
        TariffCategory.LEVIES: "Levies",
    }
    ordered_categories = [
        TariffCategory.ENERGY,
        TariffCategory.GRID_FEES,
        TariffCategory.LEVIES,
    ]
    grouped = []
    for category in ordered_categories:
        category_items = [item for item in items if item.tariff_category == category]
        if not category_items:
            continue
        prepared_items = []
        for item in category_items:
            prepared_items.append(
                {
                    "description": strip_period_suffix(item.description, period_start, period_end),
                    "quantity_kwh": item.quantity_kwh,
                    "unit": item.unit,
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

    creditor_city = _normalize_text(getattr(invoice.zev.owner, "city", ""))

    creditor = _build_qr_party(
        name=invoice.zev.name,
        line1=invoice.zev.address_line1,
        postal_code=invoice.zev.postal_code,
        city=creditor_city,
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

    try:
        from qrbill import QRBill
        bill = QRBill(
            account=iban,
            creditor=creditor,
            debtor=debtor,
            amount=str(invoice.total_chf),
            currency="CHF",
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
    creditor_city = _normalize_text(getattr(invoice.zev.owner, "city", ""))

    return {
        "invoice": invoice,
        "items": items,
        "grouped_items": _group_items_by_category(items, invoice.period_start, invoice.period_end),
        "zev": invoice.zev,
        "creditor_city": creditor_city,
        "participant": invoice.participant,
        "qr_svg": qr_svg,
        "formatted_dates": {
            "invoice_date": _format_date_value(invoice.created_at, app_settings.date_format_short),
            "period_start": _format_date_value(invoice.period_start, app_settings.date_format_short),
            "period_end": _format_date_value(invoice.period_end, app_settings.date_format_short),
            "due_date": _format_date_value(invoice.due_date, app_settings.date_format_short),
        },
    }


def generate_pdf(invoice) -> bytes:
    """Render the invoice to PDF bytes."""
    html_string = render_to_string(TEMPLATE_NAME, _build_template_context(invoice))
    pdf_bytes = HTML(string=html_string, base_url=".").write_pdf()
    return pdf_bytes


def save_invoice_pdf(invoice) -> None:
    """Generate PDF and attach it to the Invoice model."""
    pdf_bytes = generate_pdf(invoice)
    filename = f"invoice_{invoice.invoice_number}.pdf"
    invoice.pdf_file.save(filename, ContentFile(pdf_bytes), save=True)
    logger.info("Saved PDF for invoice %s", invoice.invoice_number)
