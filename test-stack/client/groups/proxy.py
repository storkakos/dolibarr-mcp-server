"""TEST ONLY. Check group "proxy": the reverse proxy: restoauth's discovery URLs, and in the nginx variant
(compose.nginx.yaml) the MCP server under a path prefix (skipped behind Caddy). No LibreChat needed.
Builds on the group "oauth" (metadata, registered client)."""
import os
import re
from urllib.parse import urlparse

import requests

import flows
from checklib import Group, state
from common import DOLIBARR, ISSUER, KC_USERS

# Which proxy is in front (compose.nginx.yaml sets nginx), and the MCP server under a path prefix (nginx only).
PROXY = os.environ.get("TEST_PROXY", "caddy")
PREFIX_MCP = os.environ.get("TEST_MCP_PREFIX_URL", "")

group = Group(__name__, f"Reverse proxy ({PROXY}): restoauth discovery, the MCP server under a path prefix",
              order=50, needs=("oauth",))
check = group.check
anna, bob, carl, dave = KC_USERS


@check("restoauth metadata at the server root and in the issuer path, both names (discovery rules)")
def _():
    for name in ("oauth-authorization-server", "openid-configuration"):
        for url in (f"{DOLIBARR}/.well-known/{name}/custom/restoauth", f"{ISSUER}/.well-known/{name}"):
            r = requests.get(url, allow_redirects=False)
            assert r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json")                 and r.json().get("issuer") == ISSUER, f"{url}: {r.status_code} {r.text[:120]}"
    return "4 URLs"


def _prefix_skip():
    return "SKIP Caddy has no path prefix variant; run the nginx variant (compose.nginx.yaml)" if not PREFIX_MCP else None


@check("path prefix: 401 challenge at the prefixed endpoint, protected resource metadata under the prefix")
def _():
    if skip := _prefix_skip():
        return skip
    r = requests.post(PREFIX_MCP, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                      headers={"Accept": "application/json, text/event-stream"})
    m = re.search(r'resource_metadata="([^"]+)"', r.headers.get("www-authenticate", ""))
    assert r.status_code == 401 and m, f"{r.status_code} {r.headers.get('www-authenticate')}"
    u = urlparse(PREFIX_MCP)
    expected = f"{u.scheme}://{u.netloc}/.well-known/oauth-protected-resource{u.path}"
    assert m.group(1) == expected, m.group(1)
    r = requests.get(m.group(1), allow_redirects=False)
    assert r.status_code == 200, f"{r.status_code} {r.text[:120]}"
    prm = r.json()
    assert prm["resource"].rstrip("/") == PREFIX_MCP and [s.rstrip("/") for s in prm["authorization_servers"]] == [ISSUER], prm
    state["prefix_prm"] = prm
    return m.group(1)


@check("path prefix: a user connects for the prefixed resource and the tools answer through the prefix")
def _():
    if skip := _prefix_skip():
        return skip
    con = flows.Connection(state["prefix_prm"], state["asm"], state["client_id"], anna[0], anna[1])
    tok = con.tokens()["access_token"]
    res = flows._result(flows.mcp(tok, "tools/call", {"name": "whoami", "arguments": {}}, url=PREFIX_MCP))
    assert "Anna Agent (anna)" in res["content"][0]["text"], res
    return "whoami names anna"
