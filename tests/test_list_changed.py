"""Telling a client that a list moved, and only when it did.

The tool list, when the policy file changed what it allows, and the
download list, when a tool wrote a download.

Two kinds of test. Most hand the server a fake connection and count what
it was told, which is cheap and exact. The ones under *over the wire*
connect a real client through the SDK's own runner, because that is the
path that broke once without any of the others noticing: the runner
builds a session per request, and a server that remembered sessions
told nobody for as long as that had been so.
"""

from __future__ import annotations

import asyncio
import gc
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import CallToolRequestParams

from benethos_lexware_office_mcp import server as server_module
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools, preset
from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.settings import Settings
from helpers import FILE_ID, capture_lines, recorder, server_with, write_policy

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def quick_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two seconds is right in production and far too long in a test."""
    monkeypatch.setattr(server_module, "POLICY_POLL_SECONDS", 0.01)


class Session:
    """A request's session, over a client that counts what it was told.

    Shaped like the SDK's: the session wraps a connection, and the
    connection has the channel a notification outside a request goes on.
    Here all three are this one object, which is what makes the count
    simple.
    """

    def __init__(self, fail: bool = False) -> None:
        self.told = 0
        self.downloads = 0
        self.fail = fail
        self._connection = self
        self.outbound = self

    async def notify(self, method: str, params: Any, opts: Any = None) -> None:
        if self.fail:
            raise RuntimeError("this client is gone")
        if method == "notifications/tools/list_changed":
            self.told += 1
        elif method == "notifications/resources/list_changed":
            self.downloads += 1
        else:
            raise AssertionError(f"unexpected notification {method}")


class Ctx:
    def __init__(self, session: Session) -> None:
        self.session = session


@pytest.fixture
def policy(tmp_path: Path) -> Path:
    path = tmp_path / "tools.json"
    ToolPolicy(path).save(preset("read-only"))
    return path


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


async def test_the_download_list_is_promised_as_well(policy: Path) -> None:
    """The same binding, so a client is promised both lists it may ask for.

    Not `subscribe`: a download is never overwritten, so no resource has a
    content that changes.
    """
    server = build_server(Settings(tool_policy_path=policy))

    options = server._lowlevel_server.create_initialization_options()

    assert options.capabilities.resources is not None
    assert options.capabilities.resources.list_changed is True
    assert options.capabilities.resources.subscribe is False


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
        write_policy(policy, dict.fromkeys(known_tools(), True))
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
        write_policy(policy, dict.fromkeys(known_tools(), True))
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
        write_policy(policy, dict.fromkeys(known_tools(), True))
        await settle()

        assert dead not in server._connections
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


# -- the download list ------------------------------------------------------


async def test_a_download_tells_every_session(tmp_path: Path) -> None:
    """The server wrote the file, so it is the one that knows the list grew.

    Whoever listed either the tools or the resources is told, and about
    the download list alone: the tool list did not move.
    """
    server, _ = server_with(recorder(), download_path=tmp_path)
    first, second = Session(), Session()
    await server._handle_list_tools(Ctx(first), None)
    await server._handle_list_resources(Ctx(second), None)
    try:
        await server.call_tool("download_file", {"file_id": FILE_ID})

        assert (first.downloads, second.downloads) == (1, 1)
        assert (first.told, second.told) == (0, 0)
    finally:
        await server.stop_watching()


async def test_reading_a_download_back_tells_nobody(tmp_path: Path) -> None:
    """Only an answer that links a download has changed the list."""
    server, _ = server_with(recorder(), download_path=tmp_path)
    session = Session()
    await server._handle_list_tools(Ctx(session), None)
    try:
        result = await server.call_tool("download_file", {"file_id": FILE_ID})
        uri = (result.structured_content or {})["uri"]
        await server.call_tool("read_download", {"uri": uri})

        assert session.downloads == 1
    finally:
        await server.stop_watching()


async def test_a_session_gone_by_the_download_is_dropped(tmp_path: Path) -> None:
    server, _ = server_with(recorder(), download_path=tmp_path)
    dead, alive = Session(fail=True), Session()
    await server._handle_list_tools(Ctx(dead), None)
    await server._handle_list_tools(Ctx(alive), None)
    try:
        await server.call_tool("download_file", {"file_id": FILE_ID})

        assert dead not in server._connections
        assert alive.downloads == 1
    finally:
        await server.stop_watching()


async def test_a_client_that_only_calls_is_told_as_well(tmp_path: Path) -> None:
    """Claude Desktop calls from a second process that never lists."""
    server, _ = server_with(recorder(), download_path=tmp_path)
    session = Session()
    await server._handle_call_tool(
        Ctx(session),
        CallToolRequestParams(name="download_file", arguments={"file_id": FILE_ID}),
    )

    assert session.downloads == 1


async def test_a_download_told_at_once_is_not_told_again(tmp_path: Path) -> None:
    """The watcher saw the same change and keeps quiet about it."""
    server, _ = server_with(recorder(), download_path=tmp_path)
    session = Session()
    await server._handle_list_tools(Ctx(session), None)
    try:
        await server.call_tool("download_file", {"file_id": FILE_ID})
        await settle()

        assert session.downloads == 1
    finally:
        await server.stop_watching()


async def test_a_file_written_by_another_hand_is_noticed(tmp_path: Path) -> None:
    """Claude Desktop downloads in a second process of the same server.

    The one answering the listing never saw the call, so the directory
    is what tells it. A client that listed the downloads is enough to
    start the watcher.
    """
    server, _ = server_with(recorder(), download_path=tmp_path)
    session = Session()
    await server._handle_list_resources(Ctx(session), None)
    try:
        await settle(3)
        assert session.downloads == 0
        (tmp_path / "by-another-process.pdf").write_bytes(b"%PDF-1.4")
        await settle()

        assert session.downloads == 1
    finally:
        await server.stop_watching()


async def test_a_directory_that_stays_the_same_tells_nobody(tmp_path: Path) -> None:
    server, _ = server_with(recorder(), download_path=tmp_path)
    session = Session()
    await server._handle_call_tool(
        Ctx(session),
        CallToolRequestParams(name="download_file", arguments={"file_id": FILE_ID}),
    )
    try:
        await settle()

        assert session.downloads == 1
        assert session.told == 0
    finally:
        await server.stop_watching()


async def test_a_download_with_nobody_to_tell_is_still_a_download(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The suite calls tools without a session, and so may a script."""
    server, _ = server_with(recorder(), download_path=tmp_path)
    lines = capture_lines(caplog, "INFO")

    result = await server.call_tool("download_file", {"file_id": FILE_ID})

    assert result.is_error is not True
    assert "The download list changed, 0 sessions told" in lines.text


