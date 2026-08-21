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
import logging
import sys
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


def _parse_args(argv: list[str] | None, defaults: Settings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="benethos-lexware-office-mcp",
        description=(
            "MCP server for the Lexware Office API. Speaks stdio. "
            "Offers the tools the policy file enables, and no others."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default=defaults.log_level,
        help="Log level on stderr. Env: LXO_MCP_LOG_LEVEL. Default: %(default)s.",
    )
    parser.add_argument(
        "--tools",
        choices=("show", "all", "read-only", "none"),
        help=(
            "Work on the tool policy file instead of serving. 'show' prints "
            "which tools are on. 'all', 'read-only' and 'none' write the file "
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
    # registry the policy is written against. The registry is filled as the
    # tools are *defined*, so it is complete even when the file enables none
    # of them - which is the state this command exists to get out of.
    build_server(settings)
    policy = active_policy()

    if action != "show":
        policy.save(preset(cast(Preset, action)))
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
