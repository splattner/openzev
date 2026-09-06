"""Tariff overview PDF: every tariff of a ZEV, as of a date, for printing.

Every other participant-facing document a ZEV produces — invoice, annual
statement, financial summary, participation contract — has a printable form.
The tariffs did not: they existed only as rows on the Tariffs page. This is a
projection of what ``Tariff`` and ``TariffPeriod`` already store; nothing new
is computed here except the percentage-of-energy effective price, which goes
through ``tariff_pricing`` so this document and the participation contract
cannot print two different answers for the same tariff.

Unlike the invoice, contract and annual statement, this is not a customisable
``PdfTemplate`` — see ``docs/specs/2026-09-tariff-overview-pdf.md`` §10 for why.

See ``docs/specs/2026-09-tariff-overview-pdf.md`` for the full design.
"""
from datetime import date
from decimal import Decimal

from django.template.loader import render_to_string
from django.utils import timezone

from accounts.models import AppSettings
from tariffs.models import BillingMode, EnergyType, SplitKey, TariffCategory
from zev.models import VatMode

from .band_labels import band_description, band_recurrence, translations_for
from .dates import format_date_value
from .pdf_render import render_pdf
from .pdf_translations import INVOICE_TRANSLATIONS
from .tariff_overview_translations import TARIFF_OVERVIEW_TRANSLATIONS
from .tariff_pricing import display_grid_base_chf_per_kwh, grid_base_is_multiband

TARIFF_OVERVIEW_TEMPLATE = "invoices/tariff_overview_pdf.html"

# Same order the invoice groups its line items in
# (pdf._group_items_by_category), so a reader holding both documents sees
# categories in the same sequence.
_CATEGORY_ORDER = [
    TariffCategory.ENERGY,
    TariffCategory.GRID_FEES,
    TariffCategory.LEVIES,
    TariffCategory.METERING,
]

_FEE_UNIT_BY_MODE = {
    BillingMode.MONTHLY_FEE: "unit_chf_month",
    BillingMode.YEARLY_FEE: "unit_chf_year",
    BillingMode.PER_METERING_POINT_MONTHLY_FEE: "unit_chf_month",
    BillingMode.PER_METERING_POINT_YEARLY_FEE: "unit_chf_year",
    BillingMode.SHARED_MONTHLY_FEE: "unit_chf_month",
    BillingMode.SHARED_YEARLY_FEE: "unit_chf_year",
}

_SHARED_MODES = {BillingMode.SHARED_MONTHLY_FEE, BillingMode.SHARED_YEARLY_FEE}
_PER_METERING_POINT_MODES = {
    BillingMode.PER_METERING_POINT_MONTHLY_FEE,
    BillingMode.PER_METERING_POINT_YEARLY_FEE,
}


def _is_active(tariff, as_of: date) -> bool:
    if tariff.valid_from > as_of:
        return False
    if tariff.valid_to is not None and tariff.valid_to < as_of:
        return False
    return True


def _select_tariffs(zev, as_of: date, scope: str) -> list:
    tariffs = list(zev.tariffs.prefetch_related("periods").all())
    if scope == "all":
        return tariffs
    return [t for t in tariffs if _is_active(t, as_of)]


def _validity_display(tariff, tr: dict, date_pattern: str) -> str:
    valid_from = format_date_value(tariff.valid_from, date_pattern)
    if tariff.valid_to:
        valid_to = format_date_value(tariff.valid_to, date_pattern)
        return tr["valid_span"].format(start=valid_from, end=valid_to)
    return tr["valid_open"].format(date=valid_from)


def _price_rows_for_energy_tariff(tariff, tr: dict, band_tr: dict) -> list[dict]:
    # One row per band, never an average — this is the same principle #546
    # established for the invoice: a participant must be able to look up the
    # exact figure they were quoted, not a blend of several. Band wording goes
    # through band_labels' own vocabulary (band_tr = CONTRACT_TRANSLATIONS),
    # not this document's own translations, so the overview, the contract and
    # the band-itemised invoice name one band one way.
    return [
        {
            "label": band_description(period, band_tr),
            "recurrence": band_recurrence(period, band_tr),
            "amount": f"{float(period.price_chf_per_kwh) * 100:.2f}",
            "unit": tr["unit_rp"],
            "footnote": None,
        }
        for period in tariff.periods.all()
    ]


