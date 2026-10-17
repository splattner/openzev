"""Credit note (Gutschrift) PDF: context, rendering and storage (#388).

Rendered like the invoice (WeasyPrint through :func:`invoices.pdf._render_template`,
so an admin-edited template applies) but far simpler: a credit note is frozen
at issue, so there is no draft state to guard against and no QR bill.
"""
import logging
from decimal import Decimal
from types import SimpleNamespace

from accounts.models import AppSettings
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from zev.models import VatMode

from .document_parties import template_parties
from .pdf import _format_date_value, _render_template, delete_stored_pdf
from .pdf_render import render_pdf
from .pdf_translations import CREDIT_TRANSLATIONS

logger = logging.getLogger(__name__)

CREDIT_NOTE_TEMPLATE = "invoices/credit_note_pdf.html"


def build_credit_context(credit) -> dict:
    app_settings = AppSettings.load()
    source = credit.source_invoice
    lang = credit.zev.invoice_language or "de"
    tr = dict(CREDIT_TRANSLATIONS.get(lang, CREDIT_TRANSLATIONS["de"]))
    try:
        tr["notes_question"] = tr["notes_question"].format(email=settings.DEFAULT_FROM_EMAIL)
    except (KeyError, ValueError):
        pass  # keep the raw string if a translator removed the placeholder

    credit_day = timezone.localdate(credit.created_at)
    # The parties are the invoice's frozen copy; the stand-in covers a credit
    # without a source invoice (goodwill credits, later).
    anchor = source or SimpleNamespace(period_end=credit_day)
    parties = SimpleNamespace(zev=credit.zev, participant=credit.participant, period_end=anchor.period_end)

    date_pattern = app_settings.date_format_short
    invoice_date = _format_date_value(source.created_at, date_pattern) if source else ""
    credit_for_invoice = (
        tr["credit_for_invoice"].format(number=source.invoice_number, date=invoice_date) if source else ""
    )
    registered = credit.vat_mode == VatMode.REGISTERED
    number = credit.credit_number or ""
    prefix, _, suffix = number.rpartition("-")
    return {
        "credit": credit,
        "source_invoice": source,
        "lang": lang,
        "tr": tr,
        "kind_display": tr["kind_values"].get(credit.kind, credit.kind),
        "credit_number_prefix": prefix + "-" if prefix else number,
        "credit_number_suffix": suffix if prefix else "",
        "credit_for_invoice": credit_for_invoice,
        # A non-registered issuer shows no VAT figure, so only a registered
        # credit gets the net / VAT / total breakdown.
        "show_vat": registered,
        "net_chf": credit.amount_chf - credit.vat_chf,
        "vat_rate_percent": Decimal(credit.vat_rate or 0) * 100,
        **template_parties(parties, credit.issuer or {}, credit.recipient or {}),
        "formatted_dates": {
            "credit_date": _format_date_value(credit.created_at, date_pattern),
            "invoice_date": invoice_date,
            "period_start": _format_date_value(source.period_start, date_pattern) if source else "",
            "period_end": _format_date_value(source.period_end, date_pattern) if source else "",
        },
    }


def generate_credit_pdf(credit) -> bytes:
    html_string = _render_template(CREDIT_NOTE_TEMPLATE, build_credit_context(credit))
    return render_pdf(html_string)


def save_credit_pdf(credit) -> None:
    """Render and attach the PDF with a targeted ``UPDATE`` (never a full
    ``save`` of a possibly stale instance). Raises ``Credit.DoesNotExist`` when
    the credit vanished meanwhile, after removing the orphaned file."""
    from .models import Credit, InvoicePdfStatus

    pdf_bytes = generate_credit_pdf(credit)
    storage = credit.pdf_file.storage
    previous_name = credit.pdf_file.name
    credit.pdf_file.save(f"credit_{credit.credit_number}.pdf", ContentFile(pdf_bytes), save=False)
    stored_name = credit.pdf_file.name
    try:
        updated = Credit.objects.filter(pk=credit.pk).update(
            pdf_file=stored_name, pdf_status=InvoicePdfStatus.READY,
        )
    except Exception:
        logger.exception("Credit PDF database update failed for %s", credit.credit_number)
        delete_stored_pdf(storage, stored_name)
        raise
    if not updated:
        delete_stored_pdf(storage, stored_name)
        raise Credit.DoesNotExist(f"Credit {credit.pk} was deleted while its PDF was rendering.")
    credit.pdf_status = InvoicePdfStatus.READY
    if previous_name and previous_name != stored_name:
        delete_stored_pdf(storage, previous_name)
    logger.info("Saved PDF for credit note %s", credit.credit_number)
