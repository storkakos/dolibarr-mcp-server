"""The test suite never writes to the operator's data folders.

The session fixture `operator_data_untouched` in conftest.py fails the run if the default audit log
location or a logs folder next to the source changes. This test checks the other half: the servers the
tests start write their audit log into a pytest temp folder.
"""
from __future__ import annotations

import os
from pathlib import Path

from dolibarr_mcp_server.config import DEFAULT_AUDIT_LOG


def test_session_audit_log_is_in_a_pytest_temp_folder(client, dolibarr, audit, tmp_path_factory):
    client.call_tool("whoami")

    log = Path(os.environ["MCP_AUDIT_LOG"]).resolve()
    assert log.is_relative_to(tmp_path_factory.getbasetemp().resolve())
    assert log != Path(DEFAULT_AUDIT_LOG).resolve()
    assert audit.entries(), "the call should have been logged in the temp folder"
