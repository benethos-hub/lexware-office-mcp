"""Every line this server writes to stderr, and where those lines go.

The log answers three questions for whoever runs the server: is it running,
and with which permissions? What did the assistant change in the books? What
was refused or failed, and why? For whoever develops it, a fourth: which API
calls did a tool make?

**What never goes into a line.** The log is read on the machine, kept by
Docker and shipped to wherever an operator collects logs, so it is held to a
stricter rule than a tool result:

- the API key and the bearer token
- a tool's arguments: search terms, names, email addresses, amounts, notes,
  paths the model named. A line names the tool and the Lexware id of the
  record, never what went in
- anything the API answered with: no customer record, no voucher, no amount
- a URL's query string. A request line carries the path only
- this server's own error messages, which are written for the model and
  quote what it sent. A line names the error class, and for a refusal by the
  API its status and code
- the name of a downloaded file, which is the document's name and often the
  customer's

What a line may carry: tool names, Lexware ids, HTTP status codes, the API's
error codes, counts, durations, sizes, version numbers, and the paths of the
configuration files, which the person at the machine needs to act on.

The libraries underneath are held to the same rule by being held at
``WARNING``, see :mod:`.output`.

The modules:

- ``output`` - the one handler on stderr, the levels, the short logger names
- ``access`` - uvicorn's line per HTTP request, cut down to what is safe
"""

from __future__ import annotations

from .output import configure

__all__ = ["configure"]
