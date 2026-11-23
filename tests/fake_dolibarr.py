"""Small fake of the Dolibarr REST API (api/index.php) with the restoauth extensions, for tests.

Serves `restoauth/me` (token check), `restoauth/endpoints` and the list and read endpoints the tools
use, with configurable users and rights, and records what it received, so tests can check what
actually reached Dolibarr.
"""
from __future__ import annotations

import copy
import socket
import threading
import time
from dataclasses import dataclass, field

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

API_PREFIX = "/api/index.php"

# The rights rules restoauth sends with restoauth/me (a trimmed copy of its rights_map.json).
RIGHTS_RULES = {
    "default": {"GET": ["lire", "read"], "POST": ["creer", "write"], "PUT": ["creer", "write"],
                "DELETE": ["supprimer", "delete"]},
    "endpoints": {
        "thirdparties": {"module": "societe"},
        "invoices": {"module": "facture"},
        "proposals": {"module": "propal"},
        "orders": {"module": "commande"},
        "products": {"module": "produit"},
        "status": {"GET": ""},
        "restoauth": {"GET": ""},
    },
    "paths": {
        "GET /thirdparties/{id}/outstandinginvoices": ["societe.lire", "facture.lire"],
    },
}

# Rights of a user who may read everything the curated tools cover.
ALL_READ_RIGHTS = ["societe.lire", "facture.lire", "propal.lire", "commande.lire", "produit.lire"]

ENDPOINTS = [
    {"path": "/thirdparties", "summary": "List third parties"},
    {"path": "/thirdparties/{id}", "summary": "Get a third party"},
    {"path": "/thirdparties/{id}/outstandinginvoices", "summary": "Outstanding invoices"},
    {"path": "/invoices", "summary": "List invoices"},
    {"path": "/invoices/{id}", "summary": "Get an invoice"},
    {"path": "/proposals", "summary": "List proposals"},
    {"path": "/orders", "summary": "List orders"},
    {"path": "/products", "summary": "List products"},
    {"path": "/status", "summary": "API status"},
]

SAMPLE = {
    "thirdparties": [{"id": "1", "name": "Acme GmbH", "client": "1", "town": "Berlin", "status": "1"}],
    "invoices": [{"id": "1", "ref": "FA2611-0001", "socid": "1", "total_ttc": "119.00", "status": "1",
                  "lines": [{"desc": "Service", "qty": "1", "subprice": "100", "total_ttc": "119.00"}]}],
    "proposals": [{"id": "1", "ref": "PR2611-0001", "socid": "1", "total_ttc": "238.00", "status": "1"}],
    "orders": [{"id": "1", "ref": "CO2611-0001", "socid": "1", "total_ttc": "357.00", "status": "1"}],
    "products": [{"id": "1", "ref": "SRV-01", "label": "Consulting hour", "price": "100", "status": "1"}],
}

OUTSTANDING_INVOICES = [{"id": "1", "ref": "FA2611-0001", "socid": "1", "total_ttc": "119.00", "remaintopay": "119.00"}]


@dataclass
class User:
    login: str = "max"
    firstname: str = "Max"
    lastname: str = "Muster"
    admin: int = 0
    rights: list[str] = field(default_factory=lambda: list(ALL_READ_RIGHTS))


@dataclass
class ReceivedRequest:
    path: str
    authorization: str | None
    query_params: dict[str, str]


