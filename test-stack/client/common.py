"""TEST ONLY. Shared values and helpers of the test stack. Every password and secret here is a test value."""
import os
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DOLIBARR = "https://erp.example.com"
SSO = "https://sso.example.com"
CHAT = "https://chat.example.com"
# The MCP server's public URL (its MCP_RESOURCE_URL), group setting TEST_MCP_URL (README "Group settings").
# The only place the test client names it: checks, flows and config edits all use this value. The default
# is the repo stack's; the combined stack, where each repo's server has its own host name, sets the variable.
MCP = os.environ.get("TEST_MCP_URL", "https://mcp.example.com/mcp")
REALM = "example"
# restoauth's issuer: the module URL behind the proxy (the setup page's Issuer field stays empty).
ISSUER = f"{DOLIBARR}/custom/restoauth"

# Test values (the same as in compose.yaml)
DOLIBARR_ADMIN = ("admin", "Test-Admin-Pw1!")
KC_ADMIN = ("admin", "test-kc-admin-pw")
KC_SECRET_DOLIBARR = "test-secret-dolibarr-client-0123456789"
KC_SECRET_LIBRECHAT = "test-secret-librechat-client-0123456789"
# anna's own Dolibarr API key (TEST_ANNA_API_KEY in compose.yaml), not a restoauth token
ANNA_API_KEY = "test-anna-api-key-0123456789abcdef0123"
# Keycloak users; the Dolibarr login is the same name (preferred_username). Rights: see README.
KC_USERS = [
    ("anna", "Test-Anna-Pw1!", "Anna", "Agent", "anna@example.com"),
    ("bob", "Test-Bob-Pw1!", "Bob", "Support", "bob@example.com"),
    ("carl", "Test-Carl-Pw1!", "Carl", "Sales", "carl@example.com"),
    ("dave", "Test-Dave-Pw1!", "Dave", "Leaver", "dave@example.com"),
]

# LibreChat refuses requests without a browser User-Agent ("Illegal request").
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


def say(*a):
    print(*a, flush=True)


def browser() -> requests.Session:
    b = requests.Session()
    b.headers["User-Agent"] = BROWSER_UA
    return b


def page_text(html: str, n: int = 600) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" ")).strip()[:n]


def follow(b: requests.Session, r, stop_prefix: str | None = None):
    """Follow redirects like a browser; returns the final response, or the URL that starts with stop_prefix."""
    while r.status_code in (301, 302, 303, 307, 308):
        loc = urljoin(r.url, r.headers["Location"])
        if stop_prefix and loc.startswith(stop_prefix):
            return loc
        r = b.get(loc, allow_redirects=False)
    return r


def form_data(form) -> dict:
    data = {}
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name or el.has_attr("disabled"):
            continue
        t = (el.get("type") or "text").lower()
        if el.name == "input" and t in ("checkbox", "radio") and not el.has_attr("checked"):
            continue
        if el.name == "input" and t in ("submit", "button", "image"):
            continue
        if el.name == "select":
            opt = el.find("option", selected=True) or el.find("option")
            data[name] = opt.get("value", opt.text) if opt else ""
        else:
            data[name] = el.get("value", "") if el.name == "input" else el.text
    return data


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
