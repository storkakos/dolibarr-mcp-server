# Example setup: Keycloak and LibreChat

**Example setup, not required.** This manual shows one documented way to connect an
**identity provider** (Keycloak) and an **MCP client** (LibreChat) to Dolibarr and the MCP server.
Other identity providers and MCP clients work too; the Dolibarr prerequisites (restoauth) stay the
same for them.

Before you start:

- Prepare Dolibarr as the [Dolibarr prerequisites](dolibarr-prerequisites.md) describe: restoauth,
  API REST, the setup page, the connect right and the discovery rewrite rule. Their check list must
  pass.
- The MCP server runs behind your reverse proxy (see the [README](../../README.md)), and
  `MCP_RESOURCE_URL` is in restoauth's **Allowed resources**.
- Keycloak is installed and reachable over HTTPS, with a realm for your users. Installing Keycloak
  is not covered; see the [Keycloak documentation](https://www.keycloak.org/documentation).
- LibreChat is installed, reachable over HTTPS behind your reverse proxy, and works with at least
  one AI model. This manual covers only the LibreChat settings for Keycloak and the MCP server.
  Not covered, see the LibreChat documentation:
  - installing LibreChat: [Docker setup](https://www.librechat.ai/docs/local/docker)
  - MongoDB: [MongoDB Community Server](https://www.librechat.ai/docs/configuration/mongodb/mongodb_community)
    or [MongoDB Atlas](https://www.librechat.ai/docs/configuration/mongodb/mongodb_atlas)
  - setting up AI models (LLM endpoints):
    [AI endpoints](https://www.librechat.ai/docs/configuration/librechat_yaml/ai_endpoints)
  - all `librechat.yaml` options:
    [librechat.yaml](https://www.librechat.ai/docs/configuration/librechat_yaml), and LibreChat's own
    pages on [MCP](https://www.librechat.ai/docs/features/mcp) and
    [Keycloak](https://www.librechat.ai/docs/configuration/authentication/OAuth2-OIDC/keycloak)

The [test stack](../../test-stack/README.md) runs this whole manual on one Docker host, configured
automatically, and its `checks.py` runs the [check list](#check-list) (test only, not for
production).

## Contents

1. [Example hostnames](#example-hostnames)
2. [Who does what](#who-does-what)
3. [Tested with](#tested-with)
4. [Keycloak: client for Dolibarr](#keycloak-client-for-dolibarr)
5. [Dolibarr: log in with Keycloak](#dolibarr-log-in-with-keycloak)
6. [Dolibarr user accounts](#dolibarr-user-accounts)
7. [Keycloak: client for LibreChat](#keycloak-client-for-librechat)
8. [LibreChat](#librechat)
9. [Check list](#check-list)
10. [Both MCP servers in one LibreChat](#both-mcp-servers-in-one-librechat)

## Example hostnames

All URLs use HTTPS behind the customer's reverse proxy. Replace them with yours everywhere in this
manual and in the config snippets.

| Example | What it is | Replace with yours |
|---|---|---|
| `https://erp.example.com` | Dolibarr (`$dolibarr_main_url_root`) | |
| `https://erp.example.com/custom/restoauth` | restoauth's issuer (the module URL, derived from the Dolibarr URL) | |
| `https://sso.example.com` | Keycloak, base URL without `/realms/...` | |
| `example` | Keycloak realm of your users | |
| `https://sso.example.com/realms/example` | Issuer of the realm (derived from the two lines above) | |
| `https://erp.example.com/core/modules/openid_connect/callback.php` | Dolibarr's callback for the Keycloak login (derived from the Dolibarr URL) | |
| `https://chat.example.com` | LibreChat (`DOMAIN_CLIENT` and `DOMAIN_SERVER`) | |
| `https://chat.example.com/oauth/openid/callback` | LibreChat's callback for the Keycloak login (derived from the LibreChat URL) | |
| `https://chat.example.com/api/mcp/dolibarr/oauth/callback` | LibreChat's callback for the restoauth OAuth flow (derived from the LibreChat URL and the server name `dolibarr`) | |
| `https://mcp.example.com/mcp` | Public URL of the MCP server (`MCP_RESOURCE_URL`) | |

## Who does what

| Component | Role | What it does in this setup |
|---|---|---|
| Keycloak | **Identity provider** | Logs users in: into Dolibarr (through `openid_connect`) and into LibreChat (through OpenID Connect). |
| Dolibarr with restoauth | **Authorization server** | Asks the logged-in user for consent and issues the access token for the MCP server. Checks the token on every REST call. |
| LibreChat | **MCP client** | The chat users work in. Fetches the token from restoauth and sends it with every call to the MCP server. |
| MCP server | **MCP server** | Forwards each tool call to Dolibarr's REST API with the caller's token. Stores no secrets, issues no tokens. |

**Keycloak never issues MCP tokens.** The tokens Keycloak issues log users into Dolibarr and
LibreChat, nothing more. The MCP server's metadata names restoauth as its only authorization server,
and restoauth accepts only tokens it issued itself. Do not try to configure Keycloak as the
authorization server of the MCP server, and do not add an audience or client scope for the MCP
server in Keycloak.

What a user experiences the first time they connect the assistant:

1. The user logs into LibreChat with Keycloak.
2. They connect the Dolibarr server in LibreChat. LibreChat calls the MCP server, gets `401`, reads
   the metadata, registers itself with restoauth and sends the user's browser to restoauth's
   authorization page.
3. restoauth needs a logged-in Dolibarr user and shows Dolibarr's login page. The user clicks
   **Use OpenID to login**. If they still have a Keycloak session from step 1, Keycloak lets them
   through without asking for a password again.
4. Keycloak sends the browser back to Dolibarr (`callback.php`). Dolibarr logs the user in as the
   Dolibarr user whose login matches their Keycloak username (see
   [Dolibarr user accounts](#dolibarr-user-accounts)) and shows restoauth's consent page, which lists
   the rights the assistant will act with.
5. After consent, restoauth issues the token to LibreChat. From now on, the assistant sees exactly
   what this Dolibarr user may see. The user finds the connection on their user card, tab
   **Connected applications**, and can end it there.

## Tested with

| Component | Version | Validation run |
|---|---|---|
| Dolibarr | 23.0.4 (image `dolibarr/dolibarr:23.0.4`) | 2026-11-24 |
| restoauth | 0.2.1 | 2026-11-24 |
| Keycloak | 26.8.2 | 2026-11-24 |
| LibreChat | v0.8.9 | 2026-11-24 |

The validation run used Dolibarr, Keycloak and LibreChat as containers behind a TLS-terminating
reverse proxy (the [test stack](../../test-stack/README.md)). LibreChat's v0.8.9 image is published
on Docker Hub as `librechat/librechat:v0.8.9`.

Newer versions should work but are untested. Dolibarr versions other than 23 are not supported by
restoauth.

## Keycloak: client for Dolibarr

Dolibarr logs users in through a **confidential** OpenID Connect client named `dolibarr` in the
realm `example`. In the Keycloak admin console (Keycloak 26):

1. Select the realm `example`.
2. Go to **Clients** → **Create client**.
3. Fill in the three pages of the wizard with the values below, then **Save**.
4. Open the **Credentials** tab of the new client. Leave **Client Authenticator** at
   **Client Id and Secret** and copy the **Client Secret**. You need it in
   [Dolibarr: log in with Keycloak](#dolibarr-log-in-with-keycloak).

| Page | Field | Value |
|---|---|---|
| General settings | Client type | `OpenID Connect` |
| | Client ID | `dolibarr` |
| | Name | `Dolibarr` |
| Capability config | Client authentication | **On** (confidential client) |
| | Authorization | Off |
| | Standard flow | **On** |
| | Direct access grants | **Off** (on by default when the client is created; untick it) |
| | Implicit flow | Off |
| | Service accounts roles | Off |
| | Standard Token Exchange | Off |
| | OAuth 2.0 Device Authorization Grant | Off |
| | OIDC CIBA Grant | Off |
| | Require PKCE | Off (see below) |
| Login settings | Root URL | `https://erp.example.com` |
| | Home URL | `https://erp.example.com/` |
| | Valid redirect URIs | `https://erp.example.com/core/modules/openid_connect/callback.php` (exactly this, no wildcard) |
| | Valid post logout redirect URIs | `https://erp.example.com/index.php*` (with the `*`, see the **Logout URL** below) |
| | Web origins | empty (Dolibarr calls Keycloak from the server, not from the browser) |
| Logout settings | Front channel logout | **On** |
| | Front-channel logout URL | `https://erp.example.com/custom/restoauth/frontchannel-logout.php` (restoauth's front-channel logout endpoint) |
| | Backchannel logout URL | empty (Dolibarr has no endpoint for it) |

Why these values:

- **Standard flow only.** Dolibarr's `openid_connect` login uses the authorization code flow. Direct
  access grants would let anyone with the client secret exchange a user's password for tokens;
  implicit flow and service accounts are not used.
- **Require PKCE off.** Dolibarr 23's `openid_connect` login does not send PKCE parameters, so
  requiring PKCE would make every login fail. The client is confidential, so the code exchange is
  protected by the client secret. (The OAuth flow of the MCP client against restoauth always uses
  PKCE; that is a different flow.)
- **Redirect URI exact.** Keycloak compares redirect URIs case-sensitively. If Dolibarr does not live
  at the web root, the path prefix belongs in front of `/core`.
- **Post logout redirect URI with `*`.** Dolibarr 23 appends its own parameters to the logout URL, so
  the address Keycloak is asked to return to is `https://erp.example.com/index.php` followed by
  `?client_id=...`. Without the trailing `*`, Keycloak refuses the logout with "Invalid redirect
  uri". The `*` only allows addresses that start with Dolibarr's own `index.php`.
- **Front-channel logout to restoauth.** A Keycloak logout (for example LibreChat's **Log out**, see
  [Log out of Keycloak too](#env-log-out-of-keycloak-too)) ends only Keycloak's own session unless
  Keycloak knows how to log the user out of Dolibarr. With this URL, Keycloak's logout page loads
  restoauth's front-channel logout endpoint in the browser, and Dolibarr's session ends too. Without
  it, Dolibarr stays logged in as the previous user: if someone else then logs into LibreChat in the
  same browser and connects Dolibarr, restoauth's consent page is shown for the previous user's
  Dolibarr account, and that person's token ends up in the new user's LibreChat. restoauth's endpoint
  handles the session end cleanly, without the side effect that loading Dolibarr's own logout page
  had.

### Users in Keycloak

Dolibarr identifies the user by the claim set as **Login claim** (below: `preferred_username`, the
Keycloak username). So:

- Every user who logs into Dolibarr needs a Keycloak username that is exactly the login of their
  Dolibarr user (see [Dolibarr user accounts](#dolibarr-user-accounts)).
- **Users must not be able to choose their own username.** Whoever can set a username in Keycloak can
  log into Dolibarr as the Dolibarr user with that login.

In realm `example`, check these settings:

| Where in the admin console | Field | Value | Default |
|---|---|---|---|
| **Realm settings** → **Login** → **User info settings** | **Edit username** | Off (leave) | Off |
| **Realm settings** → **Login** → **Login screen customization** | **User registration** | Off (leave) | Off |
| **Realm settings** → **Login** → **Login screen customization** | **Email as username** | Off (leave), see below | Off |

- **Edit username** On would let users rename themselves in the account console, and so pick
  another Dolibarr user's login.
- **User registration** On would let anyone create an account and choose its username. Leave it
  off.
- **Email as username** On makes the username follow the email. Then the email decides the Dolibarr
  login, and users must not be able to change their email either: in **Realm settings** →
  **User profile** → **Attributes** → `email` → **Permission**, untick **User** under
  **Who can edit?**, and turn on **Verify email**.
- **Identity providers:** if your realm also lets users log in through other identity providers
  (**Identity providers** in the menu), the username of a user created through them comes from that
  provider. Whoever controls the username at that provider then controls which Dolibarr user they
  log in as.
- Admins (users with the `manage-users` role) can still change usernames, so treat that role as able
  to log into Dolibarr as anyone.

If you leave Dolibarr's **Login claim** empty, Dolibarr matches by **email** instead. Then the email
rules from the last two bullets apply in full.

Check 3 of the [check list](#check-list) tests that a user cannot change their username.

## Dolibarr: log in with Keycloak

Two places change: `conf/conf.php` (turn the login mode on) and Dolibarr's security setup (the
Keycloak values).

### `conf/conf.php`

Add `openid_connect` to the authentication modes and keep `dolibarr`:

```php
$dolibarr_main_authentication = 'openid_connect,dolibarr';
```

- `openid_connect` adds a **Use OpenID to login** button to Dolibarr's login page.
- `dolibarr` keeps the login form, so local accounts (for example your administrator) can still log
  in. With `openid_connect` alone, Dolibarr sends every visitor straight to Keycloak.
- With the official Docker image, set `DOLI_AUTH=openid_connect,dolibarr` instead; the image writes
  it into `conf.php`.

### Setup → Security → OpenID authentication parameters

Log in as administrator, go to **Setup** → **Security** → tab **OpenID authentication parameters**,
switch on **Enable the OpenID Connect authentication mode**, and fill in:

| Field | Value |
|---|---|
| Login claim | `preferred_username` |
| Client ID | `dolibarr` |
| Client secret | the client secret from the **Credentials** tab of the `dolibarr` client |
| Scopes | `openid email profile` |
| Authorize URL | `https://sso.example.com/realms/example/protocol/openid-connect/auth` |
| Token URL | `https://sso.example.com/realms/example/protocol/openid-connect/token` |
| User info URL | `https://sso.example.com/realms/example/protocol/openid-connect/userinfo` |
| Logout URL | `https://sso.example.com/realms/example/protocol/openid-connect/logout?client_id=dolibarr&post_logout_redirect_uri=https%3A%2F%2Ferp.example.com%2Findex.php` |

Then **Save**.

- **Populate from well-known URL** with `https://sso.example.com/realms/example` fills in the four
  URLs from the realm's metadata. Check them afterwards against the table; the **Logout URL** needs
  the parameters above.
- **Logout URL:** Dolibarr 23 appends `?client_id=...&returnTo=...` (the parameters of another
  provider). Keycloak needs `client_id` and `post_logout_redirect_uri`, so both are part of the
  configured URL, and the `dolibarr` client allows the return address with a trailing `*` (see
  [Keycloak: client for Dolibarr](#keycloak-client-for-dolibarr)). On logout, Keycloak asks "Do you
  want to log out?"; after **Logout** the browser lands on Dolibarr's login page.
- The page shows the **Redirect URL** to enter in Keycloak. It must be exactly the **Valid redirect
  URI** of the `dolibarr` client.
- Dolibarr calls the token and user info URLs from the server over HTTPS. If Keycloak's certificate
  comes from an internal CA, the Dolibarr server (PHP's curl) must trust that CA. Do not turn off
  certificate verification.

The client secret is stored in Dolibarr's database. Keep database dumps out of reach accordingly.

Behind a reverse proxy, Dolibarr must know its public URL: `$dolibarr_main_url_root` is
`https://erp.example.com`, and the proxy passes `X-Forwarded-Proto: https`. Otherwise Dolibarr builds
the callback with `http://` and Keycloak refuses it.

## Dolibarr user accounts

Dolibarr 23 does **not** create users on their first Keycloak login. When a user comes back from
Keycloak, Dolibarr looks for an **enabled** user whose **login is exactly the Keycloak username**
(the Login claim). If there is none, the login is refused.

For every person who should log in with Keycloak:

1. Create a Dolibarr user (**Users & Groups** → **New user**) with:
   - **Login**: the user's Keycloak username exactly
   - a password is not needed for the Keycloak login; leave the generated one or set a random one
2. On the user's **Permissions** tab, give the rights this person needs in Dolibarr. To use the
   assistant, this includes **Connect applications (AI assistant) via OAuth with own rights**
   (module REST-OAuth). Without it, the consent page offers only **Deny**.
3. Restrict which customers the user sees as for any other user (for example sales representative
   assignments without the right to see all customers).

The assistant sees exactly what this Dolibarr user sees. Assign rights with that in mind.

Keep at least one local administrator account. It keeps working with Dolibarr's login form and is
your way in if Keycloak is down or misconfigured.

Disabling a Dolibarr user ends all of that user's connections: the assistant stops working for them
at once, also through tokens issued earlier.

## Keycloak: client for LibreChat

LibreChat logs users in through a second **confidential** OpenID Connect client named `librechat`
in the same realm `example`. Create it like the `dolibarr` client: **Clients** → **Create client**,
fill in the values below, **Save**, then copy the **Client Secret** from the **Credentials** tab. You
need it in [LibreChat](#librechat).

| Page | Field | Value |
|---|---|---|
| General settings | Client type | `OpenID Connect` |
| | Client ID | `librechat` |
| | Name | `LibreChat` |
| Capability config | Client authentication | **On** (confidential client) |
| | Authorization | Off |
| | Standard flow | **On** |
| | Direct access grants | **Off** (on by default when the client is created; untick it) |
| | Implicit flow | Off |
| | Service accounts roles | Off |
| | Standard Token Exchange | Off |
| | OAuth 2.0 Device Authorization Grant | Off |
| | OIDC CIBA Grant | Off |
| | Require PKCE | Off (see below) |
| Login settings | Root URL | `https://chat.example.com` |
| | Home URL | `https://chat.example.com/` |
| | Valid redirect URIs | `https://chat.example.com/oauth/openid/callback` (exactly this, no wildcard) |
| | Valid post logout redirect URIs | `https://chat.example.com/login` (LibreChat's login page, see [Log out of Keycloak too](#env-log-out-of-keycloak-too)) |
| | Web origins | empty (LibreChat calls Keycloak from the server, not from the browser) |

The reasons are the same as for the [`dolibarr` client](#keycloak-client-for-dolibarr): authorization
code flow only, exact redirect URI. **Require PKCE** off means Keycloak accepts a login with or
without PKCE. LibreChat sends PKCE (`S256`) when `OPENID_USE_PKCE=true`, and the client secret
protects the code exchange either way. The **post logout redirect URI** is where Keycloak sends the
browser after LibreChat's logout. Without it, Keycloak answers the logout with "Invalid redirect uri"
and keeps the session, so the next **Sign in with Keycloak** logs the same person in without a
password.

LibreChat matches its accounts by **email**, so every LibreChat user needs an email in Keycloak.
LibreChat accounts give access to chats only, not to Dolibarr data: what the assistant may read is
decided by the Dolibarr user who gives consent in restoauth.

**This client is for logging into LibreChat only.** Do not use it, or any other Keycloak client, for
the MCP server. LibreChat gets the token for the MCP server from restoauth (see
[Who does what](#who-does-what)).

## LibreChat

Two files change: `.env` (the Keycloak login) and `librechat.yaml` (the MCP server). Restart
LibreChat after changing either of them. In Dolibarr, restoauth must allow LibreChat's callback.

### `.env`: log in with Keycloak

Set or add these keys:

```sh
# Public URL of LibreChat. Both callbacks are built from DOMAIN_SERVER.
DOMAIN_CLIENT=https://chat.example.com
DOMAIN_SERVER=https://chat.example.com

# Keycloak login. Social login must be on for OpenID to be offered.
ALLOW_SOCIAL_LOGIN=true
# Creates the LibreChat account on a user's first Keycloak login.
ALLOW_SOCIAL_REGISTRATION=true

OPENID_ISSUER=https://sso.example.com/realms/example
OPENID_CLIENT_ID=librechat
OPENID_CLIENT_SECRET=<client secret from the Credentials tab of the librechat client>
OPENID_SCOPE="openid profile email"
OPENID_CALLBACK_URL=/oauth/openid/callback
# A long random value, for example from: openssl rand -hex 32
OPENID_SESSION_SECRET=<random value>
OPENID_BUTTON_LABEL=Sign in with Keycloak
OPENID_USE_PKCE=true
```

- `OPENID_ISSUER` is the realm's issuer, without `/.well-known/...`.
- `OPENID_CALLBACK_URL` is a path. LibreChat puts `DOMAIN_SERVER` in front of it, which must give
  exactly the **Valid redirect URI** of the `librechat` client.
- `OPENID_USE_PKCE=true` adds PKCE (`S256`) on top of the client secret. Keycloak accepts it with
  **Require PKCE** off on the `librechat` client.
- If only Keycloak users should use LibreChat, also set `ALLOW_REGISTRATION=false`. Keep
  `ALLOW_EMAIL_LOGIN` as it is if you need a local LibreChat admin account.
- If Keycloak, Dolibarr or the MCP server use certificates from an internal CA, set
  `NODE_EXTRA_CA_CERTS` to the CA file for LibreChat.

### `.env`: log out of Keycloak too

By default, LibreChat's **Log out** only ends the LibreChat session. The Keycloak session stays, and
the next **Sign in with Keycloak** logs the same person in again without asking for a password: on a
shared computer the next user gets the previous user's account, and nobody can switch to another
account. Add these keys so that the logout ends the Keycloak session too:

```sh
# Log out of Keycloak as well, then come back to LibreChat's login page.
OPENID_USE_END_SESSION_ENDPOINT=true
OPENID_POST_LOGOUT_REDIRECT_URI=https://chat.example.com/login
```

- `OPENID_USE_END_SESSION_ENDPOINT=true` makes LibreChat send the browser to Keycloak's logout
  endpoint (the realm's `end_session_endpoint`) after its own logout.
- `OPENID_POST_LOGOUT_REDIRECT_URI` is where Keycloak sends the browser afterwards. It must be listed
  exactly under **Valid post logout redirect URIs** of the
  [`librechat` client](#keycloak-client-for-librechat). Without the key, LibreChat sends
  `DOMAIN_CLIENT` + `/login`, the same URL; the key makes it explicit.
- When LibreChat still has the user's ID token, Keycloak logs out at once. Otherwise Keycloak first
  asks "Do you want to log out?"; after **Logout** the browser lands on LibreChat's login page.
- The logout ends the user's Keycloak session for every application. Dolibarr's own session in the
  browser ends too, through the **front-channel logout** of the
  [`dolibarr` client](#keycloak-client-for-dolibarr): Keycloak's logout page loads restoauth's
  front-channel logout endpoint in an iframe. The connection to the MCP server stays: it is
  restoauth's grant for the LibreChat user, not a login, and ends only as described in the user guide.
- The front-channel logout works only if the browser sends Dolibarr's session cookie inside that
  iframe. That is the case when Dolibarr and Keycloak are on the same site (like `erp.example.com` and
  `sso.example.com`). If they are on different domains, browsers that block third-party cookies send
  no cookie, and Dolibarr stays logged in. It also does not reach a Dolibarr session that was opened
  with Dolibarr's own login form instead of **Use OpenID to login**. In those cases log out of
  Dolibarr by hand, or let each person use their own browser profile.

LibreChat sits behind your reverse proxy. The proxy must pass `X-Forwarded-Proto: https` to
LibreChat. Otherwise LibreChat does not set its session cookie during the Keycloak login, and the
login fails with "Unable to verify authorization request state" in LibreChat's log.

### `librechat.yaml`: the Dolibarr MCP server

Add three parts to `librechat.yaml`. Keep the `version` line and everything else in the file.

**`mcpServers`:** the MCP server, under the name `dolibarr`:

```yaml
mcpServers:
  dolibarr:
    type: streamable-http
    # Exactly the MCP server's MCP_RESOURCE_URL.
    url: https://mcp.example.com/mcp
    title: Dolibarr
    description: Third parties, invoices, proposals, orders and products from Dolibarr, with your own Dolibarr rights
    # Every user connects with their own Dolibarr account.
    requiresOAuth: true
    # No "oauth:" block: LibreChat finds restoauth through the MCP server's metadata
    # and registers itself with restoauth dynamically.
```

- The name `dolibarr` is part of LibreChat's callback URL
  (`https://chat.example.com/api/mcp/dolibarr/oauth/callback`). If you choose another name, the
  entry in restoauth's redirect allowlist changes with it.
- **No `oauth:` block.** LibreChat reads the MCP server's metadata, finds restoauth as the
  authorization server and registers itself there (dynamic client registration). An `oauth:` block
  is for clients registered by hand, with fixed endpoints and client ID, which this setup does not
  use.
- **No `serverInstructions`.** The MCP server sends instructions with its `initialize` answer: what
  the Dolibarr tools are for and that they act with the user's own Dolibarr rights. LibreChat has a
  [`serverInstructions`](https://www.librechat.ai/docs/configuration/librechat_yaml/object_structure/mcp_servers)
  option to pass them to the model; this setup does not depend on it.

**`mcpSettings`:** the hosts LibreChat may contact for MCP:

```yaml
mcpSettings:
  allowedDomains:
    - "https://mcp.example.com"
    - "https://erp.example.com"
```

- List **both** hosts. LibreChat checks the MCP server's URL against this list, and also restoauth's
  OAuth endpoints on the Dolibarr host (metadata, registration, token). A host that is not listed is
  only allowed if it resolves to a public IP address. In most companies Dolibarr resolves to a
  private address, and the connection then fails with "OAuth ... resolves to a private IP address"
  in LibreChat's log.
- Once `allowedDomains` is set, LibreChat contacts **only** the listed hosts for MCP. If you already
  have other MCP servers, add their hosts too.

**`modelSpecs`:** a model entry with the Dolibarr server switched on:

```yaml
modelSpecs:
  list:
    - name: dolibarr-assistant
      label: Dolibarr assistant
      description: Answers questions about Dolibarr with your own Dolibarr rights
      preset:
        # An endpoint and model you have already set up in LibreChat.
        endpoint: <your endpoint>
        model: <your model>
      mcpServers:
        - dolibarr
```

Users who pick **Dolibarr assistant** in the model menu have the `dolibarr` server switched on in the
chat. Users of other models can switch it on themselves in the **+** menu of the chat input, section
**MCP Servers**. Use a model that supports tool calls. If `modelSpecs` already exists, add the entry
to its `list`.

**Option: Dolibarr assistant preselected.** To start every new chat with the Dolibarr assistant and
the `dolibarr` server switched on, without a click, add three keys (LibreChat
[`modelSpecs`](https://www.librechat.ai/docs/configuration/librechat_yaml/object_structure/model_specs)):

```yaml
modelSpecs:
  # Model specs come before the model a user chose last.
  prioritize: true
  # false: users may still pick other models and endpoints.
  enforce: false
  list:
    - name: dolibarr-assistant
      # This spec is the default for new chats.
      default: true
      # ... label, description, preset and mcpServers as above ...
```

Users can still pick another model, switch the `dolibarr` server off for a chat (the **×** on its
chip in the chat input), and switch it on again. With `enforce: true` they could use only the listed
model specs.

### restoauth: allow LibreChat's callback

LibreChat registers itself with restoauth with the callback
`https://chat.example.com/api/mcp/dolibarr/oauth/callback`. restoauth accepts the registration only
if this callback is on its allowlist. In Dolibarr, **Setup** → **Modules** → **REST-OAuth** → gear
icon:

| Field | Value |
|---|---|
| Allowed redirect URIs | `https://chat.example.com/api/mcp/dolibarr/oauth/callback` (LibreChat's MCP callback, exactly: `DOMAIN_SERVER` + `/api/mcp/<server name>/oauth/callback`) |
| Allowed resources | `https://mcp.example.com/mcp` (the MCP server's `MCP_RESOURCE_URL`) |
| Allow loopback redirects | Off |

**Allow loopback redirects** On would let any client with a `localhost` callback register, including
one a user runs on their own computer. Use it only for local tests, never on a production Dolibarr.

## Check list

Each check builds on the one before; fix a failing check before you go on. Use a private browser
window for the login checks, so that no earlier Dolibarr or Keycloak session gets in the way.

### 1. Keycloak's realm answers

```sh
curl -s https://sso.example.com/realms/example/.well-known/openid-configuration
```

**Expected:** JSON with `"issuer":"https://sso.example.com/realms/example"` and an
`authorization_endpoint` ending in `/protocol/openid-connect/auth`.

**If not:**

| Result | Fix |
|---|---|
| 404 | Wrong realm name, or your Keycloak uses the legacy `/auth` path: then the URL is `https://sso.example.com/auth/realms/example/...`, and the URLs in Dolibarr need `/auth` too. |
| `issuer` with another host or `http://` | Keycloak does not know its public hostname. Set Keycloak's `hostname` option to `https://sso.example.com`. |

### 2. Dolibarr's login page offers Keycloak

Open `https://erp.example.com/` in a private window.

**Expected:** Dolibarr's login form and a **Use OpenID to login** button.

**If not:**

| Result | Fix |
|---|---|
| No button | `openid_connect` is missing from `$dolibarr_main_authentication`, or **Enable the OpenID Connect authentication mode** is off. |
| Straight to Keycloak, no login form | `$dolibarr_main_authentication` is `openid_connect` alone. Add `,dolibarr`. |
| The button shows "OpenID setup not complete" | The **Authorize URL** or **Client ID** is empty. |

### 3. A Keycloak user logs into Dolibarr

You need a Keycloak user and a Dolibarr user whose login is that Keycloak username. Click **Use
OpenID to login** and log in at Keycloak.

**Expected:** Keycloak's login page for realm `example`, then Dolibarr's home page, logged in as that
Dolibarr user.

**If not:**

| Result | Fix |
|---|---|
| Keycloak: "Invalid parameter: redirect_uri" | **Valid redirect URIs** of the `dolibarr` client is not exactly the **Redirect URL** that Dolibarr's setup page shows. If it starts with `http://`, Dolibarr does not know its public URL; see [Dolibarr: log in with Keycloak](#dolibarr-log-in-with-keycloak). |
| Keycloak: "Client not found" | **Client ID** is not `dolibarr`, or the realm in the URLs is wrong. |
| Back on Dolibarr's login page with an error, or "bad login" | No enabled Dolibarr user whose login is the Keycloak username, or **Login claim** is not `preferred_username`. |
| An error right after the Keycloak login | Usually the token request to Keycloak failed: wrong client secret, or Dolibarr cannot reach `https://sso.example.com` from the server (proxy, firewall, TLS trust). |

**The same user cannot change their username.** Open
`https://sso.example.com/realms/example/account`, log in as that user, and go to **Personal info**.

**Expected:** the **Username** field is read-only.

**If not:** **Edit username** is on in the realm, see [Users in Keycloak](#users-in-keycloak).

### 4. The MCP OAuth flow goes through Keycloak to the consent page

Log out of Dolibarr and Keycloak (or use a new private window). Connect an MCP client to
`https://mcp.example.com/mcp`, for example LibreChat once it is set up (check 6).

**Expected:** the client sends you to Dolibarr's login page; you click **Use OpenID to login**, log
in at Keycloak, and land on restoauth's **consent page**, which names the client and your Dolibarr
user and lists your rights. After consent, the client is connected.

**If not:**

| Result | Fix |
|---|---|
| After the Keycloak login you land on Dolibarr's home page instead of the consent page | Start the connection in the client again: the Dolibarr session now exists, and restoauth goes straight to the consent page. If it happens every time, check `$dolibarr_main_url_root` and `X-Forwarded-Proto` (see [Dolibarr: log in with Keycloak](#dolibarr-log-in-with-keycloak)). |
| The consent page offers only **Deny** | The Dolibarr user lacks the connect right; see [Dolibarr user accounts](#dolibarr-user-accounts). |
| restoauth refuses before the consent page ("resource not allowed", "redirect URI not allowed", discovery 404) | Not related to Keycloak: see restoauth's [check list](https://github.com/storkakos/dolibarr-restoauth#check-list) and [restoauth: allow LibreChat's callback](#restoauth-allow-librechats-callback). |

### 5. A Keycloak user logs into LibreChat

Open `https://chat.example.com/` in a new private window and click **Sign in with Keycloak**.

**Expected:** Keycloak's login page for realm `example`, then LibreChat, logged in with the user's
name. On the first login, LibreChat creates the account.

**If not:**

| Result | Fix |
|---|---|
| No **Sign in with Keycloak** button | `ALLOW_SOCIAL_LOGIN` is not `true`, or `OPENID_CLIENT_ID`/`OPENID_ISSUER` is missing. LibreChat's log says "Configuring OpenID Connect..." when it picks the settings up. Restart LibreChat after changing `.env`. |
| Keycloak: "Invalid parameter: redirect_uri" | `DOMAIN_SERVER` + `OPENID_CALLBACK_URL` is not exactly the **Valid redirect URI** of the `librechat` client. |
| Back in LibreChat with an error, and LibreChat's log says "Unable to verify authorization request state" | The reverse proxy does not pass `X-Forwarded-Proto: https`, so LibreChat did not set its session cookie. See [`.env`](#env-log-in-with-keycloak). |
| Back in LibreChat with an error, and LibreChat's log says "social registration is disabled" | `ALLOW_SOCIAL_REGISTRATION` is not `true`, so LibreChat does not create accounts for new Keycloak users. |
| Back in LibreChat with an error, other message in LibreChat's log | With a PKCE error, set `OPENID_USE_PKCE=false` and restart. A token error usually means a wrong `OPENID_CLIENT_SECRET`. |
| LibreChat's log says it cannot reach the issuer | LibreChat cannot reach `https://sso.example.com` from its server, or does not trust its certificate. For an internal CA, set `NODE_EXTRA_CA_CERTS` to the CA file for LibreChat. |

### 6. Connecting the `dolibarr` server opens restoauth's consent page

In LibreChat, click the **MCP Settings** icon in the left bar. The **MCP Servers** panel lists
**Dolibarr** with an orange dot (not connected). Click the **Connect** icon (the plug) next to it,
then **Continue with OAuth** in the **Connect dolibarr** dialog. (Asking the **Dolibarr assistant** a
question before connecting shows a **Sign-in** button in the chat, which starts the same flow.)

**Expected:** a new browser tab with Dolibarr's login page. Click **Use OpenID to login**. With the
Keycloak session from check 5 you go straight to restoauth's **consent page**, naming
**LibreChat MCP Client** and your Dolibarr user, with the list of your rights. Click **Allow**. LibreChat closes the
tab, and the dot next to **Dolibarr** in the **MCP Servers** panel turns green (**Connected**).

**If not:**

| Result | Fix |
|---|---|
| LibreChat shows an error before any Dolibarr page, and its log names a blocked address, a private IP address or a domain that is not allowed | `mcpSettings.allowedDomains` does not list both `https://mcp.example.com` and `https://erp.example.com`. |
| LibreChat shows an error before any Dolibarr page, and its log says the client registration failed | LibreChat's callback is not on restoauth's allowlist: see [restoauth: allow LibreChat's callback](#restoauth-allow-librechats-callback). It must be exactly `https://chat.example.com/api/mcp/dolibarr/oauth/callback`. If LibreChat sent one starting with `http://localhost:3080`, `DOMAIN_SERVER` is not set. |
| LibreChat's log says the authorization server metadata was not found | The discovery rewrite rule is missing in Dolibarr's web server; see restoauth's README. |
| restoauth says the resource is not allowed | `url` under `mcpServers` → `dolibarr`, `MCP_RESOURCE_URL` and restoauth's **Allowed resources** differ. |
| The consent page offers only **Deny** | The Dolibarr user lacks the connect right. |
| The tab ends on a LibreChat error page after consent | Check LibreChat's log for the token exchange with restoauth, and Dolibarr's log. |

After consent, the user card of that Dolibarr user shows the tab **Connected applications** with the
new connection. LibreChat registers a client of its own for each LibreChat user, so the module's
setup page lists one **LibreChat MCP Client** per user who connected.

### 7. `whoami` names the logged-in Dolibarr user

Start a new chat with the **Dolibarr assistant** model (or with the `dolibarr` server switched on)
and ask:

> Use the whoami tool: who am I in Dolibarr?

**Expected:** the assistant calls the `whoami` tool, and its result contains
`"user": "<first name> <last name> (<login>)"` of the Dolibarr user who gave consent in check 6, the
user matching the Keycloak username. Log in as a second user and repeat: the answer must name the
second user. The assistant then sees what that Dolibarr user may see, and nothing more.

**If not:**

| Result | Fix |
|---|---|
| The model answers without calling a tool | The model does not support tool calls, or the `dolibarr` server is not switched on in this chat. |
| Another person's name | The browser was still logged into Dolibarr as someone else when consent was given in check 6, and restoauth issued the token for that user. Disconnect **Dolibarr** in LibreChat, log out of Dolibarr, and connect again. Each user should give consent in their own browser session. |

### 8. After a logout, Keycloak asks for a password again

In LibreChat, click your name at the bottom left, then **Log out**. Then click **Sign in with
Keycloak**.

**Expected:** after the logout the browser lands on LibreChat's login page (possibly after Keycloak's
"Do you want to log out?" with **Logout**). **Sign in with Keycloak** shows Keycloak's login form
again, and a second user can log in with their own username and password. Opening
`https://erp.example.com/` in the same browser shows Dolibarr's login page, and when the second user
connects **Dolibarr** in LibreChat, restoauth's consent page names *their* account in the **User**
row.

**If not:**

| Result | Fix |
|---|---|
| Keycloak: "Invalid redirect uri" after **Log out** | `OPENID_POST_LOGOUT_REDIRECT_URI` is not listed exactly under **Valid post logout redirect URIs** of the `librechat` client. |
| **Sign in with Keycloak** logs the previous user in without a form | `OPENID_USE_END_SESSION_ENDPOINT` is not `true` (restart LibreChat after changing `.env`), so LibreChat never sent the browser to Keycloak's logout. |
| Dolibarr is still logged in as the previous user, and the consent page names the previous user | The `dolibarr` client has no **Front channel logout** with the **Front-channel logout URL** `https://erp.example.com/custom/restoauth/frontchannel-logout.php`, or Dolibarr and Keycloak are on different sites (see [Log out of Keycloak too](#env-log-out-of-keycloak-too)). Click **Deny**, log out of Dolibarr, then connect again. |
| After the Keycloak login Dolibarr shows an empty page and is logged out again | The front-channel logout endpoint was loaded while Dolibarr's session had already ended. Log in again; the second login works. In LibreChat, connect **Dolibarr** again. |
| LibreChat refuses the login as rate limited (`auth_rate_limited`) | LibreChat allows about 7 logins per 5 minutes per IP. Wait five minutes. |

### 9. Dolibarr's own Logout, then a Keycloak login lands where it should

Log into Dolibarr with Keycloak (check 3), then log out of Dolibarr using Dolibarr's own **Logout**
button (not through LibreChat). Keycloak asks "Do you want to log out?"; click **Logout**. Then log
back in with **Use OpenID to login**.

**Expected:** After Dolibarr's own Logout, the browser is on Dolibarr's login page. Clicking **Use
OpenID to login** sends the browser to Keycloak, and after the Keycloak login the browser lands on
the page Dolibarr expects (the home page, or restoauth's consent page if the login was started from
the MCP OAuth flow). No empty page, no unexpected redirect to a logout page.

**If not:**

| Result | Fix |
|---|---|
| After the Keycloak login Dolibarr shows an empty page or redirects to a logout page | The front-channel logout endpoint was loaded while Dolibarr's session was already ended and set a return URL. This should not happen with restoauth's endpoint; if it does, check that the endpoint is reachable and returns correctly. |

## Both MCP servers in one LibreChat

To offer Dolibarr and iTop in the same LibreChat, run both MCP servers side by side and add both to
the same `librechat.yaml`. This section lists only what differs from the single-server setup above.
The iTop side (iTop's own settings and callback) is in the
[iTop MCP server's example setup](https://github.com/storkakos/itop-mcp-server/blob/main/docs/setup/example-keycloak-librechat.md).

| Example | What it is |
|---|---|
| `https://mcp-erp.example.com/mcp` | Dolibarr MCP server (its `MCP_RESOURCE_URL`) |
| `https://mcp-itop.example.com/mcp` | iTop MCP server (its `MCP_RESOURCE_URL`) |
| `https://chat.example.com/api/mcp/dolibarr/oauth/callback` | LibreChat's callback for Dolibarr, on **restoauth's** redirect allowlist |
| `https://chat.example.com/api/mcp/itop/oauth/callback` | LibreChat's callback for iTop, on **iTop's** redirect allowlist |

- **Each server has its own public hostname (or path) and its own resource URL.** Both MCP servers
  listen on their own port behind the reverse proxy, and each has its own `MCP_RESOURCE_URL`. The two
  servers must not share a URL.
- **Each server has its own OAuth callback**, built from its name in `librechat.yaml`
  (`/api/mcp/<server name>/oauth/callback`), so the names `dolibarr` and `itop` give two different
  callbacks. Each goes only on the allowlist of its own system: Dolibarr's in restoauth's **Allowed
  redirect URIs**, iTop's in `redirect_uris` of altioo-oauth-server. Each system's **Allowed
  resources** lists only its own MCP server's URL.
- **`allowedDomains` lists all four hosts:** both MCP servers and both systems (Dolibarr and iTop).
  A host that is missing fails as described under [`mcpSettings`](#librechatyaml-the-dolibarr-mcp-server).
- **One Keycloak client for LibreChat.** Both systems use the same Keycloak realm and the same
  `librechat` client for the login to LibreChat itself. The OAuth flows of the two MCP servers do
  not involve that client.

`librechat.yaml`:

```yaml
mcpServers:
  dolibarr:
    type: streamable-http
    url: https://mcp-erp.example.com/mcp
    title: Dolibarr
    description: Third parties, invoices, proposals, orders and products from Dolibarr, with your own Dolibarr rights
    requiresOAuth: true
  itop:
    type: streamable-http
    url: https://mcp-itop.example.com/mcp
    title: iTop
    description: Tickets, CIs and contacts from iTop, with your own iTop rights
    requiresOAuth: true

mcpSettings:
  allowedDomains:
    - "https://mcp-erp.example.com"
    - "https://mcp-itop.example.com"
    - "https://erp.example.com"
    - "https://itop.example.com"

modelSpecs:
  list:
    - name: itop-dolibarr-assistant
      label: iTop + Dolibarr assistant
      description: Answers questions about iTop and Dolibarr with your own rights in each
      preset:
        # An endpoint and model you have already set up in LibreChat.
        endpoint: <your endpoint>
        model: <your model>
      mcpServers:
        - dolibarr
        - itop
```

Keep the single-server specs next to it if you want them: a spec with `mcpServers: [dolibarr]` only
offers Dolibarr. The options for preselecting a model spec work as described above.

**Check:** each user connects both servers once (each shows its own consent page, in the user's own
Dolibarr or iTop session), then starts a chat with the **iTop + Dolibarr assistant** and asks for
both `whoami` tools:

> Use the whoami tool of Dolibarr and the whoami tool of iTop: who am I in each?

**Expected:** two tool calls, one named after each server. Dolibarr's result contains `"user"` with
the Dolibarr user, iTop's result names the iTop person. The names differ if the user has different
display names in the two systems.

**If not:** a server whose OAuth connection fails shows the symptoms of the single-server
[check list](#check-list) (check 6) for that server only; the other one keeps working.

Tested in a combined run on the test VM: one Keycloak realm, one LibreChat v0.8.9, Dolibarr 23.0.4
with restoauth 0.3.0 and iTop 3.2.3 with altioo-oauth-server, both MCP servers behind one TLS proxy
under the hostnames of the table above. LibreChat loaded exactly this configuration, and an MCP
client went through the OAuth flow (Keycloak login, consent) of both servers and called both
`whoami` tools. The chat itself, one model calling both tools, was verified in an earlier combined
run with a model behind LibreChat.
