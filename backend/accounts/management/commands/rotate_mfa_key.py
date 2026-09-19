"""
Django management command: python manage.py rotate_mfa_key

Re-encrypts every TotpDevice.secret_encrypted with the first key in
MFA_ENCRYPTION_KEYS.

Rotation is: prepend the new key ahead of the old one, deploy, run this
command, then drop the old key once it is no longer needed for decryption.
Safe to re-run — every device is re-encrypted with the current first key
regardless of which key it was already under, so running it twice with an
unchanged key list just re-encrypts everything a second time (a fresh Fernet
token each time; Fernet is non-deterministic, but the plaintext is unchanged).

Deliberately not a Celery task: this runs once per key rotation, by an
operator watching the output, not on a schedule.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.mfa_crypto import MfaKeyError, MfaNotConfigured, decrypt_secret, encrypt_secret
from accounts.models import TotpDevice
from audit.models import AuditActionCategory, AuditEventSource
from audit.services import record_audit_event


class Command(BaseCommand):
    help = "Re-encrypt every TOTP secret with the first key in MFA_ENCRYPTION_KEYS."

    def handle(self, *args, **options):
        with transaction.atomic():
            devices = TotpDevice.objects.select_for_update()
            count = devices.count()
            if count == 0:
                self.stdout.write("No TOTP devices to re-encrypt.")
                return

            for device in devices:
                try:
                    secret = decrypt_secret(bytes(device.secret_encrypted))
                except MfaNotConfigured:
                    raise CommandError(
                        "MFA_ENCRYPTION_KEYS is empty — there is no key to rotate to."
                    ) from None
                except MfaKeyError:
                    raise CommandError(
                        f"Device {device.pk} (user {device.user_id}) cannot be decrypted by any "
                        "configured key. If a key was dropped from MFA_ENCRYPTION_KEYS before this "
                        "device was re-encrypted, restore it, run this command, then drop it again. "
                        "No devices were modified — the transaction rolled back."
                    ) from None
                device.secret_encrypted = encrypt_secret(secret)
                device.save(update_fields=["secret_encrypted"])

            record_audit_event(
                action_category=AuditActionCategory.AUTH,
                action_type="auth.mfa.key_rotated",
                target_type="accounts.TotpDevice",
                summary=f"Re-encrypted {count} TOTP secret(s) under the current MFA_ENCRYPTION_KEYS[0].",
                source=AuditEventSource.MANAGEMENT_COMMAND,
                metadata={"devices_reencrypted": count},
            )

        self.stdout.write(self.style.SUCCESS(f"Re-encrypted {count} TOTP device(s)."))
