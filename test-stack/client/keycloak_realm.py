"""TEST ONLY. Keycloak through its admin REST API: realm `example`, client `dolibarr` for Dolibarr's
openid_connect login, client `librechat` for the LibreChat login, and the test users.

Same values as the admin-console tables in docs/setup/example-keycloak-librechat.md. Differences for
the local test, each on purpose: the realm itself (the manual assumes it exists); fixed client
secrets (test values) instead of copying them from the Credentials tab.

The clients are merged, not replaced: a client that exists already keeps every setting this setup does
not own (attributes, other redirect and post-logout redirect URIs, web origins), so another stack's
setup or an admin's change on the same Keycloak survives a second run.

Dolibarr matches the Keycloak user by `preferred_username` (MAIN_AUTHENTICATION_OIDC_LOGIN_CLAIM), so
users must not change their username and nobody may register themselves.
"""
from common import CHAT, DOLIBARR, KC_SECRET_DOLIBARR, KC_SECRET_LIBRECHAT, KC_USERS, REALM, SSO, kc_admin, say

# Keycloak keeps the post-logout redirect URIs in one attribute, separated by "##".
LIST_ATTRIBUTES = {"post.logout.redirect.uris"}


def _ok(r):
    if r.status_code >= 400:
        raise SystemExit(f"{r.request.method} {r.url}: {r.status_code} {r.text[:300]}")
    return r


def _union(old: list, new: list) -> list:
    return [*old, *(x for x in new if x not in old)]


def merge_client(current: dict, own: dict) -> dict:
    """The existing client representation with this setup's settings put on top: own scalar fields and
    attributes win, URI lists are joined, anything else stays as it is."""
    merged = {**current, **{k: v for k, v in own.items() if k not in ("attributes", "redirectUris", "webOrigins")}}
    merged["redirectUris"] = _union(current.get("redirectUris") or [], own.get("redirectUris") or [])
    merged["webOrigins"] = _union(current.get("webOrigins") or [], own.get("webOrigins") or [])
    attrs = dict(current.get("attributes") or {})
    for k, v in (own.get("attributes") or {}).items():
        if k in LIST_ATTRIBUTES:
            attrs[k] = "##".join(_union([x for x in attrs.get(k, "").split("##") if x],
                                        [x for x in v.split("##") if x]))
        else:
            attrs[k] = v
    merged["attributes"] = attrs
    return merged


def setup_realm() -> None:
    s = kc_admin()
    A = f"{SSO}/admin/realms"
    if s.get(f"{A}/{REALM}").status_code == 404:
        _ok(s.post(A, json={"realm": REALM, "enabled": True}))
    R = f"{A}/{REALM}"

    def client(cid, name, root, redirect, post_logout, secret):
        body = {
            "clientId": cid, "name": name, "protocol": "openid-connect", "enabled": True,
            "publicClient": False, "clientAuthenticatorType": "client-secret", "secret": secret,
            "authorizationServicesEnabled": False, "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False, "implicitFlowEnabled": False, "serviceAccountsEnabled": False,
            "attributes": {"standard.token.exchange.enabled": "false",
                           "oauth2.device.authorization.grant.enabled": "false",
                           "oidc.ciba.grant.enabled": "false", "pkce.code.challenge.method": "",
                           "post.logout.redirect.uris": post_logout},
            "rootUrl": root, "baseUrl": root + "/", "redirectUris": [redirect], "webOrigins": [],
        }
        found = s.get(f"{R}/clients", params={"clientId": cid}).json()
        if found:
            current = _ok(s.get(f"{R}/clients/{found[0]['id']}")).json()
            _ok(s.put(f"{R}/clients/{found[0]['id']}", json=merge_client(current, body)))
        else:
            _ok(s.post(f"{R}/clients", json=body))
        say("   keycloak client", cid)

    # Dolibarr 23's openid_connect callback (core/lib/openid_connect.lib.php) and its login page after logout.
    # The post-logout URI ends in a wildcard: Dolibarr 23 appends "?client_id=..&returnTo=.." to the
    # configured logout URL, so the post_logout_redirect_uri Keycloak receives is index.php plus that text.
    client("dolibarr", "Dolibarr", DOLIBARR, f"{DOLIBARR}/core/modules/openid_connect/callback.php",
           f"{DOLIBARR}/index.php*", KC_SECRET_DOLIBARR)
    # LibreChat's OpenID login callback (OPENID_CALLBACK_URL in librechat/librechat.env) and its login page
    # after logout (OPENID_POST_LOGOUT_REDIRECT_URI). Without the latter, Keycloak answers LibreChat's
    # logout with "Invalid redirect uri" and keeps the session.
    client("librechat", "LibreChat", CHAT, f"{CHAT}/oauth/openid/callback", f"{CHAT}/login", KC_SECRET_LIBRECHAT)

    realm = _ok(s.get(R)).json()
    realm.update({"registrationAllowed": False, "editUsernameAllowed": False})
    _ok(s.put(R, json=realm))
    say("   keycloak realm: no self-registration, usernames fixed")

    for username, pw, first, last, mail in KC_USERS:
        if not s.get(f"{R}/users", params={"username": username, "exact": "true"}).json():
            _ok(s.post(f"{R}/users", json={
                "username": username, "firstName": first, "lastName": last, "email": mail,
                "emailVerified": True, "enabled": True,
                "credentials": [{"type": "password", "value": pw, "temporary": False}]}))
        say("   keycloak user", username)
