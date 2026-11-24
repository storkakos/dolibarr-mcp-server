"""TEST ONLY. Browser flows: an MCP client (like LibreChat) connecting through restoauth, with the
Dolibarr login through Keycloak and restoauth's consent page, and MCP calls with the token it gets."""
import base64
import hashlib
import html
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from common import CHAT, DOLIBARR, MCP, REALM, SSO, browser, follow, form_data, page_text

# The MCP client's redirect URI, on restoauth's redirect allowlist (compose.yaml). Nothing answers at
# this address: the flows stop at the redirect and read code, state and iss from it, as a client would.
CALLBACK = f"{CHAT}/api/mcp/dolibarr/oauth/callback"
API = f"{DOLIBARR}/api/index.php"
_KEYCLOAK_AUTH = re.compile(re.escape(f"{SSO}/realms/{REALM}/protocol/openid-connect/auth") + r"[^\"'\s<>]*")


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def discover() -> tuple[dict, dict]:
    """What an MCP client does first: 401 challenge -> protected resource metadata (RFC 9728) ->
    authorization server metadata at the server root (RFC 8414). Returns (prm, asm)."""
    r = requests.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                      headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401, f"MCP without a token: {r.status_code}"
    prm = requests.get(re.search(r'resource_metadata="([^"]+)"', r.headers["www-authenticate"]).group(1)).json()
    u = urlparse(prm["authorization_servers"][0])
    asm = requests.get(f"{u.scheme}://{u.netloc}/.well-known/oauth-authorization-server{u.path}").json()
    return prm, asm


