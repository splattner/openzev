"""
Contract PDF generation for ZEV participation agreements.
Renders an HTML template via Django's template engine and converts it to PDF
using WeasyPrint.
"""
from datetime import date
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


def _build_local_tariff_display(zev, tr: dict, date_pattern: str, as_of: date) -> list[dict]:
    """Return a list of display rows for all active local energy tariffs of the ZEV.

    Each row: {"name", "rate_rp", "rate_description", "pct", "unit",
    "valid_from", "valid_to", "validity", "notes"}. For percentage-of-energy
    tariffs the effective price is computed from the active GRID energy tariffs
    and the calculation formula is included; unit is empty when no grid base
    price exists (the rate then displays as a bare percentage). validity is the
    formatted validity span (open-ended tariffs render via tr["tariff_valid_open"]);
    notes forwards Tariff.notes so a configured reference product can be
    printed in clause 5. Tariffs are filtered against ``as_of`` so a re-download
    reproduces the issued document rather than today's state.
    """
    rows = []

    # Fetch all tariffs once and partition in Python. The grid base price for
    # percentage tariffs is shared by every local tariff, so it is computed a
    # single time instead of once per percentage row.
    tariffs = list(zev.tariffs.prefetch_related("periods").all())

    def _active(t, *, local):
        if t.valid_from > as_of or (t.valid_to is not None and t.valid_to < as_of):
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


def _build_contract_context(participant, document_id: str | None = None,
                            as_of: date | None = None) -> dict:
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

    # The effective issue date: "today" for a fresh render, the snapshot's
    # rendered_on for a change-detection re-render. Every date-sensitive lookup
    # below (assignment filtering, contract date, active VAT rate, active
    # tariffs) goes through as_of so the re-render reproduces the issued
    # document byte-for-byte — the passing of time alone never mints a version.
    # localdate() applies Django's configured timezone (Europe/Zurich) rather
    # than the server's, so the document date matches the business calendar.
    as_of = as_of or timezone.localdate()

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
            valid_to__gte=as_of,
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

    local_tariff_rows = _build_local_tariff_display(zev, tr, date_pattern, as_of)
    billing_interval_display = tr["billing_intervals"].get(
        zev.billing_interval, zev.billing_interval
    )
    contract_date = format_date_value(as_of, date_pattern)

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

    # Short document id for traceability on paper. Issued contracts carry the
    # stable per-ZEV document number; the pure render path falls back to a
    # compact digest of the participant's primary key.
    if document_id is None:
        document_id = f"CTR-{str(participant.pk).replace('-', '')[:8].upper()}"

    # Show the currently active VAT rate when the ZEV is VAT-liable.
    vat_rate_display = ""
    if zev.vat_number:
        active_rate = VatRate.active_for_day(as_of)
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


def _render_contract_html(participant, document_id: str | None = None,
                          as_of: date | None = None) -> str:
    """Render the contract HTML for a participant (DB override wins)."""
    context = _build_contract_context(participant, document_id=document_id, as_of=as_of)
    # Import here to avoid circular imports at module load time
    from .models import PdfTemplate
    record = PdfTemplate.objects.filter(template_name=CONTRACT_TEMPLATE_NAME).first()
    if record:
        return Template(record.content).render(Context(context))
    return render_to_string(CONTRACT_TEMPLATE_NAME, context)


def generate_contract_pdf(participant, document_id: str | None = None) -> bytes:
    """Generate a participation contract PDF for the given participant.

    Pure render: always re-derives the current state. Issued documents should
    go through :func:`issue_contract_pdf`, which freezes a versioned snapshot.
    """
    return render_pdf(_render_contract_html(participant, document_id=document_id))


