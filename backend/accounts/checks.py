"""Django system checks for the accounts app.

Imported for its side effect (the ``@register`` decorators run at import
time) from ``AccountsConfig.ready()``, the same pattern used for ``schema``.
"""

from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
FRONTEND_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


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


@register(Tags.security)
def webauthn_rp_configured(app_configs, **kwargs):
    """Warn when passkeys would be served under the development RP ID.

    A relying-party ID that does not match the domain the browser sees makes
    every WebAuthn ceremony fail with an opaque error the user cannot act on,
    so the operator is told here, once, instead. Skipped under DEBUG, where
    ``localhost`` is exactly right.
    """
    if settings.DEBUG or settings.WEBAUTHN_RP_ID != "localhost":
        return []
    return [
        Warning(
            "WEBAUTHN_RP_ID is still 'localhost'. Passkey registration and "
            "sign-in will fail for users on any other domain.",
            hint="Set WEBAUTHN_RP_ID to the domain users open OpenZEV on, and WEBAUTHN_ORIGIN to its full origin.",
            id="accounts.W002",
        )
    ]


@register(Tags.security)
def production_hosts_configured(app_configs, **kwargs):
    """Reject development host/origin defaults when ``DEBUG=False``."""
    if settings.DEBUG:
        return []
    errors = []
    hosts = [h.strip().lower() for h in settings.ALLOWED_HOSTS if h.strip()]
    if "*" in hosts or not hosts or set(hosts) <= LOOPBACK_HOSTS:
        errors.append(
            Error(
                "ALLOWED_HOSTS must not use development defaults in production.",
                hint="Set ALLOWED_HOSTS to the public hostname(s) of this instance. "
                '"*" disables Host header validation and must not be used.',
                id="accounts.E003",
            )
        )
    frontend_url = str(settings.FRONTEND_URL).strip()
    hostname = (urlparse(frontend_url if "://" in frontend_url else f"//{frontend_url}").hostname or "").lower()
    if not frontend_url or hostname in FRONTEND_LOOPBACK_HOSTS:
        errors.append(
            Error(
                "FRONTEND_URL must not use a development origin in production.",
                hint="Set FRONTEND_URL to the public base URL of the frontend.",
                id="accounts.E004",
            )
        )
    return errors
