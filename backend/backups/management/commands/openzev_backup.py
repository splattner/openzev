"""Take a backup from the command line.

Runs in-process, with no Celery broker involved, so it works from cron, from a
deploy script, and on a host where only the database is up::

    manage.py openzev_backup --destination nightly
    manage.py openzev_backup --path /var/backups/openzev
    manage.py openzev_backup --destination nightly --zev "Sonnenhof"
"""

import uuid

from django.core.management.base import BaseCommand, CommandError

from audit.models import AuditEventSource
from backups import crypto
from backups.models import BackupDestination, BackupDestinationKind, BackupJob, BackupJobScope
from backups.storage import DestinationError, validate_local_path
from backups.tasks import execute_backup_job
from zev.models import Zev


class Command(BaseCommand):
    help = "Back up the whole instance, or one ZEV, to a backup destination or a local directory."

    def add_arguments(self, parser):
        where = parser.add_mutually_exclusive_group(required=True)
        where.add_argument("--destination", help="Name of a configured backup destination.")
        where.add_argument("--path", help="Write to this local directory instead, without a saved destination.")
        parser.add_argument("--zev", help="Back up only this ZEV (its id or exact name) instead of the whole instance.")

    def _resolve_zev(self, value):
        try:
            return Zev.objects.get(pk=uuid.UUID(value))
        except ValueError:
            pass
        except Zev.DoesNotExist:
            raise CommandError(f"No ZEV with id {value}.") from None
        matches = list(Zev.objects.filter(name=value))
        if not matches:
            raise CommandError(f"No ZEV named {value!r}.")
        if len(matches) > 1:
            ids = ", ".join(str(z.pk) for z in matches)
            raise CommandError(f"{len(matches)} ZEVs are named {value!r}; pass one of these ids instead: {ids}")
        return matches[0]

    def handle(self, *args, **options):
        saved = None
        adhoc = None
        if options["destination"]:
            try:
                saved = BackupDestination.objects.get(name=options["destination"])
            except BackupDestination.DoesNotExist:
                raise CommandError(f"No backup destination named {options['destination']!r}.") from None
            if not saved.enabled:
                raise CommandError(f"Destination {saved.name!r} is disabled.")
        else:
            problem = validate_local_path(options["path"])
            if problem:
                raise CommandError(problem)
            adhoc = BackupDestination(name="(command line)", kind=BackupDestinationKind.LOCAL, path=options["path"])

        zev = self._resolve_zev(options["zev"]) if options["zev"] else None

        try:
            encrypting = crypto.encryption_configured()
        except crypto.BackupCryptoError as exc:
            raise CommandError(str(exc)) from exc
        if not encrypting:
            self.stderr.write(self.style.WARNING(
                "WARNING: BACKUP_ENCRYPTION_KEYS is not set, so this archive will NOT be encrypted. "
                "It contains password hashes, participant personal data, invoices and the OAuth client "
                "secret in the clear. Set a key before storing it anywhere shared."
            ))

        job = BackupJob.objects.create(
            scope=BackupJobScope.ZEV if zev else BackupJobScope.INSTANCE, zev=zev, destination=saved,
        )
        self.stdout.write(f"Backing up {'ZEV ' + zev.name if zev else 'the whole instance'}...")
        try:
            result = execute_backup_job(job.pk, source=AuditEventSource.MANAGEMENT_COMMAND, destination=adhoc)
        except DestinationError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - the job row and log carry the detail
            job.refresh_from_db()
            raise CommandError(job.error_message or f"Backup failed: {exc}") from exc

        job.refresh_from_db()
        self.stdout.write(self.style.SUCCESS("Backup complete."))
        self.stdout.write(f"  location   {result['location']}")
        self.stdout.write(f"  size       {result['bytes']:,} bytes")
        self.stdout.write(f"  sha256     {job.archive_sha256}")
        self.stdout.write(f"  encrypted  {'yes (key ' + job.encryption_key_fingerprint + ')' if result['encrypted'] else 'NO'}")
        missing = sum(len(z["media"]["missing"]) for z in job.manifest_json.get("zevs", []))
        if missing:
            self.stderr.write(self.style.WARNING(
                f"WARNING: {missing} invoice PDF(s) are referenced in the database but missing from storage; "
                "they are not in this backup. See the manifest's media.missing lists."
            ))
