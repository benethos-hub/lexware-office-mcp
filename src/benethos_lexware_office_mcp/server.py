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

from . import __version__
from .config import LOG_LEVELS, MODES, Mode, Settings, load_settings
from .policy import set_active_mode
from .tools import register_tools

logger = logging.getLogger(__name__)

_INSTRUCTIONS = """\
Access to a Lexware Office account through its public API. Read-only unless
the account owner enabled writing.

Identifiers are Lexware UUIDs and are never invented. To act on a document or
a contact, find it first with search_vouchers or search_contacts and use the
id from the result. Monetary values are returned exactly as the API reports
them, always with their currency.
"""


def build_server(settings: Settings) -> MCPServer:
    """Create a server whose registered tools match the permission tier."""
    set_active_mode(settings.mode)
    server = MCPServer(
        name="benethos-lexware-office-mcp",
        title="Unofficial Lexware Office MCP Server",
        version=__version__,
        instructions=_INSTRUCTIONS,
    )
    register_tools(server, settings)
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
    return parser.parse_args(argv)


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
