"""TEST ONLY. Browser flows: an MCP client (like LibreChat) connecting through restoauth, with the
Dolibarr login through Keycloak and restoauth's consent page, and MCP calls with the token it gets;
the Dolibarr administrator and a user on the user card (disable, enable, end a connection); then
LibreChat itself: Keycloak login, connecting the dolibarr server, a chat."""
import base64
import hashlib
import html
import json
import os
import re
import secrets
import time
import uuid
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from common import CHAT, DOLIBARR, DOLIBARR_ADMIN, MCP, REALM, SSO, browser, follow, form_data, page_text

# The MCP client's redirect URI, on restoauth's redirect allowlist (compose.yaml): LibreChat's callback
# for the MCP server named dolibarr. The Connection flows stop at the redirect and read code, state and
# iss from it, as a client would; the LibreChat flows let LibreChat's browser session open it.
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


def mcp(access_token: str, method: str, params: dict | None = None, url: str = MCP) -> requests.Response:
    return requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
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


def _csrf(text: str) -> str:
    """Dolibarr's CSRF token of the page, as its own links and forms carry it."""
    m = re.search(r'[?&;]token=([0-9a-f]{16,})', text) or re.search(r'name="token" value="([0-9a-f]{16,})"', text)
    assert m, "no CSRF token on the page"
    return m.group(1)


def user_status(text: str) -> str:
    """The status badge of a user card: Enabled or Disabled."""
    m = re.search(r'class="badge badge-status\d+ badge-status" title="([^"]+)"', text)
    assert m, "no status badge on the user card"
    return m.group(1)


class DolibarrAdmin:
    """The Dolibarr administrator in a browser, logged in with Dolibarr's own login form."""

    def __init__(self):
        self.b = browser()
        r = follow(self.b, self.b.get(f"{DOLIBARR}/index.php", allow_redirects=False))
        form = next((f for f in BeautifulSoup(r.text, "lxml").find_all("form")
                     if f.find("input", attrs={"name": "username"})), None)
        assert form is not None, f"no login form: {r.status_code} {r.url}"
        d = form_data(form)
        d.update(username=DOLIBARR_ADMIN[0], password=DOLIBARR_ADMIN[1])
        r = follow(self.b, self.b.post(urljoin(r.url, form.get("action") or r.url), data=d, allow_redirects=False))
        assert "logout.php" in r.text, f"admin login failed: {page_text(r.text, 300)}"

    def user_id(self, login: str) -> int:
        r = self.b.get(f"{DOLIBARR}/user/list.php", params={"search_login": login})
        for a in BeautifulSoup(r.text, "lxml").find_all("a", href=re.compile(r"/user/card\.php\?id=\d+")):
            if a.get_text(strip=True) == login:
                return int(re.search(r"id=(\d+)", a["href"]).group(1))
        raise AssertionError(f"user {login} not in the user list")

    def user_card(self, user_id: int):
        r = self.b.get(f"{DOLIBARR}/user/card.php", params={"id": user_id})
        assert r.status_code == 200, f"user card {r.status_code}"
        return r

    def set_enabled(self, user_id: int, enabled: bool) -> str:
        """Disable or enable a user as on the user card (button, then Yes). Returns the new status."""
        token = _csrf(self.user_card(user_id).text)
        action = "confirm_enable" if enabled else "confirm_disable"
        follow(self.b, self.b.get(f"{DOLIBARR}/user/card.php", allow_redirects=False,
                                  params={"id": user_id, "action": action, "confirm": "yes", "token": token}))
        status = user_status(self.user_card(user_id).text)
        assert status == ("Enabled" if enabled else "Disabled"), f"user {user_id} is {status}"
        return status


def connected_apps(b: requests.Session, user_id: int):
    """The user card's tab Connected applications (restoauth), reached through the tab link on the card.
    Returns the page and the revoke links by connection id."""
    card = b.get(f"{DOLIBARR}/user/card.php", params={"id": user_id})
    m = re.search(r'href="([^"]*/restoauth/connected\.php\?id=\d+)"', card.text)
    assert m, f"no Connected applications tab on the user card: {page_text(card.text, 300)}"
    r = b.get(urljoin(card.url, html.unescape(m.group(1))))
    assert r.status_code == 200, f"Connected applications {r.status_code}"
    links = {}
    for a in BeautifulSoup(r.text, "lxml").find_all("a", href=True):
        q = parse_qs(urlparse(a["href"]).query)
        if q.get("action") == ["revoke"]:
            links[q["connection"][0]] = urljoin(r.url, a["href"])
    return r, links