def _price_row_for_percentage_tariff(
    tariff, tr: dict, grid_sum_chf: Decimal, multiband_base: bool
) -> dict:
    pct = Decimal(str(tariff.percentage or 0))
    if grid_sum_chf > 0:
        effective_rp = grid_sum_chf * (pct / Decimal("100")) * Decimal("100")
        grid_rp = grid_sum_chf * Decimal("100")
        return {
            "label": f"{float(pct):.2f} % × {float(grid_rp):.2f} {tr['unit_rp']}",
            "recurrence": "",
            "amount": f"{float(effective_rp):.2f}",
            "unit": tr["unit_rp"],
            "footnote": "multiband_base" if multiband_base else None,
        }
    return {
        "label": f"{float(pct):.2f} {tr['unit_percent']}",
        "recurrence": "",
        "amount": f"{float(pct):.2f}",
        "unit": tr["unit_percent"],
        "footnote": "multiband_base" if multiband_base else None,
    }


def _price_row_for_fee_tariff(tariff, tr: dict) -> dict:
    # The label always states what the number means, not just what it is —
    # a SHARED_* fixed_price_chf is what the *community* pays, and printing
    # the bare figure without saying so would read as a per-participant
    # amount and be wrong by the size of the ZEV.
    if tariff.billing_mode in _PER_METERING_POINT_MODES:
        label = tr["fee_per_metering_point"]
    elif tariff.billing_mode in _SHARED_MODES:
        label = tr["fee_shared_weight"] if tariff.split_key == SplitKey.WEIGHT else tr["fee_shared_equal"]
    else:
        # A plain monthly/yearly fee has nothing left to qualify — the
        # tariff-row header already names the billing mode, and repeating it
        # here would just echo the same word back at the reader.
        label = ""

    amount = Decimal(str(tariff.fixed_price_chf or 0))
    return {
        "label": label,
        "recurrence": "",
        "amount": f"{float(amount):.2f}",
        "unit": tr[_FEE_UNIT_BY_MODE[tariff.billing_mode]],
        "footnote": None,
    }


def _label_is_redundant(tariff, price_row: dict, band_tr: dict) -> bool:
    """Whether a lone price row's label repeats what the tariff row says.

    Only the flat band qualifies: ``band_description`` calls it "Einheitstarif"
    to distinguish it from HT/NT, and a tariff with no other band has nothing
    to distinguish it from. A fee's label names its split key and a percentage
    row's label carries the formula, so both are kept.
    """
    return (
        tariff.billing_mode == BillingMode.ENERGY
        and price_row["label"] == band_tr["tariff_flat"]
        and not price_row["recurrence"]
    )


def _build_tariff_row(
    tariff, tr: dict, band_tr: dict, date_pattern: str, as_of: date,
    grid_sum_chf: Decimal, multiband_base: bool,
) -> dict | None:
    if tariff.billing_mode == BillingMode.ENERGY:
        price_rows = _price_rows_for_energy_tariff(tariff, tr, band_tr)
        if not price_rows:
            # A tariff with no bands has nothing to print — skip it rather
            # than emit a header with an empty table underneath.
            return None
    elif tariff.billing_mode == BillingMode.PERCENTAGE_OF_ENERGY:
        price_rows = [_price_row_for_percentage_tariff(tariff, tr, grid_sum_chf, multiband_base)]
    else:
        price_rows = [_price_row_for_fee_tariff(tariff, tr)]

    # A tariff with one price needs no second line to put it on: the price
    # goes on the tariff's own row and the table halves in height. Most
    # tariffs are this shape — a levy or a fee has exactly one number — so
    # the two-row form is the exception, not the default.
    inline_price = price_rows[0] if len(price_rows) == 1 else None
    if inline_price is not None and _label_is_redundant(tariff, inline_price, band_tr):
        # "Flat rate" under a tariff that has no other band says nothing the
        # single row does not already say.
        inline_price = {**inline_price, "label": ""}

    return {
        "name": tariff.name,
        "validity": _validity_display(tariff, tr, date_pattern),
        "billing_mode_label": tr["billing_modes"].get(tariff.billing_mode, tariff.get_billing_mode_display()),
        "is_current": _is_active(tariff, as_of),
        "notes": tariff.notes,
        "price_rows": price_rows,
        "inline_price": inline_price,
    }


def _grid_base(tariffs: list, as_of: date) -> tuple[Decimal, bool]:
    """The static display base for percentage-of-energy tariffs, and whether
    it approximates a multi-band grid tariff (see ``tariff_pricing``).

    Computed once against ``as_of`` — not per row — so a superseded
    percentage-of-energy version shown under ``scope=all`` reads against the
    same reference the current version does, matching how the participation
    contract has always treated it (one document, one reference date).

    Selected by energy type and billing mode only, deliberately *not* by
    category. What a percentage-of-grid tariff is a percentage *of* is the
    whole grid price a participant would otherwise pay — the Arbeitspreis plus
    Netznutzung plus every levy — and a Swiss grid tariff sheet spreads those
    across the GRID_FEES and LEVIES categories. Filtering to ENERGY keeps only
    the Arbeitspreis and understates the base by whatever the network charges
    and levies come to, which on a real ZEV is more than half of it. The engine
    (``TariffResolver``) and the participation contract both select this way;
    see docs/specs/2026-09-tariff-overview-pdf.md §6.1.
    """
    grid_tariffs = [
        t for t in tariffs
        if t.energy_type == EnergyType.GRID
        and t.billing_mode == BillingMode.ENERGY
        and _is_active(t, as_of)
    ]
    return display_grid_base_chf_per_kwh(grid_tariffs), grid_base_is_multiband(grid_tariffs)


