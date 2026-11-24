"""TEST ONLY. Takes the screenshots of docs/quick-start.md and docs/user-guide.md from the test stack.

Run it on a freshly started stack (see ../README.md, section "Screenshots"): it logs in as the test
users, connects the Dolibarr assistant in LibreChat, asks the assistant questions (needs the LLM key),
and ends a connection on a user card. It writes PNG files (1280 or 1440 x 900 pixels) to
/out/quick-start and /out/user-guide, which compose mounts from docs/images.

    python shoot.py              # all parts, in this order: anna, carl, bob, admin
    python shoot.py anna admin   # only these parts
"""
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

DOLIBARR = "https://erp.example.com"
CHAT = "https://chat.example.com"
OUT = Path("/out")
# Test values, the same as in compose.yaml and client/common.py
DOLIBARR_ADMIN = ("admin", "Test-Admin-Pw1!")
USERS = {"anna": "Test-Anna-Pw1!", "bob": "Test-Bob-Pw1!", "carl": "Test-Carl-Pw1!"}
VIEWPORT = {"width": 1280, "height": 900}
# How long a chat answer may take (tool calls plus the model)
ANSWER_TIMEOUT = 180_000
# Only for working on this script: a folder where the LibreChat sessions are kept between runs, so
# that repeated runs do not hit LibreChat's login rate limit. Not set for the real run.
STATE_DIR = os.environ.get("SHOOT_STATE_DIR")


def say(*a):
    print(*a, flush=True)


def shot(page: Page, name: str):
    """Saves the visible part of the page as OUT/<name>.png (name: '<folder>/<file>')."""
    path = OUT / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(700)  # let animations settle
    page.screenshot(path=str(path))
    say("  saved", path)


def dump(page: Page, name: str):
    """On failure: the page as PNG and HTML in OUT/debug, for debugging (not for the docs)."""
    (OUT / "debug").mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / "debug" / f"{name}.png"))
    (OUT / "debug" / f"{name}.html").write_text(page.content())


def new_context(browser, user: str | None = None, width: int = VIEWPORT["width"]):
    state = None
    if STATE_DIR and user and Path(STATE_DIR, f"{user}.json").exists():
        state = str(Path(STATE_DIR, f"{user}.json"))
    # The test CA is not in Chromium's trust store; the hostnames only exist in the stack's network.
    return browser.new_context(viewport={"width": width, "height": VIEWPORT["height"]},
                               ignore_https_errors=True, locale="en-US", timezone_id="Europe/Berlin",
                               color_scheme="light", storage_state=state)


def save_state(page: Page, user: str):
    if STATE_DIR:
        page.context.storage_state(path=str(Path(STATE_DIR, f"{user}.json")))


def scroll_to(page: Page, locator, offset: int = 120):
    """Scrolls so that the element is <offset> pixels below the top of the window."""
    locator.wait_for(timeout=30_000)
    y = locator.evaluate("e => e.getBoundingClientRect().top + window.scrollY")
    page.evaluate(f"window.scrollTo(0, {max(0, y - offset)})")


# --- LibreChat ---------------------------------------------------------------------------------------

def chat_login(page: Page, user: str, shots: bool = False):
    """Logs into LibreChat through Keycloak (Sign in with Keycloak). LibreChat limits logins per IP, and
    the third user of a run can hit the limit already: then it waits five minutes and tries again."""
    if STATE_DIR and Path(STATE_DIR, f"{user}.json").exists():
        page.goto(f"{CHAT}/c/new")
        try:
            page.get_by_test_id("text-input").wait_for(timeout=20_000)
            return
        except Exception:
            pass
    for attempt in range(2):
        page.goto(f"{CHAT}/login")
        btn = page.get_by_text("Sign in with Keycloak")
        expect(btn).to_be_visible(timeout=30_000)
        if shots:
            shot(page, "user-guide/01-librechat-login")
        btn.click()
        form = page.locator("#kc-form-login")
        chat = page.get_by_test_id("text-input")
        page.wait_for_url(re.compile(r"sso\.example\.com|/c/|auth_rate_limited"), timeout=60_000)
        if form.count() or "sso.example.com" in page.url:  # no Keycloak session yet
            page.fill("#username", user)
            if shots:
                shot(page, "user-guide/02-keycloak-login")
            page.fill("#password", USERS[user])
            page.click("#kc-login")
        # Logged in: the chat. Rate limited: LibreChat's login page again.
        chat.or_(btn).first.wait_for(timeout=60_000)
        if chat.count():
            break
        if attempt:
            raise AssertionError("LibreChat's login rate limit")
        say("  LibreChat's login rate limit: waiting five minutes")
        page.wait_for_timeout(300_000)
    save_state(page, user)


