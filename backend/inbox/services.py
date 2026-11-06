"""The only writers of ``DeliveredDocument`` (SPEC-2026-11-participant-document-inbox §6.1).

Every function writes the file before the row and removes it again if the row
cannot be written, so a failed delivery leaves no orphaned file behind (the
``save_invoice_pdf`` pattern).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditActionCategory, AuditEventSource
from audit.services import record_audit_event
from config.http import sanitize_filename

from .models import REPORT_KINDS, DeliveredDocument, DocumentKind, inbox_upload_to

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredFile:
    """Bytes already written to storage, ready to back one or more rows."""

    name: str
    size: int
    sha256: str
    file_name: str


def store_file(zev, body: bytes, file_name: str = "") -> StoredFile:
    """Write ``body`` to storage under a server-chosen name.

    Kept apart from ``deliver`` so a broadcast can store one file and point a
    row at it per recipient. The caller owns the file until a row references it:
    call ``discard_file`` if the rows cannot be written.
    """

    class _Anchor:  # ``inbox_upload_to`` only reads ``zev_id``
        zev_id = zev.pk

    name = default_storage.save(inbox_upload_to(_Anchor, file_name), ContentFile(body))
    return StoredFile(
        name=name,
        size=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        file_name=sanitize_filename(file_name) if file_name else "",
    )


def discard_file(name: str) -> None:
    """Remove a stored file that no row references (best effort)."""
    try:
        default_storage.delete(name)
    except Exception:
        logger.exception("Orphaned inbox file could not be removed: %s", name)


def remove_file_if_unreferenced(name: str) -> bool:
    """Delete ``name`` unless some row still points at it. Returns whether it was deleted."""
    if not name or DeliveredDocument.objects.filter(file=name).exists():
        return False
    discard_file(name)
    return True


def _audit(action, document, *, user=None, summary, source=None, metadata=None):
    record_audit_event(
        action_category=AuditActionCategory.PARTICIPANT,
        action_type=f"inbox.document.{action}",
        target_type="inbox.DeliveredDocument",
        target_id=str(document.pk),
        target_display=document.title,
        summary=summary,
        user=user,
        zev=document.zev,
        source=source or (AuditEventSource.API if user is not None else AuditEventSource.SYSTEM),
        metadata={
            "kind": document.kind,
            "participant_id": str(document.participant_id) if document.participant_id else None,
            "sha256": document.sha256,
            "size_bytes": document.size_bytes,
            **(metadata or {}),
        },
    )


def _existing(*, kind, participant, invoice, contract_issue, period):
    """The row this delivery would duplicate, or ``None``."""
    if invoice is not None:
        return DeliveredDocument.objects.filter(invoice=invoice).first()
    if contract_issue is not None:
        return DeliveredDocument.objects.filter(contract_issue=contract_issue, participant=participant).first()
    return None


def deliver(
    *,
    participant,
    kind: str,
    title: str,
    body: bytes | None = None,
    stored: StoredFile | None = None,
    file_name: str = "",
    delivered_by=None,
    batch_id=None,
    invoice=None,
    contract_issue=None,
    period: tuple | None = None,
    document_number: str = "",
    delivered_at=None,
) -> tuple[DeliveredDocument, bool]:
    """Record that a document reached ``participant``. Returns ``(row, created)``.

    Idempotent for an invoice and for a contract version: delivering one again
    returns the existing row. Delivering a report kind that already has a
    current row for the period supersedes it. A contract carries no file
    (``contract_issue`` is the body); every other kind needs ``body`` or
    ``stored``.
    """
    if kind == DocumentKind.CONTRACT:
        if contract_issue is None or body is not None or stored is not None:
            raise ValueError("A contract is delivered by reference to its ContractIssue, with no file.")
    elif (body is None) == (stored is None):
        raise ValueError("Give exactly one of body and stored.")

    existing = _existing(
        kind=kind, participant=participant, invoice=invoice, contract_issue=contract_issue, period=period
    )
    if existing is not None:
        return existing, False

    wrote_here = False
    if body is not None:
        stored = store_file(participant.zev, body, file_name)
        wrote_here = True

    fields = dict(
        participant=participant,
        kind=kind,
        title=title,
        document_number=document_number,
        period_start=period[0] if period else None,
        period_end=period[1] if period else None,
        invoice=invoice,
        contract_issue=contract_issue,
        delivered_by=delivered_by,
        batch_id=batch_id,
        delivered_at=delivered_at or timezone.now(),
    )
    if stored is not None:
        fields.update(
            file=stored.name, file_name=stored.file_name or file_name,
            size_bytes=stored.size, sha256=stored.sha256,
        )
    else:
        issue_bytes = bytes(contract_issue.pdf)
        fields.update(
            file_name=sanitize_filename(f"{document_number or title}.pdf"),
            size_bytes=len(issue_bytes), sha256=hashlib.sha256(issue_bytes).hexdigest(),
        )

    try:
        with transaction.atomic():
            previous = _current_report(participant, kind, period)
            if previous is not None:
                # Flag first: the one-current-report constraint would otherwise refuse the insert.
                previous.superseded_at = fields["delivered_at"]
                previous.save(update_fields=["superseded_at"])
            document = DeliveredDocument.objects.create(**fields)
            if previous is not None:
                previous.superseded_by = document
                previous.save(update_fields=["superseded_by"])
            _audit(
                "delivered", document, user=delivered_by,
                summary=f"Delivered {document.get_kind_display().lower()} “{document.title}” to a participant.",
                metadata={"superseded": str(previous.pk) if previous else None},
            )
    except IntegrityError:
        # Lost a race with an identical delivery: the other one stands.
        if wrote_here:
            discard_file(stored.name)
        existing = _existing(
            kind=kind, participant=participant, invoice=invoice, contract_issue=contract_issue, period=period
        ) or _current_report(participant, kind, period)
        if existing is None:
            raise
        return existing, False
    except Exception:
        if wrote_here:
            discard_file(stored.name)
        raise
    return document, True


def _current_report(participant, kind, period):
    if kind not in REPORT_KINDS:
        return None
    queryset = DeliveredDocument.objects.select_for_update().filter(
        participant=participant, kind=kind, superseded_at__isnull=True
    )
    if period is not None:
        queryset = queryset.filter(period_start=period[0], period_end=period[1])
    return queryset.first()


def supersede(old: DeliveredDocument, new: DeliveredDocument, *, user=None) -> DeliveredDocument:
    """Mark ``old`` as replaced by ``new`` (a corrected invoice). Nothing is deleted."""
    if old.pk == new.pk:
        raise ValueError("A document cannot supersede itself.")
    if old.superseded_at is not None:
        return old
    old.superseded_at = timezone.now()
    old.superseded_by = new
    old.save(update_fields=["superseded_at", "superseded_by"])
    _audit(
        "superseded", old, user=user,
        summary=f"Document “{old.title}” was superseded by “{new.title}”.",
        metadata={"superseded_by": str(new.pk)},
    )
    return old


def withdraw(document: DeliveredDocument, by) -> DeliveredDocument:
    """Hide an operator document from participants. The row and file stay. Idempotent."""
    if document.kind != DocumentKind.OPERATOR:
        raise ValueError("Only operator documents can be withdrawn.")
    if document.withdrawn_at is not None:
        return document
    document.withdrawn_at = timezone.now()
    document.withdrawn_by = by
    document.save(update_fields=["withdrawn_at", "withdrawn_by"])
    _audit("withdrawn", document, user=by, summary=f"Withdrew document “{document.title}”.")
    return document
