# Changelog

All notable changes to the Dolibarr MCP server are listed here. Versions follow
[Semantic Versioning](https://semver.org/); each release is a git tag `vX.Y.Z`, and operators build
the image from that tag with `docker compose up -d --build` (see the README's Install and Update
chapters).

## Unreleased

- Example setup (Keycloak and LibreChat), security-relevant for operators: a LibreChat logout now ends
  the user's Dolibarr session in the browser too. Before, Dolibarr stayed logged in as the previous
  user, so the next person who logged into LibreChat in the same browser and connected Dolibarr was
  shown restoauth's consent page for the previous user's account, and their LibreChat received that
  user's token. Existing installations that follow the example setup should change two things:
  - In Keycloak, on the `dolibarr` client, turn on **Front channel logout** and set the
    **Front-channel logout URL** to `https://erp.example.com/user/logout.php?noredirect=1` (your
    Dolibarr address). Backchannel logout stays empty.
  - In LibreChat's `.env`, keep `OPENID_USE_END_SESSION_ENDPOINT=true` and
    `OPENID_POST_LOGOUT_REDIRECT_URI` set to your LibreChat login page, listed under **Valid post
    logout redirect URIs** of the `librechat` client; without them LibreChat never sends the browser
    to Keycloak's logout.
- Limits: the front-channel logout works only when the browser sends Dolibarr's session cookie in
  Keycloak's logout iframe (Dolibarr and Keycloak on the same site), and not for a Dolibarr session
  opened with Dolibarr's own login form; there, log out of Dolibarr by hand or use separate browser
  profiles. After Dolibarr's own **Logout**, the next Keycloak login within an hour ends logged out
  once. See `docs/setup/example-keycloak-librechat.md`.
- The MCP server itself is unchanged.
- The test stack and documentation now use restoauth 0.3.1 (release ZIP sha256 `71039e30a823bebe7a9c621da7bd5c241109e758e9b11fdc49dd32897bd1af7d`). Tested with restoauth 0.3.1.

## 0.1.1 - 2026-11-24

- The MCP server now accepts only restoauth access tokens. A user's plain Dolibarr API key
  (`DOLAPIKEY`) sent as a bearer token is refused with `401` and the usual `WWW-Authenticate`
  challenge, and is never forwarded to Dolibarr for a tool call. `restoauth/me` answers for such a
  key too, but with `"token": null`; 0.1.0 accepted it. The key keeps working at Dolibarr's REST API
  directly, so other `DOLAPIKEY` integrations are not affected.
- The refusal is written to the audit log (`"tool": null`,
  `"info": "refused: not a restoauth access token"`, the key's short hash, never the key) and to the
  application log (`Token rejected (...): not a restoauth access token`).
- No new or changed settings. Tested with restoauth 0.2.2 on Dolibarr 23.

## 0.1.0 - 2026-11-24

- First release: the read-only tools `whoami`, `my_permissions`, `list_thirdparties`,
  `get_thirdparty`, `list_invoices`, `get_invoice`, `list_proposals`, `list_orders`, `list_products`,
  `list_api_endpoints` and `api_get`, with the caller's own restoauth token, per-user tool list,
  rights checks, row cap, input checks, audit log, public host behind a reverse proxy and internal CA
  support.
