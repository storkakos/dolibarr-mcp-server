"""Test seam: the MCP server over real HTTP, with a fake Dolibarr behind it.

Tests act like an MCP client (JSON-RPC POSTs to /mcp with a Bearer token, GETs on the
.well-known metadata). Nothing inside the server is mocked.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import httpx
import pytest

from fake_dolibarr import FakeDolibarr, User, free_port, serve_in_thread

RESOURCE_URL = "https://mcp.example.test/mcp"
ISSUER = "https://dolibarr.example.test/custom/restoauth"
VALID_TOKEN = "valid-token-0123456789abcdef0123456789abcdef"


@pytest.fixture(scope="session")
def fake_dolibarr() -> FakeDolibarr:
    dolibarr = FakeDolibarr()
    port = free_port()
    dolibarr.base_url = f"http://127.0.0.1:{port}"
    serve_in_thread(dolibarr.app(), port)
    return dolibarr


@pytest.fixture(scope="session")
def mcp_server(fake_dolibarr, tmp_path_factory) -> str:
    """Start the MCP server once per session; returns its base URL."""
    port = free_port()
    os.environ.update({
        "DOLIBARR_URL": fake_dolibarr.base_url,
        "DOLIBARR_OAUTH_ISSUER": ISSUER,
        "MCP_RESOURCE_URL": RESOURCE_URL,
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(port),
        # The server caches restoauth/me per token; tests change users and rights between calls.
        "MCP_RIGHTS_CACHE_SECONDS": "0",
        "MCP_AUDIT_LOG": str(tmp_path_factory.mktemp("logs") / "audit.log"),
    })
    # Configuration is read at import time, so import only after the environment is set.
    server = importlib.import_module("dolibarr_mcp_server.server")
    serve_in_thread(server.mcp.streamable_http_app(), port)
    return f"http://127.0.0.1:{port}"


@pytest.fixture
def dolibarr(fake_dolibarr) -> FakeDolibarr:
    """The fake Dolibarr, reset for each test, accepting VALID_TOKEN for a user with all read rights."""
    fake_dolibarr.reset()
    fake_dolibarr.tokens[VALID_TOKEN] = User()
    return fake_dolibarr


class MCPClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.http = httpx.Client(timeout=30)
        self._id = 0

    def post(self, method: str, params: dict | None = None, token: str | None = None) -> httpx.Response:
        self._id += 1
        headers = {"Accept": "application/json, text/event-stream"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        body = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        return self.http.post(f"{self.base_url}/mcp", json=body, headers=headers)

    def call_tool(self, name: str, arguments: dict | None = None, token: str = VALID_TOKEN) -> httpx.Response:
        return self.post("tools/call", {"name": name, "arguments": arguments or {}}, token=token)

    def tool_names(self, token: str = VALID_TOKEN) -> set[str]:
        r = self.post("tools/list", token=token)
        assert r.status_code == 200, r.text
        return {t["name"] for t in r.json()["result"]["tools"]}


@pytest.fixture
def client(mcp_server) -> MCPClient:
    c = MCPClient(mcp_server)
    yield c
    c.http.close()


@pytest.fixture
def audit(mcp_server):
    """Collects the audit lines written during the test."""
    return AuditLog(Path(os.environ["MCP_AUDIT_LOG"]))


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.start = path.stat().st_size if path.exists() else 0

    def raw(self) -> str:
        if not self.path.exists():
            return ""
        with self.path.open("rb") as f:
            f.seek(self.start)
            return f.read().decode("utf-8")

    def entries(self) -> list[dict]:
        return [json.loads(line) for line in self.raw().splitlines()]
