# Glossary

**MCP server**
This product. Receives tool calls from an MCP client and forwards them to the Dolibarr REST API with the caller's own token. It stores no user secrets and issues no tokens.
_Avoid_: bridge, proxy

**MCP client**
The application a user chats in that calls the MCP server, e.g. LibreChat.
_Avoid_: frontend, chat

**Authorization server**
The component that issues the access token the MCP client sends to the MCP server. Always Dolibarr with the restoauth module; never the identity provider.
_Avoid_: OAuth server (ambiguous), IdP

**restoauth**
The Dolibarr module (separate repo `dolibarr-restoauth`, GPL-3.0-or-later) that makes Dolibarr the authorization server for its own REST API. It also provides `restoauth/me` and `restoauth/endpoints`, the REST extensions the MCP server depends on.
_Avoid_: OAuth module, plugin

**Identity provider**
Where users log in, e.g. Keycloak. It authenticates users for Dolibarr (via `openid_connect`) and for the MCP client, but never issues tokens the MCP server accepts.
_Avoid_: SSO, auth server

**Connect right**
The restoauth right "connect applications via OAuth". Only users who have it, or admins, can authorize an MCP client.

**Rights map**
restoauth's `rights_map.json`: which Dolibarr rights a REST path needs, as a default rule plus exceptions. `restoauth/me` delivers it, and the MCP server filters its tools and checks calls with it.

**Dolibarr prerequisites**
What every customer must set up in Dolibarr before the MCP server works, independent of which identity provider or MCP client they use (API REST and restoauth enabled, allowlists, the connect right, the discovery rewrite rule). Documented in `docs/setup/dolibarr-prerequisites.md`.

**Example setup**
One documented, non-mandatory way to connect an identity provider and an MCP client (Keycloak and LibreChat) to Dolibarr and the MCP server.
_Avoid_: reference installation
