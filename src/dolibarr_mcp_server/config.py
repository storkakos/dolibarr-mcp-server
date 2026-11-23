"""Configuration from the environment. Every setting is documented in `.env.example`.

Required:  DOLIBARR_URL               base URL of Dolibarr (the REST API is <DOLIBARR_URL>/api/index.php)
           DOLIBARR_OAUTH_ISSUER      issuer of restoauth, exactly as its setup page shows it
           MCP_RESOURCE_URL           public URL of this MCP server, as MCP clients reach it
Optional:  MCP_MAX_ROWS               (default: 50)
           MCP_RIGHTS_CACHE_SECONDS   (default: 30, 0 = no cache)
           MCP_HOST                   (default: 0.0.0.0, all interfaces inside the container)
           MCP_PORT                   (default: 8131)
           MCP_AUDIT_LOG              (default: /data/logs/mcp-dolibarr-audit.log)
           SSL_CERT_FILE              CA bundle (PEM) for a Dolibarr with an internally signed certificate
                                      (default: unset, the built-in public CAs)

A missing required value never falls back to localhost or a developer machine: startup stops with a
message that names the variable. A malformed value (no http(s) URL, not a number, out of range) stops
startup the same way.

SSL_CERT_FILE is read by the HTTP client itself (httpx with trust_env); the bundle replaces the built-in
public CAs. It is checked here only so that a missing, unreadable or empty bundle stops startup instead of
turning every token check into a 401. Certificate verification is never turned off.
"""
from __future__ import annotations

import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_MAX_ROWS = 50
DEFAULT_RIGHTS_CACHE_SECONDS = 30
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8131
DEFAULT_AUDIT_LOG = "/data/logs/mcp-dolibarr-audit.log"


class ConfigError(ValueError):
    """Missing or invalid configuration; the message names the variable."""


@dataclass(frozen=True)
class Config:
    dolibarr_url: str
    issuer: str
    resource_url: str
    max_rows: int
    rights_cache_seconds: int
    host: str
    port: int
    audit_log: str
    ca_bundle: str | None


def _optional(env: Mapping[str, str], name: str) -> str | None:
    value = (env.get(name) or "").strip()
    return value or None


def _required(env: Mapping[str, str], name: str) -> str:
    value = _optional(env, name)
    if value is None:
        raise ConfigError(f"{name} is not set (required, see .env.example)")
    return value


def _http_url(env: Mapping[str, str], name: str) -> str:
    """A required http(s) URL with a host, without query or fragment."""
    value = _required(env, name)
    parts = urlsplit(value)
    try:
        hostname = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        hostname = None
    if parts.scheme not in ("http", "https") or not hostname or parts.query or parts.fragment:
        raise ConfigError(f"{name} must be an http(s) URL with a host, but is {value!r}")
    return value


def _int(env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int) -> int:
    value = _optional(env, name)
    if value is None:
        return default
    try:
        number = int(value)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, but is {value!r}") from None
    if not minimum <= number <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}, but is {number}")
    return number


def _ca_bundle(env: Mapping[str, str], name: str) -> str | None:
    """An optional CA bundle: a readable PEM file with at least one CA certificate."""
    path = _optional(env, name)
    if path is None:
        return None
    try:
        context = ssl.create_default_context(cafile=path)
    except OSError as e:  # missing or unreadable file (ssl.SSLError is an OSError, handled below)
        if isinstance(e, ssl.SSLError):
            raise ConfigError(f"{name} must be a PEM file with CA certificates, but '{path}' is not") from None
        raise ConfigError(f"{name} names a CA bundle that cannot be read: '{path}' ({e.strerror})") from None
    if not context.get_ca_certs():
        raise ConfigError(f"{name} must be a PEM file with CA certificates, but '{path}' contains none")
    return path


def load_config(env: Mapping[str, str]) -> Config:
    return Config(
        dolibarr_url=_http_url(env, "DOLIBARR_URL").rstrip("/"),
        issuer=_http_url(env, "DOLIBARR_OAUTH_ISSUER").rstrip("/"),
        resource_url=_http_url(env, "MCP_RESOURCE_URL"),
        max_rows=_int(env, "MCP_MAX_ROWS", DEFAULT_MAX_ROWS, 1, 10_000),
        rights_cache_seconds=_int(env, "MCP_RIGHTS_CACHE_SECONDS", DEFAULT_RIGHTS_CACHE_SECONDS, 0, 3600),
        host=_optional(env, "MCP_HOST") or DEFAULT_HOST,
        port=_int(env, "MCP_PORT", DEFAULT_PORT, 1, 65535),
        audit_log=_optional(env, "MCP_AUDIT_LOG") or DEFAULT_AUDIT_LOG,
        ca_bundle=_ca_bundle(env, "SSL_CERT_FILE"),
    )
