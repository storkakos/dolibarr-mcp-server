# Dolibarr MCP server

An MCP server for Dolibarr 23: read-only tools, and every call runs with the caller's own Dolibarr token. Dolibarr itself is the authorization server, through the [restoauth](https://github.com/storkakos/dolibarr-restoauth) module (GPL-3.0-or-later, separate repo).

Work in progress: install, configuration and operations chapters follow before the first release.

## Configuration

Every setting comes from environment variables, documented in [.env.example](.env.example). `DOLIBARR_URL`, `DOLIBARR_OAUTH_ISSUER` and `MCP_RESOURCE_URL` are required and have no defaults. A missing or malformed value stops startup with a message that names the setting.

## Tools

All tools only read. Every call runs with the caller's own Dolibarr token and rights.

| Tool | Reads | Needs |
|---|---|---|
| `whoami`, `my_permissions` | the signed-in user, rights and active modules (`restoauth/me`) | a valid token |
| `list_thirdparties`, `get_thirdparty` | third parties | `societe.lire` |
| `list_invoices`, `get_invoice` | customer invoices | `facture.lire` |
| `list_proposals` | proposals | `propal.lire` |
| `list_orders` | customer orders | `commande.lire` |
| `list_products` | products and services | `produit.lire` |
| `list_api_endpoints` | readable REST paths of all active API classes (`restoauth/endpoints`), filtered by the user's rights | a valid token |
| `api_get` | one GET on a path `list_api_endpoints` lists | the path's rights |

The rights a path needs come from restoauth's rights map (delivered with `restoauth/me`). The server adds its own, stricter rules where Dolibarr is too lax: `GET /thirdparties/{id}/outstandinginvoices` and the two `getinvoicesqualifiedfor...` paths show invoice data, so they need `facture.lire` as well as `societe.lire`. The tool list only offers tools the user has the rights for, and a call without the right is refused before it reaches Dolibarr.

Input is checked before anything is sent: record IDs are whole numbers from 1 to 2147483647, search texts have at most 100 characters and no control characters (quotes, parentheses and other characters that could leave the SQL filter are removed), and `api_get` takes only an absolute path whose segments are letters, digits, `_`, `-` and `.` (no `.`/`..` segments, no query string, no placeholders), plus at most 20 query parameters. Query parameters that carry credentials (`DOLAPIKEY`, `api_key`, `token`, ...) are refused.

Every list asks Dolibarr for at most `MCP_MAX_ROWS` rows (default 50). If an endpoint ignores the limit, the answer is cut to `MCP_MAX_ROWS` rows and says so.

## Audit log

Every tool call appends exactly one JSON line to `MCP_AUDIT_LOG`: also calls the server refuses (invalid input, missing right, arguments that do not fit the tool), calls where Dolibarr fails, and calls that are cancelled while they run.

```json
{"ts": "2026-11-23T09:14:02", "user": "jdoe", "token": "3f9a1c0e7b2d", "tool": "list_invoices", "args": {"status": "unpaid"}, "ok": true, "info": ""}
```

| Field | Meaning |
|---|---|
| `ts` | Time of the call in the server's time zone |
| `user` | Dolibarr login the token belongs to (from `restoauth/me`); `?` if it cannot be looked up |
| `token` | Short, non-reversible hash of the token, to tell sessions apart. Never the token itself. |
| `tool` | Tool name |
| `args` | Arguments as the client sent them; the caller's token, long token-like strings and values after secret-looking names (`password=`, `Bearer`, `DOLAPIKEY=`, ...) are masked as `***` |
| `ok` | `true` only if the call was not refused and every Dolibarr request of the call succeeded |
| `info` | Empty when `ok` is `true`. Otherwise `refused: ...` (invalid input or missing right; Dolibarr was not asked for data), Dolibarr's error (`Dolibarr HTTP 500 ...`, `No permission in Dolibarr (HTTP 403)`, `Dolibarr not reachable: ...`), the SDK's error for unfitting arguments, or `cancelled`. Shortened and masked like `args`. |

The server only appends; rotate the file with logrotate (`copytruncate`). The application log contains no tokens either: the HTTP client's request log (which would show query strings) is switched off, and error messages are masked like the audit log.

## Development

The unit tests drive the MCP server over real HTTP with a fake Dolibarr behind it (`tests/fake_dolibarr.py`). They need no Docker:

```sh
python -m venv .venv
.venv/Scripts/python -m pip install --no-deps -r requirements.lock -r requirements-build.lock   # .venv/bin/python on Linux
.venv/Scripts/python -m pip install --no-deps --no-build-isolation -e .
.venv/Scripts/python -m pip install pytest==8.4.2
.venv/Scripts/python -m pip install "pywin32>=310"   # Windows only: the MCP SDK needs it there, the Linux lock file does not list it
.venv/Scripts/python -m pytest -q
```

## Licence

MIT, see [LICENSE](LICENSE).
