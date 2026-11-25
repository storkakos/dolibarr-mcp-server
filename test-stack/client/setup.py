"""TEST ONLY. Sets up Keycloak and checks that the stack is usable through the proxy.

Dolibarr configures itself on start: dolibarr/50-test-stack.sh installs restoauth from its release ZIP
and runs dolibarr/configure.php inside the Dolibarr container, because that step needs Dolibarr's own
PHP functions. Compose starts this service only once the Dolibarr container is healthy, i.e. once
that step succeeded.

Idempotent: a step already done is skipped, so `docker compose up` can run it again.
"""
import os
import re

import requests

import keycloak_realm
from common import DOLIBARR, ISSUER, MCP, REALM, SSO, say, wait_for


def check(what: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise SystemExit(f"setup check failed: {what} {detail}".rstrip())
    say("   ok:", what)


def main() -> None:
    say("waiting for Keycloak")
    wait_for(f"{SSO}/realms/master", lambda r: r.status_code == 200, what="Keycloak")

    say("Keycloak: realm, client dolibarr, test users")
    keycloak_realm.setup_realm()

    say("checks through the proxy")
    r = requests.get(f"{SSO}/realms/{REALM}/.well-known/openid-configuration", timeout=10)
    check("Keycloak realm metadata",
          r.status_code == 200 and r.json().get("issuer") == f"{SSO}/realms/{REALM}", f"{r.status_code}")

    # RFC 8414: metadata at the server root with the issuer path appended (the discovery rewrite rule).
    r = requests.get(f"{DOLIBARR}/.well-known/oauth-authorization-server/custom/restoauth", timeout=10)
    ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json")
    check("restoauth metadata via the discovery rewrite rule",
          ok and r.json().get("issuer") == ISSUER, f"{r.status_code} {r.text[:200]}")
    check("restoauth metadata: PKCE S256", "S256" in r.json().get("code_challenge_methods_supported", []))
    r = requests.get(f"{DOLIBARR}/custom/restoauth/.well-known/oauth-authorization-server", timeout=10)
    check("restoauth metadata at the issuer path",
          r.status_code == 200 and r.json().get("issuer") == ISSUER, f"{r.status_code}")
    if os.environ.get("TEST_PROXY") == "nginx":
        # The nginx variant: Dolibarr's Apache must not answer discovery itself, so the checks above
        # prove restoauth's nginx rules and not the Apache ones.
        r = requests.get("http://dolibarr/.well-known/oauth-authorization-server/custom/restoauth",
                         headers={"Host": "erp.example.com"}, allow_redirects=False, timeout=10)
        check("nginx variant: Dolibarr's Apache leaves discovery to nginx", r.status_code == 404, f"{r.status_code}")

    r = requests.get(f"{DOLIBARR}/index.php", timeout=10)
    check("Dolibarr login page offers the Keycloak login",
          r.status_code == 200 and f"{SSO}/realms/{REALM}/protocol/openid-connect/auth" in r.text,
          f"{r.status_code}")

    r = requests.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                      headers={"Accept": "application/json, text/event-stream"}, timeout=10)
    m = re.search(r'resource_metadata="([^"]+)"', r.headers.get("www-authenticate", ""))
    check("MCP server: 401 challenge without a token", r.status_code == 401 and m is not None,
          f"{r.status_code} {r.headers.get('www-authenticate')}")
    r = requests.get(m.group(1), timeout=10)
    prm = r.json() if r.status_code == 200 else {}
    check("MCP server: protected resource metadata names the public URL and the restoauth issuer",
          prm.get("resource", "").rstrip("/") == MCP
          and [s.rstrip("/") for s in prm.get("authorization_servers", [])] == [ISSUER],
          f"{r.status_code} {r.text[:200]}")

    say("setup complete")


if __name__ == "__main__":
    main()
