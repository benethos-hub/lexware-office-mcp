# Concept: errors and output

Part of the [concept](../CONCEPT.md): sections 12 to 13.

## 12. Error handling

| Upstream | Error class | Message shape |
|---|---|---|
| 400, 406 | `ValidationError` | the API `errorCode` and `message`, plus the offending field path when the response names one |
| 401 | `AuthError` | "API key rejected", with a pointer to the add-on page and the note that a changed key needs the client to start the server again, never the key |
| 403 | `AuthError` | the method and path the key may not use, and to check the permissions it was created with |
| 404 | `NotFoundError` | the path that answered nothing - a 404 does not say which part of it was wrong. A tool that looked a record up itself names the resource and the ID or number instead |
| 406 naming `version`, 409 | `ConflictError` | a stale version (406) says to read the record again. A 409 says the record's current state refused the request, without naming a version. The one message that names both versions is the local check before an update, which compares the version read with the version passed |
| 429 | `RateLimitError` | after retries are exhausted, to try again shortly. When the breaker trips it says how long it pauses, and when `Retry-After` asks for longer than a call waits it says that wait |
| 3xx | `UpstreamError` | the status, and that it came instead of a result. The client follows no redirect and the API documents none, so a redirect's body is never taken for a document. On a write the outcome is unknown |
| 5xx, network | `UpstreamError` | short, no traceback. On a POST, on a PUT or DELETE that ran out of retries, and on any write whose 2xx answer cannot be read, it says the outcome is unknown |
| — (local disk) | `LocalFileError` | a download or upload the machine refused: the operating system's reason, never a path |
| — (upload URL) | `ValidationError`, `UpstreamError` | a URL no prefix of `LXO_MCP_UPLOAD_URLS` covers, or none allowed at all, and that nothing was requested. A file too large, of a type the API does not take, or named as another type, as for a file on disk. A status other than 200, a redirect among them, by its number and never with the page that came with it, a fetch past 30 seconds, no connection - each by the host alone, and that nothing was sent to Lexware |
| — (policy) | `PermissionDeniedError` | a tool the policy file does not enable, called by a client whose tool list predates the change. Refused before its arguments are checked, since the SDK's refusal of invalid ones names the fields the tool requires and quotes what was sent |
| — (arguments) | `ToolError` | an argument the tool does not take, by its name when it looks like one and as `?` otherwise, and that nothing was sent. The SDK builds each argument model to drop what it does not know, so such a call ran without the filter and answered as if it had, which is how `only_open` hid paid vouchers (issue #95). Refused only for a tool the policy allows, so a withheld one says nothing about its schema |
| — (settings) | `ConfigError` | no API key, said with the command that sets one, over stdio the prompt that opens it as well unless `LXO_MCP_SETUP_PROMPT` withholds it, and that a key saved there is used from the next call - never with a path, also when the file a key is saved to cannot be decoded, which stderr names instead. At startup the same class ends the process in one line |

**Two lists of issues are in use upstream, and they share no field names.**
`IssueList` carries `source` and `i18nKey`, which is what a rejected query
parameter or a stale version comes back as. `details` carries `field` and
`violation`, which is what a refused request body comes back as - measured
2026-08-21 against `POST /v1/articles`, where a missing `price` answers 406
with `{"violation": "NOTNULL", "field": "price"}` and a message that reads
"please see details list for specific causes". Reading only the first shape
therefore handed the caller a pointer to a list they were not given. Both are
read, and the localized German sentence beside each violation is left out
because it says no more than the violation name does.

**A field that was left out is not a field with a bad value.** The
stale-version answer keys off the field an issue names, and a request that
sends no `version` at all names the same field. Violations that mean "absent"
- `NOTNULL`, `NOTEMPTY`, `NOTBLANK` - are therefore left out of that signal,
so a caller who forgot a field is told to send it rather than to re-read a
record that was never the problem. Measured 2026-08-21 on `PUT /v1/articles`.
The `IssueList` shape says the same thing in `i18nKey` as `missing_entity`,
and is read the same way.

**Which status a stale version arrives as depends on the resource.** A
contact answers 406 naming `version`, an article answers **409**. Both end as
`ConflictError`, which is why the mapping reads the body rather than the
status alone.

No raw traceback ever reaches the client. Expected failures are `ToolError`
subclasses with concise, actionable messages.

**The message is for the model, and the log never prints it.** It quotes what
the model sent - a path, a number that did not match - and that is exactly what
[section 11.2](../LOGGING.md) keeps out of a line. So a `ToolError` also
carries `status` and `code`: the HTTP status the API answered with, and the
API's own codes for what it refused, which `from_response` sets and the client
sets for a 5xx or a 429. A line names the class and those two, then what the
call cost, as in `update_voucher refused: ConflictError 406 version:
invalid_value, after 1 API call, 230 ms`.

**What a crash sends depended on the SDK version.** A traceback never
travels on either, but on 2.0.0 an unanticipated exception's own message
does, and from 2.1 it does not. That alone was not reason enough to raise
the floor: the difference is a message this server never composed, in a
path it does not expect to reach. The floor moved to 2.2.0 on 2026-10-19
for a different reason, GHSA-84m7-p3x7-pcfv: before 2.2.0 a stateful
Streamable HTTP server never reclaimed its sessions, and this server
serves that transport in stateful mode. The 2.0.0 behaviour is no longer
installable.

### 12.1 Why `ToolError` derives from the SDK's

The SDK sorts a failing tool call by the **type** of what was raised. Its own
`ToolError` means a failure the server anticipated: the message is handed to
the model and logged at INFO without a traceback. Anything else is a crash,
and from mcp 2.1.0 onward the text stays on the server while the model is told
only `Error executing tool <name>`. So the hierarchy above derives from
`mcp.server.mcpserver.exceptions.ToolError`, and without that inheritance
every sentence in the table would be written and none of them delivered.

The `ValueError` raised for an unknown preset sits on the other side of
that line deliberately. It is a mistake in how the process was invoked, not
an answer for the model, and withholding its text is right. A rate of zero
used to be the second example and is not any more: the settings refuse it
with a `ConfigError` before a bucket is built, and the process ends in one
line.

Measured 2026-09-02 over real stdio against mcp 2.1.1, upgrading from 2.0.0.
The same denial arrived as:

```
2.0.0  Error executing tool get_profile: get_profile is not enabled for this
       installation. The account owner decides that in the server's tool policy.
2.1.1  Error executing tool get_profile
```

**What the gates did and did not catch.** Twenty-one tests failed on the bump,
because they assert on the message text of what `MCPServer.call_tool` raises,
and that call re-raises through the same sorting. The suite is not blind here.
What it cannot see is anything further out: `call_tool` raises, while a client
is answered by `_handle_call_tool`, which converts. A change to that conversion
- the wire shape, the tool list, the annotations - passes every test in this
repository. [Section 14.3](testing.md#143-the-sdk-is-the-second-blind-spot)
says how to look.

## 13. Output format

- Compact JSON, small by construction. A search tool returns exactly one
  upstream page of `LXO_MCP_PAGE_SIZE` rows and always carries the page
  metadata, so a caller knows something was left behind and can ask for the
  next page.
- **There is one page size, not two.** The value is sent upstream as the `size`
  parameter and is also what the caller receives, so the token budget is
  controlled by asking the API for less rather than by fetching a full page and
  trimming it afterwards. A second, client-side row cap would waste a request
  on rows it then discards, and would hide from the caller that the API had
  more to give. The default of `25` matches the documented typical page size,
  and open question 1 is what would let it be raised per endpoint with
  evidence.
- **Every paged list has the same shape**, `{<records>: [...], "page": {...}}`,
  where `page` carries `number`, `size`, `totalElements`, `totalPages` and
  `last`. A caller that has learned to page through one list can page through
  all of them, and only the row formatter differs per resource. Of the nine
  fields the API's envelope carries, `first` restates `number == 0`,
  `numberOfElements` restates the row count, and `sort` describes the ordering
  with five fields per sort key and is identical on every response, so all
  three are dropped.
- **A downloaded file is named, not embedded.** The bytes never go into a tool
  result. Base64 costs roughly 1.37 times the file size in the client's context
  window, is spent whether or not anybody wanted the file, and a model cannot
  read a PDF anyway. Instead each download is reported twice: a `path`, which
  is what a client sharing the machine with the server wants, and a `uri` under
  which the client can read the bytes on demand. Both name the same file.
- **A PDF cannot be delivered to Claude Desktop at all, in any encoding.**
  Measured on 2026-08-20 by reading the raw JSON-RPC off a real subprocess:
  the server sends `type: "resource"` with `mimeType: application/pdf` and a
  blob, which is what the specification prescribes and contains no image block
  of any kind. Claude Desktop nevertheless maps a binary embedded resource
  onto an **image** block when it builds its own API request, and that request
  is then refused with
  `ClaudeAiToolResultRequest.content.0.image.source.media_type: Input is not
  one of the permitted values` — the permitted ones being `image/jpeg`,
  `image/png`, `image/gif` and `image/webp`. A PNG goes through the same path
  without trouble, so the obstacle is the media type and not the route. Two
  things follow: re-encoding the same bytes cannot help, and the only way to
  put a PDF in front of that client is to turn it into something else, namely
  its extracted text or its pages rendered as images.
- **So a PDF is delivered as pictures of its pages.** `read_download` renders
  them rather than handing over bytes no client will show, and **the rendered
  pages were confirmed to arrive in Claude Desktop on 2026-08-20**: the client
  that refuses the blob displays these. The decisions behind them were
  measured the same day against a two-page A4 invoice:
  - **`pypdfium2`, not PyMuPDF.** PyMuPDF is faster and better known, and it
    is AGPL-3.0 or a commercial licence from Artifex, which an MIT project
    cannot take. `pypdfium2` binds the same PDFium that Chrome uses, under
    BSD-3-Clause and Apache-2.0, in a 3.7 MiB wheel. It is the project's first
    runtime dependency beyond the MCP SDK, httpx and platformdirs.
  - **PNG, encoded here rather than by an imaging library.** Writing a PNG
    from raw pixels is zlib and four chunks. Pillow would be a second
    dependency to save fifteen lines, and the adaptive filtering it brings
    measured *larger* on rendered pages, where rows are mostly white and a
    per-row filter only adds entropy at glyph edges: 48.9 KiB unfiltered
    against 57.3 KiB with PNG's Up filter.
  - **1400 px on the long edge**, which puts an A4 page at 990x1400. Claude
    resizes anything past roughly 1568 px before looking at it, so rendering
    larger spends bytes on pixels that are then discarded.
  - **Colour, not grayscale.** Grayscale is a third of the bytes (17.3 KiB
    against 48.9 KiB) but an image is charged by its dimensions rather than
    its weight, so the saving is in transfer only, and a red overdue stamp on
    an invoice is information.
  - **Ten pages by default**, with `max_pages` to raise the limit and `null`
    for as many as one call renders, which is 100 - not every page of a
    longer document. The page count is the real budget: one page costs
    roughly its pixels divided by 750 in tokens whatever it weighs in bytes,
    so ten is already a substantial answer. What matters more than the number
    is that the cut-off is **declared** — it is the schema default the client
    sees, it is named in the tool description, and the result reports the
    document's total pages beside how many were rendered. A partial read that
    announces itself is a limit, a silent one is a lie about the document.
- **A client that cannot follow the link still gets the file.** Resource
  links are the cheap path, not a requirement: `read_download` takes the same
  URI and puts the content into the answer directly, because a tool call is
  something every client makes. Claude Desktop turned out not to resolve
  resource links from a tool result, so this is not hypothetical. The delivery
  form follows the content rather than being one shape for everything — XML as
  **text**, so an XRechnung becomes an invoice a model can read, images as
  **images**, and everything else as an embedded binary the client handles.
  Capped at 5 MiB, the same number the upload accepts, because base64 of
  anything larger would swallow the answer it was meant to be part of. A
  `resources/read` is held to the same ceiling with the same sentence, since
  it puts the bytes into one message just as well.
- **A downloaded file is reused, not copied.** Saving refuses to overwrite a
  file whose contents differ, because replacing last month's invoice with this
  month's is worse than failing. A file whose contents are *identical* is
  handed back instead of duplicated: four downloads of one unchanged invoice
  used to leave four copies numbered up to `-4`, which is not caution but
  litter.
- **A link keeps working after a restart.** `read_download` and
  `resources/read` both resolve the file from the download directory. The
  file outlives the process, and nothing about a link is tied to one. The
  name is sanitized and the result checked to be inside the directory, since
  it arrives from the caller. Its content type comes from the extension,
  which is the name the API
  itself chose in its `Content-Disposition`. **That name always carried an
  extension**, checked 2026-10-08 over every file and every rendered
  document in the test account (`{id}.pdf`, `{id}.png`,
  `Rechnung_RE0001.pdf`), so a name without one, which would be delivered as
  an opaque blob, is a case the API has not produced. Nothing guards it.
- **The URI is an MCP resource, listed per file.** A path only means something
  while client and server share a filesystem, which the stdio transport happens
  to give and the HTTP transport of
  [section 6](transport.md#6-transport-and-runtime) will not. What holds
  either way is that the file is on the *server's* disk and the server is the
  one reading it, which is the shape MCP resources already have. Listed per
  file rather than behind one URI template, so each carries its own content
  type — a PDF and an XRechnung are not the same thing to a client deciding
  what to do with them.
- **The list and the reads are answered from the download directory**, at the
  moment they are asked, since 2026-09-30. Before that, resources were
  registered with the SDK. Registering only what the running process fetched
  was a defect, measured over stdio on 2026-08-21: a fresh process answered
  `resources/list` with an empty list and `resources/read` with "Unknown
  resource" for a file in its own download directory, which `read_download`
  read from disk in the same breath. Registering the whole directory at
  startup fixed that, at the price of a start that read every file and a
  registry that only grew. Answering from the disk keeps what the fix was for,
  drops a file removed from the directory at once, and reads nothing at start.
- **The download directory is a cache of the newest 100 downloads**, decided
  2026-09-30. Nothing used to delete a download, so the directory grew with
  every distinct document and kept business records on disk for as long as
  nobody cleared it. Every one of them is in Lexware Office and one API call
  away, so the directory is treated as what it is, a cache: older files are
  deleted at the real server start and after each download, and never by
  `--tools`, `setup` or anything else that builds a server only to look at
  it. A count rather than an age, chosen over a 24-hour limit so one number
  bounds both the directory and the list. The price is that a rarely used
  installation keeps its last hundred documents indefinitely.
  - **Where it applies.** In the default cache directory unless
    `LXO_MCP_KEPT_DOWNLOADS` says otherwise. A directory named by
    `LXO_MCP_DOWNLOAD_DIR` may be somebody's own folder, so nothing is deleted
    there unless the bound is set as well. `0` deletes nothing anywhere. The
    image names `/downloads` and sets the bound to 100 beside it, because that
    directory is the container's own. Being an image variable it beats
    `/config/.env`, so in a container the number is changed in the Compose file
    or with `docker run -e`, not in the configuration interface.
  - **What goes.** Plain files only, oldest by modification time first, which
    a reused download renews. A subdirectory or a symbolic link was put there
    by someone else. A file that cannot be deleted - one open in a viewer on
    Windows - waits for the next time. **Only a name a download could have**
    is counted or deleted: one that the sanitizing every saved name goes
    through leaves unchanged, with an extension a document has. The
    configuration interface offers the directory and the bound as fields,
    so a folder of somebody's own can end up named, and `Urlaub 2025.jpg`
    or `notes.docx` in it are left alone. A name alone cannot tell
    `report.pdf` from a download, which is why a named directory still
    needs the bound set as well. Added 2026-09-30 after a review.
  - **Asking for one that is gone says what to do.** `read_download` and
    `resources/read` both answer that the server keeps the newest downloads,
    so it may have been removed, and to download the document again - where
    only "not found" would leave the model guessing whether it ever existed.
  - **The list names the same newest downloads**, because the SDK answers
    `resources/list` whole and ignores the cursor the protocol has for paging.
    An entry is about 220 bytes, measured 2026-10-12 with the size it carries
    since then, so a thousand downloads made a list of about 220 KB. Where
    nothing is deleted, an older file is unlisted but still readable by its
    link and through `read_download`.
  - **What the list costs a model is the client's decision, not the server's.**
    Unlike the tool list of [section 8](tools.md#8-tools) it is not sent with
    every request, only when a client asks, and nothing in the tool list or the
    instructions names a download. Claude Desktop offers it in its attachment
    menu, "Add from" the server, for a person to pick from, measured
    2026-10-16. A client that passes the whole list to the model pays for every
    entry: 225 to 241 characters each with names shaped like the API's own,
    `{id}.pdf` and `invoice-{id}.pdf`, so the default 100 came to 23,415
    characters on 2026-10-16, roughly 6,200 to 7,300 tokens at the ratio of
    [section 8](tools.md#8-tools). That is why the bound is one number for the
    disk and the list: lowering `LXO_MCP_KEPT_DOWNLOADS` for such a client
    shortens both, and no second setting is needed for it.
- **A client is told when the tool list changes, since 2026-08-22, and
  when the download list does, since 2026-10-16.** The measurement below
  explains why neither happened by default. Measured against mcp 2.0.0 on
  2026-08-21:
  - Under the handshake protocols, capabilities come from `NotificationOptions`,
    whose three flags all default to `False`. `MCPServer` has no parameter for
    them and calls `create_initialization_options()` with no arguments, so
    `prompts`, `resources` and `tools` all report `listChanged: false`. Every
    server on this wrapper reports the same, which is worth knowing before
    concluding that a client is at fault.
  - Under `2026-07-28` the same capabilities derive instead from whether
    `subscriptions/listen` is served — and `MCPServer` always serves it, with
    an in-memory bus unless one is passed to the constructor. The flags would
    be `true` without this project doing anything.
  - That version is never reached here. `initialize` negotiates down to
    `2025-11-25`, the newest handshake version, whatever the client asks for,
    and the modern `server/discover` is not reachable over stdio at all.
    Measured again on 2026-10-16, and not so: over stdio, with mcp 2.0.0 and
    2.3.0 alike, a client that sends `server/discover` instead of `initialize`
    is served `2026-07-28` and promised `tools.listChanged`. The notifications
    reach it on its listen stream, see
    [section 9.2](permissions.md#92-the-policy).

  **What that analysis missed is that `PolicyServer` is ours.** The default
  is what it is, but `create_initialization_options` takes the
  `NotificationOptions` and can be bound once in the constructor — where it
  covers stdio and both HTTP transports at a stroke, since all three call
  that same method. The conclusion drawn from the measurement, that a watcher
  would be "waste at best", followed from the flag being out of reach. It was
  not.

  So [section 9.2](permissions.md#92-the-policy) now describes a server that
  announces `tools.listChanged` and sends `notifications/tools/list_changed`
  when the set of enabled tools actually changes — and **Claude Desktop acts on
  it, measured 2026-08-22** over a real stdio handshake reporting `tools:
  {'listChanged': True}`. The two halves are separable and only one of them had
  ever been tried: sending the notification without announcing the capability
  leaves a conforming client free to ignore it, and whether any client did was
  never established.

  For **resources** the same binding announces `resources.listChanged`
  since 2026-10-16, and `PolicyServer.call_tool` sends
  `notifications/resources/list_changed` to every client when a tool's
  answer carries a download link, which is the one moment the list grows.
  The answer decides rather than the tool's name, so a tool added later
  that saves a file is covered by what it returns. The watcher of section
  9.2 looks at the directory as well, by the names the list would answer
  with, because the process that wrote a download is not always the one
  that answers the listing: Claude Desktop starts the server twice and
  sends its calls to the second process, measured 2026-10-16, so the
  first learned of a download only from the disk, and a file put there
  by hand is a change of the list too. A download told at once is not
  told again, since the watcher's last sight is refreshed with it. A list
  the server itself changed is the server's to announce, and the
  protocol has the notification for it: a client that listed once would
  otherwise keep the list from the start of its session. **Claude Desktop
  does not ask again, measured 2026-10-16:** its own log shows the
  notification leaving the listing process two seconds after a download
  made by the other one, the attach menu opened twice in the minutes
  after still showed no file, and no `resources/list` followed. It acts
  on `tools/list_changed` and not on this one, so there a download
  appears in the menu at the next start. The server's half is done
  either way, and `read_download` stays, for a client that does not
  follow a resource link, which Claude Desktop does not.
- Monetary values are passed through as the API returns them, never rounded or
  reformatted, and always accompanied by the currency.
- Every result echoes the identifiers it was called with, so an answer can be
  matched back to its question.
- Fields that are null or empty upstream are dropped rather than serialized, to
  keep responses inside the client's token budget.
