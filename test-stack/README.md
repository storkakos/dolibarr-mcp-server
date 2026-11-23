# Test stack

**Test only, not for production.** Every password, key and secret in this folder is a test value.
Nothing here is needed to run the MCP server; production uses the `compose.yaml` in the repo root.

The stack runs Dolibarr with restoauth, an identity provider and the MCP server together on one
Docker host, configured without manual clicks, so the whole chain can be tested against real
software.

It starts a TLS proxy (Caddy) for `erp.example.com`, `sso.example.com` and `mcp.example.com`,
MariaDB, Dolibarr 23.0.4 with restoauth 0.2.1, Keycloak 26.8.2 and the MCP server built from this
repo. Inside the stack's network the hostnames point to the proxy, so no hosts file is needed.

## What you need

- Docker with Compose v2.24 or later, about 3 GB of free disk space, internet access (Docker Hub,
  quay.io and GitHub for restoauth)
- `openssl` and `sh` for the certificates

## Start

```sh
cd test-stack
./make-certs.sh                   # test CA + certificate, in certs/ (git-ignored)
docker compose up -d --build      # builds the images, installs and configures everything
docker compose logs -f setup      # wait for "setup complete" (a few minutes on the first start)
```

`setup` ends with checks through the proxy and stops with `setup check failed: ...` if one fails.
`docker compose ps` shows `dolibarr` as `healthy` once Dolibarr is configured.

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
                                  # documents and custom folder, Keycloak)
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
| Enable API REST, third parties, invoices, proposals, orders, products, services, scheduled jobs and restoauth; allowed resources, redirect allowlist, loopback off, `API_IN_TOKEN_TABLE` off; `openid_connect` against Keycloak; test users and rights; sample data | `dolibarr/configure.php` (Dolibarr's own PHP functions) |
| Keycloak realm `example`, client `dolibarr`, test users; no self-registration, usernames cannot be changed | `client/keycloak_realm.py` |
| Checks through the proxy: Keycloak metadata, restoauth metadata at `/.well-known/oauth-authorization-server/custom/restoauth` and at the issuer path, Keycloak button on Dolibarr's login page, the MCP server's `401` challenge and protected resource metadata | `client/setup.py` |

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
| `anna` | Keycloak; Dolibarr user `anna` | `Test-Anna-Pw1!` | connect right, read third parties, invoices, proposals, orders, products; sales representative of North Customer Ltd only |
| `bob` | Keycloak; Dolibarr user `bob` | `Test-Bob-Pw1!` | the same read rights, **no** connect right |
| `admin` | Keycloak `master` realm | `test-kc-admin-pw` | |

`anna` and `bob` log in to Dolibarr through Keycloak only (button on the login page); they have no
Dolibarr password. The Dolibarr login equals the Keycloak `preferred_username`, because Dolibarr 23
does not create users on the first `openid_connect` login. Neither has the right to see all
customers, so `anna` sees only North Customer Ltd and its documents.

Sample data: products `SRV-MAINT` (service) and `HW-ROUTER` (product); customers North Customer Ltd
(Hamburg) and South Customer Inc (Munich), each with one validated invoice, proposal and order.

restoauth settings: allowed resource `https://mcp.example.com/mcp`; redirect allowlist
`https://chat.example.com/api/mcp/dolibarr/oauth/callback`; loopback redirects off; issuer empty
(the module URL `https://erp.example.com/custom/restoauth`). Change them in `compose.yaml`
(`TEST_*` of the `dolibarr` service).

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
| MCP server | 8131 (`TEST_MCP_PORT`) | plain HTTP |
| MariaDB | 3306 (`TEST_DB_PORT`) | user `dolibarr`, password `test-dolibarr-db-pw` |

If another stack on the host already uses a port, set the variable, e.g.
`TEST_HTTPS_PORT=8443 TEST_DOLIBARR_PORT=18082 docker compose -f compose.yaml -f compose.ports.yaml up -d`.

**Logins and the OAuth flows need the hostnames**: Dolibarr and Keycloak send the browser to
`https://*.example.com` (port 443). For those, map the hostnames to the Docker host in your hosts
file, publish the proxy on port 443, and trust `certs/ca.crt` in your browser (or accept the
certificate warning once per hostname). The MCP server answers only for `mcp.example.com` and
loopback, so its plain HTTP port is useful for the healthcheck and little else.

## Notes

- The stack uses the name `dolibarr-mcp-test` for its project and volumes. `TEST_TAG` (default
  `local`) names the three images built here; on a shared Docker host give each run its own
  project name and tag, e.g. `TEST_TAG=dr10 docker compose -p dr10 up -d --build` (see
  `docs/agents/test-vm.md`).
- `chat.example.com` is already in the certificate and in the redirect allowlist for an MCP client
  in the stack; the stack itself has no MCP client yet.
