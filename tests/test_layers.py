"""Which part of the package may import which, read from the source.

The package is layered, see SPECS.md section 4: the foundation every layer
stands on, then what talks to Lexware and what handles a file, then the
tools, the server, how a client reaches it, and the two commands on top. The
order holds exactly as long as nothing checks it, so this does: every import
statement in the package, including one inside a function or under
``TYPE_CHECKING``, since a deferred import is still a dependency.

A new module or subpackage fails the last test until it is given a row in
:data:`MAY_IMPORT`. That is the cost of the table, and deliberately one line.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import benethos_lexware_office_mcp

PACKAGE = "benethos_lexware_office_mcp"
_SOURCE = Path(benethos_lexware_office_mcp.__file__).parent

# Everything else stands on these, and they stand on nothing but each other.
FOUNDATION = frozenset({"errors", "settings", "logbook"})

# Which layers a layer may import, besides itself and the package root, which
# every module may read `__version__` from.
MAY_IMPORT: dict[str, frozenset[str]] = {
    "errors": FOUNDATION,
    "settings": FOUNDATION,
    "logbook": FOUNDATION,
    "records": frozenset({"errors"}),
    "api": FOUNDATION | {"records"},
    "files": FOUNDATION,
    "policy": frozenset({"errors", "logbook", "settings"}),
    "tools": FOUNDATION | {"records", "api", "files", "policy"},
    "server": FOUNDATION | {"tools", "policy", "api", "files"},
    "transport": FOUNDATION | {"server"},
    # The configuration interface builds a server to measure what the tools
    # cost, and is started by the command line alone.
    "configui": FOUNDATION | {"records", "api", "files", "policy", "tools", "server"},
    # The top: anything below it, and imported by nothing but `python -m`.
    "cli": FOUNDATION
    | {"records", "api", "files", "policy", "tools", "server", "transport", "configui"},
    "__main__": frozenset({"cli"}),
}


def _layer(module: str) -> str:
    """``benethos_lexware_office_mcp.api.client`` is in the layer ``api``."""
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else ""


def _imports(path: Path) -> list[tuple[str, int]]:
    """Every module of this package that ``path`` imports, with its line."""
    relative = path.relative_to(_SOURCE).with_suffix("").parts
    # What `.` means: the package a module sits in, and for an __init__ the
    # package it is - both of which drop the last part.
    base = [PACKAGE, *relative][:-1]
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = base[: len(base) - (node.level - 1)]
                module = ".".join([*anchor, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            if module != PACKAGE and not module.startswith(f"{PACKAGE}."):
                continue
            if module == PACKAGE:
                # `from .. import logbook` names the layer in the alias.
                found += [
                    (f"{module}.{alias.name}", node.lineno) for alias in node.names
                ]
            else:
                found.append((module, node.lineno))
        elif isinstance(node, ast.Import):
            found += [
                (alias.name, node.lineno)
                for alias in node.names
                if alias.name.startswith(f"{PACKAGE}.")
            ]
    return found


def _modules() -> list[Path]:
    return sorted(_SOURCE.rglob("*.py"))


@pytest.mark.parametrize(
    "path", _modules(), ids=[p.relative_to(_SOURCE).as_posix() for p in _modules()]
)
def test_a_module_imports_only_the_layers_below_it(path: Path) -> None:
    layer = path.relative_to(_SOURCE).parts[0].removesuffix(".py")
    if layer == "__init__":
        return  # the package root, which holds the version and nothing else
    allowed = MAY_IMPORT[layer]
    wrong = [
        f"line {line}: {module}"
        for module, line in _imports(path)
        if (target := _layer(module)) not in ("", "__version__", layer)
        and target not in allowed
    ]
    assert wrong == [], f"{layer} may import {sorted(allowed)}"


def test_every_layer_has_a_row() -> None:
    """A module or subpackage added without deciding where it sits fails here."""
    layers = {
        path.relative_to(_SOURCE).parts[0].removesuffix(".py") for path in _modules()
    } - {"__init__"}
    assert layers == set(MAY_IMPORT)


def test_the_table_reads_real_imports() -> None:
    """A parser that found nothing would pass every test above."""
    tools = _imports(_SOURCE / "tools" / "files.py")
    assert {_layer(module) for module, _ in tools} >= {"api", "files", "records"}
    # `from .. import logbook`, where the layer is the name imported.
    connection = _imports(_SOURCE / "api" / "connection.py")
    assert "logbook" in {_layer(module) for module, _ in connection}
