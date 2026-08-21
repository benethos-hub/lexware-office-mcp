"""MCP server entry point.

Run with ``python -m benethos_lexware_office_mcp`` or the installed
``benethos-lexware-office-mcp`` console script. The transport is **stdio**
only, which is what Claude Desktop and comparable local clients use. An HTTP
transport is planned for 0.3.0 and will ship with its own authentication in
front of the API key (SPECS.md section 6).

Logging always goes to stderr, so that under stdio stdout stays reserved for
the JSON-RPC stream.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from pathlib import Path
from typing import cast

from mcp.server.mcpserver import MCPServer

from . import __version__, resources
from .client import ClientProvider
from .config import LOG_LEVELS, Settings, download_dir, load_settings
from .policy import (
    Preset,
    ToolPolicy,
    active_policy,
    known_tools,
    preset,
    set_active_policy,
)
from .tools import register_tools

logger = logging.getLogger(__name__)

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


def build_server(
    settings: Settings, provider: ClientProvider | None = None
) -> MCPServer:
    """Create a server whose registered tools match the permission tier.

    ``provider`` is injectable for tests. Left out, the server builds the one
    client it is allowed to have, and every tool shares it — and with it the
    one rate limiter.
    """
    set_active_policy(ToolPolicy(settings.policy_file()))
    server = MCPServer(
        name="benethos-lexware-office-mcp",
        title="Unofficial Lexware Office MCP Server",
        version=__version__,
        instructions=_INSTRUCTIONS,
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
choosing the tools:

  The server offers only what its policy file allows, and nothing at all
  when there is no file. Write a starting point, then edit it by hand.

    benethos-lexware-office-mcp --tools read-only
        reading only: search, look up, download

    benethos-lexware-office-mcp --tools write
        the above, and creating and changing records

    benethos-lexware-office-mcp --tools irreversible
        the above, and deleting, booking and finalizing

    benethos-lexware-office-mcp --tools show
        change nothing, just list what is on

  The file is JSON, one line per tool:

    {
     "search_contacts": true,
     "create_contact": false
    }

  Setting one to false takes effect at once: the tool is refused from the
  next request on, though a client that has already fetched the list goes on
  showing it. Setting one to true needs the server restarted, because tools
  are registered when it starts. Claude Desktop is quit from the tray.

  Running --tools again overwrites the whole file, so edits made by hand are
  lost. Use it to start a file, not to update one.

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
  config/.env.sample lists every setting and what it does.

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
        choices=("show", "read-only", "write", "irreversible"),
        metavar="WHICH",
        help=(
            "list or rewrite the policy file instead of starting the server: "
            "show, read-only, write, irreversible (see below)"
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
        try:
            policy.save(preset(cast(Preset, action)))
        except OSError as exc:
            # A path that is a directory, a read-only disk, a folder somebody
            # else owns. All of them are the caller's typo or the machine's
            # business, and none of them deserve a traceback.
            print(
                f"Could not write {policy.path}: {exc.strerror or exc}", file=sys.stderr
            )
            raise SystemExit(2) from None
        print(f"Wrote the '{action}' preset to {policy.path}", file=sys.stderr)

    flags = policy.as_map()
    width = max(len(name) for name in flags)
    for name, on in flags.items():
        print(f"  {name:<{width}}  {'on' if on else 'off'}", file=sys.stderr)
    print(
        f"{sum(flags.values())} of {len(flags)} tools on, per {policy.path}",
        file=sys.stderr,
    )


def _named_env_file(argv: list[str] | None) -> Path | None:
    """``--env-file`` before anything else reads configuration.

    Its own miniature parse, because the real one takes its defaults from the
    settings, and the settings are what this argument decides.
    """
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env-file")
    known, _ = pre.parse_known_args(argv)
    if not known.env_file:
        return None
    named = Path(known.env_file).expanduser()
    if not named.is_file():
        # Falling back to the search here would be the worst of both: the
        # server would start, read something else, and behave in a way the
        # command line appears to rule out.
        print(f"No .env file at {named}", file=sys.stderr)
        raise SystemExit(2)
    return named


def main(argv: list[str] | None = None) -> None:
    """Console script entry point."""
    settings = load_settings(env_file=_named_env_file(argv))
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

    if args.tools:
        _tools_command(args.tools, settings)
        return

    server = build_server(settings)
    _report_what_is_enabled(settings)
    server.run()


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
