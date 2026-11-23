"""Rejected input never reaches Dolibarr; api_get only sends GET on known paths."""
from __future__ import annotations

import pytest


def _result(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _text(response) -> str:
    result = _result(response)
    assert result["isError"] is False, result
    return result["content"][0]["text"]


def _tool_requests(dolibarr) -> list[str]:
    """What tools asked Dolibarr for, apart from the token check and the endpoint list."""
    return [r.path for r in dolibarr.data_requests() if r.path != "/restoauth/endpoints"]


# --- IDs ------------------------------------------------------------------------------------

@pytest.mark.parametrize("tool", ["get_thirdparty", "get_invoice"])
@pytest.mark.parametrize("value", [0, -1, 2**31, 10**20])
def test_record_id_out_of_range_is_refused(client, dolibarr, tool, value):
    text = _text(client.call_tool(tool, {"id": value}))

    assert text.startswith("Invalid id")
    assert _tool_requests(dolibarr) == []


@pytest.mark.parametrize("tool", ["get_thirdparty", "get_invoice"])
@pytest.mark.parametrize("value", ["1/../../users", "1 OR 1=1", "abc", 1.5, None])
def test_record_id_that_is_not_a_number_is_refused(client, dolibarr, tool, value):
    result = _result(client.call_tool(tool, {"id": value}))

    assert result["isError"] is True
    assert _tool_requests(dolibarr) == []


@pytest.mark.parametrize("tool", ["list_invoices", "list_proposals", "list_orders"])
@pytest.mark.parametrize("value", [-1, 2**31])
def test_thirdparty_filter_out_of_range_is_refused(client, dolibarr, tool, value):
    text = _text(client.call_tool(tool, {"thirdparty_id": value}))

    assert text.startswith("Invalid thirdparty_id")
    assert _tool_requests(dolibarr) == []


@pytest.mark.parametrize("status", ["Paid", "open", "unpaid' OR '1'='1", "1"])
def test_unknown_invoice_status_is_refused(client, dolibarr, status):
    assert _text(client.call_tool("list_invoices", {"status": status})) == "Invalid status (draft, unpaid, paid, cancelled)"
    assert _tool_requests(dolibarr) == []


# --- search strings -------------------------------------------------------------------------

@pytest.mark.parametrize("tool", ["list_thirdparties", "list_products"])
@pytest.mark.parametrize("search, message", [
    ("x" * 101, "Invalid search: at most 100 characters."),
    ("Acme\x00", "Invalid search: control characters are not allowed."),
    ("Acme\nGmbH", "Invalid search: control characters are not allowed."),
])
def test_invalid_search_text_is_refused(client, dolibarr, tool, search, message):
    assert _text(client.call_tool(tool, {"search": search})) == message
    assert _tool_requests(dolibarr) == []


def test_filter_of_list_api_endpoints_is_checked_too(client, dolibarr):
    assert _text(client.call_tool("list_api_endpoints", {"filter": "x" * 101})).startswith("Invalid filter")


@pytest.mark.parametrize("search, expected", [
    ("x') or (1:=:1", "(t.nom:like:'%x or 11%')"),
    ("O'Brien", "(t.nom:like:'%OBrien%')"),
    ("a%b_c\\", "(t.nom:like:'%ab_c%')"),
    ("Müller & Söhne", "(t.nom:like:'%Müller  Söhne%')"),
    ("info@acme.de", "(t.nom:like:'%info@acme.de%')"),
])
def test_search_text_cannot_break_out_of_the_sql_filter(client, dolibarr, search, expected):
    _text(client.call_tool("list_thirdparties", {"search": search}))

    [request] = dolibarr.data_requests()
    assert request.query_params["sqlfilters"] == expected


# --- api_get --------------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "thirdparties",                       # not absolute
    "/thirdparties/../users",             # traversal
    "/thirdparties/1/..",
    "/thirdparties/./1",
    "/..",
    "/thirdparties//1",                   # empty segment
    "/thirdparties/",                     # trailing slash
    "/thirdparties?limit=1000",           # query string in the path
    "/thirdparties#x",
    "/thirdparties/%2e%2e/users",         # encoded traversal
    "/thirdparties\\..\\users",
    "/thirdparties/{id}",                 # placeholder not filled in
    "/thirdparties/1 2",
    "/" + "a" * 200,
    "",
])
def test_api_get_refuses_invalid_paths(client, dolibarr, path):
    assert _text(client.call_tool("api_get", {"path": path})).startswith("Invalid path")
    assert dolibarr.data_requests() == []


@pytest.mark.parametrize("path", ["/users", "/users/1", "/setup/company", "/thirdparties/1/delete", "/restoauth/me"])
def test_api_get_refuses_paths_restoauth_does_not_list(client, dolibarr, path):
    text = _text(client.call_tool("api_get", {"path": path}))

    assert text == "Path is not a readable Dolibarr REST path (see list_api_endpoints)."
    assert _tool_requests(dolibarr) == []


@pytest.mark.parametrize("query, message", [
    ({"DOLAPIKEY": "abc"}, "Query parameter DOLAPIKEY is not allowed."),
    ({"api_key": "abc"}, "Query parameter api_key is not allowed."),
    ({"Token": "abc"}, "Query parameter Token is not allowed."),
    ({"a-b": "1"}, "Invalid query parameter name: 'a-b'"),
    ({"1abc": "1"}, "Invalid query parameter name: '1abc'"),
    ({"sortfield": "x" * 501}, "Invalid value for query parameter sortfield."),
    ({"sortfield": "t.ref\r\nX: y"}, "Invalid value for query parameter sortfield."),
    ({"limit": "ten"}, "Invalid query parameter limit: must be a whole number."),
    ({"limit": "-5"}, "Invalid query parameter limit: must be a whole number."),
    ({f"p{i}": "1" for i in range(21)}, "Invalid query: at most 20 parameters."),
])
def test_api_get_refuses_invalid_query(client, dolibarr, query, message):
    assert _text(client.call_tool("api_get", {"path": "/thirdparties", "query": query})) == message
    assert dolibarr.data_requests() == []


def test_api_get_sends_a_valid_query_on(client, dolibarr):
    """Control case: the refusal tests above would pass vacuously if nothing ever reached Dolibarr."""
    _text(client.call_tool("api_get", {"path": "/thirdparties", "query": {"sortfield": "t.nom", "sortorder": "ASC"}}))

    [request] = [r for r in dolibarr.data_requests() if r.path == "/thirdparties"]
    assert request.query_params["sortfield"] == "t.nom"
    assert request.query_params["sortorder"] == "ASC"


def test_api_get_fills_placeholders_only_with_real_segments(client, dolibarr):
    _text(client.call_tool("api_get", {"path": "/thirdparties/1/outstandinginvoices"}))

    assert _tool_requests(dolibarr) == ["/thirdparties/1/outstandinginvoices"]


def test_valid_input_reaches_dolibarr(client, dolibarr):
    """Control case for IDs and search texts."""
    _text(client.call_tool("get_invoice", {"id": 1}))
    _text(client.call_tool("list_orders", {"thirdparty_id": 2147483647}))
    _text(client.call_tool("list_products", {"search": "x" * 100}))

    assert _tool_requests(dolibarr) == ["/invoices/1", "/orders", "/products"]
