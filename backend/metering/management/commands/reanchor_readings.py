"""Move legacy offset-less CSV readings from "Swiss wall clock labelled UTC" to the real instant.

Before ADR 0026 the CSV/Excel importer stamped offset-less timestamps as UTC.
Swiss sources export Swiss local time, so those readings sit one hour (winter)
or two (summer) late on the UTC timeline. The database cannot tell which CSV
files had offsets, so nothing moves automatically: an operator picks the
batches, checks the dry run, and applies it.

Spec: docs/specs/2026-09-swiss-civil-time.md §6.3.
"""

from datetime import timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Max, Min

from allocation.validity import business_tz, civil_date
from audit.models import AuditActionCategory, AuditEventSource
from audit.services import record_audit_event
from invoices.models import Invoice, InvoiceStatus
from metering.models import ImportLog, ImportSource, MeterReading
from zev.models import MeteringPointAssignment

MAX_LISTED = 20
LOCKED_INVOICE_STATUSES = (InvoiceStatus.APPROVED, InvoiceStatus.SENT, InvoiceStatus.PAID)


def legacy_batches():
    """CSV imports whose offset-less timestamps were read as UTC."""
    return ImportLog.objects.filter(source=ImportSource.CSV, timestamp_timezone="")


def reanchored(ts):
    """The real instant of a reading stored as Swiss wall clock labelled UTC.

    Returns ``None`` when that wall-clock time does not exist (the spring DST
    gap). An autumn wall-clock time is ambiguous; the legacy import could
    only store it once, and it is read as summer time (``fold=0``).
    """
    wall = ts.astimezone(timezone.utc).replace(tzinfo=None)
    local = wall.replace(tzinfo=business_tz())
    instant = local.astimezone(timezone.utc)
    if instant.astimezone(business_tz()).replace(tzinfo=None) != wall:
        return None
    return instant


class SelectionPlan:
    """What re-anchoring the selected batches would do, computed without writing.

    The batches are planned together: a month's first hours move onto the
    previous month's last hours, which the previous month's batch vacates in
    the same run. Only readings outside the selection can block a target.
    """

    def __init__(self, logs):
        self.logs = logs
        batch_ids = [log.batch_id for log in logs]
        readings = list(
            MeterReading.objects.filter(import_batch__in=batch_ids)
            .order_by("timestamp")
            .values_list("pk", "import_batch", "metering_point_id", "timestamp", "direction", "energy_kwh")
        )
        self.moves = []  # (pk, old, new), in ascending old order
        self.dropped = []  # (pk, old) zero-energy readings in the spring gap
        self.nonexistent = []  # (pk, old) non-zero readings in the spring gap
        self.collisions = []  # (metering_point_id, new, direction)
        self.per_batch = {batch_id: {"moved": 0, "dropped": 0} for batch_id in batch_ids}
        targets = set()
        for pk, batch_id, mp_id, ts, direction, energy in readings:
            new = reanchored(ts)
            if new is None:
                (self.dropped if energy == 0 else self.nonexistent).append((pk, ts))
                self.per_batch[batch_id]["dropped"] += energy == 0
                continue
            self.moves.append((pk, ts, new))
            self.per_batch[batch_id]["moved"] += 1
            key = (mp_id, new, direction)
            if key in targets:
                self.collisions.append(key)
            targets.add(key)
        self._check_outside_collisions({pk for pk, *_ in readings}, targets)
        self.invoices = self._locked_invoices({mp_id for _, _, mp_id, *_ in readings})

    def _check_outside_collisions(self, selected_pks, targets):
        """Targets already held by a reading that is not part of the selection."""
        if not targets:
            return
        instants = [new for _, new, _ in targets]
        occupied = MeterReading.objects.filter(
            metering_point_id__in={mp_id for mp_id, _, _ in targets},
            timestamp__gte=min(instants),
            timestamp__lte=max(instants),
        ).exclude(pk__in=selected_pks).values_list("metering_point_id", "timestamp", "direction")
        self.collisions.extend(key for key in occupied if key in targets)

    def _locked_invoices(self, metering_point_ids):
        """Approved, sent or paid invoices whose period holds a moved reading."""
        if not self.moves:
            return []
        first = civil_date(min(new for _, _, new in self.moves))
        last = civil_date(max(old for _, old, _ in self.moves))
        participant_ids = MeteringPointAssignment.objects.filter(
            metering_point_id__in=metering_point_ids,
        ).values_list("participant_id", flat=True)
        return list(
            Invoice.objects.filter(
                participant_id__in=participant_ids,
                status__in=LOCKED_INVOICE_STATUSES,
                period_start__lte=last,
                period_end__gte=first,
            ).order_by("period_start", "invoice_number")
        )

    @property
    def refusal(self):
        if self.nonexistent:
            return (
                f"{len(self.nonexistent)} reading(s) with energy at a time that does not exist in "
                "Swiss time (DST start); fix or delete them first."
            )
        if self.collisions:
            return f"{len(self.collisions)} target slot(s) are already taken by readings outside the selection."
        return None


