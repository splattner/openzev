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
from .models import Invoice

# ── Invoice translations ───────────────────────────────────────────────────────
INVOICE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        "invoice_label": "Rechnung",
        "invoice_date": "Rechnungsdatum",
        "billing_period": "Abrechnungsperiode",
        "status": "Status",
        "due_date": "F\u00e4lligkeitsdatum",
        "from": "Von",
        "to": "An",
        "description": "Beschreibung",
        "qty": "Menge",
        "unit": "Einheit",
        "unit_price": "Einzelpreis (CHF)",
        "amount": "Betrag (CHF)",
        "subtotal": "Subtotal",
        "vat": "MwSt.",
        "total": "Total",
        "payment_terms_label": "Zahlungsbedingungen:",
        "payment_terms_text": "Zahlbar innert 30 Tagen ab Rechnungsdatum",
        "bank_details": "Bankverbindung:",
        "currency": "W\u00e4hrung: CHF",
        "reference_prefix": "Referenz: Rechnung",
        "slip_header": "\u2702 EINZAHLUNGSSCHEIN (F\u00fcr Ihre Unterlagen behalten)",
        "slip_invoice_details": "Rechnungsdetails",
        "slip_invoice_nr": "Rechnungs-Nr.:",
        "slip_date": "Datum:",
        "slip_period": "Periode:",
        "slip_amount_due": "F\u00e4lliger Betrag: CHF",
        "slip_participant": "Teilnehmer",
        "slip_email": "E-Mail:",
        "slip_remit_to": "Zahlung an",
        "slip_ocr": "OCR/Referenz:",
        "chart_title": "Energieverbrauch \u2014 Periodenvergleich",
        "chart_description": "Lokale ZEV-Produktion vs. Netzbezug f\u00fcr die Abrechnungsperiode, verglichen mit \u00e4quivalenten Perioden fr\u00fcherer Jahre.",
        "chart_from_zev": "Aus ZEV (lokale Prod.)",
        "chart_from_grid": "Aus dem Netz",
        "chart_current": "(aktuell)",
        "cat_energy": "Energie",
        "cat_grid_fees": "Netzgeb\u00fchren",
        "cat_levies": "Abgaben",
        "unit_month": "Monat",
        "page_label": "Seite",
        "page_of": "von",
    },
    "fr": {
        "invoice_label": "Facture",
        "invoice_date": "Date de facturation",
        "billing_period": "P\u00e9riode de facturation",
        "status": "Statut",
        "due_date": "Date d\u2019\u00e9ch\u00e9ance",
        "from": "De",
        "to": "\u00c0",
        "description": "Description",
        "qty": "Qt\u00e9",
        "unit": "Unit\u00e9",
        "unit_price": "Prix unitaire (CHF)",
        "amount": "Montant (CHF)",
        "subtotal": "Sous-total",
        "vat": "TVA",
        "total": "Total",
        "payment_terms_label": "Conditions de paiement\u202f:",
        "payment_terms_text": "Payable dans les 30 jours \u00e0 compter de la date de facturation",
        "bank_details": "Coordonn\u00e9es bancaires\u202f:",
        "currency": "Devise\u202f: CHF",
        "reference_prefix": "R\u00e9f\u00e9rence\u202f: Facture",
        "slip_header": "\u2702 BULLETIN DE VERSEMENT (\u00c0 conserver pour vos archives)",
        "slip_invoice_details": "D\u00e9tails de la facture",
        "slip_invoice_nr": "Facture n\u00b0\u202f:",
        "slip_date": "Date\u202f:",
        "slip_period": "P\u00e9riode\u202f:",
        "slip_amount_due": "Montant d\u00fb\u202f: CHF",
        "slip_participant": "Participant",
        "slip_email": "E-mail\u202f:",
        "slip_remit_to": "Payer \u00e0",
        "slip_ocr": "OCR/R\u00e9f\u00e9rence\u202f:",
        "chart_title": "Consommation d\u2019\u00e9nergie \u2014 Comparaison de p\u00e9riodes",
        "chart_description": "Production locale ZEV vs importation r\u00e9seau pour cette p\u00e9riode de facturation, compar\u00e9e aux p\u00e9riodes \u00e9quivalentes des ann\u00e9es pr\u00e9c\u00e9dentes.",
        "chart_from_zev": "Depuis ZEV (prod. locale)",
        "chart_from_grid": "Depuis le r\u00e9seau",
        "chart_current": "(actuel)",
        "cat_energy": "\u00c9nergie",
        "cat_grid_fees": "Frais de r\u00e9seau",
        "cat_levies": "Taxes",
        "unit_month": "mois",
        "page_label": "Page",
        "page_of": "de",
    },
    "it": {
        "invoice_label": "Fattura",
        "invoice_date": "Data fattura",
        "billing_period": "Periodo di fatturazione",
        "status": "Stato",
        "due_date": "Data di scadenza",
        "from": "Da",
        "to": "A",
        "description": "Descrizione",
        "qty": "Qt\u00e0",
        "unit": "Unit\u00e0",
        "unit_price": "Prezzo unitario (CHF)",
        "amount": "Importo (CHF)",
        "subtotal": "Subtotale",
        "vat": "IVA",
        "total": "Totale",
        "payment_terms_label": "Condizioni di pagamento:",
        "payment_terms_text": "Pagabile entro 30 giorni dalla data fattura",
        "bank_details": "Coordinate bancarie:",
        "currency": "Valuta: CHF",
        "reference_prefix": "Riferimento: Fattura",
        "slip_header": "\u2702 DISTINTA DI VERSAMENTO (Conservare per i propri archivi)",
        "slip_invoice_details": "Dettagli fattura",
        "slip_invoice_nr": "Fattura n.:",
        "slip_date": "Data:",
        "slip_period": "Periodo:",
        "slip_amount_due": "Importo dovuto: CHF",
        "slip_participant": "Partecipante",
        "slip_email": "E-mail:",
        "slip_remit_to": "Rimettere pagamento a",
        "slip_ocr": "OCR/Riferimento:",
        "chart_title": "Consumo energetico \u2014 Confronto periodi",
        "chart_description": "Produzione locale ZEV vs importazione rete per il periodo di fatturazione, confrontata con i periodi equivalenti degli anni precedenti.",
        "chart_from_zev": "Da ZEV (prod. locale)",
        "chart_from_grid": "Dalla rete",
        "chart_current": "(attuale)",
        "cat_energy": "Energia",
        "cat_grid_fees": "Costi rete",
        "cat_levies": "Imposte",
        "unit_month": "mese",
        "page_label": "Pagina",
        "page_of": "di",
    },
    "en": {
        "invoice_label": "Invoice",
        "invoice_date": "Invoice Date",
        "billing_period": "Billing Period",
        "status": "Status",
        "due_date": "Due Date",
        "from": "From",
        "to": "To",
        "description": "Description",
        "qty": "Qty",
        "unit": "Unit",
        "unit_price": "Unit Price (CHF)",
        "amount": "Amount (CHF)",
        "subtotal": "Subtotal",
        "vat": "VAT",
        "total": "Total",
        "payment_terms_label": "Payment Terms:",
        "payment_terms_text": "Due within 30 days of invoice date",
        "bank_details": "Bank Details:",
        "currency": "Currency: CHF",
        "reference_prefix": "Reference: Invoice",
        "slip_header": "\u2702 PAYMENT SLIP (Keep for your records)",
        "slip_invoice_details": "Invoice Details",
        "slip_invoice_nr": "Invoice #:",
        "slip_date": "Date:",
        "slip_period": "Period:",
        "slip_amount_due": "Amount Due: CHF",
        "slip_participant": "Participant",
        "slip_email": "Email:",
        "slip_remit_to": "Remit Payment To",
        "slip_ocr": "OCR/Reference:",
        "chart_title": "Energy Consumption \u2014 Period Comparison",
        "chart_description": "Local ZEV production vs grid import for this billing period, compared with equivalent periods in prior years.",
        "unit_month": "month",
        "page_label": "Page",
        "page_of": "of",
        "chart_from_zev": "From ZEV (local production)",
        "chart_from_grid": "From Grid",
        "chart_current": "(current)",
        "cat_energy": "Energy",
        "cat_grid_fees": "Grid Fees",
        "cat_levies": "Levies",
    },
}

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


