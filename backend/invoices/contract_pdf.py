"""
Contract PDF generation for ZEV participation agreements.
Renders an HTML template via Django's template engine and converts it to PDF
using WeasyPrint.
"""
from decimal import Decimal

from django.template.loader import render_to_string
from django.template import Template, Context
from django.utils import timezone

from accounts.models import AppSettings, VatRate
from .contract_translations import CONTRACT_TRANSLATIONS
from .dates import format_date_value
from .pdf_render import render_pdf

from tariffs.models import BillingMode, EnergyType, PeriodType
from zev.models import MeteringPointType

CONTRACT_TEMPLATE_NAME = "contracts/participant_contract_pdf.html"


def _build_local_tariff_display(zev, tr: dict, date_pattern: str) -> list[dict]:
    """Return a list of display rows for all active local energy tariffs of the ZEV.

    Each row: {"name", "rate_rp", "rate_description", "pct", "unit",
    "valid_from", "valid_to", "validity", "notes"}. For percentage-of-energy
    tariffs the effective price is computed from the active GRID energy tariffs
    and the calculation formula is included; unit is empty when no grid base
    price exists (the rate then displays as a bare percentage). validity is the
    formatted validity span (open-ended tariffs render via tr["tariff_valid_open"]);
    notes forwards Tariff.notes so a configured reference product can be
    printed in clause 5.
    """
    today = timezone.localdate()
    rows = []

    # Fetch all tariffs once and partition in Python. The grid base price for
    # percentage tariffs is shared by every local tariff, so it is computed a
    # single time instead of once per percentage row.
    tariffs = list(zev.tariffs.prefetch_related("periods").all())

    def _active(t, *, local):
        if t.valid_from > today or (t.valid_to is not None and t.valid_to < today):
            return False
        return t.energy_type == (EnergyType.LOCAL if local else EnergyType.GRID)

    local_tariffs = [
        t for t in tariffs
        if _active(t, local=True)
        and t.billing_mode in (BillingMode.ENERGY, BillingMode.PERCENTAGE_OF_ENERGY)
    ]
    grid_tariffs = [
        t for t in tariffs
        if _active(t, local=False) and t.billing_mode == BillingMode.ENERGY
    ]

    # Sum the flat / HT prices of active GRID tariffs once: this is the base
    # price every percentage-of-grid-tariff local tariff is computed from.
    grid_sum_chf = Decimal("0")
    for gt in grid_tariffs:
        periods = list(gt.periods.all())
        flat = next((p for p in periods if p.period_type == PeriodType.FLAT), None)
        if flat:
            grid_sum_chf += Decimal(str(flat.price_chf_per_kwh))
        else:
            ht = next((p for p in periods if p.period_type == PeriodType.HIGH), None)
            if ht:
                grid_sum_chf += Decimal(str(ht.price_chf_per_kwh))
            elif periods:
                grid_sum_chf += Decimal(str(periods[0].price_chf_per_kwh))

    rp_unit = tr.get("tariff_rp_unit", "Rp./kWh")

    for tariff in local_tariffs:
        valid_from_display = format_date_value(tariff.valid_from, date_pattern)
        valid_to_display = (
            format_date_value(tariff.valid_to, date_pattern) if tariff.valid_to else None
        )
        base_row = {
            "name": tariff.name,
            "unit": tr["tariff_rp_unit"],
            "valid_from": valid_from_display,
            "valid_to": valid_to_display,
            "validity": (
                f"{valid_from_display} – {valid_to_display}"
                if valid_to_display
                else tr["tariff_valid_open"].format(date=valid_from_display)
            ),
            "notes": tariff.notes,
        }

        if tariff.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY:
            pct = Decimal(str(tariff.percentage or 0))

            effective_chf = grid_sum_chf * (pct / Decimal("100"))
            effective_rp = effective_chf * Decimal("100")
            grid_rp = grid_sum_chf * Decimal("100")

            if grid_sum_chf > 0:
                description = (
                    f"{float(pct):.2f}% × {float(grid_rp):.2f} {rp_unit}"
                    f" ({tr['tariff_pct_prefix'].strip('% ')})"
                )
            else:
                description = f"{float(pct):.2f}% {tr['tariff_pct_prefix']}"

            rows.append({
                **base_row,
                "rate_rp": f"{float(effective_rp):.2f}" if grid_sum_chf > 0 else f"{float(pct):.2f}%",
                "rate_description": description,
                "pct": f"{float(pct):.2f}",
                "unit": tr["tariff_rp_unit"] if grid_sum_chf > 0 else "",
            })
            continue

        periods = list(tariff.periods.all())
        if not periods:
            continue

        flat = next((p for p in periods if p.period_type == PeriodType.FLAT), None)
        if flat:
            rp = float(flat.price_chf_per_kwh) * 100
            rows.append({
                **base_row,
                "rate_rp": f"{rp:.2f}",
                "rate_description": tr["tariff_flat"],
                "pct": None,
            })
        else:
            ht = next((p for p in periods if p.period_type == PeriodType.HIGH), None)
            nt = next((p for p in periods if p.period_type == PeriodType.LOW), None)
            if ht:
                rp = float(ht.price_chf_per_kwh) * 100
                rows.append({
                    **base_row,
                    "rate_rp": f"{rp:.2f}",
                    "rate_description": tr["tariff_ht"],
                    "pct": None,
                })
            if nt:
                rp = float(nt.price_chf_per_kwh) * 100
                rows.append({
                    **base_row,
                    "rate_rp": f"{rp:.2f}",
                    "rate_description": tr["tariff_nt"],
                    "pct": None,
                })

    return rows


