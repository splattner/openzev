"""Documents the operator issues to participants on demand (SPEC-2026-11-participant-document-inbox §5.3).

The annual statement, the financial summary and the tariff overview are rendered
with the same generators the live downloads use, and the bytes are kept: what
the participant opens later is what was issued, even if the figures move.
Re-issuing supersedes the earlier row (``services.deliver`` does that for report
kinds), so the history stays and only one row per period is current.

Everything is rendered before anything is written, so a generator that fails
leaves nothing delivered.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from invoices.annual_statement import ANNUAL_TRANSLATIONS, generate_annual_statement_pdf
from invoices.financial_summary import FINANCIAL_SUMMARY_TRANSLATIONS, generate_financial_summary_pdf
from invoices.models import InvoiceItem, billed_invoices, sent_to_participant
from invoices.tariff_overview import generate_tariff_overview_pdf
from invoices.tariff_overview_translations import TARIFF_OVERVIEW_TRANSLATIONS
from zev.access import live_participant_q
from zev.models import Participant

from .models import DocumentKind
from .services import StoredFile, deliver, discard_file, store_file


@dataclass
class Delivery:
    """What one issue call did, in the shape of the response (spec §5.2)."""

    batch_id: uuid.UUID
    documents: list
    created: int
    without_account: int
    # The rows this call wrote, which are the ones to announce; ``documents`` also holds repeats.
    fresh: list = field(default_factory=list)


def _title(translations: dict, zev, key: str, suffix: str = "") -> str:
    table = translations.get(zev.invoice_language or "de") or translations["de"]
    return f"{table[key]} {suffix}".strip()


def current_participants(zev):
    """Participants whose link is current today, the audience of a broadcast."""
    return Participant.objects.filter(live_participant_q(), zev=zev).select_related("zev", "user")


def one_per_person(participants) -> list:
    """One row per person for a document that is the same for every participant row.

    A person with two participant rows (a flat and a parking space) has one
    account and reads one inbox, so a notice or the tariff overview sent to
    both rows would show up twice. The first row, in the given order, stands
    for the person. Rows without a linked account stay as they are: nothing
    says two of them are the same person, and each is a separate addressee
    until an account is linked. Statements and summaries are not reduced here,
    because their content differs per participant row.
    """
    seen: set = set()
    kept = []
    for participant in participants:
        if participant.user_id is not None:
            if participant.user_id in seen:
                continue
            seen.add(participant.user_id)
        kept.append(participant)
    return kept


def statement_participant_ids(zev, year: int) -> set:
    """Participants with an invoice in ``year`` that reached them (what the statement lists)."""
    invoices = billed_invoices(zev, date(year, 1, 1), date(year, 12, 31)).filter(sent_to_participant())
    return set(invoices.values_list("participant_id", flat=True))


def summary_participant_ids(zev, year: int) -> set:
    """Producers: participants whose billed invoices of ``year`` carry feed-in or a credit for local energy."""
    invoices = billed_invoices(zev, date(year, 1, 1), date(year, 12, 31))
    produced = InvoiceItem.objects.filter(invoice__in=invoices).filter(
        Q(item_type=InvoiceItem.ItemType.FEED_IN)
        | Q(item_type=InvoiceItem.ItemType.LOCAL_ENERGY, total_chf__lt=0)
    )
    return set(produced.values_list("invoice__participant_id", flat=True))


def _count(created_rows: list) -> tuple[int, int]:
    return len(created_rows), sum(1 for document, _ in created_rows if document.participant.user_id is None)


def delivery_of(batch_id, results) -> Delivery:
    created = [(document, was_created) for document, was_created in results if was_created]
    count, without_account = _count(created)
    return Delivery(
        batch_id, [document for document, _ in results], count, without_account,
        fresh=[document for document, _ in created],
    )


def issue_per_participant(zev, participants, *, kind, year, render, user) -> Delivery:
    """One rendered document per participant, for the year ``year``."""
    period = (date(year, 1, 1), date(year, 12, 31))
    translations, key, prefix = {
        DocumentKind.ANNUAL_STATEMENT: (ANNUAL_TRANSLATIONS, "title", "annual-statement"),
        DocumentKind.FINANCIAL_SUMMARY: (FINANCIAL_SUMMARY_TRANSLATIONS, "title", "financial-summary"),
    }[kind]
    title = _title(translations, zev, key, str(year))
    rendered = [(participant, render(participant)) for participant in participants]
    batch_id = uuid.uuid4()
    results = []
    with transaction.atomic():
        for participant, body in rendered:
            results.append(
                deliver(
                    participant=participant, kind=kind, title=title, body=body,
                    file_name=f"{prefix}-{year}.pdf", period=period,
                    delivered_by=user, batch_id=batch_id,
                )
            )
    return delivery_of(batch_id, results)


def issue_annual_statements(zev, participants, year: int, user) -> Delivery:
    return issue_per_participant(
        zev, participants, kind=DocumentKind.ANNUAL_STATEMENT, year=year, user=user,
        render=lambda participant: generate_annual_statement_pdf(participant, zev, year, sent_only=True),
    )


def issue_financial_summaries(zev, participants, year: int, user) -> Delivery:
    return issue_per_participant(
        zev, participants, kind=DocumentKind.FINANCIAL_SUMMARY, year=year, user=user,
        render=lambda participant: generate_financial_summary_pdf(zev, participant, year),
    )


def issue_tariff_overview(zev, participants, user) -> Delivery:
    """The tariff overview as of today, rendered once and shared by every row."""
    as_of = timezone.localdate()
    body = generate_tariff_overview_pdf(zev, as_of, "valid")
    title = _title(TARIFF_OVERVIEW_TRANSLATIONS, zev, "document_label", as_of.strftime("%d.%m.%Y"))
    stored: StoredFile = store_file(zev, body, f"tariff-overview-{as_of.isoformat()}.pdf")
    batch_id = uuid.uuid4()
    try:
        with transaction.atomic():
            results = [
                deliver(
                    participant=participant, kind=DocumentKind.TARIFF_OVERVIEW, title=title,
                    stored=stored, file_name=stored.file_name, delivered_by=user, batch_id=batch_id,
                )
                for participant in participants
            ]
    except BaseException:
        discard_file(stored.name)
        raise
    delivery = delivery_of(batch_id, results)
    if delivery.created == 0:
        discard_file(stored.name)
    return delivery
