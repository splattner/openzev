"""Atomic reservation release for Django RedisCache (Valkey or Redis) and LocMemCache.

Uses backend internals; integration tests cover the pinned Django version.
Unsupported backends keep the reservation until it expires.
"""
import pickle

from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.core.cache.backends.redis import RedisCache


def delete_if_value(key: str, value: str) -> bool:
    """Delete an owned reservation atomically; unsupported backends retain it."""
    backend = caches["default"]
    key = backend.make_and_validate_key(key)
    if isinstance(backend, RedisCache):
        client = backend._cache.get_client(key, write=True)
        return bool(client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1, key, backend._cache._serializer.dumps(value),
        ))
    if isinstance(backend, LocMemCache):
        with backend._lock:
            if not backend._has_expired(key) and pickle.loads(backend._cache[key]) == value:
                return backend._delete(key)
    return False
