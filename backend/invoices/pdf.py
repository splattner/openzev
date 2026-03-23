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
        "cat_metering": "Messtarif",
        "unit_month": "Monat",
        "page_label": "Seite",
        "page_of": "von",
        "savings_title": "Ersparnisse durch lokale Solarenergie",
        "savings_local_label": "Lokale ZEV-Energie (tats\u00e4chlich verrechnet)",
        "savings_grid_label": "Hypothetische Netzkosten (gleiche kWh)",
        "savings_saved_label": "Ersparnisse",
        "hourly_chart_title": "Durchschnittliches Tagesverbrauchsprofil (24 h)",
        "hourly_chart_description": "Durchschnittlicher st\u00fcndlicher Energiebezug \u00fcber die Abrechnungsperiode \u2014 aufgeteilt in lokale ZEV-Energie und Netzbezug.",
        "feed_in_hint": "Hinweis: Die Verg\u00fctung f\u00fcr lokale Energie wird anteilig an Produzenten verteilt. Der Einspeisetarif gilt nur f\u00fcr tats\u00e4chlich ins Netz exportierte Energie.",
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
        "cat_metering": "Tarif de comptage",
        "unit_month": "mois",
        "page_label": "Page",
        "page_of": "de",
        "savings_title": "\u00c9conomies gr\u00e2ce \u00e0 l\u2019\u00e9nergie solaire locale",
        "savings_local_label": "\u00c9nergie locale ZEV (effectivement factur\u00e9e)",
        "savings_grid_label": "Co\u00fbt r\u00e9seau hypoth\u00e9tique (m\u00eames kWh)",
        "savings_saved_label": "\u00c9conomies",
        "hourly_chart_title": "Profil de consommation journali\u00e8re moyen (24 h)",
        "hourly_chart_description": "Consommation \u00e9nerg\u00e9tique horaire moyenne sur la p\u00e9riode de facturation \u2014 r\u00e9partie en \u00e9nergie locale ZEV et importation r\u00e9seau.",
        "feed_in_hint": "Remarque : la r\u00e9mun\u00e9ration de l\u2019\u00e9nergie locale est r\u00e9partie proportionnellement entre les producteurs. Le tarif d\u2019injection s\u2019applique uniquement \u00e0 l\u2019\u00e9nergie effectivement export\u00e9e vers le r\u00e9seau.",
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
        "cat_metering": "Tariffa di misurazione",
        "unit_month": "mese",
        "page_label": "Pagina",
        "page_of": "di",
        "savings_title": "Risparmi grazie all\u2019energia solare locale",
        "savings_local_label": "Energia locale ZEV (effettivamente fatturata)",
        "savings_grid_label": "Costo rete ipotetico (stesso kWh)",
        "savings_saved_label": "Risparmi",
        "hourly_chart_title": "Profilo di consumo giornaliero medio (24 h)",
        "hourly_chart_description": "Consumo energetico orario medio nel periodo di fatturazione \u2014 suddiviso in energia locale ZEV e importazione dalla rete.",
        "feed_in_hint": "Nota: il compenso per l\u2019energia locale \u00e8 ripartito proporzionalmente tra i produttori. La tariffa di immissione si applica solo all\u2019energia effettivamente esportata in rete.",
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
        "cat_metering": "Metering Tariff",
        "savings_title": "Savings from Local Solar Energy",
        "savings_local_label": "Local ZEV Energy (actually billed)",
        "savings_grid_label": "Hypothetical grid cost (same kWh)",
        "savings_saved_label": "Savings",
        "hourly_chart_title": "Average Daily Consumption Profile (24 h)",
        "hourly_chart_description": "Average hourly energy draw over the billing period \u2014 split between local ZEV energy and grid import.",
        "feed_in_hint": "Note: Local energy revenue is distributed to producers proportionally. Feed-in tariff is applied only to energy actually exported to the grid.",
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


