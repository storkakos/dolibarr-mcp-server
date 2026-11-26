"""TEST ONLY. Dolibarr's own Logout, then a Keycloak login lands where it should
(combined-stack-findings 07).

A user logs into Dolibarr through Keycloak, then logs out with Dolibarr's own Logout (top bar, not
through LibreChat). Dolibarr sends the browser to Keycloak's logout (MAIN_AUTHENTICATION_OIDC_LOGOUT_URL),
Keycloak asks "Do you want to log out?", loads the front-channel logout URL of the dolibarr client in
an iframe and returns to Dolibarr's login page. Then the user logs in again with "Use OpenID to login".
Expected: the browser ends on a Dolibarr page with the user logged in, without passing a Dolibarr
logout page on the way. With Dolibarr's user/logout.php as front-channel URL, that iframe showed the
login page, Dolibarr remembered it as return URL, and the next login ended on the logout page once.

    docker compose run --rm client python dolibarr_logout.py

checks.py runs the same scenario as one check of the group "librechat" (groups/librechat.py, see
run()).
"""
import html
import sys
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from common import DOLIBARR, KC_USERS, SSO, browser, form_data, page_text, say
from flows import _KEYCLOAK_AUTH

A = KC_USERS[0]  # anna


def _go(b, r, seen: list):
    """Follow redirects like a browser, appending every URL to seen."""
    seen.append(r.url)
    while r.status_code in (301, 302, 303, 307, 308):
        r = b.get(urljoin(r.url, r.headers["Location"]), allow_redirects=False)
        seen.append(r.url)
    return r


def _post(b, r, form, seen: list, extra: dict | None = None):
    d = form_data(form)
    d.update(extra or {})
    return _go(b, b.post(urljoin(r.url, form.get("action") or r.url), data=d, allow_redirects=False), seen)


def _on_dolibarr(r) -> bool:
    return urlparse(r.url).netloc == urlparse(DOLIBARR).netloc


def _logged_in(r) -> bool:
    return _on_dolibarr(r) and "logout.php" in r.text


def dolibarr_keycloak_login(b, user, pwd, seen: list):
    """Opens Dolibarr and logs in through Keycloak like a browser: Dolibarr's login page -> "Use OpenID
    to login" -> Keycloak's login form (skipped while a Keycloak session exists) -> Dolibarr's
    openid_connect callback, a form the browser submits by script -> the page Dolibarr returns to.
    Returns the last response."""
    r = _go(b, b.get(f"{DOLIBARR}/index.php", allow_redirects=False), seen)
    for _ in range(12):
        soup = BeautifulSoup(r.text, "lxml")
        if _logged_in(r):
            return r
        if urlparse(r.url).netloc == urlparse(SSO).netloc and soup.find("form", id="kc-form-login"):
            r = _post(b, r, soup.find("form", id="kc-form-login"), seen,
                      {"username": user, "password": pwd, "credentialId": ""})
        elif soup.find("input", attrs={"name": "openid_mode"}):
            r = _post(b, r, soup.find("input", attrs={"name": "openid_mode"}).find_parent("form"), seen)
        elif _on_dolibarr(r) and (m := _KEYCLOAK_AUTH.search(r.text)):
            # Dolibarr's login page: the "Use OpenID to login" button carries Keycloak's auth URL
            r = _go(b, b.get(html.unescape(m.group(0)), allow_redirects=False), seen)
        else:
            raise AssertionError(f"unexpected page {r.status_code} {r.url}: {page_text(r.text, 300)}")
    raise AssertionError(f"too many pages: {seen}")


def dolibarr_own_logout(b, seen: list) -> dict:
    """Dolibarr's own Logout from the top bar, through Keycloak's logout like a browser: "Do you want to
    log out?" -> Logout, the front-channel logout iframes, then on to the post-logout redirect URI.
    Returns where the browser landed and the front-channel URLs it loaded."""
    r = _go(b, b.get(f"{DOLIBARR}/index.php", allow_redirects=False), seen)
    assert _logged_in(r), f"not logged into Dolibarr before the logout: {r.status_code} {r.url}"
    link = BeautifulSoup(r.text, "lxml").find("a", href=lambda h: h and "logout.php" in h)
    assert link, "could not find Dolibarr's Logout link"
    r = _go(b, b.get(urljoin(r.url, html.unescape(link["href"])), allow_redirects=False), seen)
    confirm = BeautifulSoup(r.text, "lxml").find("input", attrs={"name": "confirmLogout"})
    if confirm is not None:  # no id_token_hint: Keycloak asks "Do you want to log out?"
        r = _post(b, r, confirm.find_parent("form"), seen, {"confirmLogout": "Logout"})
    soup = BeautifulSoup(r.text, "lxml")
    frames = [urljoin(r.url, f["src"]) for f in soup.find_all("iframe") if f.get("src")]
    for src in frames:
        _go(b, b.get(src, allow_redirects=False), [])
    cont = soup.find("a", id="continue")
    if frames and cont is not None and cont.get("href"):
        r = _go(b, b.get(urljoin(r.url, cont["href"]), allow_redirects=False), seen)
    return {"landed": r.url, "logged_in": _logged_in(r), "confirmed": confirm is not None,
            "frontchannel": [urlparse(f).netloc + urlparse(f).path for f in frames]}


def run(user=A, log=lambda *_: None) -> dict:
    """The scenario, step by step. Returns what happened in each step."""
    b = browser()
    first: list = []
    r = dolibarr_keycloak_login(b, user[0], user[1], first)
    log("1. A logs into Dolibarr through Keycloak, landed on", r.url)
    out = dolibarr_own_logout(b, [])
    log("2. A logs out with Dolibarr's own Logout",
        f"landed on {out['landed']}, front-channel logouts {out['frontchannel']}")
    again: list = []
    r = dolibarr_keycloak_login(b, user[0], user[1], again)
    log("3. A logs in again through Keycloak, landed on", r.url)
    log("   pages on the way", again)
    return {"logout": out, "relogin_url": r.url, "relogin_logged_in": _logged_in(r), "relogin_seen": again}


def verdict(res: dict) -> str:
    """Raises AssertionError when the logout or the login after it did not land where it should."""
    out = res["logout"]
    assert not out["logged_in"], f"still logged into Dolibarr after its own Logout ({out['landed']})"
    assert out["landed"].startswith(f"{DOLIBARR}/"), \
        f"after Dolibarr's own Logout the browser landed on {out['landed']}, expected Dolibarr's login page"
    assert any("restoauth/frontchannel-logout.php" in f for f in out["frontchannel"]), \
        f"Keycloak's logout did not load restoauth's front-channel logout endpoint: {out['frontchannel']}"
    logout_pages = [u for u in res["relogin_seen"]
                    if u.startswith(f"{DOLIBARR}/") and "logout" in urlparse(u).path]
    assert not logout_pages, f"the login after the Logout passed a Dolibarr logout page: {logout_pages}"
    assert res["relogin_logged_in"], f"not logged into Dolibarr after the new login ({res['relogin_url']})"
    return (f"logout landed on {out['landed']} (front-channel {out['frontchannel']}), "
            f"the new login landed on {res['relogin_url']}")


if __name__ == "__main__":
    result = run(log=lambda step, value: say(f"{step}: {value}"))
    try:
        say("PASS", verdict(result))
    except AssertionError as e:
        say("FAIL", e)
        sys.exit(1)
