"""Each of the eleven read-only tools works through the seam and asks Dolibarr only with GET."""
from __future__ import annotations

import json

import pytest

from conftest import VALID_TOKEN

ALL_TOOLS = {
    "whoami", "my_permissions", "list_thirdparties", "get_thirdparty", "list_invoices", "get_invoice",
    "list_proposals", "list_orders", "list_products", "list_api_endpoints", "api_get",
}


def _ok(response) -> str:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False, result
    return result["content"][0]["text"]


def test_exactly_the_eleven_read_only_tools_exist(client, dolibarr):
    assert client.tool_names() == ALL_TOOLS
    for name in ALL_TOOLS:
        assert not any(w in name for w in ("create", "update", "delete", "add", "set_", "post", "put", "write"))


def test_my_permissions_lists_rights_and_modules(client, dolibarr):
    out = json.loads(_ok(client.call_tool("my_permissions")))

    assert "facture.lire" in out["rights"]
    assert "restoauth" in out["active_modules"]


@pytest.mark.parametrize("tool, arguments, path, key", [
    ("list_thirdparties", {"search": "Acme"}, "/thirdparties", "thirdparties"),
    ("list_invoices", {"status": "unpaid", "thirdparty_id": 1}, "/invoices", "invoices"),
    ("list_proposals", {"thirdparty_id": 1}, "/proposals", "proposals"),
    ("list_orders", {}, "/orders", "orders"),
    ("list_products", {"search": "SRV"}, "/products", "products"),
])
def test_list_tools_return_rows_from_dolibarr(client, dolibarr, tool, arguments, path, key):
    out = json.loads(_ok(client.call_tool(tool, arguments)))

    assert out["count"] == 1
    assert out[key][0]["id"] == "1"
    assert [r.path for r in dolibarr.data_requests()] == [path]


def test_list_filters_reach_dolibarr(client, dolibarr):
    _ok(client.call_tool("list_invoices", {"status": "unpaid", "thirdparty_id": 7}))
    _ok(client.call_tool("list_thirdparties", {"search": "Acme", "customers_only": True}))

    invoices, thirdparties = dolibarr.data_requests()
    assert invoices.query_params["status"] == "unpaid"
    assert invoices.query_params["thirdparty_ids"] == "7"
    assert thirdparties.query_params["sqlfilters"] == "(t.nom:like:'%Acme%')"
    assert thirdparties.query_params["mode"] == "1"


def test_get_thirdparty_and_get_invoice_read_one_record(client, dolibarr):
    thirdparty = json.loads(_ok(client.call_tool("get_thirdparty", {"id": 1})))
    invoice = json.loads(_ok(client.call_tool("get_invoice", {"id": 1})))

    assert thirdparty["name"] == "Acme GmbH"
    assert invoice["ref"] == "FA2611-0001"
    assert invoice["lines"][0]["desc"] == "Service"
    assert [r.path for r in dolibarr.data_requests()] == ["/thirdparties/1", "/invoices/1"]


def test_unknown_record_says_not_found(client, dolibarr):
    assert _ok(client.call_tool("get_invoice", {"id": 999})) == "Not found or no permission."


def test_list_api_endpoints_and_api_get(client, dolibarr):
    endpoints = json.loads(_ok(client.call_tool("list_api_endpoints", {"filter": "thirdparties"})))
    data = json.loads(_ok(client.call_tool("api_get", {"path": "/thirdparties/1"})))

    assert "/thirdparties/{id}" in [p["path"] for p in endpoints["paths"]]
    assert all("thirdparties" in p["path"] for p in endpoints["paths"])
    assert data["name"] == "Acme GmbH"
    assert dolibarr.data_requests()[-1].path == "/thirdparties/1"


def test_every_request_carries_the_callers_token(client, dolibarr):
    for tool, arguments in [("list_orders", {}), ("get_thirdparty", {"id": 1}), ("api_get", {"path": "/status"})]:
        _ok(client.call_tool(tool, arguments))

    assert dolibarr.data_requests()
    assert {r.authorization for r in dolibarr.requests} == {f"Bearer {VALID_TOKEN}"}


def test_dolibarr_error_is_reported_as_text(client, dolibarr):
    dolibarr.fail_status = 500

    text = _ok(client.call_tool("list_orders"))

    assert text.startswith("Dolibarr HTTP 500")


def test_dolibarr_refusing_access_is_reported_as_no_permission(client, dolibarr):
    dolibarr.fail_status = 403

    assert _ok(client.call_tool("get_thirdparty", {"id": 1})) == "No permission in Dolibarr (HTTP 403)"
