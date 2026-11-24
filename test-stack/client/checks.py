"""TEST ONLY. End to end: an MCP client connects through restoauth (Keycloak login, consent, PKCE),
refreshes, gets caught reusing a refresh token, revokes; then the MCP server's tools run as two
connected users with different rights, and a user without the connect right is turned away. Then the
three ways a connection ends: the user is disabled, the user ends it on their user card, the access
token expires (the stack sets a short access token lifetime).
Finally the example setup (docs/setup/example-keycloak-librechat.md): LibreChat users log in through
Keycloak, connect the dolibarr server through restoauth's consent page and ask whoami in a chat (the
chat checks need an LLM key in llm.env and are skipped without it).
Reports each check as PASS, FAIL or SKIP; exit code 1 if any check failed.

    docker compose run --rm client            # python checks.py; -v adds the traceback of a failure

Later checks use what earlier ones set up (tokens, record ids); after a failure they fail too.
"""
import os
import sys
import time
import traceback

import requests

import flows
from common import ISSUER, KC_USERS, MCP

results = []
state: dict = {}
anna, bob, carl, dave = KC_USERS
# The MCP server keeps a token's rights for MCP_RIGHTS_CACHE_SECONDS (default 30); a revoked token is
# refused by Dolibarr at once and by the MCP server at the latest after that.
CACHE_WAIT = int(os.environ.get("MCP_RIGHTS_CACHE_SECONDS", "30")) + 15

ALL_TOOLS = sorted(["whoami", "my_permissions", "list_thirdparties", "get_thirdparty", "list_invoices", "get_invoice",
                    "list_proposals", "list_orders", "list_products", "list_api_endpoints", "api_get"])
# Tools that read invoices, proposals or orders: carl has none of those rights.
DOCUMENT_TOOLS = ["get_invoice", "list_invoices", "list_orders", "list_proposals"]
REFUSED = "No permission"


