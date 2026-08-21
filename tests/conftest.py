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
from benethos_lexware_office_mcp import server as _server  # noqa: F401
from benethos_lexware_office_mcp.policy import ToolPolicy, preset


@pytest.fixture(autouse=True)
def policy_file_off_this_machine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Give every test its own policy file, with every tool enabled.

    Two things at once, and both are deliberate. The file is **not** the one
    this machine uses, so the suite reports on the code rather than on a
    laptop. And it enables everything, because a test about `search_vouchers`
    is not also a test about whether somebody switched it on - the tests that
    are about that make their own file and name it through
    `Settings(tool_policy_path=...)`.

    Importing the server package first is what fills the tool registry, since
    `classify` records a tool as it is defined.
    """
    # Beside `tmp_path`, not inside it: many tests use `tmp_path` as the
    # download directory and count what is in it, so a policy file - or a
    # directory holding one - would show up as a download.
    target = tmp_path.parent / f"{tmp_path.name}-policy" / "tools.json"
    ToolPolicy(target).save(preset("all"))
    monkeypatch.setattr(config, "tool_policy_file", lambda: target)
    return target
