"""uvicorn's line per HTTP request, cut down to what is safe and useful.

uvicorn writes one line for every request it answers, as
``'%s - "%s %s HTTP/%s" %d'`` with the client address, the method, the path
with its query string, the HTTP version and the status. Two things change on
the way to stderr:

- **The query string is dropped.** The MCP endpoint takes none today, so this
  is a precaution: a query is where a value of the caller's would travel, and
  a request line is no place for one.
- **Below ``DEBUG`` only a refused request is kept**, one answered with 400 or
  above. Those are the requests somebody made without the token or under a
  host name this server does not answer to, and the line carries the client
  address that tried. Every other line says that a client did what clients
  do, once per request.
"""

from __future__ import annotations

import logging

__all__ = ["ACCESS_LOGGER", "AccessLines"]

ACCESS_LOGGER = "uvicorn.access"

# The position of each value in uvicorn's arguments.
_PATH = 2
_STATUS = 4
_FIELDS = 5


class AccessLines(logging.Filter):
    """The filter on ``uvicorn.access``. ``everything`` keeps every request."""

    def __init__(self, *, everything: bool) -> None:
        super().__init__()
        self.everything = everything

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # A line of another shape is passed on as it came. uvicorn has written
        # this one for years, and guessing at a new one could only drop the
        # refusals this filter exists to keep.
        if not isinstance(args, tuple) or len(args) != _FIELDS:
            return True
        status = args[_STATUS]
        if not self.everything and not (isinstance(status, int) and status >= 400):
            return False
        path = str(args[_PATH]).split("?", 1)[0]
        record.args = (*args[:_PATH], path, *args[_PATH + 1 :])
        return True
