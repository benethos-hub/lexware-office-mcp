"""Where the lines go, and which of them are let through.

One handler, on stderr, for this server and everything underneath it: under
stdio, stdout is the protocol, and over HTTP a second stream is one more
thing for Docker to keep. ``LXO_MCP_LOG_LEVEL`` sets the level of this
server's own lines and of nothing else.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from collections.abc import Iterator
from datetime import datetime
from http import HTTPStatus
from typing import TextIO

from .access import ACCESS_LOGGER, AccessLines, request

__all__ = [
    "LIBRARIES",
    "PACKAGE",
    "configure",
    "in_colour",
    "paint",
    "source",
    "stamp",
    "untouched_root",
]

PACKAGE = __name__.split(".")[0]

# Held at WARNING whatever the level says, and there is no switch to lower
# them. Their INFO lines carry exactly what this server never writes down:
# httpx names every request with its whole URL, which holds the name or email
# `search_contacts` looked for, and the SDK quotes a failed tool's message,
# which quotes the arguments. The server writes its own line for both, see
# the package docstring for what those may carry.
LIBRARIES = ("httpx", "httpcore", "mcp")

# uvicorn's own messages - started, stopped, a malformed request - are the
# lifecycle of the HTTP transport and stay visible at INFO even when this
# server's lines are set to DEBUG. Its DEBUG is connection chatter.
_UVICORN = "uvicorn.error"

FORMAT = "%(asctime)s %(levelname)-8s %(where)s: %(message)s"

# Marks the handler this module installed, so configuring twice replaces it
# rather than printing every line twice.
_MARK = "_lxo_logbook"


@contextlib.contextmanager
def untouched_root() -> Iterator[None]:
    """Undo whatever the block did to the root logger's handlers and level.

    Every ``MCPServer`` the SDK builds calls ``logging.basicConfig``, with a
    ``RichHandler`` where ``rich`` is installed and a plain stream handler
    where it is not. ``server.py`` builds one on import, before the command
    line has been read, and that handler stayed: every line appeared twice,
    and this server's own ``basicConfig`` came too late to do anything. That
    is what the level setting had been until 2026-09-30 - ignored, with the
    SDK's ``INFO`` in its place.

    Taking off what the block added, whatever its type, rather than looking
    for one class: which handler the SDK picks depends on what else is
    installed. Once :func:`configure` has run, ``basicConfig`` finds a
    handler and does nothing, so a server built later needs no such care.
    """
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        yield
    finally:
        for added in [h for h in root.handlers if h not in handlers]:
            root.removeHandler(added)
        root.setLevel(level)


# What a line names as its source, where that is not the logger's own name.
# uvicorn calls its server log `uvicorn.error`, after the error log of the
# classic web servers, into which a server writes everything about itself.
# Spelled out, an ordinary start reads like a failure.
_SOURCES = {
    PACKAGE: "server",
    ACCESS_LOGGER: "http",
    _UVICORN: "uvicorn",
    "uvicorn": "uvicorn",
}


def source(name: str) -> str:
    """The short name a line carries for the logger called ``name``.

    ``client`` rather than ``benethos_lexware_office_mcp.client``: every line
    of this server would otherwise start with the same thirty characters. Any
    other library's name is left whole, so a line still says whose it is.
    """
    prefix = f"{PACKAGE}."
    if name.startswith(prefix):
        return name[len(prefix) :]
    return _SOURCES.get(name, name)


class _Where(logging.Filter):
    """Puts :func:`source` on the record, where the format finds it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.where = source(record.name)
        return True


def stamp(created: float) -> str:
    """ISO 8601 in local time, to the millisecond, with the offset.

    ``2026-09-30T13:58:50.597+02:00``. The offset is what makes a line from
    a container, which usually runs in UTC, comparable with one from the
    machine next to it, and the ``T`` keeps the whole stamp one field.
    """
    local = datetime.fromtimestamp(created).astimezone()
    return local.isoformat(timespec="milliseconds")


