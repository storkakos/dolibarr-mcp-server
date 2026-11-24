"""The MCP server accepts only restoauth access tokens. A user's plain Dolibarr API key sent as a bearer
token is refused with the usual 401 challenge, never used for a tool call, and the refusal is audited
without the key: restoauth/me answers for such a key too, but with "token": null."""
from __future__ import annotations

import hashlib
import logging
import re

import httpx
import pytest

from conftest import VALID_TOKEN
from fake_dolibarr import User
from test_config import _base, _me_calls, start_server  # noqa: F401  (start_server is a fixture)

API_KEY = "plainapikey0123456789abcdef0123456789abcdef"


@pytest.fixture
def api_key(dolibarr) -> str:
    """max (the owner of VALID_TOKEN) also has a plain Dolibarr API key."""
    dolibarr.api_keys[API_KEY] = User()
    return API_KEY


def _challenge_points_at_metadata(response) -> None:
    assert response.status_code == 401, response.text
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer")
    assert re.search(r'resource_metadata="https://[^"/]+/\.well-known/oauth-protected-resource/mcp"', challenge), challenge


@pytest.mark.parametrize("method, params", [
    ("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"}}),
    ("tools/list", {}),
    ("tools/call", {"name": "whoami", "arguments": {}}),
    ("tools/call", {"name": "api_get", "arguments": {"path": "/thirdparties"}}),
])
def test_plain_api_key_gets_401_with_the_challenge(client, dolibarr, api_key, method, params):
    r = client.post(method, params, token=api_key)

    _challenge_points_at_metadata(r)
    # Only the token check reached Dolibarr; no tool asked it for data.
    assert [req.path for req in dolibarr.requests] == ["/restoauth/me"]
    assert dolibarr.data_requests() == []


def test_refused_api_key_is_audited_without_the_key(client, dolibarr, audit, api_key, caplog, capfd):
    caplog.set_level(logging.DEBUG)

    assert client.call_tool("list_thirdparties", {"search": "Acme"}, token=api_key).status_code == 401

    [entry] = audit.entries()
    assert entry["user"] == "max"
    assert entry["token"] == hashlib.sha256(api_key.encode()).hexdigest()[:12]
    assert entry["tool"] is None
    assert entry["args"] == {}
    assert entry["ok"] is False
    assert entry["info"] == "refused: not a restoauth access token"
    assert entry["ts"]
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "not a restoauth access token" in logs
    for text in [audit.raw(), logs, *capfd.readouterr()]:
        assert api_key not in text


def test_api_key_is_not_cached_while_a_restoauth_token_is(start_server, dolibarr, api_key):
    # With the default rights cache (30 s) a restoauth token is checked once; the answer of restoauth/me
    # for an API key is never kept as a valid token, so each request asks again and is refused again.
    server = start_server(**_base(DOLIBARR_URL=dolibarr.base_url))

    for _ in range(2):
        assert server.call_tool("whoami", {}).status_code == 200
    assert _me_calls(dolibarr) == 1
    for _ in range(3):
        r = httpx.post(f"{server.base_url}/mcp", timeout=30,
                       json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "whoami", "arguments": {}}},
                       headers={"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {api_key}"})
        _challenge_points_at_metadata(r)
    assert _me_calls(dolibarr) == 4
    assert [req.authorization for req in dolibarr.data_requests()] == []


def test_restoauth_token_of_the_same_user_still_works(client, dolibarr, api_key):
    assert client.call_tool("whoami", token=api_key).status_code == 401

    r = client.call_tool("list_thirdparties")

    assert r.status_code == 200, r.text
    assert r.json()["result"]["isError"] is False
    assert all(req.authorization == f"Bearer {VALID_TOKEN}" for req in dolibarr.requests[1:])
    assert dolibarr.data_requests(), "the restoauth token reached Dolibarr's REST API"

