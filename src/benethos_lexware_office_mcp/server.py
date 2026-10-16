"""The server: an ``MCPServer`` that answers to the policy file.

:class:`PolicyServer` lists only what the file allows and, through the guard
every tool is registered with, calls only that. :func:`build_server` makes
one from the settings, and importing this module is what fills the tool
registry. The command line that starts a server is :mod:`.cli`.

Logging always goes to stderr, so that under stdio stdout stays reserved for
the JSON-RPC stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import re
import weakref
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError
from mcp.server.mcpserver.exceptions import ToolError as SDKToolError
from mcp.server.session import ServerSession
from mcp.types import CallToolResult, Icon, Resource, Tool
from pydantic import ValidationError as ArgumentError

from . import __version__, logbook
from .api.client import ClientProvider
from .errors import SETUP_PROMPT_TITLE, ConfigError, ToolError
from .files import resources
from .policy import ToolPolicy, known_tools, withheld
from .settings import DEFAULT_KEPT_DOWNLOADS, Settings, load_settings
from .tools import register_tools


def _links_a_download(result: Any) -> bool:
    """Whether a tool's answer carries a link to a download of this server.

    The download tools answer with one and nothing else does. The answer
    decides rather than the tool's name, so a tool added later that saves a
    file is covered by the shape of what it returns.
    """
    if not isinstance(result, CallToolResult):
        return False
    return any(
        block.type == "resource_link" and resources.name_of(str(block.uri)) is not None
        for block in result.content
    )


# How often the watcher looks at the policy file. Short enough that a change
# made in the browser feels immediate, long enough that reading a few hundred
# bytes of JSON at that rate is nothing.
POLICY_POLL_SECONDS = 2.0

# What an argument's name may look like to be repeated in a refusal.
_ARGUMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")

# Sent once, when a session starts, rather than with every request the way a
# tool description is. That is the whole reason there is room here for what
# holds across tools instead of inside one of them.
_INSTRUCTIONS = """\
Access to a Lexware Office account through its public API. The account owner
decides which of these tools exist, so the list is the whole of what is
permitted - a tool that is missing was withheld deliberately, not forgotten.

Identifiers are Lexware UUIDs and are never invented. To act on a document or
a contact, find it first with search_vouchers or search_contacts and use the
id from the result. search_vouchers is the only way to find a document at all,
so a question about invoices, credit notes or what is still unpaid starts
there. Monetary values are returned exactly as the API reports them, always
with their currency.

These are somebody's books, and a tool without readOnlyHint changes them for
real. Before the first such call in a session, call get_profile and name the
company you are about to write to. Most of what this API creates it cannot
remove again, so say what a call will leave behind before making it, and make
it once - there is no idempotency key, and a repeated create is a second
record rather than the same one.

