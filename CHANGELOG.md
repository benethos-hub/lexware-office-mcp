# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

Every user-facing change gets an entry under `[Unreleased]` in the same commit
that makes the change, never in a later cleanup pass. Entries describe what
changed for someone using this server. Development process and internal
housekeeping are out of scope here — design decisions live in
[SPECS.md](SPECS.md).

## [Unreleased]

### Changed

- **The documentation and `containers/production/` name the image
  `ghcr.io/benethos-hub/benethos-lexware-office-mcp`**, which 0.4.2
  introduced. It is the image `ghcr.io/benethos-hub/lexware-office-mcp`
  carries as well, until 0.5.0. Downloading the production folder again
  moves an installation over, and its volumes stay.

## [0.4.2] - 2026-10-08

The container files move into `containers/`, where the production folder
runs the published image without a clone of the repository, and the
restart on a changed `.env` that the image relies on loses nothing any
more. No change to any tool, parameter or answer. **If you run the
Compose file from the repository root**, it is gone: see the Compose
entry below, the volumes carry over.

### Fixed

- **A setting saved in the first seconds after a start reaches the
  server.** With `LXO_MCP_EXIT_ON_CONFIG_CHANGE`, as in the image, the
  watch took the `.env` as it found it two polls into the start, so a save
  in those two to four seconds - a key entered while the container was
  coming up - was taken as the starting state and never ended the process,
  which kept running without it. The watch now compares with the file as
  the settings were read from it.
- **An open stream no longer keeps an HTTP server running indefinitely**
  once it was asked to end, by a changed `.env`, Ctrl+C or `docker stop`.
  It waits five seconds for open connections, then closes them, and a
  client reconnects to the new process. Over `sse` a client holding its
  stream open had kept the old process, and the old settings, alive.

### Changed

- **The image is published under the package's name as well**:
  `ghcr.io/benethos-hub/benethos-lexware-office-mcp`, beside
  `ghcr.io/benethos-hub/lexware-office-mcp`. Both carry the same image.
  The old name gets the 0.4 patch releases and none from 0.5.0 on, its
  `:latest` included, so move to the new one at your next update.
- **The Dockerfile moved to `containers/images/lexware-office-mcp/`.** A
  build of your own names it, still from the repository root:
  `docker build -f containers/images/lexware-office-mcp/Dockerfile .`
  The image it builds is the same.
- **Compose moved into `containers/`, in two folders, and the root
  `compose.yaml` is gone.** `containers/production/` runs the published
  image at the version `LXO_VERSION` names in an `.env` beside it, made
  from `.env.example`, and needs nothing else from the repository. It
  keeps the project name of the root file, so its volumes carry over with
  the key, the token and the tools: `docker compose up -d` there replaces
  the container and keeps them. `containers/development/` builds from the
  checkout under a project of its own, on `127.0.0.1:8780` and `8781`,
  with volumes of its own. Switching to the published image by commenting
  lines is no longer needed.
- **The container runs hardened under Compose**: a read-only root file
  system, `/tmp` in memory, no Linux capabilities and `no-new-privileges`.
  It writes nothing but its volumes and `/tmp`, so nothing it does changes.
  The README's `docker run` examples carry the same flags.

## [0.4.1] - 2026-10-05

A patch release for the container image, which is built from the
lockfile and had fallen behind it. No change to any tool, parameter or
answer. An installation from the index resolved most of this already.

### Changed

- **The container image is built on current dependencies**:
  cryptography 50.0.2, whose wheels carry OpenSSL 4.0.3, pypdfium2
  5.14.0 with PDFium 156, platformdirs 4.12.3 and rpds-py 2026.9.1 in
  the lockfile the image is built from. An installation from the index
  resolved them already. mypy, ruff and python-dotenv moved in the
  development environment only.

- **MCP SDK 2.3.0.** The tool list, a refused call, an argument the
  schema rejects and an unknown tool reach a client byte for byte as
  before, over both protocol versions. The answer to `initialize` no
  longer carries an empty `experimental` capability.

- **The container image runs Python 3.14.8**, on the current
  `python:3.14-slim` base with its system packages, and is built with
  uv 0.12.23. Both are pinned by digest, so the image moves only when
  that pin does.

## [0.4.0] - 2026-09-30

A minor release, because an existing installation can trip over four of
these: the download directory is cut down to its newest 100 files on the
first start, an API key or bearer token with a character no HTTP header can
carry now stops the start, `create_contact` and `update_contact` refuse a
field the contact's kind has no place for, and every log line has a new
time format and shorter source names, which anything parsing the log will
notice. Each of them says what happened, on stderr or in the tool's answer.

### Security

- **A key the configuration interface is checking is never shown back.**
  A key typed into the form was tried before it was known as a secret, and
  one with a line break or a NUL in it made the HTTP library refuse the
  header and quote it, so the page showed `Bearer` and the key. It is
  registered before it is tried, and a secret is also redacted where a
  message quotes it escaped, as bytes.
- **The configuration interface no longer claims a `0.0.0.0` bind is
  safe.** The warning at its start said the pages answer only when called
  as `127.0.0.1` or `localhost`, and the 0.3.0 entry said such a bind does
  not answer the network. The check reads the `Host` header, which the
  caller writes, so it stops DNS rebinding in a browser and nothing more.
  The warning now says that whoever reaches the port can open the pages
  and change the key, and to use `--host 127.0.0.1` outside a container.

### Changed

- **The download directory keeps the last 100 documents.** Older downloads
  are deleted when the server starts and after each download. Every document
  is still in Lexware Office, so one that is needed again is downloaded
  again. Nothing was ever deleted before, so an existing directory is cut
  down to its newest 100 files on the first start. `LXO_MCP_KEPT_DOWNLOADS`
  sets the number, and `0` keeps everything. It applies to the default cache
  directory, and to a directory named by `LXO_MCP_DOWNLOAD_DIR` only when it
  is set as well. Only a file named the way a download is named is counted
  or deleted, so a space, an umlaut or an extension such as `.docx` keeps a
  file of your own out of it. The configuration interface shows and edits
  it beside the download directory. The container image sets it to 100 for
  its `/downloads` volume. `read_download` and a resource read for a download
  that is gone say that it may have been removed and to download it again.
- **The resource list names the same newest downloads**, newest first, where
  it named every file in the directory in name order. It is read from the
  directory at the moment a client asks, so a file that is gone is gone from
  the list at once, and a server start no longer reads the whole directory.
  A download that finds its unchanged file already on disk counts as new.
- **`compose.yaml` caps what Docker keeps of the logs**: five files of 10 MB
  per service, the oldest dropped first. The server wrote a line for every
  HTTP request, refused ones included, and at `DEBUG` still does, see below.
  Docker kept all of it for as long as the container existed, restarts
  included. The README's `docker run` example sets the same cap.
- **A search term no longer reaches the log.** At `INFO` httpx wrote every
  API request with its whole URL, so a `search_contacts` left the name or
  email address it looked for on stderr, and in a container's log for as
  long as Docker kept it. `LXO_MCP_LOG_LEVEL` now sets the level of this
  server's own lines only. httpx, httpcore and the MCP SDK stay at
  `WARNING` whatever it says, and there is no setting to lower them.
