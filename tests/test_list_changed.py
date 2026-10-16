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
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession
from mcp.client.subscriptions import ResourcesListChanged, ToolsListChanged, listen
from mcp.server.connection import NotifyOnlyOutbound
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

    has_standalone_channel = True

    def __init__(self, fail: bool = False) -> None:
        self.told = 0
        self.downloads = 0
        self.fail = fail
        self._connection = self
        self.outbound: Any = self

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


async def until(condition: Callable[[], bool], within: float = 2.0) -> bool:
    """Whether ``condition`` comes true in time, looked at once a watcher turn."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within
    while not condition() and loop.time() < deadline:
        await asyncio.sleep(server_module.POLICY_POLL_SECONDS)
    return condition()


async def turns(count: int = 8) -> None:
    """Let the watcher take ``count`` turns, for a test that expects nothing."""
    await asyncio.sleep(count * server_module.POLICY_POLL_SECONDS)


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
        assert await until(lambda: session.told == 1)
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
            await turns(3)

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
        assert await until(lambda: (first.told, second.told) == (1, 1))
    finally:
        await server.stop_watching()


async def test_a_session_that_is_gone_is_dropped(policy: Path) -> None:
    server = build_server(Settings(tool_policy_path=policy))
    dead, alive = Session(fail=True), Session()
    await server._handle_list_tools(Ctx(dead), None)
    await server._handle_list_tools(Ctx(alive), None)
    try:
        write_policy(policy, dict.fromkeys(known_tools(), True))
        assert await until(lambda: alive.told == 1)
        assert dead not in server._connections
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


async def test_a_connection_the_notification_cannot_reach_is_not_counted(
    policy: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Neither drops it with an error, so each was counted as told."""
    lines = capture_lines(caplog, "INFO")
    server = build_server(Settings(tool_policy_path=policy))
    modern, without, handshake = Session(), Session(), Session()
    modern.outbound = NotifyOnlyOutbound(modern)
    without.has_standalone_channel = False  # type: ignore[misc]
    for session in (modern, without, handshake):
        await server._handle_list_tools(Ctx(session), None)
    try:
        write_policy(policy, dict.fromkeys(known_tools(), True))
        assert await until(lambda: "The tool list changed" in lines.text)
        assert (modern.told, without.told, handshake.told) == (0, 0, 1)
        assert "The tool list changed, 1 clients told" in lines.text
    finally:
        await server.stop_watching()


async def test_the_bus_hears_of_both_lists(tmp_path: Path) -> None:
    """The bus is what a 2026-07-28 listen stream is fed from."""
    everything = dict.fromkeys(known_tools(), True)
    policy = write_policy(tmp_path / "tools.json", {**everything, "get_profile": False})
    server, _ = server_with(
        recorder(), download_path=tmp_path / "downloads", tool_policy_path=policy
    )
    events: list[Any] = []
    server._subscriptions.subscribe(events.append)
    await server._handle_list_tools(Ctx(Session()), None)
    try:
        await server.call_tool("download_file", {"file_id": FILE_ID})
        write_policy(policy, everything)
        assert await until(lambda: len(events) == 2)
        assert [type(e) for e in events] == [ResourcesListChanged, ToolsListChanged]
    finally:
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
        await turns()

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
        await turns(3)
        assert session.downloads == 0
        (tmp_path / "by-another-process.pdf").write_bytes(b"%PDF-1.4")

        assert await until(lambda: session.downloads == 1)
    finally:
        await server.stop_watching()


async def test_with_the_file_tools_off_a_new_file_tells_nobody(
    tmp_path: Path,
) -> None:
    """No download is listed then, so none has joined the list."""
    policy = write_policy(tmp_path / "tools.json", {"get_profile": True})
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    server, _ = server_with(
        recorder(), download_path=downloads, tool_policy_path=policy
    )
    session = Session()
    await server._handle_list_tools(Ctx(session), None)
    try:
        (downloads / "by-another-process.pdf").write_bytes(b"%PDF-1.4")
        await turns()

        assert session.downloads == 0
    finally:
        await server.stop_watching()


async def test_the_directory_is_scanned_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It may hold thousands of files, or sit on a network drive."""
    server, _ = server_with(recorder(), download_path=tmp_path)
    threads: list[threading.Thread] = []
    scan = server_module.resources.names

    def names(*args: Any) -> tuple[str, ...]:
        threads.append(threading.current_thread())
        return scan(*args)

    monkeypatch.setattr(server_module.resources, "names", names)

    await server._download_names()

    assert threads and threading.main_thread() not in threads


async def test_a_reading_of_the_policy_in_hand_is_not_taken_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The watcher reads the file once a turn and hands the reading on."""
    server, _ = server_with(recorder(), download_path=tmp_path)
    allowed = server.policy.as_map()

    def read_again() -> dict[str, bool]:
        raise AssertionError("the policy file was read a second time")

    monkeypatch.setattr(server.policy, "as_map", read_again)

    assert await server._download_names(allowed) == ()


async def test_a_directory_that_stays_the_same_tells_nobody(tmp_path: Path) -> None:
    server, _ = server_with(recorder(), download_path=tmp_path)
    session = Session()
    await server._handle_call_tool(
        Ctx(session),
        CallToolRequestParams(name="download_file", arguments={"file_id": FILE_ID}),
    )
    try:
        await turns()

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
    assert "The download list changed, 0 clients told" in lines.text


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


async def test_the_wire_carries_the_tool_list_notification(policy: Path) -> None:
    """A policy change reaches a client that listed the tools, as sent by the SDK."""
    server = build_server(Settings(tool_policy_path=policy))
    received: list[str] = []
    try:
        async with connected(server, received) as client:
            await client.list_tools()
            write_policy(policy, dict.fromkeys(known_tools(), True))

            assert await until(lambda: "notifications/tools/list_changed" in received)
    finally:
        await server.stop_watching()


async def test_the_wire_carries_the_download_notification(tmp_path: Path) -> None:
    """A download reaches a client that only ever called, before its result."""
    server, _ = server_with(recorder(), download_path=tmp_path)
    received: list[str] = []
    try:
        async with connected(server, received) as client:
            result = await client.call_tool("download_file", {"file_id": FILE_ID})

            # Sent before the result, so here by the time the result is.
            assert result.is_error is not True
            assert "notifications/resources/list_changed" in received
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


@asynccontextmanager
async def listening(server: Any, **kinds: bool) -> AsyncIterator[Any]:
    """A 2026-07-28 client: no handshake, its notifications on a listen stream.

    It lists the tools first, as a client does before it uses them, which
    is what starts the watcher.
    """
    low = server._lowlevel_server
    async with create_client_server_memory_streams() as (client_end, server_end):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(low.run, *server_end, low.create_initialization_options())
            async with ClientSession(*client_end) as client:
                await client.discover()
                await client.list_tools()
                async with listen(client, **kinds) as subscription:
                    yield subscription
            tasks.cancel_scope.cancel()


async def test_a_listen_stream_carries_the_tool_list_notification(
    policy: Path,
) -> None:
    """The 2026-07-28 era has no channel outside a request but this one."""
    server = build_server(Settings(tool_policy_path=policy))
    try:
        async with listening(server, tools_list_changed=True) as subscription:
            write_policy(policy, dict.fromkeys(known_tools(), True))

            with anyio.fail_after(2):
                event = await anext(aiter(subscription))

        assert isinstance(event, ToolsListChanged)
    finally:
        await server.stop_watching()
