"""Shared fixtures for the supplementary-data API tests (not collected by pytest)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone

from cryptography.fernet import Fernet
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import FeatureFlag, UserRole
from testing import factories
from testing.helpers import authenticate, make_user
from zev.models import MeteringPointType, ZevAccessGrant, ZevAccessRole

INTEGRATION_KEY = Fernet.generate_key().decode()
SOURCES_URL = "/api/v1/metering/supplementary/sources/"
INGEST_URL = "/api/v1/metering/supplementary/ingest/"


def enable_feature(enabled: bool = True) -> None:
    FeatureFlag.objects.update_or_create(
        name=FeatureFlag.SUPPLEMENTARY_ENERGY_DATA_ENABLED, defaults={"enabled": enabled}
    )


def client_for(user) -> APIClient:
    client = APIClient()
    if user is not None:
        authenticate(client, user)
    return client


def quarter_hours(count: int, *, end: datetime | None = None, step_back: int = 0):
    """``count`` aligned 15-minute interval starts, the last one a few hours in the past."""
    end = (end or datetime.now(dt_timezone.utc)).replace(second=0, microsecond=0, minute=0) - timedelta(hours=3)
    start = end - timedelta(minutes=15 * (count + step_back))
    return [start + timedelta(minutes=15 * i) for i in range(count)]


def reading_payload(ts: datetime, **overrides) -> dict:
    row = {
        "timestamp": ts.isoformat(),
        "consumption_kwh": "0.4",
        "production_kwh": "1.2",
        "import_kwh": "0.1",
        "export_kwh": "0.9",
    }
    row.update(overrides)
    return row


class SupplementaryApiTestCase(TestCase):
    """A ZEV with a manager, a viewer, a participant holding a flagged meter, and a stranger."""

    def setUp(self):
        enable_feature()
        self.admin = make_user("sup_admin", UserRole.ADMIN)
        self.manager = make_user("sup_manager", UserRole.USER)
        self.viewer = make_user("sup_viewer", UserRole.USER)
        self.holder_user = make_user("sup_holder", UserRole.USER)
        self.other_user = make_user("sup_other", UserRole.USER)
        self.stranger = make_user("sup_stranger", UserRole.USER)

        self.zev = factories.ZevFactory(owner=self.manager)
        ZevAccessGrant.objects.create(zev=self.zev, user=self.viewer, role=ZevAccessRole.VIEWER)

        self.holder = factories.ParticipantFactory(zev=self.zev, user=self.holder_user, valid_from=date(2025, 1, 1))
        self.other = factories.ParticipantFactory(zev=self.zev, user=self.other_user, valid_from=date(2025, 1, 1))
        self.point = factories.MeteringPointFactory(
            zev=self.zev, meter_type=MeteringPointType.BIDIRECTIONAL, has_behind_meter_generation=True
        )
        self.assignment = factories.MeteringPointAssignmentFactory(
            metering_point=self.point, participant=self.holder, valid_from=date(2025, 1, 1)
        )

    def create_push_source(self, *, as_user=None, point=None, **extra):
        payload = {
            "metering_point": str((point or self.point).pk),
            "provider": "push",
            "label": "Home Assistant",
            "consent": True,
            **extra,
        }
        return client_for(as_user or self.holder_user).post(SOURCES_URL, payload, format="json")


# ---- a stand-in for the Solar Manager cloud -----------------------------------------------------

import json  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402


def vendor_row(stamp: datetime) -> dict:
    """The vendor's row for the interval starting at ``stamp``: a deterministic synthetic profile in Wh."""
    n = int(stamp.timestamp() // 900)
    return {
        "t": stamp.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "cWh": 100 + n % 7, "pWh": 300 + n % 11, "iWh": 20 + n % 5, "eWh": 200 + n % 3,
        # Derived and power fields the client must ignore.
        "cPvWh": 999, "scWh": 999, "bcWh": 0, "bdWh": 0, "soc": 0, "cW": 1, "pW": 1,
    }


class StubSolarManager:
    """A local HTTP server that behaves like the parts of ``cloud.solar-manager.ch`` OpenZEV uses.

    Refresh tokens rotate: only the current one is accepted, and each exchange issues the next.
    Set ``range_response`` to a callable ``(request_number) -> (status, headers, body_bytes) | None``
    to misbehave on a range request; ``None`` answers normally.
    """

    def __init__(self, token: str = "key-1"):
        self.current_token = token
        self.rotate = True
        self.exchanges = 0
        self.refresh_status = None
        self.range_response = None
        self.extra_rows = lambda start, end: []
        self.refresh_requests: list[dict] = []
        self.range_requests: list[dict] = []
        self.access_tokens: set[str] = set()
        self._server = None

    # lifecycle

    def start(self):
        vendor = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body=b"", headers=None):
                self.send_response(status)
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status, payload):
                self._send(status, json.dumps(payload).encode(), {"Content-Type": "application/json"})

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                vendor.refresh_requests.append(body)
                if vendor.refresh_status:
                    return self._json(vendor.refresh_status, {"message": "nope"})
                if body.get("grant_type") != "refresh_token" or body.get("refresh_token") != vendor.current_token:
                    return self._json(401, {"message": "invalid refresh token"})
                vendor.exchanges += 1
                access = f"access-{vendor.exchanges}"
                vendor.access_tokens.add(access)
                payload = {"access_token": access, "expires_in": 3600, "token_type": "Bearer"}
                if vendor.rotate:
                    vendor.current_token = f"key-{vendor.exchanges + 1}"
                    payload["refresh_token"] = vendor.current_token
                self._json(200, payload)

            def do_GET(self):  # noqa: N802
                url = urlparse(self.path)
                query = {key: values[0] for key, values in parse_qs(url.query).items()}
                bearer = self.headers.get("Authorization", "").removeprefix("Bearer ")
                vendor.range_requests.append({"path": url.path, "query": query, "bearer": bearer})
                number = len(vendor.range_requests)
                if bearer not in vendor.access_tokens:
                    return self._json(401, {"message": "unauthorized"})
                if vendor.range_response:
                    custom = vendor.range_response(number)
                    if custom is not None:
                        status, headers, body = custom
                        return self._send(status, body, headers)
                start = datetime.fromisoformat(query["from"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(query["to"].replace("Z", "+00:00"))
                rows, stamp = [], start
                while stamp <= end:  # the vendor includes the boundary; the client must not keep it
                    rows.append(vendor_row(stamp))
                    stamp += timedelta(minutes=15)
                rows.extend(vendor.extra_rows(start, end))
                self._json(200, {"data": rows, "interval": 900})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"
