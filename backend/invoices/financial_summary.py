"""Financial summary PDF export for energy producers in a ZEV.

This report shows the taxable revenue for any producer participant:
1. Local energy sold — income from selling energy to the ZEV (producer credits).
2. Local energy consumed — what the producer bought from the ZEV (self-consumption).
3. Net local energy revenue — sold minus consumed.
4. Feed-in compensation — income from energy fed into the grid.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from accounts.models import AppSettings
from weasyprint import HTML

from .models import Invoice, InvoiceItem, InvoiceStatus
from .pdf import _format_date_value, _render_template

FINANCIAL_SUMMARY_TEMPLATE = "invoices/financial_summary_pdf.html"


FINANCIAL_SUMMARY_TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        "title": "Steuerübersicht",
        "subtitle": "Steuerpflichtige Einnahmen aus dem Zusammenschluss zum Eigenverbrauch (ZEV)",
        "year": "Jahr",
        "zev": "ZEV",
        "producer": "Produzent",
        "generated_on": "Erstellt am",
        "taxable_income": "Steuerpflichtiges Einkommen",
        "local_sold": "Verkauf Solarstrom an ZEV",
        "local_consumed": "Bezug Solarstrom aus ZEV",
        "net_local": "Netto Erlös Eigenverbrauch",
        "feed_in": "Einspeisevergütung (Netzeinspeisung)",
        "total_taxable": "Total steuerpflichtiges Einkommen",
        "kwh": "kWh",
        "chf": "CHF",
        "monthly_breakdown": "Aufstellung pro Monat",
        "month": "Monat",
        "tariff_detail": "Angewandte Tarife",
        "tariff_category": "Kategorie",
        "tariff_name": "Tarif",
        "tariff_price": "Preis/kWh",
        "no_data": "Keine Rechnungsdaten für dieses Jahr.",
        "taxable_note": "Dieses Einkommen ist steuerpflichtig gemäss Schweizer Steuerrecht.",
        "months": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"],
    },
    "fr": {
        "title": "Aperçu fiscal",
        "subtitle": "Revenus imposables du regroupement dans le cadre de la consommation propre (RCP)",
        "year": "Année",
        "zev": "RCP",
        "producer": "Producteur",
        "generated_on": "Généré le",
        "taxable_income": "Revenu imposable",
        "local_sold": "Vente d'énergie solaire au RCP",
        "local_consumed": "Achat d'énergie solaire du RCP",
        "net_local": "Revenu net autoconsommation",
        "feed_in": "Rémunération injection (réseau)",
        "total_taxable": "Total revenu imposable",
        "kwh": "kWh",
        "chf": "CHF",
        "monthly_breakdown": "Détail par mois",
        "month": "Mois",
        "tariff_detail": "Tarifs appliqués",
        "tariff_category": "Catégorie",
        "tariff_name": "Tarif",
        "tariff_price": "Prix/kWh",
        "no_data": "Aucune donnée de facture pour cette année.",
        "taxable_note": "Ce revenu est imposable selon le droit fiscal suisse.",
        "months": ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"],
    },
    "it": {
        "title": "Panoramica fiscale",
        "subtitle": "Reddito imponibile dal raggruppamento ai fini del consumo proprio (RCP)",
        "year": "Anno",
        "zev": "RCP",
        "producer": "Produttore",
        "generated_on": "Generato il",
        "taxable_income": "Reddito imponibile",
        "local_sold": "Vendita energia solare al RCP",
        "local_consumed": "Acquisto energia solare dal RCP",
        "net_local": "Ricavo netto autoconsumo",
        "feed_in": "Remunerazione immissione (rete)",
        "total_taxable": "Totale reddito imponibile",
        "kwh": "kWh",
        "chf": "CHF",
        "monthly_breakdown": "Dettaglio per mese",
        "month": "Mese",
        "tariff_detail": "Tariffe applicate",
        "tariff_category": "Categoria",
        "tariff_name": "Tariffa",
        "tariff_price": "Prezzo/kWh",
        "no_data": "Nessun dato di fattura per questo anno.",
        "taxable_note": "Questo reddito è imponibile secondo il diritto fiscale svizzero.",
        "months": ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"],
    },
    "en": {
        "title": "Tax Overview",
        "subtitle": "Taxable revenue from the community for self-consumption (ZEV)",
        "year": "Year",
        "zev": "ZEV",
        "producer": "Producer",
        "generated_on": "Generated on",
        "taxable_income": "Taxable Income",
        "local_sold": "Energy sold to ZEV",
        "local_consumed": "Energy consumed from ZEV",
        "net_local": "Net local energy revenue",
        "feed_in": "Feed-in compensation (grid export)",
        "total_taxable": "Total taxable income",
        "kwh": "kWh",
        "chf": "CHF",
        "monthly_breakdown": "Breakdown by month",
        "month": "Month",
        "tariff_detail": "Applied tariffs",
        "tariff_category": "Category",
        "tariff_name": "Tariff",
        "tariff_price": "Price/kWh",
        "no_data": "No invoice data for this year.",
        "taxable_note": "This income is taxable under Swiss tax law.",
        "months": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    },
}


def _fmt_money(value: Decimal) -> str:
    return f"{value:.2f}"


def _fmt_kwh(value: Decimal) -> str:
    return f"{value:.2f}"


def generate_financial_summary_pdf(zev, participant, year: int) -> bytes:
    """Generate a financial summary PDF for a specific producer participant.

    Looks at the participant's own invoices and computes:
    - local_sold:  abs(negative LOCAL_ENERGY items) — producer credits received
    - local_consumed: positive LOCAL_ENERGY items — energy bought from ZEV
    - net_local:  local_sold - local_consumed
    - feed_in:   abs(FEED_IN items) — grid export compensation
    """
    lang = zev.invoice_language or "de"
    tr = FINANCIAL_SUMMARY_TRANSLATIONS.get(lang, FINANCIAL_SUMMARY_TRANSLATIONS["de"])
    app_settings = AppSettings.load()

    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    all_invoices = list(
        Invoice.objects.filter(
            zev=zev,
            participant=participant,
            status=InvoiceStatus.PAID,
            period_start__gte=year_start,
            period_end__lte=year_end,
        )
        .prefetch_related("items")
        .order_by("period_start")
    )

    # ── deduplicate overlapping periods ─────────────────────────────
    # When invoices are regenerated with a different billing interval,
    # stale invoices for the old interval may still exist as drafts.
    # Keep the most recently created invoice for any overlapping window.
    invoices: list[Invoice] = []
    for inv in sorted(all_invoices, key=lambda x: x.created_at, reverse=True):
        overlaps = any(
            not (inv.period_end < existing.period_start or inv.period_start > existing.period_end)
            for existing in invoices
        )
        if not overlaps:
            invoices.append(inv)

    # ── aggregate revenue from the participant's own invoices ────────
    total_local_sold = Decimal("0")
    total_local_consumed = Decimal("0")
    total_feed_in = Decimal("0")
    total_local_sold_kwh = Decimal("0")
    total_local_consumed_kwh = Decimal("0")
    total_feed_in_kwh = Decimal("0")

    monthly_local_sold: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    monthly_local_consumed: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    monthly_feed_in: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))

    # Tariff detail lines: keyed by (item_type_category, description, unit_price)
    tariff_details: dict[tuple[str, str, Decimal], dict] = {}

    for invoice in invoices:
        # Determine covered months for even distribution in monthly breakdown.
        start_month = invoice.period_start.month
        end_month = invoice.period_end.month
        covered_months = list(range(start_month, end_month + 1))
        n_months = len(covered_months)

        for item in invoice.items.all():
            if item.item_type == InvoiceItem.ItemType.LOCAL_ENERGY:
                if item.total_chf < 0:
                    # Negative LOCAL_ENERGY = producer credit (energy sold to ZEV)
                    amount = abs(item.total_chf)
                    total_local_sold += amount
                    total_local_sold_kwh += item.quantity_kwh
                    per_month = amount / n_months
                    for m in covered_months:
                        monthly_local_sold[m] += per_month
                    category = "local_sold"
                elif item.total_chf > 0:
                    # Positive LOCAL_ENERGY = energy consumed from ZEV
                    total_local_consumed += item.total_chf
                    total_local_consumed_kwh += item.quantity_kwh
                    per_month = item.total_chf / n_months
                    for m in covered_months:
                        monthly_local_consumed[m] += per_month
                    category = "local_consumed"
                else:
                    continue
            elif item.item_type == InvoiceItem.ItemType.FEED_IN:
                # Feed-in items are negative on invoices (credits);
                # abs() gives the revenue received from the grid.
                amount = abs(item.total_chf)
                total_feed_in += amount
                total_feed_in_kwh += item.quantity_kwh
                per_month = amount / n_months
                for m in covered_months:
                    monthly_feed_in[m] += per_month
                category = "feed_in"
            else:
                continue

            # Accumulate tariff detail line — key by category + description
            # so items with the same tariff across periods merge even if
            # unit_price differs by rounding.
            key = (category, item.description)
            if key not in tariff_details:
                tariff_details[key] = {
                    "category": category,
                    "description": item.description,
                    "quantity_kwh": Decimal("0"),
                    "total_chf": Decimal("0"),
                }
            tariff_details[key]["quantity_kwh"] += item.quantity_kwh
            tariff_details[key]["total_chf"] += abs(item.total_chf)

    net_local = total_local_sold - total_local_consumed
    total_taxable = net_local + total_feed_in

    # ── build template rows ──────────────────────────────────────────
    monthly_rows = []
    for idx in range(1, 13):
        sold = monthly_local_sold.get(idx, Decimal("0"))
        consumed = monthly_local_consumed.get(idx, Decimal("0"))
        fi = monthly_feed_in.get(idx, Decimal("0"))
        net = sold - consumed
        monthly_rows.append({
            "month": tr["months"][idx - 1],
            "local_sold": _fmt_money(sold),
            "local_consumed": _fmt_money(consumed),
            "net_local": _fmt_money(net),
            "feed_in": _fmt_money(fi),
            "total": _fmt_money(net + fi),
        })

    # ── build tariff detail rows ───────────────────────────────────
    # Group by category, sorted: local_sold, local_consumed, feed_in
    category_order = {"local_sold": 0, "local_consumed": 1, "feed_in": 2}
    category_labels = {
        "local_sold": tr["local_sold"],
        "local_consumed": tr["local_consumed"],
        "feed_in": tr["feed_in"],
    }
    tariff_rows = []
    for key in sorted(tariff_details.keys(), key=lambda k: (category_order.get(k[0], 9), k[1])):
        detail = tariff_details[key]
        qty = detail["quantity_kwh"]
        total = detail["total_chf"]
        unit_price = (total / qty).quantize(Decimal("0.00001")) if qty else Decimal("0")
        tariff_rows.append({
            "category": category_labels.get(detail["category"], detail["category"]),
            "description": detail["description"],
            "quantity_kwh": _fmt_kwh(qty),
            "unit_price": _fmt_money(unit_price),
            "total_chf": _fmt_money(total),
        })

    producer_name = participant.full_name or (
        f"{participant.first_name} {participant.last_name}".strip()
    )

    context = {
        "lang": lang,
        "tr": tr,
        "year": year,
        "zev": zev,
        "producer_name": producer_name,
        "formatted_dates": {
            "generated_on": _format_date_value(date.today(), app_settings.date_format_short),
        },
        "totals": {
            "local_sold": _fmt_money(total_local_sold),
            "local_consumed": _fmt_money(total_local_consumed),
            "net_local": _fmt_money(net_local),
            "feed_in": _fmt_money(total_feed_in),
            "total_taxable": _fmt_money(total_taxable),
            "local_sold_kwh": _fmt_kwh(total_local_sold_kwh),
            "local_consumed_kwh": _fmt_kwh(total_local_consumed_kwh),
            "feed_in_kwh": _fmt_kwh(total_feed_in_kwh),
        },
        "monthly_rows": monthly_rows,
        "tariff_rows": tariff_rows,
        "has_data": total_local_sold != Decimal("0") or total_feed_in != Decimal("0") or total_local_consumed != Decimal("0"),
    }

    html_string = _render_template(FINANCIAL_SUMMARY_TEMPLATE, context)
    return HTML(string=html_string, base_url=".").write_pdf()
