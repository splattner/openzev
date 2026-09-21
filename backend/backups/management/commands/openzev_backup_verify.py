"""Check a backup archive without restoring it.

Re-reads the whole file: decrypts it if needed, then checks every member's
SHA-256 and record count against the manifest, and that nothing is present
that the manifest does not vouch for::

    manage.py openzev_backup_verify /var/backups/openzev/openzev-backup-...zip.enc
"""

from django.core.management.base import BaseCommand, CommandError

from backups import archive, crypto


class Command(BaseCommand):
    help = "Verify a backup archive's integrity without restoring anything."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to a backup archive (encrypted or not).")

    def handle(self, *args, **options):
        try:
            handle = open(options["file"], "rb")  # noqa: SIM115 - closed below
        except OSError as exc:
            raise CommandError(f"Cannot read {options['file']}: {exc.strerror}.") from exc

        with handle:
            try:
                result = archive.verify_archive(handle)
            except archive.ArchiveError as exc:
                for failure in exc.failures:
                    self.stderr.write(f"  - {failure}")
                if exc.total_failures > len(exc.failures):
                    self.stderr.write(f"  ... and {exc.total_failures - len(exc.failures)} more")
                raise CommandError(str(exc)) from exc
            except crypto.BackupCryptoError as exc:
                raise CommandError(str(exc)) from exc

        manifest = result["manifest"]
        self.stdout.write(self.style.SUCCESS("Backup verified."))
        self.stdout.write(f"  scope      {manifest['scope']}")
        self.stdout.write(f"  created    {manifest['created_at']}")
        self.stdout.write(f"  instance   {manifest.get('instance_name') or '-'}")
        self.stdout.write(f"  zevs       {', '.join(z['name'] for z in manifest['zevs']) or '-'}")
        self.stdout.write(f"  members    {result['members']}")
        self.stdout.write(f"  records    {result['records']:,}")
        encryption = manifest.get("encryption")
        self.stdout.write(f"  encrypted  {'yes (key ' + encryption['key_fingerprint'] + ')' if encryption else 'NO'}")
