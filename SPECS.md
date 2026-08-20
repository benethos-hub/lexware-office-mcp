# Specification — Unofficial Lexware Office MCP Server

> **Status: 0.1.0 in progress.** The client, the configuration, the permission
> tiers and the first tool are built and tested. Everything else in this
> document describes what is still being built, and the roadmap in section 16
> says which is which. Sections marked **(to verify)** rest on the public
> documentation and must be confirmed against the live API before the
> corresponding code is written. Facts already checked against a live account
> say so with their date.

## 1. Purpose

An [MCP](https://modelcontextprotocol.io) server that gives MCP clients (for
example Claude Desktop) access to a
[Lexware Office](https://developers.lexware.io/docs/) account through the
official public REST API. It covers the accounting and sales side of the
product: contacts, articles, sales documents (invoices, quotations, credit
notes and their relatives), bookkeeping vouchers, payments, master data and
document files.

The server is not affiliated with Lexware or Haufe-Lexware. It talks to the
documented public API with an API key the account owner generates themselves.

## 2. Scope

**In scope:** reading the company profile, searching and reading contacts and
articles, querying the voucher list, reading every sales document type, reading
bookkeeping vouchers and their payment status, reading master data (countries,
payment conditions, posting categories, print layouts), rendering and
downloading document PDFs, building deeplinks into the web app, and — behind
an explicit opt-in — creating and updating contacts, articles, vouchers and
sales documents.

**Out of scope (non-goals):** payroll, banking and transaction import,
event subscriptions and webhooks (they need a publicly reachable callback, a
different deployment shape), scraping any undocumented endpoint, storing
business data beyond a local download directory, and multi-tenant hosting where
one server instance serves several Lexware accounts.

**Deliberately gated rather than excluded:** finalizing a document, booking a
voucher, and deleting an article. These are irreversible in the product and are
governed by the permission model in section 9.

## 3. Naming

One name everywhere, with the GitHub repository as the single deliberate
exception.

| Where | Name |
|---|---|
| PyPI distribution | `benethos-lexware-office-mcp` |
| Import package | `benethos_lexware_office_mcp` |
| Console script | `benethos-lexware-office-mcp` |
| MCP server `name` | `benethos-lexware-office-mcp` |
| MCP server `title` | `Unofficial Lexware Office MCP Server` |
| GitHub repo | `benethos-hub/lexware-office-mcp` (plain, for discoverability) |
| Env var prefix | `LXO_MCP_` |
| README H1 | `# Unofficial Lexware Office MCP Server` |

"Lexware Office" is spelled out in prose because it names the integrated API,
not this project. No Lexware logos, brand colors, or domains containing
"lexware" are used, and the README carries a non-affiliation notice.

## 4. Architecture

```
MCP client (Claude)  --stdio/JSON-RPC-->  server.py (MCPServer + policy)
                                              |
                     +------------------------+-----------------------+
                     v                        v                       v
                 tools/*.py               client.py             formatting.py
             (thin tool defs)      (httpx, auth, retries,     (API JSON ->
                                    error mapping, owns the    compact output)
                                    one ratelimit.TokenBucket)
                                              |
                                        https://api.lexware.io/v1/...
```

| Module | Responsibility | State |
|--------|----------------|-------|
| `server.py` | `MCPServer` instance, tool registration, CLI and `main()`. | built |
| `__main__.py` | Enables `python -m benethos_lexware_office_mcp`. | built |
| `config.py` | Settings resolution and credential lookup, see section 7 for the precedence. | built |
| `client.py` | All HTTP access to the API: auth header, retry/backoff, pagination, error normalization. Its `ClientProvider` hands out the one client a process may have, so every tool shares one connection pool and one rate limiter. Nothing else talks to the network. | built |
| `ratelimit.py` | The token bucket, with an injectable clock so it can be tested against virtual time. | built |
| `policy.py` | Permission tiers and their enforcement, see section 9. | built |
| `formatting.py` | API JSON to compact, token-frugal tool output, including the page envelope every list endpoint shares. | built |
| `rendering.py` | PDF pages to PNG images, the only way a PDF becomes visible in a client that cannot display one. The single place allowed to touch `pypdfium2`. | built |
| `resources.py` | Downloaded files published as MCP resources, so a client that does not share a filesystem with the server can still get the bytes. See section 13. | built |
| `storage.py` | Where downloads land on disk. Its own module because the filename comes from the server and is treated as untrusted input, and because an existing file is never overwritten. | built |
| `payloads.py` | Tool arguments to API request bodies. The other direction from `formatting.py`, and not symmetric with it: a response is trimmed, a request has to be complete. See section 5 on why an update starts from the record it is changing. | built |
| `errors.py` | `ToolError` and its subclasses. | built |
| `tools/_base.py` | Registration helper, tidies a docstring before it becomes a tool description. | built |
| `tools/diagnostics.py` | Profile and connection check. | built |
| `tools/contacts.py` | Contacts, read and written. | built |
| `tools/articles.py` | Articles. | planned |
| `tools/vouchers.py` | Voucher list, bookkeeping vouchers and payment status. | built |
| `tools/sales_documents.py` | The seven sales document types. | planned |
| `tools/files.py` | Upload, download, rendered documents, deeplinks. | built |
| `tools/master_data.py` | Countries, payment conditions, posting categories, print layouts. | planned |

**Layer rule:** tool functions stay thin. Every HTTP call lives in
`client.py`, never in a tool function.

## 5. Upstream API

Facts taken from <https://developers.lexware.io/docs/>.

- **Base URL:** `https://api.lexware.io`, all resources under `/v1/`.
- **Auth:** a private API key generated by the account owner at
  `https://app.lexware.de/addons/public-api`, sent as
  `Authorization: Bearer <key>`. The documentation uses "API key" and "access
  token" interchangeably and describes no refresh flow, so the key is treated
  as a long-lived static secret. Any OAuth2 partner flow is **(to verify)** and
  out of scope for the first releases.
- **Rate limit:** up to 2 requests per second, enforced with the
  [token bucket algorithm](https://en.wikipedia.org/wiki/Token_bucket). The
  limit is **global across the whole API**, not per endpoint — the
  documentation states that "our limits refer to all endpoints of the Lexware
  API at the same time". Exceeding it returns 429 and the call is not
  performed. The documentation also warns that "enforcing the mentioned limits
  without any buffer will commonly result in rate limited requests", because
  network jitter shifts the arrival times, and that a client which does not
  reduce its rate "will stay blocked permanently". The **authorization server
  has its own, undocumented limits**, independent of the resource endpoints.
  See section 10.1 for what this means for the implementation.
- **Pagination:** `page` (zero-indexed) and `size`, response carries
  `totalPages`, `totalElements`, `size`, `number`, `first`, `last`,
  `numberOfElements`. The documented 25 is the *default*, not the ceiling.
  **Verified 2026-08-20:** the ceiling is **per endpoint**, not one number for
  the whole API. `voucherlist` refuses 251 with "parameter 'size' must be equal
  or lower than 250". `contacts` accepts 500 and refuses 1000 with a different
  message, "parameter 'size' exceeds the limit". This project caps at **250**
  regardless, because it is the lowest ceiling measured and therefore the one
  value that works everywhere. `LXO_MCP_PAGE_SIZE` is validated against it, so
  a misconfiguration fails at startup rather than as an API error later.
- **Master data is not paginated.** `countries` and `payment-conditions` return
  a bare JSON array, not a page object. Verified 2026-08-20. Anything reading
  those endpoints must not assume the page envelope.
- **Filtering:** `?filter_1=value_1&filter_n=value_n`, combined with AND.
  Pattern matching supports `_` (one character) and `%` (many), escaped with a
  backslash.
- **Filter validation is per parameter and the messages are poor.** Verified
  2026-08-20 on `contacts`: `name` and `email` are refused below three
  characters, and the refusal reads "size must be between 3 and 128" although
  `size` is a different parameter entirely. `number` is numeric, and a
  non-numeric value gives a 400 whose body carries no `message` at all, only
  `IssueList: [{source: "number", i18nKey: "invalid_value"}]`. An out-of-range
  `page` or `size` is **not** refused, it is silently replaced by the default.
  Two conclusions: the tool schemas enforce what the API enforces, so a caller
  gets a comprehensible constraint instead of a misleading error, and
  `IssueList` is parsed into the error text because sometimes it is the only
  thing the response says.
- **Optimistic locking:** mutable resources carry a `version` integer. A PUT
  must send the version it read. **Verified 2026-08-20:** a mismatch comes back
  as **406**, not the 409 the documentation implies, and the body names the
  field: `IssueList: [{source: "version", i18nKey: "invalid_value"}]`. Status
  alone is therefore not enough to tell a stale version from any other refusal,
  which is why the client reads the issue sources. See section 12.
- **A PUT replaces the record, it does not patch it.** Verified 2026-08-20 on
  contacts: a body carrying only the changed fields does not leave the rest
  alone, it empties it. Any update therefore reads the current record first and
  lays the change on top, which costs a second API call and is not optional.
  Read-only fields in the record that comes back (`organizationId`, the role
  numbers, `archived`) are accepted and ignored on the way in, so they can be
  sent back untouched.
- **Datetimes:** RFC 3339 with offset, for example
  `2023-02-21T00:00:00.000+01:00`. **Country codes:** ISO 3166 alpha-2.
- **Known constraints:** at most 300 line items per voucher, at most one
  billing and one shipping address per contact for API writes, at most one
  entry per email or phone type, at most one contact person per company.
- **Contact writes, verified 2026-08-20.** A new contact needs `version: 0`,
  at least one of `roles.customer` and `roles.vendor` (an empty object is
  enough, the numbers are assigned by Lexware), and exactly one of `company`
  and `person` — sending both is refused. Every one of these refusals arrives
  as **406** with an `IssueList` naming the field:
  `roles.customer or roles.vendor: missing_entity`,
  `company or person: missing_entity`, `company and person: invalid_value`,
  `addresses.billing.size: invalid_value`, `countryCode:
  countrycode_is_not_valid`. A creation answers with
  `{id, resourceUri, createdDate, updatedDate, version}` and `version` starts
  at 1, not 0.
- **A contact cannot be deleted or archived through the API.** Verified
  2026-08-20: `DELETE /v1/contacts/{id}` answers 404, there is no such route,
  and a PUT setting `archived: true` answers 200 and leaves the flag at
  `false`. `archived` is therefore something a tool reports and never sets.

### Endpoints in use

| Resource | Path | Methods used |
|---|---|---|
| Profile | `/v1/profile` | GET |
| Contacts | `/v1/contacts` | GET, POST, PUT |
| Articles | `/v1/articles` | GET, POST, PUT, DELETE |
| Voucherlist | `/v1/voucherlist` | GET |
| Payments | `/v1/payments/{voucherId}` | GET |
| Vouchers | `/v1/vouchers` | GET, POST, PUT |
| Invoices | `/v1/invoices` | GET, POST |
| Quotations | `/v1/quotations` | GET, POST |
| Credit notes | `/v1/credit-notes` | GET, POST |
| Order confirmations | `/v1/order-confirmations` | GET, POST |
| Delivery notes | `/v1/delivery-notes` | GET, POST |
| Dunnings | `/v1/dunnings` | GET, POST |
| Down payment invoices | `/v1/down-payment-invoices` | GET |
| Recurring templates | `/v1/recurring-templates` | GET |
| Payments | `/v1/payments/{id}` | GET |
| Payment conditions | `/v1/payment-conditions` | GET |
| Posting categories | `/v1/posting-categories` | GET |
| Print layouts | `/v1/print-layouts` | GET |
| Countries | `/v1/countries` | GET |
| Files | `/v1/files` | GET, POST |
| Rendered document | `/v1/{resource}/{id}/document` | GET |
| Document file | `/v1/{resource}/{id}/file` | GET |

Event subscriptions (`/v1/event-subscriptions`) are deliberately unused, see
section 2.

### Files, verified 2026-08-20

- **Uploading creates a voucher.** `POST /v1/files` answers **202** with
  `{id, voucherId}`: it does not only store a file, it also creates the
  bookkeeping voucher the file belongs to. Any tool that uploads is therefore
  a write in the fullest sense, and the voucher it produces cannot be deleted.
- **The form.** The part must be named `file`, and `type` is a required form
  field whose only accepted value is `voucher` — `receipt` is refused with
  "Invalid or missing upload type." That settles open question 3.
- **The ceiling is 5 MiB inclusive.** 5,242,880 bytes is accepted, one byte
  more is refused with `max_file_size_exceeded`. The tool checks this before
  spending a request.
- **What may be uploaded: PDF, JPEG, PNG and XML.** Measured by trying them,
  and the same four the web app names. `.gif` is refused with
  `inacceptable_file_extension`, so are `.tif` and `text/plain`. **`.xml` is
  accepted and parsed as an XRechnung** — a file that is not one comes back as
  `invalid_xrechnung`, which is how an e-invoice reaches the account. The API
  inspects content, not just extensions: a degenerate 1x1 PNG is refused with
  `image_conversion_error` and a structurally broken PDF with
  `voucher_upload_toxic_pdf`.
- **Downloading.** `GET /v1/files/{id}` returns the bytes with the file's own
  content type and `Content-Disposition: inline; filename={id}.{ext};`.
  Asking for `application/xml` when the file is a PDF is a **404**, not a 406.
  The client's default `Accept: application/json` has to be overridden or the
  wrong representation comes back.
- **Rendered documents are for sales documents only.**
  `/v1/vouchers/{id}/document` and `/v1/vouchers/{id}/file` answer 404 for a
  bookkeeping voucher. The sales document paths are **(to verify)**: the test
  account holds no sales documents, so `download_document` follows the
  documented Accept matrix without a live check behind it.
- **Deeplinks** are `{appbaseurl}/permalink/{resource}/{action}/{id}` with
  **plural, kebab-cased** resources (`contacts`, `credit-notes`), and files
  are the exception at `{appbaseurl}/permalink/files/{id}` with no action.
  Taken from the documentation's own quoted examples rather than guessed.

### Voucher semantics, verified 2026-08-20

- **"Voucher" is three things.** `/v1/voucherlist` is a read-only **index**
  over sales and bookkeeping documents and the only way to find one without
  its id. `/v1/vouchers` holds **bookkeeping vouchers**, a booked amount
  against a posting category. The sales documents live behind their own paths.
  Conflating them is the easiest mistake to make here.
- **`voucherType` and `voucherStatus` are required**, not optional filters.
  Without them the API answers "Missing required request parameters". The
  accepted values were measured by trying every plausible one:
  `any, invoice, salesinvoice, purchaseinvoice, creditnote, salescreditnote,
  purchasecreditnote, orderconfirmation, quotation, deliverynote,
  downpaymentinvoice` and `any, draft, open, paid, paidoff, voided,
  transferred, sepadebit, overdue, accepted, rejected, unchecked`. **`dunning`
  is not accepted**, so dunnings cannot be found through the voucher list at
  all.
- **`sort` accepts only the voucher date**, ascending or descending. Anything
  else is refused with "parameter 'sort' is invalid".
- **A bookkeeping voucher cannot be deleted.** `DELETE /v1/vouchers/{id}`
  answers 404, so a wrong entry has to be corrected in the web app. Creating
  one without `voucherStatus` books it as `open` immediately, and
  `voucherStatus: unchecked` is the way to record one that still needs review.
- **A PUT must not echo `voucherStatus`.** Unlike a contact, which accepts its
  read-only fields and ignores them, a voucher is refused outright with
  `voucherStatus: invalid_value`. `payloads.VOUCHER_PUT_DROP` is what strips
  it, along with `contactName`, the timestamps and `organizationId`.
- **The API checks the totals against the lines** and refuses a mismatch with
  `totalGrossAmount: invalid_total_amount`, and the tax against the tax type
  with `voucherItems[0].taxAmount: invalid_taxamount`. Every voucher
  validation failure arrives as **406**.
- **Payment information exists only once a voucher is booked.** Asking for an
  `unchecked` one is refused with "No payment information for this
  voucher/voucher type".

### Document semantics that shape the tools

- A sales document is created as a **draft** (editable) unless
  `?finalize=true` is passed, which creates it in status **open** and makes it
  immutable through the API. The voucher number is assigned by Lexware.
- **Pursue:** `POST /v1/invoices?precedingSalesVoucherId={id}` creates a
  document following a finalized predecessor along the
  quotation → order confirmation → delivery note → invoice chain. A draft
  predecessor cannot be pursued and yields 406.
- **PDF:** `GET /v1/{resource}/{id}/document` returns a `documentFileId` for
  the Files endpoint. Rendering is triggered when a document moves from draft
  to open. `GET /v1/{resource}/{id}/file` downloads the binary directly and
  honours the `Accept` header, so an XRechnung can be fetched as XML or PDF
  while ZUGFeRD and plain documents are PDF only.
- **Deeplinks:** `{appbaseurl}/permalink/{resource}/view/{id}` and `/edit/{id}`.
  The app base URL is configuration, not something to hardcode from a guess
  **(to verify)**.

## 6. Transport and runtime

- **Phase 1 is stdio only.** `MCPServer.run()` with the default stdio
  transport, launched as a subprocess by the client. This is the entire
  transport surface of the first releases, by explicit decision.
- **Phase 3 adds HTTP** (`--transport streamable-http` / `sse`) with
  `--host`, `--port`, `--path`, `--allowed-hosts`, `--allowed-origins`. The HTTP
  transport also needs its own authentication in
  front of the API key, because anyone who can reach the port can otherwise
  spend the account owner's credentials. A static bearer token checked by the
  server, plus the SDK's DNS-rebinding `Host`/`Origin` guard, is the intended
  minimum. Until that is built, HTTP stays unavailable rather than insecure.
- **stdio is sacred.** stdout carries the JSON-RPC stream. Library and server
  code never `print()` to stdout, all logging goes to stderr
  (`logging.basicConfig(stream=sys.stderr)`).
- **CLI flags:** `--log-level`, `--mode`, `--download-dir` in phase 1, plus the
  transport flags in phase 3. Every flag has an env equivalent, precedence is
  CLI > env > `.env` > default.
- **Entry points:** `python -m benethos_lexware_office_mcp` or the
  `benethos-lexware-office-mcp` console script.
- **Python:** 3.11 to 3.14, all in the CI matrix.

## 7. Configuration

| Env var | Meaning | Default |
|---|---|---|
| `LXO_MCP_API_KEY` | Lexware Office API key. Required. | — |
| `LXO_MCP_BASE_URL` | API base URL, for tests and sandboxes. | `https://api.lexware.io` |
| `LXO_MCP_APP_BASE_URL` | Web app base used to build deeplinks. | `https://app.lexware.de` |
| `LXO_MCP_MODE` | Permission tier, see section 9. | `read` |
| `LXO_MCP_DOWNLOAD_DIR` | Where downloaded documents are written. | user cache dir |
| `LXO_MCP_PDF_PAGES` | Pages of a PDF `read_download` renders when the call does not say. Deliberately not named after a page size: `LXO_MCP_PAGE_SIZE` counts rows of a search result, this counts sheets of a document, and one answering for the other would be a quiet mistake. No upstream ceiling exists to derive a maximum from, and a caller overrides it per call anyway. | `10` |
| `LXO_MCP_TIMEOUT` | HTTP timeout in seconds. | `30` |
| `LXO_MCP_RATE` | Token bucket refill, requests per second, global. | `1.5` |
| `LXO_MCP_BURST` | Token bucket capacity. | `2` |
| `LXO_MCP_PAGE_SIZE` | Rows per page, sent upstream as `size`. | `25` |
| `LXO_MCP_LOG_LEVEL` | Log level on stderr. | `INFO` |

Precedence, highest first: a real environment variable, `.env` in the working
directory, `config/.env` in the working directory, `config/.env` of the source
checkout the package runs from, and `.env` in the per-user config directory
resolved via `platformdirs`.

The fourth rule exists because a client such as Claude Desktop spawns the
server with a working directory of its own, so a clone had to be startable from
anywhere without repeating its configuration. It is limited to a **source
checkout**, decided by a `pyproject.toml` beside the `config/` directory. An
installed package sits in `site-packages`, which has none, so nothing is read
from there — configuration read out of a directory shared with every other
installed package is not a property this server should have. The invocation
outranks the installation, which is why the working directory sits above it.

No secret is ever read from a versioned file. `config/.env` is gitignored and
`config/.env.sample`, which is committed, holds no key.

## 8. Tools

Tool count is kept deliberately low. Descriptions and schemas are sent on every
request, so a wide surface is paid for continuously. Measured on a comparable
MCP server, 22 tools came to roughly 23,000 characters of descriptions and
schemas on every single request. Related endpoints
are therefore grouped behind one tool with an enum parameter rather than
exposed one tool per path.

### Phase 1 — read only

| Tool | Inputs | Output | Calls |
|---|---|---|---|
| `get_profile` | — | `{organizationId, companyName, connectionId, taxType, smallBusiness, businessFeatures}`. Verified against a live account 2026-08-20. The `created` block the API also returns is **dropped**: it carries the setting-up user's email address, which the tool does not need and which has no business reaching a language model. Doubles as the connection check. | 1 |
| `search_contacts` | `name`, `email`, `number`, `role` (customer/vendor/any), `page`, `size` | `{contacts: [{id, version, name, type, roles, customerNumber, vendorNumber, email, phone, archived?}], page: {number, size, totalElements, totalPages, last}}`. The filter is named `name` rather than `query`, because it matches names only and calling it a query would promise a full-text search the API does not offer. `name` and `email` carry the API's three-character minimum in the schema. The response's `sort` block is dropped, and `archived` appears only when true. Built and verified against live records 2026-08-20. | 1 |
| `get_contact` | `contact_id` | the full contact including addresses, roles and `version`, with `organizationId` dropped: it is identical on every record and `get_profile` already answers it. A drop-list, not an allow-list, so a field added upstream still surfaces. Built and verified against live records 2026-08-20. | 1 |
| `search_articles` | `query`, `article_number`, `gtin`, `type`, `page`, `size` | list of `{id, version, title, articleNumber, type, unitName, price, currency}` | 1 |
| `get_article` | `article_id` | full article including version | 1 |
| `search_vouchers` | `voucher_type`, `voucher_status`, `contact_id`, `date_from`, `date_to`, `only_open`, `only_overdue`, `archived`, `sort`, `page`, `size` | `{vouchers: [{id, voucherType, voucherStatus, voucherNumber, voucherDate, dueDate, contactName, totalAmount, openAmount, currency, archived?}], page: {...}}`. The central discovery tool, and the only way to find a document at all. `voucher_type` and `voucher_status` default to `any` because the API requires them, so the tool always sends both. `createdDate` and `updatedDate` are dropped from the rows: they say when somebody typed it in, not when the document is dated. Built and verified live 2026-08-20. | 1 |
| `get_sales_document` | `document_type` (invoice, quotation, credit-note, order-confirmation, delivery-note, dunning, down-payment-invoice), `document_id` | the document, normalized to a common envelope with the type-specific fields kept intact | 1 |
| `get_voucher` | `voucher_id` **or** `voucher_number` | the bookkeeping voucher with its lines, posting categories, tax type and `version`. Takes a number as well as an id because `voucherlist` cannot filter by number and `/v1/vouchers?voucherNumber=` is the only lookup the API offers. A number matching several vouchers is refused with their ids rather than guessed at. Built and verified live 2026-08-20. | 1 |
| `get_payments` | `voucher_id` | `{openAmount, paymentStatus, currency, voucherType, voucherStatus, paymentItems}`. An `openAmount` of 0 is the answer to "is it settled" and is reported, not dropped. Refused by the API for a voucher that is not booked yet. Built and verified live 2026-08-20. | 1 |
| `get_recurring_templates` | `page`, `size` | list of recurring templates | 1 |
| `get_master_data` | `kind` (countries, payment-conditions, posting-categories, print-layouts) | the requested list, trimmed to the fields a caller needs | 1 |
| `download_document` | `document_type`, `document_id`, `file_format` (pdf/xml) | `{path, mimeType, size}`. Renamed from the planned `get_document_pdf`, which promised a format the tool does not always fetch, and reduced to **one** behaviour and **one** call: it downloads and saves. The planned variant that returned a `documentFileId` without saving was dropped, because the only thing a caller could do with that id is hand it to `download_file` — the same work through a second tool. **(to verify)** against a live sales document. | 1 |
| `download_file` | `file_id`, `file_format` (pdf/xml) | `{path, uri, mimeType, size, deeplink}` plus a `resource_link` block. The `deeplink` costs nothing to build and is the one route that works when the client can display neither the file nor a link: a person opens it in a browser. One helper builds it for both downloads and `get_deeplink`, so the three cannot drift apart. The bytes stay out of the answer and are fetched by the client from `uri` when it wants them, see section 13. An existing file is never replaced. Built and verified live 2026-08-20. | 1 |
| `read_download` | `uri` | `{uri, mimeType, size, deliveredAs, pages?, pagesShown?}` plus the content itself. The fallback for a client that does not follow resource links: it puts a downloaded file into the answer as text, as an image, as **rendered page images for a PDF**, or as an embedded binary, depending on what the file is. Refuses anything outside `lexware://download/`, so it is not a file reader, and refuses above 5 MiB. Built 2026-08-20 after Claude Desktop turned out not to resolve resource links. | 0 |
| `get_deeplink` | `target`, `target_id`, `action` (view/edit) | `{url}`. `target` reaches past the sales documents to contacts, vouchers and files, since the permalink shape is the same for all of them and the extra entries cost nothing. Built 2026-08-20. | 0 |

### Phase 2 — writes, behind `LXO_MCP_MODE=write`

| Tool | Inputs | Calls | Notes |
|---|---|---|---|
| `create_contact` | `kind` (company/person), `name`, `roles`, `first_name`, `salutation`, `email`, `phone`, `billing_address`, `shipping_address`, `vat_registration_id`, `tax_number`, `note` | 1 | Returns the id and version the API answers with, not the record. The customer and vendor numbers are assigned by Lexware, so they are only visible after reading the contact back. The parameters are flat rather than the API's nested object because the API itself allows only one billing address, one shipping address and one entry per email or phone type, so flat loses nothing. Addresses are the exception and stay structured, since they have five fields each. Built 2026-08-20. |
| `update_contact` | `contact_id`, `version`, then the same fields, all optional | 2 | Reads the record and lays the given fields on top, because a PUT replaces rather than patches. The `version` the caller passes is checked against the record before anything is sent, so a stale one costs one read and no write. Built 2026-08-20. |

| Tool | Notes |
|---|---|
| `create_contact` / `update_contact` | **Built 2026-08-20**, see the phase 1 table above for what they cost. |
| `create_article` / `update_article` | same version rule |
| `create_voucher` / `update_voucher` | **Built 2026-08-20.** `create_voucher` takes the type, date, tax type and lines, and adds the totals up from the lines unless the caller states them, which is arithmetic the API insists on rather than a number being invented. `unchecked` records an entry for review instead of booking it. `update_voucher` reads, merges and replaces like `update_contact`, and additionally strips the fields a voucher refuses on the way back in. Neither can be undone: the API cannot delete a voucher. |
| `create_sales_document` | `document_type` limited to the types the API allows creating, structured line items, optional `preceding_sales_voucher_id` for pursue |
| `upload_file` | **Built 2026-08-20.** Takes a path on the machine the server runs on. Accepts PDF, JPEG, PNG and XML, and refuses a missing file, any other extension and anything above 5 MiB before spending a request. The answer carries a `voucherId` as well as a file id, because uploading creates a voucher, and the docstring says so where a caller will read it. |

### Phase 3 — irreversible, behind `LXO_MCP_MODE=full`

`finalize` on `create_sales_document`, booking a voucher, `delete_article`.
Each of these additionally takes an explicit `confirm: true` argument, so an
accidental call fails with a clear message instead of an irreversible effect.

### Parameter conventions

- Every parameter gets an `Annotated[type, Field(description=...)]`, numeric
  limits get `ge`/`le` bounds, enums are real `Literal` types so the client can
  only send a valid value.
- The docstring is the tool description the model reads. It is written for an
  LLM caller and states what the tool does, when to use it instead of a
  neighbouring tool, and what the caller must fetch first (for example the
  `version` before an update).
- IDs are Lexware UUIDs. No tool invents, guesses or assembles an ID. A caller
  that has only a name uses `search_contacts` or `search_vouchers` first.

## 9. Permission model

Two gates, and a call needs both. The **tier** is the coarse ceiling an
operator sets. The **per-tool policy** refines what is allowed inside it.
Enabling a tool in the policy can never lift it above the tier, so a deployment
pinned to `read` stays read-only whatever any file says.

### 9.1 Tier — the ceiling (implemented)

| Mode | Allows |
|---|---|
| `read` (default) | queries only |
| `write` | additionally create and update of drafts and master records |
| `full` | additionally the irreversible operations: finalizing a document, booking a voucher, deleting an article |

Set with `--mode` or `LXO_MCP_MODE`, so a container, a CI job or a client
configuration can pin it without touching a file. Deliberately coarse and
deliberately not changeable at runtime: it states what this process may at
most do.

Checked at two levels (defence in depth):

1. **Registration:** a tool above the active tier is not registered, so it
   never appears in `list_tools` and costs no tokens.
2. **Call:** the tier is checked again when a call arrives, so a client holding
   a stale tool list cannot smuggle one through.

The default is `read` because this server points at a real accounting system
holding real business records. Nothing that writes is reachable without a
deliberate change by the account owner.

### 9.2 Per-tool policy — the refinement (planned)

**A single read/write/full switch is too blunt.** Raising the tier to `write`
so the model may draft a quotation also hands it every other write tool in the
server. What is wanted is a decision per tool, with groups as a convenience
rather than as the unit of truth.

**Registry.** Every tool carries metadata, recorded where the tool is defined
so the classification cannot drift away from the code:

| Field | Values |
|---|---|
| `domain` | diagnostics, contacts, articles, vouchers, sales documents, payments, files, master data |
| `access` | `read` or `write` |
| `effect` | write tools only: `create`, `update`, `delete`, `book`, `finalize` |

`delete`, `book` and `finalize` are marked **irreversible**. In this product
that is not a figure of speech: a finalized invoice carries a consecutive
number and can be corrected only by a further document, which is the same
reason section 10.2 refuses to retry a failed creation.

**Policy store.** Flags per tool in a JSON file, in the config directory and
never in the repository:

```json
{ "get_profile": true, "search_vouchers": true, "create_invoice": false }
```

Defaults when the file is missing or a tool is absent from it: **read tools on,
write tools off, unknown tools off.** A tool that arrives with an upgrade is
therefore off until someone turns it on, rather than silently enabled by an
update.

**Group actions are presets, not state.** "All contact tools on", "everything
read-only", "irreversible off" set individual flags and nothing else. The truth
stays per tool, so the file always says exactly what is allowed.

**Enforcement** mirrors 9.1 and adds the policy to both gates: a disabled tool
is not listed, and a call to one is refused with a message naming the tool and
where to enable it.

**Changing it while the server runs.** Under stdio the client spawns the server
as its own process, so a configuration interface is a separate process and the
two share the policy file: the interface writes it, the server re-reads it when
answering `tools/list` and before each call. Re-reading a small JSON file per
request is cheap and beats holding a copy that can go stale. The server then
sends `notifications/tools/list_changed` so the client refetches. **(to
verify)** how completely the SDK supports a tool list that changes after
startup. Under the HTTP transport of 0.3.0 both would live in one process and
share the state directly, with the file serving only to survive a restart.

**Interface.** The natural home is the configuration interface of section 16.1:
a table grouped by domain, one toggle per row, `read` and `write` marked,
irreversible effects flagged, and the connected organization shown at the top
from `get_profile` — so it is never in doubt which account the permissions
being granted apply to.

Later, if it earns its place: confirmation required rather than plain on and
off for irreversible tools.

## 10. Client behaviour (`client.py`)

- One shared `httpx.AsyncClient` with `Authorization: Bearer` set once, a
  connection pool, and `LXO_MCP_TIMEOUT`.
- **Rate limiting:** a single process-wide token bucket, see section 10.1.
- **Retries:** method-aware, see section 10.2. A 429 is always safe to retry,
  a failed POST is never retried, and 4xx other than 429 is never retried.
- **Pagination:** search tools request one page and report the page metadata.
  A caller that wants more asks for the next page. The client does not silently
  walk every page of a large account.
- **Error mapping:** upstream status to `ToolError` subclass, see section 12.
- **Secrets:** the API key is never logged, never echoed in a tool result, and
  redacted from any error text before it leaves the process.

### 10.1 Rate limiting

The upstream limit is 2 requests per second, applied as a token bucket **across
all endpoints of the API at once**. That single sentence decides the design.

#### The algorithm, and which half of it we implement

The [token bucket](https://en.wikipedia.org/wiki/Token_bucket) has three
parameters: a bucket of capacity **b** tokens, a token added every **1/r**
seconds, and a cost of **n** tokens per unit of work. Tokens arriving at a full
bucket are discarded. Work costing *n* tokens is **conformant** when the bucket
holds at least *n*, which are then removed, and **non-conformant** otherwise,
in which case the bucket is left untouched. Here *n* is 1 for every request,
because the limit counts calls and not payload bytes. The long-run average is
capped at *r*, while *b* sets how much of an idle period may be spent at once.

The interesting part is what happens to a non-conformant request. The
literature gives three treatments, and Lexware and this server pick different
ones from the same list:

| Side | Treatment | Effect |
|---|---|---|
| Lexware | **policing** — drop | 429, and the documentation is explicit that "the actual call will not be performed" |
| This server | **shaping** — enqueue | the call waits until enough tokens have accumulated, then goes out |

So both sides run the same algorithm and only the penalty differs. That is why
the local bucket has to be at least as strict as the remote one: a request our
shaper lets through early is a request their policer destroys. The third
treatment, marking a request non-conformant and sending it anyway, has no
meaning for an HTTP client and is not used.

The queueing variant of the **leaky bucket** was considered and rejected. It
would emit a perfectly even stream with no jitter at all, but it also forbids
any burst, so a tool that legitimately costs two calls would always eat a full
`1/r` gap in the middle. Mirroring the upstream model is both simpler and
closer to how the account is actually metered.

#### Implementation

```
acquire(n = 1):
    now    = monotonic()
    tokens = min(b, tokens + (now - last_refill) * r)
    last_refill = now
    if tokens >= n:
        tokens -= n
        return                      # conformant, send immediately
    wait (n - tokens) / r seconds   # shaping: enqueue, do not drop
    then retry
```

Four details that matter:

- **Continuous refill, no background task.** Tokens are recomputed from the
  elapsed time on each acquisition, so an idle server costs nothing and there
  is no timer to keep alive. Fractional tokens are kept, matching the fluid
  formulation of the algorithm.
- **A monotonic clock, never the wall clock.** An NTP correction or a
  daylight-saving step must not hand out free tokens or stall the server for an
  hour.
- **One lock around the whole acquisition.** Two concurrent tool calls in the
  same event loop must not both read the same token count and spend it twice.
  Waiters are served in arrival order so a chatty tool cannot starve a quiet
  one.
- **The wait is awaited, not slept.** `asyncio.sleep`, so the server keeps
  answering other MCP traffic while a call is queued behind the bucket.

**One bucket per process, not one per endpoint or per tool.** The limiter is a
single object owned by the client module and shared by every request, whatever
resource it targets. A per-resource limiter would let five idle endpoints hand
out five buckets worth of tokens and blow the global budget while each one
believes it is well behaved. There is exactly one bucket, and every outbound
call acquires a token from it before the request is issued, including retries,
pagination follow-ups and the second call that `get_document_pdf` needs.

**Parameters:** *r* is `LXO_MCP_RATE` (default `1.5` per second) and *b* is
`LXO_MCP_BURST` (default `2`). The rate sits deliberately **below** the
documented 2 per second, because the documentation says that enforcing the
limit without a buffer commonly produces 429s anyway once network jitter shifts
the arrival times. A shaper that aims exactly at the policer's threshold loses
every race the network decides.

The capacity is the more dangerous of the two. Upstream *b* is not documented,
only *r*, so how long an idle stretch may be cashed in at once is unknown. A
generous local *b* would let the server open with a burst that our own limiter
considers conformant and theirs does not — it would move the failure from our
queue to their 429 without any warning that it had happened. `2` is therefore
the deliberate floor: enough that the two calls of `get_document_pdf` are not
artificially separated, small enough that a wrong guess about upstream capacity
costs little. Both values are configurable, so an account that behaves
differently can be tuned without a code change, and open question 6 in
section 16 is what would let the default be raised with evidence.

**What the budget comes to in practice.** The documented ceiling is a rate, not
a quota, so it is easiest to read as a steady gap between calls:

| | rate *r* | sustained per minute | gap between calls |
|---|---|---|---|
| Lexware documented ceiling | 2 per second | 120 | 500 ms |
| Server default (`LXO_MCP_RATE`) | 1.5 per second | 90 | 667 ms |

The per-minute figure is a consequence, **not a quota that can be banked**.
A fixed window of 120 per minute would permit all 120 in one burst at the end
of the minute. A token bucket never does: whatever the minute's total, the
instantaneous allowance is only ever the *b* tokens currently in the bucket,
and after that the pace returns to *r*. A client that has been idle can start
with a burst of *b*, and that is the entire concession.

At the default this means a broad question stays comfortable. A quarter of
invoices at 25 rows per page is 20 pages, so 20 calls, roughly 13 seconds.
Reading 50 documents in full is 50 calls, about 33 seconds. The limit only
becomes the bottleneck when a caller walks thousands of rows, which is exactly
the case section 13 caps by returning one page at a time.

**No parallel fan-out.** Every request passes the bucket *before* it is issued,
rather than being fired concurrently and throttled afterwards. That is not the
same as one request at a time — while tokens remain, up to *b* calls go out
back to back, which is the whole point of a token bucket. What is ruled out is
a tool spawning a batch of calls and leaving the limiter to sort out the
aftermath. A tool that needs several calls acquires for each one in turn and
simply takes longer. The `Calls` column in section 8 states what each tool
costs, so a caller can reason about it.

**The client-side limiter is necessary, not sufficient.** The budget belongs to
the Lexware account, not to this process. A second server instance, another
integration, or a script the user runs by hand all draw from the same 2 per
second. 429 handling therefore stays mandatory and is never treated as a bug in
the limiter.

**Backing off for real.** On 429 the request is retried with exponential
backoff and jitter, honouring `Retry-After` when it is present. After a small
number of consecutive 429s the client stops retrying, drains the bucket for a
cool-down window, and returns `RateLimitError` to the caller. This is a
deliberate circuit breaker rather than politeness — the documentation states
that a client which does not reduce its rate stays blocked permanently, so
retrying harder is the one response that can turn a transient problem into a
dead API key.

**Authorization requests are separate.** The authorization server has its own
undocumented limits. Should a future release ever obtain tokens rather than
using a static API key, those calls get their own conservative bucket and are
never counted against the resource budget.

### 10.2 Retry safety

Retrying is not uniformly safe, and the difference matters more here than in
most APIs, because a duplicate request can create a second invoice in someone's
bookkeeping. A duplicate is not a technical annoyance to be cleaned up later —
it is a document with a consecutive number that the account owner has to cancel
by hand. The rule is therefore decided per HTTP method and per failure mode,
not per status code alone.

| Failure | GET | PUT, DELETE | POST |
|---|---|---|---|
| 429 | retry | retry | **retry** |
| 5xx | retry | retry | **never** |
| timeout, connection reset | retry | retry | **never** |
| 4xx other than 429 | never | never | never |

**Why 429 is the exception.** The documentation states that on 429 "the actual
call will not be performed". The request never reached the resource, so
repeating it cannot duplicate anything. This is the one failure mode where the
upstream tells us the outcome with certainty.

**Why a failed POST is never retried.** A 5xx or a timeout says nothing about
whether the document was created. The request may have been executed and only
the response lost. Retrying then risks a second invoice, and the client cannot
tell the two cases apart. Instead the failure surfaces as an `UpstreamError`
whose message says explicitly that the outcome is unknown and that the caller
must check whether the document exists before trying again. Losing a request is
recoverable, silently issuing two invoices is not.

**Why PUT is safe.** Beyond being idempotent, an update carries the `version`
it read. If the first attempt succeeded, the version has moved on and the retry
fails with 409 rather than applying the change twice. Optimistic locking makes
the retry self-protecting.

Open question 2 is what would change this table: if the API offers an
idempotency key, POST could be retried safely and the asymmetry would
disappear.

## 11. Data and secrets policy

These rules are absolute for this repository.

- Real API keys live only in `.env` files that are gitignored. Never in code,
  documentation, tests, commit messages or memory files.
- Real tenant, organization, contact and voucher IDs never appear in versioned
  files. Documentation uses placeholders.
- Downloaded documents are real business records. They go to the download
  directory, which is gitignored, and are never committed.
- When summarizing an API response into a lasting file, real values are
  replaced by placeholders first.
- **Write operations are exercised against a Lexware account the user has
  explicitly confirmed as a test account.** There is no technical guard on the
  API side once a key has write access, only care at the call site. Before any
  write during development, `get_profile` is called and the returned
  organization checked against the confirmed one.

### 11.1 Test environment

**There is no sandbox.** The API is exposed by a single gateway at
`https://api.lexware.io`, and the reference documentation contains no notion of
a staging or sandbox host. Every call, from any key, reaches the production
system.

What Lexware offers instead is a **test account**, and the vendor recommends it
for exactly this purpose: "Wir empfehlen für die Entwicklung von Anbindungen,
welche die Public API verwenden, die Verwendung von Lexware Office
Test-Accounts." They can be created at any time, are free of charge, and are
valid for **30 days**. Aside from a few exclusions such as Elster they provide
the full feature set of the Lexware XL edition.

Three consequences follow, and they shape how this project is developed.

- **The isolation is the account, not the URL.** A test key and a live key
  differ only in their value, and both address the same base URL. Nothing on
  the wire distinguishes them, so a wrong key in the environment reaches real
  bookkeeping with no warning. This is precisely why `get_profile` is called
  and its organization checked before any write, rather than trusted to
  configuration.
- **A test account expires after 30 days.** Nothing may depend on data
  surviving in it. Test fixtures live in the repository as anonymized copies of
  response shapes, never as records that have to exist upstream, and the
  offline suite must stay runnable with no account at all.
- **An empty account answers few questions.** The open questions about page
  sizes and bucket capacity need an account holding enough contacts and
  vouchers to paginate. A freshly created test account has to be populated
  before it can measure anything.

**Confirmed on 2026-08-20:** an API key can be generated inside a test
account, and it reaches the ordinary production endpoints. A key from a
freshly created test account returned its profile, paged the voucher list and
read master data. This was open question 8, and it was the one everything else
depended on.

## 12. Error handling

| Upstream | Error class | Message shape |
|---|---|---|
| 400, 406 | `ValidationError` | the API `errorCode` and `message`, plus the offending field path when the response names one |
| 401 | `AuthError` | "API key rejected", with a pointer to the add-on page, never the key |
| 404 | `NotFoundError` | resource type and the ID that was asked for |
| 409 | `ConflictError` | version mismatch or locked state, naming the current version so the caller can re-read and retry |
| 429 | `RateLimitError` | after retries are exhausted, with the wait hint |
| 5xx, network | `UpstreamError` | short, no traceback |

No raw traceback ever reaches the client. Expected failures are `ToolError`
subclasses with concise, actionable messages.

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
  them rather than handing over bytes no client will show. The decisions
  behind it were measured on 2026-08-20 against a two-page A4 invoice:
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
  - **Ten pages by default**, with `max_pages` to raise or lift the limit and
    `null` for all of them. The page count is the real budget: one page costs
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
  anything larger would swallow the answer it was meant to be part of.
- **A downloaded file is reused, not copied.** Saving refuses to overwrite a
  file whose contents differ, because replacing last month's invoice with this
  month's is worse than failing. A file whose contents are *identical* is
  handed back instead of duplicated: four downloads of one unchanged invoice
  used to leave four copies numbered up to `-4`, which is not caution but
  litter.
- **A link keeps working after a restart.** `read_download` resolves the file
  from the download directory rather than from the resource registry, which
  only knows what the current process fetched. The file outlives the process,
  and only the registration was ever tied to one. The name is sanitized and
  the result checked to be inside the directory, since it arrives from the
  caller. Its content type comes from the extension, which is the name the API
  itself chose in its `Content-Disposition`.
- **The URI is an MCP resource, registered per download.** A path only means
  something while client and server share a filesystem, which the stdio
  transport happens to give and the HTTP transport of section 6 will not. What
  holds either way is that the file is on the *server's* disk and the server is
  the one reading it, which is the shape MCP resources already have. Registered
  per file rather than behind one URI template, so each carries its own content
  type — a PDF and an XRechnung are not the same thing to a client deciding
  what to do with them — and so that only what this process downloaded is
  reachable, rather than everything that has ever accumulated in the download
  directory.
- Monetary values are passed through as the API returns them, never rounded or
  reformatted, and always accompanied by the currency.
- Every result echoes the identifiers it was called with, so an answer can be
  matched back to its question.
- Fields that are null or empty upstream are dropped rather than serialized, to
  keep responses inside the client's token budget.

## 14. Testing

The suite that gates the project and the checks that touch a live account are
two different things, kept apart deliberately. Section 14.1 says why.

- Offline unit tests using `httpx.MockTransport`, no network in the suite, no
  API key needed to run it.
- Fixtures are anonymized copies of real response shapes, with placeholder IDs.
- Coverage floor 80 percent, measured over the offline suite alone and
  enforced by CI once CI exists.
- **The rate limiter is unit tested against an injected clock**, never against
  `time.sleep`, so the suite stays fast and deterministic. The properties worth
  asserting follow straight from the algorithm in section 10.1: the bucket is
  shared across different endpoints rather than duplicated per resource, a
  burst larger than *b* is spread out to the long-run rate *r*, refill
  saturates at *b* so an hour of idling does not buy an hour of tokens, a
  non-conformant request is delayed and never dropped, concurrent acquisitions
  cannot spend the same token twice, and a run of 429s trips the circuit
  breaker instead of retrying forever.
- Gates: `pytest -q`, `ruff check .`, `ruff format --check .`, `mypy`.

### 14.1 Live checks are not a gate

No API key ships with this repository and none is ever placed in CI. A public
checkout cannot talk to Lexware at all, and that is the intended state: a key
held in a CI secret would put a real accounting system one merge away from a
workflow file that anyone able to open a pull request can edit.

The consequences are the point of writing this down.

- **The offline suite is the only gate.** Everything CI runs has to pass with
  no key, no network and no account. That is true today and stays true. A test
  that quietly skips when no key is present is not a gate, it is a hole that
  reports green.
- **`tests/smoke.py` is run by hand and never collected by pytest.** It takes
  a key from the normal configuration chain of section 7, refuses to start
  without one, calls `get_profile` first so whoever runs it sees which
  organization is about to be read, and performs **read-only** calls only.
  **Not built yet** — live checks have so far been one-off scripts kept
  outside the repository, which is fine for a probe and no substitute for a
  script anyone can rerun.
- **Upstream drift is invisible to CI.** The suite mocks HTTP completely, so
  it stays green through any change in Lexware's field names or response
  shapes. Only a live run catches that, and only someone holding an account
  can perform one. This is why statements about the API in this document carry
  **(to verify)** until a live call has confirmed them.
- **The open questions below cannot be closed by CI.** Questions 2 and 3 need
  write calls against a disposable test account, see section 11.1. That is a
  deliberate act by the account owner, not something automation initiates.

## 15. Conventions

- Everything in the repository is English: code, comments, docstrings and
  documentation. Conversation with the user may be German.
- Type hints everywhere, `from __future__ import annotations` at the top of
  every module.
- Virtual environment only, never the global interpreter. `uv sync --extra dev`
  is the recommended setup.
- `CHANGELOG.md` gets an entry under `[Unreleased]` in the same commit as the
  change it describes, and the static coverage badge in the README is
  re-checked whenever the number moves.
- No semicolons in prose.
- The commit identity is configured repo-locally rather than documented here,
  so a clone cannot silently inherit a different one from a global git config.

## 16. Roadmap

### What exists today

Built, tested offline and exercised against a live test account:

- `config.py`, `errors.py`, `policy.py`, `ratelimit.py`, `client.py`,
  `formatting.py`, `server.py`, `tools/diagnostics.py` and `tools/contacts.py`
- fifteen tools over the **stdio** transport. At tier `read`: `get_profile`,
  `search_contacts`, `get_contact`, `search_vouchers`, `get_voucher`,
  `get_payments`, `download_file`, `download_document`, `read_download` and
  `get_deeplink`. At tier `write`: `create_contact`, `update_contact`,
  `create_voucher`, `update_voucher` and `upload_file`
- permission tier `read` by default, enforced at registration and at call
- one shared token bucket per process, retries decided per method and failure
  mode, upstream statuses mapped onto `ToolError` subclasses
- paging and filtering in the client, one page per call, never a walk over
  every page, and one page shape shared by every list tool
- `payloads.py`, which builds request bodies and does the read-then-merge an
  update needs, and `storage.py`, which decides where a download lands and
  refuses to overwrite anything
- binary downloads and multipart uploads through the same rate limiter and
  the same retry rules as every other call

Verified against a live account rather than assumed: the profile response
shape, the per-endpoint page ceiling, the 404 and 400 error bodies including
the `IssueList`-only form, the three-character minimum on the contact filters,
that master data comes back as a bare list, that a key can be created inside a
test account, and that the bucket paces real calls (five tool calls at rate 1.5
took 2.69 seconds).

The contact and voucher tools were exercised against that account end to end:
records created, read back, searched, and updated in a way that proved the
merge keeps the fields the caller did not mention. The shapes in the test
fixtures are the shapes the API actually returned, and the enum values in the
voucher schemas were measured rather than taken from the documentation, which
does not list them.

**The immediate next step** is the sales documents: reading an invoice, a
quotation or a credit note in full. `search_vouchers` already returns their
ids and `download_document` can already fetch their PDFs, so reading the
document itself is the missing piece — and it would also put a real sales
document in the test account, which is what `download_document` still
needs to be verified against.

| Phase | Content | State |
|---|---|---|
| 0.1.0 | stdio transport, read-only tools of section 8 phase 1, config, client with rate limiting, error mapping, offline test suite, CI | **in progress** — transport, config, permission tiers, client, rate limiter, error mapping, paging, downloads, and the contact, voucher and file groups are done and exercised against a live account. Articles, sales documents, master data and CI are open. |
| 0.2.0 | write tools behind `LXO_MCP_MODE=write`, file upload, optimistic locking round trip | **started** — contacts, bookkeeping vouchers and receipt upload are written and the locking round trip works, the remaining resources are open |
| 0.3.0 | HTTP transport with its own bearer authentication, Docker image and Compose file | planned |
| 0.4.0 | irreversible operations behind `full`, pursue chains, ZUGFeRD and XRechnung download variants | planned |
| later | per-tool permission policy (section 9.2), recurring templates beyond read, event subscriptions if a deployment shape justifies them | undecided |

Section 16.1 holds one design decision that has to be settled before a release,
independently of the tool roadmap above.

### 16.1 Open: how a user configures the server

**To do before publishing.** The way settings and the API key are stored works
for a clone on the developer's machine and falls apart for anyone installing
the package. This has to be reworked rather than patched.

**What is wrong today**

- A user installing from PyPI gets **no sample**. The wheel packs the package
  directory only, and `config/.env.sample` sits beside it, so the ten settings
  exist only in the README. Verified by building the wheel: 17 files, none of
  them the sample.
- There is **no way to create the file**. The only location that works for an
  installed package is the per-user config directory, and neither the
  directory nor the file is created by anything. A user would have to make
  both by hand from a path they have to look up first.
- **Nothing says which file is in effect.** Five sources are merged, and a
  setting that appears not to work gives no hint whether it was overridden, or
  read from a file the user has forgotten about.
- The failure a user meets first is therefore a server that starts, lists its
  tools, and answers every one of them with "no API key".

**Directions, to decide rather than to assume**

- **Ship the sample in the wheel** and name its target path in the error
  message. The smallest change, and it fixes the discoverability half.
- **A command that writes the file**, creating the directory and refusing to
  overwrite an existing one. Considered once and dropped, because it wrote
  into the per-user directory while development wanted the clone. Both cases
  now exist, so it is worth reconsidering with that distinction built in.
- **A small local configuration interface.** A page served on localhost that
  shows which settings are active and where each one came from, lets the key
  be entered without going through a text file, and names the storage paths
  explicitly. It would also be the natural place to manage the per-tool
  permission policy of section 9.2 and to raise the tier deliberately, which is
  a decision that deserves more friction than editing a line in a file. Runs only when asked and never as part of the MCP server
  itself, since that speaks stdio.
- **A read-only diagnostic** as a smaller version of the same idea: report
  every candidate path, whether it exists, and which value won, without ever
  printing the key. Useful on its own, whatever else is chosen.

**Constraints that hold regardless.** The key never enters a versioned file
and never appears in output. A real environment variable keeps outranking
every file, because that is what lets a client, a container or a test override
the lot. Whatever is built must work for both an installed package and a
clone, and say plainly which of the two it is acting on.

### Open questions

Numbering is stable, so cross-references elsewhere keep pointing at the right
item. Answered questions stay in place with their answer.

1. ~~Exact maximum page size per endpoint.~~ **Answered 2026-08-20:** it is
   per endpoint, not one number. `voucherlist` caps at 250, `contacts`
   accepts 500 and refuses 1000. This project caps at 250 as the lowest
   ceiling measured. See section 5.
2. Whether the API offers an idempotency key for POST. This is the highest
   value unknown after question 8 — it decides whether a failed document
   creation can be retried at all, see section 10.2.
3. ~~File upload limits: maximum size, accepted MIME types, and whether
   `type=voucher` is the only accepted form value.~~ **Answered
   2026-08-20:** 5 MiB inclusive, PDFs and images, and yes — `voucher` is
   the only accepted value. See section 5.
4. The correct app base URL for deeplinks per account region. The permalink
   *shape* was confirmed against the documentation on 2026-08-20, the host
   was not. Two independent
   third-party implementations default to `https://app.lexware.de` and make it
   configurable, which corroborates the choice without confirming it.
5. Whether any endpoint returns a partner or OAuth-only field that a plain API
   key cannot reach.
6. The upstream token bucket capacity, which is not documented. Only the refill
   rate of 2 per second is stated, so how large a burst is tolerated after an
   idle period has to be measured. Until then `LXO_MCP_BURST` stays at `2`.
7. Whether 429 responses carry a `Retry-After` header, and whether the block
   duration grows with repeated offences as the wording about permanent
   blocking suggests.
8. ~~Whether an API key can be generated inside a 30-day test account.~~
   **Answered 2026-08-20:** yes, and it works against the production endpoints.
   See section 11.1.

**Still open and worth a probe while a test account exists:** 2 (idempotency
key) and 6 (bucket capacity). Question 7 cannot be probed
deliberately — provoking 429s is exactly what the documentation warns leads to
a permanent block.
