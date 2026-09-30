"""Where the lines go, and which of them are let through.

One handler, on stderr, for this server and everything underneath it: under
stdio, stdout is the protocol, and over HTTP a second stream is one more
thing for Docker to keep. ``LXO_MCP_LOG_LEVEL`` sets the level of this
server's own lines and of nothing else.
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

from .access import ACCESS_LOGGER, AccessLines

__all__ = ["LIBRARIES", "PACKAGE", "configure"]

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

FORMAT = "%(asctime)s %(levelname)s %(where)s: %(message)s"

# Marks the handler this module installed, so configuring twice replaces it
# rather than printing every line twice.
_MARK = "_lxo_logbook"


class _Where(logging.Filter):
    """The logger's name, without this package in front of it.

    ``client`` rather than ``benethos_lexware_office_mcp.client``: every line
    of this server would otherwise start with the same thirty characters. A
    library's name is left whole, so ``uvicorn.error`` still says whose it is.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name
        prefix = f"{PACKAGE}."
        record.where = name[len(prefix) :] if name.startswith(prefix) else name
        return True


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
    handler.setFormatter(logging.Formatter(FORMAT))
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
    for old in [f for f in access.filters if isinstance(f, AccessLines)]:
        access.removeFilter(old)
    access.addFilter(AccessLines(everything=own <= logging.DEBUG))
