"""Isolation the whole suite depends on.

Tests must not read configuration belonging to the machine they run on. That
is not a hypothetical: three tests once passed or failed according to whether
the developer's own `.env` said `read` or `write`, which made the suite a
report about one laptop rather than about the code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_lexware_office_mcp import config


@pytest.fixture(autouse=True)
def policy_file_off_this_machine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point the default policy file at a path no test has written to.

    A test that wants a policy file makes one and names it through
    ``Settings(tool_policy_path=...)``. Every other test gets a file that does
    not exist, which means every tool enabled - the behaviour of an
    installation nobody has configured.
    """
    target = tmp_path / "tools-default.json"
    monkeypatch.setattr(config, "tool_policy_file", lambda: target)
    return target
