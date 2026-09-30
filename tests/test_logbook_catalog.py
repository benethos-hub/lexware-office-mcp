"""The catalogue of lines, held to what a line may carry.

Two halves, see the `logbook` package docstring. Every line is a function
there, and its parameters are drawn from the vocabulary below - so a new
parameter is a decision somebody makes here, in a test named for it, rather
than a `query` that slipped into a signature. And nothing outside the package
logs at all, so there is no second place for a line to hide.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import benethos_lexware_office_mcp
from benethos_lexware_office_mcp import logbook
from benethos_lexware_office_mcp.errors import ValidationError
from benethos_lexware_office_mcp.logbook._describe import describe
from benethos_lexware_office_mcp.logbook.output import PACKAGE

RECORD = "0b7a5c9e-3f2d-4e1a-9c8b-7d6e5f4a3b2c"

CATALOGUE: list[ModuleType] = [
    logbook.api,
    logbook.calls,
    logbook.configui,
    logbook.files,
    logbook.lifecycle,
    logbook.policy,
]

# Every parameter name a line may take: what it holds, and a value to call it
# with. Nothing here is a value the model chose or the API answered with.
VOCABULARY: dict[str, tuple[str, Any]] = {
    "attempt": ("which attempt at a request", 2),
    "calls": ("how many API calls a tool call made", 2),
    "count": ("how often something happened", 3),
    "delay": ("seconds waited, or to be waited", 1.5),
    "enabled": ("a count of tools", 3),
    "endpoint": ("a request's path, words and UUIDs only", "/v1/contacts"),
    "error": ("an exception, read through describe() only", OSError(2, "gone")),
    "fields": ("the names of arguments the schema refused", ("items.0.unit",)),
    "file": ("the name of a settings file", ".env"),
    "finalized": ("whether a write finalized its record", True),
    "found": ("a policy value, named by its JSON type only", "false"),
    "host": ("the address this server binds", "127.0.0.1"),
    "method": ("an HTTP method", "GET"),
    "ms": ("a duration in milliseconds", 230.0),
    "path": ("a configuration file's path", Path("tools.json")),
    "port": ("the port this server binds", 8770),
    "queued": ("milliseconds spent waiting for the rate limiter", 400.0),
    "record_id": ("a Lexware id, shown only as a UUID", RECORD),
    "route": ("the URL path this server serves", "/mcp"),
    "rows": ("how many rows a list answered with", 12),
    "sessions": ("a count of client sessions", 2),
    "size": ("a download's size in bytes", 151_552),
    "source": ("where a policy was read from", "tools.json"),
    "status": ("an HTTP status", 503),
    "tool": ("a tool's name", "create_voucher"),
    "total": ("a count of tools", 25),
    "transport": ("stdio, streamable-http or sse", "stdio"),
    "version": ("this server's version, or a record's", 3),
    "voucher": ("the id of a voucher an upload created", ""),
    "writers": ("tool names", ("create_contact",)),
}

_SOURCE = Path(benethos_lexware_office_mcp.__file__).parent


def _lines() -> list[tuple[str, Callable[..., None]]]:
    return [
        (f"{module.__name__.rsplit('.', 1)[1]}.{name}", getattr(module, name))
        for module in CATALOGUE
        for name in module.__all__
    ]


@pytest.mark.parametrize(("name", "line"), _lines(), ids=[n for n, _ in _lines()])
def test_every_parameter_is_in_the_vocabulary(
    name: str, line: Callable[..., None]
) -> None:
    for parameter in inspect.signature(line).parameters:
        assert parameter in VOCABULARY, f"{name} takes {parameter!r}"


@pytest.mark.parametrize(("name", "line"), _lines(), ids=[n for n, _ in _lines()])
def test_every_function_writes_one_line_of_this_server(
    name: str, line: Callable[..., None], caplog: pytest.LogCaptureFixture
) -> None:
    arguments = {
        parameter: VOCABULARY[parameter][1]
        for parameter in inspect.signature(line).parameters
    }

    with caplog.at_level(logging.DEBUG, logger=PACKAGE):
        line(**arguments)

    assert len(caplog.records) == 1, name
    assert caplog.records[0].name.startswith(f"{PACKAGE}.")


def test_every_module_of_the_catalogue_is_listed() -> None:
    """A module added to the package but not here would go unchecked."""
    found = {
        path.stem
        for path in (_SOURCE / "logbook").glob("*.py")
        if not path.stem.startswith("_")
        and path.stem not in ("output", "access", "tally")
    }
    assert found == {module.__name__.rsplit(".", 1)[1] for module in CATALOGUE}


def test_nothing_outside_the_logbook_logs() -> None:
    offenders = [
        str(path.relative_to(_SOURCE))
        for path in _SOURCE.rglob("*.py")
        if "logbook" not in path.relative_to(_SOURCE).parts
        and (
            "import logging" in (text := path.read_text(encoding="utf-8"))
            or "getLogger" in text
        )
    ]
    assert offenders == []


# -- what of an exception a line may say -----------------------------------


def test_an_error_of_ours_is_named_by_its_class_alone() -> None:
    """Our messages are written for the model and quote what it sent."""
    error = ValidationError("No file at C:/Mustermann/receipt.pdf.")

    assert describe(error) == "ValidationError"


def test_a_system_error_says_why_without_the_file() -> None:
    error = OSError(13, "Permission denied", "C:/Users/someone/tools.json")

    assert describe(error) == "PermissionError, Permission denied"


def test_a_broken_json_file_says_where() -> None:
    try:
        json.loads('{"get_profile": tru}')
    except json.JSONDecodeError as exc:
        error = exc

    assert describe(error) == "JSONDecodeError at line 1 column 17"
