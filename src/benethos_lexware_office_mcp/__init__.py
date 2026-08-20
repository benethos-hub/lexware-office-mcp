"""Unofficial Lexware Office MCP server.

An MCP server that gives MCP clients such as Claude Desktop access to a
Lexware Office account through the documented public REST API. Read-only by
default. Not affiliated with Lexware or Haufe-Lexware.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    # The distribution (PyPI) name, which differs from the import package name.
    __version__ = version("benethos-lexware-office-mcp")
except PackageNotFoundError:  # pragma: no cover - package not installed
    __version__ = "0.0.0+unknown"
