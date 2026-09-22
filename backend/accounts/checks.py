"""Django system checks for the accounts app.

Imported for its side effect (the ``@register`` decorators run at import
time) from ``AccountsConfig.ready()``, the same pattern used for ``schema``.
"""

from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


def _is_public_https_origin(value):
    """Return whether value is a scheme/host-only public HTTPS origin."""
    try:
        parsed = urlparse(str(value).strip())
        hostname = (parsed.hostname or "").lower()
    except ValueError:
        return False
    return bool(
        parsed.scheme.lower() == "https"
        and parsed.netloc
        and hostname
        and hostname not in LOOPBACK_HOSTS
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _is_public_rp_id(value):
    """Return whether value is a non-loopback WebAuthn relying-party ID."""
    raw = str(value).strip()
    if not raw or "://" in raw or any(char in raw for char in "/?#@"):
        return False
    try:
        parsed = urlparse(f"//{raw}")
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return False
    return bool(hostname and hostname not in LOOPBACK_HOSTS and port is None and "*" not in raw)


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
    """Warn when passkeys are not configured for a public HTTPS origin.

    A relying-party ID or origin that does not match the domain the browser
    sees makes every WebAuthn ceremony fail with an opaque error the user
    cannot act on, so the operator is told here, once, instead. Skipped under
    DEBUG, where localhost is exactly right.
    """
    if settings.DEBUG or (
        _is_public_rp_id(settings.WEBAUTHN_RP_ID)
        and _is_public_https_origin(settings.WEBAUTHN_ORIGIN)
    ):
        return []
    return [
        Warning(
            "WEBAUTHN_RP_ID and WEBAUTHN_ORIGIN are not configured for a "
            "public HTTPS origin. Passkey registration and sign-in will fail.",
            hint="Set WEBAUTHN_RP_ID to the domain users open OpenZEV on, and WEBAUTHN_ORIGIN to its full HTTPS origin.",
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
    if not _is_public_https_origin(frontend_url):
        errors.append(
            Error(
                "FRONTEND_URL must be a public HTTPS origin in production.",
                hint="Set FRONTEND_URL to the public HTTPS base URL of the frontend.",
                id="accounts.E004",
            )
        )
    return errors


@register(Tags.security)
def production_configuration_configured(app_configs, **kwargs):
    """Reject incomplete security and email settings when ``DEBUG=False``."""
    if settings.DEBUG:
        return []
    errors = []

    csrf_origins = [str(origin).strip() for origin in settings.CSRF_TRUSTED_ORIGINS if str(origin).strip()]
    if not csrf_origins or any(not _is_public_https_origin(origin) for origin in csrf_origins):
        errors.append(
            Error(
                "CSRF_TRUSTED_ORIGINS must contain a public HTTPS origin in production.",
                hint="Set it to the HTTPS origin users open OpenZEV on, even for same-origin deployments.",
                id="accounts.E005",
            )
        )

    email_backend = str(settings.EMAIL_BACKEND).strip()
    console_backend = "django.core.mail.backends.console.EmailBackend"
    smtp_backend = "django.core.mail.backends.smtp.EmailBackend"
    if email_backend == console_backend:
        errors.append(
            Error(
                "The console email backend must not be used in production.",
                hint="Configure EMAIL_BACKEND for SMTP or another real delivery backend.",
                id="accounts.E006",
            )
        )
    elif email_backend == smtp_backend and (
        not str(settings.EMAIL_HOST).strip() or not str(settings.DEFAULT_FROM_EMAIL).strip()
    ):
        errors.append(
            Error(
                "SMTP production email requires EMAIL_HOST and DEFAULT_FROM_EMAIL.",
                hint="Configure the SMTP server and sender address in backend/.env.",
                id="accounts.E007",
            )
        )

    if not _is_public_rp_id(settings.WEBAUTHN_RP_ID):
        errors.append(
            Error(
                "WEBAUTHN_RP_ID must be a public relying-party domain in production.",
                hint="Set it to the bare domain users open OpenZEV on, without a scheme or port.",
                id="accounts.E008",
            )
        )
    if not _is_public_https_origin(settings.WEBAUTHN_ORIGIN):
        errors.append(
            Error(
                "WEBAUTHN_ORIGIN must be a public HTTPS origin in production.",
                hint="Set it to the full HTTPS origin where the frontend is served.",
                id="accounts.E009",
            )
        )
    return errors
