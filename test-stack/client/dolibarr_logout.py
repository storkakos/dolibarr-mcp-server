"""TEST ONLY. Dolibarr's own Logout, then a Keycloak login lands where it should
(combined-stack-findings 07).

A user logs into Dolibarr through Keycloak, then logs out of Dolibarr using Dolibarr's own Logout
button (not through LibreChat). Then the user logs back in with "Use OpenID to login". Expected: the
browser lands on the page Dolibarr expects (the home page), not on an empty page or a logout page.

    docker compose run --rm client python dolibarr_logout.py

checks.py runs the same scenario as one check of the group "librechat" (groups/librechat.py, see
run()).
"""
import sys

import flows
from common import DOLIBARR, KC_USERS, browser, follow, say

A = KC_USERS[0]  # anna


def dolibarr_own_logout(b) -> str:
    """Log out of Dolibarr using Dolibarr's own logout button. Returns the URL the browser lands on."""
    r = follow(b, b.get(f"{DOLIBARR}/index.php", allow_redirects=False))
    assert "logout.php" in r.text, "not logged into Dolibarr"
    # Dolibarr's logout link is in the top bar; follow it.
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "lxml")
    logout_link = soup.find("a", href=lambda h: h and "logout.php" in h)
    assert logout_link, "could not find Dolibarr's logout link"
    logout_url = logout_link["href"]
    if not logout_url.startswith("http"):
        logout_url = f"{DOLIBARR}/{logout_url.lstrip('/')}"
    r = follow(b, b.get(logout_url, allow_redirects=False))
    return r.url


def dolibarr_keycloak_login(b, user, pwd) -> str:
    """Log into Dolibarr through Keycloak. Returns the URL the browser lands on."""
    r = follow(b, b.get(f"{DOLIBARR}/index.php", allow_redirects=False))
    assert "Use OpenID to login" in r.text, "Dolibarr's login page does not offer Keycloak"
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "lxml")
    openid_link = soup.find("a", string=lambda s: s and "OpenID" in s)
    assert openid_link, "could not find the OpenID login link"
    openid_url = openid_link["href"]
    if not openid_url.startswith("http"):
        openid_url = f"{DOLIBARR}/{openid_url.lstrip('/')}"
    r = follow(b, b.get(openid_url, allow_redirects=False))
    # Now at Keycloak's login page; fill in the form.
    from flows import _post_form
    soup = BeautifulSoup(r.text, "lxml")
    form = soup.find("form")
    r = _post_form(b, r, form, {"username": user, "password": pwd, "login": "Sign In"})
    return r.url


def run(user=A, log=lambda *_: None) -> dict:
    """The scenario, step by step. Returns the URLs visited."""
    b = browser()
    log("1. A logs into Dolibarr through Keycloak")
    login_url = dolibarr_keycloak_login(b, user[0], user[1])
    log("   landed on", login_url)
    log("2. A logs out of Dolibarr using Dolibarr's own Logout")
    logout_url = dolibarr_own_logout(b)
    log("   landed on", logout_url)
    log("3. A logs back in through Keycloak")
    relogin_url = dolibarr_keycloak_login(b, user[0], user[1])
    log("   landed on", relogin_url)
    return {"login_url": login_url, "logout_url": logout_url, "relogin_url": relogin_url}


def verdict(res: dict) -> str:
    """Raises AssertionError when the relogin did not land where it should."""
    # After Dolibarr's own logout, the browser should be on the login page.
    assert res["logout_url"].startswith(f"{DOLIBARR}/"), \
        f"after Dolibarr's own logout the browser landed on {res['logout_url']}"
    # After the Keycloak relogin, the browser should be on Dolibarr's home page (or a page under Dolibarr).
    assert res["relogin_url"].startswith(f"{DOLIBARR}/"), \
        f"after the Keycloak relogin the browser landed on {res['relogin_url']}, expected a Dolibarr page"
    # The relogin should not land on a logout page.
    assert "logout" not in res["relogin_url"], \
        f"after the Keycloak relogin the browser landed on a logout page: {res['relogin_url']}"
    return (f"logout landed on {res['logout_url']}, relogin landed on {res['relogin_url']}")


if __name__ == "__main__":
    result = run(log=lambda step, value: say(f"{step}: {value}"))
    try:
        say("PASS", verdict(result))
    except AssertionError as e:
        say("FAIL", e)
        sys.exit(1)
