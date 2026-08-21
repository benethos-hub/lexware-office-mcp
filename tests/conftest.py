"""Isolation the whole suite depends on.

Tests must not read configuration belonging to the machine they run on. That
is not a hypothetical: three tests once passed or failed according to whether
the developer's own `.env` said `read` or `write`, which made the suite a
report about one laptop rather than about the code.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from benethos_lexware_office_mcp import config
from benethos_lexware_office_mcp import server as _server  # noqa: F401
from benethos_lexware_office_mcp.configui import state as configui_state
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools


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
    ToolPolicy(target).save(dict.fromkeys(known_tools(), True))
    monkeypatch.setattr(config, "tool_policy_file", lambda: target)
    return target


@pytest.fixture
def no_configuration_from_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``.env`` and no environment variable belonging to the developer.

    The same concern as the fixture above, one level further out. Anything
    that resolves settings - and the configuration interface resolves them on
    every page - would otherwise report on whichever machine ran the suite:
    the checkout's own `config/.env` is a candidate, and so is the per-user
    configuration directory.

    Two references have to be replaced, because `config_candidates` is looked
    up in the module that defines it and in the one that imported it.
    """
    monkeypatch.setattr(config, "config_candidates", lambda name, cwd=None: [])
    monkeypatch.setattr(configui_state, "config_candidates", lambda name, cwd=None: [])
    for key in [name for name in os.environ if name.startswith("LXO_MCP_")]:
        monkeypatch.delenv(key, raising=False)
