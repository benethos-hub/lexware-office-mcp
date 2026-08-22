"""Telling a client that the tool list moved, and only when it did."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from benethos_lexware_office_mcp import server as server_module
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools, preset
from benethos_lexware_office_mcp.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def quick_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two seconds is right in production and far too long in a test."""
    monkeypatch.setattr(server_module, "POLICY_POLL_SECONDS", 0.01)


class Session:
    """A client that counts how often it was told to ask again."""

    def __init__(self, fail: bool = False) -> None:
        self.told = 0
        self.fail = fail

    async def send_tool_list_changed(self) -> None:
        if self.fail:
            raise RuntimeError("this session is gone")
        self.told += 1


class Ctx:
    def __init__(self, session: Session) -> None:
        self.session = session


@pytest.fixture
def policy(tmp_path: Path) -> Path:
    path = tmp_path / "tools.json"
    ToolPolicy(path).save(preset("read-only"))
    return path


def rewrite(path: Path, flags: dict[str, bool]) -> None:
    path.write_text(json.dumps(flags), encoding="utf-8")


async def settle(times: int = 8) -> None:
    """Give the watcher a few turns of its loop."""
    for _ in range(times):
        await asyncio.sleep(0.01)


# -- the announcement -------------------------------------------------------


async def test_the_capability_is_announced(policy: Path) -> None:
    """A notification for a capability nobody promised may be ignored.

    Bound once for every transport: `run_stdio_async` and its two HTTP
    siblings all call `create_initialization_options()` with no arguments.
    """
    server = build_server(Settings(tool_policy_path=policy))

    options = server._lowlevel_server.create_initialization_options()

    assert options.capabilities.tools is not None
    assert options.capabilities.tools.list_changed is True


# -- the watcher ------------------------------------------------------------


async def test_nothing_watches_until_a_client_asks(policy: Path) -> None:
    """No session means nobody to tell, and no task to leave behind."""
    server = build_server(Settings(tool_policy_path=policy))

    await server.list_tools()

    assert server._watcher is None


async def test_a_changed_list_is_announced(policy: Path) -> None:
    server = build_server(Settings(tool_policy_path=policy))
    session = Session()
    await server._handle_list_tools(Ctx(session), None)
    try:
        rewrite(policy, dict.fromkeys(known_tools(), True))
        await settle()

        assert session.told == 1
    finally:
        await server.stop_watching()


async def test_writing_the_same_flags_again_is_not_a_change(policy: Path) -> None:
    """The interface rewrites the whole file on every save.

    Watching the timestamp would announce a change on every click that
    changed nothing.
    """
    server = build_server(Settings(tool_policy_path=policy))
    session = Session()
    await server._handle_list_tools(Ctx(session), None)
    try:
        for _ in range(3):
            ToolPolicy(policy).save(preset("read-only"))
            await settle(3)

        assert session.told == 0
    finally:
        await server.stop_watching()


async def test_every_session_is_told(policy: Path) -> None:
    """One client over stdio, several over HTTP later."""
    server = build_server(Settings(tool_policy_path=policy))
    first, second = Session(), Session()
    await server._handle_list_tools(Ctx(first), None)
    await server._handle_list_tools(Ctx(second), None)
    try:
        rewrite(policy, dict.fromkeys(known_tools(), True))
        await settle()

        assert (first.told, second.told) == (1, 1)
    finally:
        await server.stop_watching()


async def test_a_session_that_is_gone_is_dropped(policy: Path) -> None:
    server = build_server(Settings(tool_policy_path=policy))
    dead, alive = Session(fail=True), Session()
    await server._handle_list_tools(Ctx(dead), None)
    await server._handle_list_tools(Ctx(alive), None)
    try:
        rewrite(policy, dict.fromkeys(known_tools(), True))
        await settle()

        assert dead not in server._sessions
        assert alive.told == 1
    finally:
        await server.stop_watching()


async def test_listing_again_does_not_start_a_second_watcher(policy: Path) -> None:
    server = build_server(Settings(tool_policy_path=policy))
    session = Session()
    await server._handle_list_tools(Ctx(session), None)
    first = server._watcher
    try:
        await server._handle_list_tools(Ctx(session), None)

        assert server._watcher is first
    finally:
        await server.stop_watching()


async def test_the_watcher_can_be_stopped(policy: Path) -> None:
    """A task that outlives the process it belongs to is a leak."""
    server = build_server(Settings(tool_policy_path=policy))
    await server._handle_list_tools(Ctx(Session()), None)
    task = server._watcher

    await server.stop_watching()

    assert task is not None and task.done()
    assert server._watcher is None
    await server.stop_watching()  # and again, without complaining


async def test_stopping_never_started_is_harmless(policy: Path) -> None:
    server = build_server(Settings(tool_policy_path=policy))

    await server.stop_watching()


# -- what it does not do ----------------------------------------------------


async def test_enforcement_never_waits_for_the_notification(policy: Path) -> None:
    """The list is filtered from the file on every request regardless.

    A client that ignores the notification, or never gets one, still cannot
    call a tool that has been switched off.
    """
    server = build_server(Settings(tool_policy_path=policy))
    session = Session()
    await server._handle_list_tools(Ctx(session), None)
    try:
        rewrite(policy, {"get_profile": True})

        names = {tool.name for tool in await server.list_tools()}

        assert names == {"get_profile"}
        assert session.told == 0  # before the watcher has even looked
    finally:
        await server.stop_watching()
