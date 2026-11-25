"""TEST ONLY. Check group "librechat": the example setup (docs/setup/example-keycloak-librechat.md,
checks 5 to 8): LibreChat users log in through Keycloak, connect the dolibarr server through restoauth's
consent page and ask whoami in a chat (the chat checks need an LLM key in llm.env or LLM_ENV_FILE and
report SKIP without it); the Keycloak setup run again keeps client settings it does not own; after a
LibreChat logout Keycloak asks for a password and another user logs in; after a LibreChat logout the
Dolibarr session in the browser has ended too, so the next user consents as themselves
(client/user_switch.py). Five LibreChat logins in all; LibreChat counts two requests per login against
its limit of seven per five minutes, and a login that would hit the limit waits for the window instead
of failing. Needs the services librechat and mongo; before its first check it waits until LibreChat
answers."""
import os
import time

import requests

import flows
import keycloak_realm
from checklib import Group
from common import CHAT, KC_USERS, REALM, SSO, kc_admin

# Seconds to wait for LibreChat before the first check of this group (it boots after the setup).
READY_TIMEOUT = int(os.environ.get("LIBRECHAT_READY_TIMEOUT", "300"))


def wait_for_librechat():
    """LibreChat is ready when /health answers and /api/config offers the Keycloak login. Neither is under
    /oauth/, so the wait costs nothing of LibreChat's login limit."""
    start = time.time()
    last = "no answer"
    while True:
        try:
            if requests.get(f"{CHAT}/health", timeout=10).status_code == 200:
                r = requests.get(f"{CHAT}/api/config", timeout=10)
                if r.status_code == 200 and r.json().get("openidLoginEnabled"):
                    break
                last = f"/api/config answered {r.status_code} without the Keycloak login"
            else:
                last = "/health not 200 yet"
        except (requests.RequestException, ValueError) as e:
            last = type(e).__name__
        if time.time() - start > READY_TIMEOUT:
            raise RuntimeError(f"LibreChat at {CHAT} not ready within {READY_TIMEOUT} s ({last}); is the "
                               "librechat service running? Start the whole stack, or raise LIBRECHAT_READY_TIMEOUT")
        time.sleep(3)
    waited = int(time.time() - start)
    if waited:
        print(f"   waited {waited} s until LibreChat was ready", flush=True)


group = Group(__name__, "Example setup: LibreChat (docs/setup/example-keycloak-librechat.md)", order=40,
              services=("librechat",), ready=wait_for_librechat)
check = group.check
anna, bob, carl, dave = KC_USERS
chats: dict = {}


def _librechat(user):
    lc = flows.LibreChat(user[0], user[1])
    me = lc.login()
    assert me.get("email") == user[4], me
    chats[user[0]] = lc
    return f"{me.get('name')} <{me.get('email')}>, PKCE {lc.pkce}, LibreChat login requests left {lc.login_budget}"


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
        return "SKIP no shared LLM key (LITELLM_KEY in /root/shared/llm.env on the test VM, else test-stack/llm.env), see README"
    lc = chats[user[0]]
    spec = next(x for x in lc.config()["modelSpecs"]["list"] if x["name"] == "dolibarr-assistant")
    calls, text = lc.ask("Use the whoami tool: who am I in Dolibarr?", spec)
    retried = ""
    if not calls and not text.strip():  # the model sometimes answers nothing: ask once more
        print("chat answer empty, retrying once", flush=True)
        retried = " (after one retry: first answer empty)"
        calls, text = lc.ask("Use the whoami tool: who am I in Dolibarr?", spec)
    outputs = " ".join(str(c.get("output")) for c in calls if "whoami" in (c.get("name") or ""))
    assert f"{user[2]} {user[3]} ({user[0]})" in outputs, f"tool calls {calls}, answer {text[:200]}"
    return text.strip()[:80] + retried


@check("example 7: whoami in a chat names the logged-in Dolibarr user")
def _():
    return _whoami_chat(anna)


@check("example 7: a second user gets their own name")
def _():
    _librechat(carl)
    _connect(carl)
    return _whoami_chat(carl)


@check("example setup: running the Keycloak setup again keeps client settings it does not own")
def _():
    # Another stack's or an admin's settings on the librechat client, then the stack's own setup again.
    kc = kc_admin()
    base = f"{SSO}/admin/realms/{REALM}/clients"
    url = f"{base}/{kc.get(base, params={'clientId': 'librechat'}).json()[0]['id']}"
    other = "https://other.example.com"
    rep = kc.get(url).json()
    rep["attributes"]["test.foreign.attribute"] = "kept"
    rep["attributes"]["post.logout.redirect.uris"] += f"##{other}/login"
    rep["redirectUris"] = rep["redirectUris"] + [f"{other}/callback"]
    assert kc.put(url, json=rep).status_code == 204
    try:
        keycloak_realm.setup_realm()
        after = kc.get(url).json()
        logout_uris = after["attributes"].get("post.logout.redirect.uris", "").split("##")
        assert after["attributes"].get("test.foreign.attribute") == "kept", after["attributes"]
        assert f"{other}/login" in logout_uris and f"{CHAT}/login" in logout_uris, logout_uris
        assert f"{other}/callback" in after["redirectUris"]             and f"{CHAT}/oauth/openid/callback" in after["redirectUris"], after["redirectUris"]
    finally:  # back to the stack's own settings
        rep = kc.get(url).json()
        rep["attributes"]["test.foreign.attribute"] = ""  # an empty value removes the attribute
        rep["attributes"]["post.logout.redirect.uris"] = "##".join(
            x for x in rep["attributes"]["post.logout.redirect.uris"].split("##") if not x.startswith(other))
        rep["redirectUris"] = [x for x in rep["redirectUris"] if not x.startswith(other)]
        kc.put(url, json=rep)
    return "foreign attribute, redirect URI and post-logout redirect URI kept next to the stack's own"


@check("example 8: after a LibreChat logout Keycloak asks for a password, and another user logs in")
def _():
    # One more LibreChat login (bob) on top of anna's and carl's. LibreChat counts two requests per login
    # against its limit of 7 per 5 minutes; if the budget is used up, LibreChat.login waits for the window.
    lc = chats[carl[0]]
    out = lc.logout()
    assert out["end_session"] == f"{SSO}/realms/{REALM}/protocol/openid-connect/logout", out
    assert out["landed"].startswith(f"{CHAT}/login"), f"after the logout the browser landed on {out['landed']}"
    gone = lc.b.post(f"{CHAT}/api/auth/refresh")
    # Without a session LibreChat answers in plain text ("Refresh token not provided"), with one in JSON.
    assert not (gone.status_code == 200 and gone.headers.get("content-type", "").startswith("application/json")),         "LibreChat session still alive after the logout"
    # The same browser: Sign in with Keycloak must show Keycloak's login form (LibreChat.login asserts it).
    switch = flows.LibreChat(bob[0], bob[1])
    switch.b = lc.b
    me = switch.login()
    assert me.get("email") == bob[4], me
    return (f"Keycloak login form shown again, now {me.get('email')}"
            + (" (Keycloak asked to confirm the logout)" if out["confirmed"] else "")
            + f", LibreChat login requests left {switch.login_budget}"
            + (f", waited {switch.waited} s for LibreChat's login limit" if switch.waited else ""))


@check("example 8: after a LibreChat logout the next user consents in Dolibarr as themselves")
def _():
    import user_switch  # the scenario lives in its own file (combined-stack-findings 06)
    return user_switch.verdict(user_switch.run())