- **Over HTTP, uvicorn's line per request moved from stdout to stderr**, and
  lost its query string. At `INFO` it appears only for a refused request,
  one answered with 400 or above, which carries the client address that
  tried. `DEBUG` shows every request.
- **uvicorn's lines are named `uvicorn`, and its request line `http`**,
  where they carried the logger names `uvicorn.error` and `uvicorn.access`.
  The first made an ordinary start read like a failure.
- **A line's time is ISO 8601 with milliseconds and the offset**,
  `2026-09-30T13:58:50.597+02:00` where it was `2026-09-30 13:58:50,597`
  without saying which zone, and the level is padded to eight characters so
  the sources line up.
- **At a terminal a line is coloured**: the time dimmed, the level in a
  colour of its own, the source in cyan. Only when stderr is a terminal and
  `NO_COLOR` is not set, so a client's log, a container log and a file get
  the plain line as before. uvicorn's request line reads `POST /mcp 401
  Unauthorized 10.0.0.7:5555` there, the status in the colour of its class
  and the client dimmed.
- **The start names the `.env` it read**, `Settings from <path>`, or says
  that none was found and the settings come from the environment and the
  defaults. Only the policy file was named before, so which of the
  searched places had supplied the settings was not to be seen.
- **The first line says which version started over which transport**, and a
  line at `INFO` says when the tool list changed and how many clients were
  told. A broken policy or profile file is named with the reason it could
  not be read - the error's class, and the system's reason or the position
  in the JSON - rather than with the error's whole text.
- **Every API call is a line of this server's own at `DEBUG`**, in place of
  the one httpx wrote: method, path, status, milliseconds, which attempt,
  and how long it waited for the rate limiter. The path shows resource names
  and ids and nothing else. A retry, the circuit breaker holding requests
  back and a rejected API key are each a `WARNING`.
- **Every tool call is a line at `INFO`**: what it read or wrote, how many
  API calls it made and how long it took - `search_contacts read 12 rows in
  1 API call, 230 ms`, `create_contact wrote <id> (version 0) in 1 API
  call`, `create_sales_document wrote <id> (version 1, finalized)`. A line
  names the record by its id, a list by its count of rows and a download by
  its size, and never carries an argument, an answer or a file name. A call
  that was refused or failed is a `WARNING` naming the error's class, and
  for a refusal by the API its status and error codes: `update_voucher
  refused: ConflictError 406 version: invalid_value`. Arguments that do not
  match a tool's schema are named by field.
- **The configuration interface leaves a trace of what it changed.** Saving
  the API key, the bearer token, a setting, the tool policy or a profile is
  a line on stderr, and switching on a tool that can write is a `WARNING`
  that names it. So is a request one of its guards refused, and a file it
  could not write. The key, the token and a setting's value are never in a
  line, only which setting changed. The pages keep no request log.
- **The container image is built on current dependencies**: sse-starlette
  3.5.0, PyJWT 2.15.1 and platformdirs 4.12.2 in the lockfile the image is
  built from. An installation from the index resolved these already.

### Fixed

- **An API key or a bearer token with a character no header can carry is
  refused where it is set.** A zero-width space or a space copied along with
  the key made every request fail to encode, which reached the model as a
  crash, and the configuration interface's check ended without an answer.
  The server now refuses such a value at start, naming the setting and never
  the value, and the interface refuses it before trying or writing it.
- **A policy file named with `--tools-file` stays marked as named** in the
  configuration interface after a save. Saving anything read the settings
  again, and the badge switched to "Suche" although the file had not
  changed.
- **JSON nested deeper than Python's stack is an unreadable file**, not a
  crash: an imported policy in the configuration interface, the policy file
  a server reads, which then enables nothing as for any broken file, and
  the saved profiles.
- **A security token with a character outside ASCII is refused** by the
  configuration interface like any other wrong token, where it ended the
  request without an answer.
- **Deleting a profile the configuration interface cannot write is
  reported** on the page, as saving and overwriting one already were, where
  the browser got a dropped connection.
- **An update retried after a lost answer no longer blames somebody
  else.** When the first attempt went through and only its answer was
  lost, the retry was refused as stale and the model was told the record
  had changed since it was read - which invites applying the same change
  again. It now says the first attempt was most likely carried out, and to
  check the record before sending the change again.
- **The tool policy and the saved profiles are written whole or not at
  all**, the way the `.env` already was. They were written in place, and a
  running server that reads the policy the moment it changes could catch it
  half-written, fall back to nothing enabled and tell its clients twice. A
  new policy or profiles file is readable by its owner only.
- **A text line in `create_sales_document` needs only its text.** The
  schema demanded a quantity, a unit, a price and a tax rate for every
  line, and a text line then dropped all four, so the model had to invent
  values that went nowhere. They are optional in the schema now, and a
  priced line without one of them is refused before any request, naming
  what is missing.
- **`create_contact` and `update_contact` refuse a field the contact has
  no place for.** A VAT id or a tax number on a person, or a first name or
  a salutation on a company, was left out of the request, and the call
  reported success with nothing of it stored. It is now a validation error
  naming the field, before any request.
- **An answer that cannot be decoded is a clean failure.** A response
  announcing a compression its body did not have escaped as a crash, so
  the model was told only which tool failed, and after a write not that its
  outcome was unknown. It is now handled like a lost connection: a read is
  retried, and a create says the record may or may not exist.
- **A `Retry-After` is waited out in full.** The random spread that keeps
  retries apart was applied after it, so `Retry-After: 7` could be retried
  after three and a half seconds, early enough to be refused again. The
  spread now shortens only the server's own backoff.
- **Saving in the configuration interface no longer ends without an
  answer** when the `.env` already held a value the server refuses. The key
  or the token was written, reading the settings back failed on the other
  value, and the browser got a dropped connection. The page now says it was
  written and quotes why the server would refuse the file.
- **On Windows, `setup` no longer starts on a port already in use.** It
  bound the port anyway, and the browser kept talking to whatever had it
  first - an interface started earlier, or another program - which then
  received the key typed in. A taken port now ends `setup` with one line
  that says so and suggests `--port`.
- **Ctrl+C ends in one line and exit code 130, not a traceback.** Over
  HTTP, uvicorn shut down cleanly and then raised the interrupt again, and
  stdio ended in it as well, so stopping the server by hand printed a
  `KeyboardInterrupt` traceback that read like a crash. It now writes
  `Stopped by an interrupt` and exits with 130. `docker stop` and systemd
  were never affected.
- **`LXO_MCP_LOG_LEVEL` and `--log-level` take effect.** They were ignored:
  the MCP SDK put a handler of its own on the root logger when the server
  module was imported, before the setting was read, so the level stayed at
  the SDK's `INFO` whatever it said, and every line was wrapped to the width
  of a console. That handler is no longer left in place, whichever kind the
  SDK installed, and each line appears once, on one line.

## [0.3.0] - 2026-09-27

A minor release, because an existing installation can trip over four of
these: a policy file with `"true"` as a string, an `http://` base URL, a
`LXO_MCP_PDF_PAGES` above 100, and a configuration interface reached under a
name other than `127.0.0.1`, `localhost` or `::1`. None of them fails
silently: each is named on stderr or refused with a message that says what
to change.

