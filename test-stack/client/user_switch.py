"""TEST ONLY. User switch in one browser (combined-stack-findings 06).

User A logs into LibreChat and connects the dolibarr server (consent in restoauth), then logs out of
LibreChat. User B logs into LibreChat in the same browser and connects the dolibarr server. Expected:
Dolibarr no longer has A's session, so B consents as B and LibreChat gets B's token. Without the
front-channel logout the Dolibarr session of A survived the logout, the consent page named A and B's
LibreChat got a token for A's Dolibarr account.

    docker compose run --rm client python user_switch.py   # prints each step, exit 1 on the wrong user

checks.py runs the same scenario as one check of the group "librechat" (groups/librechat.py, see
run()). A is anna, B is carl (bob may not connect
applications in this stack).
"""
import re
import sys

from bs4 import BeautifulSoup

import flows
from common import CHAT, DOLIBARR, KC_USERS, browser, follow, say

A, B = KC_USERS[0], KC_USERS[2]


def dolibarr_session(b) -> str | None:
    """Whom Dolibarr shows in the top bar of this browser, or None when Dolibarr shows its login page.
    Looks with a copy of the browser's cookies: Dolibarr's login page sets the cookie DOL_rollback_url_*
    (where its Keycloak login returns to) only if it is not set yet, so a look at the login page would
    send the next login back to index.php instead of restoauth's consent page."""
    look = browser()
    look.cookies.update(b.cookies.copy())
    r = follow(look, look.get(f"{DOLIBARR}/index.php", allow_redirects=False))
    if "logout.php" not in r.text:
        return None
    name = BeautifulSoup(r.text, "lxml").find(class_="atoploginusername")
    return name.get_text(strip=True) if name else f"? ({r.status_code} {r.url})"


def consenting_login(consent_text: str | None) -> str | None:
    """The Dolibarr login in the User row of restoauth's consent page ("User Anna Agent (anna)")."""
    body = (consent_text or "").split("on your behalf.", 1)[-1]
    m = re.search(r"\bUser (.+?) \((\S+)\)", body)
    return m.group(2) if m else None


def connections(admin, logins) -> dict[str, set]:
    """restoauth's connections per Dolibarr login, from the Connected applications tab of each user card."""
    return {login: set(flows.connected_apps(admin.b, admin.user_id(login))[1]) for login in logins}


def disconnect(lc) -> None:
    """LibreChat's Disconnect of the dolibarr server: forgets the stored token, so the next connect
    opens restoauth again."""
    r = lc.b.post(f"{CHAT}/api/user/plugins", headers=lc.h,
                  json={"pluginKey": "mcp_dolibarr", "action": "uninstall", "auth": {}})
    assert r.status_code < 400, f"LibreChat disconnect {r.status_code} {r.text[:200]}"


def run(a=A, b=B, log=lambda *_: None) -> dict:
    """The scenario, step by step. Returns what B ended up with; log(step, result) gets every step."""
    admin = flows.DolibarrAdmin()
    lc_a = flows.LibreChat(a[0], a[1])
    me = lc_a.login()
    log("1. A logs into LibreChat", me.get("email"))
    disconnect(lc_a)
    s = lc_a.connect_dolibarr()
    log("2. A connects dolibarr: consent page names", consenting_login(s["consent"]) or "(no consent page)")
    log("   pages on the way", s["seen"])
    log("   Dolibarr session in the browser", dolibarr_session(lc_a.b))
    out = lc_a.logout()
    log("3. A logs out of LibreChat", f"landed on {out['landed']}, front-channel logouts {out['frontchannel']}")
    after_logout = dolibarr_session(lc_a.b)
    log("4. Dolibarr session in the browser after the logout", after_logout or "none (Dolibarr login page)")

    lc_b = flows.LibreChat(b[0], b[1])
    lc_b.b = lc_a.b  # the same browser
    me = lc_b.login()
    log("5. B logs into LibreChat in the same browser", me.get("email"))
    disconnect(lc_b)
    before = connections(admin, (a[0], b[0]))
    s = lc_b.connect_dolibarr()
    consented_as = consenting_login(s["consent"])
    log("6. B connects dolibarr: consent page names", consented_as or "(no consent page)")
    log("   pages on the way", s["seen"])
    body = (s["consent"] or "")
    log("   consent page text", body[body.find("Allow access? An application"):][:420])
    after = connections(admin, (a[0], b[0]))
    new = [login for login in after for _ in after[login] - before[login]]
    log("7. new restoauth connection (the token B's LibreChat holds) belongs to", new)
    return {"dolibarr_after_logout": after_logout, "consented_as": consented_as, "token_for": new,
            "frontchannel": out["frontchannel"], "waited": lc_a.waited + lc_b.waited}


def verdict(res: dict, b=B) -> str:
    """Raises AssertionError when B consented or got a token as someone else."""
    assert res["consented_as"] == b[0], \
        f"B ({b[0]}) was shown the consent page for {res['consented_as']} (Dolibarr session after the " \
        f"logout: {res['dolibarr_after_logout']})"
    assert res["token_for"] == [b[0]], f"B's LibreChat holds a token for {res['token_for']}"
    return (f"consent and token for {b[0]}, Dolibarr session after the logout: "
            f"{res['dolibarr_after_logout'] or 'none'}"
            + (f", waited {res['waited']} s for LibreChat's login limit" if res["waited"] else ""))


if __name__ == "__main__":
    result = run(log=lambda step, value: say(f"{step}: {value}"))
    try:
        say("PASS", verdict(result))
    except AssertionError as e:
        say("FAIL", e)
        sys.exit(1)