def _group_items_by_category(items, period_start: date, period_end: date, tr: dict):
    labels = {
        TariffCategory.ENERGY: tr["cat_energy"],
        TariffCategory.GRID_FEES: tr["cat_grid_fees"],
        TariffCategory.LEVIES: tr["cat_levies"],
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


def _build_energy_chart_svg(invoice, tr: dict) -> str | None:
    """Generate an SVG stacked bar chart comparing local-ZEV vs grid kWh for the
    current invoice period alongside equivalent periods from prior years."""
    ps = invoice.period_start
    pe = invoice.period_end

    # Collect invoices for the same participant/ZEV that cover the same seasonal window
    comparable = []
    for h in (
        Invoice.objects.filter(participant=invoice.participant, zev=invoice.zev)
        .exclude(id=invoice.id)
        .order_by("period_start")
    ):
        if (
            h.period_start.month == ps.month
            and h.period_start.day == ps.day
            and h.period_end.month == pe.month
            and h.period_end.day == pe.day
        ):
            comparable.append(
                (h.period_start.year, float(h.total_local_kwh), float(h.total_grid_kwh))
            )

    data = comparable + [(ps.year, float(invoice.total_local_kwh), float(invoice.total_grid_kwh))]
    data.sort(key=lambda x: x[0])

    max_val = max((local + grid) for _, local, grid in data) if data else 0
    if max_val == 0:
        return None

    # ── SVG geometry ───────────────────────────────────────────────────────────
    W, H = 520, 228
    ML, MR, MT, MB = 58, 12, 15, 68   # margins: left, right, top, bottom
    cw = W - ML - MR    # chart area width
    ch = H - MT - MB    # chart area height

    n = len(data)
    group_w = cw / n
    bar_w = max(14, min(40, group_w * 0.55))  # wider: single stacked bar per group

    def s(v):        # value → pixel bar height
        return ch * v / max_val

    svg = []
    svg.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"'
        f' viewBox="0 0 {W} {H}">'
    )

    # Y-axis grid lines & labels (6 steps: 0 .. max)
    for i in range(6):
        frac = i / 5
        gy = MT + ch - ch * frac
        val = max_val * frac
        svg.append(
            f'<line x1="{ML}" y1="{gy:.1f}" x2="{ML + cw}" y2="{gy:.1f}"'
            f' stroke="#e5e7eb" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{ML - 4}" y="{gy + 3:.1f}" text-anchor="end"'
            f' font-size="7" fill="#6b7280">{val:.0f}</text>'
        )

    # Rotated Y-axis unit label
    mid_y = MT + ch // 2
    svg.append(
        f'<text transform="rotate(-90 9 {mid_y})" x="9" y="{mid_y}"'
        f' text-anchor="middle" font-size="7" fill="#6b7280">kWh</text>'
    )

    # X-axis baseline
    svg.append(
        f'<line x1="{ML}" y1="{MT + ch}" x2="{ML + cw}" y2="{MT + ch}"'
        f' stroke="#9ca3af" stroke-width="1"/>'
    )

    # ── Stacked bars (local ZEV bottom, grid on top) ─────────────────────────
    for idx, (year, local, grid) in enumerate(data):
        cx = ML + group_w * idx + group_w / 2
        bx = cx - bar_w / 2          # left edge of bar
        is_current = year == ps.year
        hl = s(local)
        hg = s(grid)
        total_h = hl + hg

        # Bottom segment: local ZEV (green)
        yl = MT + ch - hl
        svg.append(
            f'<rect x="{bx:.1f}" y="{yl:.1f}" width="{bar_w:.1f}"'
            f' height="{max(hl, 0):.1f}" fill="#16a34a"/>'
        )
        # Label inside segment if tall enough
        if hl > 14:
            svg.append(
                f'<text x="{cx:.1f}" y="{yl + hl / 2 + 3:.1f}"'
                f' text-anchor="middle" font-size="6" fill="#fff">{local:.1f}</text>'
            )

        # Top segment: grid (amber), rounded top corners
        yg = MT + ch - total_h
        svg.append(
            f'<rect x="{bx:.1f}" y="{yg:.1f}" width="{bar_w:.1f}"'
            f' height="{max(hg, 0):.1f}" fill="#f59e0b" rx="2" ry="2"/>'
        )
        # Square off the bottom corners of the grid segment by overlaying a rect
        if hg > 3:
            overlap = min(3, hg)
            svg.append(
                f'<rect x="{bx:.1f}" y="{yg + hg - overlap:.1f}" width="{bar_w:.1f}"'
                f' height="{overlap:.1f}" fill="#f59e0b"/>'
            )
        # Label inside segment if tall enough
        if hg > 14:
            svg.append(
                f'<text x="{cx:.1f}" y="{yg + hg / 2 + 3:.1f}"'
                f' text-anchor="middle" font-size="6" fill="#fff">{grid:.1f}</text>'
            )

        # Total above the full bar
        if total_h > 0:
            svg.append(
                f'<text x="{cx:.1f}" y="{MT + ch - total_h - 3:.1f}"'
                f' text-anchor="middle" font-size="7" font-weight="bold" fill="#374151">'
                f'{local + grid:.1f}</text>'
            )

        # Year label (bold + marker for current)
        fw = "bold" if is_current else "normal"
        col = "#111827" if is_current else "#374151"
        svg.append(
            f'<text x="{cx:.1f}" y="{MT + ch + 12:.1f}" text-anchor="middle"'
            f' font-size="8" fill="{col}" font-weight="{fw}">{year}</text>'
        )
        # Period date range (same window for all bars)
        period_str = f"{ps.day:02d}.{ps.month:02d}.–{pe.day:02d}.{pe.month:02d}."
        svg.append(
            f'<text x="{cx:.1f}" y="{MT + ch + 22:.1f}" text-anchor="middle"'
            f' font-size="6" fill="#6b7280">{period_str}</text>'
        )
        if is_current:
            svg.append(
                f'<text x="{cx:.1f}" y="{MT + ch + 33:.1f}" text-anchor="middle"'
                f' font-size="6" fill="#6b7280">{tr["chart_current"]}</text>'
            )

    # ── Legend ──────────────────────────────────────────────────────────────
    ly = MT + ch + (46 if any(yr == ps.year for yr, *_ in data) else 38)
    svg.append(f'<rect x="{ML}" y="{ly}" width="9" height="8" fill="#16a34a" rx="1"/>')
    svg.append(
        f'<text x="{ML + 12}" y="{ly + 7}" font-size="8" fill="#374151">{tr["chart_from_zev"]}</text>'
    )
    svg.append(f'<rect x="{ML + 155}" y="{ly}" width="9" height="8" fill="#f59e0b" rx="1"/>')
    svg.append(f'<text x="{ML + 167}" y="{ly + 7}" font-size="8" fill="#374151">{tr["chart_from_grid"]}</text>')

    svg.append('</svg>')
    return '\n'.join(svg)


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
    owner_participant = invoice.zev.participants.filter(user=invoice.zev.owner).first()
    creditor_city = _normalize_text(owner_participant.city if owner_participant else "")
    lang = invoice.zev.invoice_language or "de"
    tr = INVOICE_TRANSLATIONS.get(lang, INVOICE_TRANSLATIONS["de"])

    return {
        "invoice": invoice,
        "items": items,
        "grouped_items": _group_items_by_category(items, invoice.period_start, invoice.period_end, tr),
        "zev": invoice.zev,
        "owner_participant": owner_participant,
        "creditor_city": creditor_city,
        "participant": invoice.participant,
        "qr_svg": qr_svg,
        "energy_chart_svg": _build_energy_chart_svg(invoice, tr),
        "tr": tr,
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
