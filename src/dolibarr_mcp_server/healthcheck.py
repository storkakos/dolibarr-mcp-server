"""Container healthcheck: fetches the protected resource metadata over loopback.

Exit 0 if the server answers with 200, otherwise 1. The metadata path follows RFC 9728 from the path
of MCP_RESOURCE_URL (/mcp -> /.well-known/oauth-protected-resource/mcp); the port is MCP_PORT. The
endpoint answers without a token, so Dolibarr is not asked.

The request always goes straight to 127.0.0.1, never through a proxy from HTTP(S)_PROXY, whatever
NO_PROXY says. That is why MCP_HOST must stay 0.0.0.0 inside the container (see .env.example).
"""
from __future__ import annotations

import os
import sys
import urllib.request
from urllib.parse import urlsplit

from .config import ConfigError, load_config


def metadata_url(env) -> str:
    config = load_config(env)
    path = urlsplit(config.resource_url).path
    if path == "/":
        path = ""
    return f"http://127.0.0.1:{config.port}/.well-known/oauth-protected-resource{path}"


# Empty proxy table: no proxies from the environment, for any URL.
_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main() -> int:
    try:
        url = metadata_url(os.environ)
        with _direct.open(url, timeout=5) as r:
            return 0 if r.status == 200 else 1
    except (ConfigError, OSError) as e:
        print(f"unhealthy: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
