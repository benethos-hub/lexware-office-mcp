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

## [0.2.2] - 2026-08-23

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

[Unreleased]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/benethos-hub/lexware-office-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/benethos-hub/lexware-office-mcp/releases/tag/v0.1.0
