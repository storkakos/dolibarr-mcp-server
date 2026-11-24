# Dolibarr MCP server

An MCP server for Dolibarr 23, built and run as a Docker container on your own machine. MCP clients
such as LibreChat use it to let users read third parties, invoices, proposals, orders and products
from Dolibarr through an AI assistant.

- **Read-only.** The tools only read from Dolibarr. There are no tools that create or change data.
- **Every call runs with the caller's own Dolibarr token.** Dolibarr, with the
  [restoauth](https://github.com/storkakos/dolibarr-restoauth) module, is the authorization server:
  it logs the user in (also through Keycloak via `openid_connect`), asks for consent and issues the
  token. The MCP server forwards that token to Dolibarr's REST API, so each user sees exactly what
  Dolibarr allows them to see. The server stores no user secrets and issues no tokens.
- **Plain HTTP on `127.0.0.1`.** Your existing reverse proxy terminates TLS in front of it.
- **Audit log** as JSON lines in a host folder. Tokens never appear in any log.

How the parts fit together, and the Dolibarr 23 details behind them:
[architecture](docs/architecture.md).

New here? The [**quick start for administrators**](docs/quick-start.md) walks through the whole
setup in order, with screenshots, and links to the detailed sections below. For the people who
use the assistant, there is a [**user guide**](docs/user-guide.md).

## Contents

1. [Prerequisites on the Dolibarr side](#prerequisites-on-the-dolibarr-side)
2. [Requirements on the Docker host](#requirements-on-the-docker-host)
3. [Install](#install)
4. [Configuration](#configuration)
5. [Reverse proxy (TLS)](#reverse-proxy-tls)
6. [Internal CA](#internal-ca)
7. [Update and rollback](#update-and-rollback)
8. [Audit log](#audit-log)
9. [Tools and the per-user token model](#tools-and-the-per-user-token-model)
10. [Troubleshooting](#troubleshooting)
11. [Licences](#licences)
12. [Development](#development)

## Prerequisites on the Dolibarr side

Prepare Dolibarr before you start the container:

- [**Dolibarr prerequisites**](docs/setup/dolibarr-prerequisites.md) (required for every customer):
  Dolibarr 23, the restoauth module, API REST, the redirect and resource allowlists, the connect
  right, the discovery rewrite rule, `API_IN_TOKEN_TABLE` left off, and a check list.
- [**Example setup: Keycloak and LibreChat**](docs/setup/example-keycloak-librechat.md) (optional):
  one way to log into Dolibarr through an identity provider and to connect an MCP client.
- [**Test stack**](test-stack/README.md) (test only, not for production): both manuals on one Docker
  host, set up automatically, with a command that runs their check lists.

One thing to get exactly right: restoauth's **Allowed resources** (on the module's setup page) must
contain `MCP_RESOURCE_URL` of this server (same scheme, host, port and path; restoauth ignores a
trailing slash). A mismatch does not show up as a server error. The OAuth flow starts, and restoauth
then sends the client back with `invalid_target` ("Resource is not allowed").

## Requirements on the Docker host

- Docker with the Compose plugin (`docker compose`)
- `git`
- Internet access to Docker Hub and PyPI while building (the image is built on your machine)
- A reverse proxy that terminates TLS (see [Reverse proxy](#reverse-proxy-tls))
- The container must reach Dolibarr over HTTPS

## Install

```sh
# 1. Get a released version
git clone https://github.com/storkakos/dolibarr-mcp-server.git
cd dolibarr-mcp-server
git checkout v0.1.1

# 2. Configure: set DOLIBARR_URL, DOLIBARR_OAUTH_ISSUER and MCP_RESOURCE_URL
cp .env.example .env
${EDITOR:-vi} .env

# 3. Prepare the log folder BEFORE the first start
mkdir -p logs && sudo chown 10001:10001 logs

# 4. Build and start
docker compose up -d --build

# 5. Check health
docker compose ps        # STATUS shows "(healthy)" after a few seconds
curl -si http://127.0.0.1:8131/mcp -X POST | head -n 1                   # HTTP/1.1 401 Unauthorized
curl -s http://127.0.0.1:8131/.well-known/oauth-protected-resource/mcp   # your resource URL and issuer
```

Step 3 matters: the container runs as UID 10001 and writes the audit log to `./logs`. If the folder
is missing, Docker creates it as root, and the container stops right after starting and restarts in
a loop (see [Troubleshooting](#troubleshooting)). If you set `MCP_LOG_DIR` to another folder,
prepare that one instead.

The metadata path in step 5 is `/.well-known/oauth-protected-resource` followed by the path of
`MCP_RESOURCE_URL` (here `/mcp`). Then put the reverse proxy in front and run the
[check list](docs/setup/dolibarr-prerequisites.md#check-list) against the public URL.

## Configuration

All settings live in `.env` next to `compose.yaml`. [`.env.example`](.env.example) lists each one
with a comment. There are no defaults that point at a particular Dolibarr: the container refuses to
start when a required value is missing or invalid, and `docker compose logs` names the variable.

**Server settings** (passed into the container):

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `DOLIBARR_URL` | yes | | Base URL of your Dolibarr, without a trailing slash, e.g. `https://erp.example.com`. The server calls the REST API under `<DOLIBARR_URL>/api/index.php`. |
| `DOLIBARR_OAUTH_ISSUER` | yes | | Issuer of restoauth, exactly as its setup page shows it; with the default layout `<DOLIBARR_URL>/custom/restoauth`. The protected resource metadata points MCP clients here. |
| `MCP_RESOURCE_URL` | yes | | Public URL of this server as MCP clients reach it through the reverse proxy, e.g. `https://mcp.example.com/mcp`. Must be in restoauth's **Allowed resources**. |
| `MCP_MAX_ROWS` | no | `50` | Maximum number of rows a single tool call fetches from Dolibarr (1 to 10000) |
| `MCP_RIGHTS_CACHE_SECONDS` | no | `30` | How long the result of `restoauth/me` (user, rights, token expiry) is kept per token (0 to 3600; 0 asks Dolibarr on every call). A revoked token or a changed right takes effect after at most this long. |
| `SSL_CERT_FILE` | no | | CA bundle inside the container for an internal CA, see [Internal CA](#internal-ca) |

**Docker compose settings** (read by `docker compose` itself, only from `.env` or the shell):

| Variable | Default | Meaning |
|---|---|---|
| `MCP_PUBLISH_PORT` | `8131` | Host port, published on `127.0.0.1` only. Point your reverse proxy at it. |
| `MCP_LOG_DIR` | `./logs` | Host folder for the audit log. Must be writable by UID 10001. |

**Inside the container** (normally leave alone):

| Variable | Default | Meaning |
|---|---|---|
| `MCP_AUDIT_LOG` | `/data/logs/mcp-dolibarr-audit.log` | Audit log path inside the container. Keep it in `/data/logs`: anywhere else is read-only and the server refuses to start, except `/tmp`, which is writable but lost when the container is recreated. |
| `MCP_HOST`, `MCP_PORT` | `0.0.0.0`, `8131` | Fixed by `compose.yaml`; setting them in `.env` has no effect. |

After changing `.env`, apply it with `docker compose up -d`.

## Reverse proxy (TLS)

The container speaks plain HTTP on `127.0.0.1:8131` (or `MCP_PUBLISH_PORT`). Your reverse proxy
terminates TLS on the public host name from `MCP_RESOURCE_URL` and forwards to that port. It must:

- forward both `/mcp` and `/.well-known/oauth-protected-resource/mcp` (MCP clients fetch the
  metadata there); forwarding the whole host is simplest
- pass the original `Host` header through (nginx: `proxy_set_header Host $host;`, Apache:
  `ProxyPreserveHost On`; Caddy and Traefik do this by default). The server only accepts the host
  (and port) of `MCP_RESOURCE_URL` and loopback (for the container healthcheck). A request with any
  other host gets `421 Misdirected Request`. Likewise, an `Origin` header (sent by browser-based
  clients) must be the origin of `MCP_RESOURCE_URL` or loopback, otherwise the request gets
  `403 Forbidden` (DNS-rebinding protection). This check comes first, on every path including the
  `.well-known` metadata, and before the bearer token is looked at: a refused request gets `421` or
  `403` with or without a token (never a `401` challenge), and nothing is sent to Dolibarr for it.
- pass the `Authorization` header through unchanged

Host and origin are compared in normal form, on the configured and on the incoming side: letter case
does not matter, the trailing dot of a fully qualified name is ignored (`mcp.example.com.` is
`mcp.example.com`), and IPv6 literals are compared in compressed form (`[2001:db8:0::5]` is
`[2001:db8::5]`). The default port (`443` for `https`, `80` for `http`) may be present or left out,
both in the `Host` header and in `MCP_RESOURCE_URL`. A non-default port, as in
`https://mcp.example.com:8443/mcp`, must be in the `Host` header (`mcp.example.com:8443`). An IPv4
address must be written as a dotted quad (`192.0.2.10`); other spellings that the URL standard and
many resolvers also read as IPv4 (`192.0.522`, `0xc0.0.2.10`, `0300.0.2.10`, `3221225994`) are
refused rather than normalised: in `MCP_RESOURCE_URL` they stop startup with a message naming the
setting, in an incoming `Host` header they get `421` and in an `Origin` header `403`. The advertised
URL stays exactly as written in `MCP_RESOURCE_URL`.

nginx (tested: the test stack's [nginx variant](test-stack/README.md#nginx-variant) builds its
configuration from this block and the one under [path prefix](#resource-url-with-a-path-prefix)):

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name mcp.example.com;

    ssl_certificate     /etc/ssl/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/ssl/mcp.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8131;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;   # each Dolibarr request may take up to 60 s; raise this if Dolibarr is slow
    }
}
```

Apache (`mod_proxy`, `mod_proxy_http`, `mod_ssl`):

```apache
<VirtualHost *:443>
    ServerName mcp.example.com
    SSLEngine on
    SSLCertificateFile    /etc/ssl/mcp.example.com/fullchain.pem
    SSLCertificateKeyFile /etc/ssl/mcp.example.com/privkey.pem

    ProxyPreserveHost On
    ProxyTimeout 120
    ProxyPass        / http://127.0.0.1:8131/
    ProxyPassReverse / http://127.0.0.1:8131/
</VirtualHost>
```

### Resource URL with a path prefix

If the server shares a host with other services and lives under a path, e.g.
`MCP_RESOURCE_URL=https://apps.example.com/dolibarr/mcp`, the two paths behave differently:

| Public path | Forward to | Why |
|---|---|---|
| `/dolibarr/mcp` | `/mcp` (**strip** the prefix) | The server always serves the MCP endpoint at `/mcp`. |
| `/.well-known/oauth-protected-resource/dolibarr/mcp` | the same path (**keep** it) | The server serves its metadata at `/.well-known/oauth-protected-resource` plus the full path of `MCP_RESOURCE_URL`, and the `401` challenge points there. |

nginx, inside the `server` block of `apps.example.com`:

```nginx
location = /dolibarr/mcp {
    proxy_pass http://127.0.0.1:8131/mcp;
    proxy_set_header Host $host;
    proxy_read_timeout 120s;
}
location = /.well-known/oauth-protected-resource/dolibarr/mcp {
    proxy_pass http://127.0.0.1:8131;   # no URI part: the path is passed on unchanged
    proxy_set_header Host $host;
}
```

restoauth's **Allowed resources** then contains `https://apps.example.com/dolibarr/mcp`.

If the proxy runs on another machine, it cannot reach `127.0.0.1` on the Docker host. In that case
publish the port on an internal interface in a `compose.override.yaml` and restrict access to the
proxy with your firewall; never expose the plain HTTP port to the network at large.

## Internal CA

If Dolibarr's HTTPS certificate is issued by your own certificate authority, mount the CA bundle
(PEM) read-only and point `SSL_CERT_FILE` at it. Certificate verification is never turned off.

1. Put the bundle on the host, e.g. `certs/internal-ca.pem`, readable by UID 10001
   (`chmod 644 certs/internal-ca.pem`).
2. Create `compose.override.yaml` next to `compose.yaml` (so `compose.yaml` stays unchanged for
   `git pull`; compose reads the override automatically):

   ```yaml
   services:
     dolibarr-mcp-server:
       volumes:
         - ./certs/internal-ca.pem:/etc/dolibarr-mcp/ca.pem:ro
   ```

3. In `.env`: `SSL_CERT_FILE=/etc/dolibarr-mcp/ca.pem`
4. `docker compose up -d`

The bundle **replaces** the built-in list of public CAs. It must contain the CA that issued
Dolibarr's certificate (the root, plus intermediates if Dolibarr does not send them). A missing,
unreadable or empty bundle stops startup with a message that names `SSL_CERT_FILE`. With a bundle
that does not contain the right CA, the server starts, but every request gets `401` and
`docker compose logs` shows `Dolibarr not reachable: ConnectError`.

## Update and rollback

Releases are git tags `vX.Y.Z`. The image is tagged with the same version
(`dolibarr-mcp-server:X.Y.Z`), so `docker image ls dolibarr-mcp-server` shows which versions are
built on the host.

Update to a new release:

```sh
git fetch --tags
git checkout v0.2.0          # the new tag
docker compose up -d --build
docker compose ps            # wait for "(healthy)"
```

If you follow a branch instead of tags, `git pull` followed by `docker compose up -d --build` does
the same.

Roll back to the previous release:

```sh
git checkout v0.1.0          # the previous tag
docker compose up -d --build
```

The server keeps no state, so nothing needs migrating either way. `.env`, `compose.override.yaml`,
`logs/` and `certs/` are not tracked by git and stay as they are. Read the release notes of the new
version ([CHANGELOG.md](CHANGELOG.md)) for new or changed settings in `.env.example`, and for the restoauth version it was tested
with. restoauth is updated separately, inside Dolibarr, from its release ZIP (see its
[README](https://github.com/storkakos/dolibarr-restoauth#install)).

## Audit log

Every tool call appends exactly one JSON line to `logs/mcp-dolibarr-audit.log` on the host
(`MCP_LOG_DIR`): also calls the server refuses (invalid input, missing right, arguments that do not
fit the tool), calls where Dolibarr is unreachable or answers with an error, and calls that are
cancelled while they run. This covers the generic `api_get` tool as well. A bearer that Dolibarr knows
but that is not a restoauth access token (a user's plain API key) also gets a line, with `"tool": null`,
although the request ends with `401` before any tool runs. The file survives container recreation and
updates.

```json
{"ts": "2026-11-23T09:14:02", "user": "jdoe", "token": "3f9a1c0e7b2d", "tool": "list_invoices", "args": {"status": "unpaid"}, "ok": true, "info": ""}
```

| Field | Meaning |
|---|---|
| `ts` | Time of the call in the container's time zone (UTC unless you set `TZ`) |
| `user` | Dolibarr login the token belongs to (from `restoauth/me`); `?` if it cannot be looked up |
| `token` | Short, non-reversible hash of the token, to tell sessions apart. Never the token itself. |
| `tool` | Tool name; `null` for a refused bearer that is not a restoauth access token |
| `args` | Arguments as the client sent them; the caller's token, long token-like strings and values after secret-looking names (`password=`, `Bearer`, `DOLAPIKEY=`, ...) are masked as `***` |
| `ok` | `true` only if the call was not refused and **every** Dolibarr request of the call succeeded |
| `info` | Empty when `ok` is `true`. Otherwise `refused: ...` (invalid input, missing right, or `refused: not a restoauth access token`; Dolibarr was not asked for data), Dolibarr's error (`Dolibarr HTTP 500 ...`, `No permission in Dolibarr (HTTP 403)`, `Dolibarr not reachable: ...`), the SDK's error for unfitting arguments, or `cancelled`. Shortened and masked like `args`. |

**Rotation is your job.** The server only appends and never rotates or deletes the file. Use
logrotate with `copytruncate`, and keep the files as long as your audit rules require.

The application log (startup, rejected tokens, errors) goes to stdout:
`docker compose logs dolibarr-mcp-server`. It contains no tokens either, only the same short hash:
the HTTP client's request log (which would show query strings) is switched off, and error messages
are masked like the audit log.

## Tools and the per-user token model

The MCP client fetches a token for the user from restoauth (OAuth 2.1 with PKCE, through Dolibarr's
login and restoauth's consent page) and sends it as `Authorization: Bearer ...` with every request.
The server checks the token by calling `restoauth/me` with it, keeps the answer (user, rights,
active modules, token expiry) for at most `MCP_RIGHTS_CACHE_SECONDS` and never past the token's
expiry, and then calls Dolibarr's REST API with the same token. A request without a valid token gets
`401` with a `WWW-Authenticate` header that points the client to the
[protected resource metadata](https://www.rfc-editor.org/rfc/rfc9728) and from there to restoauth.
An expired, revoked or refreshed-away token, or the token of a user who was disabled in Dolibarr, is
refused as soon as Dolibarr refuses it and the cached answer has run out.

Only restoauth access tokens are accepted. A user's own Dolibarr API key (`DOLAPIKEY`) sent as a
bearer token gets the same `401` challenge and is never forwarded to Dolibarr for a tool call, although
it keeps working at Dolibarr's REST API directly for other integrations. See
[Which tokens the MCP server accepts](docs/setup/dolibarr-prerequisites.md#which-tokens-the-mcp-server-accepts).

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

The rights a path needs come from restoauth's rights map (delivered with `restoauth/me`). The server
adds its own, stricter rules where Dolibarr is too lax: `GET /thirdparties/{id}/outstandinginvoices`
and the two `getinvoicesqualifiedfor...` paths show invoice data, so they need `facture.lire` as well
as `societe.lire`. The tool list only offers tools the user has the rights for, and a call without
the right is refused before it reaches Dolibarr. Dolibarr checks every call itself as well.

Input is checked before anything is sent: record IDs are whole numbers from 1 to 2147483647, search
texts have at most 100 characters and no control characters (quotes, parentheses and other
characters that could leave the SQL filter are removed), and `api_get` takes only an absolute path
whose segments are letters, digits, `_`, `-` and `.` (no `.`/`..` segments, no query string, no
placeholders), plus at most 20 query parameters. Query parameters that carry credentials
(`DOLAPIKEY`, `api_key`, `token`, ...) are refused.

Every list asks Dolibarr for at most `MCP_MAX_ROWS` rows. If an endpoint ignores the limit, the
answer is cut to `MCP_MAX_ROWS` rows and says so.

## Troubleshooting

**The container restarts in a loop, `docker compose ps` never shows "healthy".** Look at
`docker compose logs dolibarr-mcp-server`. The line `Dolibarr MCP server on ...` is logged *before*
the audit log check and does **not** mean a successful start; look at the lines after it.

| Message | Cause and fix |
|---|---|
| `Configuration error: audit log ... is not writable (MCP_AUDIT_LOG, ...)` | With the default configuration: the host folder `./logs` (`MCP_LOG_DIR`) is not owned by UID 10001, usually because Docker created it as root. Fix: `sudo chown 10001:10001 logs`, then `docker compose up -d`, and check the log again. If you set `MCP_AUDIT_LOG`, it must point into `/data/logs`. |
| `Configuration error: DOLIBARR_URL is not set (required, see .env.example)` (or `DOLIBARR_OAUTH_ISSUER`, `MCP_RESOURCE_URL`) | The required value is missing in `.env`, or `.env` is not next to `compose.yaml`. |
| `Configuration error: MCP_RESOURCE_URL must be an http(s) URL with a host, ...` | Use the full public URL, e.g. `https://mcp.example.com/mcp`. The same message exists for `DOLIBARR_URL` and `DOLIBARR_OAUTH_ISSUER`. |
| `Configuration error: SSL_CERT_FILE ...` | The CA bundle is missing, unreadable for UID 10001, or contains no PEM certificate. See [Internal CA](#internal-ca). |

**Every request gets `401`, even with a token.** `docker compose logs` shows why the token check
failed: `Token rejected (...): HTTP 401` means Dolibarr refused the token (expired, revoked, ended on
the user card, or the user is disabled); `not a restoauth access token` means the client sent a
plain Dolibarr API key instead of a token from restoauth (connect through the MCP client's OAuth flow
instead); `HTTP 503` on every token usually means `API_IN_TOKEN_TABLE`
is switched on in Dolibarr 23 (turn it off, see the
[Dolibarr prerequisites](docs/setup/dolibarr-prerequisites.md)); any other status usually means
`DOLIBARR_URL` is wrong or API REST or restoauth is not enabled (check 1 and 2 of the
[check list](docs/setup/dolibarr-prerequisites.md#check-list)). `Dolibarr not reachable: ...` means the
container cannot reach Dolibarr (network, proxy, or certificate, see [Internal CA](#internal-ca)).

**`421 Misdirected Request` through the reverse proxy** (on every path, with or without a token). The
proxy does not pass the public `Host` header, or `MCP_RESOURCE_URL` names another host. See
[Reverse proxy](#reverse-proxy-tls).

**The MCP client cannot find the authorization server** (discovery fails, `404` on
`/.well-known/oauth-authorization-server/custom/restoauth`). The rewrite rule for the discovery path
is missing on Dolibarr's web server. See
[Dolibarr prerequisites → Discovery rewrite rule](docs/setup/dolibarr-prerequisites.md#discovery-rewrite-rule).

**The MCP client cannot register** (`invalid_redirect_uri`, "Redirect URI not allowed: ..."). The
client's callback is not in restoauth's **Allowed redirect URIs**. Add it exactly as the message
names it.

**The OAuth flow ends with `invalid_target` ("Resource is not allowed").** `MCP_RESOURCE_URL` is not
in restoauth's **Allowed resources**. See
[Prerequisites on the Dolibarr side](#prerequisites-on-the-dolibarr-side).

**The consent page shows no Allow button** ("Your user may not connect applications"). The user
lacks the restoauth right **Connect applications (AI assistant) via OAuth with own rights**. Grant it
to the user or one of their groups.

**The Keycloak login into Dolibarr fails for a new user.** Dolibarr 23 does not create users on
first login: the user must already exist in Dolibarr, with the login equal to the Keycloak
`preferred_username`.

**A tool is missing from the assistant, or a call says the right is missing.** The tool list follows
the user's Dolibarr rights; `my_permissions` shows them. After a right is granted, the change shows
up within `MCP_RIGHTS_CACHE_SECONDS`.

More checks with expected output: [check list](docs/setup/dolibarr-prerequisites.md#check-list).

## Licences

- This repository is licensed under the **MIT licence**, see [`LICENSE`](LICENSE). The licence file
  is installed into the image.
- **restoauth** is licensed under the **GNU GPL-3.0-or-later**, like Dolibarr itself. It is not part
  of this repository: it is a separate repo,
  [storkakos/dolibarr-restoauth](https://github.com/storkakos/dolibarr-restoauth), and runs inside
  your Dolibarr. The MCP server needs it on the Dolibarr side, but is a separate program that runs as
  its own process and talks to Dolibarr only over HTTP.
- **Dolibarr** is licensed under the GNU GPL-3.0-or-later by its authors.

## Development

Agent workflow, tickets and the test VM: see [AGENTS.md](AGENTS.md). Terms used in code and docs:
[GLOSSARY.md](GLOSSARY.md). Decisions: [docs/adr/](docs/adr/).

The unit tests drive the MCP server over real HTTP with a fake Dolibarr behind it
(`tests/fake_dolibarr.py`), like an MCP client. They need no Docker and no real Dolibarr, but
Python 3.13 on Linux (`requirements.lock` is resolved for Linux).

On the Windows dev machine, never run them locally: one command copies the working tree
(uncommitted changes included) to the test VM, runs pytest there in a throwaway container, shows the
result and cleans up. Run it from Git Bash; arguments go to pytest, the exit code is pytest's:

```sh
bash scripts/test-on-vm.sh
bash scripts/test-on-vm.sh tests/test_config.py -x
```

See [docs/agents/test-vm.md](docs/agents/test-vm.md) for the VM, run names and cleanup.

On a Linux machine, run them directly:

```sh
python -m venv .venv
.venv/bin/pip install --no-deps -r requirements.lock -r requirements-build.lock
.venv/bin/pip install --no-deps --no-build-isolation -e .
.venv/bin/pip install pytest==8.4.2
.venv/bin/pytest
```

The container smoke test needs a Docker host (on the Windows dev machine: the test VM). It builds the
image, starts it next to a fake Dolibarr on HTTPS with a throwaway internal CA, and checks the
healthcheck, the `401` challenge, the protected resource metadata, one tool call, the CA handling and
the audit log from outside, without touching your `.env` or `./logs`:

```sh
bash scripts/smoke-test.sh
```

The end-to-end tests run the whole chain (Dolibarr 23 with restoauth, Keycloak, LibreChat, Caddy and
this server) in the [test stack](test-stack/README.md).

Releasing: set `__version__` in `src/dolibarr_mcp_server/__init__.py` and the image tag in
`compose.yaml` to the same version (a test checks this), run pytest, the smoke test and the test
stack's end-to-end checks on the test VM, both with Caddy and with the
[nginx variant](test-stack/README.md#nginx-variant) (mandatory: it tests the nginx blocks of this
README and of restoauth's README), then tag `vX.Y.Z`.
