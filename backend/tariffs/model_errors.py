"""Native Django validation errors shared by tariff models."""

from django.core.exceptions import ValidationError


def model_error(message, code, **params):
    # Keep percent signs in user text out of Django's interpolation template.
    return ValidationError(
        "%(diagnostic)s", code=code, params={"diagnostic": message, **params}
    )
