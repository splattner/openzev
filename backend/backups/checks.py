"""Django system checks for the backups app (ADR 0024).

Imported from ``BackupsConfig.ready()`` so the ``@register`` decorators run.
"""

from django.conf import settings
from django.core.checks import Tags, Warning, register
from django.db import DatabaseError


@register(Tags.database)
def scheduled_backup_is_encrypted(app_configs, databases=None, **kwargs):
    """Warn when a schedule would write unencrypted archives on its own.

    A database check, so it only runs under ``manage.py check --database default``
    — an ordinary ``check`` must not need a database. Encryption is optional
    (ADR 0024), which is exactly why a schedule that quietly produces plaintext
    archives full of password hashes and personal data, unattended and for months,
    deserves a warning of its own.
    """
    if not databases or "default" not in databases or settings.BACKUP_ENCRYPTION_KEYS:
        return []
    try:
        from .schedule import get_schedule

        enabled = get_schedule()["enabled"]
    except DatabaseError:
        return []  # not migrated yet: nothing is scheduled
    if not enabled:
        return []
    return [
        Warning(
            "Scheduled backups are enabled but BACKUP_ENCRYPTION_KEYS is not set, so every scheduled archive is "
            "written unencrypted.",
            hint=(
                'Generate a key with `python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32))'
                '.decode())"` and set it as BACKUP_ENCRYPTION_KEYS. See ADR 0024.'
            ),
            id="backups.W001",
        )
    ]
