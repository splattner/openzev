"""Admin-only platform health reporting (nav-regroup phase 3).

Backs the "System health" tab of the admin Overview hub: a read-only snapshot
of database, Celery worker/broker, and email-backend status. Every probe is
best-effort — a probe that cannot run (no Redis in a test/dev environment,
unreachable broker) reports ``status: "unknown"`` with the reason instead
of failing the whole endpoint, so the tab degrades gracefully the same way
the readiness cockpit does.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial

from django.conf import settings
from django.db import connection
from kombu import Producer
from kombu.pidbox import Mailbox

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsAdmin

# Short, fixed timeouts: this view backs a dashboard tab that refreshes
# occasionally, not a load balancer probe — waiting tens of seconds on a dead
# broker would hang the admin's page for no diagnostic value.
PING_TIMEOUT_SECONDS = 1.0
QUEUE_TIMEOUT_SECONDS = 1.0


class _ProbeMailbox(Mailbox):
    """Publish only on the probe connection, without publication retries.

    Celery's shared control mailbox can acquire a producer from the normal
    application pool even when ping receives an explicit connection. Kombu
    also retries publication independently of connection establishment.
    """

    @contextmanager
    def producer_or_acquire(self, producer=None, channel=None):
        with Producer(channel, auto_declare=False) as probe_producer:
            probe_producer.publish = partial(
                probe_producer.publish, retry_policy={"max_retries": 0}
            )
            yield probe_producer


def _ping_workers(app, conn):
    mailbox = _ProbeMailbox(
        app.conf.control_exchange,
        type="fanout",
        connection=conn,
        serializer=app.conf.task_serializer,
        accept=app.conf.accept_content,
    )
    return mailbox.multi_call("ping", timeout=PING_TIMEOUT_SECONDS)


def _probe_database() -> dict:
    engine = settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1]
    size_bytes: int | None = None
    status = "ok"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
            if engine == "postgresql":
                cursor.execute("SELECT pg_database_size(current_database())")
                size_bytes = int(cursor.fetchone()[0])
            elif engine == "sqlite3":
                # Includes in-memory databases and pages still in the WAL;
                # a SQLite URI is not necessarily an on-disk filename.
                cursor.execute("PRAGMA page_count")
                pages = int(cursor.fetchone()[0])
                cursor.execute("PRAGMA page_size")
                size_bytes = pages * int(cursor.fetchone()[0])
    except Exception:  # noqa: BLE001 — any probe failure degrades, never 500s
        status = "degraded"

    return {
        "status": status,
        "engine": engine,
        "size_bytes": size_bytes,
    }


def _probe_celery() -> dict:
    """Worker ping + broker queue depth, both best-effort.

    Returns ``status: "unknown"`` when no broker is reachable (local dev
    without Redis, CI, test suite) — that is a valid, reportable state, not
    an error.
    """
    workers_responding: int | None = None
    queue_depth: int | None = None
    error: str | None = None

    try:
        from config.celery import app as celery_app

        # The ping timeout only bounds waiting for replies. Bound connection
        # establishment and Redis socket operations too, and disable Kombu's
        # default connection retries for this interactive diagnostic.
        with celery_app.connection_for_write(
            connect_timeout=QUEUE_TIMEOUT_SECONDS,
            transport_options={
                **celery_app.conf.broker_transport_options,
                "socket_connect_timeout": QUEUE_TIMEOUT_SECONDS,
                "socket_timeout": QUEUE_TIMEOUT_SECONDS,
                "max_retries": 0,
            },
        ) as conn:
            conn.ensure_connection(max_retries=0)
            try:
                replies = _ping_workers(celery_app, conn)
                workers_responding = len(replies or [])
            except Exception as exc:  # noqa: BLE001
                error = type(exc).__name__
            try:
                if conn.transport.driver_type == "redis":
                    queue = celery_app.conf.task_default_queue
                    # queue_declare(passive=True) uses Redis transport's size
                    # calculation, including every configured priority bucket.
                    queue_depth = int(conn.default_channel.queue_declare(queue=queue, passive=True).message_count)
            except Exception:  # noqa: BLE001 — queue depth is optional diagnostics
                pass
    except Exception as exc:  # noqa: BLE001 — broker may simply not be running
        # Exception messages can contain broker URLs/credentials. The class is
        # sufficient diagnostic detail for this admin payload.
        error = type(exc).__name__

    if workers_responding is None:
        status = "unknown"
    elif workers_responding == 0:
        status = "degraded"
    else:
        status = "ok"

    payload: dict = {
        "status": status,
        "workers_responding": workers_responding,
        "queue_depth": queue_depth,
        "broker_configured": bool(settings.CELERY_BROKER_URL),
    }
    if error:
        payload["detail"] = error[:200]
    return payload


def _probe_email() -> dict:
    backend = settings.EMAIL_BACKEND
    if "smtp" in backend:
        mode = "smtp"
    elif "console" in backend:
        mode = "console"
    elif "locmem" in backend or "memory" in backend:
        mode = "memory"
    else:
        mode = "other"

    return {
        # Configuration reporting only: actually dialing the SMTP host here
        # would make the tab slow and flappy; misconfiguration shows up in
        # the email retry banners where users can act on it.
        "status": "ok",
        "mode": mode,
        "backend": backend.rsplit(".", 1)[-1],
    }


class SystemHealthView(APIView):
    """Snapshot of platform health for the admin System health tab.

    Admin-only: the payload names infrastructure details (broker backend,
    database engine and size) that only platform admins should see.
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, *args, **kwargs):
        return Response(
            {
                "database": _probe_database(),
                "celery": _probe_celery(),
                "email": _probe_email(),
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )
