"""TEST ONLY. Check group "rights": a user without the connect right is turned away; the MCP server's
tools run as two connected users with different rights. No LibreChat needed. Builds on the group
"oauth" (registered client, anna's connection). The checks find their data by name and do not count
products or documents, so a Dolibarr with more data than the sample data (TEST_EXTRA_DATA) passes too."""
import requests

import flows
from checklib import Group, state
from common import ANNA_API_KEY, KC_USERS
from groups.oauth import callback_error

group = Group(__name__, "Rights: a user without the connect right, and two connected users with different rights",
              order=20, needs=("oauth",))
check = group.check
anna, bob, carl, dave = KC_USERS
# Enough rows for a stack with some more data than the sample data (the MCP server caps lists at 50 by default).
ROWS = 50
SAMPLE_PRODUCTS = ["HW-ROUTER", "SRV-MAINT"]

ALL_TOOLS = sorted(["whoami", "my_permissions", "list_thirdparties", "get_thirdparty", "list_invoices", "get_invoice",
                    "list_proposals", "list_orders", "list_products", "list_api_endpoints", "api_get"])
# Tools that read invoices, proposals or orders: carl has none of those rights.
DOCUMENT_TOOLS = ["get_invoice", "list_invoices", "list_orders", "list_proposals"]
REFUSED = "No permission"


def thirdparties(token: str) -> dict[str, str]:
    """Name -> id of every third party the token's user sees."""
    rows = flows.call_json(token, "list_thirdparties", limit=ROWS)["thirdparties"]
    return {x["name"]: str(x["id"]) for x in rows}


def assert_sample_products(token: str) -> None:
    for ref in SAMPLE_PRODUCTS:
        found = [x["ref"] for x in flows.call_json(token, "list_products", search=ref)["products"]]
        assert ref in found, (ref, found)


@check("negative: a user without the connect right sees no Allow button on the consent page")
def _():
    con = flows.Connection(state["prm"], state["asm"], state["client_id"], bob[0], bob[1])
    _, ch = flows.pkce()
    r = con.consent_page(ch, "b")
    text = flows.page_text(r.text, 5000)
    form = flows.consent_form(r)
    values = [x.get("value") for x in form.find_all("button", attrs={"name": "restoauth_action"})]
    assert "(bob)" in text and "may not connect applications" in text and values == ["deny"], (values, text[:400])
    state["bob"], state["bob_page"] = con, r
    return "only Deny"


@check("negative: a user without the connect right gets access_denied even when posting allow")
def _():
    q = callback_error(flows.decide(state["bob"].b, state["bob_page"], "allow"))
    assert q.get("error") == "access_denied" and q.get("state") == "b", q
    return q.get("error_description")


@check("both connected users work as themselves")
def _():
    state["anna_tok"] = state["anna"].tokens()["access_token"]
    state["carl"] = flows.Connection(state["prm"], state["asm"], state["client_id"], carl[0], carl[1])
    state["carl_tok"] = state["carl"].tokens()["access_token"]
    a = flows.call_json(state["anna_tok"], "whoami")["user"]
    c = flows.call_json(state["carl_tok"], "whoami")["user"]
    assert (a, c) == ("Anna Agent (anna)", "Carl Sales (carl)"), (a, c)
    return f"{a}, {c}"


@check("the tool list differs: carl lacks the invoice, proposal and order tools")
def _():
    a = flows.tool_names(state["anna_tok"])
    c = flows.tool_names(state["carl_tok"])
    assert a == ALL_TOOLS, a
    assert c == sorted(set(ALL_TOOLS) - set(DOCUMENT_TOOLS)), c
    return f"anna {len(a)} tools, carl {len(c)}"


@check("anna reads her own customer's records only")
def _():
    t = state["anna_tok"]
    tps = thirdparties(t)
    assert "North Customer Ltd" in tps and "South Customer Inc" not in tps, tps
    north = tps["North Customer Ltd"]
    # Every document anna sees belongs to one of her customers, and North Customer Ltd has some.
    for tool, key in (("list_invoices", "invoices"), ("list_proposals", "proposals"), ("list_orders", "orders")):
        rows = flows.call_json(t, tool, limit=ROWS)[key]
        assert rows and {str(x["socid"]) for x in rows} <= set(tps.values()), (tool, rows)
        assert any(str(x["socid"]) == north for x in flows.call_json(t, tool, thirdparty_id=int(north))[key]), tool
    inv = flows.call_json(t, "list_invoices", thirdparty_id=int(north))["invoices"]
    assert inv and all(str(x["socid"]) == north for x in inv), inv
    one = flows.call_json(t, "get_invoice", id=int(inv[0]["id"]))
    assert one["ref"] == inv[0]["ref"] and one["lines"], one
    assert_sample_products(t)
    out = flows.call(t, "api_get", path=f"/thirdparties/{north}/outstandinginvoices")
    assert REFUSED not in out, out[:200]
    state["north"] = north
    return f"North Customer Ltd, invoice {inv[0]['ref']}"


