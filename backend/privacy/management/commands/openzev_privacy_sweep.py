"""Apply the privacy retention windows — from cron, without beat.

The built-in daily sweep does this too. Use this where no beat process runs, or
with ``--dry-run`` to see what the configured windows would remove before
trusting them::

    manage.py openzev_privacy_sweep --dry-run
    manage.py openzev_privacy_sweep
"""

from django.core.management.base import BaseCommand

from audit.models import AuditEventSource
from privacy import sweep

LABELS = (
    ("audit_network", "audit events with IP address / user agent blanked"),
    ("email_log", "invoice email logs with recipient blanked"),
)
TOKEN_LABELS = {
    "email_verification": "email verification tokens",
    "magic_link": "magic-link tokens",
    "onboarding": "participant onboarding tokens",
}


class Command(BaseCommand):
    help = "Blank old audit IPs and email recipients and delete spent one-time tokens, per the PRIVACY_* settings."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report the counts; change nothing.")

    def handle(self, *args, **options):
        report = sweep.sweep(dry_run=options["dry_run"], source=AuditEventSource.MANAGEMENT_COMMAND)
        verb = "Would affect" if report["dry_run"] else "Affected"
        for key, label in LABELS:
            self.stdout.write(f"  {verb}: {report[key]} {label}")
        for key, label in TOKEN_LABELS.items():
            self.stdout.write(f"  {verb}: {report['tokens'].get(key, 0)} {label}")
        self.stdout.write(self.style.SUCCESS(
            f"{'Dry run: ' if report['dry_run'] else ''}{report['total']} record(s)."
        ))