@dataclass
class FakeDolibarr:
    # token -> user it belongs to
    tokens: dict[str, User] = field(default_factory=dict)
    requests: list[ReceivedRequest] = field(default_factory=list)
    base_url: str = ""
    # seconds from now until issued tokens expire
    token_lifetime: int = 3600
    # Lists have this many rows (None: the sample rows). Dolibarr honours "limit" unless ignore_limit is set,
    # like an endpoint that does not support it.
    list_rows: int | None = None
    ignore_limit: bool = False
    # Answer every request except restoauth/me with this HTTP status and error message.
    fail_status: int | None = None
    fail_message: str = "Internal error"
    # The rights rules restoauth/me delivers (tests may edit them, e.g. drop an exception).
    rights_rules: dict = field(default_factory=lambda: copy.deepcopy(RIGHTS_RULES))

    def reset(self) -> None:
        self.tokens.clear()
        self.requests.clear()
        self.token_lifetime = 3600
        self.list_rows = None
        self.ignore_limit = False
        self.fail_status = None
        self.fail_message = "Internal error"
        self.rights_rules = copy.deepcopy(RIGHTS_RULES)

    def data_requests(self) -> list[ReceivedRequest]:
        """Requests other than the token check (restoauth/me): what a tool asked Dolibarr for."""
        return [r for r in self.requests if r.path != "/restoauth/me"]

    def _rows(self, kind: str, query: dict[str, str]) -> list[dict]:
        if self.list_rows is None:
            rows = SAMPLE[kind]
        else:
            rows = [{"id": str(i), "ref": f"REF-{i}", "name": f"Row {i}", "status": "1"}
                    for i in range(1, self.list_rows + 1)]
        if not self.ignore_limit and query.get("limit", "").isdigit():
            rows = rows[:int(query["limit"])]
        return rows

    def _user(self, request: Request) -> User | None:
        auth = request.headers.get("authorization") or ""
        if not auth.startswith("Bearer "):
            return None
        return self.tokens.get(auth.removeprefix("Bearer "))

    async def _api(self, request: Request) -> Response:
        path = "/" + request.path_params["path"].strip("/")
        self.requests.append(ReceivedRequest(path, request.headers.get("authorization"), dict(request.query_params)))
        user = self._user(request)
        if user is None:
            return JSONResponse({"error": {"code": 401, "message": "Unauthorized"}}, status_code=401)
        if path == "/restoauth/me":
            return JSONResponse({
                "user": {"id": 2, "login": user.login, "firstname": user.firstname, "lastname": user.lastname,
                         "email": f"{user.login}@example.test", "admin": user.admin, "external": False, "socid": 0},
                "entity": 1,
                "dolibarr_version": "23.0.3",
                "modules": ["societe", "facture", "propal", "commande", "produit", "api", "restoauth"],
                "rights": list(user.rights),
                "token": {"type": "restoauth", "expires_at": int(time.time()) + self.token_lifetime,
                          "connection": 1, "client": "Test client"},
                "api_rights_rules": self.rights_rules,
            })
        if self.fail_status is not None:
            return JSONResponse({"error": {"code": self.fail_status, "message": self.fail_message}},
                                status_code=self.fail_status)
        if path == "/restoauth/endpoints":
            return JSONResponse(ENDPOINTS)
        if path == "/status":
            return JSONResponse({"success": {"code": 200, "dolibarr_version": "23.0.3"}})
        parts = path.strip("/").split("/")
        if parts[0] in SAMPLE:
            rows = SAMPLE[parts[0]]
            if len(parts) == 1:
                return JSONResponse(self._rows(parts[0], dict(request.query_params)))
            if len(parts) == 3 and parts[0] == "thirdparties" and parts[2].lower() == "outstandinginvoices":
                return JSONResponse(OUTSTANDING_INVOICES)
            if len(parts) == 2:
                hit = [r for r in rows if r["id"] == parts[1]]
                if hit:
                    return JSONResponse(hit[0])
        return JSONResponse({"error": {"code": 404, "message": "Not found"}}, status_code=404)

    def app(self) -> Starlette:
        return Starlette(routes=[Route(API_PREFIX + "/{path:path}", self._api, methods=["GET"])])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    """Standalone fake Dolibarr for the container smoke test (scripts/smoke-test.sh).

    FAKE_DOLIBARR_TOKENS: comma-separated tokens to accept, each for the default user (Max Muster with
    all read rights); FAKE_DOLIBARR_PORT: listen port (default 8080).
    FAKE_DOLIBARR_SSL_CERTFILE / FAKE_DOLIBARR_SSL_KEYFILE: serve HTTPS with this certificate and key.
    """
    import os

    tokens = [t for t in os.environ.get("FAKE_DOLIBARR_TOKENS", "").split(",") if t]
    dolibarr = FakeDolibarr(tokens={t: User() for t in tokens})
    uvicorn.run(dolibarr.app(), host="0.0.0.0", port=int(os.environ.get("FAKE_DOLIBARR_PORT", "8080")),
                log_level="warning",
                ssl_certfile=os.environ.get("FAKE_DOLIBARR_SSL_CERTFILE") or None,
                ssl_keyfile=os.environ.get("FAKE_DOLIBARR_SSL_KEYFILE") or None)


def serve_in_thread(app, port: int, **uvicorn_options) -> uvicorn.Server:
    """Start an ASGI app with uvicorn on 127.0.0.1:<port> in a daemon thread and wait until it is up."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", **uvicorn_options))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError(f"server on port {port} did not start")
        time.sleep(0.05)
    return server


if __name__ == "__main__":
    main()
