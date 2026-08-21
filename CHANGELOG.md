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

Nothing has been released yet. This section describes what 0.1.0 will contain.

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
  away. Costs one API call that is never
  retried, and **cannot be undone**: the API has no way to delete a voucher.
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
- **`config/.env.sample`** — a commented sample listing every setting with its
  default and the reasoning behind it. Copy it to `config/.env` and fill in the
  key. That copy is gitignored, the sample is committed and holds no key.
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
  deleting, booking and finalizing, and `--tools show` only reports.
  `--tools-file` says which file, and works with every preset. A preset
  overwrites, so it starts a file rather than updating one, and a target that
  is a directory or cannot be written is refused with a message rather than a
  traceback.
- **An edit takes effect in both directions without a restart.** The file is
  read as the tool list is built and again on every call, so a tool switched
  on is offered from the next listing and one switched off stops being
  offered. A client that has already fetched the list keeps showing it until
  it asks again, which most do only at startup.
- **Where that file lives:** found the same way the `.env` is — per-user
  configuration directory, then `config/` of a checkout, then the working
  directory, last one found winning — so a `config/tools.json` in a clone
  overrides an installed one. `LXO_MCP_TOOL_POLICY` overrides the search and
  `--tools-file` overrides both.
- `README.md` and `LICENSE` (MIT).

### Not yet

Only `get_profile` exists. Searching contacts, articles and vouchers, reading
sales documents, downloading PDFs and every write operation are specified but
not built — see the roadmap in [SPECS.md](SPECS.md) section 16, along with the
questions still open against the live API. The HTTP transport is planned for
0.3.0 and will ship with its own authentication in front of the API key.
