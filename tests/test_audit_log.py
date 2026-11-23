"""Every tool call writes exactly one JSON line to the audit log, and no log or error ever contains the token
or another secret."""
from __future__ import annotations

import hashlib
import importlib
import logging

import anyio
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from conftest import VALID_TOKEN
from fake_dolibarr import User


def _result(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _ok(response) -> str:
    result = _result(response)
    assert result["isError"] is False, result
    return result["content"][0]["text"]


@pytest.mark.parametrize("tool, arguments", [
    ("whoami", {}),
    ("my_permissions", {}),
    ("list_thirdparties", {"search": "Acme", "limit": 5}),
    ("get_thirdparty", {"id": 1}),
    ("list_invoices", {"status": "paid"}),
    ("get_invoice", {"id": 1}),
    ("list_proposals", {"thirdparty_id": 1}),
    ("list_orders", {}),
    ("list_products", {"search": "SRV"}),
    ("list_api_endpoints", {"filter": "invoices"}),
    ("api_get", {"path": "/thirdparties/1/outstandinginvoices", "query": {"sortfield": "t.ref"}}),
])
def test_each_tool_call_appends_one_json_line(client, dolibarr, audit, tool, arguments):
    _ok(client.call_tool(tool, arguments))

    [entry] = audit.entries()
    assert entry["user"] == "max"
    assert entry["tool"] == tool
    assert entry["args"] == arguments
    assert entry["ok"] is True
    assert entry["info"] == ""
    assert entry["token"] == hashlib.sha256(VALID_TOKEN.encode()).hexdigest()[:12]
    assert entry["ts"]


@pytest.mark.parametrize("tool, arguments, info", [
    ("get_invoice", {"id": -1}, "refused: Invalid id"),
    ("list_invoices", {"status": "open"}, "refused: Invalid status"),
    ("list_products", {"search": "x" * 101}, "refused: Invalid search"),
    ("api_get", {"path": "/thirdparties/../users"}, "refused: Invalid path"),
    ("api_get", {"path": "/users"}, "refused: Path is not a readable Dolibarr REST path"),
    ("api_get", {"path": "/thirdparties", "query": {"DOLAPIKEY": "x"}}, "refused: Query parameter DOLAPIKEY"),
])
def test_refused_input_is_logged_with_ok_false(client, dolibarr, audit, tool, arguments, info):
    _ok(client.call_tool(tool, arguments))

    [entry] = audit.entries()
    assert entry["tool"] == tool
    assert entry["user"] == "max"
    assert entry["ok"] is False
    assert entry["info"].startswith(info)


def test_missing_right_is_logged_with_ok_false(client, dolibarr, audit):
    dolibarr.tokens[VALID_TOKEN] = User(rights=["societe.lire"])

    _ok(client.call_tool("api_get", {"path": "/thirdparties/1/outstandinginvoices"}))

    [entry] = audit.entries()
    assert entry["ok"] is False
    assert entry["info"] == "refused: No permission: your Dolibarr user has no rights for this."


def test_arguments_the_sdk_rejects_are_logged_too(client, dolibarr, audit):
    result = _result(client.call_tool("get_invoice", {"id": "abc"}))

    assert result["isError"] is True
    [entry] = audit.entries()
    assert entry["tool"] == "get_invoice"
    assert entry["args"] == {"id": "abc"}
    assert entry["user"] == "max"
    assert entry["ok"] is False


def test_unknown_tool_is_logged(client, dolibarr, audit):
    assert _result(client.call_tool("delete_invoice", {"id": 1}))["isError"] is True

    [entry] = audit.entries()
    assert entry["tool"] == "delete_invoice"
    assert entry["ok"] is False


def test_failed_dolibarr_call_is_logged_with_ok_false(client, dolibarr, audit):
    dolibarr.fail_status = 500
    dolibarr.fail_message = "Database error"

    _ok(client.call_tool("list_orders"))

    [entry] = audit.entries()
    assert entry["ok"] is False
    assert entry["info"] == "Dolibarr HTTP 500 Database error"


@pytest.fixture
def server(mcp_server):
    return importlib.import_module("dolibarr_mcp_server.server")


def test_cancelled_call_writes_exactly_one_line(server, dolibarr, audit, monkeypatch):
    """A cancelled call (e.g. the server shuts down) cannot be produced through the HTTP seam; call the
    tool in-process with the token in the request context, as the SDK's auth middleware sets it."""
    async def slow_get(*args, **kwargs):
        await anyio.sleep(5)

    monkeypatch.setattr(server, "_api_get", slow_get)

    async def run() -> bool:
        reset = auth_context_var.set(AuthenticatedUser(AccessToken(token=VALID_TOKEN, client_id="t", scopes=[])))
        try:
            with anyio.move_on_after(0.5) as scope:
                await server._audited_call_tool("list_orders", {})
            return scope.cancelled_caught
        finally:
            auth_context_var.reset(reset)

    assert anyio.run(run) is True
    [entry] = audit.entries()
    assert entry["tool"] == "list_orders"
    assert entry["user"] == "max"
    assert entry["ok"] is False
    assert entry["info"] == "cancelled"


def test_token_never_appears_in_audit_file_tool_answers_or_application_log(client, dolibarr, audit, caplog, capfd):
    caplog.set_level(logging.DEBUG)
    short = "short-token-42"  # too short for the long-string rule, redacted because it is the caller's token
    dolibarr.tokens[short] = User()
    answers = []

    # Normal calls, the token smuggled into arguments, refused calls and a rejected token.
    answers.append(_ok(client.call_tool("whoami")))
    answers.append(_ok(client.call_tool("list_thirdparties", {"search": VALID_TOKEN})))
    answers.append(_ok(client.call_tool("api_get", {"path": f"/thirdparties/{VALID_TOKEN}"})))
    answers.append(_ok(client.call_tool("api_get", {"path": "/thirdparties", "query": {"sortfield": VALID_TOKEN}})))
    answers.append(_ok(client.call_tool("list_products", {"search": short}, token=short)))
    rejected = "rejected-token-abcdefabcdefabcdefabcdefabcdef"
    assert client.call_tool("whoami", token=rejected).status_code == 401
    # Dolibarr echoes the token and a password in its error message.
    dolibarr.fail_status = 500
    dolibarr.fail_message = f"Bad request from Bearer {VALID_TOKEN} with password=hunter2 DOLAPIKEY=abc123"
    answers.append(_ok(client.call_tool("list_orders")))

    raw = audit.raw()
    assert len(audit.entries()) == 6
    texts = [raw, "\n".join(answers), "\n".join(r.getMessage() for r in caplog.records), *capfd.readouterr()]
    for text in texts:
        assert VALID_TOKEN not in text
        assert short not in text
        assert rejected not in text
        assert "hunter2" not in text
        assert "abc123" not in text
    assert caplog.records, "expected some application log output to inspect"
    assert answers[-1].startswith("Dolibarr HTTP 500 Bad request from Bearer ***")
