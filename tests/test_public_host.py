"""The MCP server behind the operator's TLS reverse proxy.

Requests through the proxy carry the public host name in the Host header. The host (and port) of
MCP_RESOURCE_URL must be accepted; the DNS-rebinding protection stays on for every other host.
Loopback keeps working for the container healthcheck. The protected resource metadata and the 401
challenge always advertise the public URL, never the internal bind address.
"""
from __future__ import annotations

import re

import httpx
import pytest

from conftest import RESOURCE_URL, VALID_TOKEN
from fake_dolibarr import free_port
from test_config import _assert_stops_and_names, _base, _run_until_exit, start_server  # noqa: F401  (fixture)

PUBLIC_METADATA_URL = "https://mcp.example.test/.well-known/oauth-protected-resource/mcp"


def _call_whoami(base_url: str, host: str, origin: str | None = None) -> httpx.Response:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}}
    headers = {"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {VALID_TOKEN}",
               "Host": host}
    if origin is not None:
        headers["Origin"] = origin
    return httpx.post(f"{base_url}/mcp", json=body, headers=headers, timeout=30)


def _challenge(base_url: str, host: str) -> httpx.Response:
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    headers = {"Accept": "application/json, text/event-stream", "Host": host}
    return httpx.post(f"{base_url}/mcp", json=body, headers=headers, timeout=30)


def _resource_metadata_url(response: httpx.Response) -> str:
    m = re.search(r'resource_metadata="([^"]+)"', response.headers["www-authenticate"])
    assert m, response.headers["www-authenticate"]
    return m.group(1)


def _dolibarr_was_called(dolibarr) -> bool:
    # The token check (restoauth/me) runs before the host check; no data request may follow it.
    return bool(dolibarr.data_requests())


# --- metadata and challenge advertise the public URL -----------------------------------------

@pytest.mark.parametrize("host", ["mcp.example.test", "localhost"], ids=["through-proxy", "loopback"])
def test_challenge_advertises_the_public_metadata_url(mcp_server, dolibarr, host):
    port = mcp_server.rsplit(":", 1)[1]
    r = _challenge(mcp_server, host if host != "localhost" else f"localhost:{port}")

    assert r.status_code == 401
    assert _resource_metadata_url(r) == PUBLIC_METADATA_URL
    assert "127.0.0.1" not in r.headers["www-authenticate"]
    assert "localhost" not in r.headers["www-authenticate"]


@pytest.mark.parametrize("host", ["mcp.example.test", "localhost"], ids=["through-proxy", "loopback"])
def test_metadata_names_the_public_resource_url(mcp_server, dolibarr, host):
    port = mcp_server.rsplit(":", 1)[1]
    r = httpx.get(f"{mcp_server}/.well-known/oauth-protected-resource/mcp",
                  headers={"Host": host if host != "localhost" else f"localhost:{port}"}, timeout=10)

    assert r.status_code == 200, r.text
    assert r.json()["resource"] == RESOURCE_URL
    assert "127.0.0.1" not in r.text


def test_public_url_wins_over_a_wildcard_bind_address(start_server, dolibarr):
    # Inside the container the server binds 0.0.0.0; that address must never show up in what it advertises.
    port = free_port()
    server = start_server(**_base(DOLIBARR_URL=dolibarr.base_url, MCP_HOST="0.0.0.0", MCP_PORT=str(port)))

    r = _challenge(server.base_url, "mcp.customer.test")

    assert r.status_code == 401
    assert _resource_metadata_url(r) == "https://mcp.customer.test/.well-known/oauth-protected-resource/mcp"
    doc = server.metadata()
    assert doc["resource"] == "https://mcp.customer.test/mcp"
    assert "0.0.0.0" not in r.headers["www-authenticate"] + str(doc)


# --- MCP_RESOURCE_URL without a port (in-process seam: https://mcp.example.test/mcp) --------

@pytest.mark.parametrize("host", ["mcp.example.test", "mcp.example.test:443"])
def test_public_host_of_resource_url_is_accepted(mcp_server, dolibarr, host):
    r = _call_whoami(mcp_server, host)

    assert r.status_code == 200, r.text
    assert "Max Muster" in r.json()["result"]["content"][0]["text"]


@pytest.mark.parametrize("host", ["evil.test", "mcp.example.test.evil.test", "mcp.example.test:8443",
                                  "evil.test:443"])
def test_unrelated_host_is_refused_with_421(mcp_server, dolibarr, host):
    r = _call_whoami(mcp_server, host)

    assert r.status_code == 421
    assert not _dolibarr_was_called(dolibarr)


@pytest.mark.parametrize("host", ["MCP.Example.TEST", "Mcp.Example.Test:443"])
def test_public_host_in_other_letter_case_is_accepted(mcp_server, dolibarr, host):
    r = _call_whoami(mcp_server, host)

    assert r.status_code == 200, r.text


