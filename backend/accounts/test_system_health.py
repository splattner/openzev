"""Tests for the admin-only system-health endpoint (nav-regroup phase 3).

The endpoint must degrade gracefully: every probe is best-effort, so the
suite asserts on response shape and permissions, never on a live Redis or
SMTP being reachable.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.django_db

URL = "/api/v1/auth/system-health/"


@pytest.fixture(autouse=True)
def broker(monkeypatch):
    """No test relies on the developer's broker or broadcasts to real workers."""
    from config.celery import app
    from accounts import views_system

    connection = MagicMock()
    connection.transport.driver_type = "redis"
    connection.default_channel.queue_declare.return_value.message_count = 3
    factory = MagicMock()
    factory.return_value.__enter__.return_value = connection
    monkeypatch.setattr(app, "connection_for_write", factory)
    monkeypatch.setattr(views_system, "_ping_workers", MagicMock(return_value=[{"worker": {"ok": "pong"}}]))
    return connection, factory


def _assert_probe_shape(payload: dict) -> None:
    assert isinstance(payload, dict)
    assert payload["status"] in {"ok", "degraded", "unknown"}


def test_system_health_requires_authentication(api_client):
    response = api_client.get(URL)

    assert response.status_code == 401


def test_system_health_forbidden_for_non_admin(owner_client, participant_client):
    for client in (owner_client, participant_client):
        response = client.get(URL)

        assert response.status_code == 403


def test_system_health_returns_probe_snapshot(admin_client):
    response = admin_client.get(URL)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"database", "celery", "email", "checked_at"}
    _assert_probe_shape(body["database"])
    _assert_probe_shape(body["celery"])
    _assert_probe_shape(body["email"])
    # Configuration facts the tab renders directly.
    assert body["database"]["engine"]
    assert body["database"]["status"] == "ok"
    assert isinstance(body["database"]["size_bytes"], int | None)
    assert isinstance(body["celery"]["workers_responding"], int | None)
    assert isinstance(body["celery"]["queue_depth"], int | None)
    assert body["email"]["mode"] in {"smtp", "console", "memory", "other"}
    assert body["checked_at"]


def test_system_health_celery_probe_shape_without_broker(admin_client, broker):
    """Celery probe reports a shape even with no broker reachable (CI/dev).

    Connection failure must not expose broker credentials in the response.
    """
    connection, factory = broker
    connection.ensure_connection.side_effect = RuntimeError("redis://user:secret@broker")
    response = admin_client.get(URL)

    assert response.status_code == 200
    connection.ensure_connection.assert_called_once_with(max_retries=0)
    assert factory.call_args.kwargs["connect_timeout"] == 1.0
    assert "secret" not in response.content.decode()
    probe = response.json()["celery"]
    assert probe["status"] == "unknown"
    assert probe["status"] in {"ok", "degraded", "unknown"}
    assert "broker_configured" in probe


def test_system_health_database_degrades_gracefully(admin_client, monkeypatch):
    """A database probe failure downgrades the probe, not the endpoint."""

    from accounts import views_system

    class BrokenConnection:
        def cursor(self):
            raise RuntimeError("connection lost")

    # Patch only the module-local reference so the test client's own queries
    # (auth, DB access) keep using the real connection.
    monkeypatch.setattr(views_system, "connection", BrokenConnection())

    response = admin_client.get(URL)

    assert response.status_code == 200
    assert response.json()["database"]["status"] == "degraded"


def test_system_health_uses_configured_queue(admin_client, broker, monkeypatch):
    from config.celery import app

    monkeypatch.setitem(app.conf, "task_default_queue", "billing")
    response = admin_client.get(URL)
    assert response.status_code == 200
    assert response.json()["celery"]["queue_depth"] == 3
    broker[0].default_channel.queue_declare.assert_called_once_with(queue="billing", passive=True)


def test_probe_mailbox_uses_its_connection_without_publication_retries():
    """Exercise real Kombu publication, including a dropped connection.

    No application producer pool or network is involved. A broken publish
    must propagate immediately, rather than reconnecting with infinite retries.
    """
    from unittest.mock import patch

    from kombu import Connection
    from kombu.exceptions import OperationalError
    from accounts.views_system import _ProbeMailbox

    with Connection("memory://") as conn:
        mailbox = _ProbeMailbox("probe-test", connection=conn)
        with mailbox.producer_or_acquire(channel=conn.default_channel) as producer:
            assert producer.channel is conn.default_channel
            def broken_publish(*args, **kwargs):
                raise conn.recoverable_connection_errors[0]("lost")

            with (
                patch.object(producer, "_publish", broken_publish),
                patch.object(conn, "_ensure_connection") as reconnect,
                pytest.raises(OperationalError),
            ):
                producer.publish({"method": "ping"}, retry=True)
            reconnect.assert_not_called()


def test_system_health_reports_no_workers_as_degraded(admin_client, monkeypatch):
    from accounts import views_system

    monkeypatch.setattr(views_system, "_ping_workers", lambda app, conn: [])
    response = admin_client.get(URL)
    assert response.json()["celery"]["status"] == "degraded"
    assert response.json()["celery"]["workers_responding"] == 0
