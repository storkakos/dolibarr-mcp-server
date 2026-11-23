"""TEST ONLY. Shared values and helpers of the test stack. Every password and secret here is a test value."""
import time

import requests

DOLIBARR = "https://erp.example.com"
SSO = "https://sso.example.com"
MCP = "https://mcp.example.com/mcp"
REALM = "example"
# restoauth's issuer: the module URL behind the proxy (the setup page's Issuer field stays empty).
ISSUER = f"{DOLIBARR}/custom/restoauth"

# Test values (the same as in compose.yaml)
DOLIBARR_ADMIN = ("admin", "Test-Admin-Pw1!")
KC_ADMIN = ("admin", "test-kc-admin-pw")
KC_SECRET_DOLIBARR = "test-secret-dolibarr-client-0123456789"
# Keycloak users; the Dolibarr login is the same name (preferred_username). Rights: see README.
KC_USERS = [
    ("anna", "Test-Anna-Pw1!", "Anna", "Agent", "anna@example.com"),
    ("bob", "Test-Bob-Pw1!", "Bob", "Support", "bob@example.com"),
]


def say(*a):
    print(*a, flush=True)


def wait_for(url: str, ok=lambda r: r.status_code < 500, timeout: int = 900, what: str = ""):
    end = time.time() + timeout
    while True:
        try:
            r = requests.get(url, allow_redirects=False, timeout=10)
            if ok(r):
                return r
        except requests.RequestException:
            pass
        if time.time() > end:
            raise SystemExit(f"timeout waiting for {what or url}")
        time.sleep(3)


def kc_admin() -> requests.Session:
    s = requests.Session()
    tok = s.post(f"{SSO}/realms/master/protocol/openid-connect/token", data={
        "grant_type": "password", "client_id": "admin-cli", "username": KC_ADMIN[0], "password": KC_ADMIN[1]}).json()
    s.headers["Authorization"] = "Bearer " + tok["access_token"]
    return s