@pytest.mark.parametrize("host", ["EVIL.test", "MCP.Example.TEST:8443"])
def test_unrelated_host_in_capitals_is_still_refused_with_421(mcp_server, dolibarr, host):
    r = _call_whoami(mcp_server, host)

    assert r.status_code == 421
    assert not _dolibarr_was_called(dolibarr)


@pytest.mark.parametrize("origin", ["https://mcp.example.test", "HTTPS://MCP.Example.Test"])
def test_public_origin_is_accepted_in_any_letter_case(mcp_server, dolibarr, origin):
    r = _call_whoami(mcp_server, "mcp.example.test", origin)

    assert r.status_code == 200, r.text


@pytest.mark.parametrize("origin", ["https://evil.test", "http://mcp.example.test", "https://mcp.example.test:8443"])
def test_foreign_origin_is_refused_with_403(mcp_server, dolibarr, origin):
    r = _call_whoami(mcp_server, "mcp.example.test", origin)

    assert r.status_code == 403
    assert not _dolibarr_was_called(dolibarr)


@pytest.mark.parametrize("loopback", ["localhost", "127.0.0.1"])
def test_loopback_host_keeps_working(mcp_server, dolibarr, loopback):
    port = mcp_server.rsplit(":", 1)[1]

    r = _call_whoami(mcp_server, f"{loopback}:{port}")

    assert r.status_code == 200, r.text


# --- MCP_RESOURCE_URL with an explicit port (separate server process) ------------------------

def test_resource_url_with_explicit_port(start_server, dolibarr):  # noqa: F811
    server = start_server(**_base(DOLIBARR_URL=dolibarr.base_url,
                                  MCP_RESOURCE_URL="https://mcp.customer.test:8443/mcp"))
    port = server.base_url.rsplit(":", 1)[1]

    assert _call_whoami(server.base_url, "mcp.customer.test:8443").status_code == 200
    assert _call_whoami(server.base_url, f"localhost:{port}").status_code == 200
    assert _call_whoami(server.base_url, "mcp.customer.test").status_code == 421
    assert _call_whoami(server.base_url, "mcp.customer.test:9999").status_code == 421
    assert _call_whoami(server.base_url, "mcp.customer.test:8443", "https://mcp.customer.test:8443").status_code == 200
    assert _call_whoami(server.base_url, "mcp.customer.test:8443", "https://mcp.customer.test").status_code == 403
    assert (_resource_metadata_url(_challenge(server.base_url, "mcp.customer.test:8443"))
            == "https://mcp.customer.test:8443/.well-known/oauth-protected-resource/mcp")


@pytest.mark.parametrize(("resource_url", "public_host", "default_port", "origin"), [
    ("https://mcp.customer.test:443/mcp", "mcp.customer.test", 443, "https://mcp.customer.test"),
    ("http://mcp.customer.test:80/mcp", "mcp.customer.test", 80, "http://mcp.customer.test"),
], ids=["https-443", "http-80"])
def test_resource_url_with_default_port_behaves_like_url_without_port(start_server, dolibarr, resource_url,  # noqa: F811
                                                                      public_host, default_port, origin):
    server = start_server(**_base(DOLIBARR_URL=dolibarr.base_url, MCP_RESOURCE_URL=resource_url))

    for host in (public_host, f"{public_host}:{default_port}"):
        r = _call_whoami(server.base_url, host)
        assert r.status_code == 200, (host, r.text)
        assert "Max Muster" in r.json()["result"]["content"][0]["text"]
    assert _call_whoami(server.base_url, public_host, origin).status_code == 200
    assert _call_whoami(server.base_url, public_host, f"{origin}:{default_port}").status_code == 403
    assert _call_whoami(server.base_url, f"{public_host}:8443").status_code == 421


def test_resource_url_with_ipv6_host(start_server, dolibarr):  # noqa: F811
    server = start_server(**_base(DOLIBARR_URL=dolibarr.base_url, MCP_RESOURCE_URL="https://[2001:db8::5]/mcp"))

    assert _call_whoami(server.base_url, "[2001:db8::5]").status_code == 200
    assert _call_whoami(server.base_url, "[2001:db8::5]:443").status_code == 200
    assert _call_whoami(server.base_url, "[2001:db8::6]").status_code == 421


# --- MCP_RESOURCE_URL must name a host -------------------------------------------------------

@pytest.mark.parametrize("value", ["mcp.customer.test/mcp", "ftp://mcp.customer.test/mcp", "https:///mcp"])
def test_resource_url_without_http_host_stops_startup(value):
    result = _run_until_exit(**_base(MCP_RESOURCE_URL=value))

    _assert_stops_and_names(result, "MCP_RESOURCE_URL")