### Security

- **Only JSON `true` enables a tool in the policy file.** A value was read
  with `bool()`, so `"create_voucher": "false"` - a non-empty string -
  switched the tool on. Anything but `true` is now off, and a value that is
  not a boolean is named on stderr. The configuration interface reads an
  imported file by the same rule.
- **Downloads are resources only while a download tool is enabled.** Every
  file in the download directory was listed and readable over
  `resources/list` and `resources/read` even with a policy that enabled
  nothing. Now they answer only while `download_file`, `download_document`
  or `read_download` is on, and a symbolic link in the directory is never
  published.
- **The configuration interface checks the port and issues its own tokens.**
  A form post was accepted from any loopback page, and the session cookie was
  accepted whatever its value. Because cookies are not scoped by port, a page
  served by another local program could set the cookie, submit a form, point
  the API base URL at its own host and have the connection test send the key
  there. Now `Origin` has to name this page's host and port, and only a token
  this process issued counts.
- **The configuration interface answers only to a loopback name.** A page
  whose `Host` is not `127.0.0.1`, `localhost` or `::1` is refused, so DNS
  rebinding cannot read the pages - bearer token included - and a `--host
  0.0.0.0` bind outside a container does not answer the network. Every
  response carries `Cache-Control: no-store`.
- **A line break in a setting is refused rather than written.** A value
  carrying `%0A` from a form ended its line in the `.env`, and what followed
  became a setting of its own - `LXO_MCP_API_KEY` included, unchecked. The
  `.env` is now written to a temporary file and moved into place, and a new
  one is created readable by its owner only. An existing file keeps its
  permissions.
- **New setting `LXO_MCP_UPLOAD_DIR`: the one directory the upload tools may
  read from.** `upload_file` and `attach_file_to_voucher` take a path from
  the model and read any file the process can read with an accepted
  extension. With the setting, a file has to resolve inside that directory
  or is refused before any request. Unset, nothing changes, and the README
  now says so plainly.
- **Smaller hardening.** The configuration interface refuses a form body over
  1 MiB or with a nonsense `Content-Length` without reading it, and sends
  headers that keep its pages out of frames and out of `Referer`.
  `get_deeplink` encodes the id, so a slash or `?` in it can no longer point
  the link at another page of the web app. The HTTP transport closes a
  websocket before accepting it and passes no scope but `lifespan` unguarded.
- **An id can no longer steer a request to another endpoint.** Ids were put
  into request paths as the model sent them, so `x/../../articles/y` could
  turn an update of a contact into one of an article, and the same for a
  delete. Every id is now percent-encoded into its own path segment, and
  `.`, `..` or an empty id is refused before any request.
- **`LXO_MCP_BASE_URL` and `LXO_MCP_APP_BASE_URL` must be `https://`.** The
  server refuses to start otherwise, and the configuration interface refuses
  to save one.

### Fixed

- **`read_download` rendered PDF pages with red and blue swapped.** PDFium
  hands out BGR and the PNG declared RGB, so the red stamp on a dunning
  letter came out blue.
- **A write whose answer cannot be read is reported as an unknown outcome.**
  An empty, HTML or non-object body on a successful create, update or upload
  escaped as a plain exception, so the model was told only that the tool
  failed - an invitation to try again and make a second record. It now says
  the request may have been carried out and to check before retrying.
- **A `Retry-After` longer than eight seconds ends the call instead of
  stalling it.** The header was honoured without a limit, inside the tool
  call: `86400` held it for a day and `inf` for ever. Up to eight seconds it
  is still honoured, beyond that the call answers that it was rate limited.
- **A `.env` saved with a byte order mark is read correctly.** Windows
  editors write one, and it became part of the first key, so an
  `LXO_MCP_API_KEY` on line one was not found. A rewrite through the
  configuration interface drops the mark.
- **A setting that appears twice in the `.env` is rewritten everywhere.** The
  configuration interface replaced the first occurrence while the server
  reads the last, so a key reported as checked and saved was never used.
- **A missing `version` is no longer reported as a changed record.** In the
  `IssueList` shape the API names it `missing_entity`, and the model was
  told to read the record again - which does not help when the request
  simply did not carry one.
- **A file that cannot be written or read is an answer, not a crash.** A full
  disk, a download directory owned by someone else, a locked receipt or too
  many files of one name reached the model as a bare tool failure. The
  download and upload tools now say what the system refused, without a path.
- **`LXO_MCP_DOWNLOAD_DIR` expands `~`**, as `LXO_MCP_TOOL_POLICY` always
  did. `~/Belege` created a folder literally named `~`.
- **`nan` and `inf` are refused as numbers.** `LXO_MCP_RATE=nan` let no
  request through ever, and `inf` switched the rate limiter off. The server
  now refuses to start with either, as it does with any other bad number.
- **A bad setting no longer breaks `--version`, `--help` or `setup`.** The
  server was built from the environment the moment its module was imported,
  so one bad value ended every command with a traceback. Starting the server
  with one now ends in a single line naming it.
- **Each server answers to its own policy file.** There was one policy per
  process, set by whichever server was built last, and every call guard read
  that one.
- **Downloading an unchanged document again no longer logs a warning** on
  stderr every time.
- **A timeout ends a run of rate limits.** The breaker that pauses after three
  429s in a row counted across a network failure, so two 429s either side of
  a timeout paused the server for thirty seconds.
- **`delete_article` no longer reports a deletion it made as not found.**
  When the first attempt's answer was lost and the retry found nothing, the
  404 was passed on - as if the article had never existed.
- **`read_download` finds a file under the name it is listed by.** A file
  put into the download directory by hand, such as `my invoice.pdf`, was
  offered as a resource under its own name and then looked up under a
  sanitized one, so it could be listed but not read. A percent-encoded name
  is found too.
- **A download named like a Windows device is saved under another name.**
  `CON.pdf` or `LPT1.pdf` from the API is the console or a printer port on
  Windows, not a file, and is now saved as `_CON.pdf`.
- **Two downloads at once can no longer overwrite each other.** A name was
  checked and then written, so two downloads could both find it free. The
  file is now created exclusively.
- **Rendering a PDF no longer holds up every other call.** `read_download`
  rendered on the event loop, so a long document stalled the whole server
  for as long as it took. Rendering and file access now run in a worker
  thread.
- **`read_download` renders at most 100 pages.** `max_pages` accepts up to
  100, `null` means every page up to that, and `LXO_MCP_PDF_PAGES` above 100
  is refused. `pages` and `pagesShown` still say what was left out.
