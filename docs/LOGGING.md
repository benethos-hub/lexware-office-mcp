# Logging

Section 11.2 of the [concept](CONCEPT.md).

Built 2026-09-30. Before it, what was logged followed from library defaults
rather than from a decision: at `INFO` httpx wrote every API request with its
whole URL, so a `search_contacts` put the name or email it searched for into
a container log that outlived the call, and uvicorn wrote a line per HTTP
request to stdout.

**What the log is for.** Three questions for whoever runs the server: is it
running, and with which permissions? What did the assistant change in the
books? What was refused or failed, and why? And one for whoever develops it:
which API calls did a tool make? There is one process and one actor, the
model behind the client, and no store but stderr, so no user, no session and
no audit table.

**What never goes into a line.** Stricter than the rule for a tool result,
because stderr is kept by Docker and shipped to wherever logs are collected:

- the API key and the bearer token
- a tool's arguments - search terms, names, email addresses, amounts, notes,
  paths the model named. A line names the tool and the Lexware id of the
  record, never what went in
- anything the API answered with - no customer record, no voucher, no amount
- a URL's query string. A request line carries the path only
- this server's own error messages, see
  [section 12](concept/errors-and-output.md#12-error-handling)
- the name or path of a downloaded file, which is the document's name and
  often the customer's

What a line may carry: tool names, Lexware ids, HTTP status codes, the API's
error codes, counts, durations, sizes, version numbers and the paths of the
configuration files, which the person at the machine needs to act on.

**How that is held.** Every line is a function in one of the catalogue
modules of `logbook/`, and no other module imports `logging`. A function's
parameters are drawn from a vocabulary that `tests/test_logbook_catalog.py`
spells out with what each name may hold, so a new parameter is a decision
made in that test rather than a `query` that slipped into a signature. An
exception reaches a line through `describe()`, which reads its class, the
system's reason for an `OSError`, the position of a JSON error, and a
`ToolError`'s `status` and `code` - never its text. An id is shown only when
it is a UUID, and a request path only as lowercase words and UUIDs, because
an id is the model's argument and a name put where one belongs would
otherwise be written down. Anything else is shown as `~`.

**Levels.** `LXO_MCP_LOG_LEVEL` sets the level of this server's lines and
nothing else.

| Level | What | Example |
|---|---|---|
| `ERROR` | a crash, with its traceback, written by the SDK | a tool raised something that is not a `ToolError` |
| `WARNING` | refused or failed, the server carries on | a tool refused by the policy or the API, a retry, the breaker, a rejected key, writing tools switched on |
| `INFO` | what changed, what was read, the lifecycle | start, every tool call, the tool list changing, older downloads deleted, a save in the interface |
| `DEBUG` | the steps, without content | every API attempt with its status and duration, a reused download |

**Reading is `INFO` like writing**, decided 2026-09-30: the log is where the
account owner sees what the assistant looked at as well as what it changed.

**One handler, and it is this server's.** Every `MCPServer` the SDK builds
calls `logging.basicConfig`, with a `RichHandler` where `rich` is installed
and a plain stream handler where it is not, and the first is built when
`server.py` is imported, before the command line is read. Until 2026-09-30
that made this server's own `basicConfig` a no-op, so the level setting was
ignored and every line was wrapped to a console's width. The registry server
is now built inside `untouched_root()`, which takes off whatever that added,
whatever its type. A test in a fresh process holds the import order a real
start has, and the oldest allowed SDK, which has no `rich`, is what showed
that looking for a `RichHandler` was not enough.

**The libraries stay at `WARNING`, and there is no switch to lower them.**
An HTTP client names every request with its URL, and the SDK writes a
failed tool's message at `INFO`, which quotes the arguments. The server
writes its own line for both. Two clients are held by name: httpx and
httpcore, which this server uses for Lexware and for a fetched upload, and
httpx2 and httpcore2, which the SDK uses. A test fails when a held name is
not installed or when an HTTP client in the process logs under a name the
list does not hold. uvicorn's lifecycle messages stay at `INFO`.

**uvicorn's request line goes to stderr.** It is started with
`log_config=None`, so it installs no handler of its own. A filter drops the
query string and, below `DEBUG`, keeps only a request answered with 400 or
above: the ones made without the token or under a host name this server does
not answer to, with the client address that tried. That line is the record
of a refused bearer token, so the server writes none of its own. The SDK
writes a refused `Host` header as a warning itself.

**What a line looks like.** The time, the level padded to eight characters
so the sources line up, the source and the message:

```
2026-09-30T13:58:50.597+02:00 INFO     tools: search_contacts read 12 rows in 1 API call, 230 ms
2026-09-30T13:58:51.020+02:00 WARNING  tools: update_voucher refused: ConflictError 406 version: invalid_value
```

The time is ISO 8601 in local time, to the millisecond, with its offset. A
container usually runs in UTC, and the offset is what makes its lines
comparable with those of the machine next to it. The `T` keeps the stamp one
field for anything that splits a line on spaces. A traceback follows on the
lines after the message.

**At a terminal the same fields are coloured**, and nowhere else: when
stderr is a TTY and `NO_COLOR` is not set to anything, following
https://no-color.org. The time is dimmed, the level is blue for `DEBUG`,
green for `INFO`, yellow for `WARNING`, red for `ERROR` and bold red for
`CRITICAL`, the source is cyan and padded to eight characters, and each
coloured part ends in a reset. A traceback stays uncoloured. A client's pipe
under stdio, a container log, journald and a file get the plain line. A
Windows console shows the codes as text until the process asks it not to, so
the server asks, and keeps the line plain where the console refuses.

uvicorn's request line is laid out again at a terminal, as method, path,
status with its phrase, and client: `POST /mcp 401 Unauthorized
10.0.0.7:5555`. The status has the colour of its class the way uvicorn
colours its own, green for 2xx, yellow for 3xx, red for 4xx and bold red for
5xx, and the client is dimmed. Anywhere else it keeps uvicorn's shape,
`10.0.0.7:5555 - "POST /mcp HTTP/1.1" 401`.

**A line names its source in short.** This server's loggers without the
package in front, `tools` rather than `benethos_lexware_office_mcp.tools`,
and the package itself as `server`. uvicorn's request line is `http`, and
its own lines, from `uvicorn.error` and `uvicorn`, are `uvicorn`: it names
its server log after the error log of the classic web servers, into which a
server writes everything about itself, and spelled out an ordinary start
reads like a failure. Any other logger keeps its full name.

**Ctrl+C ends in a line and exit code 130, not a traceback.** uvicorn shuts
down cleanly on SIGINT, as far as `Finished server process`, and then raises
the signal again on purpose so the process ends as interrupted. Uncaught,
that is a `KeyboardInterrupt` traceback that reads like a crash, and stdio
ends the same way. `cli.main` catches it around the whole run, writes
`Stopped by an interrupt` and exits with 130, which is 128 plus SIGINT, for
every transport. SIGTERM, which `docker stop` and systemd send, is not
affected, since Python turns only SIGINT into an exception: the server shuts
down without the extra line and without a traceback. `setup` catches Ctrl+C
itself and ends with the same line, with `Stopped from the page` after
*Beenden*, or with `Stopped after 30 minutes without a request` under
`--exit-when-idle`. Its lines go through the catalogue, so they carry the
time and the level like every other.

**The catalogue**, by module. The logger name a line carries is in brackets
where it differs.

| Module | Level | Line |
|---|---|---|
| `lifecycle` (`server`) | `INFO` | `0.10.6 started over stdio`, `Settings from <path>` or that no `.env` was found, what is enabled when nothing can write, where HTTP listens, `setup` started from the prompt or found open already, ending on a changed settings file, `Stopped by an interrupt` |
| | `WARNING` | no policy file, what is enabled when something can write and which, bound to a non-loopback address, a token generated, a key saved after the start that could not be read, `setup` that could not be started from the prompt |
| `policy` | `DEBUG` | a client that could not be told about the change and was dropped, which a client that went away makes normal |
| | `INFO` | `The tool list changed, 2 clients told`, counting those told on their own channel and not the listen streams of the 2026-07-28 protocol, see [section 9.2](concept/permissions.md#92-the-policy) |
| | `WARNING` | an unreadable policy, one that is not an object, a flag that is not a boolean - each once, and again only after the file says something else, since the watcher reads it every two seconds, and a turn of the watcher that failed, by the error's class, before the next one follows |
| `api` (`client`) | `DEBUG` | `GET /v1/contacts 200 in 230 ms, attempt 1`, an attempt without an answer, a honoured Retry-After, a Retry-After that was no number of seconds, a status check that failed for a reason nothing in this server raises, by the error's class |
| | `WARNING` | `GET /v1/profile answered 503, attempt 2 follows in 1.2 s`, `GET /v1/profile got no answer (ReadTimeout), attempt 2 follows in 1.2 s`, the breaker holding requests, a rejected key, a Retry-After too long to wait |
| `calls` (`tools`) | `INFO` | `search_contacts read 12 rows in 1 API call, 230 ms`, `get_contact read <id>`, `download_file read <id>, 148 kB`, `create_contact wrote <id> (version 0)`, `upload_file wrote <id> for voucher <id>`, `(version 1, finalized)`, `delete_article removed <id>` |
| | `WARNING` | `<tool> refused: <class> [status] [codes]`, `<tool> failed: UpstreamError 503, outcome unknown`, `<tool> refused: invalid page` for arguments the schema refused |
| `files` (`storage`, and `fetch` for an upload's URL) | `INFO` | `Deleted 2 older downloads, the newest 100 are kept`, by count and never by name, `The download list changed, 2 clients told`, `Fetched 48213 bytes to upload from https://files.example.com in 310 ms`, by scheme and host and never the path or the query |
| | `WARNING` | `Fetching an upload from https://files.example.com failed: UpstreamError 404`, or with `timeout`, `connection` or the refusal's class where the status was fine and the file was not, `Refused to fetch an upload over https: the address is outside LXO_MCP_UPLOAD_URLS, nothing was requested` without the host the model chose, the same for what is no URL that can be fetched, and that no address is allowed at all, and a download answered while the clients could not be told the list changed, by the error's class |
| | `DEBUG` | a download that reused an identical file, by size |
| `configui` | `INFO` | the key written, checked or not, the token written or generated, which settings were written, the policy with nothing that writes, a profile created, overwritten or deleted, a browser signed in with the start code but never the code, the three files `setup` edits, `Stopped by an interrupt`, `Stopped from the page` or stopped after the idle minutes `--exit-when-idle` named |
| | `WARNING` | the address with the start code, the one line that carries it and at this level so no log level hides it, a bind beyond loopback, the policy with writing tools on and which, a key the account refused, a request a guard refused, a wrong start code among them, a file that could not be written, unreadable profiles |
| | `ERROR` | a port `setup` could not open, before it ends |

**Where a tool's line comes from.** Not from the tools, which stay thin.
`register_tool` puts `logged()` around every tool, outside the policy guard,
so a call the policy refuses is a line too and no tool can forget to report
itself. It times the call and counts the API calls through a context
variable the client increments per attempt. The variable is per task, so two
calls at once each count their own. From the result it takes only the id,
version, rows, size and the voucher an upload created. Arguments that fail
the schema never reach that wrapper, so `PolicyServer.call_tool` names their
fields. `server_status` is registered past it and writes no line, since
asking how the server is changes nothing.

**The configuration interface keeps no request log.** It is one person on
the local machine, and a request log would record them clicking. What it
writes down is what changed and what it refused, so whoever changed the key
or switched on a writing tool left a trace. Never a setting's value, only
its name.