# ANSI, and only at a terminal. Each coloured part ends in a reset.
_RESET = "\033[0m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_LEVELS = {
    logging.DEBUG: "\033[34m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}


# A request's status by its class, the way uvicorn colours its own.
_STATUSES = {2: "\033[32m", 3: "\033[33m", 4: "\033[31m", 5: "\033[1;31m"}


def paint(code: str, text: str) -> str:
    return f"{code}{text}{_RESET}" if code else text


def _request_line(record: logging.LogRecord) -> str | None:
    """uvicorn's request line for a terminal: method, path, status, client.

    ``POST /mcp 401 Unauthorized 10.0.0.7:5555``, the status in the colour
    of its class and the client dimmed. ``None`` for any other line.
    """
    seen = request(record)
    if seen is None:
        return None
    try:
        status = f"{seen.status} {HTTPStatus(seen.status).phrase}"
    except ValueError:
        status = str(seen.status)
    status = paint(_STATUSES.get(seen.status // 100, ""), status)
    return f"{seen.method} {seen.path} {status} {paint(_DIM, seen.client)}"


def in_colour(stream: TextIO) -> bool:
    """Whether lines to ``stream`` are coloured.

    Only for a terminal, and not when ``NO_COLOR`` is set to anything, see
    https://no-color.org. A pipe - the client's, under stdio - a container
    log, journald and a file each get the plain line.
    """
    if os.environ.get("NO_COLOR"):
        return False
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    return _console_takes_colour(stream)


def _console_takes_colour(stream: TextIO) -> bool:
    """A Windows console shows the codes as text until it is asked not to.

    Asking can fail, on an old console or a handle that is not one, and the
    line then stays plain rather than full of escape codes.
    """
    if sys.platform != "win32":
        return True
    import ctypes
    import msvcrt

    try:
        handle = msvcrt.get_osfhandle(stream.fileno())
    except (AttributeError, OSError, ValueError):
        return False
    kernel32 = ctypes.windll.kernel32
    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return False
    virtual_terminal_processing = 0x0004
    return bool(
        kernel32.SetConsoleMode(handle, mode.value | virtual_terminal_processing)
    )


class _Line(logging.Formatter):
    """:data:`FORMAT`, with the time as :func:`stamp` writes it.

    ``colour`` gives the same fields at a terminal: the time dimmed, the
    level in its colour, the source in cyan. A traceback follows uncoloured,
    the way the base class appends it.
    """

    def __init__(self, *, colour: bool = False) -> None:
        super().__init__(FORMAT)
        self.colour = colour

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        return stamp(record.created)

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802
        if not self.colour:
            return super().formatMessage(record)
        level = paint(_LEVELS.get(record.levelno, ""), f"{record.levelname:<8}")
        where = paint(_CYAN, f"{source(record.name):<8}")
        message = _request_line(record) or record.message
        return f"{paint(_DIM, record.asctime)} {level} {where} {message}"


def configure(level: str, stream: TextIO | None = None) -> None:
    """Send every line to ``stream``, stderr unless given, at these levels.

    Safe to call again: the handler it installed the last time is replaced,
    and so is the filter on uvicorn's request lines.
    """
    own = logging.getLevelNamesMapping()[level.upper()]
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _MARK, False)]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    setattr(handler, _MARK, True)
    handler.addFilter(_Where())
    handler.setFormatter(_Line(colour=in_colour(handler.stream)))
    root.addHandler(handler)
    # Anything not named here - a library nobody thought of - is held at
    # WARNING by default rather than let through.
    root.setLevel(logging.WARNING)

    logging.getLogger(PACKAGE).setLevel(own)
    for name in LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger(_UVICORN).setLevel(max(own, logging.INFO))

    access = logging.getLogger(ACCESS_LOGGER)
    access.setLevel(logging.INFO)
    for stale in [f for f in access.filters if isinstance(f, AccessLines)]:
        access.removeFilter(stale)
    access.addFilter(AccessLines(everything=own <= logging.DEBUG))