def _build_contract_context(participant) -> dict:
    from zev.models import MeteringPoint, MeteringPointAssignment

    zev = participant.zev
    lang = zev.invoice_language or "de"
    # Copied rather than used in place: CONTRACT_TRANSLATIONS is a module-level
    # constant shared by every contract, and payment_terms_unit is resolved
    # per-ZEV below — writing it back into the shared dict would leak one
    # ZEV's payment term into every other contract rendered afterwards.
    tr = dict(CONTRACT_TRANSLATIONS.get(lang, CONTRACT_TRANSLATIONS["de"]))
    tr["payment_terms_unit"] = (
        tr["payment_terms_unit_sg"] if zev.payment_term_days == 1 else tr["payment_terms_unit_pl"]
    )
    # Retention table rows are zipped from parallel lists: the category labels
    # are translated per locale, so they cannot be dict keys (the locale-parity
    # test requires identical keys). Order is contractually significant — both
    # lists must stay in sync.
    tr["privacy_retention_rows"] = list(
        zip(tr["privacy_retention_categories"], tr["privacy_retention_periods"])
    )

    # ZEV owner as participant (for address details)
    owner_participant = zev.participants.filter(user=zev.owner).first()

    # The contract PDF is generated on demand, so "today" doubles as the issue
    # date. localdate() applies Django's configured timezone (Europe/Zurich)
    # rather than the server's, so the document date matches the business
    # calendar.
    today = timezone.localdate()

    # Include all non-ended assignments so the contract can be prefilled for
    # participants who start on a future meter assignment.
    assigned_mp_ids = set(
        MeteringPointAssignment.objects.filter(
            participant=participant,
        ).filter(
            valid_to__isnull=True,
        ).values_list("metering_point_id", flat=True)
    ) | set(
        MeteringPointAssignment.objects.filter(
            participant=participant,
            valid_to__gte=today,
        ).values_list("metering_point_id", flat=True)
    )

    all_mps = list(MeteringPoint.objects.filter(id__in=assigned_mp_ids))

    consumption_mps = [
        mp for mp in all_mps
        if mp.meter_type in (MeteringPointType.CONSUMPTION, MeteringPointType.BIDIRECTIONAL)
    ]
    production_mps = [
        mp for mp in all_mps
        if mp.meter_type in (MeteringPointType.PRODUCTION, MeteringPointType.BIDIRECTIONAL)
    ]

    # Dates follow the same AppSettings patterns as the invoice PDF so both
    # documents print identically formatted dates.
    app_settings = AppSettings.load()
    date_pattern = app_settings.date_format_short

    local_tariff_rows = _build_local_tariff_display(zev, tr, date_pattern)
    billing_interval_display = tr["billing_intervals"].get(
        zev.billing_interval, zev.billing_interval
    )
    contract_date = format_date_value(today, date_pattern)

    # Clause-5 tariff rule, derived from the first active local tariff so the
    # green box, tariff table and clause always agree on the governing rule: a
    # percentage-of-grid-tariff tariff prints the formula (with the configured
    # percentage rendered), a fixed tariff the flat-rate clause. The reference
    # product from Tariff.notes is printed when the manager configured one.
    first_tariff_row = local_tariff_rows[0] if local_tariff_rows else None
    tariff_rule = None
    tariff_pct_line = None
    tariff_reference_product = None
    if first_tariff_row:
        if first_tariff_row["pct"]:
            pct = first_tariff_row["pct"]
            tariff_rule = tr["clause_tariff_rule_pct"].format(pct=pct)
            tariff_pct_line = tr["tariff_pct_of"].format(pct=pct)
        else:
            tariff_rule = tr["clause_tariff_rule_flat"]
        tariff_reference_product = first_tariff_row["notes"] or None

    # Effective participation start: earliest metering-point assignment start,
    # falling back to the participant's own validity start.
    first_assignment_start = MeteringPointAssignment.objects.filter(
        participant=participant,
    ).order_by("valid_from").values_list("valid_from", flat=True).first()
    participation_start = format_date_value(first_assignment_start or participant.valid_from, date_pattern)

    # Short document id for traceability on paper (a compact digest of the
    # participant's primary key, not the internal id itself).
    document_id = f"CTR-{str(participant.pk).replace('-', '')[:8].upper()}"

    # Show the currently active VAT rate when the ZEV is VAT-liable.
    vat_rate_display = ""
    if zev.vat_number:
        active_rate = VatRate.active_for_day(today)
        if active_rate is not None:
            vat_rate_display = f"{float(active_rate.rate) * 100:.2f} %"

    return {
        "participant": participant,
        "owner_participant": owner_participant,
        "zev": zev,
        "consumption_mps": consumption_mps,
        "production_mps": production_mps,
        "local_tariff_rows": local_tariff_rows,
        "tariff_rule": tariff_rule,
        "tariff_pct_line": tariff_pct_line,
        "tariff_reference_product": tariff_reference_product,
        "billing_interval_display": billing_interval_display,
        "contract_date": contract_date,
        "participation_start": participation_start,
        "document_id": document_id,
        "vat_rate_display": vat_rate_display,
        "tr": tr,
        "lang": lang,
        "local_tariff_notes": zev.local_tariff_notes or "",
        "additional_contract_notes": zev.additional_contract_notes or "",
    }


def _render_contract_html(participant) -> str:
    """Render the contract HTML for a participant (DB override wins)."""
    context = _build_contract_context(participant)
    # Import here to avoid circular imports at module load time
    from .models import PdfTemplate
    record = PdfTemplate.objects.filter(template_name=CONTRACT_TEMPLATE_NAME).first()
    if record:
        return Template(record.content).render(Context(context))
    return render_to_string(CONTRACT_TEMPLATE_NAME, context)


def generate_contract_pdf(participant) -> bytes:
    """Generate a participation contract PDF for the given participant."""
    return render_pdf(_render_contract_html(participant))