def check(name):
    def deco(fn):
        try:
            detail = fn()
            if isinstance(detail, str) and detail.startswith("SKIP"):
                results.append(("SKIP", name, detail[5:]))
            else:
                results.append(("PASS", name, detail or ""))
        except Exception as e:  # noqa: BLE001
            results.append(("FAIL", name, f"{type(e).__name__}: {e}"))
            if "-v" in sys.argv:
                traceback.print_exc()
        status, _, detail = results[-1]
        print(f"{status}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
        return fn
    return deco


def callback_error(r) -> dict:
    assert isinstance(r, str), f"no redirect back to the client: {r.status_code} {r.url}"
    q = flows.callback_query(r)
    assert "code" not in q, "a code was issued"
    return q


print("== OAuth flow: discovery, registration, authorize, Keycloak login, consent, token, refresh, revoke")


@check("discovery: 401 challenge -> protected resource metadata -> authorization server metadata")
def _():
    prm, asm = flows.discover()
    assert prm["resource"].rstrip("/") == MCP and [s.rstrip("/") for s in prm["authorization_servers"]] == [ISSUER], prm
    assert asm["issuer"].rstrip("/") == ISSUER, asm["issuer"]
    for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"):
        assert asm.get(k, "").startswith(ISSUER + "/"), k
    assert asm.get("code_challenge_methods_supported") == ["S256"], asm.get("code_challenge_methods_supported")
    state.update(prm=prm, asm=asm)


@check("dynamic registration (RFC 7591) with the allowlisted redirect URI")
def _():
    r = flows.register(state["asm"], [flows.CALLBACK])
    assert r.status_code == 201, f"{r.status_code} {r.text[:200]}"
    state["client_id"] = r.json()["client_id"]
    return f"client_id {state['client_id'][:8]}..."


@check("negative: registration with a redirect URI not on the allowlist is refused")
def _():
    r = flows.register(state["asm"], ["https://evil.example.org/callback"], "evil client")
    assert r.status_code == 400 and r.json().get("error") == "invalid_redirect_uri", f"{r.status_code} {r.text[:200]}"
    return r.json()["error"]


@check("negative: authorize with a redirect URI not registered for the client is refused, no redirect")
def _():
    _, ch = flows.pkce()
    r = flows.authorize(flows.browser(), state["asm"], flows.auth_params(
        state["prm"], state["client_id"], ch, "s", redirect_uri="https://evil.example.org/callback"))
    assert not isinstance(r, str) and r.status_code == 400 and "location" not in r.headers, r
    return r.text[:80]


@check("negative: authorize without PKCE, or with method plain, is refused")
def _():
    b = flows.browser()
    q = callback_error(flows.authorize(b, state["asm"], flows.auth_params(state["prm"], state["client_id"], None, "s1")))
    assert q.get("error") == "invalid_request" and q.get("state") == "s1", q
    q = callback_error(flows.authorize(b, state["asm"], flows.auth_params(
        state["prm"], state["client_id"], flows.pkce()[0][:43], "s2", code_challenge_method="plain")))
    assert q.get("error") == "invalid_request", q
    return q.get("error_description")


@check("negative: authorize for a resource that is not allowed (RFC 8707) is refused")
def _():
    _, ch = flows.pkce()
    q = callback_error(flows.authorize(flows.browser(), state["asm"], flows.auth_params(
        state["prm"], state["client_id"], ch, "s3", resource="https://evil.example.org/mcp")))
    assert q.get("error") == "invalid_target", q
    return q.get("error_description")


@check("authorize -> Dolibarr login through Keycloak -> consent page lists the user's rights")
def _():
    con = flows.Connection(state["prm"], state["asm"], state["client_id"], anna[0], anna[1])
    _, ch = flows.pkce()
    r = con.consent_page(ch, "x")
    assert con.seen == ["dolibarr login page", "keycloak login", "dolibarr openid_connect callback"], con.seen
    text = flows.page_text(r.text, 5000)
    assert "test-stack MCP client" in text and "(anna)" in text, text[:400]
    rights = text[text.find("These are:") + len("These are:"):text.find("You can end the connection")]
    assert "may not connect" not in text and "Read customer invoices" in rights and "Read third parties" in rights \
        and "Connect applications" in rights, rights[:600]
    state["anna"] = con
    return rights.strip()[:140] + "..."


@check("token: a wrong or missing PKCE verifier is refused")
def _():
    con = state["anna"]
    code, _ = con.code()
    t = flows.token(state["asm"], grant_type="authorization_code", code=code, redirect_uri=flows.CALLBACK,
                    client_id=state["client_id"], code_verifier=flows.pkce()[0])
    assert t.status_code == 400 and t.json().get("error") == "invalid_grant", f"{t.status_code} {t.text[:200]}"
    code, _ = con.code()
    t = flows.token(state["asm"], grant_type="authorization_code", code=code, redirect_uri=flows.CALLBACK,
                    client_id=state["client_id"])
    assert t.status_code == 400 and t.json().get("error") == "invalid_request", f"{t.status_code} {t.text[:200]}"
    return "invalid_grant, invalid_request"


@check("token with PKCE: consent, code, token; the code works only once")
def _():
    con = state["anna"]
    code, verifier = con.code()
    data = dict(grant_type="authorization_code", code=code, redirect_uri=flows.CALLBACK,
                client_id=state["client_id"], code_verifier=verifier, resource=state["prm"]["resource"])
    t = flows.token(state["asm"], **data)
    assert t.status_code == 200, f"{t.status_code} {t.text[:200]}"
    tok = t.json()
    assert tok.get("token_type", "").lower() == "bearer" and tok.get("access_token") and tok.get("refresh_token"), tok.keys()
    again = flows.token(state["asm"], **data)
    assert again.status_code == 400 and again.json().get("error") == "invalid_grant", again.text[:200]
    assert len(con.seen) == 3, f"logged in again although the Dolibarr session exists: {con.seen}"
    state["tok1"] = tok
    return f"expires_in {tok.get('expires_in')}, no new login for later authorizations"


@check("the token works at the MCP server (whoami) and at the Dolibarr REST API")
def _():
    who = flows.call_json(state["tok1"]["access_token"], "whoami")
    assert who["user"] == "Anna Agent (anna)" and who["admin"] is False, who
    assert flows.dolibarr_me(state["tok1"]["access_token"]).status_code == 200
    return who["user"]


@check("refresh with rotation: new tokens, the old access token is dead, the new one works")
def _():
    old = state["tok1"]
    t = flows.token(state["asm"], grant_type="refresh_token", refresh_token=old["refresh_token"],
                    client_id=state["client_id"])
    assert t.status_code == 200, f"{t.status_code} {t.text[:200]}"
    new = t.json()
    assert new["refresh_token"] != old["refresh_token"] and new["access_token"] != old["access_token"]
    assert flows.dolibarr_me(old["access_token"]).status_code == 401, "old access token still valid at Dolibarr"
    assert flows.call_json(new["access_token"], "whoami")["user"] == "Anna Agent (anna)"
    state["tok2"] = new


@check("refresh token reuse: refused and the whole connection is revoked")
def _():
    old, new = state["tok1"], state["tok2"]
    r = flows.token(state["asm"], grant_type="refresh_token", refresh_token=old["refresh_token"],
                    client_id=state["client_id"])
    assert r.status_code == 400 and "reuse" in r.json().get("error_description", ""), f"{r.status_code} {r.text[:200]}"
    r = flows.token(state["asm"], grant_type="refresh_token", refresh_token=new["refresh_token"],
                    client_id=state["client_id"])
    assert r.status_code == 400, f"the newest refresh token still works: {r.status_code}"
    assert flows.dolibarr_me(new["access_token"]).status_code == 401, "access token still valid at Dolibarr"
    took = flows.wait_for_mcp_401(new["access_token"], CACHE_WAIT)
    return f"Dolibarr 401 at once, MCP server 401 after {took} s"


@check("revoke (RFC 7009): a new connection, revoked by its refresh token")
def _():
    tok = state["anna"].tokens()
    assert flows.call_json(tok["access_token"], "whoami")["user"] == "Anna Agent (anna)"
    r = requests.post(state["asm"]["revocation_endpoint"], data={"token": tok["refresh_token"],
                                                                 "client_id": state["client_id"]})
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    assert flows.dolibarr_me(tok["access_token"]).status_code == 401, "access token still valid at Dolibarr"
    r = flows.token(state["asm"], grant_type="refresh_token", refresh_token=tok["refresh_token"],
                    client_id=state["client_id"])
    assert r.status_code == 400, f"refresh after revoke: {r.status_code}"
    took = flows.wait_for_mcp_401(tok["access_token"], CACHE_WAIT)
    return f"Dolibarr 401 at once, MCP server 401 after {took} s"


print("== Rights: a user without the connect right, and two connected users with different rights")


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
    tps = flows.call_json(t, "list_thirdparties")["thirdparties"]
    assert [x["name"] for x in tps] == ["North Customer Ltd"], tps
    north = tps[0]["id"]
    inv = flows.call_json(t, "list_invoices")["invoices"]
    assert len(inv) == 1 and str(inv[0]["socid"]) == str(north), inv
    one = flows.call_json(t, "get_invoice", id=int(inv[0]["id"]))
    assert one["ref"] == inv[0]["ref"] and one["lines"], one
    for tool, key in (("list_proposals", "proposals"), ("list_orders", "orders")):
        rows = flows.call_json(t, tool)[key]
        assert len(rows) == 1 and str(rows[0]["socid"]) == str(north), (tool, rows)
    prods = sorted(x["ref"] for x in flows.call_json(t, "list_products")["products"])
    assert prods == ["HW-ROUTER", "SRV-MAINT"], prods
    out = flows.call(t, "api_get", path=f"/thirdparties/{north}/outstandinginvoices")
    assert REFUSED not in out, out[:200]
    state["north"] = north
    return f"North Customer Ltd, invoice {inv[0]['ref']}"


@check("carl reads his own customer, and nothing of the invoices, proposals and orders")
def _():
    t = state["carl_tok"]
    tps = flows.call_json(t, "list_thirdparties")["thirdparties"]
    assert [x["name"] for x in tps] == ["South Customer Inc"], tps
    south = tps[0]["id"]
    assert flows.call_json(t, "get_thirdparty", id=int(south))["name"] == "South Customer Inc"
    assert len(flows.call_json(t, "list_products")["products"]) == 2
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


print("== How a connection ends: user disabled, connection ended on the user card, access token expired")


def connection_of(access_token: str) -> tuple[int, str]:
    """(Dolibarr user id, connection id) of a token, from restoauth/me."""
    me = flows.dolibarr_me(access_token)
    assert me.status_code == 200, f"restoauth/me {me.status_code}"
    return int(me.json()["user"]["id"]), me.json()["token"]["connection"]


def refresh(tok: dict) -> requests.Response:
    return flows.token(state["asm"], grant_type="refresh_token", refresh_token=tok["refresh_token"],
                       client_id=state["client_id"])


def assert_refresh_refused(tok: dict) -> None:
    r = refresh(tok)
    assert r.status_code == 400 and r.json().get("error") == "invalid_grant", f"refresh: {r.status_code} {r.text[:200]}"


def before_expiry(tok: dict, issued: float, what: str) -> None:
    """A refusal only proves something while the access token has not expired by itself."""
    assert time.time() < issued + int(tok["expires_in"]), f"{what} only after the access token expired by itself"


@check("expiry: a new connection gets a short-lived access token (stack setting) that works")
def _():
    tok = state["anna"].tokens()
    state["exp"], state["exp_issued"] = tok, time.time()
    assert int(tok["expires_in"]) <= 120, f"expires_in {tok['expires_in']}: the stack's short lifetime is not set"
    assert flows.call_json(tok["access_token"], "whoami")["user"] == "Anna Agent (anna)"
    assert flows.dolibarr_me(tok["access_token"]).status_code == 200
    return f"expires_in {tok['expires_in']} s; checked again after the next checks"


@check("disabled user: every connection ends at once (gone from the user card, access token 401, refresh invalid_grant)")
def _():
    admin = flows.DolibarrAdmin()
    dave_id = admin.user_id(dave[0])
    if flows.user_status(admin.user_card(dave_id).text) != "Enabled":
        admin.set_enabled(dave_id, True)  # left disabled by an interrupted earlier run
    con = flows.Connection(state["prm"], state["asm"], state["client_id"], dave[0], dave[1])
    used, untouched = con.tokens(), con.tokens()
    issued = time.time()
    assert flows.call_json(used["access_token"], "whoami")["user"] == "Dave Leaver (dave)"
    uid, used_conn = connection_of(used["access_token"])
    _, untouched_conn = connection_of(untouched["access_token"])
    assert uid == dave_id, (uid, dave_id)
    _, links = flows.connected_apps(admin.b, dave_id)
    assert {used_conn, untouched_conn} <= set(links), f"connections not listed before: {sorted(links)}"
    state.update(admin=admin, dave_id=dave_id, dave_used=used, dave_untouched=untouched, dave_issued=issued)

    admin.set_enabled(dave_id, False)
    # Before any of the tokens is used again: restoauth has already ended both connections.
    _, links = flows.connected_apps(admin.b, dave_id)
    assert not links, f"connections still listed for the disabled user: {sorted(links)}"
    assert flows.dolibarr_me(used["access_token"]).status_code == 401, "access token still valid at Dolibarr"
    assert_refresh_refused(used)
    before_expiry(used, issued, "refused")
    return "no connection on the user card, Dolibarr 401, refresh invalid_grant"


@check("disabled user: enabling the user again does not revive the old tokens")
def _():
    admin, dave_id = state["admin"], state["dave_id"]
    admin.set_enabled(dave_id, True)
    for name in ("dave_used", "dave_untouched"):
        assert flows.dolibarr_me(state[name]["access_token"]).status_code == 401, f"{name}: access token works again"
    assert_refresh_refused(state["dave_untouched"])
    before_expiry(state["dave_untouched"], state["dave_issued"], "refused")
    _, links = flows.connected_apps(admin.b, dave_id)
    assert not links, f"connections listed again after enabling: {sorted(links)}"
    return "both connections stay dead, also the one not used while disabled"


@check("disabled user: the MCP server refuses the token after its rights cache")
def _():
    took = flows.wait_for_mcp_401(state["dave_used"]["access_token"], CACHE_WAIT)
    before_expiry(state["dave_used"], state["dave_issued"], "the MCP server refused")
    return f"MCP server 401 after {took} s"


@check("disabled user: once enabled again, the user can connect anew")
def _():
    con = flows.Connection(state["prm"], state["asm"], state["client_id"], dave[0], dave[1])
    tok = con.tokens()
    assert flows.call_json(tok["access_token"], "whoami")["user"] == "Dave Leaver (dave)"
    return "new connection works"


@check("user card: ending a connection removes it from the list, its tokens are refused")
def _():
    con = state["anna"]
    tok = con.tokens()
    issued = time.time()
    assert flows.call_json(tok["access_token"], "whoami")["user"] == "Anna Agent (anna)"
    uid, conn = connection_of(tok["access_token"])
    _, links = flows.connected_apps(con.b, uid)
    assert conn in links, f"connection not on anna's user card: {sorted(links)}"
    r = con.b.get(links[conn])
    assert r.status_code == 200, f"revoke {r.status_code}"
    _, links = flows.connected_apps(con.b, uid)
    assert conn not in links, "the connection is still listed"
    assert flows.dolibarr_me(tok["access_token"]).status_code == 401, "access token still valid at Dolibarr"
    assert_refresh_refused(tok)
    took = flows.wait_for_mcp_401(tok["access_token"], CACHE_WAIT)
    before_expiry(tok, issued, "the MCP server refused")
    return f"gone from the list, Dolibarr 401 at once, refresh invalid_grant, MCP server 401 after {took} s"


@check("expiry: the expired access token is refused at Dolibarr and the MCP server; refresh gives a working one")
def _():
    tok = state["exp"]
    wait = state["exp_issued"] + int(tok["expires_in"]) + 2 - time.time()
    if wait > 0:
        time.sleep(wait)
    assert flows.dolibarr_me(tok["access_token"]).status_code == 401, "expired access token still valid at Dolibarr"
    flows.wait_for_mcp_401(tok["access_token"], 5)
    r = refresh(tok)
    assert r.status_code == 200, f"refresh {r.status_code} {r.text[:200]}"
    new = r.json()["access_token"]
    assert flows.dolibarr_me(new).status_code == 200
    assert flows.call_json(new, "whoami")["user"] == "Anna Agent (anna)"
    return f"waited {max(0, int(wait))} s more; Dolibarr and MCP server 401, the refreshed token works at both"


print("== Example setup: LibreChat (docs/setup/example-keycloak-librechat.md)")
chats: dict = {}


def _librechat(user):
    lc = flows.LibreChat(user[0], user[1])
    me = lc.login()
    assert me.get("email") == user[4], me
    chats[user[0]] = lc
    return f"{me.get('name')} <{me.get('email')}>, PKCE {lc.pkce}"


def _connect(user):
    s = chats[user[0]].connect_dolibarr()
    if s["consent"]:
        text = s["consent"]
        assert "LibreChat MCP Client" in text and f"({user[0]})" in text and "may not connect" not in text, text[:400]
        assert "keycloak login" not in s["seen"], f"Keycloak asked for the password again: {s['seen']}"
    return "connected" + (f" after consent, pages {s['seen']}" if s["consent"] else " (already authorized earlier)")


@check("example 5: a Keycloak user logs into LibreChat")
def _():
    return _librechat(anna)


@check("example 6: connecting the dolibarr server opens restoauth's consent page")
def _():
    return _connect(anna)


@check("example option: Dolibarr assistant preselected for new chats")
def _():
    specs = chats[anna[0]].config()["modelSpecs"]
    spec = next(x for x in specs["list"] if x["name"] == "dolibarr-assistant")
    assert specs.get("prioritize") is True and spec.get("default") is True \
        and spec.get("mcpServers") == ["dolibarr"], specs
    return "default spec dolibarr-assistant with the dolibarr server"


def _whoami_chat(user):
    if not flows.llm_key_present():
        return "SKIP no LLM key (llm.env), see README"
    lc = chats[user[0]]
    spec = next(x for x in lc.config()["modelSpecs"]["list"] if x["name"] == "dolibarr-assistant")
    calls, text = lc.ask("Use the whoami tool: who am I in Dolibarr?", spec)
    outputs = " ".join(str(c.get("output")) for c in calls if "whoami" in (c.get("name") or ""))
    assert f"{user[2]} {user[3]} ({user[0]})" in outputs, f"tool calls {calls}, answer {text[:200]}"
    return text.strip()[:80]


@check("example 7: whoami in a chat names the logged-in Dolibarr user")
def _():
    return _whoami_chat(anna)


@check("example 7: a second user gets their own name")
def _():
    _librechat(carl)
    _connect(carl)
    return _whoami_chat(carl)


failed = [r for r in results if r[0] == "FAIL"]
print(f"\n{sum(r[0] == 'PASS' for r in results)} passed, {len(failed)} failed, "
      f"{sum(r[0] == 'SKIP' for r in results)} skipped")
sys.exit(1 if failed else 0)