def register(asm: dict, redirect_uris: list[str], name: str = "test-stack MCP client") -> requests.Response:
    return requests.post(asm["registration_endpoint"], json={
        "client_name": name, "redirect_uris": redirect_uris, "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]})


def authorize(b: requests.Session, asm: dict, params: dict):
    """GET the authorization endpoint and follow redirects; returns the response, or the callback URL."""
    return follow(b, b.get(asm["authorization_endpoint"], params=params, allow_redirects=False), CALLBACK)


def auth_params(prm: dict, client_id: str, challenge: str | None, state: str, **extra) -> dict:
    p = {"response_type": "code", "client_id": client_id, "redirect_uri": CALLBACK, "state": state,
         "resource": prm["resource"], "scope": "dolibarr"}
    if challenge is not None:
        p.update(code_challenge=challenge, code_challenge_method="S256")
    p.update(extra)
    return {k: v for k, v in p.items() if v is not None}


def _post_form(b, r, form, extra: dict | None = None):
    d = form_data(form)
    d.update(extra or {})
    return follow(b, b.post(urljoin(r.url, form.get("action") or r.url), data=d, allow_redirects=False), CALLBACK)


def browse_to_consent(b: requests.Session, r, user: str, pwd: str, seen: list | None = None):
    """Walks the login pages until restoauth's consent page or the client callback.
    Dolibarr login page -> Keycloak login form -> Dolibarr's openid_connect callback form -> consent.
    Appends the name of each page passed to seen. Returns ("consent", response) or ("callback", url)."""
    seen = [] if seen is None else seen
    for _ in range(12):
        if isinstance(r, str):
            return "callback", r
        soup = BeautifulSoup(r.text, "lxml")
        host = urlparse(r.url).netloc
        if host == urlparse(SSO).netloc and soup.find("form", id="kc-form-login"):
            seen.append("keycloak login")
            r = _post_form(b, r, soup.find("form", id="kc-form-login"),
                           {"username": user, "password": pwd, "credentialId": ""})
        elif soup.find("input", attrs={"name": "openid_mode"}):
            # Dolibarr's openid_connect callback: a form the browser submits by script
            seen.append("dolibarr openid_connect callback")
            r = _post_form(b, r, soup.find("input", attrs={"name": "openid_mode"}).find_parent("form"))
        elif soup.find("button", attrs={"name": "restoauth_action"}) and soup.find("input", attrs={"name": "req"}):
            return "consent", r
        elif (m := _KEYCLOAK_AUTH.search(r.text)) and host == urlparse(DOLIBARR).netloc:
            # Dolibarr's login page: the "login with OpenID Connect" button
            seen.append("dolibarr login page")
            r = follow(b, b.get(html.unescape(m.group(0)), allow_redirects=False), CALLBACK)
        else:
            raise AssertionError(f"unexpected page {r.status_code} {r.url}: {page_text(r.text, 300)}")
    raise AssertionError("too many pages")


def consent_form(r):
    return next(f for f in BeautifulSoup(r.text, "lxml").find_all("form") if f.find("input", attrs={"name": "req"}))


def decide(b: requests.Session, r, decision: str):
    """Submits restoauth's consent form with restoauth_action=allow|deny (the button value)."""
    return _post_form(b, r, consent_form(r), {"restoauth_action": decision})


def callback_query(url: str) -> dict:
    assert url.startswith(CALLBACK), url
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def token(asm: dict, **data) -> requests.Response:
    return requests.post(asm["token_endpoint"], data=data)


class Connection:
    """One user connecting an MCP client: their own browser (Dolibarr session) and one registered client."""

    def __init__(self, prm: dict, asm: dict, client_id: str, user: str, pwd: str):
        self.prm, self.asm, self.client_id, self.user, self.pwd = prm, asm, client_id, user, pwd
        self.b = browser()
        self.seen: list[str] = []   # login pages passed on the way to the consent page, all authorizations

    def consent_page(self, challenge: str, state: str):
        r = authorize(self.b, self.asm, auth_params(self.prm, self.client_id, challenge, state))
        where, r = browse_to_consent(self.b, r, self.user, self.pwd, self.seen)
        assert where == "consent", f"expected the consent page, got the callback {r}"
        return r

    def code(self) -> tuple[str, str]:
        """Authorize, log in if needed, allow. Returns (code, verifier); checks state and iss."""
        verifier, challenge = pkce()
        state = secrets.token_urlsafe(16)
        cb = decide(self.b, self.consent_page(challenge, state), "allow")
        assert isinstance(cb, str), f"consent did not lead back to the client: {page_text(cb.text, 300)}"
        q = callback_query(cb)
        assert "code" in q, q
        assert q.get("state") == state, "state changed"
        assert q.get("iss", "").rstrip("/") == self.asm["issuer"].rstrip("/"), f"iss {q.get('iss')}"
        return q["code"], verifier

    def tokens(self) -> dict:
        code, verifier = self.code()
        t = token(self.asm, grant_type="authorization_code", code=code, redirect_uri=CALLBACK,
                  client_id=self.client_id, code_verifier=verifier, resource=self.prm["resource"])
        assert t.status_code == 200, f"token {t.status_code} {t.text[:200]}"
        return t.json()


def dolibarr_me(access_token: str) -> requests.Response:
    """restoauth's GET /restoauth/me straight at the Dolibarr REST API with the token."""
    return requests.get(f"{API}/restoauth/me", headers={"Authorization": f"Bearer {access_token}"})


def mcp(access_token: str, method: str, params: dict | None = None) -> requests.Response:
    return requests.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                         headers={"Authorization": f"Bearer {access_token}",
                                  "Accept": "application/json, text/event-stream",
                                  "MCP-Protocol-Version": "2025-06-18"})


def _result(r: requests.Response) -> dict:
    assert r.status_code == 200, f"MCP HTTP {r.status_code} {r.text[:200]}"
    m = re.search(r"^data: (.*)$", r.text, re.M)
    body = json.loads(m.group(1)) if m else r.json()
    assert "result" in body, body
    return body["result"]


def tool_names(access_token: str) -> list[str]:
    return sorted(t["name"] for t in _result(mcp(access_token, "tools/list"))["tools"])


def call(access_token: str, tool: str, **arguments) -> str:
    """tools/call; returns the tool's text (a refusal is text too, as the server answers it)."""
    res = _result(mcp(access_token, "tools/call", {"name": tool, "arguments": arguments}))
    return res["content"][0]["text"]


def call_json(access_token: str, tool: str, **arguments):
    text = call(access_token, tool, **arguments)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise AssertionError(f"{tool}: {text[:200]}") from None


def wait_for_mcp_401(access_token: str, seconds: int) -> int:
    """The MCP server caches a token's rights for MCP_RIGHTS_CACHE_SECONDS; polls until it answers 401.
    Returns the seconds it took."""
    start = time.time()
    while True:
        if mcp(access_token, "tools/list").status_code == 401:
            return int(time.time() - start)
        if time.time() - start > seconds:
            raise AssertionError(f"MCP server still accepts the token after {seconds} s")
        time.sleep(2)