Every call spends from one budget of two requests per second, shared across
all endpoints. One search with the right filter is worth several fetches, and
a list answers in pages: read the page block of a result before asking for
another one.
"""

# What a client may show beside the name, sent once in the handshake and
# never to the model: the same description, address and icons the MCP
# Registry entry carries, so a client shows what the registry shows.
# `tests/test_server.py` keeps the two in step.
DESCRIPTION = (
    "Unofficial MCP server for the Lexware Office accounting API — runs over "
    "stdio or HTTP."
)
WEBSITE = "https://github.com/benethos-hub/lexware-office-mcp"
_RAW = "https://raw.githubusercontent.com/benethos-hub/lexware-office-mcp/main/assets/brand/"
ICONS = [
    Icon(src=_RAW + "icon.svg", mime_type="image/svg+xml", sizes=["any"]),
    Icon(src=_RAW + "icon.png", mime_type="image/png", sizes=["512x512"]),
]

# Wherever the prompt exists, see `Settings.offers_setup_prompt`. Without it
# a client that lists no tool leaves the model guessing at a broken
# connection, which is what happened the first time this was tried in Claude
# Desktop.
_SETUP_HINT = f"""
The person can open the configuration interface, where the API key is set and
the tools are chosen, by picking the prompt "{SETUP_PROMPT_TITLE}" in the
client. When no tool is listed, or the one a request needs is missing, say so
and point to that prompt rather than guessing at a fault.
"""


class PolicyServer(MCPServer):
    """An ``MCPServer`` that lists only what the policy file allows.

    The filter sits here rather than at registration so that both directions
    take effect the same way: the file is read as the list is built, so a tool
    switched on is offered from the next listing, exactly as one switched off
    stops being offered. Registering the decision instead would have frozen it
    at startup.

    A client is told when that happens, so it can ask again: the server
    announces ``tools.listChanged`` and a watcher sends
    ``notifications/tools/list_changed`` when the set of enabled tools
    actually differs. Whether a given client acts on it is the client's
    business - enforcement never relies on it, because the file is read again
    on every call.

    The downloads it offers as resources are announced the same way:
    ``resources.listChanged`` is promised beside it, and every session is
    told after a tool answered with a link to a download, which is the one
    moment that list grows.
    """

    def __init__(
        self,
        *args: Any,
        policy: ToolPolicy,
        downloads: Path | None = None,
        listed_downloads: int = DEFAULT_KEPT_DOWNLOADS,
        kept_downloads: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._policy = policy
        # Where the download resources are read from, and how many are listed.
        # None when no directory resolves, which lists nothing and reads
        # nothing - a download says what to set when one is asked for.
        self._downloads = downloads
        self._listed_downloads = listed_downloads
        self._kept_downloads = kept_downloads
        # Held weakly: a session that ended is gone from here with it. Over
        # streamable HTTP every client that lists tools opens one, and a
        # plain set kept each until a policy change failed to reach it.
        self._sessions: weakref.WeakSet[ServerSession] = weakref.WeakSet()
        self._watcher: asyncio.Task[None] | None = None
        self._seen: dict[str, bool] | None = None
        # Bound once, here, rather than per transport: `run_stdio_async` and
        # its two HTTP siblings all call this same method with no arguments,
        # and its default leaves every listChanged flag false. Announcing the
        # capability is what makes the notification mean anything - a client
        # is entitled to ignore one it was never promised. Prompts are the
        # one list that never changes.
        low = self._lowlevel_server
        low.create_initialization_options = functools.partial(  # type: ignore[method-assign]
            low.create_initialization_options,
            NotificationOptions(tools_changed=True, resources_changed=True),
        )

    async def list_tools(self) -> list[Tool]:
        # One reading of the file for the whole list. Asking `enabled` per
        # tool would open and parse it once per tool, which is fifteen times
        # for an answer that has to be consistent anyway - a file edited
        # halfway through would otherwise produce a list that never existed.
        allowed = self._policy.as_map()
        tools = await super().list_tools()
        return [tool for tool in tools if allowed.get(tool.name, False)]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Any = None
    ) -> Any:
        """Call a tool, and note a call whose arguments never reached it.

        Every other outcome is noted by the wrapper each tool is registered
        with, see ``tools._base.logged``. Arguments that fail the schema are
        refused before the tool runs, so that wrapper never hears of them,
        and the SDK's own line for them is held back with the rest of its
        INFO. The line names the fields, never what was in them.

        **An argument the tool does not take is refused, not dropped.** The
        SDK builds each tool's argument model to ignore what it does not
        know, so a call with a filter that is not there ran without it and
        answered as if it had: `search_vouchers(only_open=True)` from a
        client holding a tool list older than the removal of that flag
        would have listed every paid voucher as before. Only for a tool the
        policy allows, so a withheld one still says nothing about itself.

        **A withheld tool is refused first**, before the SDK checks the
        arguments: its refusal of an invalid call names the fields the tool
        requires and quotes what was sent, which is the schema the policy
        keeps from the caller. The answer is the one the guard each tool is
        wrapped in gives a valid call.
        """
        enabled = self._policy.enabled(name)
        if not enabled and name in known_tools():
            refused = withheld(name)
            logbook.calls.ended(name, refused, 0, 0.0)
            # Worded as the SDK words a refusal raised inside a tool, which is
            # where the guard raises it for a valid call, so a client reads
            # the same answer whatever the arguments were.
            raise SDKToolError(f"Error executing tool {name}: {refused}") from refused
        unknown = await self._unknown_arguments(name, arguments) if enabled else []
        if unknown:
            logbook.calls.arguments_refused(name, unknown)
            raise ToolError(
                f"{name} takes no argument {', '.join(unknown)}, so nothing "
                "was sent. The tool list says which arguments it takes."
            )
        try:
            result = await super().call_tool(name, arguments, context)
        except SDKToolError as exc:
            cause = exc.__cause__
            if isinstance(cause, ArgumentError):
                fields = sorted(
                    {".".join(str(part) for part in e["loc"]) for e in cause.errors()}
                )
                logbook.calls.arguments_refused(name, fields)
            raise
        if _links_a_download(result):
            await self._downloads_changed()
        return result

    async def _unknown_arguments(
        self, name: str, arguments: dict[str, Any]
    ) -> list[str]:
        """The arguments of a call that the tool's schema does not name.

        Each is shown by its name when it looks like one and as ``?``
        otherwise: a name is what the caller typed, and a line on stderr or
        a message back is no place for an arbitrary string.
        """
        if not arguments:
            return []
        tool = next((t for t in await super().list_tools() if t.name == name), None)
        if tool is None:
            return []
        known = set(tool.input_schema.get("properties", {}))
        return sorted(
            key if _ARGUMENT_NAME.fullmatch(key) else "?"
            for key in arguments
            if key not in known
        )

    @property
    def policy(self) -> ToolPolicy:
        """The file this server answers to, for listing and for every call."""
        return self._policy

    def _resources_enabled(self) -> bool:
        """Whether any tool a download resource belongs to is enabled."""
        allowed = self._policy.as_map()
        return any(allowed.get(name, False) for name in resources.GATING_TOOLS)

    async def list_resources(self) -> list[Resource]:
        # Read from the download directory as it is now, but offered only
        # under the same file that decides the tools: with every download
        # tool off, the files they left behind are not a way around that.
        if not self._resources_enabled():
            return []
        registered = await super().list_resources()
        return [
            *registered,
            *resources.listed(self._downloads, self._listed_downloads),
        ]

    async def read_resource(self, uri: Any, context: Any = None) -> Any:
        if not self._resources_enabled():
            raise ResourceNotFoundError(f"Unknown resource: {uri}")
        if resources.name_of(str(uri)) is not None:
            found = resources.read(self._downloads, str(uri))
            if found is None:
                raise ResourceNotFoundError(
                    f"Unknown resource: {uri}. " + resources.gone(self._kept_downloads)
                )
            return found
        return await super().read_resource(uri, context)

    async def _handle_list_tools(self, ctx: Any, params: Any) -> Any:
        """Answer the request, and keep the session it arrived on.

        The private hook rather than `list_tools`, because this is the only
        place the session is offered for a listing: `_handle_list_tools`
        receives the request context and calls `list_tools()` without it.
        """
        self._sessions.add(ctx.session)
        self._start_watching()
        return await super()._handle_list_tools(ctx, params)

    async def _handle_list_resources(self, ctx: Any, params: Any) -> Any:
        """Answer the request, and keep this session as well.

        A client that listed the downloads is one to tell when the next is
        added. The watcher is not started here: it compares the tool list,
        and a client that never asked for one has nothing to compare.
        """
        self._sessions.add(ctx.session)
        return await super()._handle_list_resources(ctx, params)

    def _start_watching(self) -> None:
        """Begin polling, once there is somebody to tell.

        Deliberately not started at construction. Without a session there is
        nobody to notify, and a task that outlives every test in a suite that
        never connects a client is a nuisance nobody asked for.
        """
        if self._watcher is not None and not self._watcher.done():
            return
        self._seen = self._policy.as_map()
        self._watcher = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        """Notice a changed tool list and say so.

        **The comparison is the visible set, not the file.** The
        configuration interface rewrites the whole policy file on every save,
        so watching its timestamp would announce a change on every click that
        changed nothing.
        """
        while True:
            await asyncio.sleep(POLICY_POLL_SECONDS)
            current = self._policy.as_map()
            if current == self._seen:
                continue
            self._seen = current
            await self._announce()

    async def _announce(self) -> None:
        """The tool list is not what it was: tell every live session."""
        told = await self._tell(lambda session: session.send_tool_list_changed())
        logbook.policy.list_changed(told)

    async def _downloads_changed(self) -> None:
        """A download was written, so the resource list is not what it was.

        Sent from the call that wrote it rather than by a watcher, since the
        server is the one writing: there is nothing to poll for.
        """
        told = await self._tell(lambda session: session.send_resource_list_changed())
        logbook.files.list_changed(told)

    async def _tell(self, send: Callable[[Any], Awaitable[None]]) -> int:
        """Send to every session, forget the ones that fail, count the rest."""
        told = 0
        for session in list(self._sessions):
            try:
                await send(session)
            except Exception as exc:  # noqa: BLE001 - a dead session is normal
                # On stderr rather than swallowed: a client that never
                # refreshes is a thing to be able to look into, and this is
                # the only trace it would leave.
                logbook.policy.session_dropped(exc)
                self._sessions.discard(session)
            else:
                told += 1
        return told

    async def stop_watching(self) -> None:
        """Cancel the watcher. For tests, which run many servers in one loop.

        Nothing calls it on shutdown, and nothing has to: the watcher is a
        task of the event loop, and ``asyncio.run`` cancels every task left
        when the transport returns.
        """
        task, self._watcher = self._watcher, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def build_server(
    settings: Settings, provider: ClientProvider | None = None
) -> PolicyServer:
    """Create a server that answers to the policy file ``settings`` name.

    ``provider`` is injectable for tests. Left out, the server builds the one
    client it is allowed to have, and every tool shares it — and with it the
    one rate limiter.

    The policy belongs to the server and to nothing else. Every tool's call
    guard is bound to it, so a second server in the same process - the
    configuration interface measures costs with one - cannot change what the
    first one enforces.
    """
    policy = ToolPolicy(settings.policy_file())
    try:
        downloads: Path | None = settings.download_directory()
    except ConfigError:
        # No home and no LXO_MCP_DOWNLOAD_DIR: nothing to offer, and a
        # download says what to set when one is asked for.
        downloads = None
    server = PolicyServer(
        name="benethos-lexware-office-mcp",
        title="Unofficial Lexware Office MCP Server",
        description=DESCRIPTION,
        website_url=WEBSITE,
        icons=ICONS,
        version=__version__,
        instructions=_INSTRUCTIONS
        + (_SETUP_HINT if settings.offers_setup_prompt() else ""),
        policy=policy,
        downloads=downloads,
        listed_downloads=settings.downloads_listed(),
        kept_downloads=settings.downloads_kept(),
    )
    register_tools(server, settings, provider or ClientProvider(settings))
    return server


# Importing this module fills the tool registry, which the policy file, the
# presets and the configuration interface are all written against. Tools
# classify themselves as they are defined, and they are defined by being
# registered - so they are registered once here, on a server that serves
# nothing, with default settings. Default on purpose: this runs on import,
# before `--version` or `setup` has been parsed, and a bad value in somebody's
# environment must not stop either of them.
#
# The SDK configures logging whenever it builds a server, and this is the one
# built before the command line is read, so what it put on the root logger is
# taken off again, see `logbook.output.untouched_root`.
with logbook.output.untouched_root():
    _registry = MCPServer(name="registry")
register_tools(_registry, Settings(), ClientProvider(Settings()))

_inspected: PolicyServer | None = None


def __getattr__(name: str) -> Any:
    """``server.mcp``: a server as configured here, built on first use.

    For the inspect commands in CLAUDE.md, which want the tool list as this
    machine's settings and policy file produce it. Built only when asked for,
    since building it reads the environment.
    """
    if name == "mcp":
        global _inspected
        if _inspected is None:
            _inspected = build_server(load_settings())
        return _inspected
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
