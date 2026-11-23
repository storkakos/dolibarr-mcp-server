"""Configuration contract: the server is started as a real process with a given environment.

Checked from outside: exit code and startup output, the protected resource metadata, and what
reaches the fake Dolibarr. Only the defaults that would make a server write outside the test's temp
folders (the audit log under /data) are read from the loaded configuration instead.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

from conftest import VALID_TOKEN
from dolibarr_mcp_server.config import load_config
from fake_dolibarr import free_port

REPO = Path(__file__).resolve().parent.parent
RESOURCE_URL = "https://mcp.customer.test/mcp"
ISSUER = "https://erp.customer.test/custom/restoauth"
CONFIG_VARS = ("DOLIBARR_URL", "DOLIBARR_OAUTH_ISSUER", "MCP_RESOURCE_URL", "MCP_HOST", "MCP_PORT",
               "MCP_MAX_ROWS", "MCP_RIGHTS_CACHE_SECONDS", "MCP_AUDIT_LOG", "SSL_CERT_FILE",
               # read by docker compose on the host, not by the server
               "MCP_PUBLISH_PORT", "MCP_LOG_DIR")
REQUIRED = ("DOLIBARR_URL", "DOLIBARR_OAUTH_ISSUER", "MCP_RESOURCE_URL")


def _env(**config: str) -> dict[str, str]:
    """The current environment without any server setting, plus the given ones."""
    env = {k: v for k, v in os.environ.items() if k not in CONFIG_VARS}
    env.update(config)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _base(**overrides: str | None) -> dict[str, str]:
    """A complete, valid configuration that does not listen on a fixed port; None removes a value."""
    config = {"DOLIBARR_URL": "https://erp.customer.test", "DOLIBARR_OAUTH_ISSUER": ISSUER,
              "MCP_RESOURCE_URL": RESOURCE_URL, "MCP_HOST": "127.0.0.1", "MCP_PORT": str(free_port())}
    config.update(overrides)
    return {k: v for k, v in config.items() if v is not None}


def _start(python_args: list[str] | None = None, **config: str) -> subprocess.Popen:
    """Start the server as `python -m dolibarr_mcp_server.server`, or as `python <python_args>`."""
    # Output goes to a temp file, not a pipe: nobody reads the pipe while the server runs, and once
    # its buffer is full the server blocks on logging and stops answering.
    output = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    args = python_args or ["-m", "dolibarr_mcp_server.server"]
    proc = subprocess.Popen([sys.executable, *args], env=_env(**config),
                            stdout=output, stderr=subprocess.STDOUT, text=True)
    proc.output = output
    return proc


def _output(proc: subprocess.Popen) -> str:
    proc.output.seek(0)
    return proc.output.read()


def _run_until_exit(cwd: Path | None = None, **config: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "dolibarr_mcp_server.server"], env=_env(**config),
                          capture_output=True, text=True, timeout=30, cwd=cwd)


def _assert_stops_and_names(result: subprocess.CompletedProcess, name: str) -> str:
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert name in output
    assert "Configuration error" in output
    assert "Traceback" not in output
    assert "Uvicorn running" not in output
    return output


class RunningServer:
    def __init__(self, proc: subprocess.Popen, base_url: str):
        self.proc = proc
        self.base_url = base_url

    def metadata(self) -> dict:
        r = httpx.get(f"{self.base_url}/.well-known/oauth-protected-resource/mcp", timeout=10)
        assert r.status_code == 200
        return r.json()

    def call_tool(self, name: str, arguments: dict) -> httpx.Response:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        headers = {"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {VALID_TOKEN}"}
        return httpx.post(f"{self.base_url}/mcp", json=body, headers=headers, timeout=30)

    def stop(self) -> str:
        """Stop the server and return everything it printed."""
        self.proc.terminate()
        self.proc.wait(timeout=10)
        out = _output(self.proc)
        self.proc.output.close()
        return out


@pytest.fixture
def start_server(tmp_path):
    started: list[RunningServer] = []

    def start(python_args: list[str] | None = None, **config: str) -> RunningServer:
        port = int(config.setdefault("MCP_PORT", str(free_port())))
        config.setdefault("MCP_AUDIT_LOG", str(tmp_path / "audit.log"))
        proc = _start(python_args, **config)
        server = RunningServer(proc, f"http://127.0.0.1:{port}")
        started.append(server)
        deadline = time.monotonic() + 20
        while True:
            if proc.poll() is not None:
                pytest.fail(f"server exited early:\n{_output(proc)}")
            try:
                httpx.get(f"{server.base_url}/.well-known/oauth-protected-resource/mcp", timeout=1)
                return server
            except httpx.TransportError:
                if time.monotonic() > deadline:
                    pytest.fail("server did not start")
                time.sleep(0.1)

    yield start
    for server in started:
        if server.proc.poll() is None:
            server.stop()


# --- required variables: fail fast, name the variable --------------------------------------

@pytest.mark.parametrize("missing", REQUIRED)
@pytest.mark.parametrize("value", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_missing_required_variable_stops_startup_and_names_it(missing, value):
    result = _run_until_exit(**_base(**{missing: value}))

    _assert_stops_and_names(result, missing)


@pytest.mark.parametrize("var", REQUIRED)
@pytest.mark.parametrize("value", ["erp.customer.test", "ftp://erp.customer.test", "https://",
                                   "https://erp.customer.test:99999", "https://erp.customer.test/?a=1"],
                         ids=["no-scheme", "wrong-scheme", "no-host", "bad-port", "query"])
def test_malformed_url_stops_startup_and_names_it(var, value):
    result = _run_until_exit(**_base(**{var: value}))

    _assert_stops_and_names(result, var)


@pytest.mark.parametrize("var,value", [
    ("MCP_PORT", "abc"), ("MCP_PORT", "0"), ("MCP_PORT", "70000"),
    ("MCP_MAX_ROWS", "abc"), ("MCP_MAX_ROWS", "0"), ("MCP_MAX_ROWS", "-5"),
    ("MCP_RIGHTS_CACHE_SECONDS", "abc"), ("MCP_RIGHTS_CACHE_SECONDS", "-1"), ("MCP_RIGHTS_CACHE_SECONDS", "1.5"),
])
def test_malformed_number_stops_startup_and_names_it(var, value):
    result = _run_until_exit(**_base(**{var: value}))

    _assert_stops_and_names(result, var)


def test_no_fallback_to_a_local_dolibarr(tmp_path):
    # Without any configuration the server must not quietly start against a Dolibarr on localhost.
    result = _run_until_exit(cwd=tmp_path, MCP_PORT=str(free_port()))

    output = _assert_stops_and_names(result, "DOLIBARR_URL")
    assert "127.0.0.1" not in output
    assert not (tmp_path / "logs").exists()  # no audit log next to wherever it was started


# --- issuer and resource in the metadata ----------------------------------------------------

def test_metadata_names_the_configured_resource_and_issuer(start_server):
    server = start_server(**_base(DOLIBARR_OAUTH_ISSUER=ISSUER + "/"))

    doc = server.metadata()

    assert doc["resource"] == RESOURCE_URL
    assert [s.rstrip("/") for s in doc["authorization_servers"]] == [ISSUER]


def test_issuer_is_not_derived_from_dolibarr_url(start_server):
    # restoauth's issuer can be set on its setup page, so the server takes it as given.
    server = start_server(**_base(DOLIBARR_OAUTH_ISSUER="https://login.customer.test/oauth"))

    doc = server.metadata()

    assert [s.rstrip("/") for s in doc["authorization_servers"]] == ["https://login.customer.test/oauth"]


# --- optional settings and their defaults ---------------------------------------------------

def _thirdparty_limits(dolibarr) -> list[str]:
    return [r.query_params.get("limit") for r in dolibarr.requests if r.path == "/thirdparties"]


def _me_calls(dolibarr) -> int:
    return sum(1 for r in dolibarr.requests if r.path == "/restoauth/me")


def test_defaults_for_row_cap_and_rights_cache(start_server, dolibarr):
    server = start_server(**_base(DOLIBARR_URL=dolibarr.base_url))

    for _ in range(2):
        assert server.call_tool("list_thirdparties", {"limit": 999}).status_code == 200

    assert _thirdparty_limits(dolibarr) == ["50", "50"]
    assert _me_calls(dolibarr) == 1  # the second call is answered from the 30-second cache


def test_row_cap_and_rights_cache_are_configurable(start_server, dolibarr):
    server = start_server(**_base(DOLIBARR_URL=dolibarr.base_url, MCP_MAX_ROWS="7", MCP_RIGHTS_CACHE_SECONDS="0"))

    for _ in range(2):
        assert server.call_tool("list_thirdparties", {"limit": 999}).status_code == 200

    assert _thirdparty_limits(dolibarr) == ["7", "7"]
    assert _me_calls(dolibarr) >= 2  # no cache: every call asks Dolibarr again


def test_audit_log_goes_to_configured_path(start_server, dolibarr, tmp_path):
    audit = tmp_path / "custom" / "audit.jsonl"
    server = start_server(**_base(DOLIBARR_URL=dolibarr.base_url, MCP_AUDIT_LOG=str(audit)))

    assert server.call_tool("whoami", {}).status_code == 200

    assert audit.exists()
    assert '"tool": "whoami"' in audit.read_text(encoding="utf-8")


def test_defaults_for_host_port_and_audit_log_are_container_friendly():
    # Read from the loaded configuration, not by starting a server: a server would create the default
    # audit log under /data (C:\data on Windows), and whether that works depends on the machine.
    config = load_config({"DOLIBARR_URL": "https://erp.customer.test", "DOLIBARR_OAUTH_ISSUER": ISSUER,
                          "MCP_RESOURCE_URL": RESOURCE_URL})

    # Listens on all interfaces, and the audit log sits in the data folder (the container mount),
    # not next to the source code.
    assert config.host == "0.0.0.0"
    assert config.port == 8131
    assert config.audit_log == "/data/logs/mcp-dolibarr-audit.log"


def test_unwritable_audit_log_stops_startup_and_names_it(tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("a file where the log folder should be", encoding="utf-8")

    result = _run_until_exit(**_base(MCP_AUDIT_LOG=str(blocker / "audit.log")))

    output = _assert_stops_and_names(result, "MCP_AUDIT_LOG")
    assert "not writable" in output


# --- container healthcheck ------------------------------------------------------------------

def _healthcheck(env: dict[str, str] | None = None, **config: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "dolibarr_mcp_server.healthcheck"], env=env or _env(**config),
                          capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("resource_url", [RESOURCE_URL, "https://mcp.customer.test/dolibarr/mcp",
                                          "https://mcp.customer.test:8443/"])
def test_healthcheck_passes_against_running_server(start_server, dolibarr, resource_url):
    config = _base(DOLIBARR_URL=dolibarr.base_url, MCP_RESOURCE_URL=resource_url)
    start_server(**config)

    result = _healthcheck(**config)

    assert result.returncode == 0, result.stderr
    assert not dolibarr.requests  # needs no token and does not ask Dolibarr


def test_healthcheck_ignores_proxy_from_environment(start_server, dolibarr):
    # An operator sets HTTP(S)_PROXY in .env so the server reaches Dolibarr; the healthcheck's loopback
    # request must not go through that proxy, even without NO_PROXY.
    config = _base(DOLIBARR_URL=dolibarr.base_url)
    start_server(**config)
    dead_proxy = f"http://127.0.0.1:{free_port()}"  # nothing listens there
    env = _env(**config)
    for name in ("NO_PROXY", "no_proxy"):
        env.pop(name, None)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[name] = dead_proxy

    result = _healthcheck(env)

    assert result.returncode == 0, result.stderr


def test_healthcheck_queries_loopback_whatever_the_bind_address(start_server, dolibarr):
    # The healthcheck sees the server's environment, MCP_HOST included, but must not connect to the bind
    # address. Here MCP_HOST names an unreachable documentation address (TEST-NET-1) while the server
    # listens on loopback (so the test never opens a port on all interfaces of the machine it runs on).
    config = _base(DOLIBARR_URL=dolibarr.base_url)
    start_server(**config)

    result = _healthcheck(**{**config, "MCP_HOST": "192.0.2.1"})

    assert result.returncode == 0, result.stderr


def test_healthcheck_fails_without_server():
    result = _healthcheck(**_base())

    assert result.returncode == 1
    assert "unhealthy" in result.stderr


def test_healthcheck_fails_on_missing_configuration():
    result = _healthcheck(**_base(DOLIBARR_URL=None))

    assert result.returncode == 1
    assert "DOLIBARR_URL" in result.stderr


# --- .env.example documents every setting ---------------------------------------------------

def test_env_example_documents_every_setting():
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    lines = text.splitlines()

    for var in CONFIG_VARS:
        assert any(line.lstrip("#").startswith(f"{var}=") for line in lines), f"{var} missing in .env.example"
    for var in REQUIRED:
        # Required settings are set (uncommented) with a placeholder, optional ones are commented out.
        assert any(line.startswith(f"{var}=") for line in lines), var
    # No value that points at a developer machine.
    assert "127.0.0.1:8125" not in text
    assert "localhost" not in text
