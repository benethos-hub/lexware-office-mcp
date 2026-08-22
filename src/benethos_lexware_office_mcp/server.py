"""MCP server entry point.

Run with ``python -m benethos_lexware_office_mcp`` or the installed
``benethos-lexware-office-mcp`` console script. The transport is **stdio**
only, which is what Claude Desktop and comparable local clients use. An HTTP
transport is planned for 0.2.0 and will ship with its own authentication in
front of the API key (SPECS.md section 6).

Logging always goes to stderr, so that under stdio stdout stays reserved for
the JSON-RPC stream.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import functools
import logging
import sys
from pathlib import Path
from typing import Any, cast

from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.mcpserver import MCPServer

from . import __version__, configui, resources
from .client import ClientProvider
from .config import (
    LOG_LEVELS,
    TRANSPORTS,
    Settings,
    download_dir,
    load_settings,
    resolve_config_file,
    settings_sample,
)
from .errors import ConfigError
from .policy import (
    Preset,
    ToolPolicy,
    active_policy,
    known_tools,
    preset,
    set_active_policy,
)
from .tools import register_tools
from .transport import require_bearer, run_http

logger = logging.getLogger(__name__)

# How often the watcher looks at the policy file. Short enough that a change
# made in the browser feels immediate, long enough that reading a few hundred
# bytes of JSON at that rate is nothing.
POLICY_POLL_SECONDS = 2.0

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
    """

    def __init__(self, *args: Any, policy: ToolPolicy, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._policy = policy
        self._sessions: set[Any] = set()
        self._watcher: asyncio.Task[None] | None = None
        self._seen: dict[str, bool] | None = None
        # Bound once, here, rather than per transport: `run_stdio_async` and
        # its two HTTP siblings all call this same method with no arguments,
        # and its default leaves every listChanged flag false. Announcing the
        # capability is what makes the notification mean anything - a client
        # is entitled to ignore one it was never promised.
        low = self._lowlevel_server
        low.create_initialization_options = functools.partial(  # type: ignore[method-assign]
            low.create_initialization_options,
            NotificationOptions(tools_changed=True),
        )

    async def list_tools(self) -> list[Any]:
        # One reading of the file for the whole list. Asking `enabled` per
        # tool would open and parse it once per tool, which is fifteen times
        # for an answer that has to be consistent anyway - a file edited
        # halfway through would otherwise produce a list that never existed.
        allowed = self._policy.as_map()
        tools = await super().list_tools()
        return [tool for tool in tools if allowed.get(tool.name, False)]

    async def _handle_list_tools(self, ctx: Any, params: Any) -> Any:
        """Answer the request, and keep the session it arrived on.

        The private hook rather than `list_tools`, because this is the only
        place the session is offered for a listing: `_handle_list_tools`
        receives the request context and calls `list_tools()` without it.
        """
        self._sessions.add(ctx.session)
        self._start_watching()
        return await super()._handle_list_tools(ctx, params)

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
        """Tell every live session, and forget the ones that are not."""
        for session in list(self._sessions):
            try:
                await session.send_tool_list_changed()
            except Exception as exc:  # noqa: BLE001 - a dead session is normal
                # On stderr rather than swallowed: a client that never
                # refreshes is a thing to be able to look into, and this is
                # the only trace it would leave.
                logger.debug("Could not notify a session, dropping it: %s", exc)
                self._sessions.discard(session)

    async def stop_watching(self) -> None:
        """Cancel the watcher. For shutdown, and for tests."""
        task, self._watcher = self._watcher, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def build_server(
    settings: Settings, provider: ClientProvider | None = None
) -> MCPServer:
    """Create a server whose registered tools match the permission tier.

    ``provider`` is injectable for tests. Left out, the server builds the one
    client it is allowed to have, and every tool shares it — and with it the
    one rate limiter.
    """
    policy = ToolPolicy(settings.policy_file())
    set_active_policy(policy)
    server = PolicyServer(
        name="benethos-lexware-office-mcp",
        title="Unofficial Lexware Office MCP Server",
        version=__version__,
        instructions=_INSTRUCTIONS,
        policy=policy,
    )
    register_tools(server, settings, provider or ClientProvider(settings))
    resources.publish_existing(server, settings.download_path or download_dir())
    return server


# Module-level instance so the tool surface can be inspected without starting
# a server. See the inspect command in CLAUDE.md.
mcp = build_server(load_settings())


# Written for someone reading it in a terminal for the first time. The
# options say what they are in one line each, and everything that needs a
# paragraph is a worked example underneath, where argparse will not reflow it.
_DESCRIPTION = """\
Gives an AI assistant access to a Lexware Office account.

It speaks MCP over stdio, so you do not run it yourself: a client such as
Claude Desktop starts it. What you do run is --tools, to say which of its
tools that client may use."""

_EPILOG = """\
the configuration interface:

  benethos-lexware-office-mcp setup

  Serves three pages on 127.0.0.1 and opens a browser: which files are in
  effect and where each setting comes from, the API key, and one checkbox
  per tool with what it costs the model in context. It writes the same files
  this command line does, so the two can be used interchangeably.

  Loopback only, with no way to bind anything else. The pages have no login,
  because they cannot be reached from another machine.

  --port and --no-browser belong to it. --env-file and --tools-file say which
  files it edits, and unlike everywhere else the .env does not have to exist
  yet - creating one is part of what the interface is for.

choosing the tools:

  The server offers only what its policy file allows, and nothing at all
  when there is no file. Write a starting point, then edit it by hand.

    benethos-lexware-office-mcp --tools read-only
        reading only: search, look up, download

    benethos-lexware-office-mcp --tools write
        the above, and creating and changing records

    benethos-lexware-office-mcp --tools irreversible
        the above, and deleting an article, the one thing this
        API can delete

    benethos-lexware-office-mcp --tools show
        change nothing, just list what is on

    benethos-lexware-office-mcp --tools sync
        add the tools the file does not mention yet, all off,
        and leave every flag already in it alone

  'write' does not mean undoable. Nothing in it deletes a record, but the
  API cannot delete a bookkeeping voucher at all, so a voucher created by
  create_voucher or by upload_file has to be corrected in the web app.

  The file is JSON, one line per tool:

    {
     "search_contacts": true,
     "create_contact": false
    }

  Changes take effect at once, in both directions - the file is read as the
  tool list is built and again on every call. What lags is the client: most
  ask for the list once, when they start, and go on showing what they were
  told then. Claude Desktop is quit from the tray to make it ask again.

  A preset overwrites the whole file, so edits made by hand are lost. Use one
  to start a file, not to update one. That is what sync is for: after an
  upgrade brings new tools, it writes them in as off and touches nothing else.
  Sync never switches anything on.

where the file goes:

  Without --tools-file, tools.json is looked for in these places, and the
  last one found is the one that counts:

    1. the per-user configuration directory
    2. config/ of the source checkout, if you are running from the sources
    3. ./config/tools.json, then ./tools.json

  --tools-file overrides that, and works two ways. With --tools it says
  where to write:

    benethos-lexware-office-mcp --tools write --tools-file ./tools.json

  On its own it says which file the running server obeys, so it belongs in
  the client's configuration next to the command it starts:

    "args": ["--tools-file", "/path/to/tools.json"]

  One account per file, then, if you run this server more than once.

settings and the API key:

  Everything else is configuration, read from a .env file found the same way
  the policy file is, or from real environment variables, which win.
  --settings-sample prints a commented list of every setting.

  --env-file names one instead of searching, and pairs with --tools-file so
  that one client entry has its own account and its own permissions:

    "args": ["--env-file", "/path/to/test.env",
             "--tools-file", "/path/to/test-tools.json"]

  Put your API key in it as LXO_MCP_API_KEY. Create one in Lexware Office
  under Extensions, Public API. A real environment variable still overrides
  the file, so a client can change one value without editing anything."""


def _parse_args(argv: list[str] | None, defaults: Settings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="benethos-lexware-office-mcp",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=__version__, help="print the version"
    )
    parser.add_argument(
        "--settings-sample",
        action="store_true",
        help="print the commented settings sample and exit",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("setup",),
        metavar="COMMAND",
        help=(
            "setup: open the configuration interface in a browser instead of "
            "starting the server (see below)"
        ),
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default=defaults.log_level,
        metavar="LEVEL",
        help=(
            "how much to report on stderr: "
            + ", ".join(LOG_LEVELS).lower()
            + " (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--tools",
        choices=("show", "sync", "read-only", "write", "irreversible"),
        metavar="WHICH",
        help=(
            "list or rewrite the policy file instead of starting the server: "
            "show, sync, read-only, write, irreversible (see below)"
        ),
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        help=(
            "which .env to read instead of looking for one - the settings, "
            "including the API key (see below)"
        ),
    )
    parser.add_argument(
        "--tools-file",
        metavar="PATH",
        help=(
            "which policy file to use instead of looking for one - both for "
            "--tools and for the server itself (see below)"
        ),
    )
    parser.add_argument(
        "--transport",
        choices=TRANSPORTS,
        default=defaults.transport,
        help="how a client reaches this server (default: %(default)s)",
    )
    # --host and --port serve whichever of the two things this process is:
    # the HTTP transport, or the configuration interface. A process is never
    # both, and one pair of names is easier to remember than two.
    parser.add_argument(
        "--host",
        metavar="ADDR",
        help=(
            "address to bind, for an HTTP transport or for setup. Anything "
            "but a loopback address is reachable from outside this machine"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        metavar="N",
        help=(
            f"port to bind (default: {defaults.http_port} for a transport, "
            f"{configui.DEFAULT_PORT} for setup)"
        ),
    )
    parser.add_argument(
        "--path",
        metavar="PATH",
        default=defaults.http_path,
        help="URL path the HTTP transport serves on (default: %(default)s)",
    )
    parser.add_argument(
        "--allowed-hosts",
        metavar="LIST",
        help=(
            "comma-separated Host values to accept besides loopback, for a "
            "container or a proxy, for example lexware-office-mcp:8770"
        ),
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="setup only: do not open a browser, just print the address",
    )
    return parser.parse_args(argv)


def _tools_command(action: str, settings: Settings) -> None:
    """Show or rewrite the policy file, then return without serving.

    Everything here goes to **stderr**. stdout carries the JSON-RPC stream,
    and a command that shares an entry point with the server has no business
    learning a different habit.
    """
    # Building a server imports the tool modules, which is what fills the
    # registry the policy is written against. The registry is filled as the
    # tools are *defined*, so it is complete even when the file enables none
    # of them - which is the state this command exists to get out of.
    build_server(settings)
    policy = active_policy()

    if action != "show":
        existed = policy.exists()
        try:
            if action == "sync":
                added, stale = policy.sync()
            else:
                policy.save(preset(cast(Preset, action)))
        except OSError as exc:
            # A path that is a directory, a read-only disk, a folder somebody
            # else owns. All of them are the caller's typo or the machine's
            # business, and none of them deserve a traceback.
            print(
                f"Could not write {policy.path}: {exc.strerror or exc}", file=sys.stderr
            )
            raise SystemExit(2) from None
        if action == "sync":
            _report_sync(policy.path, existed, added, stale)
        else:
            print(f"Wrote the '{action}' preset to {policy.path}", file=sys.stderr)

    flags = policy.as_map()
    width = max(len(name) for name in flags)
    for name, on in flags.items():
        print(f"  {name:<{width}}  {'on' if on else 'off'}", file=sys.stderr)
    print(
        f"{sum(flags.values())} of {len(flags)} tools on, per {policy.path}",
        file=sys.stderr,
    )


def _report_sync(
    path: Path | None, existed: bool, added: list[str], stale: list[str]
) -> None:
    """Say what a sync changed, in the terms somebody would ask about.

    Which tools appeared matters, because each is a decision waiting to be
    made. That nothing was switched on is worth saying out loud, since that is
    the whole reason this action is safe to run unattended.
    """
    if not existed:
        print(f"Wrote a new policy file at {path}, everything off.", file=sys.stderr)
    elif added:
        listed = ", ".join(added)
        print(
            f"Added {len(added)} tool{'s' if len(added) != 1 else ''} to {path}, "
            f"off: {listed}",
            file=sys.stderr,
        )
    else:
        print(f"{path} already lists every tool. Nothing added.", file=sys.stderr)
    if stale:
        print(
            f"Dropped {len(stale)} name{'s' if len(stale) != 1 else ''} that is no "
            f"longer a tool: {', '.join(stale)}",
            file=sys.stderr,
        )
    print("Nothing was switched on.", file=sys.stderr)


def _named_env_file(argv: list[str] | None, *, must_exist: bool = True) -> Path | None:
    """``--env-file`` before anything else reads configuration.

    Its own miniature parse, because the real one takes its defaults from the
    settings, and the settings are what this argument decides.

    ``must_exist`` is false for the setup command, which exists in part to
    create the file the rest of the program insists on finding.
    """
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env-file")
    known, _ = pre.parse_known_args(argv)
    if not known.env_file:
        return None
    named = Path(known.env_file).expanduser()
    if not named.is_file() and must_exist:
        # Falling back to the search here would be the worst of both: the
        # server would start, read something else, and behave in a way the
        # command line appears to rule out.
        print(f"No .env file at {named}", file=sys.stderr)
        raise SystemExit(2)
    return named


def main(argv: list[str] | None = None) -> None:
    """Console script entry point."""
    wants_setup = "setup" in (argv if argv is not None else sys.argv[1:])
    named_env = _named_env_file(argv, must_exist=not wants_setup)
    settings = load_settings(env_file=named_env)
    args = _parse_args(argv, settings)

    # The command line wins over the environment, which wins over the search.
    # Left unset it stays None, so the search decides - and no absolute path
    # from this machine has to appear in --help to explain that.
    if args.tools_file:
        named = Path(args.tools_file).expanduser()
        if named.exists() and not named.is_file():
            print(f"Not a file: {named}", file=sys.stderr)
            raise SystemExit(2)
        settings = dataclasses.replace(settings, tool_policy_path=named)

    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.settings_sample:
        print(settings_sample(), end="")
        return

    if args.command == "setup":
        configui.start(
            settings,
            configui.target_env_file(named_env),
            host=args.host or configui.DEFAULT_HOST,
            port=args.port or configui.DEFAULT_PORT,
            open_browser=not args.no_browser,
        )
        return

    if args.tools:
        _tools_command(args.tools, settings)
        return

    # The command line outranks the environment for the transport, the same
    # way --tools-file does: each is a decision about this one run.
    settings = dataclasses.replace(
        settings,
        transport=args.transport,
        http_host=args.host or settings.http_host,
        http_port=args.port or settings.http_port,
        http_path=args.path,
        allowed_hosts=_host_list(args.allowed_hosts) or settings.allowed_hosts,
    )

    if settings.transport != "stdio":
        try:
            require_bearer(settings)
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from None

    server = build_server(settings)
    _report_what_is_enabled(settings)

    if settings.transport == "stdio":
        server.run()
        return

    _report_where_it_listens(settings)
    # The .env is read once, at startup. Where something restarts this
    # process - a container, a service manager - it can be told to end when
    # that file changes, so a key saved in the browser takes effect without
    # anyone opening a terminal. Nowhere else, since ending would be the
    # whole of it.
    watch = _env_in_effect(named_env) if settings.exit_on_config_change else None
    if watch is not None:
        logging.getLogger(__name__).info("Ending on a change to %s", watch.name)
    run_http(server, settings, watch=watch)


def _env_in_effect(named: Path | None) -> Path:
    """The settings file this process was configured from.

    Pinned here for the same reason the policy file is pinned: the identity
    of the file is decided once, and only its contents are read again.
    """
    return named if named is not None else resolve_config_file(".env")


def _host_list(raw: str | None) -> tuple[str, ...]:
    """Split a comma-separated ``--allowed-hosts`` value, ignoring blanks."""
    if not raw:
        return ()
    return tuple(part for part in (piece.strip() for piece in raw.split(",")) if part)


def _report_where_it_listens(settings: Settings) -> None:
    """Say on stderr what is being served and to whom.

    A bind address is the one setting where being told what happened matters
    more than being told what to type: 0.0.0.0 in a container is right, and
    on a laptop it is a mistake nobody meant to make.
    """
    log = logging.getLogger(__name__)
    log.info(
        "%s on http://%s:%s%s, bearer token required",
        settings.transport,
        settings.http_host,
        settings.http_port,
        settings.http_path,
    )
    if settings.http_host not in ("127.0.0.1", "localhost", "::1"):
        log.warning(
            "Bound to %s, so this port is reachable from outside this machine. "
            "In a container that is what the published port is for. Anywhere "
            "else, the bearer token is the only thing in the way.",
            settings.http_host,
        )


def _report_what_is_enabled(settings: Settings) -> None:
    """Say on stderr what this process may do, and how to change it.

    A server offering nothing looks broken from the client, where the tool
    list is simply empty. Naming the file and the command turns that into
    something a person can act on.
    """
    policy = ToolPolicy(settings.policy_file())
    enabled = [name for name, on in policy.as_map().items() if on]
    if not policy.exists():
        logger.warning(
            "No tool policy at %s, so no tools are offered. Create one with "
            "--tools read-only, then enable what this account may be used for.",
            policy.path,
        )
        return
    writers = [name for name in enabled if known_tools()[name].access == "write"]
    if writers:
        logger.warning(
            "%d of %d tools enabled, %d of them able to change real accounting "
            "records: %s. Per %s.",
            len(enabled),
            len(known_tools()),
            len(writers),
            ", ".join(sorted(writers)),
            policy.path,
        )
    else:
        logger.info(
            "%d of %d tools enabled, all read-only. Per %s.",
            len(enabled),
            len(known_tools()),
            policy.path,
        )
