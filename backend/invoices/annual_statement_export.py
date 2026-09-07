"""Whole-ZEV annual statement ZIP construction (serial).

The export job's renderer renders every eligible participant's statement
through the single-statement code path into one ZIP. The ZEV-wide share map
and community totals are computed once per batch and reused, as the billing
engine and dashboards do.
"""

import io
import logging
import zipfile
from collections import Counter
from datetime import date

from billiard.exceptions import SoftTimeLimitExceeded
from allocation.read_model import (
    community_totals_by_timestamp,
    eligible_participant_shares,
)
from allocation.validity import active_during, period_window

logger = logging.getLogger(__name__)

# ZIP entry names must stay well under the 255-byte filesystem limit: both
# name fields allow 100 chars. The pk disambiguator is only added on name
# collisions, but every entry — with or without it — must fit the budget.
_ZIP_ENTRY_BYTE_BUDGET = 180


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """Truncate ``value`` to at most ``max_bytes`` UTF-8 bytes, keeping whole characters."""
    return value.encode("utf-8")[:max(0, max_bytes)].decode("utf-8", "ignore")


# Characters Windows forbids in file names; the fixed prefix plus UUID/".pdf"
# suffix already rule out reserved device names and trailing dots/spaces.
_WINDOWS_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def _sanitize_participant_name(participant) -> str:
    """Readable ``Last_First`` base for a ZIP entry, safe for Windows."""
    safe_name = f"{participant.last_name}_{participant.first_name}".replace(" ", "_")
    return "".join(
        "_"
        if character in _WINDOWS_INVALID_FILENAME_CHARS or ord(character) < 32
        else character
        for character in safe_name
    )


def _annual_statement_zip_name(participant, year: int, disambiguator: str = "") -> str:
    """One ZIP entry name for a participant's annual statement.

    ``disambiguator`` (``-{pk}``) is only passed for names that collide
    within the batch, so the common case stays readable while duplicate
    names stay distinguishable.
    """
    prefix = f"annual-statement-{year}-"
    suffix = f"{disambiguator}.pdf"
    readable_budget = _ZIP_ENTRY_BYTE_BUDGET - len(prefix.encode("utf-8")) - len(suffix.encode("utf-8"))
    safe_name = _truncate_utf8(_sanitize_participant_name(participant), readable_budget)
    return f"{prefix}{safe_name}{suffix}"


def _annual_statement_zip_names(participants, year: int) -> dict:
    """Entry names keyed by participant pk, disambiguating only collisions.

    Names are compared after sanitising and truncation, so two maximal
    names that truncate identically are caught as well. A final loop guards
    against a secondary collision: a plain readable name can equal another
    entry's pk-suffixed name. Resolving those stragglers with their own pk
    terminates — the pk lives in the never-truncated suffix, so pk-suffixed
    names are unique per participant.
    """
    plain = {p.pk: _annual_statement_zip_name(p, year) for p in participants}
    counts = Counter(plain.values())
    names = {}
    for participant in participants:
        name = plain[participant.pk]
        if counts[name] == 1:
            names[participant.pk] = name
        else:
            names[participant.pk] = _annual_statement_zip_name(
                participant, year, disambiguator=f"-{participant.pk}",
            )
    while True:
        duplicates = {name for name, count in Counter(names.values()).items() if count > 1}
        if not duplicates:
            return names
        for participant in participants:
            if names[participant.pk] in duplicates:
                names[participant.pk] = _annual_statement_zip_name(
                    participant, year, disambiguator=f"-{participant.pk}",
                )


class AnnualStatementExportError(Exception):
    """The export cannot be produced; ``message`` is safe to show to users."""


def _eligible_participants(zev, year: int):
    """Participants active at any point during ``year``, in display order."""
    return list(
        active_during(zev.participants, date(year, 1, 1), date(year, 12, 31))
        .order_by("last_name", "first_name")
    )


def build_annual_statements_zip(zev, year: int) -> tuple[bytes, list[str], list[str]]:
    """Render every eligible participant's annual statement into one ZIP.

    Returns ``(zip_bytes, generated_ids, omitted_ids)``. A failure of one
    participant's statement omits only that statement, which is then listed
    in an ``omitted.txt`` manifest inside the archive. If no statement at all
    can be generated the archive is never published and
    :class:`AnnualStatementExportError` is raised — an all-failed export must
    not look like a successful (even partial) one.
    """
    participants = _eligible_participants(zev, year)
    if not participants:
        raise AnnualStatementExportError(
            f"No participants found for this ZEV and year {year}."
        )

    # A failure here would fail every statement, so the whole export fails
    # rather than degrading to omissions.
    from invoices.annual_statement import generate_annual_statement_pdf

    try:
        share_windows = [
            (p.id, p.valid_from, p.valid_to, p.allocation_weight)
            for p in participants
        ]
        shares_by_date = eligible_participant_shares(
            zev, date(year, 1, 1), date(year, 12, 31), windows=share_windows,
        )
        year_start_dt, year_end_dt = period_window(date(year, 1, 1), date(year, 12, 31))
        zev_totals_by_ts = community_totals_by_timestamp(zev, year_start_dt, year_end_dt)
    except SoftTimeLimitExceeded:
        # Abort on the soft limit too: repackaging it as an export failure
        # would hide the interruption from the worker's handler.
        raise
    except Exception:
        logger.exception(
            "Annual-statement export shared-data calculation failed for ZEV %s and year %s",
            zev.id, year,
        )
        raise AnnualStatementExportError("Could not generate annual statements.") from None

    buf = io.BytesIO()
    generated = []
    omitted = []
    # Names are fixed before rendering so duplicates share one decision.
    entry_names = _annual_statement_zip_names(participants, year)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for participant in participants:
            try:
                pdf_bytes = generate_annual_statement_pdf(
                    participant,
                    zev,
                    year,
                    shares_by_date=shares_by_date,
                    zev_totals_by_ts=zev_totals_by_ts,
                )
            except SoftTimeLimitExceeded:
                # Never swallow the limit as a participant failure: it would
                # keep rendering toward a published ZIP.
                raise
            except Exception:
                logger.exception(
                    "Annual statement omitted for participant %s", participant.pk,
                )
                omitted.append(participant)
                continue
            generated.append(participant.pk)
            zf.writestr(entry_names[participant.pk], pdf_bytes)
        if omitted:
            # A partial archive must stay distinguishable from a complete one
            # even after the ZIP has left the server.
            entries = "\n".join(
                f"- {p.pk} ({p.last_name}, {p.first_name})"
                for p in sorted(omitted, key=lambda p: str(p.pk))
            )
            zf.writestr(
                "omitted.txt",
                "The following participants were omitted because their annual "
                f"statement could not be generated:\n{entries}\n",
            )

    if not generated:
        raise AnnualStatementExportError("Could not generate annual statements.")

    return (
        buf.getvalue(),
        [str(pk) for pk in generated],
        [str(p.pk) for p in omitted],
    )
