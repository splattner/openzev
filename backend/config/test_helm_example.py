"""Keep the Helm chart's documented production example deployable.

`charts/openzev/README.md` presents its "Example values" block as a complete
production-oriented configuration. The chart never sets `DEBUG`, which
defaults to `False`, and the backend image runs `manage.py migrate` before
gunicorn (`backend/Dockerfile`), so a values file that trips a production
system check (`accounts.E003`-`E009`) stops the pod at startup. The chart CI
job only runs `helm lint`/`helm template` against the development defaults in
`values.yaml`, so this test is the guard that maps the documented example
onto the settings the template would produce and runs `manage.py check`.
"""

import re
from pathlib import Path

import yaml
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from config.settings import validate_secret_key

README = Path(__file__).resolve().parents[2] / "charts" / "openzev" / "README.md"

# Development defaults the settings module falls back to when the chart omits
# the corresponding environment variable (see config/settings.py and the
# conditional env entries in charts/openzev/templates/backend-deployment.yaml).
_DEV_ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
_DEV_CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]
_DEV_FRONTEND_URL = "http://localhost:5173"
_DEV_RP_ID = "localhost"
_CONSOLE_EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


def _example_values() -> dict:
    """Return the parsed YAML block under the README's "## Example values"."""
    text = README.read_text(encoding="utf-8")
    if "## Example values" not in text:
        raise AssertionError(f"README section '## Example values' not found in {README}")
    section = text.split("## Example values", 1)[1]
    match = re.search(r"```yaml\n(.*?)```", section, re.S)
    if match is None:
        raise AssertionError(f"no yaml example block under '## Example values' in {README}")
    values = yaml.safe_load(match.group(1))
    if not isinstance(values, dict):
        raise AssertionError(f"example values block in {README} is not a YAML mapping")
    return values


def _split(raw) -> list[str]:
    """Split a comma-separated values entry like Django's env.list()."""
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def _effective_settings(values: dict) -> dict:
    """Map example values to the settings the backend template would produce.

    Mirrors `charts/openzev/templates/backend-deployment.yaml`: unconditional
    env entries use the example value, conditional ones fall back to the
    development defaults from `config/settings.py` when absent or empty.
    """
    backend = values.get("backend") or {}
    webauthn = values.get("webauthn") or {}
    email = values.get("email") or {}
    cors_origins = _split(backend.get("corsAllowedOrigins") or "")
    # backend-deployment.yaml: csrfTrustedOrigins falls back to
    # corsAllowedOrigins, and settings.py falls back to CORS_ALLOWED_ORIGINS.
    csrf_origins = _split(backend.get("csrfTrustedOrigins") or "") or cors_origins
    return {
        "FRONTEND_URL": str(values.get("frontendUrl") or _DEV_FRONTEND_URL),
        "ALLOWED_HOSTS": _split(backend.get("allowedHosts") or "") or _DEV_ALLOWED_HOSTS,
        "CORS_ALLOWED_ORIGINS": cors_origins or _DEV_CORS_ORIGINS,
        "CSRF_TRUSTED_ORIGINS": csrf_origins or _DEV_CORS_ORIGINS,
        "WEBAUTHN_RP_ID": str(webauthn.get("rpId") or _DEV_RP_ID),
        "WEBAUTHN_ORIGIN": str(webauthn.get("origin") or _DEV_FRONTEND_URL),
        "EMAIL_BACKEND": str(email.get("backend") or _CONSOLE_EMAIL_BACKEND),
        "EMAIL_HOST": str(email.get("host") or "localhost"),
        "DEFAULT_FROM_EMAIL": str(email.get("defaultFromEmail") or "openzev@example.com"),
    }


class HelmExampleValuesTests(SimpleTestCase):
    def test_example_passes_production_system_checks(self):
        """The documented example must satisfy every DEBUG=False check.

        `call_command("check")` raises SystemCheckError naming the failed
        check IDs, so a regression here fails with the offending setting.
        """
        with override_settings(DEBUG=False, **_effective_settings(_example_values())):
            call_command("check")

    def test_example_secret_key_is_not_the_insecure_placeholder(self):
        """The template would otherwise boot with the placeholder key and die.

        `validate_secret_key` runs at settings import time, which is already
        past by the time tests execute, so invoke it with the effective value
        the template renders: a Kubernetes secret, or `secretKey.value`.
        """
        secret = _example_values().get("secretKey") or {}
        if (secret.get("existingSecret") or {}).get("name"):
            effective_key = "a-real-key-from-the-kubernetes-secret"
        else:
            effective_key = str(secret.get("value") or "")
        validate_secret_key(False, effective_key)
