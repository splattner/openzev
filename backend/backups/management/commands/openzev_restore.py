"""Restore a whole instance from a backup archive.

Meant for a fresh installation: migrate the database, point this command at a
backup, and every account, setting, community, invoice PDF and audit event comes
back with its original identifiers::

    manage.py migrate
    manage.py openzev_restore --mode instance --from /var/backups/openzev/openzev-backup-....zip.enc --dry-run
    manage.py openzev_restore --mode instance --from /var/backups/openzev/openzev-backup-....zip.enc

    manage.py openzev_restore --mode instance --from s3://bucket/openzev/backup.zip.enc --region eu-central-1

Deliberately a command and not an API endpoint: restoring an instance replaces
every account, including the one that would be asking, so it is an operator
action taken on the host, not a button (ADR 0023). Stop the web and worker
processes first.
"""

import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backups import archive, crypto, restore
from backups.storage import DestinationError, fetch_archive


class Command(BaseCommand):
    help = "Restore the whole instance from a backup archive (a fresh installation, or --force to replace one)."

    def add_arguments(self, parser):
        parser.add_argument("--mode", required=True, choices=["instance"], help="What to restore.")
        parser.add_argument(
            "--from", dest="source", required=True,
            help="A backup archive: a file path, or s3://bucket/key (credentials from BACKUP_S3_* or the environment).",
        )
        parser.add_argument("--endpoint-url", default="", help="S3-compatible endpoint, for a non-AWS store.")
        parser.add_argument("--region", default="", help="S3 region.")
        parser.add_argument("--dry-run", action="store_true", help="Check the archive and report; change nothing.")
        parser.add_argument(
            "--force", action="store_true",
            help="Replace an instance that already has data. Everything it holds is deleted first.",
        )

    def handle(self, *args, **options):
        source = options["source"]
        if source.startswith("s3://"):
            self._restore_from_s3(source, options)
        else:
            self._restore_from_file(Path(source), options)

    def _restore_from_s3(self, url, options):
        with tempfile.TemporaryDirectory(dir=settings.BACKUP_WORK_DIR or None) as work:
            target = Path(work) / "backup"
            self.stdout.write(f"Downloading {url}…")
            try:
                fetch_archive(url, target, endpoint_url=options["endpoint_url"], region=options["region"])
            except DestinationError as exc:
                raise CommandError(str(exc)) from exc
            self._restore_from_file(target, options)

    def _restore_from_file(self, path, options):
        try:
            handle = path.open("rb")
        except OSError as exc:
            raise CommandError(f"Cannot read {path}: {exc.strerror}.") from exc

        with handle:
            try:
                report = restore.restore_instance(
                    handle,
                    dry_run=options["dry_run"],
                    force=options["force"],
                    progress=lambda message: self.stdout.write(f"  {message}"),
                )
            except archive.ArchiveError as exc:
                for failure in exc.failures:
                    self.stderr.write(f"  - {failure}")
                if exc.total_failures > len(exc.failures):
                    self.stderr.write(f"  ... and {exc.total_failures - len(exc.failures)} more")
                raise CommandError(str(exc)) from exc
            except (restore.RestoreError, crypto.BackupCryptoError) as exc:
                raise CommandError(str(exc)) from exc

        self._report(report)

    def _report(self, report):
        manifest = report.manifest
        for warning in report.warnings:
            self.stderr.write(self.style.WARNING(f"WARNING: {warning}"))
        if report.media_missing:
            self.stderr.write(self.style.WARNING(
                f"WARNING: {report.media_missing} invoice PDF(s) were already missing when the backup was taken, "
                "so they are not restored. Regenerate those invoices to recreate them."
            ))

        verb = "would restore" if report.dry_run else "restored"
        self.stdout.write(self.style.SUCCESS(
            "Dry run: the backup is intact and compatible, nothing was changed." if report.dry_run else "Restore complete."
        ))
        self.stdout.write(f"  backup taken  {manifest['created_at']} ({manifest.get('instance_name') or '-'})")
        self.stdout.write(f"  version       {manifest.get('openzev_version') or '-'}")
        self.stdout.write(f"  communities   {', '.join(z['name'] for z in manifest['zevs']) or '-'}")
        self.stdout.write(f"  records       {verb} {report.records:,}")
        for label, count in sorted(report.counts.items()):
            self.stdout.write(f"    {label:38s} {count:>10,}")
        if report.replaced:
            kinds = ", ".join(f"{label} {n:,}" for label, n in sorted(report.replaced.items()))
            self.stdout.write(f"  replaced      {sum(report.replaced.values()):,} existing rows ({kinds})")
        if report.dry_run:
            expected = sum(z["media"]["files"] for z in manifest["zevs"])
            self.stdout.write(f"  invoice PDFs  would restore {expected:,} file(s)")
        else:
            self.stdout.write(f"  invoice PDFs  {report.media_files:,} file(s), {report.media_bytes:,} bytes")
            self.stdout.write(f"  sequences     {len(report.sequences)} table(s) advanced past their restored ids")
            self.stdout.write("Start the web and worker processes again, then sign in with a restored account.")
