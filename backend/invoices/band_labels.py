"""Naming a tariff price band in a participant-facing document.

The participation contract lists a tariff's bands and their prices; an invoice
that itemises its bands has to call them the same thing, or the two documents
describe the same tariff in two vocabularies. Both therefore go through
``band_description`` rather than each formatting bands their own way.

The wording lives in ``CONTRACT_TRANSLATIONS`` because the contract needed it
first. ``translations_for`` is here so a caller that only has a language code
does not have to reach into that module itself.
"""

from tariffs.models import PeriodType
from tariffs.periods import hhmm, month_ranges, months_of

from .contract_translations import CONTRACT_TRANSLATIONS


def translations_for(lang: str) -> dict:
    """The band vocabulary for ``lang``, falling back to German."""
    return CONTRACT_TRANSLATIONS.get(lang, CONTRACT_TRANSLATIONS["de"])


def band_window(period, tr: dict) -> str:
    """``07:00-21:00``, or the generic band name when the band has no window."""
    if period.time_from and period.time_to:
        return f"{hhmm(period.time_from)}–{hhmm(period.time_to)}"
    return tr["tariff_band"]


def band_description(period, tr: dict) -> str:
    """The band's name, qualified by its season when it has one.

    HT and NT are named; a plain band is not, because the tariff it came from
    does not name its bands either. Such a band is called by its own label if
    one was given, and otherwise by the window that distinguishes it — which a
    contract has to state in any case.
    """
    label = {
        PeriodType.FLAT: tr["tariff_flat"],
        PeriodType.HIGH: tr["tariff_ht"],
        PeriodType.LOW: tr["tariff_nt"],
    }.get(period.period_type)
    if label is None:
        label = period.label or band_window(period, tr)

    ranges = month_ranges(months_of(period))
    if not ranges:
        return label

    names = tr["tariff_months_short"]
    season = ", ".join(
        names[first - 1] if first == last else f"{names[first - 1]}–{names[last - 1]}"
        for first, last in ranges
    )
    return tr["tariff_season"].format(label=label, season=season)
