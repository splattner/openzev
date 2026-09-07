"""Per-type export definitions.

The generic job lifecycle (:mod:`exports.tasks`) knows nothing about what a
job produces. Each ``export_type`` registers one :class:`ExportDefinition`
here — request validator, renderer, audit vocabulary (prefix, category,
display and summaries) and download file name — and the generic entry points
(:func:`validate_export`, :func:`render_export`) resolve it by type. A new
export type adds one definition and one entry in ``EXPORT_DEFINITIONS``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import MAXYEAR, MINYEAR

from audit.models import AuditActionCategory

from .models import ExportType


class ExportValidationError(Exception):
    """Bad request for an export type; ``message`` is safe to show to users."""


class ExportNotPossibleError(Exception):
    """The export could not be produced; ``message`` is safe to show to users."""


@dataclass
class ExportResult:
    payload: bytes
    generated_count: int
    omitted_ids: list[str]


@dataclass
class ExportDefinition:
    """Everything the shared job lifecycle needs to know about one export type."""

    validator: Callable[..., dict]
    renderer: Callable[..., ExportResult]
    audit_prefix: str
    audit_category: str
    filename: Callable[..., str]
    display_for: Callable[..., str]
    created_summary_for: Callable[..., str]
    enqueue_failed_summary_for: Callable[..., str]
    completed_summary_for: Callable[..., str]
    audit_metadata_for: Callable[..., dict]


# ── Annual statements ────────────────────────────────────────────────────────

def validate_annual_statements(zev, params: dict) -> dict:
    """Validate and clean ``params`` for an annual-statement export.

    Mirrors the single-statement endpoint's year contract (upper bound is
    ``MAXYEAR - 1`` because the report builders construct ``datetime(year+1,
    1, 1)`` as the exclusive end of the period).
    """
    year_raw = params.get("year")
    if year_raw in (None, ""):
        raise ExportValidationError("year is required.")
    try:
        year = int(year_raw)
    except (TypeError, ValueError):
        raise ExportValidationError("year must be a number.") from None
    if not MINYEAR <= year <= MAXYEAR - 1:
        raise ExportValidationError(f"year must be between {MINYEAR} and {MAXYEAR - 1}.")

    from allocation.validity import active_during
    from datetime import date

    has_participants = (
        active_during(
            zev.participants,
            date(year, 1, 1),
            date(year, 12, 31),
        ).exists()
    )
    if not has_participants:
        raise ExportValidationError(
            "No participants found for this ZEV and year."
        )
    return {"year": year}


def render_annual_statements(job) -> ExportResult:
    """Render every eligible annual statement for ``job`` into a ZIP.

    The ZIP construction lives in ``invoices.annual_statement_export``, with
    the rest of the document domain.
    """
    from invoices.annual_statement_export import (
        AnnualStatementExportError,
        build_annual_statements_zip,
    )

    year = job.params["year"]
    try:
        zip_bytes, generated_ids, omitted_ids = build_annual_statements_zip(job.zev, year)
    except AnnualStatementExportError as exc:
        raise ExportNotPossibleError(str(exc)) from None
    return ExportResult(
        payload=zip_bytes,
        generated_count=len(generated_ids),
        omitted_ids=omitted_ids,
    )


def _annual_statements_completed_summary(zev, params, result: ExportResult) -> str:
    """Completion summary for an annual-statement export, partial or whole."""
    partial = bool(result.omitted_ids)
    return (
        f"Generated annual statement export for ZEV {zev.name} "
        f"({result.generated_count} statement(s))."
        + (" Some statements were omitted." if partial else "")
    )


EXPORT_DEFINITIONS = {
    ExportType.ANNUAL_STATEMENTS: ExportDefinition(
        validator=validate_annual_statements,
        renderer=render_annual_statements,
        audit_prefix="annual_statement_export",
        audit_category=AuditActionCategory.INVOICE,
        filename=lambda params: f"annual-statements-{params['year']}.zip",
        display_for=lambda zev, params: f"{zev.name} {params['year']}".strip(),
        created_summary_for=(
            lambda zev, params: (
                f"Queued annual statement export for ZEV {zev.name} ({params['year']})."
            )
        ),
        enqueue_failed_summary_for=(
            lambda zev, params: (
                f"Export for ZEV {zev.name} ({params['year']}) could not be queued."
            )
        ),
        completed_summary_for=_annual_statements_completed_summary,
        audit_metadata_for=lambda params: {"year": params["year"]},
    ),
}


def validate_export(export_type: str, zev, params: dict) -> dict:
    """Run the validator registered for ``export_type``."""
    try:
        definition = EXPORT_DEFINITIONS[export_type]
    except KeyError:
        raise ExportValidationError("Unknown export type.") from None
    return definition.validator(zev, params)


def render_export(job) -> ExportResult:
    """Run the renderer registered for ``job.export_type``."""
    try:
        definition = EXPORT_DEFINITIONS[job.export_type]
    except KeyError:  # pragma: no cover - guarded at creation time
        raise ExportNotPossibleError("This export type is not available.") from None
    return definition.renderer(job)
