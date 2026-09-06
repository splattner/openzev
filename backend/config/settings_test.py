"""Test-only settings.

Imports the full production configuration and overrides only what makes the
suite faster without changing behaviour under test. Kept separate so production
password security is never weakened.
"""
from .settings import *  # noqa: F401,F403

# The default PBKDF2 hasher runs ~600k iterations per password; the suite creates
# well over a hundred users, so hashing dominates the run time. Tests don't need
# real password security — MD5 cuts the full suite from minutes to well under one.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Every participant read touches the geocoding cache (ParticipantSerializer's
# building_footprint field). Tests shouldn't need a real Redis instance for that —
# an in-memory cache behaves the same for anything under test.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Throttle counters live in that cache and survive between tests, so a suite
# that reuses one API key would start failing once it crossed the hourly limit —
# in whichever test happened to be the 601st. Tests that exercise throttling
# override the rate themselves.
# Derived from the real scopes rather than restated, so a throttle added to
# settings.py cannot be missed here — the failure that produces is a wall of
# ImproperlyConfigured in unrelated tests, which says nothing about the cause.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {
        scope: None
        for scope in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]  # noqa: F405
    },
}

# Pin the env-tunable upload caps to their defaults so a developer's local
# .env cannot change what the suite observes; limit tests patch the module
# constants directly.
IMPORT_MAX_ROWS = 200_000
TRANSFER_MAX_DECOMPRESSED_MB = 500
