# Dolibarr MCP server

An MCP server for Dolibarr 23: read-only tools, and every call runs with the caller's own Dolibarr token. Dolibarr itself is the authorization server, through the [restoauth](https://github.com/storkakos/dolibarr-restoauth) module (GPL-3.0-or-later, separate repo).

Work in progress: install, configuration and operations chapters follow before the first release.

## Development

The unit tests drive the MCP server over real HTTP with a fake Dolibarr behind it (`tests/fake_dolibarr.py`). They need no Docker:

```sh
python -m venv .venv
.venv/Scripts/python -m pip install --no-deps -r requirements.lock -r requirements-build.lock   # .venv/bin/python on Linux
.venv/Scripts/python -m pip install --no-deps --no-build-isolation -e .
.venv/Scripts/python -m pip install pytest==8.4.2
.venv/Scripts/python -m pip install "pywin32>=310"   # Windows only: the MCP SDK needs it there, the Linux lock file does not list it
.venv/Scripts/python -m pytest -q
```

## Licence

MIT, see [LICENSE](LICENSE).
