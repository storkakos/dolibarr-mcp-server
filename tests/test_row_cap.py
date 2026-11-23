"""Results are capped at MCP_MAX_ROWS: in what is asked from Dolibarr and in what comes back."""
from __future__ import annotations

import json

import pytest

from conftest import MAX_ROWS

LIST_TOOLS = ["list_thirdparties", "list_invoices", "list_proposals", "list_orders", "list_products"]


def _text(response) -> str:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False, result
    return result["content"][0]["text"]


def _limits(dolibarr) -> list[str]:
    return [r.query_params.get("limit") for r in dolibarr.data_requests() if r.path != "/restoauth/endpoints"]


@pytest.mark.parametrize("tool", LIST_TOOLS)
@pytest.mark.parametrize("requested", [MAX_ROWS + 1, 1000, 10**9])
def test_limit_above_max_rows_is_capped(client, dolibarr, tool, requested):
    _text(client.call_tool(tool, {"limit": requested}))

    assert _limits(dolibarr) == [str(MAX_ROWS)]


@pytest.mark.parametrize("tool", LIST_TOOLS)
def test_limit_within_max_rows_is_passed_through(client, dolibarr, tool):
    _text(client.call_tool(tool, {"limit": MAX_ROWS - 1}))

    assert _limits(dolibarr) == [str(MAX_ROWS - 1)]


@pytest.mark.parametrize("requested", [0, -5])
def test_limit_below_one_is_raised_to_one(client, dolibarr, requested):
    _text(client.call_tool("list_orders", {"limit": requested}))

    assert _limits(dolibarr) == ["1"]


@pytest.mark.parametrize("query, sent", [
    ({}, MAX_ROWS),
    ({"limit": "1000"}, MAX_ROWS),
    ({"limit": "3"}, 3),
    ({"limit": "0"}, 1),
])
def test_api_get_limit_is_capped(client, dolibarr, query, sent):
    _text(client.call_tool("api_get", {"path": "/thirdparties", "query": query}))

    assert _limits(dolibarr) == [str(sent)]


@pytest.mark.parametrize("tool, key", [("list_thirdparties", "thirdparties"), ("list_orders", "orders")])
def test_answer_longer_than_max_rows_is_cut_and_says_so(client, dolibarr, tool, key):
    # An endpoint that ignores the limit parameter must not flood the model.
    dolibarr.list_rows = MAX_ROWS * 4
    dolibarr.ignore_limit = True

    out = json.loads(_text(client.call_tool(tool, {"limit": 1000})))

    assert out["count"] == MAX_ROWS
    assert len(out[key]) == MAX_ROWS
    assert out["capped_at"] == MAX_ROWS


def test_answer_within_max_rows_is_not_marked_as_capped(client, dolibarr):
    dolibarr.list_rows = MAX_ROWS

    out = json.loads(_text(client.call_tool("list_orders", {"limit": 1000})))

    assert out["count"] == MAX_ROWS
    assert "capped_at" not in out


def test_api_get_answer_is_cut_too(client, dolibarr):
    dolibarr.list_rows = MAX_ROWS * 4
    dolibarr.ignore_limit = True

    text = _text(client.call_tool("api_get", {"path": "/thirdparties"}))

    rows_json, note = text.rsplit("\n(", 1)
    assert len(json.loads(rows_json)) == MAX_ROWS
    assert note.startswith(f"Only the first {MAX_ROWS} rows")