def new_chat(page: Page):
    page.goto(f"{CHAT}/c/new")
    page.get_by_test_id("text-input").wait_for(timeout=60_000)
    page.wait_for_timeout(4000)  # the greeting types itself


def ask(page: Page, question: str, wait_answer: bool = True):
    page.get_by_test_id("text-input").fill(question)
    page.keyboard.press("Enter")
    page.get_by_test_id("stop-generation-button").wait_for(timeout=30_000)
    if wait_answer:
        page.get_by_test_id("stop-generation-button").wait_for(state="detached", timeout=ANSWER_TIMEOUT)
        page.wait_for_timeout(1500)


def open_mcp_panel(page: Page, state: str):
    """The MCP Settings panel; waits until the dolibarr server shows the state (Needs Auth, Connected)."""
    page.get_by_test_id("nav-panel-mcp-builder").click()
    page.locator(f"[aria-label='Dolibarr - {state}']").wait_for(timeout=60_000)
    page.wait_for_timeout(1000)


# --- Dolibarr and restoauth --------------------------------------------------------------------------

def oauth_tab(page: Page, click, name: str | None, allow: bool = True):
    """Clicks what opens the OAuth tab, logs into Dolibarr through Keycloak (Use OpenID to login; the
    Keycloak session of the chat login is reused) and lands on restoauth's consent page. Takes the
    screenshot <name> of it, then clicks Allow (the tab closes itself) or leaves the tab open."""
    with page.context.expect_page(timeout=60_000) as info:
        click()
    tab = info.value
    tab.get_by_text("Use OpenID to login").click(timeout=60_000)
    tab.get_by_text("Allow access?").first.wait_for(timeout=60_000)
    if name:
        shot(tab, name)
    if allow:
        tab.get_by_role("button", name="Allow").click()
        # From the MCP Settings panel the tab closes itself; from the Sign-in button in a chat it
        # ends on a LibreChat page instead, which a user would close.
        for _ in range(60):
            if tab.is_closed() or (tab.url.startswith(CHAT) and "/oauth/" not in tab.url):
                break
            page.wait_for_timeout(1000)
        else:
            raise AssertionError(f"OAuth tab did not return to LibreChat: {tab.url}")
        if not tab.is_closed():
            tab.close()
    return tab


# --- Parts -------------------------------------------------------------------------------------------

def part_anna(browser):
    """anna: chat login, connecting the Dolibarr assistant, questions, ending the connection in Dolibarr."""
    ctx = new_context(browser, "anna")
    page = ctx.new_page()
    chat_login(page, "anna", shots=True)
    page.wait_for_timeout(4000)
    shot(page, "user-guide/03-librechat-home")

    open_mcp_panel(page, "Needs Auth")
    shot(page, "quick-start/04-librechat-mcp-servers")
    page.get_by_role("button", name="Connect").click()
    cont = page.get_by_role("button", name="Continue with OAuth")
    cont.wait_for(timeout=30_000)
    shot(page, "quick-start/05-librechat-connect-dialog")
    oauth_tab(page, cont.click, "quick-start/06-restoauth-consent")
    page.locator("[aria-label='Dolibarr - Connected']").wait_for(timeout=60_000)
    shot(page, "quick-start/07-librechat-connected")

    new_chat(page)
    ask(page, "Use the whoami tool: who am I in Dolibarr?")
    shot(page, "quick-start/08-librechat-whoami")

    new_chat(page)
    page.get_by_test_id("model-selector-button").click()
    page.wait_for_timeout(1000)
    shot(page, "user-guide/04-model-menu")
    page.keyboard.press("Escape")
    page.get_by_test_id("composer-palette-button").click()
    page.get_by_placeholder("Search tools, skills and servers").fill("Dolibarr")
    page.wait_for_timeout(1000)
    shot(page, "user-guide/05-plus-menu-mcp-servers")
    page.keyboard.press("Escape")

    for name, question in [
        ("06-customers", "Which customers can I see in Dolibarr?"),
        ("07-unpaid-invoices", "Which invoices are unpaid? Answer with a short table."),
        ("08-products", "Which products and services do we sell?"),
        ("09-read-only", "Mark the unpaid invoice of North Customer Ltd as paid."),
    ]:
        new_chat(page)
        ask(page, question)
        shot(page, f"user-guide/{name}")
    save_state(page, "anna")

    # Dolibarr: the own user card, tab Connected applications, end the connection
    erp = ctx.new_page()
    erp.goto(f"{DOLIBARR}/")
    card = erp.locator("a[href*='/user/card.php?id=']").first
    openid = erp.get_by_text("Use OpenID to login")
    openid.or_(card).first.wait_for(state="attached", timeout=60_000)
    if openid.count():  # no Dolibarr session left from the OAuth tab
        openid.click()
    card.wait_for(state="attached", timeout=60_000)
    erp.goto(DOLIBARR + card.get_attribute("href"))
    erp.get_by_role("link", name="Connected applications").first.click()
    end = erp.get_by_text("End connection").first
    end.wait_for(timeout=30_000)
    shot(erp, "user-guide/11-dolibarr-connected-applications")
    end.click()
    erp.get_by_text("Connection ended").first.wait_for(timeout=30_000)
    shot(erp, "user-guide/12-connection-ended")
    ctx.close()


