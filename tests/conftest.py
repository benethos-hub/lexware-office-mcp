"""Isolation the whole suite depends on.

Tests must not read configuration belonging to the machine they run on. That
is not a hypothetical: three tests once passed or failed according to whether
the developer's own `.env` said `read` or `write`, which made the suite a
report about one laptop rather than about the code.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from benethos_lexware_office_mcp import server as _server  # noqa: F401
from benethos_lexware_office_mcp.configui import probe
from benethos_lexware_office_mcp.logbook.access import ACCESS_LOGGER
from benethos_lexware_office_mcp.logbook.output import LIBRARIES, PACKAGE
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools
from benethos_lexware_office_mcp.settings import locations
from helpers import OPEN_PROVIDERS, capture_lines


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
    monkeypatch.setattr(locations, "tool_policy_file", lambda: target)
    return target


@pytest.fixture(autouse=True)
async def providers_closed() -> AsyncIterator[None]:
    """Close every provider the test built, after it, passed or failed."""
    yield
    while OPEN_PROVIDERS:
        await OPEN_PROVIDERS.pop().aclose()


@pytest.fixture(autouse=True)
def no_account_from_another_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """The account the last connection test found is held by the process.

    Every page of the configuration interface names it, so one test's check
    would otherwise be on the next test's pages.
    """
    monkeypatch.setattr(probe, "_last", None)


@pytest.fixture
def lines(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """The INFO lines this package writes, as the server configures itself.

    A suite that wants DEBUG as well overrides it, see test_logbook_api.py.
    """
    return capture_lines(caplog, "INFO")


@pytest.fixture(autouse=True)
def logging_as_it_was() -> Iterator[None]:
    """Undo whatever a test's call of `logbook.configure` did to logging.

    Levels, handlers and filters live on loggers that belong to the process,
    not to a test. A test that starts the server at WARNING would otherwise
    leave this package at WARNING for every test after it, and a line that
    one of those expects would go missing depending on the order they ran in.
    """
    names = ["", PACKAGE, *LIBRARIES, "uvicorn.error", ACCESS_LOGGER]
    saved = {
        name: (
            logging.getLogger(name).level,
            list(logging.getLogger(name).handlers),
            list(logging.getLogger(name).filters),
        )
        for name in names
    }
    yield
    for name, (level, handlers, filters) in saved.items():
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.handlers[:] = handlers
        logger.filters[:] = filters


@pytest.fixture
def no_configuration_from_this_machine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``.env`` and no environment variable belonging to the developer.

    The same concern as the fixture above, one level further out. Anything
    that resolves settings - and the configuration interface resolves them on
    every page - would otherwise report on whichever machine ran the suite:
    the checkout's own `config/.env` is a candidate, and so is the per-user
    configuration directory.

    The search is pointed at a directory that does not exist rather than
    emptied. A candidate list has to have a first entry: that is the answer to
    "where would a file go", which a message names when none exists yet.
    """
    nowhere = tmp_path / "no-configuration-here"
    monkeypatch.setattr(
        locations, "config_candidates", lambda name, cwd=None: [nowhere / name]
    )
    for key in [name for name in os.environ if name.startswith("LXO_MCP_")]:
        monkeypatch.delenv(key, raising=False)
