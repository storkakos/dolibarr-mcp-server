"""TEST ONLY. Keycloak through its admin REST API: realm `example`, client `dolibarr` for Dolibarr's
openid_connect login, and the test users.

Dolibarr matches the Keycloak user by `preferred_username` (MAIN_AUTHENTICATION_OIDC_LOGIN_CLAIM), so
users must not change their username and nobody may register themselves.
"""
from common import DOLIBARR, KC_SECRET_DOLIBARR, KC_USERS, REALM, SSO, kc_admin, say


def _ok(r):
    if r.status_code >= 400:
        raise SystemExit(f"{r.request.method} {r.url}: {r.status_code} {r.text[:300]}")
    return r


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
            _ok(s.put(f"{R}/clients/{found[0]['id']}", json=body))
        else:
            _ok(s.post(f"{R}/clients", json=body))
        say("   keycloak client", cid)

    # Dolibarr 23's openid_connect callback (core/lib/openid_connect.lib.php) and its login page after logout.
    client("dolibarr", "Dolibarr", DOLIBARR, f"{DOLIBARR}/core/modules/openid_connect/callback.php",
           f"{DOLIBARR}/index.php", KC_SECRET_DOLIBARR)

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