@check("carl reads his own customer, and nothing of the invoices, proposals and orders")
def _():
    t = state["carl_tok"]
    tps = thirdparties(t)
    assert "South Customer Inc" in tps and "North Customer Ltd" not in tps, tps
    assert not set(tps) & set(thirdparties(state["anna_tok"])), "anna and carl see the same customer"
    south = tps["South Customer Inc"]
    assert flows.call_json(t, "get_thirdparty", id=int(south))["name"] == "South Customer Inc"
    assert_sample_products(t)
    for tool in DOCUMENT_TOOLS:
        out = flows.call(t, tool, **({"id": 1} if tool == "get_invoice" else {}))
        assert out.startswith(REFUSED), (tool, out[:200])
    state["south"] = south
    return "South Customer Inc; invoice, proposal and order tools refused"


@check("the generic API tools enforce the rights too (stricter than Dolibarr for outstanding invoices)")
def _():
    t = state["carl_tok"]
    for path in ("/invoices", "/orders", f"/thirdparties/{state['south']}/outstandinginvoices"):
        out = flows.call(t, "api_get", path=path)
        assert out.startswith(REFUSED), (path, out[:200])
    carl_paths = [p["path"] for p in flows.call_json(t, "list_api_endpoints")["paths"]]
    anna_paths = [p["path"] for p in flows.call_json(state["anna_tok"], "list_api_endpoints")["paths"]]
    doc = ("/invoices", "/proposals", "/orders")
    assert not [p for p in carl_paths if p.startswith(doc) or p.endswith("outstandinginvoices")], carl_paths
    assert "/thirdparties" in carl_paths and "/invoices" in anna_paths, (carl_paths[:20], anna_paths[:20])
    return f"anna {len(anna_paths)} readable paths, carl {len(carl_paths)}"


@check("users cannot read each other's customers, through the MCP server or straight at Dolibarr")
def _():
    out = flows.call(state["anna_tok"], "get_thirdparty", id=int(state["south"]))
    assert "South Customer Inc" not in out, out[:200]
    out = flows.call(state["carl_tok"], "get_thirdparty", id=int(state["north"]))
    assert "North Customer Ltd" not in out, out[:200]
    r = requests.get(f"{flows.API}/invoices", headers={"Authorization": f"Bearer {state['carl_tok']}"})
    assert r.status_code in (401, 403), f"Dolibarr gave carl the invoices: {r.status_code}"
    return f"Dolibarr answers carl's /invoices with {r.status_code}"


@check("anna's own Dolibarr API key works at Dolibarr's REST API, but the MCP server refuses it with 401")
def _():
    r = requests.get(f"{flows.API}/thirdparties", headers={"DOLAPIKEY": ANNA_API_KEY})
    names = [x["name"] for x in r.json()] if r.status_code == 200 else []
    assert "North Customer Ltd" in names and "South Customer Inc" not in names, \
        f"Dolibarr /thirdparties with anna's API key: {r.status_code} {r.text[:200]}"
    # What the MCP server sees: restoauth/me knows the key's user, but it is no restoauth token.
    me = flows.dolibarr_me(ANNA_API_KEY)
    assert me.status_code == 200 and me.json()["user"]["login"] == "anna" and me.json()["token"] is None, \
        f"restoauth/me {me.status_code} {me.text[:200]}"
    for method, params in (("tools/list", {}), ("tools/call", {"name": "whoami", "arguments": {}})):
        m = flows.mcp(ANNA_API_KEY, method, params)
        assert m.status_code == 401, f"MCP server {method} with anna's API key: {m.status_code} {m.text[:200]}"
        challenge = m.headers.get("www-authenticate", "")
        assert challenge.startswith("Bearer") and "resource_metadata=" in challenge, challenge
    return "Dolibarr 200, MCP server 401 with the resource metadata challenge"