- **A process with no home directory says what to set.** With `HOME` unset
  and no password database entry for the uid, platformdirs 4.12 raises
  instead of answering a relative `~/.config/...`, and the server ended in a
  traceback. Now a configuration file in the working directory or a checkout
  is still found, and where none exists the server says in one line to set
  `HOME` or to name the files with `--env-file` and `--tools-file`. A
  download asks for `LXO_MCP_DOWNLOAD_DIR` in the same case.
- **`update_contact` replaces the email address and the phone number.** The
  new value was filed under `business` or `private` beside the old one, so a
  contact whose address sat under `office` ended up with two. It now replaces
  what the contact had, and a contact that used one category keeps it.
- **`update_voucher` keeps the totals when no line changes.** They were
  added up again from the lines on every update, which for a voucher made
  from an upload, holding no lines yet, meant a total of zero. Now they are
  worked out only when `items` is passed, and otherwise sent as read.
- **`search_articles` and `get_recurring_templates` follow
  `LXO_MCP_PAGE_SIZE`.** Both asked for 25 rows whatever it said. Articles
  still ask for at least 25, the least that endpoint accepts.

### Changed

- **Dependencies refreshed**: httpx2 and httpcore2 2.13.1, starlette 1.7.0,
  uvicorn 0.54.0, pyjwt 2.15.0, platformdirs 4.12.0, idna 3.20,
  opentelemetry-api 1.45.0 and ruff 0.16.9. No change to any tool, parameter
  or answer.
- **`get_sales_document` tells a draft by `voucherStatus`.** Its description
  pointed at the missing `files.documentFileId`, which Lexware has marked for
  removal on every sales document type. The answer itself is unchanged.

### Added

- **`update_voucher` takes `use_collective_contact`.** A voucher could be
  moved to a named contact but not back to the collective one, which only
  `create_voucher` could choose. Passing it together with `contact_id` is
  refused before anything is sent.
- **`search_vouchers` takes `voucher_number`.** It finds a document by its
  number in one call, sales documents included, which until now only
  `get_voucher` could do and only for bookkeeping vouchers. The number is
  matched in full, ignoring case.
- **`search_vouchers` sorts by number, creation and last change too.** Its
  description said the API sorts on the voucher date and nothing else, and
  `sort` offered only that. The API honours `voucherNumber`, `createdDate`
  and `updatedDate` as well, each way round.
- **`update_voucher` can book an unchecked voucher.** A receipt sent with
  `upload_file` arrives `unchecked`, and could be filled in but never
  booked: the update left it unchecked. `finalize`, together with `confirm`,
  now moves it to `open`. It is refused for a voucher in any other state
  before anything is written.

## [0.2.4] - 2026-09-14

### Changed

- **MCP SDK raised to 2.2.0**, from 2.1.1. Over stdio nothing a client sees
  moves: the tool list, the `initialize` answer, a delivered error message and
  a rejected argument were captured on both versions and are byte-identical.

  **Over HTTP, an idle session now expires after 30 minutes.** The SDK closes a
  streamable-HTTP session with nothing in flight for that long, and the
  client's next request is answered 404 and has to initialize again. A client
  that keeps its GET stream open is not affected, and neither is stdio, which
  has no sessions. This is the SDK's new default and it is kept: a session a
  crashed client left behind no longer lives until the server does.

- **Dependencies refreshed**: uvicorn 0.53.0, anyio 4.15.1 and sse-starlette
  3.4.11 in the HTTP transport, pyjwt 2.14.0, plus coverage and ruff to their
  current releases. No change to any tool, parameter or answer, and the tool
  list a client receives is byte-identical.

## [0.2.3] - 2026-09-02

### Fixed

- **Error messages reach the model again on MCP SDK 2.1.** The SDK sorts a
  failing tool call by the type of what was raised: its own `ToolError` is a
  failure the server anticipated and its message is handed to the model, while
  anything else counts as a crash and the model is told only `Error executing
  tool <name>`. This server's error classes derived from plain `Exception`, so
  on 2.1 every message it sends - no API key configured, key rejected, record
  not found, rate limit, tool not enabled for this installation - was replaced
  by that one sentence. They now derive from the SDK's class.

  This affected installations of 0.2.2 and earlier, not only this checkout:
  the declared range is `mcp>=2.0.0,<3`, so anyone installing after the SDK's
  2.1.0 release resolved to it and lost the messages. Measured over real stdio
  against 2.1.1, both before and after.

### Changed

- **MCP SDK raised to 2.1.1**, from 2.0.0. The tool list a client receives is
  byte-for-byte unchanged, and so is its size. Two behaviour changes come with
  it: the error sorting above, and a crash inside a tool no longer puts the
  exception's own text on the wire.

- **Dependencies refreshed**: cryptography 50.0.1, platformdirs 4.11.7,
  pydantic 2.13.5, and click, coverage, ruff and typer to their current
  releases. No change to any tool, parameter or answer.

## [0.2.2] - 2026-08-23

### Removed

- **`create_voucher` no longer takes `unchecked`.** The API stopped accepting
  it. It worked on 2026-08-20 and on 2026-08-23 the same call is refused with
  `voucherStatus: invalid_value`, across three voucher types - so every call
  setting the flag now fails. A voucher is booked as it is created and no
  status can be asked for.

  To record a receipt for review rather than book it, use `upload_file`: it
  files the document as an unchecked purchase invoice, which still works.

### Changed

- **`create_voucher` requires `voucher_number`.** The API refuses a voucher
  without one, for all four types, with `voucherNumber: missing_entity`. It
  was optional, so a call that omitted it spent an API request to be told no.
  Requiring it in the schema means the caller finds out before anything is
  sent.

- **The package now says Beta rather than Alpha** on the package index. What
  it claims is that the surface has stopped moving: twenty-five tools built
  and each exercised against a live account, two transports, a container
  image, and every release so far additive or a correction. It is not a claim
  that this is an official Lexware product, which it is not, or that a
  release cannot break something.

### Fixed

- **`--env-file` now reads that file and no other.** Its help has always said
  "instead of looking for one", and it did not: the named file was read
  *after* every file the search found, so a setting missing from it was still
  supplied by whatever else happened to be on the machine. Pointing at a file
  is now what it appears to be.

  The search behind it follows the same rule: the highest-precedence `.env`
  that exists is the file, and the ones below it are not read. That half was
  deliberate before and is a decision rather than a defect - one rule for both
  configuration files, since `--tools-file` and the policy search never
  combined anything either.

  A real environment variable still beats whatever the file says, so a
  container can pass its transport settings while the key lives in the mounted
  file.

  **This can change what your server reads.** If a setting of yours lives in a
  lower-precedence file - a per-user `.env` under a checkout that has its own,
  or anything alongside `--env-file` - it no longer applies. Put every setting
  you need into the one file that wins. The configuration interface names that
  file on the overview, and now says so explicitly when it is editing a `.env`
  that a server would not read.

## [0.2.1] - 2026-08-23

### Changed

- **The container image runs Python 3.14** instead of 3.13, which is the
  newest version this package supports and is tested against. It reaches the
  image only — an installation from the package index uses whatever Python it
  is installed into, unchanged at 3.11 or newer.
