"""Dolibarr behind an internal CA: the operator mounts the CA bundle and sets SSL_CERT_FILE.

The fake Dolibarr is served over HTTPS with a certificate from a throwaway test CA. The MCP server runs
as a real process; certificate verification must stay on, so without SSL_CERT_FILE the token check fails.
"""
from __future__ import annotations

import pytest

from conftest import VALID_TOKEN
from fake_dolibarr import FakeDolibarr, User, free_port, serve_in_thread
from test_config import ISSUER, RESOURCE_URL, _assert_stops_and_names, _base, _run_until_exit, start_server  # noqa: F401  (fixture)
from throwaway_ca import make_ca

# An empty value counts as unset, so the CA settings of the test machine play no part.
NO_CA = {"SSL_CERT_FILE": "", "SSL_CERT_DIR": ""}


@pytest.fixture(scope="module")
def tls_dolibarr(tmp_path_factory):
    """A fake Dolibarr on https://localhost:<port> with a certificate from a throwaway CA."""
    files = make_ca(tmp_path_factory.mktemp("ca"), ["localhost", "127.0.0.1"])
    dolibarr = FakeDolibarr()
    port = free_port()
    dolibarr.base_url = f"https://localhost:{port}"
    serve_in_thread(dolibarr.app(), port, ssl_certfile=str(files.cert), ssl_keyfile=str(files.key))
    dolibarr.ca_bundle = files.ca
    return dolibarr


@pytest.fixture
def https_dolibarr(tls_dolibarr):
    tls_dolibarr.reset()
    tls_dolibarr.tokens[VALID_TOKEN] = User()
    return tls_dolibarr


def _start(start_server, dolibarr, **ca):  # noqa: F811
    return start_server(DOLIBARR_URL=dolibarr.base_url, DOLIBARR_OAUTH_ISSUER=ISSUER, MCP_RESOURCE_URL=RESOURCE_URL,
                        MCP_HOST="127.0.0.1", **{**NO_CA, **ca})


def test_with_ssl_cert_file_token_check_and_tool_call_succeed(start_server, https_dolibarr):  # noqa: F811
    server = _start(start_server, https_dolibarr, SSL_CERT_FILE=str(https_dolibarr.ca_bundle))

    r = server.call_tool("list_thirdparties", {})

    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is False, result
    assert [req.path for req in https_dolibarr.requests] == ["/restoauth/me", "/thirdparties"]
    assert {req.authorization for req in https_dolibarr.requests} == {f"Bearer {VALID_TOKEN}"}


def test_without_ssl_cert_file_token_check_fails(start_server, https_dolibarr):  # noqa: F811
    server = _start(start_server, https_dolibarr)

    r = server.call_tool("list_thirdparties", {})

    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")
    # The TLS handshake fails, so not even the token check reaches Dolibarr.
    assert https_dolibarr.requests == []
    output = server.stop()
    assert "Dolibarr not reachable: ConnectError" in output
    assert VALID_TOKEN not in output


def test_bundle_without_the_issuing_ca_is_rejected(start_server, https_dolibarr, tmp_path):  # noqa: F811
    # A valid bundle, but from another CA: verification stays on and the handshake fails.
    other = make_ca(tmp_path / "other", ["localhost"])
    server = _start(start_server, https_dolibarr, SSL_CERT_FILE=str(other.ca))

    r = server.call_tool("list_thirdparties", {})

    assert r.status_code == 401
    assert https_dolibarr.requests == []


@pytest.mark.parametrize("content", [None, "", "not a certificate\n"], ids=["missing", "empty", "not-pem"])
def test_unusable_ca_bundle_stops_startup_and_names_it(tmp_path, content):
    bundle = tmp_path / "ca.pem"
    if content is not None:
        bundle.write_text(content, encoding="utf-8")

    result = _run_until_exit(**_base(**{**NO_CA, "SSL_CERT_FILE": str(bundle)}))

    output = _assert_stops_and_names(result, "SSL_CERT_FILE")
    assert str(bundle) in output
