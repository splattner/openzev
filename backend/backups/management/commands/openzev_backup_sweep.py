"""Apply backup retention and expiry, and recover stalled jobs — from cron, without beat.

The built-in hourly sweep does this too. Use this where no beat process runs, or
with ``--dry-run`` to see what a destination's retention setting would delete
before trusting it::

    manage.py openzev_backup_sweep --dry-run
    manage.py openzev_backup_sweep
"""

from django.core.management.base import BaseCommand, CommandError

from audit.models import AuditEventSource
from backups import retention


class Command(BaseCommand):
    help = "Delete backups past their retention or expiry, and fail jobs a stopped worker left behind."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted; change nothing.")

    def handle(self, *args, **options):
        report = retention.sweep(dry_run=options["dry_run"], source=AuditEventSource.MANAGEMENT_COMMAND)
        verb = "Would delete" if report["dry_run"] else "Deleted"
        for step, label in (("expired", "expired"), ("retention", "beyond retention")):
            for name in report[step]:
                self.stdout.write(f"  {verb} ({label}): {name}")
        for job_id in report["stalled"]:
            self.stdout.write(f"  {'Would fail' if report['dry_run'] else 'Failed'} stalled job {job_id}")
        total = len(report["expired"]) + len(report["retention"]) + len(report["stalled"])
        self.stdout.write(self.style.SUCCESS(
            f"{'Dry run: ' if report['dry_run'] else ''}{total} item(s)."
        ))
        if report["errors"]:
            raise CommandError(
                f"{report['errors']} backup file(s) could not be deleted; see the server log. The others were done."
            )
