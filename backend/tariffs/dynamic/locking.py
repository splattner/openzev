"""Short-lived per-source locks shared by fetch and maintenance operations."""

from contextlib import contextmanager
from uuid import uuid4

from django.core.cache import cache


SOURCE_LOCK_SECONDS = 30 * 60


@contextmanager
def dynamic_source_lock(source_id):
    """Try to serialize fetches and destructive maintenance for one source."""

    key = f"dynamic-tariff-source-lock:{source_id}"
    token = str(uuid4())
    acquired = cache.add(key, token, timeout=SOURCE_LOCK_SECONDS)
    try:
        yield acquired
    finally:
        # Avoid deleting a successor's lock if this lease expired while the
        # operation was still running.
        if acquired and cache.get(key) == token:
            cache.delete(key)