- **Locked dependencies refreshed** — one patch release, `ruff` 0.16.3 to
  0.16.4. It reaches the development environment and CI only: the declared
  ranges in `pyproject.toml` are unchanged, so an installation from the
  package index resolves exactly as before, and the container image installs
  without the development extra.

## [0.2.0] - 2026-08-22

### Added

- **Every tool now carries the MCP annotations**, so a client can tell a
  reading tool from a writing one without parsing prose: `readOnlyHint` on
  every read tool, `destructiveHint` false for a create and true for an update
  or a delete, `idempotentHint` saying that a second create is a second record
  while a repeated update or delete is not, and `openWorldHint` false on the
  two tools that answer without reaching the API. They are derived from the
  same classification the policy file is written against, and they decide
  nothing: the file remains the only gate.
- **An HTTP transport**, `--transport streamable-http` or `sse`, beside the
  stdio one that stays the default. `--host`, `--port`, `--path` and
  `--allowed-hosts` configure it, or `LXO_MCP_TRANSPORT`, `LXO_MCP_HTTP_HOST`,
  `LXO_MCP_HTTP_PORT`, `LXO_MCP_HTTP_PATH` and `LXO_MCP_ALLOWED_HOSTS`.
- **A bearer token in front of it, which is not optional.** Every HTTP request
  must carry `Authorization: Bearer <token>` from `LXO_MCP_BEARER_TOKEN`, and
  without one the server refuses to start an HTTP transport at all. stdio is
  untouched: there the client owns the process and nothing else can reach it.
  The SDK's DNS-rebinding guard checks `Host` and `Origin` on top, with the
  loopback names always allowed and `--allowed-hosts` adding a container or a
  proxy name.
- **A container image and a Compose file.** `docker compose up -d` serves the
  streamable-HTTP transport on `127.0.0.1:8770`, with the `.env`, the policy
  file and the saved profiles in a `config` volume and downloads in another.
  The image binds `0.0.0.0` because a process on the container's own loopback
  cannot be reached through a published port at all — who may reach it is
  decided by the host-side publish.
- **The configuration interface as a second container, behind a profile.**
  `docker compose --profile setup up -d` puts it on `127.0.0.1:8771` against
  the same volume, and a plain `up` leaves it out. It has no login and it
  takes an API key, so it is meant to be started for the minutes it is needed
  and stopped again.
- **`LXO_MCP_EXIT_ON_CONFIG_CHANGE`**, which ends the process when the
  settings file changes so that whatever started it starts it again. Settings
  are read once, at startup, and this is what lets a key saved in the browser
  reach a running server without anyone opening a terminal. Off unless asked
  for, since ending is the whole of it where nothing restarts it. The image
  switches it on.
- **The HTTP token is generated and managed where it is used.** A server
  told to (`LXO_MCP_GENERATE_BEARER_TOKEN`, which the image sets) makes one
  on first start — thirty-two random bytes into the settings file — so a
  container needs no secret typed before it runs, and none is baked into the
  image where every copy would share it. The configuration interface shows
  it, saves a typed one and generates a fresh one on request. It refuses an
  empty one: blank means unchanged for the API key, whose field is blank by
  design, but the token field shows what is in force, so blank there could
  only mean a server that stops serving.
- **The package declares its types** (PEP 561). Code that imports this
  package now gets its annotations checked instead of skipped - a type
  checker ignores every annotation in an installed package that carries no
  `py.typed` marker, however completely it is annotated.
- **The image is published**, so a container no longer means cloning this
  repository and building one. A release pushes
  `ghcr.io/benethos-hub/lexware-office-mcp` for `linux/amd64` and
  `linux/arm64`, tagged with the version, the major.minor line and `latest`.
  `compose.yaml` carries the two commented lines that switch it from building
  to pulling, and that file is then all you need from here.
- **`setup` can bind an address other than loopback**, with `--host`. A
  container has to: a process on the container's own loopback cannot be
  reached through a published port. It says on stderr when it binds anything
  else, because the pages still have no login.

### Changed

- **The server's instructions** now say what holds across tools rather than
  only how to find an id: that a tool without `readOnlyHint` changes real
  books, that `get_profile` names the company before the first write of a
  session, that a create cannot be repeated safely, and that every call spends
  from one budget shared by all endpoints. They are sent once per session
  rather than with every request, which is what makes the room affordable.

## [0.1.0] - 2026-08-22

The first release. Everything below is what it contains.

### Added

- **`get_profile`** — the first tool. Shows which Lexware Office account the
  server is connected to: organization, company name, tax setup, small-business
  status and the enabled business features. Doubles as the connection check,
  and costs one API call. The email address of the user who created the
  account, which the API returns alongside, is dropped rather than handed on.
- **`search_contacts`** — find customers and vendors by part of their name,
  part of an email address, their customer or vendor number, or their role.
  Returns one page of short rows with the contact id, name, customer and vendor
  numbers and one way to get in touch, plus the page information needed to ask
  for the next page. `page` and `size` are the caller's to set, and one call
  fetches one page: walking every page would spend a rate limit that covers the
  whole account. Costs one API call.
- **`get_contact`** — one contact in full by id, including billing and shipping
  addresses, all email addresses and phone numbers, the roles with their
  numbers and the `version` an update will have to send back. Costs one API
  call.
- **`create_contact`** — create a customer or vendor. Takes the name, the
  roles, and optionally an email address, a phone number, a billing and a
  shipping address, tax details and a note. Returns the new id and version.
  The customer and vendor numbers are assigned by Lexware, so read the contact
  back if you need them. Costs one API call
  that is never retried: a repeated create is a second contact nobody asked
  for.
- **`update_contact`** — change an existing contact. Only the fields you name
  are changed, everything else stays as it was. This costs two API calls
  rather than one, because the API replaces a record instead of patching it,
  so the current contact is read first and the change is laid on top. Without
  that, an update naming only a new email address would empty out the
  addresses, the note and everything else. It needs the `version` from your
  last read, and if the record changed in between the update is refused before
  anything is sent. Enable it in `tools.json` first.
- **`search_vouchers`** — the way into the books. Filter invoices, credit
  notes, quotations, delivery notes and bookkeeping vouchers by type, status,
  contact, date range, and by whether anything is still open or overdue.
  Returns short rows with the id, number, dates, contact, total and open
  amount. Costs one API call per page. This is the only way to find a document
  at all, so any question about what a customer owes starts here.
- **`get_voucher`** — one bookkeeping voucher in full, with its lines, posting
  categories, tax type and `version`. Takes either the Lexware id or the
  number printed on the document, because the voucher list cannot search by
  number. A number matching several vouchers is reported with their ids rather
  than guessed at. Costs one API call.
- **`get_payments`** — whether a voucher has been paid, what is still
  outstanding, and the individual payments recorded against it. An open amount
  of 0 is reported rather than dropped, because it is the answer. Costs one
  API call. Vouchers that have not been booked yet have no payment
  information, and the API says so rather than returning zeros.
