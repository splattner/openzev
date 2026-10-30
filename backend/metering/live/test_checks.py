"""``metering.W002``: live data forced on while the cache is per process (SPEC-2026-live-energy-data §6.5)."""

import os
from unittest import mock

from django.test import SimpleTestCase, override_settings

from metering import checks

FLAG_ENV = "FEATURE_LIVE_ENERGY_DATA_ENABLED"
REDIS = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": "redis://x"}}
LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class LiveCacheCheckTests(SimpleTestCase):
    def run_check(self, env_value, caches):
        with mock.patch.dict("os.environ"):
            os.environ.pop(FLAG_ENV, None)
            if env_value is not None:
                os.environ[FLAG_ENV] = env_value
            with override_settings(CACHES=caches):
                return checks.live_cache_is_shared(None)

    def test_silent_when_the_feature_is_not_forced_on(self):
        self.assertEqual(self.run_check(None, LOCMEM), [])
        self.assertEqual(self.run_check("false", LOCMEM), [])

    def test_silent_with_a_shared_cache(self):
        self.assertEqual(self.run_check("true", REDIS), [])

    def test_warns_with_a_per_process_cache(self):
        result = self.run_check("true", LOCMEM)

        self.assertEqual([warning.id for warning in result], ["metering.W002"])
        self.assertIn("locmem", result[0].msg)
