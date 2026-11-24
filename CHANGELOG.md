# Changelog

All notable changes to the Dolibarr MCP server are listed here. Versions follow
[Semantic Versioning](https://semver.org/); each release is a git tag `vX.Y.Z`, and operators build
the image from that tag with `docker compose up -d --build` (see the README's Install and Update
chapters).

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
