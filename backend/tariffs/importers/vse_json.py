"""
Parser and mapper for the VSE/AES machine-readable tariff standard.

Since 2025 every Swiss grid operator must publish its grid-usage, energy,
metering and public-authority tariffs machine-readably by 31 August (Art. 7b
StromVV). The shape is defined in NNMV-CH 2025 Annex 10 and published as an
OpenAPI 3.0.3 document; the OpenAPI definition is the normative one — the
annex's example has already drifted from it — so this module validates
against the OpenAPI shape but parses defensively, accepting the drifted
spellings too (see ``_parse_iso_or_swiss_date`` and ``_price_of``).

The module is pure: it turns a decoded JSON payload into ``Candidate``
objects describing the OpenZEV tariffs that *would* be created. Nothing here
touches the database or the network — planning against existing tariffs lives
in ``tariffs.importers.planner``, fetching in ``tariffs.importers.remote`` —
so the mapping, which is the part that silently changes what participants are
billed, can be tested on its own.

Reference: https://tariffconverter.strom.ch/ch-electricity-tariffs-openapi.yml
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from tariffs.models import BillingMode, EnergyType, PeriodType, TariffCategory
from tariffs.periods import ALL_MONTHS, format_number_list

#: A standard entry carrying both a base fee and a per-kWh price becomes *two*
#: OpenZEV tariffs, because ``Tariff`` has a single ``billing_mode``. The
#: suffix is applied even when only one component is present, so that a
#: document which grows a base price next year still appends to the same
#: series instead of forking it under a bare name. These strings end up as
#: invoice line labels, hence the Swiss-German billing vocabulary.
BASE_COMPONENT_SUFFIX = "Grundpreis"
ENERGY_COMPONENT_SUFFIX = "Arbeitspreis"

MAX_TARIFF_NAME_LENGTH = 200  # Tariff.name max_length

CATEGORY_BY_TARIFF_TYPE = {
    # A DSO's own supply is grid energy from the ZEV's point of view: the
    # community buys it through its grid connection, not from its own roof.
    "electricity": TariffCategory.ENERGY,
    "grid": TariffCategory.GRID_FEES,
    "metering": TariffCategory.METERING,
    "regional_fees": TariffCategory.LEVIES,
}

#: What a ``CHF/M`` base price may be billed as. All three are *monthly*: the
#: published price is an amount per month, so the yearly modes — which read
#: ``fixed_price_chf`` as a per-year amount — would be off by a factor of
#: twelve. The user picks in the import preview; the default is first.
#:
#: ``shared_monthly_fee`` leads because the grid operator bills the community
#: once for its connection, and a plain ``monthly_fee`` would collect that
#: amount from every participant. But a vZEV whose participants each hold
#: their own DSO contract wants ``monthly_fee``, and a per-meter charge — the
#: Messtarif is one — wants ``per_metering_point_monthly_fee``. There is no
#: way to tell which from the document, so the choice is the user's.
FEE_BILLING_MODE_OPTIONS = (
    BillingMode.SHARED_MONTHLY_FEE,
    BillingMode.MONTHLY_FEE,
    BillingMode.PER_METERING_POINT_MONTHLY_FEE,
)

WEEKDAY_NUMBERS = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}
MONTH_NUMBERS = {
    name: index
    for index, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1
    )
}

ENERGY_PRICE_QUANTUM = Decimal("0.00001")  # TariffPeriod.price_chf_per_kwh
FEE_PRICE_QUANTUM = Decimal("0.01")  # Tariff.fixed_price_chf

#: Minutes-of-day marking the end of the day. The standard writes it as
#: ``"23:59"``; a constant price instead writes ``from``/``to`` both ``00:00``.
END_OF_DAY_MINUTES = 24 * 60


class TariffDocumentError(Exception):
    """The payload is not a usable VSE/AES tariff document at all.

    Raised only for whole-document problems. A single malformed entry must not
    stop the import of the one the ZEV actually needs, so entry-level failures
    are collected in ``ParsedDocument.errors`` instead.
    """


@dataclass
class ProposedPeriod:
    """A ``TariffPeriod`` the import would create."""

    period_type: str
    price_chf_per_kwh: Decimal
    time_from: time | None
    time_to: time | None
    weekdays: str
    #: Comma-separated month numbers, blank for a band that applies all year.
    months: str = ""


@dataclass
class Candidate:
    """One OpenZEV tariff the import would create, with everything a reviewer
    needs to judge it before it starts pricing invoices."""

    #: Stable across a preview/apply round-trip because it is built from the
    #: same pair that decides idempotency: proposed name and start date.
    key: str
    name: str
    category: str
    billing_mode: str
    energy_type: str | None
    fixed_price_chf: Decimal | None
    valid_from: date
    valid_to: date | None
    notes: str
    periods: list[ProposedPeriod] = field(default_factory=list)

    # Provenance, shown in the preview so the user can tell two similarly
    # named customer groups apart.
    source_tariff_name: str = ""
    source_tariff_type: str = ""
    source_customer_type: str = ""
    source_voltage_level: int | None = None
    standard_basegroup: bool = False

    #: Billing modes the user may choose instead of ``billing_mode``, empty
    #: when there is nothing to choose. The frontend renders exactly this list
    #: and the apply step accepts exactly this list, so the two cannot drift.
    billing_mode_options: tuple[str, ...] = ()

    warnings: list[str] = field(default_factory=list)
    #: Set when the entry cannot be represented at all. A blocked candidate is
    #: still returned — reporting *why* an entry was dropped is the point.
    blocked_reason: str | None = None

    @property
    def is_importable(self) -> bool:
        return self.blocked_reason is None

    @property
    def is_free(self) -> bool:
        """True when this candidate would bill nothing.

        Documents are full of ``0.00`` placeholders for components the
        operator does not charge; they are worth showing but not worth
        pre-selecting.
        """
        if self.billing_mode == BillingMode.ENERGY:
            return all(period.price_chf_per_kwh == 0 for period in self.periods)
        return not self.fixed_price_chf

    @property
    def recommended(self) -> bool:
        """Pre-selected in the wizard: the operator's own default product,
        priced above zero, and representable."""
        return self.standard_basegroup and self.is_importable and not self.is_free


@dataclass
class ParsedDocument:
    dso_name: str
    dso_number: int | None
    candidates: list[Candidate] = field(default_factory=list)
    #: Entry-level parse failures, ``{"tariff": name, "error": message}``.
    errors: list[dict] = field(default_factory=list)


# ── Scalar parsing ───────────────────────────────────────────────────────────


def _parse_iso_or_swiss_date(raw, label: str) -> date:
    """Accept ``2025-01-01`` and the annex example's ``01.01.2025``.

    The OpenAPI definition is normative and says ISO 8601, but the PDF annex
    prints the Swiss dotted form, and published documents follow whichever the
    operator's tooling emitted.
    """
    text = str(raw or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{label} is not a date this importer understands: {raw!r}")


def _decimal(raw, label: str) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not a number: {raw!r}") from exc
    if value < 0:
        raise ValueError(f"{label} is negative ({value}); the standard requires prices ≥ 0.")
    return value


def _quantize(value: Decimal, quantum: Decimal, label: str, warnings: list[str]) -> Decimal:
    """Round to what the column can hold, saying so when precision is lost.

    Published prices like ``0.0802`` fit comfortably, but an operator emitting
    a full float expansion must not have digits dropped without a word.
    """
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    if rounded != value:
        warnings.append(f"{label} was rounded from {value} to {rounded} to fit the stored precision.")
    return rounded


def _price_of(raw, label: str) -> tuple[Decimal, str]:
    """Read a ``SimplePrice``, tolerating the annex's bare number.

    Returns ``(price, unit)``; the unit is empty when the document gave a bare
    number, which callers treat as the field's documented default.
    """
    if isinstance(raw, dict):
        return _decimal(raw.get("price"), label), str(raw.get("priceUnit") or "").strip()
    return _decimal(raw, label), ""


def _minutes(raw, label: str) -> int:
    text = str(raw or "").strip()
    try:
        parsed = datetime.strptime(text, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"{label} is not a HH:MM time: {raw!r}") from exc
    return parsed.hour * 60 + parsed.minute


def _time_from_minutes(minutes: int) -> time:
    minutes = min(minutes, END_OF_DAY_MINUTES - 1)
    return time(hour=minutes // 60, minute=minutes % 60)


def _weekday_numbers(raw, label: str) -> list[int]:
    """``["Mo", "Tu"]`` → ``[0, 1]``; empty or absent means every day.

    Case-insensitive on purpose: the annex example writes ``mo``/``tu`` and
    ``ed`` for "every day" while the OpenAPI enum is ``Mo``/``Tu``.
    """
    if not raw:
        return list(range(7))
    numbers = set()
    for item in raw:
        code = str(item).strip().casefold()[:2]
        if code == "ed":  # annex spelling for "all days"
            return list(range(7))
        if code not in WEEKDAY_NUMBERS:
            raise ValueError(f"{label} has an unknown weekday {item!r}.")
        numbers.add(WEEKDAY_NUMBERS[code])
    return sorted(numbers)


def _month_numbers(raw, label: str) -> list[int]:
    if not raw:
        return list(range(1, 13))
    numbers = set()
    for item in raw:
        code = str(item).strip().casefold()[:3]
        if code not in MONTH_NUMBERS:
            raise ValueError(f"{label} has an unknown month {item!r}.")
        numbers.add(MONTH_NUMBERS[code])
    return sorted(numbers)


# ── Price bands ──────────────────────────────────────────────────────────────


class _Unsupported(Exception):
    """This entry parses fine but OpenZEV cannot represent it."""


@dataclass
class _Band:
    price: Decimal
    start: int  # minutes from midnight, inclusive
    end: int  # minutes from midnight, exclusive
    weekdays: list[int]
    months: frozenset[int]


def _parse_band(entry: dict, label: str) -> list[_Band]:
    """One ``TimeBasedPrice`` → the bands it covers.

    A window written backwards (``22:00``–``06:00``) wraps past midnight and is
    split in two, because ``TariffPeriod`` matches with ``from <= t < to`` and
    a single row spanning midnight would match nothing at all.
    """
    price, unit = _decimal(entry.get("price"), f"{label} price"), str(entry.get("priceUnit") or "").strip()
    if unit and unit.casefold() != "chf/kwh":
        raise _Unsupported(
            f"{label} is priced in {unit}; only CHF/kWh energy prices can be billed per kWh."
        )

    months = frozenset(_month_numbers(entry.get("months"), f"{label} months"))

    weekdays = _weekday_numbers(entry.get("weekdays"), f"{label} weekdays")
    start = _minutes(entry.get("from"), f"{label} from")
    end = _minutes(entry.get("to"), f"{label} to")

    if start == end:
        # The standard's constant marker: from and to both "00:00".
        return [_Band(price, 0, END_OF_DAY_MINUTES, weekdays, months)]
    if end == 0:
        end = END_OF_DAY_MINUTES
    if end == END_OF_DAY_MINUTES - 1:
        # "23:59" is the standard's spelling for end-of-day; taken literally it
        # would leave the last minute of the day unpriced.
        end = END_OF_DAY_MINUTES
    if start < end:
        return [_Band(price, start, end, weekdays, months)]
    return [
        _Band(price, start, END_OF_DAY_MINUTES, weekdays, months),
        _Band(price, 0, end, weekdays, months),
    ]


def _uncovered_hours(bands: list[_Band]) -> bool:
    """True when some weekday/hour combination has no band.

    Not fatal — the engine falls back to a tariff's first in-season period —
    but the fallback prices those hours at a band the document never meant for
    them, so the preview says so.
    """
    for weekday in range(7):
        spans = sorted((band.start, band.end) for band in bands if weekday in band.weekdays)
        reached = 0
        for start, end in spans:
            if start > reached:
                return True  # a hole before this span
            reached = max(reached, end)
        if reached < END_OF_DAY_MINUTES:
            return True
    return False


def _months_field(months: frozenset[int]) -> str:
    """``TariffPeriod.months`` — blank means every month, which is what the
    engine already assumes, so a year-round band stores nothing."""
    return "" if months == ALL_MONTHS else format_number_list(months)


def _weekday_field(weekdays: list[int]) -> str:
    """``TariffPeriod.weekdays`` — blank means every day, which is what the
    engine already assumes, so all-seven is stored as blank rather than
    ``"0,1,2,3,4,5,6"``."""
    return "" if len(weekdays) == 7 else ",".join(str(number) for number in weekdays)


def _map_energy_bands(entries: list, label: str, warnings: list[str]) -> list[ProposedPeriod]:
    """``prices.energy`` → the ``TariffPeriod`` rows that reproduce it.

    Bands are grouped by the months they apply in, and the flat/HT/NT question
    is answered **per season**. That is not a convenience: ``period_type`` only
    has to tell apart bands that compete for the same moment, and a winter band
    never competes with a summer one. A document pricing winter-HT, winter-NT,
    summer-HT and summer-NT therefore fits in four rows carrying two distinct
    prices each, even though it carries four distinct prices overall.
    """
    bands: list[_Band] = []
    for index, entry in enumerate(entries, start=1):
        bands.extend(_parse_band(entry, f"{label} energy price {index}"))

    if not bands:
        raise _Unsupported("The entry has no energy prices to import.")

    seasons: dict[frozenset[int], list[_Band]] = {}
    for band in bands:
        seasons.setdefault(band.months, []).append(band)

    # Grouping is by *exact* month set, so seasons that merely overlap — one
    # band for Jan–Jun and another for Mar–Sep — would be mapped as if they
    # never competed, and the engine would pick whichever sorted first for the
    # months they share. Refuse rather than guess.
    _reject_overlapping_seasons(list(seasons))

    covered = frozenset().union(*seasons) if seasons else frozenset()
    if covered != ALL_MONTHS:
        warnings.append(
            f"The document prices only {len(covered)} of 12 months; the remaining months "
            "will bill at this tariff's first band."
        )

    periods: list[ProposedPeriod] = []
    for months, season_bands in seasons.items():
        periods.extend(_map_one_season(months, season_bands, warnings, seasonal=len(seasons) > 1))
    return periods


def _reject_overlapping_seasons(month_sets: list[frozenset[int]]) -> None:
    for index, earlier in enumerate(month_sets):
        for later in month_sets[index + 1:]:
            shared = earlier & later
            if shared:
                raise _Unsupported(
                    "Two of the entry's price groups apply in the same months "
                    f"({format_number_list(sorted(shared))}), so which one prices those "
                    "months is ambiguous. Enter this tariff by hand."
                )


def _map_one_season(months: frozenset[int], bands: list[_Band], warnings: list[str],
                    *, seasonal: bool) -> list[ProposedPeriod]:
    """One month group → its ``TariffPeriod`` rows.

    ``PeriodType`` offers three slots — flat, HT, NT — so the number of
    *distinct prices* decides whether a season fits, not the number of windows.
    The document this was built against writes day, evening and night with two
    prices, and maps onto HT and NT cleanly.
    """
    where = f" in {format_number_list(sorted(months))}" if seasonal else ""
    months_field = _months_field(months)
    prices = sorted({band.price for band in bands})

    if len(prices) > 2:
        raise _Unsupported(
            f"The entry has {len(prices)} different energy prices{where}; OpenZEV tariffs "
            "carry at most a high (HT) and a low (NT) band per season."
        )

    if _uncovered_hours(bands):
        warnings.append(
            f"The document leaves part of the day unpriced{where}; those hours will bill "
            "at this tariff's first band."
        )

    if len(prices) == 1:
        # One price, however many windows it was written across, is flat for
        # this season. Storing it without times also spares the engine the
        # window match on every reading.
        return [
            ProposedPeriod(
                period_type=PeriodType.FLAT,
                price_chf_per_kwh=_quantize(
                    prices[0], ENERGY_PRICE_QUANTUM, "The energy price", warnings
                ),
                time_from=None,
                time_to=None,
                weekdays="",
                months=months_field,
            )
        ]

    low, high = prices
    warnings.append(
        f"The standard does not label its bands, so the higher price ({high} CHF/kWh) was "
        f"taken as the high tariff (HT) and the lower ({low} CHF/kWh) as the low tariff (NT)"
        f"{where}."
    )
    return [
        ProposedPeriod(
            period_type=PeriodType.HIGH if band.price == high else PeriodType.LOW,
            price_chf_per_kwh=_quantize(
                band.price, ENERGY_PRICE_QUANTUM, "An energy price", warnings
            ),
            time_from=_time_from_minutes(band.start),
            time_to=_time_from_minutes(band.end),
            weekdays=_weekday_field(band.weekdays),
            months=months_field,
        )
        for band in bands
    ]


# ── Entries → candidates ─────────────────────────────────────────────────────


def _tariff_name(base: str, suffix: str, warnings: list[str]) -> str:
    name = f"{base} ({suffix})"
    if len(name) <= MAX_TARIFF_NAME_LENGTH:
        return name
    keep = MAX_TARIFF_NAME_LENGTH - len(suffix) - 4  # " (…)" around the suffix
    name = f"{base[:keep].rstrip()}… ({suffix})"
    warnings.append("The published tariff name was too long and has been shortened.")
    return name


def _candidate(
    *,
    name: str,
    category: str,
    header: dict,
    warnings: list[str],
    billing_mode: str,
    billing_mode_options: tuple[str, ...] = (),
    energy_type: str | None = None,
    fixed_price_chf: Decimal | None = None,
    periods: list[ProposedPeriod] | None = None,
    blocked_reason: str | None = None,
) -> Candidate:
    valid_from = header["start_date"]
    # Deduplicated: per-band rounding notices otherwise repeat once per window.
    unique_warnings = list(dict.fromkeys(warnings))
    return Candidate(
        key=f"{name}@{valid_from.isoformat()}",
        name=name,
        category=category,
        billing_mode=billing_mode,
        billing_mode_options=billing_mode_options,
        energy_type=energy_type,
        fixed_price_chf=fixed_price_chf,
        valid_from=valid_from,
        valid_to=header["end_date"],
        notes=header["notes"],
        periods=periods or [],
        source_tariff_name=header["tariff_name"],
        source_tariff_type=header["tariff_type"],
        source_customer_type=header["customer_type"],
        source_voltage_level=header["voltage_level"],
        standard_basegroup=header["standard_basegroup"],
        warnings=unique_warnings,
        blocked_reason=blocked_reason,
    )


def _fee_candidate(raw_price, *, name: str, category: str, header: dict, label: str) -> Candidate:
    """A ``CHF/M`` base price → a monthly fee tariff."""
    warnings: list[str] = []
    try:
        price, unit = _price_of(raw_price, label)
        if unit and unit.casefold() != "chf/m":
            raise _Unsupported(
                f"{label} is given in {unit}; only CHF/M base prices map to a monthly fee."
            )
        fixed = _quantize(price, FEE_PRICE_QUANTUM, label, warnings)
    except (ValueError, _Unsupported) as exc:
        return _candidate(
            name=name, category=category, header=header, warnings=warnings,
            billing_mode=FEE_BILLING_MODE_OPTIONS[0], blocked_reason=str(exc),
        )

    # Which of FEE_BILLING_MODE_OPTIONS is right cannot be read off the
    # document — it depends on how this ZEV relates to its operator — so the
    # candidate offers all three and the preview asks.
    return _candidate(
        name=name, category=category, header=header, warnings=warnings,
        billing_mode=FEE_BILLING_MODE_OPTIONS[0],
        billing_mode_options=FEE_BILLING_MODE_OPTIONS,
        fixed_price_chf=fixed,
    )


def _energy_candidate(entries, *, name: str, category: str, header: dict, label: str) -> Candidate:
    warnings: list[str] = []
    try:
        periods = _map_energy_bands(list(entries), label, warnings)
    except (ValueError, _Unsupported) as exc:
        return _candidate(
            name=name, category=category, header=header, warnings=warnings,
            billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
            blocked_reason=str(exc),
        )
    return _candidate(
        name=name, category=category, header=header, warnings=warnings,
        billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID, periods=periods,
    )


def _dropped_component_warnings(prices: dict) -> list[str]:
    """Say which priced components the import leaves behind.

    Documents carry ``0.00`` placeholders for components the operator does not
    charge; only a component with actual money in it is worth reporting.
    """
    warnings = []

    def _has_money(entries) -> bool:
        for entry in entries or []:
            try:
                if _decimal((entry or {}).get("price"), "price") > 0:
                    return True
            except ValueError:
                return True  # unreadable is not the same as zero
        return False

    if _has_money(prices.get("power")):
        warnings.append(
            "A power/demand charge (CHF/kW) was published but is not imported: OpenZEV "
            "does not bill demand, and no demand data is metered."
        )
    if _has_money(prices.get("reactivePower")):
        warnings.append(
            "A reactive-power charge (CHF/kVarh) was published but is not imported."
        )
    refund = prices.get("refundStorage")
    if refund is not None:
        try:
            if _price_of(refund, "refundStorage")[0] > 0:
                warnings.append(
                    "A storage grid-usage refund was published but is not imported."
                )
        except ValueError:
            warnings.append("The published storage refund could not be read and is not imported.")
    return warnings


def _read_header(entry: dict, dso_name: str, dso_number: int | None) -> dict:
    tariff_name = str(entry.get("tariffName") or "").strip()
    if not tariff_name:
        raise ValueError("The entry has no tariffName.")

    tariff_type = str(entry.get("tariffType") or "").strip().casefold()
    if tariff_type not in CATEGORY_BY_TARIFF_TYPE:
        raise ValueError(f"Unknown tariffType {entry.get('tariffType')!r} for {tariff_name!r}.")

    start_date = _parse_iso_or_swiss_date(entry.get("startDate"), "startDate")
    # endDate is required upstream, which is what lets each yearly document
    # append a cleanly closed version to an existing series.
    end_date = _parse_iso_or_swiss_date(entry.get("endDate"), "endDate")
    if end_date < start_date:
        raise ValueError(f"{tariff_name!r} ends ({end_date}) before it starts ({start_date}).")

    customer_type = str(entry.get("customerType") or "").strip()
    comment = str(entry.get("comment") or "").strip()
    voltage_level = entry.get("customerVoltageLevel")

    note_lines = [
        f"Imported from the tariff publication of {dso_name}"
        + (f" (DSO {dso_number})" if dso_number else "")
        + ".",
        f"Published tariff: {tariff_name} ({tariff_type}).",
    ]
    if customer_type:
        note_lines.append(f"Customer group: {customer_type}")
    if comment:
        note_lines.append(comment)

    return {
        "tariff_name": tariff_name,
        "tariff_type": tariff_type,
        "category": CATEGORY_BY_TARIFF_TYPE[tariff_type],
        "start_date": start_date,
        "end_date": end_date,
        "customer_type": customer_type,
        "voltage_level": int(voltage_level) if isinstance(voltage_level, int) else None,
        "standard_basegroup": bool(entry.get("standardBasegroup")),
        "notes": "\n".join(note_lines),
    }


def _candidates_for_entry(entry: dict, dso_name: str, dso_number: int | None) -> list[Candidate]:
    header = _read_header(entry, dso_name, dso_number)
    category = header["category"]
    prices = entry.get("prices") or {}
    if not isinstance(prices, dict):
        raise ValueError(f"{header['tariff_name']!r} has no readable prices object.")

    candidates: list[Candidate] = []

    if str(entry.get("tariffForm") or "").strip().casefold() == "dynamic":
        url = str((prices.get("dynamic") or {}).get("url") or "").strip()
        return [
            _candidate(
                name=_tariff_name(header["tariff_name"], ENERGY_COMPONENT_SUFFIX, []),
                category=category, header=header, warnings=[],
                billing_mode=BillingMode.ENERGY, energy_type=EnergyType.GRID,
                blocked_reason=(
                    "Dynamic tariffs are not supported: the price is served by an external "
                    "time series" + (f" at {url}" if url else "") + ", not published in this document."
                ),
            )
        ]

    if prices.get("base") is not None:
        candidates.append(
            _fee_candidate(
                prices["base"],
                name=_tariff_name(header["tariff_name"], BASE_COMPONENT_SUFFIX, []),
                category=category, header=header, label="The base price",
            )
        )
    if prices.get("energy"):
        candidates.append(
            _energy_candidate(
                prices["energy"],
                name=_tariff_name(header["tariff_name"], ENERGY_COMPONENT_SUFFIX, []),
                category=category, header=header, label="The",
            )
        )

    # Municipal and cantonal surcharges each carry their own base and energy
    # prices and apply to one place only, so they become their own levy
    # tariffs rather than being folded into the parent entry.
    for tax in prices.get("municipalityTaxes") or []:
        place = str((tax or {}).get("municipalityName") or "").strip() or "Gemeinde"
        number = (tax or {}).get("municipalityNumber")
        label = f"{header['tariff_name']} – {place}" + (f" (BFS {number})" if number else "")
        candidates.extend(
            _tax_candidates(tax, label=label, header=header, base_key="municipalityBase",
                            energy_key="municipalityEnergy", comment_key="municipalityComment")
        )
    for tax in prices.get("cantonalTaxes") or []:
        canton = str((tax or {}).get("cantonName") or "").strip() or "Kanton"
        label = f"{header['tariff_name']} – {canton}"
        candidates.extend(
            _tax_candidates(tax, label=label, header=header, base_key="cantonBase",
                            energy_key="cantonEnergy", comment_key="cantonComment")
        )

    if not candidates:
        raise ValueError(f"{header['tariff_name']!r} carries no price this importer can read.")

    dropped = _dropped_component_warnings(prices)
    if dropped:
        for candidate in candidates:
            candidate.warnings.extend(dropped)
    return candidates


def _tax_candidates(tax, *, label: str, header: dict, base_key: str, energy_key: str,
                    comment_key: str) -> list[Candidate]:
    """A municipal or cantonal surcharge → levy tariffs of its own."""
    tax = tax or {}
    # Surcharges are levies whatever the parent entry was typed as.
    scoped = dict(header, category=TariffCategory.LEVIES)
    comment = str(tax.get(comment_key) or "").strip()
    if comment:
        scoped["notes"] = f"{header['notes']}\n{comment}"

    candidates = []
    if tax.get(base_key) is not None:
        candidates.append(
            _fee_candidate(
                tax[base_key], name=_tariff_name(label, BASE_COMPONENT_SUFFIX, []),
                category=TariffCategory.LEVIES, header=scoped, label="The base price",
            )
        )
    if tax.get(energy_key):
        candidates.append(
            _energy_candidate(
                tax[energy_key], name=_tariff_name(label, ENERGY_COMPONENT_SUFFIX, []),
                category=TariffCategory.LEVIES, header=scoped, label="The",
            )
        )
    return candidates


def parse_document(payload) -> ParsedDocument:
    """Map a decoded VSE/AES tariff document onto proposed OpenZEV tariffs.

    Raises ``TariffDocumentError`` only when the document as a whole is
    unusable. A single unreadable entry is reported in ``errors`` and the rest
    are still offered: a malformed entry for a customer group this ZEV does not
    use must not block the one it does.
    """
    if not isinstance(payload, dict):
        raise TariffDocumentError(
            "The document is not a JSON object. Expected a tariff submission with "
            "a 'tariffs' array."
        )

    entries = payload.get("tariffs")
    if not isinstance(entries, list):
        raise TariffDocumentError(
            "The document has no 'tariffs' array — it does not look like a VSE/AES "
            "tariff publication."
        )

    dso_name = str(payload.get("dsoName") or "").strip() or "an unnamed grid operator"
    raw_number = payload.get("dsoNumber")
    dso_number = int(raw_number) if isinstance(raw_number, int) else None

    document = ParsedDocument(dso_name=dso_name, dso_number=dso_number)
    seen_keys: set[str] = set()

    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            document.errors.append({"tariff": f"#{index}", "error": "Entry is not an object."})
            continue
        label = str(entry.get("tariffName") or f"#{index}")
        try:
            candidates = _candidates_for_entry(entry, dso_name, dso_number)
        except ValueError as exc:
            document.errors.append({"tariff": label, "error": str(exc)})
            continue

        for candidate in candidates:
            # tariffName is unique within a DSO per the standard, but a
            # published document is not obliged to be correct; two candidates
            # sharing a key would make the selection ambiguous.
            if candidate.key in seen_keys:
                document.errors.append({
                    "tariff": label,
                    "error": f"Duplicate tariff name {candidate.name!r} for {candidate.valid_from}; "
                             "only the first was kept.",
                })
                continue
            seen_keys.add(candidate.key)
            document.candidates.append(candidate)

    if not document.candidates and not document.errors:
        raise TariffDocumentError("The document contains no tariffs.")
    return document
