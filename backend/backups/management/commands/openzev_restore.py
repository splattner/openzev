"""Restore a whole instance, or one community, from a backup archive.

**Whole instance** — meant for a fresh installation: migrate the database, point this command at a
backup, and every account, setting, community, invoice PDF and audit event comes
back with its original identifiers::

    manage.py migrate
    manage.py openzev_restore --mode instance --from /var/backups/openzev/openzev-backup-....zip.enc --dry-run
    manage.py openzev_restore --mode instance --from /var/backups/openzev/openzev-backup-....zip.enc

    manage.py openzev_restore --mode instance --from s3://bucket/openzev/backup.zip.enc --region eu-central-1

**One community** — into a running instance, leaving every other community, every
account and the audit trail alone. Preview first; a real run takes a safety backup
of the community as it is now, to the destination you name::

    manage.py openzev_restore --mode zev --from /var/backups/openzev/openzev-backup-....zip.enc \
        --zev "Sonnenhof" --dry-run
    manage.py openzev_restore --mode zev --from /var/backups/openzev/openzev-backup-....zip.enc \
        --zev "Sonnenhof" --path /var/backups/openzev/safety

Deliberately a command and not an API endpoint: restoring an instance replaces
every account, including the one that would be asking, so it is an operator
action taken on the host, not a button (ADR 0023). Stop the web and worker
processes first.
"""

import tempfile
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from audit.models import AuditEventSource
from backups import archive, crypto, restore
from backups.models import BackupDestination, BackupDestinationKind, RestoreJob
from backups.restore_zev import RestoreRefused
from backups.storage import DestinationError, fetch_archive, validate_local_path
from backups.tasks import execute_restore_job
from zev.models import Zev