- **`create_voucher`** — record a bookkeeping voucher. Takes the type, date,
  tax type and lines, each line naming the posting category it books to. The
  totals are added up from the lines unless you state them. Pass `unchecked`
  to record an entry that still needs review instead of booking it straight
  away. Costs one API call that is never retried, and **the API cannot take
  it back**: there is no call here that deletes a voucher, so correcting one
  is a job for the web app.
- **`update_voucher`** — change a recorded voucher. As with `update_contact`,
  only the fields you name change and the rest is carried over, at the cost of
  a second API call. Enable it in `tools.json` first.
- **`download_file`** — save a stored file, such as an uploaded receipt, to
  the download directory on the machine the server runs on. Reports it two
  ways: the **path** it was written to, which is what you want when the client
  shares that machine, and a **resource URI**, which the client can read to
  get the bytes wherever the server is. The file itself never travels inside
  the tool result — base64 costs roughly 1.37 times the file size in context,
  is spent whether or not anyone wanted the file, and no model can read a PDF
  anyway. An existing file is never replaced: a second download of the same
  document is saved beside the first with a counter in its name. Costs one API
  call.
- **A link into the web app is `get_deeplink`'s job alone.** A download
  reports where the bytes are and nothing else. The link is one tool call
  away, costs no API call, and is the route that works when a client can
  display neither the file itself nor a resource link: hand it to a person and
  they open it in a browser.
- **Downloaded files are offered as MCP resources.** Every download this
  server performs is registered under a `lexware://download/...` URI and
  appears in the resource list, so a client that does not share a filesystem
  with the server can still fetch the bytes. Registered per file, so each
  carries its own content type and only what was actually downloaded is
  reachable.
- **A download URI keeps working after the server restarts.** The resource
  list is filled from the download directory as the server starts, so a URI
  from an earlier session still resolves. Previously only the running process
  knew about its own downloads, and every other URI answered "Unknown
  resource" even with the file sitting on disk. Note that a download made
  *during* a session still cannot be announced: the server has no way to tell
  a client its resource list changed, which is what `read_download` is for.
- **The same file is never downloaded twice into two copies.** Saving still
  refuses to overwrite a file whose contents differ, but a file whose contents
  are identical is reused instead of being written again beside the first.
- **A download link survives a restart of the server.** `read_download`
  resolves the file from the download directory rather than from a registry
  that only lives as long as the process, so a URI handed out earlier keeps
  working.
- **`read_download`** — put a downloaded file into the answer, for clients
  that do not follow resource links. Claude Desktop is one of them, so this is
  the route that always works. What comes back depends on the file: **XML
  arrives as text**, which makes an XRechnung readable and its amounts usable,
  **a PDF arrives as pictures of its pages** since no client will display an
  embedded PDF, images arrive as images, and anything else as an embedded
  binary for the client to handle. A PDF is rendered to its first ten
  pages by default, which `max_pages` raises, lowers, or lifts entirely by
  being set to null. The answer reports how many pages the document has beside
  how many were rendered, so a limited read never looks complete.
- **`LXO_MCP_PDF_PAGES`** sets that default for an installation, for a machine
  on a tighter context budget. It is named apart from `LXO_MCP_PAGE_SIZE` on
  purpose: that one counts rows of a search result, this one counts sheets of
  a document. The value in force is reported in the tool's schema and in its
  description, so a client never plans around a number that is not the one
  applied.
- **New dependency: `pypdfium2`**, which renders those pages. PDFium under
  BSD-3-Clause and Apache-2.0, a 3.7 MiB wheel. The better known PyMuPDF is
  AGPL-3.0 or a commercial licence, which this MIT project cannot take. Costs **no** API call, since the file is already on the
  server. Only files this server downloaded can be read, and nothing above
  5 MiB, because base64 of a large file would swallow the answer.
- **`get_sales_document`** — read an invoice, quotation, credit note, order
  confirmation, delivery note, dunning or down payment invoice in full: who it
  is addressed to, every line with its unit price and discount, the totals,
  the tax breakdown, the payment and shipping conditions, and the `version`.
  Costs one API call. The type is part of the address rather than a filter, so
  it has to match the id — a mismatch answers "not found", exactly as a wrong
  id does. Take it from the `voucherType` that `search_vouchers` reported. A
  draft reads in full even though it cannot be downloaded, and says so by
  carrying no `files.documentFileId`.
- **`search_articles` now says the page floor in its schema.** That endpoint
  refuses a page size below 25 with `size: MIN`, alone among the lists, and
  the parameter had allowed 1 — so a small page failed upstream instead of
  being caught here. The minimum is now 25.
- **`create_sales_document`** — write an invoice, quotation, credit note,
  order confirmation, delivery note or dunning. A down payment invoice cannot
  be created through the API at all, so it is not offered. Costs one API call
  that is never retried. Line items carry the price on the side the
  document's tax type names, may quote an article by id, and a `text` line
  carries no price. The totals are left to the API, which adds the document
  up from its lines. It writes a **draft** unless `finalize` is set, and the
  tool tells the assistant to set that **only when you asked for the document
  to be issued** — never on its own initiative. Finalizing assigns the
  consecutive number, and the API cannot take that back.
- **`preceding_sales_voucher_id` follows an existing document** along the
  quotation to invoice chain, and a dunning needs one.
- **What each kind needs is checked before a request is spent**, and the
  message names the field: `shipping_date` for an invoice, order
  confirmation and delivery note, `expiration_date` for a quotation,
  `preceding_sales_voucher_id` for a dunning.
- **A date is given as YYYY-MM-DD**, as everywhere else in this server. These
  endpoints demand a full timestamp with milliseconds and an offset, unlike
  the voucher endpoint, and the conversion happens here.
- **`attach_file_to_voucher`** — hang a scan on a voucher that is already
  there. `upload_file` cannot do this: it creates a **new** voucher for every
  file, and a voucher cannot be deleted through the API, so picking the wrong
  one of the two leaves a voucher behind that the API cannot remove. Same four file types and
  the same 5 MiB ceiling, checked before a request is spent. The answer is
  the new file id, which `download_file` reads back. Costs one API call that
  is never retried, and an attachment cannot be removed either.
- **`get_recurring_templates`** — read the templates that issue invoices on a
  schedule. A row is shorter than the record behind it, so what a template
  will actually invoice is only visible when you read it by id. Costs one API call. With a `template_id` it answers with that one
  template, without one with a page of them, because the endpoint offers
  nothing to search by and two tools would have cost two descriptions for the
  same call. `sort` takes the four dates the API accepts. Reading is all
  there is: a template cannot be created, changed or run through the API.
- **The article catalogue, all five tools.** `search_articles` lists them,
  `get_article` reads one in full, `create_article` adds one,
  `update_article` changes one, and `delete_article` removes one — the API
  cannot bring it back.
- **`search_articles` has no search by title**, deliberately. The endpoint
  filters on article number, barcode and kind, matches both strings in full,
  and **ignores** any other parameter instead of refusing it — so a `query`
  parameter would have answered with the whole catalogue while looking like
  it had searched. Finding an article by name means paging the list.
