# Test stack

**Test only, not for production.** Every password, key and secret in this folder is a test value.
Nothing here is needed to run the MCP server; production uses the `compose.yaml` in the repo root.

The stack runs Dolibarr with restoauth, an identity provider, an MCP client and the MCP server
together on one Docker host, configured without manual clicks, so the whole chain can be tested
against real software. It reproduces the validation run of
[Example setup: Keycloak and LibreChat](../docs/setup/example-keycloak-librechat.md).

It starts a TLS proxy (Caddy, or nginx in the [nginx variant](#nginx-variant)) for `erp.example.com`, `sso.example.com`, `chat.example.com` and
`mcp.example.com`, MariaDB, Dolibarr 23.0.4 with restoauth 0.2.2, Keycloak 26.8.2, MongoDB,
LibreChat v0.8.9 and the MCP server built from this repo. Inside the stack's network the hostnames
point to the proxy, so no hosts file is needed.

## What you need

- Docker with Compose v2.24 or later, about 5 GB of free disk space, internet access (Docker Hub,
  quay.io and GitHub for restoauth)
- `openssl` and `sh` for the certificates
- For the chat checks (a chat answer in LibreChat): your own LLM API key, see [LLM key](#llm-key)

## Start

```sh
cd test-stack
./make-certs.sh                   # test CA + certificate, in certs/ (git-ignored)
docker compose up -d --build      # builds the images, installs and configures everything
docker compose logs -f setup      # wait for "setup complete" (a few minutes on the first start)
```

`setup` ends with checks through the proxy and stops with `setup check failed: ...` if one fails.
`docker compose ps` shows `dolibarr` as `healthy` once Dolibarr is configured. LibreChat starts after
`setup` completed.

## End-to-end checks

```sh
docker compose run --rm client    # waits for "setup complete", then runs client/checks.py
```

`checks.py` acts as an MCP client and as the users' browsers, through the proxy, and prints one
line per check (`PASS`, `FAIL` or `SKIP`); it exits with 1 if a check failed.
`docker compose run --rm client python checks.py -v` adds the traceback of a failed check. It takes
about two and a half minutes, mostly waiting for the MCP server's rights cache (30 s) after a
revocation; the expiry check's wait for the short access token lifetime (60 s) overlaps with those.

| Part | Checks |
|---|---|
| OAuth flow | discovery (401 challenge, protected resource metadata, authorization server metadata at the server root); dynamic registration; authorize, Dolibarr login through Keycloak, consent page with the user's rights; token with PKCE, code used only once; the token works at the MCP server and the Dolibarr REST API; refresh with rotation (old access token dead); refresh token reuse revokes the whole connection; revoke (RFC 7009) |
| Negative cases | redirect URI not on the allowlist (registration) or not registered (authorize); authorize without PKCE or with `plain`; resource not allowed (RFC 8707); wrong or missing PKCE verifier; a user without the connect right (`bob`) sees no Allow button and gets `access_denied` |
| How a connection ends | the user is disabled (by `admin` on the user card): both of `dave`'s connections disappear from his **Connected applications** tab at once, his access token gets 401 at Dolibarr and his refresh token `invalid_grant`; enabling him again revives neither connection, also not the one that was not used while he was disabled; the MCP server refuses the token after its rights cache; afterwards `dave` can connect anew. `anna` ends a connection on her own user card: it disappears from the list, its tokens are refused as above. An access token past its lifetime (60 s in the stack) is refused at Dolibarr and the MCP server, and refresh gives a working one; with a lifetime longer than `EXPIRY_MAX_WAIT` (300 s) this check is reported as `SKIP` with the reason. Each refusal is checked to happen before the token would have expired by itself |
| Example setup: LibreChat | (the [example setup's check list](../docs/setup/example-keycloak-librechat.md#check-list), checks 5 to 7) `anna` logs into LibreChat through Keycloak (with PKCE); connecting the `dolibarr` server leads through Dolibarr's login (Keycloak session reused, no password asked) to restoauth's consent page naming LibreChat MCP Client and `anna`, and after Allow LibreChat shows the server as connected; the Dolibarr assistant is the default model spec with the `dolibarr` server; in a chat, the model calls `whoami` and the result names `anna`; the same for `carl`. The two chat checks are skipped without an [LLM key](#llm-key). |
| Reverse proxy | restoauth's metadata at the server root and in the issuer path, as `oauth-authorization-server` and `openid-configuration` (the discovery rules); in the [nginx variant](#nginx-variant) only: the MCP server under a path prefix answers its `401` challenge with the prefixed metadata URL, the metadata names the prefixed resource, and `anna` connects for that resource and calls `whoami` through the prefix (behind Caddy these two are `SKIP`) |
| Rights | `anna` and `carl` connected: whoami names each; the tool list differs (`carl` has no invoice, proposal or order tools); each reads only their own customer; refused tool calls, `api_get` and `list_api_endpoints` follow the rights, including the stricter rule for outstanding invoices; Dolibarr itself answers `carl`'s `/invoices` with 403; `anna`'s own Dolibarr API key reads her third parties at Dolibarr's REST API (`DOLAPIKEY`), `restoauth/me` answers for it with `"token": null`, and the MCP server refuses it with `401` and the resource metadata challenge |

The checks register a new client on every run and leave it and the revoked connections behind;
they do not depend on what an earlier run left. The OAuth flow checks use LibreChat's callback
(`chat.example.com`, on the allowlist) as their redirect URI: they stop at that redirect and read the
code from it, as a client would. In the LibreChat checks, LibreChat itself receives it.

## nginx variant

On demand, and **mandatory before a release**: nginx replaces Caddy as the TLS proxy, with the same
hostnames and certificates, and everything else stays the same. Add `compose.nginx.yaml` to every
command:

```sh
./make-certs.sh                   # the certificate must include apps.example.com (see below)
docker compose -f compose.yaml -f compose.nginx.yaml up -d --build
docker compose -f compose.yaml -f compose.nginx.yaml logs -f setup proxy   # "setup complete"
docker compose -f compose.yaml -f compose.nginx.yaml run --rm client
docker compose -f compose.yaml -f compose.nginx.yaml down -v
```

Without `compose.nginx.yaml` the stack runs with Caddy as before. Do not switch a running stack
between the two; take it down with `down -v` first.

**The documentation is the configuration.** At start-up the proxy (`nginx/build-conf.sh`) extracts
the nginx code blocks of the READMEs and assembles its configuration from them, and prints it to its
log:

| Block | Taken from | Found by | Used for |
|---|---|---|---|
| server block for the MCP server | [`../README.md`](../README.md#reverse-proxy-tls), "Reverse proxy (TLS)" | `server_name mcp.example.com;` | `mcp.example.com`, as written |
| path prefix | [`../README.md`](../README.md#resource-url-with-a-path-prefix), "Resource URL with a path prefix" | `location = /dolibarr/mcp {` | inside the server block for `apps.example.com`, in front of a second MCP server `mcp-prefix` with `MCP_RESOURCE_URL=https://apps.example.com/dolibarr/mcp` |
| discovery rules | restoauth's `README.md`, "Rewrite rules for discovery", the copy that comes with the installed module (`htdocs/custom/restoauth/README.md`) | `/custom/restoauth/metadata.php` | inside the server block for `erp.example.com`, in front of Dolibarr's Apache |

The stack fills in only what the documentation leaves to the reader: the certificate paths
(`ssl_certificate`, `ssl_certificate_key`), the upstream (`127.0.0.1:8131` becomes the MCP container)
and the server blocks around the location snippets, plus plain proxy blocks for `sso` and `chat`.
A block that is missing or found twice stops the proxy with `[nginx-variant] ...`, a block nginx
refuses stops it at `nginx -t`, and a block that loads but does not work fails the setup or the
check list. When you change one of these blocks, keep the text it is found by, or change
`nginx/build-conf.sh` with it.

What else differs from the Caddy stack:

- `TEST_PROXY=nginx` switches off the Apache discovery rules in `dolibarr/dolibarr.conf`, so the
  discovery URLs are answered by restoauth's nginx rules only; `setup` checks that Dolibarr's Apache
  answers them with 404 itself.
- restoauth's allowed resources contain both `https://mcp.example.com/mcp` and
  `https://apps.example.com/dolibarr/mcp`.
- The proxy starts once Dolibarr (restoauth installed), both MCP servers and Keycloak are up.
- `make-certs.sh` puts `apps.example.com` into the certificate. A `certs/` folder made before that
  lacks it (`make-certs.sh` says so): delete `certs/` and run it again.

nginx is pinned in `compose.nginx.yaml` (`nginx:1.30.5`, a stable release). The run and the check
list take as long as with Caddy.

## LLM key

LibreChat needs a model with tool calls for the chat checks. The example uses OpenRouter. Put your
key into `test-stack/llm.env`, which is git-ignored and never committed:

```sh
umask 077
echo 'OPENROUTER_KEY=<your key>' > llm.env
docker compose up -d librechat        # pick up the key
```

For another provider, change the endpoint in `librechat/librechat.yaml` and the key name in
`llm.env`. Without `llm.env`, `checks.py` skips the two chat checks and says so.

## Screenshots

The screenshots in [`docs/quick-start.md`](../docs/quick-start.md) and
[`docs/user-guide.md`](../docs/user-guide.md) come from this stack. `screenshots/shoot.py` takes
them again, for example after a UI change in LibreChat, Dolibarr or restoauth: a headless Chromium
(Playwright) in the stack's network logs in as the test users, connects the Dolibarr assistant in
LibreChat, asks it the questions shown in the guides, and ends a connection on a user card. It writes
1280 pixel wide PNG files straight into `docs/images/quick-start/` and `docs/images/user-guide/`,
replacing the files there.

It needs the [LLM key](#llm-key) and a **freshly started stack**: the pictures show an empty chat
history and users who have not connected yet, and the script ends `anna`'s connection.

```sh
docker compose down -v && docker compose up -d --build   # fresh stack
docker compose logs -f setup                             # wait for "setup complete"
docker compose run --rm --build screenshots              # about five minutes
```

`docker compose run --rm --build screenshots python shoot.py anna carl` takes only some parts (`admin`,
`anna`, `carl`, `bob`; see the top of `shoot.py`), on a fresh stack as well. On a failure, the
script saves the open pages as PNG and HTML in `docs/images/debug/` (git-ignored, not part of the
docs).

The model's answers differ from run to run. Look at every picture before you commit it: the
questions must be answered from a tool call (**Ran ... in dolibarr**), and only the example
hostnames and test users may be visible. LibreChat allows about 7 logins per 5 minutes; the script
needs three, so wait five minutes between two runs.

On the test VM, run it under your own project name, with `TEST_TAG=$RUN docker compose -p $RUN run
--rm screenshots`, then copy `docs/images/` back to your checkout (see `docs/agents/test-vm.md`).

## Stop

```sh
docker compose stop               # stop, keep everything; `docker compose start` resumes
docker compose down               # remove the containers, keep the volumes (data, Keycloak realm)
```

After `down`, `docker compose up -d` brings the same state back: Dolibarr's configuration step and
`setup` run again and skip what is already done.

## Reset

```sh
docker compose down -v            # removes the containers and all volumes (database, Dolibarr
                                  # documents and custom folder, Keycloak, MongoDB)
docker compose up -d --build      # then start again from a clean state
```

`certs/` stays; delete it and run `./make-certs.sh` for new certificates. To also remove the images
built here: `docker rmi dolibarr-mcp-test-dolibarr:local dolibarr-mcp-server:test-stack-local
dolibarr-mcp-test-client:local`.

## What the stack does

| Step | Done by |
|---|---|
| restoauth release ZIP `module_restoauth-<version>.zip`: the asset of the GitHub release `v<version>` if there is one, otherwise built from the tag with restoauth's `scripts/build-release-zip.sh`; the build stops if the ZIP has no module descriptor for that version | `dolibarr/Dockerfile` |
| Dolibarr 23.0.4 from the official image; the image installs the database and the admin user | `compose.yaml` (`DOLI_*`) |
| Apache vhost: reverse-proxy settings and the discovery rewrite rule, exactly as in the restoauth README | `dolibarr/dolibarr.conf` |
| Trust the test CA, install restoauth from the ZIP into `htdocs/custom/restoauth` (the way Dolibarr's module upload does), on every start | `dolibarr/50-test-stack.sh` |
| Enable API REST, third parties, invoices, proposals, orders, products, services, scheduled jobs and restoauth; allowed resources, redirect allowlist, loopback off, short access token lifetime, `API_IN_TOKEN_TABLE` off; `openid_connect` against Keycloak; test users and rights; sample data | `dolibarr/configure.php` (Dolibarr's own PHP functions) |
| Keycloak realm `example`, clients `dolibarr` and `librechat`, test users; no self-registration, usernames cannot be changed | `client/keycloak_realm.py` (the example setup's values) |
| LibreChat `.env` and `librechat.yaml`: Keycloak login, the `dolibarr` MCP server, allowed domains, the Dolibarr assistant model spec, one LLM endpoint | `librechat/` (the example setup's snippets) |
| nginx variant: nginx as TLS proxy, its configuration assembled from the READMEs' nginx blocks; a second MCP server under a path prefix (see [nginx variant](#nginx-variant)) | `compose.nginx.yaml`, `nginx/build-conf.sh` |
| Checks through the proxy: Keycloak metadata, restoauth metadata at `/.well-known/oauth-authorization-server/custom/restoauth` and at the issuer path, Keycloak button on Dolibarr's login page, the MCP server's `401` challenge and protected resource metadata | `client/setup.py` |
| End-to-end checks: OAuth flow, rights, how a connection ends and LibreChat (on demand, see [End-to-end checks](#end-to-end-checks)) | `client/checks.py`, `client/flows.py` |

Differences from the example setup, all for a local test: the Keycloak realm is created (the manual
assumes it exists); the client secrets are fixed test values instead of being copied from the
Credentials tab; Dolibarr is configured by `dolibarr/configure.php` instead of the setup pages.

The restoauth version is pinned in one place, `RESTOAUTH_VERSION` in `dolibarr/Dockerfile`. To try
another tag: `docker compose build --build-arg RESTOAUTH_VERSION=X.Y.Z dolibarr`, then
`docker compose up -d`; the start step replaces the module folder when the version changed.

Dolibarr's configuration runs inside the Dolibarr container, not in the Python client, because it
needs Dolibarr's own PHP functions (`activateModule`, `dolibarr_set_const`, `User::addrights`, the
business object classes). The `setup` service starts once that step succeeded (healthcheck).

## Test users and data

| User | Where | Password | Dolibarr rights |
|---|---|---|---|
| `admin` | Dolibarr (local) | `Test-Admin-Pw1!` | administrator |
| `anna` | Keycloak; Dolibarr user `anna` | `Test-Anna-Pw1!` | connect right, read third parties, invoices, proposals, orders, products; sales representative of North Customer Ltd only; also has her own Dolibarr API key `test-anna-api-key-0123456789abcdef0123` (`TEST_ANNA_API_KEY`) |
| `bob` | Keycloak; Dolibarr user `bob` | `Test-Bob-Pw1!` | the same read rights, **no** connect right |
| `carl` | Keycloak; Dolibarr user `carl` | `Test-Carl-Pw1!` | connect right, read third parties and products only (no invoices, proposals, orders); sales representative of South Customer Inc only |
| `dave` | Keycloak; Dolibarr user `dave` | `Test-Dave-Pw1!` | connect right, read third parties; sales representative of no customer. The checks disable him and enable him again |
| `admin` | Keycloak `master` realm | `test-kc-admin-pw` | |

`anna`, `bob` and `carl` also log into LibreChat with **Sign in with Keycloak**; LibreChat creates
their accounts on the first login (by email, `<name>@example.com`).

`anna`, `bob`, `carl` and `dave` log in to Dolibarr through Keycloak only (button on the login page); they have no
Dolibarr password. The Dolibarr login equals the Keycloak `preferred_username`, because Dolibarr 23
does not create users on the first `openid_connect` login. None has the right to see all
customers, so `anna` sees only North Customer Ltd and its documents, and `carl` only South Customer
Inc.

Sample data: products `SRV-MAINT` (service) and `HW-ROUTER` (product); customers North Customer Ltd
(Hamburg) and South Customer Inc (Munich), each with one validated invoice, proposal and order.

The checks find customers by name and do not count products or documents, so they also pass on a
Dolibarr with more data: `TEST_EXTRA_DATA=6` (on `up`) adds that many extra customers, each with an
invoice, proposal and order, and as many extra products; extra customers 1, 4, ... belong to `anna`,
2, 5, ... to `carl`, the rest to nobody. The rights checks still prove that `anna` and `carl` see none of
each other's customers and only documents of their own.

restoauth settings: allowed resource `https://mcp.example.com/mcp`; redirect allowlist
`https://chat.example.com/api/mcp/dolibarr/oauth/callback`; loopback redirects off; issuer empty
(the module URL `https://erp.example.com/custom/restoauth`); access token lifetime 60 s
(`TEST_ACCESS_TOKEN_LIFETIME`, restoauth's minimum; the default is 3600 s) for the expiry check.
Change them in `compose.yaml` (`TEST_*` of the `dolibarr` service). `TEST_ACCESS_TOKEN_LIFETIME` and
`TEST_EXTRA_DATA` can also be set in the environment of `docker compose up`, e.g.
`TEST_ACCESS_TOKEN_LIFETIME=3600 docker compose up -d`; the expiry check then reports `SKIP`, because it
waits at most `EXPIRY_MAX_WAIT` seconds (300, set it on `docker compose run` for a longer wait).

## Reach the services with IP and port (optional)

The stack needs no published ports. To reach every service from another machine, add
`compose.ports.yaml`:

```sh
docker compose -f compose.yaml -f compose.ports.yaml up -d
```

| Service | Host port (variable) | What |
|---|---|---|
| proxy | 443 (`TEST_HTTPS_PORT`) | HTTPS for all hostnames |
| Dolibarr | 8082 (`TEST_DOLIBARR_PORT`) | Dolibarr's Apache, plain HTTP |
| Keycloak | 8080 (`TEST_KEYCLOAK_PORT`), 9000 (`TEST_KEYCLOAK_MGMT_PORT`) | admin console; management |
| LibreChat | 3080 (`TEST_LIBRECHAT_PORT`) | plain HTTP |
| MCP server | 8131 (`TEST_MCP_PORT`) | plain HTTP |
| MariaDB | 3306 (`TEST_DB_PORT`) | user `dolibarr`, password `test-dolibarr-db-pw` |
| MongoDB | 27017 (`TEST_MONGO_PORT`) | no authentication |

If another stack on the host already uses a port, set the variable, e.g.
`TEST_HTTPS_PORT=8443 TEST_DOLIBARR_PORT=18082 docker compose -f compose.yaml -f compose.ports.yaml up -d`.

**Logins and the OAuth flows need the hostnames**: Dolibarr, Keycloak and LibreChat send the browser
to `https://*.example.com` (port 443). For those, map the hostnames to the Docker host in your hosts
file, publish the proxy on port 443, and trust `certs/ca.crt` in your browser (or accept the
certificate warning once per hostname). The MCP server answers only for `mcp.example.com` and
loopback, so its plain HTTP port is useful for the healthcheck and little else.

## In a browser on another machine, without admin rights

Changing the hosts file needs admin rights. On Windows, `browser/open-browser.ps1` does without:
it starts a browser with its own profile that resolves the four hostnames to the Docker host, and
it can trust the test CA for your Windows user only.

1. Publish the proxy on port 443 (see above):
   `docker compose -f compose.yaml -f compose.ports.yaml up -d`
2. Copy `certs/ca.crt` from the Docker host to your machine.
3. In PowerShell (no admin rights), in `test-stack/browser/`:

   ```powershell
   .\open-browser.ps1 -HostIp <Docker host IP> -CaFile <path to ca.crt> -Shortcut
   ```

   Windows asks once whether to trust the test CA: answer **Yes**. The browser opens
   `https://chat.example.com` and `https://erp.example.com`; `-Shortcut` puts a desktop shortcut
   to open it again.

| `-Browser` | How it resolves the hostnames | Note |
|---|---|---|
| `firefox` (default) | profile setting `network.dns.forceResolve`: **every** hostname goes to the Docker host | use that profile only for the test stack |
| `edge`, `chrome` | `--host-resolver-rules` for the four hostnames only | |

The profiles live in `%USERPROFILE%\.dolibarr-mcp-test\`, apart from your normal browser profile.
To undo: delete that folder and the desktop shortcut, and remove the test CA in `certmgr.msc`
(Trusted Root Certification Authorities, "dolibarr-mcp test CA"). If the PowerShell execution policy
blocks the script, start it with `powershell -ExecutionPolicy Bypass -File .\open-browser.ps1 ...`.

The browser needs port 443 on the Docker host. If another stack already publishes 443 there (for
example the iTop test stack), stop that one first; the hostnames cannot be sent to another port.

## Notes

- The stack uses the name `dolibarr-mcp-test` for its project and volumes. `TEST_TAG` (default
  `local`) names the three images built here; on a shared Docker host give each run its own
  project name and tag, e.g. `TEST_TAG=dr10 docker compose -p dr10 up -d --build` (see
  `docs/agents/test-vm.md`).
- LibreChat limits logins per IP (about 7 in 5 minutes). Running `checks.py` several times in a row
  can end with `auth_rate_limited`; wait five minutes.
