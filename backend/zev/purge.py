"""Admin purge: permanently and irreversibly delete a disabled ZEV and
everything under it.

This is the terminal transition of the ZEV lifecycle
(``active -> disabled -> gone``, see the ZEV lifecycle issue). Disable is
retirement and is reversible (``ZevViewSet.disable``/``enable``); purge is
not, which is why it requires the ZEV to already be disabled — it is never a
shortcut from active, and the confirmation the view demands (typing the
ZEV's exact name) is deliberately the same friction a destructive database
operation would carry if an admin ran it by hand.

Why a single ``zev.delete()`` is (almost) enough
--------------------------------------------------
Every model that hangs off a ZEV is either ``CASCADE`` from ``Zev`` directly
or from a row that is itself ``CASCADE`` from ``Zev`` — ``Participant``
(-> ``MeteringPointAssignment``, ``ParticipantOnboardingToken``),
``MeteringPoint`` (-> ``MeterReading``, ``MeteringPointAssignment``),
``Tariff`` (-> ``TariffPeriod``), ``metering.ImportLog``. Django's delete
collector walks all of that automatically. ``AuditEvent.zev``,
``ContractIssue.zev`` and ``backups.BackupJob.zev`` are ``SET_NULL`` and
deliberately survive: ``ContractIssue`` is documented as an immutable
archive, and the audit trail (including this purge's own event, and
`BackupJob` — a backup already made from this ZEV — describing an artifact
that must keep existing) is the record that the purge happened, not
something the purge should erase.

The two exceptions are ``Invoice.zev`` and ``exports.ExportJob.zev``, both
``PROTECT`` — a bare ``zev.delete()`` raises ``ProtectedError`` while either
has rows. Both are deleted explicitly first; ``Invoice``'s cascade
(``InvoiceItem``, ``InvoiceDynamicSourceEvidence``, ``InvoiceAccessToken``,
``EmailLog``, all ``CASCADE`` from ``Invoice``) then follows automatically.

Not done here, deliberately: an automatic pre-purge safety backup. The
backups feature already takes one before a per-ZEV *restore*
(``backups.tasks._take_safety_backup``), but that helper is shaped around a
``RestoreJob`` and a configured ``BackupDestination`` — wiring an equivalent
into this synchronous request/response flow is its own piece of work,
tracked on the ZEV lifecycle issue rather than folded in here. An admin who
wants that safety net today can export a transfer archive or run
``openzev_backup`` before purging.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.core.files.storage import default_storage
from django.db import transaction

from exports.models import ExportJob
from invoices.models import Invoice

from .models import Zev


class ZevPurgeError(Exception):
    """Refused: the ZEV is not eligible for purge (yet)."""


@dataclass
class PurgeResult:
    zev_id: str
    zev_name: str
    deleted_counts: dict[str, int] = field(default_factory=dict)
    media_files_deleted: int = 0


def purge_zev(zev: Zev) -> PurgeResult:
    """Permanently delete ``zev`` and everything under it. Irreversible.

    Raises :class:`ZevPurgeError` if ``zev`` is not currently disabled.
    """
    if zev.disabled_at is None:
        raise ZevPurgeError("Only a disabled ZEV can be purged. Disable it first.")

    zev_id = str(zev.pk)
    zev_name = zev.name

    # Media files are collected before any row is deleted — a FieldFile with
    # no row left pointing at it cannot be located afterwards — but deleted
    # from storage only after the transaction below has committed. A rolled
    # back transaction must not have already destroyed files it cannot
    # bring back.
    invoice_pdfs = [
        name for name in
        Invoice.objects.filter(zev=zev).exclude(pdf_file="").values_list("pdf_file", flat=True)
        if name
    ]
    export_files = [
        name for name in
        ExportJob.objects.filter(zev=zev).exclude(result_file="").values_list("result_file", flat=True)
        if name
    ]

    counts = {
        "export_jobs": ExportJob.objects.filter(zev=zev).count(),
        "invoices": Invoice.objects.filter(zev=zev).count(),
        "participants": zev.participants.count(),
        "metering_points": zev.metering_points.count(),
        "tariffs": zev.tariffs.count(),
    }

    with transaction.atomic():
        # PROTECT relations first — see the module docstring for why these
        # two are the only rows that need an explicit pre-delete.
        ExportJob.objects.filter(zev=zev).delete()
        Invoice.objects.filter(zev=zev).delete()
        zev.delete()

    media_files_deleted = 0
    for name in (*invoice_pdfs, *export_files):
        default_storage.delete(name)
        media_files_deleted += 1

    return PurgeResult(
        zev_id=zev_id, zev_name=zev_name,
        deleted_counts=counts, media_files_deleted=media_files_deleted,
    )