def _record_number_gap(participant, skipped_number, reused_issue, issued_by):
    """Audit a document number that was minted but never used.

    Happens when two concurrent issuances race for identical content: both
    mint a number under the Zev lock, but the second reuses the snapshot the
    first committed, leaving a gap in the per-ZEV sequence (e.g. ``0001``
    then ``0003``). The gap is accepted — never papered over by reusing
    numbers — but recorded so the sequence stays explainable.
    """
    from audit.models import AuditActionCategory, AuditEventSource
    from audit.services import record_audit_event

    record_audit_event(
        action_category=AuditActionCategory.PARTICIPANT,
        action_type="contract.number_gap",
        target_type="zev.Participant",
        target_id=str(participant.pk),
        target_display=participant.full_name,
        summary=(
            f"Contract number {skipped_number} minted but unused "
            f"(identical snapshot v{reused_issue.version} reused); accepted sequence gap."
        ),
        user=issued_by,
        zev=participant.zev,
        source=AuditEventSource.SYSTEM,
        metadata={
            "zev_id": str(participant.zev_id),
            "skipped_document_number": skipped_number,
            "reused_version": reused_issue.version,
            "reused_document_number": reused_issue.document_number,
        },
    )


def issue_contract_pdf(participant, issued_by=None) -> tuple:
    """Return the frozen participation-contract snapshot for ``participant``.

    Unchanged re-downloads reuse the latest stored snapshot (same rendered
    HTML hash); any data or template change mints a new version with the next
    per-ZEV document number. ``issued_by`` is recorded on the snapshot for
    traceability. Returns ``(ContractIssue, created: bool)``.
    """
    from hashlib import sha256

    from django.db import transaction

    from .models import ContractIssue

    zev = participant.zev

    # One issue date per issuance, resolved through Django's configured
    # timezone: the rendered document date, the document-number year and the
    # frozen rendered_on must all agree — three separate date.today() calls
    # could straddle midnight around the turn of a business day.
    issue_date = timezone.localdate()

    def _matches_issue(issue) -> bool:
        """True when a re-render of ``issue`` (its document number and its
        issue date) still produces exactly the stored HTML. Rendering at the
        issue date rather than today keeps the passing of time out of the
        change detection: a calendar day alone never mints a version."""
        html = _render_contract_html(
            participant, document_id=issue.document_number, as_of=issue.rendered_on
        )
        return sha256(html.encode("utf-8")).hexdigest() == issue.context_hash

    latest = ContractIssue.objects.filter(participant=participant).order_by("-version").first()
    if latest and _matches_issue(latest):
        return latest, False

    # Number minting and issue creation share one transaction. The number is
    # minted under a row lock (see Zev.next_contract_number), which serializes
    # concurrent issuances for the same ZEV. ``latest`` is re-read and
    # re-compared under that lock — before minting and again after it — so a
    # competing issuance that committed while we waited is either reused
    # (identical content mints no redundant version) or taken into account for
    # the next version. A lost race can never collide on ``(participant,
    # version)``. If rendering or creation fails, the counter bump rolls back
    # with it.
    with transaction.atomic():
        latest = ContractIssue.objects.filter(participant=participant).order_by("-version").first()
        if latest and _matches_issue(latest):
            return latest, False
        year = issue_date.year
        document_number = zev.next_contract_number(year=year)
        # Re-read after minting: the Zev row lock serializes issuances, so any
        # competing issue that committed while we waited is visible now. A
        # competitor that landed the identical document is reused (no redundant
        # version; the unused counter bump is an accepted number gap, written
        # to the audit stream so the sequence is explainable); a competitor
        # with different content is taken into account for the version
        # derivation below.
        latest = ContractIssue.objects.filter(participant=participant).order_by("-version").first()
        if latest and _matches_issue(latest):
            _record_number_gap(participant, document_number, latest, issued_by)
            return latest, False
        html = _render_contract_html(participant, document_id=document_number, as_of=issue_date)
        digest = sha256(html.encode("utf-8")).hexdigest()

        issue = ContractIssue.objects.create(
            zev=zev,
            participant=participant,
            version=(latest.version + 1) if latest else 1,
            document_number=document_number,
            language=zev.invoice_language or "de",
            rendered_on=issue_date,
            context_hash=digest,
            pdf=render_pdf(html),
            issued_by=issued_by,
        )
    return issue, True