def _build_savings_data(invoice, tr: dict) -> dict | None:
    """Compute how much the participant saved by consuming local ZEV energy vs grid.

    Returns a dict with display-ready strings, or None if savings cannot be computed
    (e.g. no local energy, no grid energy, or local rate >= grid rate).
    """
    from .models import InvoiceItem

    local_kwh = float(invoice.total_local_kwh)
    grid_kwh = float(invoice.total_grid_kwh)

    if local_kwh <= 0 or grid_kwh <= 0:
        return None

    items = list(invoice.items.all())
    local_items = [i for i in items if i.item_type == InvoiceItem.ItemType.LOCAL_ENERGY]
    grid_items = [i for i in items if i.item_type == InvoiceItem.ItemType.GRID_ENERGY]

    local_chf = sum(float(i.total_chf) for i in local_items)
    grid_chf = sum(float(i.total_chf) for i in grid_items)

    if local_chf <= 0 or grid_chf <= 0:
        return None

    avg_local_rp = local_chf / local_kwh * 100
    avg_grid_rp = grid_chf / grid_kwh * 100

    if avg_local_rp >= avg_grid_rp:
        return None  # no savings (local tariff not cheaper than grid)

    hypothetical_chf = local_kwh * avg_grid_rp / 100
    saved_chf = hypothetical_chf - local_chf

    return {
        "local_kwh": f"{local_kwh:.2f}",
        "local_chf": f"{local_chf:.2f}",
        "local_rp": f"{avg_local_rp:.2f}",
        "grid_rp": f"{avg_grid_rp:.2f}",
        "saved_rp": f"{avg_grid_rp - avg_local_rp:.2f}",
        "hypothetical_chf": f"{hypothetical_chf:.2f}",
        "saved_chf": f"{saved_chf:.2f}",
    }


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


