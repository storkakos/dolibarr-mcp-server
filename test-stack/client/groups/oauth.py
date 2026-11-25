"""TEST ONLY. Check group "oauth": an MCP client connects through restoauth (discovery, dynamic
registration, Keycloak login, consent, PKCE), refreshes, gets caught reusing a refresh token, revokes;
with the negative cases of each step. No LibreChat needed. Sets up what the later groups build on
(state: the metadata, the registered client, anna's connection)."""
import os

import requests

import flows
from checklib import Group, state
from common import ISSUER, KC_USERS, MCP

group = Group(__name__, "OAuth flow: discovery, registration, authorize, Keycloak login, consent, token, refresh, revoke",
              order=10)
check = group.check
anna, bob, carl, dave = KC_USERS
# The MCP server keeps a token's rights for MCP_RIGHTS_CACHE_SECONDS (default 30); a revoked token is
# refused by Dolibarr at once and by the MCP server at the latest after that.
CACHE_WAIT = int(os.environ.get("MCP_RIGHTS_CACHE_SECONDS", "30")) + 15


def callback_error(r) -> dict:
    assert isinstance(r, str), f"no redirect back to the client: {r.status_code} {r.url}"
    q = flows.callback_query(r)
    assert "code" not in q, "a code was issued"
    return q


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