- **A price is one number and a side.** `create_article` and `update_article`
  take the price with `leading_price` saying whether it is net or gross, and
  the API computes the other figure. An update replaces the side you name and
  drops the other, so a new net price is never sent beside a stale gross one.
  `update_article` costs two API calls and needs the `version`, like the
  other updates.
- **`delete_article` is the first tool that destroys a record.** It takes
  `confirm: true` and sends nothing without it, and the article is removed
  rather than archived — the API cannot bring it back. It is the only member
  of the `--tools irreversible` step, and the only thing this API can delete
  at all.
- **`--tools sync`** — complete the policy file without deciding anything.
  Every tool the file does not mention is added as `false`, every flag already
  there is written back unchanged, and **nothing is ever switched on**. That
  is what a preset cannot do: presets overwrite, so hand edits are lost, which
  is right for starting a file and wrong for keeping one after an upgrade
  brings tools it has never heard of. A name in the file that matches no tool
  is reported and dropped, since it had no effect either way. Safe to run
  unattended, unlike everything else under `--tools`.
- **A refused request now names the fields it refused.** The API answers a
  bad body with a `details` list of field and violation, a different shape
  from the `IssueList` it uses elsewhere, and only the second one was read.
  A refusal that said "validation failed, please see details list" and then
  showed no details now reads `price: NOTNULL type: NOTNULL unitName:
  NOTEMPTY`. A stale `version` reported in that shape is recognized as a
  conflict too.
- **`get_master_data`** — read one of the four lists an account is configured
  with: countries, payment conditions, posting categories or print layouts.
  Costs one API call. Two of them are long — a live account holds 257
  countries and 231 posting categories, and none of these endpoints pages, so
  the whole list arrives however little of it was wanted. `search` narrows it,
  matching every text a row carries except its id, so one term filters by
  name, by group, by country code or by category type. `limit` caps what comes
  back at 25 rows by default, and the answer reports `total` beside `shown`,
  so a trimmed list never looks complete. A posting category id is what
  `create_voucher` books against.
- **`download_document`** — the same for the rendered PDF of an invoice,
  quotation, credit note, order confirmation, delivery note, dunning or down
  payment invoice. `xml` is available for an XRechnung. A document still in
  draft has not been rendered and has nothing to download. Costs one API call.
- **`get_deeplink`** — a link that opens a record in the Lexware Office web
  app, for sales documents, contacts and vouchers. Costs **no** API call,
  since the link is built from ids you already have. A contact opens on its
  one page whichever action is asked for.
- **`upload_file`** — upload a receipt from a path on the machine the server
  runs on. This does more than store a file: the API also creates the
  bookkeeping voucher that goes with it, and that voucher cannot be deleted
  afterwards. PDF, JPEG, PNG and XML up to 5 MiB are accepted, which is
  what the API takes, and an XML file is treated as an XRechnung and rejected
  if it is not one. A file that is missing, too large or of any other type is
  rejected before a request is spent on it. Costs one API call that is
  never retried.
- **`LXO_MCP_DOWNLOAD_DIR` and `LXO_MCP_APP_BASE_URL` now do something.** Both
  were read and validated before but no tool consumed them. Downloads go to
  the download directory, deeplinks are built against the app base URL.
- **The same page shape for every list.** A search result is
  `{records: [...], "page": {number, size, totalElements, totalPages, last}}`,
  so paging works the same way across tools as they are added. The API's
  ordering block is dropped: it repeats on every response and says nothing a
  caller can act on.
- **The server itself** — installable as `benethos-lexware-office-mcp`, started
  through the console script of the same name or
  `python -m benethos_lexware_office_mcp`. Speaks **stdio**, which is what
  Claude Desktop and comparable local clients use. `--log-level` and `--version` on the
  command line, plus `--tools` and `--tools-file` to write and inspect the
  policy file instead of serving.
- **Nothing is enabled by default.** Which tools this server offers is one
  flag per tool in `tools.json`, and a tool the file does not name is off — so
  an installation without the file offers nothing at all, and what a server
  may do is always something somebody decided. Enforced twice: a disabled tool
  is never registered, so it does not appear in the tool list, and the file is
  checked again when a call arrives, so a client holding a stale list cannot
  get one through. Each tool also declares what it is (reading or writing, and
  its group), which is what `--tools read-only` selects on. That
  classification never decides a call.
- **`--env-file PATH`** names the `.env` to read instead of searching for
  one, and is refused rather than ignored when the path does not exist.
  Together with `--tools-file` it lets one entry in a client's configuration
  carry its own account and its own permissions. A real environment variable
  still wins over the named file, which is what lets a client override a
  single value without editing anything.
- **Configuration** from a real environment variable, a `.env` in the working
  directory, `config/.env` in the working directory, `config/.env` of the clone
  the server runs from, or a `.env` in the per-user config directory, in that
  order of precedence. The fourth rule means a clone configures itself no
  matter which directory it is started from, which is what a client such as
  Claude Desktop needs. Settings: `LXO_MCP_API_KEY`, `LXO_MCP_TOOL_POLICY`,
  `LXO_MCP_BASE_URL`, `LXO_MCP_APP_BASE_URL`, `LXO_MCP_DOWNLOAD_DIR`,
  `LXO_MCP_TIMEOUT`, `LXO_MCP_RATE`, `LXO_MCP_BURST`, `LXO_MCP_PAGE_SIZE` and
  `LXO_MCP_LOG_LEVEL`. Values are validated when they are read, so a page size
  the API would refuse fails at startup rather than mid-conversation.
- **A settings sample that ships with the package** — a commented list of
  every setting with its default and the reasoning behind it. It is installed
  with the code rather than left beside it, so a copy from PyPI documents its
  own settings, and **`--settings-sample`** prints it:
  `benethos-lexware-office-mcp --settings-sample > config/.env`. The copy is
  gitignored, the sample holds no key.
- **Rate limiting that matches the account, not the endpoint.** The Lexware
  limit of two requests per second covers the whole API at once, so the server
  keeps a single token bucket that every request passes, retries included. It
  refills slightly below the documented rate by default, because the API
  documentation warns that aiming exactly at the limit still produces 429s once
  network jitter shifts the timing. Repeated rate limiting holds the bucket
  shut for a cool-down instead of hammering a limit that can block a key
  permanently.
- **Retries that cannot duplicate a document.** A failed `POST` is never
  repeated: a 5xx or a timeout does not say whether the invoice was created,
  and a duplicate with a consecutive number is not something the caller can
  undo. It is reported with its outcome marked unknown instead. A 429 is safe
  to repeat for any method, because the documentation states the call was not
  performed.
- **Errors written for the caller**, not stack traces: the key was rejected,
  the record changed since it was read, the resource does not exist. When the
  API refuses a parameter it sometimes sends no message at all, only a list of
  issues naming the field and what was wrong with it, so that list is folded
  into the message rather than dropped. An update rejected because somebody
  else changed the record first is reported as a conflict telling you to read
  it again, rather than as a validation error telling you to fix input that
  was never wrong. A not-found names the path that was asked for instead of
  guessing a record id out of it. The API key is redacted from every
  message, and monetary values are passed through exactly as the API reported
  them, always with their currency.
