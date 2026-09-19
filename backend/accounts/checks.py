"""Django system checks for the accounts app.

Imported for its side effect (the ``@register`` decorators run at import
time) from ``AccountsConfig.ready()``, the same pattern used for ``schema``.
"""

from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security)
def mfa_key_configured(app_configs, **kwargs):
    """Warn when no key is configured for TOTP secret encryption.

    Not an error: an instance with MFA_ENCRYPTION_KEYS unset just cannot
    enrol anyone in two-factor authentication yet (accounts.mfa_crypto
    refuses with a 503 naming this setting) — a valid, if incomplete, state
    for a fresh or upgraded deployment. Surfacing it here means `manage.py
    check`, which CI already runs, catches a deployment that meant to
    require MFA but never set the key.
    """
    if settings.MFA_ENCRYPTION_KEYS:
        return []
    return [
        Warning(
            "MFA_ENCRYPTION_KEYS is not configured. Two-factor authentication "
            "enrolment will be refused until it is set.",
            hint=(
                'Generate one with `python -c "from cryptography.fernet import '
                'Fernet; print(Fernet.generate_key().decode())"` and set it as '
                "MFA_ENCRYPTION_KEYS. See ADR 0021."
            ),
            id="accounts.W001",
        )
    ]
