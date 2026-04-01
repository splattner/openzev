"""
Annual participant statement (Jahresabrechnung) PDF generation.

Produces a year-end summary document for a participant showing:
- Monthly consumption/production breakdown with local-pool allocation
- All invoices issued in the year
- Savings compared to grid tariff
- Energy self-sufficiency ratio
"""
import logging
from datetime import date, datetime, time, timezone as dt_timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.template.loader import render_to_string
from django.template import Template, Context
from accounts.models import AppSettings
from weasyprint import HTML

from metering.models import MeterReading, ReadingDirection
from zev.models import MeteringPoint, MeteringPointType, MeteringPointAssignment
from .models import Invoice, InvoiceStatus
from .pdf import _format_date_value, _render_template

logger = logging.getLogger(__name__)

ANNUAL_STATEMENT_TEMPLATE = "invoices/annual_statement_pdf.html"

# ── Translations ────────────────────────────────────────────────────────────

ANNUAL_TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        "title": "Jahresabrechnung",
        "statement_date": "Erstellungsdatum",
        "from_label": "Von",
        "to_label": "An",
        "total_consumption": "Gesamtverbrauch",
        "from_zev": "Aus ZEV",
        "from_grid": "Aus dem Netz",
        "self_sufficiency": "Eigenversorgung",
        "autarky": "Autarkiegrad",
        "monthly_breakdown": "Monatliche Übersicht",
        "monthly_chart_description": "Monatlicher Energieverbrauch — aufgeteilt in lokale ZEV-Energie und Netzbezug.",
        "month_col": "Monat",
        "consumption_col": "Verbrauch",
        "from_zev_col": "Aus ZEV",
        "from_grid_col": "Aus Netz",
        "production_col": "Produktion",
        "self_sufficiency_col": "Autarkie",
        "total_label": "Total",
        "invoices_title": "Rechnungen",
        "invoice_number_col": "Rechnungs-Nr.",
        "period_col": "Periode",
        "status_col": "Status",
        "subtotal_col": "Subtotal",
        "vat_col": "MwSt.",
        "total_col": "Total",
        "no_invoices": "Keine Rechnungen für dieses Jahr.",
        "savings_title": "Ersparnisse durch lokale Solarenergie",
        "savings_local_label": "Lokale ZEV-Energie (tatsächlich verrechnet)",
        "savings_grid_label": "Hypothetische Netzkosten (gleiche kWh)",
        "savings_saved_label": "Ihre Ersparnisse",
        "rp_unit": "Rp./kWh",
        "generated_on": "Erstellt am",
        "months": ["Januar", "Februar", "März", "April", "Mai", "Juni",
                    "Juli", "August", "September", "Oktober", "November", "Dezember"],
    },
    "fr": {
        "title": "Décompte annuel",
        "statement_date": "Date d'émission",
        "from_label": "De",
        "to_label": "À",
        "total_consumption": "Consommation totale",
        "from_zev": "Depuis CEL",
        "from_grid": "Depuis le réseau",
        "self_sufficiency": "Autosuffisance",
        "autarky": "Taux d'autarcie",
        "monthly_breakdown": "Aperçu mensuel",
        "monthly_chart_description": "Consommation énergétique mensuelle — répartie en énergie locale CEL et importation réseau.",
        "month_col": "Mois",
        "consumption_col": "Consommation",
        "from_zev_col": "Depuis CEL",
        "from_grid_col": "Depuis réseau",
        "production_col": "Production",
        "self_sufficiency_col": "Autarcie",
        "total_label": "Total",
        "invoices_title": "Factures",
        "invoice_number_col": "Facture n°",
        "period_col": "Période",
        "status_col": "Statut",
        "subtotal_col": "Sous-total",
        "vat_col": "TVA",
        "total_col": "Total",
        "no_invoices": "Aucune facture pour cette année.",
        "savings_title": "Économies grâce à l'énergie solaire locale",
        "savings_local_label": "Énergie locale CEL (effectivement facturée)",
        "savings_grid_label": "Coût réseau hypothétique (mêmes kWh)",
        "savings_saved_label": "Vos économies",
        "rp_unit": "ct./kWh",
        "generated_on": "Généré le",
        "months": ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
                    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"],
    },
    "it": {
        "title": "Rendiconto annuale",
        "statement_date": "Data di emissione",
        "from_label": "Da",
        "to_label": "A",
        "total_consumption": "Consumo totale",
        "from_zev": "Da CEL",
        "from_grid": "Dalla rete",
        "self_sufficiency": "Autosufficienza",
        "autarky": "Grado di autarchia",
        "monthly_breakdown": "Panoramica mensile",
        "monthly_chart_description": "Consumo energetico mensile — suddiviso in energia locale CEL e importazione dalla rete.",
        "month_col": "Mese",
        "consumption_col": "Consumo",
        "from_zev_col": "Da CEL",
        "from_grid_col": "Dalla rete",
        "production_col": "Produzione",
        "self_sufficiency_col": "Autarchia",
        "total_label": "Totale",
        "invoices_title": "Fatture",
        "invoice_number_col": "Fattura n.",
        "period_col": "Periodo",
        "status_col": "Stato",
        "subtotal_col": "Subtotale",
        "vat_col": "IVA",
        "total_col": "Totale",
        "no_invoices": "Nessuna fattura per quest'anno.",
        "savings_title": "Risparmi grazie all'energia solare locale",
        "savings_local_label": "Energia locale CEL (effettivamente fatturata)",
        "savings_grid_label": "Costo rete ipotetico (stesso kWh)",
        "savings_saved_label": "I vostri risparmi",
        "rp_unit": "ct./kWh",
        "generated_on": "Generato il",
        "months": ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
                    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"],
    },
    "en": {
        "title": "Annual Statement",
        "statement_date": "Statement Date",
        "from_label": "From",
        "to_label": "To",
        "total_consumption": "Total Consumption",
        "from_zev": "From ZEV",
        "from_grid": "From Grid",
        "self_sufficiency": "Self-Sufficiency",
        "autarky": "Autarky Rate",
        "monthly_breakdown": "Monthly Overview",
        "monthly_chart_description": "Monthly energy consumption — split between local ZEV energy and grid import.",
        "month_col": "Month",
        "consumption_col": "Consumption",
        "from_zev_col": "From ZEV",
        "from_grid_col": "From Grid",
        "production_col": "Production",
        "self_sufficiency_col": "Autarky",
        "total_label": "Total",
        "invoices_title": "Invoices",
        "invoice_number_col": "Invoice #",
        "period_col": "Period",
        "status_col": "Status",
        "subtotal_col": "Subtotal",
        "vat_col": "VAT",
        "total_col": "Total",
        "no_invoices": "No invoices for this year.",
        "savings_title": "Savings from Local Solar Energy",
        "savings_local_label": "Local ZEV energy (actually billed)",
        "savings_grid_label": "Hypothetical grid cost (same kWh)",
        "savings_saved_label": "Your savings",
        "rp_unit": "Rp./kWh",
        "generated_on": "Generated on",
        "months": ["January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December"],
    },
}


