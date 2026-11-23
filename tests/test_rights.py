"""The caller's rights are checked before Dolibarr is asked, including the stricter exceptions."""
from __future__ import annotations

import json

import pytest

from conftest import VALID_TOKEN
from fake_dolibarr import User

NO_PERMISSION = "No permission: your Dolibarr user has no rights for this."
OUTSTANDING = "/thirdparties/1/outstandinginvoices"


def _ok(response) -> str:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False, result
    return result["content"][0]["text"]


@pytest.mark.parametrize("tool, arguments, missing", [
    ("list_thirdparties", {}, "societe.lire"),
    ("get_thirdparty", {"id": 1}, "societe.lire"),
    ("list_invoices", {}, "facture.lire"),
    ("get_invoice", {"id": 1}, "facture.lire"),
    ("list_proposals", {}, "propal.lire"),
    ("list_orders", {}, "commande.lire"),
    ("list_products", {}, "produit.lire"),
    ("api_get", {"path": "/invoices/1"}, "facture.lire"),
])
def test_call_without_the_right_is_refused_before_dolibarr(client, dolibarr, tool, arguments, missing):
    rights = [r for r in User().rights if r != missing]
    dolibarr.tokens[VALID_TOKEN] = User(rights=rights)

    assert _ok(client.call_tool(tool, arguments)) == NO_PERMISSION
    assert [r.path for r in dolibarr.data_requests() if r.path != "/restoauth/endpoints"] == []


def test_wildcard_rights_rule_is_honoured(client, dolibarr):
    # The default rule accepts <module>.*.lire too (e.g. a module whose read right sits one level deeper).
    dolibarr.tokens[VALID_TOKEN] = User(rights=["produit.service.lire"])

    out = json.loads(_ok(client.call_tool("list_products")))

    assert out["count"] == 1


def test_outstanding_invoices_need_the_invoice_read_right_too(client, dolibarr):
    # Dolibarr 23.0.3 itself checks only societe.lire here, but the answer shows invoice amounts.
    dolibarr.tokens[VALID_TOKEN] = User(rights=["societe.lire"])

    assert _ok(client.call_tool("api_get", {"path": OUTSTANDING})) == NO_PERMISSION
    assert OUTSTANDING not in [r.path for r in dolibarr.requests]


def test_outstanding_invoices_with_both_rights_work(client, dolibarr):
    dolibarr.tokens[VALID_TOKEN] = User(rights=["societe.lire", "facture.lire"])

    rows = json.loads(_ok(client.call_tool("api_get", {"path": OUTSTANDING})))

    assert rows[0]["remaintopay"] == "119.00"


def test_stricter_rule_holds_even_if_restoauth_does_not_deliver_it(client, dolibarr):
    # An older or edited rights map without the exception must not make the server laxer.
    dolibarr.rights_rules["paths"] = {}
    dolibarr.tokens[VALID_TOKEN] = User(rights=["societe.lire"])

    assert _ok(client.call_tool("api_get", {"path": OUTSTANDING})) == NO_PERMISSION
    assert OUTSTANDING not in [r.path for r in dolibarr.requests]


@pytest.mark.parametrize("path", ["/thirdparties/1/OutstandingInvoices", "/THIRDPARTIES/1/outstandinginvoices"])
def test_stricter_rule_ignores_case(client, dolibarr, path):
    dolibarr.tokens[VALID_TOKEN] = User(rights=["societe.lire"])

    assert _ok(client.call_tool("api_get", {"path": path})) == NO_PERMISSION
    assert all(r.path.lower() != OUTSTANDING for r in dolibarr.requests)


def test_list_api_endpoints_hides_paths_without_rights(client, dolibarr):
    dolibarr.tokens[VALID_TOKEN] = User(rights=["societe.lire"])

    paths = [p["path"] for p in json.loads(_ok(client.call_tool("list_api_endpoints")))["paths"]]

    assert "/thirdparties" in paths
    assert "/thirdparties/{id}/outstandinginvoices" not in paths
    assert "/invoices" not in paths
    assert "/status" in paths  # needs no particular right


def test_rights_are_those_of_the_caller(client, dolibarr):
    other = "other-token-0123456789abcdef0123456789abcdef"
    dolibarr.tokens[other] = User(login="erika", rights=["produit.lire"])

    assert _ok(client.call_tool("list_invoices", token=other)) == NO_PERMISSION
    assert json.loads(_ok(client.call_tool("list_invoices")))["count"] == 1
