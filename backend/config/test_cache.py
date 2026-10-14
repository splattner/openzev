import os
import uuid
from unittest.mock import patch

import pytest
from django.core.cache import caches
from django.test import override_settings

from config.cache import delete_if_value


@pytest.fixture(params=["locmem", "redis"])
def reservation_cache(request):
    prefix = "mail-slot-test-" + uuid.uuid4().hex
    if request.param == "redis":
        url = os.environ.get("TEST_VALKEY_URL")
        if not url:
            pytest.skip("Set TEST_VALKEY_URL to exercise the production Valkey/Redis operation")
        backend = {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": url}
    else:
        backend = {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": prefix}
    with override_settings(CACHES={"default": {**backend, "KEY_PREFIX": prefix}}):
        cache = caches["default"]
        try:
            yield cache
        finally:
            cache.delete("slot")


def test_owned_reservation_is_deleted(reservation_cache):
    reservation_cache.add("slot", "owner", 60)
    assert delete_if_value("slot", "owner")
    assert reservation_cache.get("slot") is None


def test_newer_owner_is_preserved(reservation_cache):
    reservation_cache.add("slot", "old-owner", 60)
    reservation_cache.set("slot", "new-owner", 60)
    assert not delete_if_value("slot", "old-owner")
    assert reservation_cache.get("slot") == "new-owner"


def test_missing_or_expired_reservation_is_not_deleted(reservation_cache):
    assert not delete_if_value("slot", "owner")
    reservation_cache.set("slot", "owner", 0)
    assert not delete_if_value("slot", "owner")


def test_release_never_uses_separate_public_get_and_delete(reservation_cache):
    from accounts.views import _release_mail_slot

    reservation_cache.add("slot", "owner", 60)
    with (
        patch.object(reservation_cache, "get", side_effect=AssertionError("non-atomic read")),
        patch.object(reservation_cache, "delete", side_effect=AssertionError("non-atomic delete")),
    ):
        _release_mail_slot("slot", "owner")
    assert reservation_cache.get("slot") is None


def test_replacement_before_the_redis_operation_is_preserved(reservation_cache):
    from accounts.views import _release_mail_slot

    from django.core.cache.backends.redis import RedisCache
    if not isinstance(reservation_cache, RedisCache):
        pytest.skip("Exercises Redis compare-and-delete")
    import redis

    reservation_cache.add("slot", "old-owner", 60)
    real_eval = redis.Redis.eval

    def replace_then_eval(client, *args, **kwargs):
        reservation_cache.set("slot", "new-owner", 60)
        return real_eval(client, *args, **kwargs)

    with patch.object(redis.Redis, "eval", new=replace_then_eval):
        _release_mail_slot("slot", "old-owner")
    assert reservation_cache.get("slot") == "new-owner"
