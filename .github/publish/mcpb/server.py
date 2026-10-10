"""Entry point of the Claude Desktop bundle, which uv starts by its path.

The manifest runs this file with ``uv run`` in the unpacked bundle, which
installs the project from its pyproject.toml and uv.lock first. A package's
``__main__`` cannot be started this way, its imports are relative.
"""

from benethos_lexware_office_mcp.cli import main

if __name__ == "__main__":
    main()