- **A refusal that is not about a version no longer claims to be.** Asking
  for the PDF of a sales document that is still a draft is refused with a
  conflict, and the message used to tell you to read the record again for a
  fresher version — advice for a problem you did not have. It now states what
  the API said: the document is a draft and has not been rendered. A genuine
  stale-version conflict still says so.
- **Which tools exist is one flag per tool, in `tools.json`.** A tool set to
  `false` is neither listed nor callable, and so is a tool the file does not
  mention — silence is a refusal, so a tool arriving with an upgrade waits to
  be enabled rather than appearing on its own. Without the file the server
  offers nothing at all.
- **Writing that file:** `--tools read-only` enables the reading tools,
  `--tools write` adds creating and changing, `--tools irreversible` adds
  deleting, `--tools sync` writes in tools an upgrade brought without
  switching any of them on, and `--tools show` only reports. **`write` does
  not mean undoable**: nothing in it deletes a record, but `create_voucher`,
  `upload_file`, `attach_file_to_voucher` and `create_sales_document` all
  leave records the API cannot remove afterwards.
  `--tools-file` says which file, and works with every preset. A preset
  overwrites, so it starts a file rather than updating one, and a target that
  is a directory or cannot be written is refused with a message rather than a
  traceback.
- **An edit takes effect in both directions without a restart.** The file is
  read as the tool list is built and again on every call, so a tool switched
  on is offered from the next listing and one switched off stops being
  offered.
- **And the client is told, so it can fetch the list again by itself.** The
  server announces `tools.listChanged` and sends
  `notifications/tools/list_changed` when the set of enabled tools actually
  changes — not when the file is merely rewritten, which the configuration
  interface does on every save. Claude Desktop picks the change up without
  being restarted, checked against the running client. Nothing depends on it
  either way: a tool that has been switched off cannot be called whatever
  list is still on screen.
- **Where that file lives:** found the same way the `.env` is — per-user
  configuration directory, then `config/` of a checkout, then the working
  directory, last one found winning — so a `config/tools.json` in a clone
  overrides an installed one. `LXO_MCP_TOOL_POLICY` overrides the search and
  `--tools-file` overrides both.
- **A configuration interface in the browser.**
  `benethos-lexware-office-mcp setup` serves three pages on `127.0.0.1` and
  opens a browser: an overview of which files are in effect and where every
  setting actually comes from, a page for the API key and the settings, and
  one checkbox per tool. It writes the same `.env` and `tools.json` the command line does, so the
  two are interchangeable. It is a separate command and never part of the MCP
  server, which speaks stdio. Loopback only, with no option to bind anything
  else, and every state-changing request is guarded against being triggered
  from another page. German throughout, since Lexware Office is sold for
  German companies only. `--port` and `--no-browser` belong to it, and unlike
  everywhere else `--env-file` may name a file that does not exist yet.
- **A fresh installation opens on a proposal rather than on a blank form.**
  With no policy file yet, the permissions page comes with the reading tools
  ticked and says plainly that nothing is active until you save. No file
  still means no tools, exactly as before — what changed is the starting
  point of the form, not what the server offers.
- **Both processes fix their files at startup and say which.** The server
  and the interface each resolve the `.env` and the policy file once, when
  they start, and hold them — the contents still take effect without a
  restart, only the identity of the file is fixed. Deleting it disables
  everything rather than falling back to another file somewhere. Since
  neither process can see how the other was started, the overview prints the
  `"args"` entry that makes your client use the same files, and says that
  giving `setup` the same arguments does the job too.
- **What a tool costs the assistant is shown next to it.** Every enabled tool
  is sent to the model on every single request, so the permissions page puts
  the character count on each row and totals it live as boxes are ticked. The
  overview repeats the total for what is currently on.
- **Destruction and permanence are marked as two different things.**
  `delete_article` destroys a record and is the one tool that can, while
  `create_contact`, `create_voucher`, `create_sales_document`, `upload_file`
  and `attach_file_to_voucher` leave records the API cannot take back. Those
  carry a mark of their own — `nur App` for a record only the web app
  deletes, `nur App · Buchhaltung` for one that enters the books — and a
  legend above the list says what each mark means. Neither claims a record is
  gone forever or bound from the start: nothing is festgeschrieben when it is
  created, and the web app deletes it unless it is festgeschrieben, has a
  payment assigned, has follow-on documents, or has been exported.
- **Permission profiles.** A named selection can be saved, loaded and
  deleted, so that "nur lesend für den Steuerberater" and "voller Zugriff auf
  dem Testkonto" are one click apart. A profile is a convenience and never a
  second policy: loading one fills in the checkboxes, and nothing reaches
  `tools.json` until save is pressed. Profiles live in `tool_profiles.json`
  beside the policy file they belong to. Creating one under a name that is
  already taken is refused — case and spacing do not make a second profile —
  and replacing one is its own button beside the list. The profile block and
  the import and export block are both folded away by default, so the tool
  list stays the page, and a block unfolds itself when it has something to
  answer.
- **A policy file can be downloaded and read back in.** The download is
  `tools.json` as it stands, with no wrapper around it, so it works on
  another installation with or without this interface — and a file written
  by `--tools` reads here. Reading one only ticks the boxes: saving is still
  a separate press. A tool the file does not mention stays **off** and the
  page says how many those are, which is what `--tools sync` does on the
  command line. Nothing else travels: not the settings, not the profiles,
  and not the API key.
- **The API key can be entered without a text editor**, checked against the
  API before it is written, and never displayed, logged or exported. The
  interface says which file it writes to, creating it and its directory if
  needed, and warns when a real environment variable is set that would
  override whatever gets saved.
- **No message hands the client a path from the server's machine.** A refusal
  used to read "Set it to true in <the full path of the file>" and a missing
  key named the directory the `.env` would go in. Both reach a model's
  context, both carry a user name and a directory layout, and neither is
  something the caller can act on. They now name the tool and the setting,
  and leave the file to stderr and the configuration interface, which is
  where somebody can actually change it. A download still answers with the
  path it wrote to, since that is what the call was for.
- **The setup instructions no longer put the API key in your client's
  configuration.** They showed it in an `env` block, which works and is the
  worse of the two places: that file belongs to another program, is readable
  in the client's own settings view, travels to the next machine with the
  rest of that configuration, and is the one people paste into a forum when
  something will not start. The key belongs in the `.env`, which the
  configuration interface writes without ever showing it back to you.
- `README.md` and `LICENSE` (MIT).

### Not yet

Every documented endpoint this API offers is covered except event
subscriptions — see the roadmap in [SPECS.md](SPECS.md) section 16, along with
the questions still open against the live API. The HTTP transport is planned
for 0.2.0 and will ship with its own authentication in front of the API key.

[Unreleased]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.2.4...v0.3.0
[0.2.4]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/benethos-hub/lexware-office-mcp/releases/tag/v0.1.0