def _vat_display(zev, tr: dict) -> tuple[str, str | None]:
    if zev.vat_mode == VatMode.REGISTERED:
        label = tr["vat_registered"]
        if zev.vat_number:
            label = f"{label} ({zev.vat_number})"
        return label, tr["vat_note_registered"]
    if zev.vat_mode == VatMode.INCLUSIVE:
        return tr["vat_inclusive"], tr["vat_note_inclusive"]
    return tr["vat_not_registered"], None


def _build_template_context(zev, as_of: date, scope: str) -> dict:
    lang = zev.invoice_language or "de"
    tr = dict(TARIFF_OVERVIEW_TRANSLATIONS.get(lang, TARIFF_OVERVIEW_TRANSLATIONS["de"]))
    # Category labels are read from the invoice's own translations rather than
    # duplicated here, so the overview and the invoice cannot describe the
    # same category with two different words.
    inv_tr = INVOICE_TRANSLATIONS.get(lang, INVOICE_TRANSLATIONS["de"])
    band_tr = translations_for(lang)
    cat_labels = {
        TariffCategory.ENERGY: inv_tr["cat_energy"],
        TariffCategory.GRID_FEES: inv_tr["cat_grid_fees"],
        TariffCategory.LEVIES: inv_tr["cat_levies"],
        TariffCategory.METERING: inv_tr["cat_metering"],
    }

    date_pattern = AppSettings.load().date_format_short
    tariffs = _select_tariffs(zev, as_of, scope)
    grid_sum_chf, multiband_base = _grid_base(tariffs, as_of)

    ordered = sorted(
        tariffs,
        key=lambda t: (
            _CATEGORY_ORDER.index(t.category) if t.category in _CATEGORY_ORDER else len(_CATEGORY_ORDER),
            t.name,
            -t.valid_from.toordinal(),
        ),
    )

    groups = []
    for category in _CATEGORY_ORDER:
        rows = [
            row for row in (
                _build_tariff_row(t, tr, band_tr, date_pattern, as_of, grid_sum_chf, multiband_base)
                for t in ordered
                if t.category == category
            )
            if row is not None
        ]
        if rows:
            groups.append({"key": category, "label": cat_labels[category], "tariffs": rows})

    # Footnotes are numbered by first appearance and only printed if actually
    # referenced, so a ZEV with no multi-band grid tariff sees no footnote at
    # all.
    used = []
    for group in groups:
        for tariff_row in group["tariffs"]:
            for price_row in tariff_row["price_rows"]:
                if price_row["footnote"] and price_row["footnote"] not in used:
                    used.append(price_row["footnote"])
    footnote_index = {key: i + 1 for i, key in enumerate(used)}
    for group in groups:
        for tariff_row in group["tariffs"]:
            for price_row in tariff_row["price_rows"]:
                if price_row["footnote"]:
                    price_row["footnote_index"] = footnote_index[price_row["footnote"]]
    footnotes = [(footnote_index[key], tr[f"footnote_{key}"]) for key in used]

    vat_display, vat_note = _vat_display(zev, tr)
    as_of_display = format_date_value(as_of, date_pattern)

    # One date, and it is ``as_of``: that is the date the prices are true on,
    # which is the only one a reader of a tariff sheet needs. The generation
    # date, the "valid as of" restatement and the footer copy all said the
    # same thing three more times.
    return {
        "zev": zev,
        "tr": tr,
        "as_of_display": as_of_display,
        "scope": scope,
        "groups": groups,
        "vat_display": vat_display,
        "vat_note": vat_note,
        "footnotes": footnotes,
    }


def generate_tariff_overview_pdf(zev, as_of: date | None = None, scope: str = "valid") -> bytes:
    """Render the tariff overview to PDF/A bytes.

    ``as_of`` defaults to today; ``scope`` is ``"valid"`` (tariffs in force on
    ``as_of``, the default) or ``"all"`` (every version, superseded ones shown
    muted).
    """
    as_of = as_of or timezone.localdate()
    context = _build_template_context(zev, as_of, scope)
    html_string = render_to_string(TARIFF_OVERVIEW_TEMPLATE, context)
    return render_pdf(html_string)
