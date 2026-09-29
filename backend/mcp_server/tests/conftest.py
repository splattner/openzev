"""Fixtures shared by the ``mcp_server`` test modules."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from accounts.api_keys import generate_key
from accounts.models import ApiKey, FeatureFlag

MCP_URL = "/api/v1/mcp/"


@pytest.fixture(autouse=True)
def mcp_server_enabled(db):
    """The MCP endpoint is 404 while its flag is off; every test in this
    package exercises behaviour behind the flag, so it defaults on here.
    ``test_transport.py``'s own gate tests turn it off explicitly.
    """
    FeatureFlag.objects.update_or_create(
        name=FeatureFlag.MCP_SERVER_ENABLED, defaults={"enabled": True}
    )


def make_api_key(user, **overrides) -> tuple[ApiKey, str]:
    full_key, prefix, hashed = generate_key()
    defaults = {"name": "mcp test key", "prefix": prefix, "hashed_key": hashed}
    defaults.update(overrides)
    return ApiKey.objects.create(user=user, **defaults), full_key


def client_for(user, *, scheme: str = "Bearer", **key_overrides) -> APIClient:
    """An ``APIClient`` authenticated as ``user`` with a freshly minted API
    key, using the MCP endpoint's accepted ``Authorization`` scheme.
    """
    client = APIClient()
    _, raw_key = make_api_key(user, **key_overrides)
    client.credentials(HTTP_AUTHORIZATION=f"{scheme} {raw_key}")
    return client


@pytest.fixture
def admin_mcp_client(db, admin_user):
    return client_for(admin_user)


@pytest.fixture
def owner_mcp_client(db, owner_user):
    return client_for(owner_user)


def rpc(client, method, params=None, *, id=1):
    body = {"jsonrpc": "2.0", "method": method}
    if id is not None:
        body["id"] = id
    if params is not None:
        body["params"] = params
    return client.post(MCP_URL, body, format="json")


def call_tool(client, name, arguments=None, *, id=1):
    return rpc(client, "tools/call", {"name": name, "arguments": arguments or {}}, id=id)