class LibreChat:
    """A LibreChat user in a browser: Keycloak login, connecting the dolibarr server, chatting."""

    def __init__(self, user: str, pwd: str):
        self.b = browser()
        self.user, self.pwd = user, pwd
        self.h: dict = {}
        self.pkce = None
        self.login_budget = None  # LibreChat's X-RateLimit-Remaining after the last login start
        self.waited = 0           # seconds waited for LibreChat's login limit
        self.oauth_done = None    # where LibreChat's MCP callback sends the browser

    def login(self) -> dict:
        cfg = self.b.get(f"{CHAT}/api/config").json()
        assert cfg.get("openidLoginEnabled"), "no Sign in with Keycloak in LibreChat"
        r = self._start_login()
        q = parse_qs(urlparse(r.headers.get("Location", "")).query)
        self.pkce = q.get("code_challenge_method", [None])[0]
        r = follow(self.b, r)
        form = BeautifulSoup(r.text, "lxml").find("form", id="kc-form-login")
        if form is None and r.url.startswith(CHAT):
            raise AssertionError(f"Keycloak logged in again without asking for a password: {r.url}")
        if form is None and "auth_rate_limited" in r.url + r.text:
            raise AssertionError("LibreChat's login rate limit (about 7 logins per 5 minutes), wait five minutes")
        assert form is not None, f"no Keycloak login form: {r.status_code} {r.url}"
        d = form_data(form)
        d.update({"username": self.user, "password": self.pwd, "credentialId": ""})
        r = follow(self.b, self.b.post(form["action"], data=d, allow_redirects=False))
        if "error=" in r.url:
            raise AssertionError(f"LibreChat login failed: {r.url}")
        tok = self.b.post(f"{CHAT}/api/auth/refresh")
        assert tok.status_code == 200 and tok.headers.get("content-type", "").startswith("application/json"), \
            f"no LibreChat session: {tok.status_code} {tok.text[:150]}"
        self.h = {"Authorization": "Bearer " + tok.json()["token"]}
        return tok.json()["user"]

    def _start_login(self):
        """Sign in with Keycloak. LibreChat's login limiter counts every request under /oauth/ per IP (start
        and callback, two per login; LOGIN_MAX 7 per LOGIN_WINDOW 5 minutes, fixed from the first request). If this start used up the
        budget, the callback would be refused with auth_rate_limited: wait for the window to end and
        start again, instead of failing."""
        r = self.b.get(f"{CHAT}/oauth/openid", allow_redirects=False)
        left, reset = r.headers.get("X-RateLimit-Remaining"), r.headers.get("X-RateLimit-Reset")
        self.login_budget = left
        if left is not None and int(left) < 1 and reset:
            wait = max(0, int(float(reset) - time.time())) + 2
            print(f"   LibreChat login limit reached, waiting {wait} s for its window", flush=True)
            time.sleep(wait)
            self.waited = wait
            r = self.b.get(f"{CHAT}/oauth/openid", allow_redirects=False)
            self.login_budget = r.headers.get("X-RateLimit-Remaining")
        return r

    def config(self) -> dict:
        return self.b.get(f"{CHAT}/api/config", headers=self.h).json()

    def logout(self) -> dict:
        """The Log out menu item: LibreChat ends its session and sends the browser to Keycloak's end-session
        endpoint (OPENID_USE_END_SESSION_ENDPOINT), which ends the Keycloak session and redirects to
        OPENID_POST_LOGOUT_REDIRECT_URI. Returns the end-session URL, whether Keycloak asked "Do you want
        to log out?" and where the browser landed."""
        r = self.b.post(f"{CHAT}/api/auth/logout", headers=self.h)
        assert r.status_code == 200, f"LibreChat logout {r.status_code} {r.text[:200]}"
        redirect = r.json().get("redirect")
        assert redirect, f"LibreChat did not send the browser to Keycloak (OPENID_USE_END_SESSION_ENDPOINT?): {r.json()}"
        self.h = {}
        r = follow(self.b, self.b.get(redirect, allow_redirects=False))
        confirm = BeautifulSoup(r.text, "lxml").find("input", attrs={"name": "confirmLogout"})
        if confirm is not None:  # no id_token_hint: Keycloak asks "Do you want to log out?"
            r = _post_form(self.b, r, confirm.find_parent("form"), {"confirmLogout": "Logout"})
        assert "Invalid redirect uri" not in r.text,             "Keycloak: Invalid redirect uri (post logout redirect URI missing on the librechat client)"
        return {"end_session": redirect.split("?")[0], "confirmed": confirm is not None, "landed": r.url}

    def connect_dolibarr(self) -> dict:
        """Connect icon -> Continue with OAuth: Dolibarr login (through Keycloak) -> consent -> allow.
        Returns LibreChat's connection status, the consent page text (None if already connected) and
        the login pages passed on the way."""
        r = self.b.post(f"{CHAT}/api/mcp/dolibarr/reinitialize", headers=self.h, json={})
        assert r.status_code == 200, f"reinitialize {r.status_code} {r.text[:200]}"
        data = r.json()
        consent_text = None
        seen: list[str] = []
        if data.get("oauthUrl"):
            r = follow(self.b, self.b.get(data["oauthUrl"], allow_redirects=False), CALLBACK)
            where, r = browse_to_consent(self.b, r, self.user, self.pwd, seen)
            assert where == "consent", f"expected the consent page, got the callback {r}"
            consent_text = page_text(r.text, 5000)
            cb = decide(self.b, r, "allow")
            assert isinstance(cb, str), f"consent did not lead back to LibreChat: {page_text(cb.text, 300)}"
            # The browser opens LibreChat's callback; LibreChat exchanges the code there. Its redirect to
            # the page under /oauth/ that says "connected" is not followed: LibreChat's login limiter counts
            # every request under /oauth/, and the logins of the checks need that budget.
            done = self.b.get(cb, allow_redirects=False)
            assert done.status_code < 400 and "error" not in done.headers.get("Location", ""),                 f"LibreChat's MCP callback: {done.status_code} {done.headers.get('Location')}"
            self.oauth_done = done.headers.get("Location")
        s: dict = {}
        for _ in range(20):
            st = self.b.get(f"{CHAT}/api/mcp/connection/status", headers=self.h).json()
            s = st.get("connectionStatus", {}).get("dolibarr", {})
            if s.get("connectionState") == "connected":
                return {"consent": consent_text, "seen": seen, **s}
            time.sleep(1)
        raise AssertionError(f"dolibarr not connected: {s}")

    def ask(self, question: str, spec: dict) -> tuple[list, str]:
        """New chat with the given model spec; returns (tool calls, answer text)."""
        preset = spec["preset"]
        body = {
            "text": question, "sender": "User", "isCreatedByUser": True,
            "parentMessageId": "00000000-0000-0000-0000-000000000000", "conversationId": None,
            "messageId": str(uuid.uuid4()), "error": False, "endpoint": preset["endpoint"],
            "endpointType": "custom", "model": preset["model"], "spec": spec["name"], "key": None,
            "isContinued": False, "isTemporary": False,
            "ephemeralAgent": {"mcp": spec.get("mcpServers", []), "execute_code": False, "web_search": False,
                               "file_search": False},
        }
        r = self.b.post(f"{CHAT}/api/agents/chat/{preset['endpoint']}", headers=self.h, json=body)
        d = r.json()
        r = self.b.get(f"{CHAT}/api/agents/chat/stream/{d['streamId']}", headers=self.h, stream=True, timeout=180)
        final = None
        for line in r.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                try:
                    ev = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if ev.get("final"):
                    final = ev
                    break
        msg = (final or {}).get("responseMessage") or {}
        parts = msg.get("content") or []
        calls = [p["tool_call"] for p in parts if p.get("type") == "tool_call"]
        text = (msg.get("text") or "") + "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        return calls, text


def llm_key_present() -> bool:
    """An LLM key from llm.env (any *_KEY). GPG_KEY is set by the Python base image, not by llm.env."""
    return any(v for k, v in os.environ.items() if k.endswith("_KEY") and k != "GPG_KEY")
