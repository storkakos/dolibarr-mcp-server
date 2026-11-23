# Copy the hardening code from itop-mcp-server instead of sharing a library

`itop-mcp-server` already has the hardening this server needs: a configuration contract with fail-fast validation, a public host behind a reverse proxy, internal CA support, a row cap, input boundary validation, an audit log with redaction, server instructions and a healthcheck that ignores proxy settings and the bind address. We copy that code into this repo and adapt it to Dolibarr, rather than extracting it into a shared Python library that both servers depend on.

Both servers are young, each has only one maintainer, and the two upstream APIs differ (iTop's single `rest.php` endpoint with an `auth_token` header, Dolibarr's REST paths with a Bearer token and a rights map). A shared library now would need its own repo, versioning and release process, and every change would have to be coordinated across three repos before either server stabilises.

## Considered Options

- **Shared library** (e.g. `mcp-server-hardening` on PyPI or as a git dependency). Rejected for now: extra release overhead, and the right seams are not known yet.
- **Copy and adapt.** Chosen. The duplication is deliberate and known.

## Consequences

- A security fix in the hardening code of one server must be checked against the other by hand. Mention the sibling repo in such a ticket.
- Revisit this decision when any of these is true: a third MCP server needs the same hardening; the same fix has had to be made in both repos more than twice; or the copied modules have stayed essentially unchanged in both repos for two releases, which shows the seams are stable enough to extract.