# -- over the wire ----------------------------------------------------------


@asynccontextmanager
async def connected(server: Any, received: list[str]) -> AsyncIterator[ClientSession]:
    """A real client on the server, through the SDK's runner, in memory.

    Every notification the client is sent lands in ``received`` by its
    method. The server runs as a task beside the client and is cancelled
    when the client has left.
    """

    async def handler(message: Any) -> None:
        method = getattr(getattr(message, "root", message), "method", None)
        if method is not None:
            received.append(method)

    low = server._lowlevel_server
    async with create_client_server_memory_streams() as (client_end, server_end):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(low.run, *server_end, low.create_initialization_options())
            async with ClientSession(*client_end, message_handler=handler) as client:
                await client.initialize()
                yield client
            tasks.cancel_scope.cancel()


async def arrived(received: list[str], method: str, within: float = 2.0) -> bool:
    """Whether ``method`` reaches ``received`` in time."""
    waited = 0.0
    while method not in received and waited < within:
        await asyncio.sleep(0.01)
        waited += 0.01
    return method in received


async def test_the_wire_carries_the_tool_list_notification(policy: Path) -> None:
    """A policy change reaches a client that listed the tools, as sent by the SDK."""
    server = build_server(Settings(tool_policy_path=policy))
    received: list[str] = []
    try:
        async with connected(server, received) as client:
            await client.list_tools()
            write_policy(policy, dict.fromkeys(known_tools(), True))

            assert await arrived(received, "notifications/tools/list_changed")
    finally:
        await server.stop_watching()


async def test_the_wire_carries_the_download_notification(tmp_path: Path) -> None:
    """A download reaches a client that only ever called, before its result."""
    server, _ = server_with(recorder(), download_path=tmp_path)
    received: list[str] = []
    try:
        async with connected(server, received) as client:
            result = await client.call_tool("download_file", {"file_id": FILE_ID})

            assert result.is_error is not True
            assert await arrived(received, "notifications/resources/list_changed")
            assert "notifications/tools/list_changed" not in received
    finally:
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
        write_policy(policy, {"get_profile": True})

        names = {tool.name for tool in await server.list_tools()}

        assert names == {"get_profile"}
        assert session.told == 0  # before the watcher has even looked
    finally:
        await server.stop_watching()


async def test_a_session_that_ended_is_not_kept(policy: Path) -> None:
    """Over HTTP, short sessions come and go without a policy change between."""
    server = build_server(Settings(tool_policy_path=policy))
    kept = Session()
    for _ in range(3):
        await server._handle_list_tools(Ctx(Session()), None)
    await server._handle_list_tools(Ctx(kept), None)
    try:
        gc.collect()

        assert list(server._connections) == [kept]
    finally:
        await server.stop_watching()
