"""Where the lines go, and which libraries are held back.

The concrete finding behind all of it: at INFO, httpx wrote every request
with its whole URL, so a contact search left the name it searched for in the
container log.
"""

from __future__ import annotations

import io
import logging
import subprocess
import sys

import pytest
from mcp.server.mcpserver import MCPServer

from benethos_lexware_office_mcp.logbook import configure
from benethos_lexware_office_mcp.logbook.access import ACCESS_LOGGER, AccessLines
from benethos_lexware_office_mcp.logbook.output import (
    LIBRARIES,
    PACKAGE,
    untouched_root,
)
from benethos_lexware_office_mcp.settings import Settings
from benethos_lexware_office_mcp.transport import uvicorn_config
from helpers import always, fast_client

SEARCHED = "Mustermann"


def _stream(level: str) -> io.StringIO:
    stream = io.StringIO()
    configure(level, stream)
    return stream


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING"])
def test_the_libraries_stay_at_warning_whatever_the_level(level: str) -> None:
    _stream(level)

    for name in LIBRARIES:
        assert logging.getLogger(name).level == logging.WARNING
    assert logging.getLogger(PACKAGE).level == logging.getLevelName(level)


async def test_a_search_term_never_reaches_the_log_even_at_debug() -> None:
    """The finding itself, end to end through a real httpx client."""
    stream = _stream("DEBUG")
    client = fast_client(always({"content": []}))

    await client.contacts(name=SEARCHED)
    await client.aclose()

    assert SEARCHED not in stream.getvalue()


def test_nor_does_the_sdk_quoting_a_failed_tool() -> None:
    """The SDK logs a failed tool's message at INFO, and ours quote input.

    The line as the SDK writes it for a refused upload, see
    `MCPServer._handle_call_tool`.
    """
    stream = _stream("DEBUG")

    logging.getLogger("mcp.server.mcpserver.server").info(
        "Tool %r failed: %r", "upload_file", f"No file at C:/{SEARCHED}/receipt.pdf"
    )

    assert SEARCHED not in stream.getvalue()


def test_lines_carry_the_logger_name_without_the_package() -> None:
    stream = _stream("INFO")

    logging.getLogger(f"{PACKAGE}.client").info("a line")
    logging.getLogger("uvicorn.error").info("theirs")

    lines = stream.getvalue().splitlines()
    assert lines[0].endswith("INFO client: a line")
    assert lines[1].endswith("INFO uvicorn.error: theirs")


def test_configuring_twice_does_not_print_twice() -> None:
    first = _stream("INFO")
    second = _stream("INFO")

    logging.getLogger(PACKAGE).info("once")

    assert first.getvalue() == ""
    assert second.getvalue().count("once") == 1


def test_a_library_nobody_named_is_held_at_warning_too() -> None:
    stream = _stream("DEBUG")

    logging.getLogger("somebody.else").info("chatter")
    logging.getLogger("somebody.else").warning("worth seeing")

    assert "chatter" not in stream.getvalue()
    assert "worth seeing" in stream.getvalue()


# -- uvicorn's request line ------------------------------------------------


def _access(status: int, path: str = "/mcp") -> logging.LogRecord:
    """A record exactly as uvicorn makes one."""
    return logging.LogRecord(
        ACCESS_LOGGER,
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.5:51234", "POST", path, "1.1", status),
        None,
    )


def test_below_debug_only_a_refused_request_is_kept() -> None:
    lines = AccessLines(everything=False)

    assert not lines.filter(_access(200))
    assert not lines.filter(_access(307))
    assert lines.filter(_access(401))
    assert lines.filter(_access(421))


def test_at_debug_every_request_is_kept() -> None:
    assert AccessLines(everything=True).filter(_access(200))


def test_the_query_string_never_reaches_the_line() -> None:
    record = _access(401, f"/mcp?name={SEARCHED}")

    AccessLines(everything=True).filter(record)

    assert record.getMessage() == '10.0.0.5:51234 - "POST /mcp HTTP/1.1" 401'


def test_a_line_of_another_shape_passes_as_it_came() -> None:
    record = logging.LogRecord(
        ACCESS_LOGGER, logging.INFO, __file__, 0, "something new", None, None
    )

    assert AccessLines(everything=False).filter(record)


def test_the_request_line_follows_the_level_it_was_configured_with() -> None:
    stream = _stream("INFO")
    access = logging.getLogger(ACCESS_LOGGER)

    access.handle(_access(200))
    access.handle(_access(401))

    assert '" 200' not in stream.getvalue()
    assert '" 401' in stream.getvalue()


def test_uvicorn_is_left_no_handler_of_its_own() -> None:
    """Its default puts the request line on stdout, next to the protocol."""
    config = uvicorn_config(
        lambda *_: None,  # type: ignore[arg-type]
        Settings(transport="streamable-http", bearer_token="x" * 32),
    )
    config.configure_logging()

    assert config.log_config is None
    assert logging.getLogger(ACCESS_LOGGER).handlers == []
    assert logging.getLogger("uvicorn.error").handlers == []


def test_nothing_reaches_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    configure("DEBUG")

    logging.getLogger(PACKAGE).warning("to stderr")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "to stderr" in captured.err


def test_a_server_built_before_configuring_leaves_no_handler_behind() -> None:
    """The SDK's basicConfig, with or without rich, is taken off again."""
    root = logging.getLogger()
    root.handlers[:] = []

    with untouched_root():
        MCPServer(name="probe")

    assert root.handlers == []


def test_in_a_fresh_process_each_line_appears_once_at_the_level_asked_for() -> None:
    """The order a real start has: the server module imported first.

    Importing the server builds an MCPServer, which is when the SDK's
    handler would arrive, and only afterwards is the level read from the
    command line. Through `cli`, which is what the console script imports.
    """
    script = "\n".join(
        [
            "import logging",
            "import benethos_lexware_office_mcp.cli",
            "from benethos_lexware_office_mcp import logbook",
            "logbook.configure('WARNING')",
            "log = logging.getLogger('benethos_lexware_office_mcp.probe')",
            "log.warning('seen once')",
            "log.info('not seen')",
        ]
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )

    assert done.stdout == ""
    assert done.stderr.count("seen once") == 1
    assert "not seen" not in done.stderr
