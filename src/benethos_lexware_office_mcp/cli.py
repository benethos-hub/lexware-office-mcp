"""The command line: the console script and ``python -m``.

``benethos-lexware-office-mcp`` starts the server over **stdio**, which is
what Claude Desktop and comparable local clients use, or with ``--transport
streamable-http`` or ``sse`` over HTTP behind a bearer token that is required
rather than offered (SPECS.md section 6). The same entry point writes the
policy file with ``--tools``, prints the settings sample, and serves the
configuration interface with ``setup``.

Everything a command prints goes to stderr. Under stdio stdout is the
JSON-RPC stream, and a command that shares an entry point with the server
does not learn a different habit.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path
from typing import cast

from . import __version__, configui, logbook
from .errors import ConfigError
from .files import storage
from .policy import Preset, ToolPolicy, known_tools, preset
from .server import build_server
from .settings import LOG_LEVELS, LOOPBACK_NAMES, TRANSPORTS, Settings, load_settings
from .settings.locations import (
    env_file_in_effect,
    resolve_config_file,
    settings_sample,
)
from .settings.parse import csv_tuple
from .transport.http import bearer_ready, run_http
from .transport.stdio import run_stdio

__all__ = ["main"]


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

  Binds 127.0.0.1. The pages have no login, so they answer only when a
  browser addresses them as 127.0.0.1 or localhost. --host exists for a
  container, where the loopback of the host publishes the port.

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
    policy = build_server(settings).policy

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
    # A bad setting ends the server, in one line rather than a traceback. Not
    # before argparse has had its turn, though: `--version` and `--help` have
    # nothing to do with the settings, and `setup` is where one is repaired.
    broken: ConfigError | None = None
    try:
        settings = load_settings(env_file=named_env)
    except ConfigError as exc:
        settings, broken = Settings(), exc
    args = _parse_args(argv, settings)
    if broken is not None and args.command != "setup":
        print(str(broken), file=sys.stderr)
        raise SystemExit(2)
    # The same for one found later, such as no home to find a file in.
    try:
        _run(args, settings, named_env)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        # uvicorn shuts down cleanly on Ctrl+C and then raises the signal
        # again, so the process ends as interrupted - which, uncaught, is a
        # traceback that reads like a crash. stdio ends the same way. SIGTERM
        # from docker stop or systemd never gets here: Python turns only
        # SIGINT into an exception.
        logbook.lifecycle.interrupted()
        raise SystemExit(130) from None  # 128 + SIGINT


def _run(args: argparse.Namespace, settings: Settings, named_env: Path | None) -> None:
    """What the command line asked for, once the settings have been read."""
    # The command line wins over the environment, which wins over the search.
    # Left unset it stays None, so the search decides - and no absolute path
    # from this machine has to appear in --help to explain that.
    if args.tools_file:
        named = Path(args.tools_file).expanduser()
        if named.exists() and not named.is_file():
            print(f"Not a file: {named}", file=sys.stderr)
            raise SystemExit(2)
        settings = dataclasses.replace(settings, tool_policy_path=named)

    logbook.configure(args.log_level)

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
        allowed_hosts=csv_tuple(args.allowed_hosts) or settings.allowed_hosts,
    )

    if settings.transport != "stdio":
        settings = bearer_ready(settings, _env_in_effect(named_env))

    server = build_server(settings)
    logbook.lifecycle.started(__version__, settings.transport)
    logbook.lifecycle.settings_from(env_file_in_effect(named=named_env))
    _report_what_is_enabled(server.policy)
    # Here and after each download, and nowhere else: `--tools`, `setup` and
    # anything else that builds a server to look at it deletes nothing.
    storage.prune_for(settings)

    if settings.transport == "stdio":
        run_stdio(server)
        return

    _report_where_it_listens(settings)
    watch = _env_in_effect(named_env) if settings.exit_on_config_change else None
    run_http(server, settings, watch=watch)


def _env_in_effect(named: Path | None) -> Path:
    """The settings file this process was configured from.

    Pinned here for the same reason the policy file is pinned: the identity
    of the file is decided once, and only its contents are read again.

    Not ``locations.env_file_in_effect``, which answers ``None`` when no file
    exists. The two callers here need a path either way - one watches for a
    file appearing, the other writes a generated token into the place a file
    belongs - and since one `.env` applies, watching that one is watching all
    of them.
    """
    return named if named is not None else resolve_config_file(".env")


def _report_where_it_listens(settings: Settings) -> None:
    """Say on stderr what is being served and to whom.

    A bind address is the one setting where being told what happened matters
    more than being told what to type: 0.0.0.0 in a container is right, and
    on a laptop it is a mistake nobody meant to make.
    """
    logbook.lifecycle.listening(
        settings.transport, settings.http_host, settings.http_port, settings.http_path
    )
    if settings.http_host not in LOOPBACK_NAMES:
        logbook.lifecycle.reachable_from_outside(settings.http_host)


def _report_what_is_enabled(policy: ToolPolicy) -> None:
    """Say on stderr what this process may do, and how to change it.

    A server offering nothing looks broken from the client, where the tool
    list is simply empty. Naming the file and the command turns that into
    something a person can act on.
    """
    if not policy.exists():
        logbook.lifecycle.no_policy(policy.path)
        return
    assert policy.path is not None
    enabled = [name for name, on in policy.as_map().items() if on]
    writers = [name for name in enabled if known_tools()[name].access == "write"]
    logbook.lifecycle.tools_enabled(
        len(enabled), len(known_tools()), writers, policy.path
    )
