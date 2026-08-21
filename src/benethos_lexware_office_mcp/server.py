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

from mcp.server.mcpserver import MCPServer

from . import __version__, resources
from .client import ClientProvider
from .config import LOG_LEVELS, MODES, Mode, Settings, download_dir, load_settings
from .policy import (
    ToolPolicy,
    active_policy,
    preset,
    set_active_mode,
    set_active_policy,
)
from .tools import register_tools

logger = logging.getLogger(__name__)

_INSTRUCTIONS = """\
Access to a Lexware Office account through its public API. Read-only unless
the account owner enabled writing.

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
    set_active_mode(settings.mode)
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


def _parse_args(argv: list[str] | None, defaults: Settings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="benethos-lexware-office-mcp",
        description=(
            "MCP server for the Lexware Office API. Speaks stdio. "
            "Read-only unless --mode says otherwise."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--mode",
        choices=MODES,
        default=defaults.mode,
        help=(
            "Permission tier. 'read' allows queries only. 'write' adds "
            "creating and updating. 'full' adds irreversible operations. "
            "Env: LXO_MCP_MODE. Default: %(default)s."
        ),
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default=defaults.log_level,
        help="Log level on stderr. Env: LXO_MCP_LOG_LEVEL. Default: %(default)s.",
    )
    parser.add_argument(
        "--tools",
        choices=("show", "all", "read-only"),
        help=(
            "Work on the per-tool policy file instead of serving. 'show' "
            "prints which tools are on. 'all' and 'read-only' write the file "
            "from that preset, overwriting what is there. Env: "
            "LXO_MCP_TOOL_POLICY sets the file's location."
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
    # registry the policy is written against. At tier `full` so every tool is
    # known, whatever tier the server will actually run at.
    build_server(replace_mode(settings, "full"))
    policy = active_policy()

    if action != "show":
        policy.save(preset("all" if action == "all" else "read-only"))
        print(f"Wrote the '{action}' preset to {policy.path}", file=sys.stderr)

    flags = policy.as_map()
    width = max(len(name) for name in flags)
    for name, on in flags.items():
        print(f"  {name:<{width}}  {'on' if on else 'off'}", file=sys.stderr)
    print(
        f"{sum(flags.values())} of {len(flags)} tools on, per {policy.path}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> None:
    """Console script entry point."""
    settings = load_settings()
    args = _parse_args(argv, settings)

    # The command line wins over the environment.
    mode: Mode = args.mode
    settings = replace_mode(settings, mode)

    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.tools:
        _tools_command(args.tools, settings)
        return

    server = build_server(settings)
    if settings.mode != "read":
        logger.warning(
            "Running at permission tier '%s'. This server can change real "
            "accounting records.",
            settings.mode,
        )
    logger.info("Starting on stdio, tier '%s'.", settings.mode)
    server.run()


def replace_mode(settings: Settings, mode: Mode) -> Settings:
    """Return a copy of ``settings`` running at a different permission tier."""
    return dataclasses.replace(settings, mode=mode)