def _compute_monthly_data(participant, zev, year: int, tr: dict) -> tuple[list[dict], dict]:
    """Compute monthly consumption/production with per-timestamp local-pool allocation.

    Mirrors the billing engine and dashboard: the local-pool split is computed at
    each 15-min timestamp, then aggregated into monthly buckets for display.

    Returns (monthly_rows, totals_dict).
    """
    from django.db.models import Q, Sum

    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    year_start_dt = datetime(year, 1, 1, tzinfo=dt_timezone.utc)
    year_end_dt = datetime(year + 1, 1, 1, tzinfo=dt_timezone.utc)

    # All metering point assignments for this participant in this year
    assignments = list(
        MeteringPointAssignment.objects.filter(
            participant=participant,
            valid_from__lte=year_end,
        ).filter(
            Q(valid_to__isnull=True) | Q(valid_to__gte=year_start)
        ).select_related("metering_point")
    )

    cons_mp_ids = [
        a.metering_point_id for a in assignments
        if a.metering_point.meter_type in [MeteringPointType.CONSUMPTION, MeteringPointType.BIDIRECTIONAL]
    ]
    prod_mp_ids = [
        a.metering_point_id for a in assignments
        if a.metering_point.meter_type in [MeteringPointType.PRODUCTION, MeteringPointType.BIDIRECTIONAL]
    ]

    # All consumption/production metering points in the ZEV for local-pool calculation
    all_cons_mp_ids = list(
        MeteringPoint.objects.filter(
            zev=zev,
            meter_type__in=[MeteringPointType.CONSUMPTION, MeteringPointType.BIDIRECTIONAL],
            is_active=True,
        ).values_list("id", flat=True)
    )
    all_prod_mp_ids = list(
        MeteringPoint.objects.filter(
            zev=zev,
            meter_type__in=[MeteringPointType.PRODUCTION, MeteringPointType.BIDIRECTIONAL],
            is_active=True,
        ).values_list("id", flat=True)
    )

    # ── Build ZEV-wide per-timestamp pivot ──────────────────────────────────
    zev_readings = (
        MeterReading.objects.filter(
            metering_point_id__in=set(all_cons_mp_ids + all_prod_mp_ids),
            timestamp__gte=year_start_dt,
            timestamp__lt=year_end_dt,
        )
        .values("timestamp", "direction")
        .annotate(total_kwh=Sum("energy_kwh"))
        .order_by("timestamp")
    )

    zev_pivot: dict[datetime, dict[str, Decimal]] = {}
    for row in zev_readings:
        ts = row["timestamp"]
        if ts not in zev_pivot:
            zev_pivot[ts] = {"consumed": Decimal("0"), "produced": Decimal("0")}
        if row["direction"] == ReadingDirection.IN:
            zev_pivot[ts]["consumed"] = row["total_kwh"] or Decimal("0")
        elif row["direction"] == ReadingDirection.OUT:
            zev_pivot[ts]["produced"] = row["total_kwh"] or Decimal("0")

    # ── Participant consumption per timestamp ───────────────────────────────
    participant_consumption_rows = (
        MeterReading.objects.filter(
            metering_point_id__in=cons_mp_ids,
            direction=ReadingDirection.IN,
            timestamp__gte=year_start_dt,
            timestamp__lt=year_end_dt,
        )
        .values("timestamp")
        .annotate(consumed_kwh=Sum("energy_kwh"))
        .order_by("timestamp")
    )

    # ── Participant production per timestamp ────────────────────────────────
    participant_production_rows = (
        MeterReading.objects.filter(
            metering_point_id__in=prod_mp_ids,
            direction=ReadingDirection.OUT,
            timestamp__gte=year_start_dt,
            timestamp__lt=year_end_dt,
        )
        .values("timestamp")
        .annotate(produced_kwh=Sum("energy_kwh"))
        .order_by("timestamp")
    )

    # ── Accumulate per-timestamp, bucket into months ────────────────────────
    month_acc = {m: {"consumed": Decimal("0"), "from_zev": Decimal("0"),
                     "from_grid": Decimal("0"), "produced": Decimal("0")}
                 for m in range(1, 13)}

    # Consumption with local-pool allocation per timestamp
    for row in participant_consumption_rows:
        ts = row["timestamp"]
        month_num = ts.month
        consumed = row["consumed_kwh"] or Decimal("0")

        zev_at_ts = zev_pivot.get(ts, {"consumed": Decimal("0"), "produced": Decimal("0")})
        zev_consumed = zev_at_ts["consumed"]
        zev_produced = zev_at_ts["produced"]
        local_pool = min(zev_produced, zev_consumed)

        if zev_consumed > 0 and local_pool > 0:
            from_zev = min(consumed, local_pool * (consumed / zev_consumed))
        else:
            from_zev = Decimal("0")
        from_grid = max(consumed - from_zev, Decimal("0"))

        month_acc[month_num]["consumed"] += consumed
        month_acc[month_num]["from_zev"] += from_zev
        month_acc[month_num]["from_grid"] += from_grid

    # Production (just sum per month, no allocation needed)
    for row in participant_production_rows:
        ts = row["timestamp"]
        month_num = ts.month
        produced = row["produced_kwh"] or Decimal("0")
        month_acc[month_num]["produced"] += produced

    # ── Build output rows ───────────────────────────────────────────────────
    months_data = []
    acc_consumed = Decimal("0")
    acc_from_zev = Decimal("0")
    acc_from_grid = Decimal("0")
    acc_produced = Decimal("0")

    for month_idx in range(12):
        month_num = month_idx + 1
        m = month_acc[month_num]

        consumed_f = float(m["consumed"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        from_zev_f = float(m["from_zev"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        from_grid_f = float(m["from_grid"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        produced_f = float(m["produced"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        self_suf = round(from_zev_f / consumed_f * 100) if consumed_f > 0 else 0

        months_data.append({
            "month_label": tr["months"][month_idx],
            "consumed_kwh": f"{consumed_f:.2f}",
            "from_zev_kwh": f"{from_zev_f:.2f}",
            "from_grid_kwh": f"{from_grid_f:.2f}",
            "produced_kwh": f"{produced_f:.2f}",
            "self_sufficiency_pct": self_suf,
        })

        acc_consumed += m["consumed"]
        acc_from_zev += m["from_zev"]
        acc_from_grid += m["from_grid"]
        acc_produced += m["produced"]

    total_consumed = float(acc_consumed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    total_from_zev = float(acc_from_zev.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    total_from_grid = float(acc_from_grid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    total_produced = float(acc_produced.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    total_self_suf = round(total_from_zev / total_consumed * 100) if total_consumed > 0 else 0

    totals = {
        "total_consumed_kwh": f"{total_consumed:.2f}",
        "from_zev_kwh": f"{total_from_zev:.2f}",
        "from_grid_kwh": f"{total_from_grid:.2f}",
        "total_produced_kwh": f"{total_produced:.2f}",
        "self_sufficiency_pct": total_self_suf,
    }

    return months_data, totals


def _compute_savings(participant, zev, year: int) -> dict | None:
    """Compute annual savings from local energy vs grid rates using actual invoice data."""
    from .models import InvoiceItem

    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)

    invoices = Invoice.objects.filter(
        participant=participant,
        zev=zev,
        period_start__gte=year_start,
        period_end__lte=year_end,
    ).exclude(status=InvoiceStatus.CANCELLED)

    total_local_kwh = float(sum(inv.total_local_kwh for inv in invoices))
    total_grid_kwh = float(sum(inv.total_grid_kwh for inv in invoices))

    if total_local_kwh <= 0 or total_grid_kwh <= 0:
        return None

    local_chf = 0.0
    grid_chf = 0.0
    for inv in invoices:
        items = list(inv.items.all())
        local_chf += sum(float(i.total_chf) for i in items if i.item_type == InvoiceItem.ItemType.LOCAL_ENERGY)
        grid_chf += sum(float(i.total_chf) for i in items if i.item_type == InvoiceItem.ItemType.GRID_ENERGY)

    if local_chf <= 0 or grid_chf <= 0:
        return None

    avg_local_rp = local_chf / total_local_kwh * 100
    avg_grid_rp = grid_chf / total_grid_kwh * 100

    if avg_local_rp >= avg_grid_rp:
        return None

    hypothetical_chf = total_local_kwh * avg_grid_rp / 100
    saved_chf = hypothetical_chf - local_chf

    return {
        "local_kwh": f"{total_local_kwh:.2f}",
        "local_chf": f"{local_chf:.2f}",
        "local_rp": f"{avg_local_rp:.2f}",
        "grid_rp": f"{avg_grid_rp:.2f}",
        "hypothetical_chf": f"{hypothetical_chf:.2f}",
        "saved_chf": f"{saved_chf:.2f}",
    }


def _build_monthly_chart_svg(monthly_data: list[dict], tr: dict) -> str | None:
    """Build a stacked bar chart SVG showing monthly from_zev vs from_grid."""
    if not monthly_data:
        return None

    values = []
    for row in monthly_data:
        values.append((float(row["from_zev_kwh"]), float(row["from_grid_kwh"])))

    max_val = max((zev + grid) for zev, grid in values) if values else 1
    if max_val <= 0:
        return None

    chart_w = 520
    chart_h = 180
    margin_l = 50
    margin_b = 30
    margin_t = 10
    bar_area_w = chart_w - margin_l - 10
    bar_area_h = chart_h - margin_b - margin_t
    bar_w = bar_area_w / 12 * 0.7
    gap = bar_area_w / 12 * 0.3

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {chart_w} {chart_h}" class="bar-chart">'
    ]

    # Y-axis labels
    for i in range(5):
        y_val = max_val * i / 4
        y_pos = margin_t + bar_area_h - (bar_area_h * i / 4)
        svg_parts.append(
            f'<text x="{margin_l - 5}" y="{y_pos + 3}" text-anchor="end" '
            f'font-size="7" fill="#888">{y_val:.0f}</text>'
        )
        svg_parts.append(
            f'<line x1="{margin_l}" y1="{y_pos}" x2="{chart_w - 10}" y2="{y_pos}" '
            f'stroke="#eee" stroke-width="0.5"/>'
        )

    # Bars
    for i, (zev_val, grid_val) in enumerate(values):
        total = zev_val + grid_val
        x = margin_l + i * (bar_w + gap) + gap / 2
        bar_total_h = (total / max_val) * bar_area_h if max_val > 0 else 0

        # ZEV portion (bottom, green)
        zev_h = (zev_val / max_val) * bar_area_h if max_val > 0 else 0
        zev_y = margin_t + bar_area_h - zev_h
        if zev_h > 0:
            svg_parts.append(
                f'<rect x="{x:.1f}" y="{zev_y:.1f}" width="{bar_w:.1f}" height="{zev_h:.1f}" '
                f'fill="#4caf50" rx="1"/>'
            )

        # Grid portion (top, blue-grey)
        grid_h = (grid_val / max_val) * bar_area_h if max_val > 0 else 0
        grid_y = zev_y - grid_h
        if grid_h > 0:
            svg_parts.append(
                f'<rect x="{x:.1f}" y="{grid_y:.1f}" width="{bar_w:.1f}" height="{grid_h:.1f}" '
                f'fill="#90a4ae" rx="1"/>'
            )

        # Month label (abbreviated)
        label = tr["months"][i][:3]
        label_x = x + bar_w / 2
        svg_parts.append(
            f'<text x="{label_x:.1f}" y="{margin_t + bar_area_h + 15}" text-anchor="middle" '
            f'font-size="7" fill="#666">{label}</text>'
        )

    # Legend
    legend_y = chart_h - 5
    svg_parts.append(
        f'<rect x="{margin_l}" y="{legend_y - 6}" width="8" height="8" fill="#4caf50" rx="1"/>'
        f'<text x="{margin_l + 11}" y="{legend_y}" font-size="7" fill="#666">{tr["from_zev_col"]}</text>'
        f'<rect x="{margin_l + 80}" y="{legend_y - 6}" width="8" height="8" fill="#90a4ae" rx="1"/>'
        f'<text x="{margin_l + 93}" y="{legend_y}" font-size="7" fill="#666">{tr["from_grid_col"]}</text>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def generate_annual_statement_pdf(participant, zev, year: int) -> bytes:
    """Generate the annual statement PDF for a participant."""
    lang = zev.invoice_language or "de"
    tr = ANNUAL_TRANSLATIONS.get(lang, ANNUAL_TRANSLATIONS["de"])
    app_settings = AppSettings.load()

    monthly_data, totals = _compute_monthly_data(participant, zev, year, tr)

    # Invoices for this year
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)

    year_invoices = list(
        Invoice.objects.filter(
            participant=participant,
            zev=zev,
            period_start__gte=year_start,
            period_end__lte=year_end,
        ).exclude(status=InvoiceStatus.CANCELLED).order_by("period_start")
    )

    date_pattern = app_settings.date_format_short
    invoice_rows = []
    sum_subtotal = Decimal("0")
    sum_vat = Decimal("0")
    sum_total = Decimal("0")
    for inv in year_invoices:
        invoice_rows.append({
            "invoice_number": inv.invoice_number,
            "period_start_formatted": _format_date_value(inv.period_start, date_pattern),
            "period_end_formatted": _format_date_value(inv.period_end, date_pattern),
            "status_display": inv.get_status_display(),
            "subtotal_chf": f"{inv.subtotal_chf:.2f}",
            "vat_chf": f"{inv.vat_chf:.2f}",
            "total_chf": f"{inv.total_chf:.2f}",
        })
        sum_subtotal += inv.subtotal_chf
        sum_vat += inv.vat_chf
        sum_total += inv.total_chf

    invoice_totals = {
        "subtotal_chf": f"{sum_subtotal:.2f}",
        "vat_chf": f"{sum_vat:.2f}",
        "total_chf": f"{sum_total:.2f}",
    }

    savings = _compute_savings(participant, zev, year)

    owner_participant = zev.participants.filter(user=zev.owner).first()

    monthly_chart_svg = _build_monthly_chart_svg(monthly_data, tr)

    context = {
        "lang": lang,
        "tr": tr,
        "year": year,
        "zev": zev,
        "participant": participant,
        "owner_participant": owner_participant,
        "monthly_data": monthly_data,
        "totals": totals,
        "monthly_chart_svg": monthly_chart_svg,
        "invoices": invoice_rows,
        "invoice_totals": invoice_totals,
        "savings": savings,
        "formatted_dates": {
            "statement_date": _format_date_value(date.today(), date_pattern),
        },
    }

    html_string = _render_template(ANNUAL_STATEMENT_TEMPLATE, context)
    pdf_bytes = HTML(string=html_string, base_url=".").write_pdf()
    return pdf_bytes
