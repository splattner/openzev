"""
Django management command: python manage.py rotate_integration_key

Re-encrypts every SupplementarySource.credential_encrypted with the first key
in INTEGRATION_ENCRYPTION_KEYS (ADR 0031).

Rotation is: prepend the new key ahead of the old one, deploy, run this
command, then drop the old key once it is no longer needed for decryption.
Safe to re-run: every credential is re-encrypted with the current first key
regardless of which key it was under. All-or-nothing: one credential that no
configured key can open rolls the whole run back.

Deliberately not a Celery task: it runs once per key rotation, by an operator
watching the output.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from audit.models import AuditActionCategory, AuditEventSource
from audit.services import record_audit_event
from metering.models import SupplementarySource
from metering.supplementary.crypto import (
    IntegrationKeyError,
    IntegrationNotConfigured,
    decrypt_secret,
    encrypt_secret,
)


class Command(BaseCommand):
    help = "Re-encrypt every integration credential with the first key in INTEGRATION_ENCRYPTION_KEYS."

    def handle(self, *args, **options):
        with transaction.atomic():
            sources = SupplementarySource.objects.select_for_update().exclude(credential_encrypted=b"")
            count = sources.count()
            if count == 0:
                self.stdout.write("No integration credentials to re-encrypt.")
                return

            for source in sources:
                try:
                    secret = decrypt_secret(bytes(source.credential_encrypted))
                except IntegrationNotConfigured:
                    raise CommandError(
                        "INTEGRATION_ENCRYPTION_KEYS is empty: there is no key to rotate to."
                    ) from None
                except IntegrationKeyError:
                    raise CommandError(
                        f"Source {source.pk} cannot be decrypted by any configured key. If a key was "
                        "dropped from INTEGRATION_ENCRYPTION_KEYS before this source was re-encrypted, "
                        "restore it, run this command, then drop it again. No sources were modified: "
                        "the transaction rolled back."
                    ) from None
                source.credential_encrypted = encrypt_secret(secret)
                source.save(update_fields=["credential_encrypted", "updated_at"])

            record_audit_event(
                action_category=AuditActionCategory.METERING,
                action_type="supplementary_source.key_rotated",
                target_type="metering.SupplementarySource",
                summary=f"Re-encrypted {count} integration credential(s) under the current INTEGRATION_ENCRYPTION_KEYS[0].",
                source=AuditEventSource.MANAGEMENT_COMMAND,
                metadata={"sources_reencrypted": count},
            )

        self.stdout.write(self.style.SUCCESS(f"Re-encrypted {count} integration credential(s)."))
