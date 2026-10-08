"""Django system checks for the metering app.

Imported for its side effect (the ``@register`` decorators run at import time)
from ``MeteringConfig.ready()``, as ``accounts.checks`` is.
"""

import os

from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security)
def integration_key_configured(app_configs, **kwargs):
    """Warn when supplementary energy data is forced on but no key can encrypt credentials.

    Environment only, on purpose: system checks run before (and without) a
    database, so the stored feature-flag value is not consulted here. The
    system-health view reports the stored case. Not an error: an instance with
    ``INTEGRATION_ENCRYPTION_KEYS`` unset just cannot connect pull sources (the
    API answers 503 naming the setting); push and file import keep working.
    """
    forced_on = os.environ.get("FEATURE_SUPPLEMENTARY_ENERGY_DATA_ENABLED", "").lower() in ("1", "true", "yes")
    if not forced_on or any(settings.INTEGRATION_ENCRYPTION_KEYS):
        return []
    return [
        Warning(
            "INTEGRATION_ENCRYPTION_KEYS is not configured, but supplementary energy data is "
            "enabled. Participants cannot connect a Solar Manager source until it is set.",
            hint=(
                'Generate one with `python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"` and set it as INTEGRATION_ENCRYPTION_KEYS. '
                "See ADR 0031."
            ),
            id="metering.W001",
        )
    ]
