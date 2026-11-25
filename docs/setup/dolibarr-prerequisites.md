# Dolibarr prerequisites

**Required for every customer.** This manual prepares an existing Dolibarr so that it can act as the
**authorization server** for the MCP server: Dolibarr logs the user in, restoauth asks for consent
and issues the access token that the MCP client sends to the MCP server. The MCP server only
forwards that token to Dolibarr's REST API. It stores no user secrets and issues no tokens.

The MCP server needs only the [restoauth](https://github.com/storkakos/dolibarr-restoauth) module
and Dolibarr's own API REST module. Logging into Dolibarr through an **identity provider** (for
example Keycloak via `openid_connect`) is optional and described in
[the example setup](example-keycloak-librechat.md). Without an identity provider, users log in with
Dolibarr's own login form, and everything in this manual still works.

restoauth's [README](https://github.com/storkakos/dolibarr-restoauth#readme) describes every setting
of the module in detail. This manual covers what the MCP server needs, in the order to do it, and
ends with a check list against a running MCP server.

## Contents

1. [Example hostnames](#example-hostnames)
2. [Requirements](#requirements)
3. [Install restoauth](#install-restoauth)
4. [Configure Dolibarr](#configure-dolibarr)
5. [Discovery rewrite rule](#discovery-rewrite-rule)
6. [Which tokens the MCP server accepts](#which-tokens-the-mcp-server-accepts)
7. [Licences](#licences)
8. [Check list](#check-list)

## Example hostnames

All URLs use HTTPS behind the customer's reverse proxy. Replace them with yours everywhere in this
manual.

| Example | What it is | Replace with yours |
|---|---|---|
| `https://erp.example.com` | Dolibarr (`DOLIBARR_URL` of the MCP server) | |
| `https://erp.example.com/custom/restoauth` | Issuer of the authorization server (`DOLIBARR_OAUTH_ISSUER`, the module URL) | |
| `https://mcp.example.com/mcp` | Public URL of the MCP server (`MCP_RESOURCE_URL`) | |
| `https://chat.example.com/api/mcp/dolibarr/oauth/callback` | Callback of the MCP client (LibreChat in the example setup; another client shows its own) | |

## Requirements

| | |
|---|---|
| Dolibarr | **23**, already installed. restoauth refuses to install on older versions. Only Dolibarr 23 is tested and supported. |
| PHP | 8.1 or newer |
| Module folder | The alternative module root `custom` set up in `conf/conf.php` (`$dolibarr_main_url_root_alt='/custom'`), the Dolibarr default for external modules |
| HTTPS | Required for Dolibarr and the MCP server. OAuth over plain HTTP exposes every code and token. |
| Web server | Access to its configuration for one rewrite rule, see [Discovery rewrite rule](#discovery-rewrite-rule) |
| Cron | Dolibarr's scheduled jobs running, so that restoauth's cleanup job deletes expired codes and tokens |
| Users | With an identity provider: every user must already exist in Dolibarr, with the Dolibarr login equal to the Keycloak `preferred_username`. Dolibarr 23 does not create users on first login. |

### Tested with

| Component | Version | Validation run |
|---|---|---|
| Dolibarr | 23.0.4 (official `dolibarr/dolibarr` image, Apache with mod_php) | 2026-11-24 |
| restoauth | 0.3.0 | 2026-11-25 |
| Keycloak (only with an identity provider) | 26.8.2 | 2026-11-24 |
| LibreChat (MCP client of the example setup) | v0.8.9 | 2026-11-24 |

The validation run is the [test stack](../../test-stack/README.md) with all its end-to-end checks.
restoauth was developed against Dolibarr 23.0.3. Newer versions should work but are untested.

## Install restoauth

Download `module_restoauth-X.Y.Z.zip` from the
[restoauth releases](https://github.com/storkakos/dolibarr-restoauth/releases), then in Dolibarr go
to **Setup → Modules → Deploy/install external module**, upload the ZIP and install it. Dolibarr
unpacks it to `htdocs/custom/restoauth`. Details, installing from a checkout, and updating:
[restoauth README → Install](https://github.com/storkakos/dolibarr-restoauth#install).

## Configure Dolibarr

1. **Enable the modules.** Setup → Modules: enable **API REST** and **REST-OAuth (AI access)**.
2. **restoauth setup page** (Setup → Modules → REST-OAuth → gear icon):

   | Field | Value for the MCP server |
   |---|---|
   | Allowed redirect URIs | The MCP client's callback, exactly as the client sends it, e.g. `https://chat.example.com/api/mcp/dolibarr/oauth/callback`. Only clients whose redirect URIs are on this list can register. |
   | Allowed resources | **Exactly** the MCP server's `MCP_RESOURCE_URL`, e.g. `https://mcp.example.com/mcp` (a trailing slash is ignored). Never leave it empty in production: an empty list allows any resource. |
   | Allow loopback redirects | Off. Only for local tests. |
   | Issuer | Empty (the module URL is used). Set it only if Dolibarr is reached under another public URL. Whatever the setup page then shows as issuer is `DOLIBARR_OAUTH_ISSUER` of the MCP server. |
   | Lifetimes | The defaults (access token 1 hour, connection 30 days without use and 90 days at most) fit the MCP server. See [restoauth README → Lifetimes](https://github.com/storkakos/dolibarr-restoauth#lifetimes). |

3. **Grant the connect right.** Give the users or groups that should use the assistant the right
   **Connect applications (AI assistant) via OAuth with own rights** (REST-OAuth module). Users
   without it see no Allow button on the consent page. Administrators may always connect.
4. **Leave `API_IN_TOKEN_TABLE` off.** It is broken in Dolibarr 23.0.3 (every REST request fails
   with `503`); restoauth maps its tokens through a hook instead. The setup page shows an error box
   if it is on.
5. **Add the discovery rewrite rule** (next section).

### What the assistant can read

A restoauth token carries **all** rights of its user: Dolibarr has no scopes. The consent page lists
those rights. The MCP server only offers reading tools and filters them by the user's rights, but
the user's Dolibarr rights are the real limit. Give the connect right to accounts whose read access
you are comfortable exposing to an AI assistant, and think twice about administrators: an
administrator's token reads everything. If an administrator also needs the assistant, give them a
second, non-admin account.

Disabling a Dolibarr user ends all of that user's connections at once; the MCP server refuses the
token after at most `MCP_RIGHTS_CACHE_SECONDS`. Users see and end their own connections on their user
card, tab **Connected applications**.

## Discovery rewrite rule

MCP clients look for the authorization server's metadata at the **site root** with the issuer path
appended (RFC 8414): `https://erp.example.com/.well-known/oauth-authorization-server/custom/restoauth`.
Dolibarr cannot answer there itself, so the web server rewrites the path to restoauth's
`metadata.php`. Ready-to-paste rules for Apache and nginx, and what to change when Dolibarr does not
live at the web root:
[restoauth README → Rewrite rules for discovery](https://github.com/storkakos/dolibarr-restoauth#rewrite-rules-for-discovery).

The MCP server publishes its own protected resource metadata (RFC 9728); Dolibarr needs no rule for
it.

## Which tokens the MCP server accepts

The MCP server accepts **only restoauth access tokens**: bearer tokens for which `restoauth/me`
answers with a `token` object of type `restoauth`. It does **not** check which resource a token was
issued for: `restoauth/me` does not say. restoauth binds a token to an allowed resource when it
issues it (RFC 8707), so keep **Allowed resources** to the MCP server's URL.

A user's own Dolibarr API key (`DOLAPIKEY`) is **refused**, even though it still works at Dolibarr's
REST API directly. restoauth's hook passes keys that are not restoauth tokens through unchanged, so
that existing `DOLAPIKEY` integrations such as n8n keep working, and `restoauth/me` answers for such a
key as well, but with `"token": null`. The MCP server takes that as "not a restoauth token": the
request gets `401` with the usual `WWW-Authenticate` challenge, nothing is sent to Dolibarr's REST
API with the key, the application log says `Token rejected (...): not a restoauth access token`, and
the audit log gets a line with `"tool": null` and `"info": "refused: not a restoauth access token"`
(the key itself is never written, only its short hash). So the assistant is only used through a
connection the user consented to, can be ended on the user card, and expires.

(MCP server 0.1.0 accepted a plain API key as well. Since 0.1.1 it does not.)

## Licences

This repository does not contain or redistribute restoauth or Dolibarr.

| Component | Where it comes from | Licence |
|---|---|---|
| restoauth | [storkakos/dolibarr-restoauth](https://github.com/storkakos/dolibarr-restoauth) | GNU GPL-3.0-or-later |
| Dolibarr | [dolibarr.org](https://www.dolibarr.org) | GNU GPL-3.0-or-later |

## Check list

Run these after the MCP server is started with `DOLIBARR_URL=https://erp.example.com`,
`DOLIBARR_OAUTH_ISSUER=https://erp.example.com/custom/restoauth` and
`MCP_RESOURCE_URL=https://mcp.example.com/mcp`. Each check builds on the one before; fix a failing
check before you go on.

### 1. The authorization server metadata answers at the site root

```sh
curl -s https://erp.example.com/.well-known/oauth-authorization-server/custom/restoauth
```

**Expected:** JSON with `"issuer":"https://erp.example.com/custom/restoauth"` and the endpoints
`authorization_endpoint`, `token_endpoint` and `registration_endpoint`.

**If not:**

| Result | Fix |
|---|---|
| 404 | The rewrite rule is missing or not active. See [Discovery rewrite rule](#discovery-rewrite-rule), and check that `mod_rewrite` is loaded (Apache). |
| 404 also for `https://erp.example.com/custom/restoauth/metadata.php` | restoauth is not installed in `htdocs/custom/restoauth`, or the `custom` module root is not set up. |
| Dolibarr login page or HTML | The rewrite points to the wrong path. |
| `issuer` with `http://` or another host | Dolibarr does not see its public URL behind the reverse proxy. Set restoauth's **Issuer** on the setup page, or fix `$dolibarr_main_url_root`. |

### 2. restoauth's REST extension answers

```sh
curl -si https://erp.example.com/api/index.php/restoauth/me | head -n 1
```

**Expected:** `401` (no token sent). A `404` or `501` means API REST or restoauth is not enabled; a
`503` means `API_IN_TOKEN_TABLE` is on (turn it off).

### 3. The MCP server answers 401 and points to its metadata

```sh
curl -si -X POST https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

**Expected:** `HTTP/1.1 401` (or `HTTP/2 401` behind a proxy with HTTP/2) and a header like

```
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource/mcp"
```

**If not:**

| Result | Fix |
|---|---|
| 502/504 | The reverse proxy cannot reach the MCP server container. |
| 421 | The reverse proxy does not pass the public `Host` header. See the [README](../../README.md#reverse-proxy-tls). |
| `resource_metadata` with another host or `http://` | `MCP_RESOURCE_URL` is not the public URL. Set it to exactly the URL clients use. |

### 4. The protected resource metadata points at restoauth

Use the URL from `resource_metadata` in check 3:

```sh
curl -s https://mcp.example.com/.well-known/oauth-protected-resource/mcp
```

**Expected:** JSON with

```json
"resource": "https://mcp.example.com/mcp",
"authorization_servers": ["https://erp.example.com/custom/restoauth"]
```

`authorization_servers` must be the `issuer` from check 1, character by character.

**If not:**

| Result | Fix |
|---|---|
| 404 | The reverse proxy forwards only `/mcp`. It must also forward `/.well-known/oauth-protected-resource/mcp` to the MCP server. |
| `authorization_servers` differs from the `issuer` | `DOLIBARR_OAUTH_ISSUER` on the MCP server does not match restoauth's issuer. |

### 5. The resource URL matches in all three places

These three values must be identical (restoauth ignores a trailing slash):

| Where | Value |
|---|---|
| MCP server environment | `MCP_RESOURCE_URL` |
| Check 4 | `"resource"` |
| restoauth setup page | one line of **Allowed resources** |

**If they differ:** the OAuth flow starts, and restoauth sends the client back with
`invalid_target` ("Resource is not allowed"). Typical differences: `http` vs `https`, an explicit
`:443`, an internal host name instead of the public one.

### 6. An MCP client can connect

Add `https://mcp.example.com/mcp` to the MCP client and connect, as a user with the connect right.
The client sends the user to Dolibarr's login page, then to restoauth's consent page that names the
client and lists the user's rights. After **Allow**, the assistant's tools work, and the user card
shows the connection in the tab **Connected applications**.

| Symptom | Fix |
|---|---|
| The client cannot register (`invalid_redirect_uri`, "Redirect URI not allowed: ...") | Its callback is not in **Allowed redirect URIs**. The message names the URI it asked for. |
| `invalid_target`, "Resource is not allowed" | See check 5. |
| The consent page shows no Allow button | The user lacks the connect right. |
| The Keycloak login into Dolibarr fails | The user does not exist in Dolibarr, or the login differs from the Keycloak `preferred_username`. |
| Login and consent work, but every tool call gets `401`; `docker compose logs` shows `Token rejected` | Dolibarr refuses the token at the REST API: check 2, and that the user is enabled. |
| Connected, but tool calls fail with `421 Misdirected Request` | The reverse proxy does not pass the public `Host` header, or `MCP_RESOURCE_URL` names another host. |
| A tool the user expects is missing | The user lacks the Dolibarr right for it; `my_permissions` lists the rights. |
