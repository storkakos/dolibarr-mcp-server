"""TEST ONLY. Check group "ends": the three ways a connection ends: the user is disabled, the user ends it
on their user card, the access token expires (the stack sets a short access token lifetime; with a
lifetime longer than EXPIRY_MAX_WAIT seconds, default 300, the expiry check is skipped). No LibreChat
needed. Builds on the group "oauth" (registered client, anna's connection)."""
import os
import time

import requests

import flows
from checklib import Group, state
from common import KC_USERS
from groups.oauth import CACHE_WAIT

group = Group(__name__, "How a connection ends: user disabled, connection ended on the user card, access token expired",
              order=30, needs=("oauth",))
check = group.check
anna, bob, carl, dave = KC_USERS
# The expiry check waits at most this long for the access token to expire by itself.
EXPIRY_MAX_WAIT = int(os.environ.get("EXPIRY_MAX_WAIT", "300"))


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


@check("expiry: a new connection gets an access token of the configured lifetime that works")
def _():
    tok = state["anna"].tokens()
    state["exp"], state["exp_issued"] = tok, time.time()
    assert int(tok["expires_in"]) > 0, f"expires_in {tok.get('expires_in')}"
    assert flows.call_json(tok["access_token"], "whoami")["user"] == "Anna Agent (anna)"
    assert flows.dolibarr_me(tok["access_token"]).status_code == 200
    later = "checked again after the next checks" if int(tok["expires_in"]) <= EXPIRY_MAX_WAIT         else f"longer than EXPIRY_MAX_WAIT ({EXPIRY_MAX_WAIT} s), the expiry check will be skipped"
    return f"expires_in {tok['expires_in']} s; {later}"


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
    if int(tok["expires_in"]) > EXPIRY_MAX_WAIT:
        return (f"SKIP access token lifetime {tok['expires_in']} s is longer than EXPIRY_MAX_WAIT "
                f"({EXPIRY_MAX_WAIT} s); the test stack sets 60 s (TEST_ACCESS_TOKEN_LIFETIME)")
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