class Command(BaseCommand):
    help = "Restore the whole instance (a fresh installation) or one community from a backup archive."

    def add_arguments(self, parser):
        parser.add_argument("--mode", required=True, choices=["instance", "zev"], help="What to restore.")
        parser.add_argument(
            "--from", dest="source", required=True,
            help="A backup archive: a file path, or s3://bucket/key (credentials from BACKUP_S3_* or the environment).",
        )
        parser.add_argument("--endpoint-url", default="", help="S3-compatible endpoint, for a non-AWS store.")
        parser.add_argument("--region", default="", help="S3 region.")
        parser.add_argument("--dry-run", action="store_true", help="Check the archive and report; change nothing.")
        parser.add_argument(
            "--force", action="store_true",
            help=(
                "instance: replace an instance that already has data (everything it holds is deleted first). "
                "zev: go ahead although the restore would delete or roll back issued invoices or contracts."
            ),
        )
        parser.add_argument("--zev", help="zev mode: the community to restore (its id, or the exact name of an existing one).")
        where = parser.add_mutually_exclusive_group()
        where.add_argument("--destination", help="zev mode: saved destination for the safety backup taken first.")
        where.add_argument("--path", help="zev mode: local directory for the safety backup taken first.")

    def handle(self, *args, **options):
        zev_only = [flag for flag in ("zev", "destination", "path") if options[flag]]
        if options["mode"] == "instance" and zev_only:
            raise CommandError(f"--{zev_only[0]} applies to --mode zev only.")
        if options["mode"] == "zev" and not options["zev"]:
            raise CommandError("--mode zev needs --zev: the community to restore.")

        source = options["source"]
        if source.startswith("s3://"):
            with tempfile.TemporaryDirectory(dir=settings.BACKUP_WORK_DIR or None) as work:
                target = Path(work) / "backup"
                self.stdout.write(f"Downloading {source}…")
                try:
                    fetch_archive(source, target, endpoint_url=options["endpoint_url"], region=options["region"])
                except DestinationError as exc:
                    raise CommandError(str(exc)) from exc
                self._dispatch(target, options)
        else:
            self._dispatch(Path(source), options)

    def _dispatch(self, path, options):
        if options["mode"] == "zev":
            self._restore_zev(path, options)
        else:
            self._restore_from_file(path, options)

    # ── one community ────────────────────────────────────────────────────────

    def _resolve_zev(self, value):
        try:
            zev_id = uuid.UUID(value)
        except ValueError:
            matches = list(Zev.objects.filter(name=value))
            if not matches:
                raise CommandError(
                    f"No community named {value!r} exists here. A community that was deleted is named by its id "
                    "(openzev_backup_verify lists the ids in a backup)."
                ) from None
            if len(matches) > 1:
                raise CommandError(
                    f"{len(matches)} communities are named {value!r}; pass one of these ids instead: "
                    + ", ".join(str(z.pk) for z in matches)
                ) from None
            return matches[0].pk, matches[0].name
        existing = Zev.objects.filter(pk=zev_id).first()
        return zev_id, existing.name if existing else ""

    def _safety_destination(self, options, *, needed):
        """``(saved destination or None, ad-hoc destination or None)`` for the safety backup."""
        if options["destination"]:
            try:
                saved = BackupDestination.objects.get(name=options["destination"])
            except BackupDestination.DoesNotExist:
                raise CommandError(f"No backup destination named {options['destination']!r}.") from None
            if not saved.enabled:
                raise CommandError(f"Destination {saved.name!r} is disabled.")
            return saved, None
        if options["path"]:
            problem = validate_local_path(options["path"])
            if problem:
                raise CommandError(problem)
            return None, BackupDestination(name="(command line)", kind=BackupDestinationKind.LOCAL, path=options["path"])
        if needed:
            raise CommandError(
                "A real restore takes a safety backup of the community first: say where with --destination NAME "
                "or --path DIR (or preview with --dry-run)."
            )
        return None, None

    def _restore_zev(self, path, options):
        try:
            path.open("rb").close()
        except OSError as exc:
            raise CommandError(f"Cannot read {options['source']}: {exc.strerror}.") from exc
        zev_id, name = self._resolve_zev(options["zev"])
        needs_safety = not options["dry_run"] and bool(name)
        saved, adhoc = self._safety_destination(options, needed=needs_safety)

        job = RestoreJob.objects.create(
            target_zev_id=zev_id, target_zev_name=name, source_description=options["source"][:500],
            dry_run=options["dry_run"], force=options["force"], safety_destination=saved,
        )
        self.stdout.write(f"{'Previewing the restore of' if job.dry_run else 'Restoring'} {name or zev_id}…")
        plan = None
        try:
            plan = execute_restore_job(
                job.pk, source=AuditEventSource.MANAGEMENT_COMMAND, archive_file=path, safety_destination=adhoc,
            )
        except RestoreRefused as exc:
            self._print_plan(exc.plan, forced=job.force)
            raise CommandError(str(exc)) from exc
        except archive.ArchiveError as exc:
            for failure in exc.failures:
                self.stderr.write(f"  - {failure}")
            raise CommandError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - the job row carries the safe message; the log the detail
            job.refresh_from_db()
            raise CommandError(job.error_message or f"Restore failed: {exc}") from exc

        self._print_plan(plan, forced=job.force)
        if job.dry_run and plan["blocked"]:
            raise CommandError("This restore would be refused; see the problems above.")
        if job.dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run: nothing was changed."))
            return
        job.refresh_from_db()
        self.stdout.write(self.style.SUCCESS("Restore complete."))
        if job.safety_backup is not None:
            self.stdout.write(f"  safety backup  {job.safety_backup.archive_location}")

    def _print_plan(self, plan, *, forced=False):
        zev = plan["zev"]
        target = zev["name"] + (f" (now called {zev['current_name']})" if zev["exists_now"] and zev["current_name"] != zev["name"] else "")
        self.stdout.write(f"  community      {target}{'' if zev['exists_now'] else ' — does not exist now; it will be recreated'}")
        backup = plan.get("backup", {})
        self.stdout.write(f"  backup taken   {backup.get('created_at', '-')} (version {backup.get('openzev_version') or '-'})")
        self.stdout.write("  section              in backup       now")
        for name, counts in plan["sections"].items():
            note = "  (kept, never restored)" if counts["kept"] else ""
            self.stdout.write(f"    {name:18s} {counts['backup']:>10,} {counts['current']:>10,}{note}")
        accounts = plan["accounts"]
        self.stdout.write(f"  accounts       {accounts['relink']} relinked by email or username")
        if accounts["missing"]:
            self.stderr.write(self.style.WARNING(
                "WARNING: no matching account for " + ", ".join(accounts["missing"]) + "; those links are left empty. "
                "No account is ever created by a restore."
            ))
        self.stdout.write(f"  invoice PDFs   {plan['media']['files']} in the backup")
        if plan["media"]["missing"]:
            self.stderr.write(self.style.WARNING(
                f"WARNING: {plan['media']['missing']} invoice PDF(s) were already missing when the backup was taken."
            ))
        for conflict in plan["conflicts"]:
            if conflict["overridable"]:
                how = "overridden with --force" if forced else "needs --force"
            else:
                how = "cannot be overridden"
            self.stderr.write(self.style.ERROR(f"  PROBLEM: {conflict['kind']}: {conflict['detail']} ({how})"))
        if plan.get("restored"):
            self.stdout.write(f"  restored       {sum(plan['restored'].values()):,} records")

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
