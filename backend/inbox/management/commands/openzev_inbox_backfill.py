from django.core.management.base import BaseCommand, CommandError

from inbox.backfill import backfill_credits, backfill_invoices
from zev.models import Zev


class Command(BaseCommand):
    help = (
        "Deliver the stored PDF of every invoice and credit note that already reached its participant "
        "into the participant inbox. Idempotent. Lists the ones that have no document to deliver."
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
        verb = "Would deliver" if dry_run else "Delivered"
        clean = True
        for label, backfill in (("invoice", backfill_invoices), ("credit note", backfill_credits)):
            report = backfill(zev=zev_obj, dry_run=dry_run)
            self.stdout.write(
                f"{verb} {report.delivered} {label}(s); {report.already_delivered} already in the inbox."
            )
            for number, reason in report.missing:
                self.stdout.write(self.style.WARNING(f"  skipped {number}: {reason}"))
            for number, error in report.failed:
                self.stdout.write(self.style.ERROR(f"  failed {number}: {error}"))
            if not report.clean:
                clean = False
                self.stdout.write(f"{len(report.missing)} {label}(s) without a document, {len(report.failed)} failed.")
        if not clean:
            self.stdout.write(
                "These stay reachable through the live invoice and credit note endpoints; the cut-over waits for this list."
            )