def _build_hourly_profile_chart_svg(invoice, tr: dict) -> str | None:
    """Generate an SVG grouped bar chart showing the average hourly energy profile
    (local ZEV vs grid) over the invoice period.

    Returns None when sub-daily metering data is not available or all values are zero.
    """
    import datetime as _dt
    from django.db import models as _dj
    from metering.models import MeterReading, ReadingDirection, ReadingResolution
    from zev.models import MeteringPoint as _MP, MeteringPointType as _MPT

    ps = invoice.period_start
    pe = invoice.period_end
    participant = invoice.participant
    zev = invoice.zev

    start_dt = _dt.datetime.combine(ps, _dt.time.min).replace(tzinfo=_dt.timezone.utc)
    end_dt = _dt.datetime.combine(pe, _dt.time.max).replace(tzinfo=_dt.timezone.utc) + _dt.timedelta(seconds=1)

    # ── Participant consumption readings ────────────────────────────────────
    consumption_mps = _MP.objects.filter(
        participant=participant,
        meter_type__in=[_MPT.CONSUMPTION, _MPT.BIDIRECTIONAL],
    )
    participant_readings = list(
        MeterReading.objects.filter(
            metering_point__in=consumption_mps,
            timestamp__gte=start_dt,
            timestamp__lt=end_dt,
            direction=ReadingDirection.IN,
        ).order_by("timestamp")
    )
    if not participant_readings:
        return None

    # Only show chart when sub-daily data is present
    resolutions = {r.resolution for r in participant_readings}
    if resolutions == {ReadingResolution.DAILY}:
        return None

    # ── ZEV-level production and consumption by timestamp ───────────────────
    all_prod_mps = _MP.objects.filter(
        participant__zev=zev,
        meter_type__in=[_MPT.PRODUCTION, _MPT.BIDIRECTIONAL],
    )
    zev_prod_by_ts = {
        row["timestamp"]: float(row["total_kwh"] or 0)
        for row in MeterReading.objects.filter(
            metering_point__in=all_prod_mps,
            timestamp__gte=start_dt,
            timestamp__lt=end_dt,
            direction=ReadingDirection.OUT,
        ).values("timestamp").annotate(total_kwh=_dj.Sum("energy_kwh"))
    }
    all_cons_mps = _MP.objects.filter(
        participant__zev=zev,
        meter_type__in=[_MPT.CONSUMPTION, _MPT.BIDIRECTIONAL],
    )
    zev_cons_by_ts = {
        row["timestamp"]: float(row["total_kwh"] or 0)
        for row in MeterReading.objects.filter(
            metering_point__in=all_cons_mps,
            timestamp__gte=start_dt,
            timestamp__lt=end_dt,
            direction=ReadingDirection.IN,
        ).values("timestamp").annotate(total_kwh=_dj.Sum("energy_kwh"))
    }

    # ── Accumulate local/grid per UTC hour-of-day ───────────────────────────
    hourly_local = [0.0] * 24
    hourly_grid = [0.0] * 24

    for reading in participant_readings:
        ts = reading.timestamp
        hour = ts.hour
        p_kwh = float(reading.energy_kwh)
        zev_cons = zev_cons_by_ts.get(ts, 0.0)
        zev_prod = zev_prod_by_ts.get(ts, 0.0)
        local_pool = min(zev_prod, zev_cons)

        if zev_cons > 0 and local_pool > 0:
            r_local = min(p_kwh, local_pool * p_kwh / zev_cons)
        else:
            r_local = 0.0
        r_grid = max(p_kwh - r_local, 0.0)

        hourly_local[hour] += r_local
        hourly_grid[hour] += r_grid

    total_days = (pe - ps).days + 1
    hourly_local = [v / total_days for v in hourly_local]
    hourly_grid = [v / total_days for v in hourly_grid]

    max_val = max((l + g) for l, g in zip(hourly_local, hourly_grid))
    if max_val == 0:
        return None

    # ── SVG geometry ────────────────────────────────────────────────────────
    W, H = 520, 210
    ML, MR, MT, MB = 46, 12, 15, 46
    cw = W - ML - MR
    ch = H - MT - MB

    group_w = cw / 24
    bar_w = max(6.0, group_w * 0.72)

    def s(v: float) -> float:
        return ch * v / max_val

    svg: list[str] = []
    svg.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"'
        f' viewBox="0 0 {W} {H}">'
    )

    # Y-axis grid lines & labels (5 steps)
    for i in range(5):
        frac = i / 4
        gy = MT + ch - ch * frac
        val = max_val * frac
        svg.append(
            f'<line x1="{ML}" y1="{gy:.1f}" x2="{ML + cw}" y2="{gy:.1f}"'
            f' stroke="#e5e7eb" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{ML - 4}" y="{gy + 3:.1f}" text-anchor="end"'
            f' font-size="7" fill="#6b7280">{val:.2f}</text>'
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

    # ── Stacked bars per hour ───────────────────────────────────────────────
    for hour in range(24):
        local = hourly_local[hour]
        grid = hourly_grid[hour]
        cx = ML + group_w * hour + group_w / 2
        bx = cx - bar_w / 2
        hl = s(local)
        hg = s(grid)
        total_h = hl + hg

        # Local segment (green, bottom)
        yl = MT + ch - hl
        if hl > 0:
            svg.append(
                f'<rect x="{bx:.1f}" y="{yl:.1f}" width="{bar_w:.1f}"'
                f' height="{hl:.1f}" fill="#16a34a"/>'
            )

        # Grid segment (amber, top), rounded top corners
        yg = MT + ch - total_h
        if hg > 0:
            svg.append(
                f'<rect x="{bx:.1f}" y="{yg:.1f}" width="{bar_w:.1f}"'
                f' height="{hg:.1f}" fill="#f59e0b" rx="2" ry="2"/>'
            )
            # Square off bottom corners of amber segment
            overlap = min(3.0, hg)
            svg.append(
                f'<rect x="{bx:.1f}" y="{yg + hg - overlap:.1f}" width="{bar_w:.1f}"'
                f' height="{overlap:.1f}" fill="#f59e0b"/>'
            )

        # Hour label every 3 hours
        if hour % 3 == 0:
            svg.append(
                f'<text x="{cx:.1f}" y="{MT + ch + 11:.1f}" text-anchor="middle"'
                f' font-size="7" fill="#374151">{hour:02d}:00</text>'
            )

    # ── Legend ─────────────────────────────────────────────────────────────
    ly = MT + ch + 26
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
        "hourly_profile_chart_svg": _build_hourly_profile_chart_svg(invoice, tr),
        "savings_data": _build_savings_data(invoice, tr),
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
