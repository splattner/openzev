"""
Plans and applies a parsed VSE/AES tariff document against one ZEV's tariffs.

Kept apart from ``vse_json`` because the two answer different questions. The
parser asks "what does this document say?", which depends only on the
document. The planner asks "what would importing it do to *this* ZEV?", which
depends on what is already stored — whether the name is new, whether last
year's version has to be closed first, whether the document has already been
imported once.

That second question is where an import silently doubles somebody's bill, so
every candidate gets a status and a sentence explaining it *before* anything
is written, and the same planning code runs again inside the write
transaction against freshly read rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError

from tariffs.models import Tariff, TariffPeriod
from tariffs.series import SERIES_FIELDS, plan_new_version

from .vse_json import Candidate, ParsedDocument


class CandidateStatus:
    NEW = "new"
    NEW_VERSION = "new_version"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"


#: Statuses the apply step will act on. Everything else is reported and left
#: alone — re-running an import must not rewrite what is already live.
APPLICABLE_STATUSES = frozenset({CandidateStatus.NEW, CandidateStatus.NEW_VERSION})


@dataclass(frozen=True)
class Selection:
    """One ticked row of the preview.

    ``billing_mode`` carries the user's answer to the one question the
    published document cannot answer — see ``FEE_BILLING_MODE_OPTIONS``.
    ``None`` means "whatever the candidate proposed".
    """

    key: str
    billing_mode: str | None = None


@dataclass
class PlannedCandidate:
    candidate: Candidate
    status: str
    detail: str
    #: Date the existing predecessor version would be closed on, if any.
    closes_predecessor_on: date | None = None
    #: The end date the new tariff would actually get, which is the document's
    #: end date unless a later version already exists and caps it earlier.
    effective_valid_to: date | None = None

    @property
    def is_applicable(self) -> bool:
        return self.status in APPLICABLE_STATUSES


@dataclass
class ImportReport:
    created: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def _existing_series(zev_id, names: set[str]) -> dict[str, list[Tariff]]:
    series: dict[str, list[Tariff]] = {}
    for tariff in Tariff.objects.filter(zev_id=zev_id, name__in=names):
        series.setdefault(tariff.name, []).append(tariff)
    return series


def _plan_one(
    candidate: Candidate, versions: list[Tariff], *, billing_mode_was_chosen: bool = False
) -> PlannedCandidate:
    """Status one candidate against the versions of its series that exist.

    ``billing_mode_was_chosen`` says the user answered the billing-mode
    question for this row, which decides what a mismatch against the existing
    series means: an unanswered one is matched to the series, an answered one
    is a conflict rather than something to quietly overrule.
    """
    if not candidate.is_importable:
        return PlannedCandidate(candidate, CandidateStatus.UNSUPPORTED, candidate.blocked_reason or "")

    if not versions:
        return PlannedCandidate(
            candidate, CandidateStatus.NEW,
            "Creates a new tariff.",
            effective_valid_to=candidate.valid_to,
        )

    # Same name and same start date is the same version: re-importing last
    # year's document must not raise, and must not touch what is live.
    if any(version.valid_from == candidate.valid_from for version in versions):
        return PlannedCandidate(
            candidate, CandidateStatus.DUPLICATE,
            f"A version of this tariff already starts on {candidate.valid_from.isoformat()}; "
            "it has been imported before and is left untouched.",
        )

    # Versions of one tariff must agree on what the tariff *is* — the model
    # enforces it, so catching it here turns a 500-shaped validation error into
    # a sentence the user can act on.
    reference = versions[0]
    matched_billing_mode: str | None = None
    for series_field in SERIES_FIELDS:
        mine = getattr(candidate, series_field)
        theirs = getattr(reference, series_field)
        if mine == theirs:
            continue

        # ``billing_mode`` is the one series field the document does not
        # decide: for a fee the user picks it on first import, and the document
        # carries no record of what they picked. So the same document
        # re-imported a year later proposes the default again and would
        # deadlock against the choice already made — the row went to CONFLICT,
        # which the preview renders as unselectable, disabling the very
        # dropdown that could have resolved it. Match the series instead, as
        # long as this candidate can be imported that way at all.
        if (
            series_field == "billing_mode"
            and not billing_mode_was_chosen
            and theirs in candidate.billing_mode_options
        ):
            candidate = replace(candidate, billing_mode=theirs)
            matched_billing_mode = theirs
            continue

        if series_field == "billing_mode" and billing_mode_was_chosen:
            return PlannedCandidate(
                candidate, CandidateStatus.CONFLICT,
                f'A tariff named "{candidate.name}" already exists in this ZEV billed as '
                f"{theirs!r}. Versions of one tariff must agree on that, so it cannot be "
                f"imported as {mine!r}. Choose {theirs!r}, or rename one of them.",
            )

        return PlannedCandidate(
            candidate, CandidateStatus.CONFLICT,
            f'A tariff named "{candidate.name}" already exists in this ZEV with '
            f"{series_field}={theirs!r}, but the document maps it to {mine!r}. "
            "Rename one of them before importing.",
        )

    window = plan_new_version(versions, candidate.valid_from)
    valid_to = candidate.valid_to
    if window.valid_to is not None and (valid_to is None or window.valid_to < valid_to):
        valid_to = window.valid_to

    detail = "Adds a new version to the existing tariff."
    if matched_billing_mode is not None:
        # Say so rather than let the dropdown quietly disagree with the
        # document the reader is comparing it against.
        detail += (
            f" Billed as {matched_billing_mode!r} to match the versions already here,"
            " not as the document proposes."
        )
    if window.predecessor_valid_to is not None:
        detail += f" The previous version is closed on {window.predecessor_valid_to.isoformat()}."
    if valid_to != candidate.valid_to:
        detail += f" The end date is capped at {valid_to.isoformat()} by a later version."

    return PlannedCandidate(
        candidate, CandidateStatus.NEW_VERSION, detail,
        closes_predecessor_on=window.predecessor_valid_to,
        effective_valid_to=valid_to,
    )


def plan_import(zev_id, document: ParsedDocument) -> list[PlannedCandidate]:
    """Status every candidate against the tariffs this ZEV already has."""
    series = _existing_series(zev_id, {candidate.name for candidate in document.candidates})
    return [_plan_one(candidate, series.get(candidate.name, [])) for candidate in document.candidates]


def _notes_with_provenance(candidate: Candidate, source_url: str, imported_on: date) -> str:
    origin = f"Source: {source_url}" if source_url else "Source: uploaded document"
    return f"{candidate.notes}\n{origin} (imported {imported_on.isoformat()})".strip()


def _create(zev, planned: PlannedCandidate, source_url: str, imported_on: date) -> Tariff:
    candidate = planned.candidate

    if planned.closes_predecessor_on is not None:
        # Truncate first: saving the new version while the predecessor still
        # covers this date would trip the overlap guard in Tariff.clean.
        predecessor = (
            Tariff.objects.filter(
                zev=zev, name=candidate.name, valid_from__lt=candidate.valid_from
            )
            .order_by("-valid_from")
            .first()
        )
        if predecessor is not None:
            predecessor.valid_to = planned.closes_predecessor_on
            predecessor.save()

    tariff = Tariff(
        zev=zev,
        name=candidate.name,
        category=candidate.category,
        billing_mode=candidate.billing_mode,
        energy_type=candidate.energy_type,
        fixed_price_chf=candidate.fixed_price_chf,
        valid_from=candidate.valid_from,
        valid_to=planned.effective_valid_to,
        notes=_notes_with_provenance(candidate, source_url, imported_on),
    )
    tariff.save()

    TariffPeriod.objects.bulk_create([
        TariffPeriod(
            tariff=tariff,
            period_type=period.period_type,
            label=period.label,
            price_chf_per_kwh=period.price_chf_per_kwh,
            time_from=period.time_from,
            time_to=period.time_to,
            weekdays=period.weekdays,
            months=period.months,
        )
        for period in candidate.periods
    ])
    return tariff


def _with_chosen_billing_mode(candidate: Candidate, chosen: str | None) -> Candidate:
    """Apply the user's billing-mode answer, refusing anything not offered.

    The candidate's own ``billing_mode_options`` is the allowlist, so what the
    preview rendered and what the write path accepts are the same list. An
    energy candidate offers nothing, and an override on one is refused rather
    than quietly ignored — silently billing per kWh what somebody asked to be
    billed monthly is exactly the kind of thing this feature must not do.
    """
    if chosen is None or chosen == candidate.billing_mode:
        return candidate
    if chosen not in candidate.billing_mode_options:
        raise ValueError(
            f"{chosen!r} is not a billing mode this tariff can be imported as. "
            f"Offered: {', '.join(candidate.billing_mode_options) or 'none'}."
        )
    return replace(candidate, billing_mode=chosen)


def apply_import(*, zev, document: ParsedDocument, selections: list[Selection], source_url: str,
                 imported_on: date) -> tuple[ImportReport, list[Tariff]]:
    """Create the selected candidates, one savepoint each.

    Per-candidate savepoints rather than one transaction for the lot: a
    document that fails on one customer group should still deliver the tariffs
    the ZEV actually uses, which is the same reason parsing is per-entry.
    """
    report = ImportReport()
    created: list[Tariff] = []

    by_key = {candidate.key: candidate for candidate in document.candidates}

    for selection in selections:
        if selection.key not in by_key:
            report.errors.append({
                "name": selection.key,
                "error": "This tariff is no longer in the document. Run the preview again.",
            })
            continue

        try:
            candidate = _with_chosen_billing_mode(by_key[selection.key], selection.billing_mode)
        except ValueError as exc:
            report.errors.append({"name": by_key[selection.key].name, "error": str(exc)})
            continue

        # Re-read the series per candidate rather than planning against a list
        # loaded once up front: the preview the user looked at may be minutes
        # old, another session may have added a version since, and each
        # candidate this loop writes changes the timeline the next one plans
        # against.
        versions = list(Tariff.objects.filter(zev_id=zev.id, name=candidate.name))
        planned = _plan_one(
            candidate, versions, billing_mode_was_chosen=selection.billing_mode is not None
        )
        if not planned.is_applicable:
            report.skipped.append({"name": candidate.name, "reason": planned.detail})
            continue
        try:
            with transaction.atomic():
                tariff = _create(zev, planned, source_url, imported_on)
        except DjangoValidationError as exc:
            report.errors.append({
                "name": candidate.name,
                "error": "; ".join(exc.messages),
            })
            continue

        created.append(tariff)
        report.created.append({
            "name": tariff.name,
            "category": tariff.category,
            "billing_mode": tariff.billing_mode,
            "valid_from": tariff.valid_from.isoformat(),
            "valid_to": tariff.valid_to.isoformat() if tariff.valid_to else None,
        })

    return report, created