def part_carl(browser):
    """carl: a question before connecting (Sign-in in the chat), then a question without the invoice right."""
    ctx = new_context(browser, "carl")
    page = ctx.new_page()
    chat_login(page, "carl")
    new_chat(page)
    ask(page, "Which customers can I see in Dolibarr?", wait_answer=False)
    signin = page.get_by_role("button", name=re.compile("Sign-in to"))
    signin.wait_for(timeout=60_000)
    page.wait_for_timeout(2000)
    shot(page, "quick-start/09-librechat-sign-in-in-chat")
    oauth_tab(page, signin.click, None)
    page.get_by_test_id("stop-generation-button").wait_for(state="detached", timeout=ANSWER_TIMEOUT)

    new_chat(page)
    ask(page, "Which invoices are unpaid?")
    shot(page, "user-guide/10-no-invoice-right")
    save_state(page, "carl")
    ctx.close()


def part_bob(browser):
    """bob has no connect right: the consent page offers only Deny."""
    ctx = new_context(browser, "bob")
    page = ctx.new_page()
    chat_login(page, "bob")
    open_mcp_panel(page, "Needs Auth")
    page.get_by_role("button", name="Connect").click()
    cont = page.get_by_role("button", name="Continue with OAuth")
    cont.wait_for(timeout=30_000)
    oauth_tab(page, cont.click, "user-guide/13-consent-without-right", allow=False)
    save_state(page, "bob")
    ctx.close()


def part_admin(browser):
    """Dolibarr as administrator: login page, restoauth setup page, registered clients, the connect right.
    The setup page's tables are wider than 1280 pixels, so these screenshots are 1440 pixels wide."""
    ctx = new_context(browser, width=1440)
    page = ctx.new_page()
    page.goto(f"{DOLIBARR}/")
    expect(page.get_by_text("Use OpenID to login")).to_be_visible()
    shot(page, "quick-start/03-dolibarr-login-openid")

    page.fill("#username", DOLIBARR_ADMIN[0])
    page.fill("#password", DOLIBARR_ADMIN[1])
    page.click("input[type=submit], button[type=submit]")
    page.wait_for_load_state("networkidle")
    page.goto(f"{DOLIBARR}/custom/restoauth/admin/setup.php")
    scroll_to(page, page.get_by_text("Maximum connection age").first)
    shot(page, "quick-start/01-restoauth-setup")
    scroll_to(page, page.get_by_text("Registered clients").first)
    shot(page, "quick-start/10-restoauth-registered-clients")

    # anna's Permissions tab, at the REST OAuth module
    page.goto(f"{DOLIBARR}/user/list.php?search_login=anna")
    page.locator("a[href*='/user/card.php?id=']", has_text="anna").first.click()
    page.get_by_role("link", name="Permissions").first.click()
    scroll_to(page, page.get_by_text("Connect applications (AI assistant)").first, offset=300)
    shot(page, "quick-start/02-dolibarr-connect-right")
    ctx.close()


# Order matters: anna and carl connect before the admin screenshot of the registered clients.
PARTS = {"anna": part_anna, "carl": part_carl, "bob": part_bob, "admin": part_admin}


def main(names: list[str]):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in names or list(PARTS):
            say(f"== {name}")
            try:
                PARTS[name](browser)
            except Exception:
                for i, ctx in enumerate(browser.contexts):
                    for j, pg in enumerate(ctx.pages):
                        dump(pg, f"failed-{name}-{i}-{j}")
                raise
        browser.close()
    say("screenshots complete")


if __name__ == "__main__":
    main(sys.argv[1:])