class Command(BaseCommand):
    help = (
        "Re-anchor readings from legacy offset-less CSV imports (read as UTC before ADR 0026) "
        "to Swiss local time. Dry run unless --apply is given."
    )

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="List legacy CSV batches and exit.")
        parser.add_argument("--zev", help="With --list: only this ZEV's batches.")
        parser.add_argument("--batch", action="append", default=[], help="Batch id to re-anchor (repeatable).")
        parser.add_argument("--apply", action="store_true", help="Write the changes (default: dry run).")
        parser.add_argument(
            "--allow-invoiced", action="store_true",
            help="Proceed although approved, sent or paid invoices cover moved readings.",
        )

    def handle(self, *args, **options):
        if options["list"]:
            self._list(options["zev"])
            return
        if not options["batch"]:
            raise CommandError("Pass --list, or one or more --batch <batch_id>.")

        logs = self._resolve_batches(options["batch"])
        self._run(logs, apply=options["apply"], allow_invoiced=options["allow_invoiced"])
        if not options["apply"]:
            self.stdout.write("Dry run: nothing was written. Re-run with --apply to re-anchor.")

    def _list(self, zev_id):
        batches = legacy_batches().select_related("zev").order_by("created_at")
        if zev_id:
            batches = batches.filter(zev_id=zev_id)
        stats = {
            row["import_batch"]: row
            for row in MeterReading.objects.filter(import_batch__in=batches.values("batch_id"))
            .values("import_batch")
            .annotate(count=Count("pk"), first=Min("timestamp"), last=Max("timestamp"))
        }
        if not batches:
            self.stdout.write("No legacy CSV batches.")
            return
        for log in batches:
            row = stats.get(log.batch_id)
            readings = row["count"] if row else 0
            span = f"{row['first'].isoformat()} – {row['last'].isoformat()}" if row else "no readings left"
            created = log.created_at.astimezone(business_tz()).strftime("%Y-%m-%d %H:%M")
            self.stdout.write(
                f"{log.batch_id}  {log.zev.name if log.zev else '-'}  {log.filename}  "
                f"imported {created}  {readings} readings  {span}"
            )

    def _resolve_batches(self, batch_ids):
        logs = []
        refused = []
        for batch_id in batch_ids:
            log = ImportLog.objects.filter(batch_id=batch_id).order_by("created_at").first()
            if log is None:
                refused.append(f"{batch_id}: no such import batch")
            elif log.source != ImportSource.CSV:
                refused.append(f"{batch_id}: {log.source} imports carry offsets and are already correct")
            elif log.timestamp_timezone:
                refused.append(f"{batch_id}: already read as {log.timestamp_timezone}")
            else:
                logs.append(log)
        if refused:
            raise CommandError("Refused, nothing was written:\n  " + "\n  ".join(refused))
        return logs

    def _run(self, logs, *, apply, allow_invoiced):
        plan = SelectionPlan(logs)
        for log in logs:
            counts = plan.per_batch[log.batch_id]
            self.stdout.write(
                f"Batch {log.batch_id} ({log.filename}): {counts['moved']} reading(s) to move"
                + (f", {counts['dropped']} zero-energy reading(s) in the spring DST gap to delete" if counts["dropped"] else "")
                + "."
            )
        if plan.moves:
            _pk, first_old, first_new = plan.moves[0]
            self.stdout.write(f"  e.g. {first_old.isoformat()} → {first_new.isoformat()}")
        for pk, ts in plan.nonexistent[:MAX_LISTED]:
            self.stdout.write(f"  Non-existent Swiss time with energy: {ts.isoformat()} (reading {pk})")
        for mp_id, ts, direction in plan.collisions[:MAX_LISTED]:
            self.stdout.write(f"  Collision: metering point {mp_id} {direction} at {ts.isoformat()}")
        for invoice in plan.invoices[:MAX_LISTED]:
            self.stdout.write(
                f"  Covered by {invoice.status} invoice {invoice.invoice_number} "
                f"({invoice.period_start} – {invoice.period_end}); it will not change."
            )

        refusal = plan.refusal
        if refusal is None and plan.invoices and not allow_invoiced:
            refusal = f"{len(plan.invoices)} approved/sent/paid invoice(s) cover these readings; pass --allow-invoiced."
        if refusal:
            raise CommandError(f"Refused, nothing was written: {refusal}")
        if not apply:
            return

        with transaction.atomic():
            MeterReading.objects.filter(pk__in=[pk for pk, _ in plan.dropped]).delete()
            # Every reading moves to an earlier instant, so in ascending order
            # each target was vacated by an earlier reading before it is taken.
            for pk, _old, new in plan.moves:
                MeterReading.objects.filter(pk=pk).update(timestamp=new)
            for log in logs:
                counts = plan.per_batch[log.batch_id]
                log.timestamp_timezone = str(business_tz())
                log.save(update_fields=["timestamp_timezone"])
                record_audit_event(
                    action_category=AuditActionCategory.IMPORT,
                    action_type="import.readings_reanchored",
                    target_type="metering.ImportLog",
                    target=log,
                    target_id=str(log.id),
                    target_display=str(log.batch_id),
                    zev=log.zev,
                    summary=f"Re-anchored {counts['moved']} reading(s) of import {log.filename} to Swiss time.",
                    source=AuditEventSource.MANAGEMENT_COMMAND,
                    metadata={
                        "batch_id": str(log.batch_id),
                        "zev_id": str(log.zev_id) if log.zev_id else None,
                        "moved": counts["moved"],
                        "dropped_nonexistent": counts["dropped"],
                        "allow_invoiced": allow_invoiced,
                    },
                )
        self.stdout.write(self.style.SUCCESS(f"Re-anchored {len(plan.moves)} reading(s) in {len(logs)} batch(es)."))
