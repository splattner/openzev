from django.core.management.base import BaseCommand, CommandError

from inbox.backfill import backfill_invoices
from zev.models import Zev


class Command(BaseCommand):
    help = (
        "Deliver the stored PDF of every invoice that already reached its participant into the "
        "participant inbox. Idempotent. Lists the invoices that have no document to deliver."
    )

    def add_arguments(self, parser):
        parser.add_argument("--zev", help="Only this ZEV (id).")
        parser.add_argument("--dry-run", action="store_true", help="Report what would be delivered; write nothing.")

    def handle(self, *args, zev=None, dry_run=False, **options):
        zev_obj = None
        if zev:
            try:
                zev_obj = Zev.objects.get(pk=zev)
            except (Zev.DoesNotExist, ValueError, TypeError):
                raise CommandError(f"No ZEV with id {zev}.") from None
        report = backfill_invoices(zev=zev_obj, dry_run=dry_run)
        verb = "Would deliver" if dry_run else "Delivered"
        self.stdout.write(f"{verb} {report.delivered} invoice(s); {report.already_delivered} already in the inbox.")
        for number, reason in report.missing:
            self.stdout.write(self.style.WARNING(f"  skipped {number}: {reason}"))
        for number, error in report.failed:
            self.stdout.write(self.style.ERROR(f"  failed {number}: {error}"))
        if not report.clean:
            self.stdout.write(
                f"{len(report.missing)} without a document, {len(report.failed)} failed. "
                "These stay reachable through the live invoice endpoints; the cut-over waits for this list."
            )
