# Specification — Unofficial Lexware Office MCP Server

> **Status: 0.2.3.** Every tool of section 8 is built, tested and exercised
> against a live account, and so is every module of section 4, including the
> HTTP transport of section 6 and the configuration interface of section 7.1.
> The container image is published, and a client has reached a live account
> through it over HTTP.
> Facts checked against a live account say so with their date, and this
> document carries a great many of them because the API's own documentation
> turned out to be wrong more than once.

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

**Deliberately gated rather than excluded:** finalizing a document and
deleting an article. Both need a decision from the account owner rather than
from a model, and both are governed by the permission model in section 9.
Booking a voucher stood here too until 2026-08-21, when it turned out to be
something this API cannot do at all - see section 5, which measures the
absence of every state transition.

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
a person          --browser/HTTP-->  configui/ (localhost, on request only)
                                          |  writes .env and tools.json
                                          v
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
| `server.py` | The `PolicyServer` instance, which is an `MCPServer` listing only what the policy file allows, plus tool registration, the CLI and `main()`. | built |
| `__main__.py` | Enables `python -m benethos_lexware_office_mcp`. | built |
| `config.py` | Settings resolution and credential lookup, see section 7 for the precedence. | built |
| `client.py` | All HTTP access to the API: auth header, retry/backoff, pagination, error normalization. Its `ClientProvider` hands out the one client a process may have, so every tool shares one connection pool and one rate limiter. Nothing else talks to the network. | built |
| `ratelimit.py` | The token bucket, with an injectable clock so it can be tested against virtual time. | built |
| `policy.py` | The policy file, what a tool declares itself to be, and the enforcement of both, see section 9. | built |
| `formatting.py` | API JSON to compact, token-frugal tool output, including the page envelope every list endpoint shares. | built |
| `rendering.py` | PDF pages to PNG images, the only way a PDF becomes visible in a client that cannot display one. The single place allowed to touch `pypdfium2`. | built |
| `resources.py` | Downloaded files published as MCP resources, so a client that does not share a filesystem with the server can still get the bytes. See section 13. | built |
| `storage.py` | Where downloads land on disk. Its own module because the filename comes from the server and is treated as untrusted input, because a file whose contents differ is never overwritten, and because one whose contents match is reused rather than copied. | built |
| `payloads.py` | Tool arguments to API request bodies. The other direction from `formatting.py`, and not symmetric with it: a response is trimmed, a request has to be complete. See section 5 on why an update starts from the record it is changing. | built |
| `errors.py` | `ToolError` and its subclasses. | built |
| `transport.py` | The HTTP transport: the bearer guard in front of it, the DNS-rebinding allowlist, and the watch that ends the process when its settings file changes. Nothing here is reached under stdio. See section 6. | built |
| `envfile.py` | Reading a `.env` and writing one back without disturbing comments, ordering or settings this project knows nothing about. One parser, used by the server and by the interface, so a displayed value cannot differ from a read one. | built |
| `configui/` | The local configuration interface, see section 7.1. A separate command, never part of the server process. `render` is the page shell, `state` which files apply and where each value came from, `cost` what a tool costs the model, `probe` the one API call it makes, `stamp` when something was written, `profiles` named sets of permissions, `transfer` reading and writing a policy file, `pages` the three screens as pure functions, `app` the HTTP server and its two CSRF guards. | built |
| `tools/_base.py` | Registration helper, tidies a docstring before it becomes a tool description. Registers every tool: what is offered is decided when the list is built, not here. | built |
| `tools/diagnostics.py` | Profile and connection check. | built |
| `tools/contacts.py` | Contacts, read and written. | built |
| `tools/articles.py` | Articles, read, written and deleted. | built |
| `tools/vouchers.py` | Voucher list, bookkeeping vouchers and payment status. | built |
| `tools/sales_documents.py` | The seven sales document types, the path segment each one lives behind, and the templates that repeat them. | built |
| `tools/files.py` | Upload, download, rendered documents, deeplinks. | built |
| `tools/master_data.py` | Countries, payment conditions, posting categories, print layouts. | built |

**Layer rule:** tool functions stay thin. Every HTTP call lives in
`client.py`, never in a tool function.

## 5. Upstream API

Facts taken from <https://developers.lexware.io/docs/>.

- **Base URL:** `https://api.lexware.io`, all resources under `/v1/`.
- **Auth:** a private API key generated by the account owner at
  `https://app.lexware.de/addons/public-api`, sent as
  `Authorization: Bearer <key>`. The documentation uses "API key" and "access
  token" interchangeably and describes no refresh flow, so the key is treated
  as a long-lived static secret. **There is no second way in**: the
  documentation describes no OAuth2 flow, no partner access and no scopes,
  checked 2026-08-21, see open question 5.
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
| Recurring templates | `/v1/recurring-templates` | GET, and GET by id |
| Payments | `/v1/payments/{id}` | GET |
| Payment conditions | `/v1/payment-conditions` | GET |
| Posting categories | `/v1/posting-categories` | GET |
| Print layouts | `/v1/print-layouts` | GET |
| Countries | `/v1/countries` | GET |
| Files | `/v1/files` | POST, and GET by id |
| Voucher attachments | `/v1/vouchers/{id}/files` | POST |
| Document file | `/v1/{resource}/{id}/file` | GET |

`/v1/{resource}/{id}/document` exists and is **not used**. It answers with the
`documentFileId` of the same bytes `/file` serves directly, measured
2026-08-21, so every call through it is one call more for the same result.
The client method was written before that was measured and removed afterwards.

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
- **Attaching to a voucher that already exists is a different call**, and a
  different form. `POST /v1/vouchers/{id}/files` takes the same part named
  `file` and **no `type` field**, answers **202** with `{id}` alone, and the
  voucher lists that id in its `files` afterwards. Measured 2026-08-21. No
  voucher is created, which is the whole difference from `/v1/files` — and
  since a voucher cannot be deleted, choosing the wrong one of the two leaves
  a voucher behind that the API cannot remove. There is no way to detach a
  file either.
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
  bookkeeping voucher.
- **The sales document paths, verified 2026-08-21** against the first real
  invoice in the test account:
  - `GET /v1/invoices/{id}/file` with `Accept: application/pdf` returns the
    PDF, and its `Content-Disposition` carries a real name (`Rechnung_RE0001.pdf`)
    rather than something to be invented from the id.
  - Asking for `application/xml` on a document that is not an XRechnung is a
    **404**, as it is for a stored file.
  - `GET /v1/invoices/{id}/document` returns `{"documentFileId": ...}`, and
    that id through `/v1/files/{id}` yields **byte-identical** content. The
    two routes are the same file, so the extra call buys nothing.
- **A draft has no document at all**, and the two paths refuse it differently
  (verified 2026-08-21): `/file` answers **409** with "is in status 'draft'
  and therefore cannot be downloaded", `/document` answers **406** with
  "Requesting PDF document is not possible in state draft". The 409 is not a
  version conflict, which is what `client._client_error` has to keep apart —
  a stale version is a 406 naming `version`.
- **A draft is still indexed.** `/v1/voucherlist` lists it with
  `voucherStatus: draft` and it already carries its document number, so it is
  findable long before it can be downloaded.
- **`invoice` and `salesinvoice` are different types**, confirmed 2026-08-21
  now that the account holds both. A sales document written in the web app is
  indexed as `invoice`. A bookkeeping voucher created through `/v1/vouchers`
  is `salesinvoice` or `purchaseinvoice`. Filtering for one never finds the
  other, which makes this the easiest way to search past what you are
  looking for.
- **Deeplinks** are `{appbaseurl}/permalink/{resource}/{action}/{id}` with
  **plural, kebab-cased** resources (`contacts`, `credit-notes`). Requested
  against the live app on 2026-08-21, unauthenticated, reading only the
  redirect each one answers with:
  - Every sales document type and `vouchers` redirect to
    `/vouchers#/{action}/{id}` for both `view` and `edit`. The resource
    segment does not change where they land, but an unknown one is a 404, so
    it is checked.
  - `contacts/view/{id}` redirects to `/contacts/{id}`. **`contacts/edit/{id}`
    is a 404** — a contact is edited on the page it is viewed on.
  - **What the app shows for an id that does not exist was never checked**
    while logged in. The redirects above were read unauthenticated, so they
    say where a link points and nothing about what is rendered there.
    `get_deeplink` used to claim such a link opens the list of that record
    type, which was an assumption wearing the clothes of a measurement. The
    description now says only what is known: the link is not checked, and a
    wrong id still produces one.
  - **`files/{id}` is a 404**, the shape the documentation quotes.
    `files/view/{id}` is a real route but lands on the unchecked voucher list
    rather than on anything to do with that file, with a real file id as much
    as with an invented one. So a stored file has no deeplink, and
    `get_deeplink` does not offer it as a target.

### What the API does not have, measured 2026-08-21

Negatives are worth writing down: without them the same paths get tried again
in six months. Every line here is a request that was actually sent.

- **No sales document type has a collection endpoint.** `GET /v1/invoices` is
  a 404, with paging parameters and without, and so is `/v1/quotations`. Only
  `/{id}` exists. The **documentation lists a filtered collection GET for
  each of them**, and it is not there. This is what makes `voucherlist` the
  single index over sales documents rather than merely the convenient one.
- **The route for attaching a file to a voucher is `/v1/vouchers/{id}/files`,
  plural, POST only.** The documentation writes it singular and gives it a
  GET as well. Singular answers 404 for both methods, and so does GET on the
  plural. An attached file is read back through the voucher, whose `files`
  field holds the ids, and then `/v1/files/{id}`.
- **`/v1/files` has no collection GET** either. A stored file is reachable
  only by an id something else handed out.
- **Nothing about banking.** `bank-accounts`, `transactions`, `users`,
  `organizations`, `webhooks`, `taxes`, `settings` and `units` are all 404,
  and there is no `/v2`. Reconciling an account against its bank is out of
  reach through this API. What exists of payment is `/v1/payments/{voucherId}`,
  the state of one document.
- **`OPTIONS` is not answered**, so the API does not describe itself. Every
  fact in this section had to be measured, and the two above show the
  documentation is not a substitute for measuring.

### Articles, verified 2026-08-21

- **The list filters on three fields**, `articleNumber`, `gtin` and `type`,
  and both string filters match **in full**: `MCP` finds nothing when
  `MCP-A-0002` exists. There is **no text search**. `query` and `title` were
  both tried and both answered with the whole list, which is also what an
  invented parameter does — **an unknown query parameter is ignored rather
  than refused**. That makes a filter that does not exist indistinguishable
  from one that matches everything, and it is why `search_articles` offers
  neither.
- **Four fields are required to create one:** `title`, `type`, `unitName` and
  `price`, and inside the price both `leadingPrice` and `taxRate`. Measured by
  leaving each out and reading which violation came back.
- **`type` is `PRODUCT` or `SERVICE`, in capitals.** Lowercase is refused, so
  the tool passes the value through as the API spells it and a type read off
  a result can be sent straight back.
- **A price is one number and a side.** `leadingPrice` says whether the figure
  given is net or gross, and the API computes the other: a gross price of
  11.90 at 19% comes back with a net price of 10.00 beside it. Nothing here
  derives an amount.
- **The page size has a floor of 25**, and this endpoint is alone in that:
  `size` below 25 is refused with `size: MIN`, where the voucher list and the
  contacts take a page of one. Found by the live check of section 14.1 on its
  first run, which is what that script is for. The floor is in the tool's
  schema, so a caller reading it never writes the call that fails.
- **An article number has to be unique.** A second article carrying one
  already in use is refused with `materialNumber:
  MATERIAL_NUMBER_ALREADY_EXISTS`, which is a field name that appears nowhere
  in the request — reading the `details` list is what makes it legible at all.
- **A GTIN is thirteen digits**, checked upstream: `1234` and the eight-digit
  `40123456` are both refused with `gtin: VALIDGTIN`.
- **A stale version is a 409**, where a contact answers 406. Both are
  conflicts, which is why the error mapping reads the body rather than the
  status.
- **A delete is a delete.** `DELETE /v1/articles/{id}` answers **204** with an
  empty body, reading the id afterwards is a 404, and a second delete is a 404
  as well. The record is gone, not archived — the one resource in this API
  that can be removed at all, where a bookkeeping voucher cannot.

### Recurring templates, verified 2026-08-21

- **The API trims the list itself**, which no other endpoint here does. A row
  carries nine fields — id, title, the two timestamps, `address`,
  `totalPrice`, `paymentConditions` and `recurringTemplateSettings` — and the
  record behind it carries twenty-one, adding `lineItems`, `version`,
  `taxConditions`, `voucherStatus`, `taxAmounts` and the texts. What a
  template will actually invoice is therefore only visible by id, and the
  tool's description says so.
- **`recurringTemplateSettings` is the whole of what makes it a template**:
  `startDate`, `executionInterval` (`MONTHLY` measured), `nextExecutionDate`,
  `lastExecutionDate`, `lastExecutionFailed`, `executionStatus` (`ACTIVE`
  measured), `retroactiveInvoice`, `shippingType` and `finalize`. Its dates
  are plain `2026-09-21`, not the timestamps the rest of the sales documents
  use.
- **`finalize` decides how dangerous the thing is.** False means each run
  leaves a **draft**, true means it issues the invoice and mails it. Nothing
  here can change that setting — the API is read-only for templates — but a
  caller reading a template can tell which of the two it is looking at.
- **A "Dauerbeleg" is not this**, and has no endpoint at all. The web app has
  two features that both recur: a *Serienrechnung* on the sales side, which is
  what `/v1/recurring-templates` returns, and a *Dauerbeleg* on the expense
  side, which is invisible to the API. Confirmed 2026-08-21 with an active
  monthly Dauerbeleg in the account while the endpoint answered zero, and by
  probing five plausible paths for it, all 404. Only what a Dauerbeleg
  *produces* is visible, as an ordinary voucher in the voucher list, and
  nothing on that voucher says it came from one.

### What a write leaves behind, verified 2026-08-21

Every deletion this API offers, in one line: **an article.** Everything else
written through it stays, because there is no call that removes it.

| Tool | Leaves behind | Removable through the API |
|---|---|---|
| `create_article` | an article | **yes**, `delete_article` |
| `create_contact` | a contact | no — `DELETE /v1/contacts/{id}` is 404 on a record that exists |
| `create_voucher` | a bookkeeping voucher | no — `DELETE /v1/vouchers/{id}` is 404 |
| `create_sales_document` | an invoice, quotation, credit note … | no — there is no `DELETE` and no `PUT` |
| `upload_file` | a file **and a voucher** | no |
| `attach_file_to_voucher` | an attachment | no — nothing detaches a file |
| `update_contact`, `update_voucher`, `update_article` | a changed record | no undo, but the record can be changed again |

**The web app is the other half of this, and this project cannot measure it.**
What it can do is read the vendor's own help pages, which is what the
following rests on — documentation rather than measurement, and about a
product this server never touches. Per
[Rechnungen und Entwürfe löschen](https://help.lexware.de/de-form/articles/548200-rechnungen-und-entwurfe-in-lexware-office-loschen),
a document is deletable in the app unless one of these stands in the way:

- it is **final festgeschrieben**, which is the one that cannot be worked
  around: GoBD and § 146 AO require that a booked document stay unchanged, and
  the answer there is a **Storno**, a counter entry, rather than a deletion,
- it has **payments assigned** — the assignment is dissolved first,
- it has **follow-on documents** hanging off it, a credit note or a
  cancellation invoice — those go or are unlinked first,
- it has been **exported**.

**Being sent does not block a deletion**, and neither does being finalized on
its own: a finalized document can be reset to a draft in the app and then
deleted, as long as it is not final festgeschrieben. That is one detail
stricter in recollection than in the documentation, and worth having right,
because it decides how a tool should word its warning. "This cannot be undone" is a claim about
the whole product that this server is in no position to make. "The API cannot
take it back, correcting it is a job for the web app" is true, checkable, and
tells the caller where to go. The descriptions say the second.

**What makes a record permanent differs by record, and the reasons are worth
keeping apart.** For a **contact** it is a missing route and nothing more: the
app deletes one without ceremony, the API simply offers no call for it. For an
**invoice or a bookkeeping voucher** it is the law — once a document is final
festgeschrieben, GoBD and § 146 AO require it to stay, and the remedy is a
Storno rather than a deletion. An **article** is neither: it can be deleted
through both.

The difference matters wherever a warning is written. "The API cannot take it
back" is the same sentence in every case, but behind it stands a gap in one
and a legal requirement in the other, and only the first could be closed by a
future API version. An interface offering to switch these tools on has the
same distinction to make: `create_contact` leaves a record somebody can tidy
up, `create_sales_document` and `create_voucher` leave one that the account
owner may be obliged to keep.

**The classification is about destruction, not permanence, and they are not
the same thing here.** `effect: delete` marks a tool that destroys an existing
record, which is `delete_article` and nothing else. Permanence runs the other
way round: `delete_article` is the one write whose result could be recreated
exactly, while the tools sitting quietly under `--tools write` are the ones
that leave marks in someone's bookkeeping. Section 9 says so where the presets
are described, because a preset name cannot carry that distinction.

### The API has no state transitions, verified 2026-08-21

A record is created in the state it will keep, or it is not created. There is
no call that moves an existing one from one state to another, which explains
several things that otherwise look like separate quirks.

Measured by sending each of these and reading the answer, with bodies empty so
nothing could be created or changed:

| Attempt | Answer |
|---|---|
| `PUT /v1/invoices/{id}` | 404 |
| `POST /v1/invoices/{id}/finalize` | 404 |
| `PUT /v1/invoices/{id}/finalize` | 404 |
| `DELETE /v1/invoices/{id}` | 404 |
| `POST /v1/vouchers/{id}/book` | 404 |
| `PUT /v1/vouchers/{id}/status` | 404 |

- **A sales document cannot be changed, finalized or deleted after creation.**
  `?finalize=true` is a parameter on the creation, not an operation on a
  draft. A draft is edited or removed in the web app or not at all.
- **A bookkeeping voucher cannot be booked, and it cannot be parked either.**
  The API sets the status itself and refuses any request that names one:
  `voucherStatus: invalid_value`, on a POST as much as on a PUT. What a
  voucher is created as is not the caller's to decide.
- **Only an article can be deleted**, which makes `delete` the one
  irreversible effect this API offers and the only member of the
  `irreversible` preset there will be until the API grows.

This is why `policy.Effect` lists `create`, `update` and `delete` and nothing
else. `book` and `finalize` were in that vocabulary until this was measured,
and a classification naming operations the API cannot perform invites a tool
that cannot be written.

### Creating a sales document, verified 2026-08-21

Measured by posting to each type in turn. Nothing was finalized, so what the
account gained is drafts, which the web app can still delete.

**Finalizing is the account owner's decision, and the tool description says
so.** Creating a draft is a reversible convenience. Issuing a document
assigns the consecutive number and puts it into the account's numbering, and
a model doing that because it seemed helpful is the failure mode worth
naming. The rule sits in three places on purpose: in the description above
the call, in the `finalize` parameter's own description, and in the refusal a
call without `confirm` gets back — a model that reads only one of the three
still meets it.

- **Each kind insists on one thing of its own**, beyond the common body of
  `voucherDate`, `address`, `lineItems`, `totalPrice` and `taxConditions`:
  - `invoice`, `order-confirmation` and `delivery-note` want
    `shippingConditions`, and answer "The shipping conditions must not be
    null" without it.
  - `quotation` wants `expirationDate`.
  - `credit-note` wants nothing extra — a minimal body created GS0001.
  - `dunning` wants `precedingSalesVoucherId`, and it is a **query
    parameter**, refused before the body is looked at at all.
  `paymentConditions` is documented as required and is **not**: every one of
  the five went through without it, taking the account's default.
- **The date format is exact**, and stricter than `/v1/vouchers`.
  `yyyy-MM-dd'T'HH:mm:ss.SSSXXX` and nothing else: `2026-08-21`,
  `2026-08-21T00:00:00`, `2026-08-21T00:00:00.000` and
  `2026-08-21T00:00:00Z` are all refused as unparseable, while
  `2026-08-21T00:00:00.000Z` and an explicit offset both parse. The
  milliseconds are not optional. A plain date from a caller is therefore sent
  as midnight **UTC**, an instant this server can construct without knowing
  the account's timezone. Read back from a German account it reads
  `2026-08-21T02:00:00.000+02:00` — the right calendar day, which is what a
  document date means, and the voucher list normalizes it to `00:00` anyway.
- **`totalPrice` carries the currency and nothing else.** The API adds the
  document up from its lines. Stating a total here would be a figure this
  project invented, and the voucher endpoint already shows what happens when
  one disagrees.
- **A line item is one of four types.** `custom` is typed out, `material` and
  `service` quote an article by `id`, and `text` carries a name and no price
  at all — verified in one document holding a `service` line quoting a live
  article and a `text` line beside it.
- **A down payment invoice cannot be created.** It has no POST, so the tool
  does not offer the type.

### Master data, verified 2026-08-21

- **All four answer with a bare JSON list**, not with the page envelope the
  rest of the API uses. There is nothing to page and no page parameter to
  pass, so the whole list arrives on every call.
- **Two of them are long.** A live account answered with 257 countries
  (33,000 characters) and 231 posting categories (40,800). Handing either
  straight on would spend a large part of an answer's budget on rows nobody
  asked for, which is why `get_master_data` filters and caps rather than
  echoing what it received.
- **The path is the kind**, for all four. The tool still writes the mapping
  out rather than interpolating the argument, so no part of a URL is ever
  assembled from a string that has not been checked.
- **A posting category carries `type`**, `income` or `outgo` — 62 and 169 of
  the 231 — plus the group it belongs to, whether it may be split and whether
  it requires a contact, which 12 of them do. `create_voucher` needs an id
  from this list, and the type is what tells a caller which end of it to look
  at.
- The other two are as small as the account is: one payment condition and one
  print layout, both flagged as the organization's default.

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
  answers 404, so a wrong entry has to be corrected in the web app. It is
  booked as `open` the moment it is created.
- **A POST can no longer ask for a status. This one changed under us.**
  **Measured 2026-08-20:** `voucherStatus: unchecked` was accepted, and five
  vouchers created that day still sit in the test account saying so, one of
  them remarked "ueber create_voucher angelegt". **Measured again 2026-08-23:**
  the same call is refused with `voucherStatus: invalid_value`, across
  `salesinvoice`, `purchaseinvoice` and `salescreditnote`, each with a valid
  number, date, tax type and line. Three days, no change on this side.

  This is the drift section 14.1 exists for: the offline suite mocks HTTP and
  stayed green throughout, and only a live call could see it. The `unchecked`
  parameter is removed in 0.2.2 because a parameter that fails every time is
  worse than an absent one. If the API accepts it again, it can come back —
  the payload builder is the only place that would change.

  **The state itself is still reachable, just not this way.** `upload_file`
  creates a `purchaseinvoice` in `unchecked`, verified 2026-08-23 by reading
  back the voucher an upload had just made. Recording a receipt for review is
  what that endpoint is for.
- **Every voucher type requires `voucherNumber`. Measured 2026-08-23**, all
  four: without it the POST is refused with `voucherNumber: missing_entity`.
  The parameter was optional and is now required, so the schema refuses the
  call before it costs anything.
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
  voucher/voucher type", and a draft sales document with "No payment
  information for this invoice in draft" — the wording names the state.
- **`paymentStatus` is its own vocabulary, not the voucher status again.**
  **Measured 2026-08-23** by asking every voucher in the test account: the
  answers were `openRevenue` for money owed to the account and `openExpense`
  for money it owes, where the voucher list calls both of them `open` or
  `overdue`. There is no plain `open` on this side. A caller matching payment
  answers against the list vocabulary would match nothing, which is why
  `get_payments` passes the value through untouched.

### Document semantics that shape the tools

- A sales document is created as a **draft** (editable) unless
  `?finalize=true` is passed, which creates it in status **open** and makes it
  immutable through the API. The voucher number is assigned by Lexware.
- **Pursue:** `POST /v1/invoices?precedingSalesVoucherId={id}` creates a
  document following a finalized predecessor along the
  quotation → order confirmation → delivery note → invoice chain. A draft
  predecessor cannot be pursued and yields 406.
- **A draft reads in full**, verified 2026-08-21. Only the download is
  refused: `GET /v1/invoices/{id}` answers with every figure on the document
  while it is still a draft. What it does not carry is `dueDate`,
  `printLayoutId` and the `files` block, and that last absence is the reliable
  way to tell whether there is anything to download — an `open` document
  carries `files.documentFileId`, pointing at the same rendered file
  `/file` serves.
- **A document type that does not match the id is a 404**, measured on
  2026-08-21 by reading a real invoice id through `/v1/quotations`,
  `/v1/credit-notes` and `/v1/dunnings`. The answer is word for word the one
  an id that does not exist gives, so a tool cannot tell the caller which
  mistake they made.
- **PDF:** `GET /v1/{resource}/{id}/document` returns a `documentFileId` for
  the Files endpoint. Rendering is triggered when a document moves from draft
  to open. `GET /v1/{resource}/{id}/file` downloads the binary directly and
  honours the `Accept` header, so an XRechnung can be fetched as XML or PDF
  while ZUGFeRD and plain documents are PDF only.
- **Deeplinks:** `{appbaseurl}/permalink/{resource}/view/{id}` and `/edit/{id}`,
  with the exceptions measured in section 5. The app base URL stays
  configuration rather than a constant, even though `https://app.lexware.de`
  is now confirmed.

## 6. Transport and runtime

- **0.1.0 is stdio only.** `MCPServer.run()` with the default stdio
  transport, launched as a subprocess by the client. This is the entire
  transport surface of the first releases, by explicit decision.
- **0.2.0 adds HTTP** (`--transport streamable-http` / `sse`) with `--host`,
  `--port`, `--path` and `--allowed-hosts`, in `transport.py`. **The bearer
  token is required, not offered**: an HTTP transport without
  `LXO_MCP_BEARER_TOKEN` refuses to start, because anyone who can reach the
  port can otherwise spend the account owner's credentials. It is one shared
  secret compared in constant time — the server speaks for one account and has
  no user to authorize, so an OAuth flow would be machinery for a case that
  does not exist. The SDK's DNS-rebinding `Host`/`Origin` guard sits on top of
  it, with the loopback names always kept and `--allowed-hosts` adding a
  container or proxy name to them. There is no `--allowed-origins`: an origin
  is derived from each allowed host, which is the only shape that has come up.

  Neither guard makes the port safe on a network. They make it survivable on a
  machine shared with other processes, which is what a container published on
  a loopback port is. **`--host` and `--port` serve whichever of the two
  listening things this process is**, the transport or the configuration
  interface of section 7.1, since a process is never both.
- **A changed settings file ends the process** when
  `LXO_MCP_EXIT_ON_CONFIG_CHANGE` says so, which the image sets and nothing
  else does. Settings are read once, at startup: the key goes into a
  long-lived client and the one rate limiter of section 10.1 hangs off it, so
  rebuilding that in place would mean moving state between two clients.
  Ending instead hands the problem to whatever started the process, and a
  fresh one reads everything again - which is what lets a key saved in a
  browser reach a running server. Off by default, because ending is the whole
  of it where nothing restarts it.

  The watch compares a **hash of the content**, not a timestamp: the
  configuration interface rewrites the whole file on every save, changed or
  not. Two further rules were bought with defects. The baseline is taken
  *after* a generated bearer token has been written, or the process would
  restart on its own first act. And **only a value that two reads in a row
  agree on counts as a state at all**, at both ends of the comparison: a save
  truncates before it writes, so a poll landing inside one reads an empty
  file, and a watch that started during a save would otherwise hold that
  emptiness as its baseline and end the process over the file coming back.
  CI found it, as a rewrite of identical content ending the process for
  nothing - a race that needs a loaded machine, which a developer's is not.
- **stdio is sacred.** stdout carries the JSON-RPC stream. Library and server
  code never `print()` to stdout, all logging goes to stderr
  (`logging.basicConfig(stream=sys.stderr)`).
- **CLI flags:** `--version`, `--log-level`, `--tools`, `--tools-file` and
  `--env-file` today, plus the transport flags when HTTP arrives. `--mode` and
  `--download-dir` were planned here and never built: the mode is gone with
  the tier of section 9.1, and the download directory stayed an environment
  setting because a client spawns the server and passes no arguments.
- **One `.env` applies, and the environment beats it.** A setting resolves as
  that one file, then the real environment, which has the last word - the
  order Docker and uvicorn use, and what lets a client override one value
  without rewriting a file. **The files themselves do not combine**, since
  2026-08-23: they used to merge key by key, so a value could arrive from a
  file nobody had named and no page could sensibly report where it came from.

  **Half of that was a defect rather than a decision.** `--env-file` was
  documented as naming the file "instead of looking for one" from the day it
  was added, in its own help text, in the epilog and in the table below, and
  the code read it *after* every file the search found. So a flag whose whole
  purpose was to make one client entry self-contained did not isolate
  anything: a setting the named file omitted was still answered by the
  machine. It now replaces the search, exactly as `--tools-file` always did.

  The other half is a decision: the search takes the highest candidate that
  exists rather than layering them, so both configuration files follow one
  rule and "which file is this value from" has one answer. The environment
  stays a separate layer because the container depends on it: the transport
  settings arrive as real variables while the key lives in the mounted file.
  `--log-level` and `--tools-file` are the two flags that outrank the
  environment, because each is a decision about this one run. `--tools` and
  `--version` are actions rather than settings and have no equivalent at all.
- **Entry points:** `python -m benethos_lexware_office_mcp` or the
  `benethos-lexware-office-mcp` console script.
- **Python:** 3.11 to 3.14, all in the CI matrix.
- **3.14 changed how annotations reach a schema, measured 2026-08-22.** One
  parameter carries a description built at startup, because the default it
  states is configurable, and the finished annotation is attached after the
  definition - `from __future__ import annotations` would otherwise turn it
  into source text the SDK evaluates in module scope, where the per-process
  value does not exist. Up to 3.13 the wrapper `classify` returns and the
  function it wraps shared one annotations dictionary, so editing one reached
  the other, which is the function `inspect.signature` arrives at. Under PEP
  649 they no longer do: annotations are computed on demand from
  `__annotate__`, the wrapper materializes a dictionary of its own, and the
  original goes on answering from its source text. Both are set now, by
  replacing the dictionary rather than editing it, which drops `__annotate__`
  and leaves one answer for every reader. The offline suite is identical on
  every version and caught none of it - the matrix did.

## 7. Configuration

| Env var | Meaning | Default |
|---|---|---|
| `LXO_MCP_API_KEY` | Lexware Office API key. Required. | — |
| — | `--env-file` names the `.env` rather than searching for one, and nothing else is read: naming a file replaces the search exactly as `--tools-file` does. The real environment still wins over it, the order Docker and uvicorn use, so a client can override one value without editing the file. A path that does not exist ends the process rather than falling back to the search: starting anyway would mean behaving in a way the command line appears to rule out. | search |
| `LXO_MCP_BASE_URL` | API base URL, for tests and sandboxes. | `https://api.lexware.io` |
| `LXO_MCP_APP_BASE_URL` | Web app base used to build deeplinks. | `https://app.lexware.de` |
| `LXO_MCP_TOOL_POLICY` | The per-tool policy file, see section 9.2. Without it the file is searched the same way the `.env` is, so a `config/tools.json` in a checkout overrides an installed one. | `tools.json`, resolved |
| `LXO_MCP_DOWNLOAD_DIR` | Where downloaded documents are written. | user cache dir |
| `LXO_MCP_PDF_PAGES` | Pages of a PDF `read_download` renders when the call does not say. Deliberately not named after a page size: `LXO_MCP_PAGE_SIZE` counts rows of a search result, this counts sheets of a document, and one answering for the other would be a quiet mistake. No upstream ceiling exists to derive a maximum from, and a caller overrides it per call anyway. | `10` |
| `LXO_MCP_TIMEOUT` | HTTP timeout in seconds. | `30` |
| `LXO_MCP_RATE` | Token bucket refill, requests per second, global. | `1.5` |
| `LXO_MCP_BURST` | Token bucket capacity. Upstream holds 4, measured. | `2` |
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
The settings sample, which is committed and ships inside the package, holds
no key.

### 7.1 The configuration interface

`benethos-lexware-office-mcp setup` serves three pages on `127.0.0.1` and
opens a browser. It writes the same `.env` and `tools.json` the command line does,
so the two are interchangeable and neither owns the files.

**It is never part of the MCP server.** That process speaks JSON-RPC over
stdio and stdout belongs to the protocol. This is a separate command, started
by a person, that stops when they are done. The two share their configuration
modules and nothing else.

**Loopback only, with no option to bind anything else.** The pages have no
login, which is defensible exactly as long as they cannot be reached from
another machine — so the choice is refused rather than defaulted. Every
state-changing request is guarded twice, because a page in another tab must
not be able to rewrite credentials or permissions: the `Origin` or `Referer`
has to be loopback, and a random token from a `SameSite=Strict` cookie has to
come back in the form.

**The pages are German.** This is the only surface a person reads, and
Lexware Office is sold for German companies only — its own help centre rules
out an Austrian or Swiss company as the account holder, so a language switch
would be machinery for a case that does not exist. Code, comments and
docstrings stay English, and so do the messages `config.py` raises: those are
quoted into the page rather than translated, because a German paraphrase
would be a second copy of a rule that lives in the code.

| Page | What it answers |
|---|---|
| Overview (`Übersicht`) | Which files are in effect, what every setting resolves to and **where it came from**, whether each file exists yet, how many tools are on and what they cost. A connection test on request, never on load. |
| Credentials (`Zugangsdaten`) | The API key, checked against the API before it is written unless that is declined, and the settings that are not secret, validated by `load_settings` itself so the page cannot accept something the server would refuse. |
| Permissions (`Rechte`) | One checkbox per tool, grouped by domain, with presets, the profiles, and what each tool costs in context. The policy file can be downloaded and read back from here. |

**Both processes fix their files when they start, and never move them.** The
server pins its policy file in `build_server`, the interface pins its own in
`Installation`. The search of section 7 can answer differently the moment a
file appears somewhere, and a process that quietly changed which permissions
it enforces — or edits — is the harder one to reason about. Deleting the
pinned file therefore disables everything rather than promoting the next
candidate, which is the safer of the two failures. What still takes effect
without a restart is the *content* of that file, read fresh on every question:
only its identity is fixed.

**The two can still disagree, and only one direction can fix it from here.**
A client usually starts the server with `--env-file` and `--tools-file`, and
`setup` is started separately and cannot see those arguments. So the overview
prints the `"args"` entry that would make the client match the files this
interface holds, and names the other way round as well — starting `setup`
with the same arguments.

**Five answers to "where did this value come from", not three.** A real
environment variable, the command line for the one setting it can name, the
`.env` this interface writes to, the search itself for a policy file nobody
named, and the built-in default. The fourth exists because a resolved path is
not a default.

There used to be a sixth — *another* `.env` the search also read — and it went
away with the merge on 2026-08-23. One file applies now, so a neighbouring one
cannot supply a value here. What replaced it is a statement about the whole
file rather than about a value: when this interface is editing a `.env` that a
server would not read, the overview says so beside the paths, because saving
would otherwise report success for work that never reaches the server.

**With no policy file the boxes open on read-only.** A blank form is a poor
starting point for a decision, and the alternative — every box empty — reads
as an invitation to tick things at random rather than as a proposal. It
changes nothing about section 9.2: no file still means no tools, and nothing
is written until somebody saves. Ticks that do not describe the file are
labelled as such at the top of the page, which is the condition under which
showing them is honest. Once a file exists the boxes follow it, including a
file that deliberately enables nothing.

**What a tool costs is shown next to it.** Section 8 measures the tool list at
around 2,032 characters per tool, sent on every request for the life of the
server. The permissions page puts that number on each row and totals it live,
because switching a tool on is a budget decision as well as a permission one
and nothing else in the project makes that visible.

**The marks are explained on the page, not in a tooltip.** Each row carries
what the tool does — `lesend`, `schreibend · create`, `schreibend · delete` —
and, where it applies, what becomes of what it writes: `nur App` for a record
only the web app deletes, `nur App · Buchhaltung` for one that enters the
books and can be bound later. A legend above the groups says what each of
those means, because a tooltip is a poor place for the one distinction this
page exists to make.

**Neither permanence mark claims a record is gone forever, or bound now.**
The wording here said `bleibt dauerhaft` on all five, which was wrong twice
over: the web app deletes most of it, and nothing is festgeschrieben at the
moment it is created. The legend now says that outright and names the four
things that do bind a record. Worth noticing for its own sake — the same
overstatement was in the tool descriptions until 2026-08-21 and was corrected
there, then written again here from memory rather than from section 5.

**Creating a profile and overwriting one are two buttons, not one.** A name
that is already taken is refused rather than silently replacing what is
there, and the match ignores case and spacing: "nur lesend" beside "Nur
lesend" is one profile to everybody except a dictionary, and the list sorts
case-insensitively, so the two would sit next to each other looking
identical. Replacing a profile is done by selecting it and pressing the
button that says so.

**Profiles are a convenience, never a second policy.** A profile is a named
list of enabled tool names, stored in `tool_profiles.json` beside the policy
file it belongs to. Loading one fills in the checkboxes and stops there — the
file is written when a person presses save, by the code that writes any other
change. Two files with a say in what may be asked of a live accounting system
would contradict section 9.2, which has one.

A profile also records **which tools existed when it was written**. Without
that, a tool that is off because somebody switched it off looks exactly like
a tool that is off because it did not exist yet, and only the second is worth
mentioning when a profile is loaded. A profile that never recorded it — one
written by hand — says nothing rather than announcing every omission.

**Timestamps carry microseconds and a UTC offset**, in profiles and on the
export alike. The offset because a bundle is made to travel and two local
times from two zones would order wrongly. Microseconds because that is what
`datetime` holds — and because nanoseconds would be decoration: measured on
2026-08-21, 200,000 consecutive `time.time_ns()` calls returned **nine**
distinct values, so the wall clock behind them advances about once a
millisecond, and Windows moves that resolution around depending on what else
is running. Six digits of clock beats six digits of clock and three of
padding, because somebody eventually relies on the difference.

**One policy file can be carried to another installation, and nothing else
can.** The download is the file itself, in the shape `tools.json` already
has: one flag per tool, no wrapper, no format version. So it can be dropped
into another installation's config directory or named with `--tools-file`,
and a file written by `--tools` reads here — one format for one thing, rather
than a second one wrapping it.

**Reading one follows the rule `--tools sync` follows.** A tool the file does
not name is off, which is what an unmentioned tool means everywhere else in
this project, so a file written before a tool existed leaves that tool
switched off rather than guessing. How many those are is said out loud, and a
name that is no longer a tool is reported and dropped. Reading only fills the
checkboxes: `tools.json` is written on save, as it is for a loaded profile,
which keeps one rule for how that file comes to be written.

**Two wider formats were built first and taken out again on 2026-08-22.** The
first carried the settings, the permissions and the profiles together, and
the settings were the problem: `LXO_MCP_TOOL_POLICY` and
`LXO_MCP_DOWNLOAD_DIR` are absolute paths describing one machine, and an
import writing the first would have pointed the target installation at a
policy file that does not exist there — no tools at all, immediately after an
import that appeared to grant some. The second carried the profiles alone,
which was safe but answered a question nobody had: a profile is a convenience
of this interface, while the policy file is the thing an installation
actually runs on.

No format carried the API key, and this one has nowhere to put a setting at
all.

## 8. Tools

Tool count is kept deliberately low. Descriptions and schemas are sent on
every request, so a wide surface is paid for continuously. Related endpoints
are therefore grouped behind one tool with an enum parameter rather than
exposed one tool per path.

**What the tool list actually costs, measured 2026-08-21, again on
2026-08-22 with the annotations below, and again on 2026-08-23 after
`create_voucher` lost a parameter that could not work.** Serialized as the
compact JSON a `tools/list` answer is, twenty-five tools come to **52,091
characters**, around 2,084 each. Roughly 13,000 to 15,000 tokens, estimated at
3.2 to 3.8 characters per token rather than counted with a tokenizer.

| Part | Characters | Share |
|---|---|---|
| Input schemas | 33,274 | 64% |
| Tool descriptions, the part under a ceiling | 10,965 | 21% |
| Output schemas | 4,340 | 8% |
| Annotations | 1,115 | 2% |
| Names, titles and the rest | ~2,092 | 4% |

The figures move whenever a description is touched, so they carry a date
rather than a promise. `CLAUDE.md` holds the one-liner that measures them.

**Annotations, and why they cost what they cost.** Every tool carries the MCP
hints, derived in `tools/_base.py` from what `@classify` already recorded
rather than written out per tool: a tool cannot then say one thing to the
policy file and another to a client. `read_only_hint` follows `access`.
`destructive_hint` is false for a create, which only adds, and true for an
update or a delete - this API replaces a record rather than patching it.
`idempotent_hint` is the same distinction seen from the other side: a second
create is a second record, since there is no idempotency key (question 2,
section 16), while a repeated update spends a version it no longer has and a
repeated delete finds nothing left, so neither changes the books twice.

`open_world_hint` is the one stated only where it differs from the protocol's
assumption, which is `get_deeplink` and `read_download` - the two tools that
answer without reaching the API. Stating it on the other twenty-three would
have cost 483 characters to repeat a default. The three hints above are
stated either way, including where they match the default: a client that does
not fill defaults in would otherwise read "this deletes things" as nothing at
all, and that is not a saving worth 900 characters.

These are hints, and the protocol says a client must not make tool-use
decisions on them from a server it does not trust. Nothing here enforces
anything - the policy file of section 9 does that, twice, and neither gate
consults an annotation.

Two things follow, and neither was obvious before the measurement.

**The 700-character ceiling governs a fifth of the cost.** Of the 33,469
characters of input schema, 13,264 are prose from `Field(description=...)` and
the remaining 20,205 are structure the schema generator emits: types,
defaults, `$defs`, `anyOf` branches and generated titles. Parameter prose is
under no ceiling at all and is not visible while writing a docstring, which is
where it should be watched: `create_voucher` spends 1,744 characters on
seventeen parameter descriptions, nearly four times its own description.

**The six structured tools carry half of it.** `create_sales_document`
(5,139), `create_voucher` (4,334), `update_contact` (3,965), `create_contact`
(3,907), `search_vouchers` (3,378) and `update_voucher` (3,359) come to 48% of
the total between them. Every one of them takes a record's worth of arguments,
and the largest takes a nested model of line items on top. The policy file of
section 9 is therefore also a context lever, not only a permission one: a
`read-only` installation sends 22,620 characters, a little under half.

The numbers move whenever a description does, so they are a measurement with
a date on it rather than a budget. What is stable is the shape: schemas cost
three times what descriptions cost, and the tools that take structured
arguments cost three to four times what the simple ones do.

### Read tools

| Tool | Inputs | Output | Calls |
|---|---|---|---|
| `get_profile` | — | `{organizationId, companyName, connectionId, taxType, smallBusiness, businessFeatures}`. Verified against a live account 2026-08-20. The `created` block the API also returns is **dropped**: it carries the setting-up user's email address, which the tool does not need and which has no business reaching a language model. Doubles as the connection check. | 1 |
| `search_contacts` | `name`, `email`, `number`, `role` (customer/vendor/any), `page`, `size` | `{contacts: [{id, version, name, type, roles, customerNumber, vendorNumber, email, phone, archived?}], page: {number, size, totalElements, totalPages, last}}`. The filter is named `name` rather than `query`, because it matches names only and calling it a query would promise a full-text search the API does not offer. `name` and `email` carry the API's three-character minimum in the schema. The response's `sort` block is dropped, and `archived` appears only when true. Built and verified against live records 2026-08-20. | 1 |
| `get_contact` | `contact_id` | the full contact including addresses, roles and `version`, with `organizationId` dropped: it is identical on every record and `get_profile` already answers it. A drop-list, not an allow-list, so a field added upstream still surfaces. Built and verified against live records 2026-08-20. | 1 |
| `search_articles` | `article_number`, `gtin`, `article_type`, `page`, `size` | `{articles: [{id, version, title, articleNumber, type, unitName, price, archived?}], page: {...}}`. **No `query`.** It was specified here and dropped on 2026-08-21 when the endpoint turned out to filter on three fields and to ignore every other parameter silently, so a text search would have answered with the whole catalogue while looking like it had searched. Both filters match in full. `description` and `note` are dropped from a row and kept by `get_article`. There is no `currency`: an article's price block carries none. Built and verified live 2026-08-21. | 1 |
| `get_article` | `article_id` | the article in full, `organizationId` dropped, including the price block and `version`. The block carries a net and a gross figure with the tax rate between them and `leadingPrice` saying which of the two was entered - dropping either half would leave a number that cannot be checked. Built and verified live 2026-08-21. | 1 |
| `search_vouchers` | `voucher_type`, `voucher_status`, `contact_id`, `date_from`, `date_to`, `only_open`, `only_overdue`, `archived`, `sort`, `page`, `size` | `{vouchers: [{id, voucherType, voucherStatus, voucherNumber, voucherDate, dueDate, contactName, totalAmount, openAmount, currency, archived?}], page: {...}}`. The central discovery tool, and the only way to find a document at all. `voucher_type` and `voucher_status` default to `any` because the API requires them, so the tool always sends both. `createdDate` and `updatedDate` are dropped from the rows: they say when somebody typed it in, not when the document is dated. Built and verified live 2026-08-20. | 1 |
| `get_sales_document` | `document_type` (invoice, quotation, credit-note, order-confirmation, delivery-note, dunning, down-payment-invoice), `document_id` | the document as the API holds it: recipient, line items with their unit prices, totals, tax breakdown, payment and shipping conditions, and `version`. A drop-list of one, `organizationId`, rather than an allow-list: the seven types differ field by field and an allow-list would swallow whatever makes a dunning a dunning. Built and verified live 2026-08-21, in both `open` and `draft`. | 1 |
| `get_voucher` | `voucher_id` **or** `voucher_number` | the bookkeeping voucher with its lines, posting categories, tax type and `version`. Takes a number as well as an id because `voucherlist` cannot filter by number and `/v1/vouchers?voucherNumber=` is the only lookup the API offers. A number matching several vouchers is refused with their ids rather than guessed at. Built and verified live 2026-08-20. | 1 |
| `get_payments` | `voucher_id` | `{openAmount, paymentStatus, currency, voucherType, voucherStatus, paymentItems}`. An `openAmount` of 0 is the answer to "is it settled" and is reported, not dropped. Refused by the API for a voucher that is not booked yet. Built and verified live 2026-08-20. | 1 |
| `get_recurring_templates` | `template_id`, `sort`, `page`, `size` | with an id the template itself, without one `{templates: [...], page: {...}}`. One tool rather than two because there is nothing to search by: the endpoint takes paging and a `sort` and ignores anything else, and a second tool would have cost a second description for the same call. `sort` is a `Literal` of the four dates the API named when it refused `title`, each way round. Nothing but `organizationId` is dropped, because the API already sends a shorter row in a list than it sends for one record — see section 5, which is also why the tool says to read by id for the lines. Built and verified live 2026-08-21. | 1 |
| `get_master_data` | `kind` (countries, payment-conditions, posting-categories, print-layouts), `search`, `limit` | `{kind, total, matched?, shown, entries}`. Nothing is dropped from a row: every field of these four decides something, including a `contactRequired` of false. What is trimmed is the number of rows, because two of the lists run into the hundreds and none of them pages, so the whole list arrives whatever the caller wanted. `search` matches every text a row carries except its id, which is one parameter instead of one per field and narrows by name, group, country code or category type alike. `matched` appears only when a search was given, where it would otherwise restate `total`. Built and verified live 2026-08-21. | 1 |
| `download_document` | `document_type`, `document_id`, `file_format` (pdf/xml) | `{path, mimeType, size}`. Renamed from the planned `get_document_pdf`, which promised a format the tool does not always fetch, and reduced to **one** behaviour and **one** call: it downloads and saves. The planned variant that returned a `documentFileId` without saving was dropped, because the only thing a caller could do with that id is hand it to `download_file` — the same work through a second tool, and the two were measured on 2026-08-21 to return the same bytes. Verified live the same day against a real invoice, in both the rendered and the draft case. | 1 |
| `download_file` | `file_id`, `file_format` (pdf/xml) | `{path, uri, mimeType, size}` plus a `resource_link` block. No deeplink: a download reports where the bytes are, and a link into the web app is `get_deeplink`'s answer to a different question. The two were joined until 2026-08-21, which is how a link to a route that does not exist rode along with a download that worked. The bytes stay out of the answer and are fetched by the client from `uri` when it wants them, see section 13. An existing file is never replaced. Built and verified live 2026-08-20. | 1 |
| `read_download` | `uri` | `{uri, mimeType, size, deliveredAs, pages?, pagesShown?}` plus the content itself. The fallback for a client that does not follow resource links: it puts a downloaded file into the answer as text, as an image, as **rendered page images for a PDF**, or as an embedded binary, depending on what the file is. Refuses anything outside `lexware://download/`, so it is not a file reader, and refuses above 5 MiB. Built 2026-08-20 after Claude Desktop turned out not to resolve resource links. | 0 |
| `get_deeplink` | `target`, `target_id`, `action` (view/edit) | `{url}`. `target` reaches past the sales documents to contacts and vouchers, since the permalink shape is the same for them and the extra entries cost nothing. A stored file is **not** a target and a contact ignores `edit`, both because the app answers those with a 404, see section 5. Built 2026-08-20, corrected against the live app 2026-08-21. | 0 |

### Write tools

| Tool | Inputs | Calls | Notes |
|---|---|---|---|
| `create_contact` | `kind` (company/person), `name`, `roles`, `first_name`, `salutation`, `email`, `phone`, `billing_address`, `shipping_address`, `vat_registration_id`, `tax_number`, `note` | 1 | Returns the id and version the API answers with, not the record. The customer and vendor numbers are assigned by Lexware, so they are only visible after reading the contact back. The parameters are flat rather than the API's nested object because the API itself allows only one billing address, one shipping address and one entry per email or phone type, so flat loses nothing. Addresses are the exception and stay structured, since they have five fields each. Built 2026-08-20. |
| `update_contact` | `contact_id`, `version`, then the same fields, all optional | 2 | Reads the record and lays the given fields on top, because a PUT replaces rather than patches. The `version` the caller passes is checked against the record before anything is sent, so a stale one costs one read and no write. Built 2026-08-20. |

| Tool | Notes |
|---|---|
| `create_contact` / `update_contact` | **Built 2026-08-20**, see the read table above for what they cost. |
| `create_article` / `update_article` | **Built 2026-08-21.** `create_article` takes the four fields the API insists on - title, type, unit and a price with its tax rate - plus a side, `NET` or `GROSS`, saying which figure the price is. The other is computed upstream rather than here: an amount this project derived and sent would be a number nobody checked. `update_article` reads, merges and replaces like `update_contact`, and drops the side that is no longer authoritative so a new net price is never sent beside a stale gross one. |
| `delete_article` | **Built 2026-08-21**, and the first tool in the whole server carrying an irreversible effect. Takes `confirm: true` and sends nothing without it. The record is removed rather than archived - verified live: 204, then 404 on the same id. |
| `create_voucher` / `update_voucher` | **Built 2026-08-20.** `create_voucher` takes the type, date, tax type and lines, and adds the totals up from the lines unless the caller states them, which is arithmetic the API insists on rather than a number being invented. The document number is required, and no status can be asked for - both measured 2026-08-23, see section 5. `update_voucher` reads, merges and replaces like `update_contact`, and additionally strips the fields a voucher refuses on the way back in. Neither can be undone: the API cannot delete a voucher. |
| `create_sales_document` | **Built 2026-08-21.** Six types, `down-payment-invoice` left out because it has no POST. The per-type requirement of section 5 is checked here rather than upstream, so a missing `shipping_date` costs no request and the message names the field. Addresses by `contact_id` only: a one-time address would add a nested model to the largest schema in the server for a case `create_contact` already covers. `finalize` needs `confirm` beside it. Line items carry the price on the side the document's `tax_type` names, and the totals are left to the API. |
| `attach_file_to_voucher` | **Built 2026-08-21.** Hangs a file on a voucher that already exists, which `upload_file` cannot do: that one creates a voucher per file. Same validation, same 5 MiB ceiling, same four types, and the answer is the file id alone. Neither the attachment nor a wrongly created voucher can be removed, so the description names the neighbouring tool rather than leaving the caller to find the difference. |
| `upload_file` | **Built 2026-08-20.** Takes a path on the machine the server runs on. Accepts PDF, JPEG, PNG and XML, and refuses a missing file, any other extension and anything above 5 MiB before spending a request. The answer carries a `voucherId` as well as a file id, because uploading creates a voucher, and the docstring says so where a caller will read it. |

### Irreversible tools

`delete_article` is **built**, and is what the `confirm: true` convention was
written for: the argument defaults to false, nothing is sent without it, and
the refusal says what would have happened. `create_sales_document` takes the
same argument for `finalize`, which is the other irreversible thing that can
be asked for here.

**And that is all of them.** Booking a voucher was listed here as a third,
and it is not possible: the API has no state transitions, measured 2026-08-21
and written up in section 5. Nothing can be booked, finalized or voided after
the fact, so `delete_article` is the whole of this group rather than its first
instalment.

It is also the only tool for which the `irreversible` preset differs from
`write`. Until it existed the two wrote the same twenty-one flags, and the
third step of the command line was a promise about tools that did not exist
yet.

### Parameter conventions

- Every parameter gets an `Annotated[type, Field(description=...)]`, numeric
  limits get `ge`/`le` bounds, enums are real `Literal` types so the client can
  only send a valid value.
- The docstring is the tool description the model reads, and it is sent on
  **every** request for the life of the server. It carries only what changes a
  caller's decision: what the tool does, what it costs in API calls, when to
  use it instead of a neighbouring tool, what to fetch first (the `version`
  before an update), how to read a result the schema does not explain, and
  what the API cannot take back - which is not the same as what cannot be
  undone, since the web app usually has a way and this server can only speak
  for the interface it uses. Design reasoning stays in this document, where it is
  paid for once. **Under 700 characters**, which is a ceiling a rewrite into
  explanation will cross rather than a limit on wording — the fix when one
  grows past it is to move a paragraph here. Not enforced by a test on
  purpose: a character count cannot judge whether a sentence earns its place,
  and making it a gate would turn the judgement into a number to be gamed.
- IDs are Lexware UUIDs. No tool invents, guesses or assembles an ID. A caller
  that has only a name uses `search_contacts` or `search_vouchers` first.

## 9. Permission model

**One file decides, tool by tool.** There is no level above it and no group
beside it. A tool is enabled or it is not, and the answer is in the same place
for all of them.

### 9.1 Why the tier was removed

The first design had a coarse `LXO_MCP_MODE` of `read`, `write` and `full`
above the file, as a ceiling an operator could pin. It was dropped on
2026-08-21, and the reasoning is worth keeping because the trade is real.

**What it cost.** A level is a bundle, and a bundle is always wrong for
somebody: raising it to `write` so a quotation could be drafted also handed
over receipt upload and voucher creation. Two gates also meant two places to
look when a tool was missing, and the answer "it is in the file but the tier
withholds it" is a confusing one to arrive at.

**What was given up.** A deployment can no longer be pinned read-only
independently of any file. Whoever can write the policy file can enable
anything in it. Where that matters — a container, a shared machine — the file
is the thing to protect, with the permissions of the filesystem rather than
with a second mechanism inside this server.

**What replaced the safety.** The default moved from "read-only" to
**nothing**: a tool the file does not name is off, and an installation without
a file offers no tools at all. The old default let a fresh installation read a
live accounting system without anybody having decided that. This one does not.

### 9.2 The policy

**The file is the truth.** `tools.json`, one flag per tool, never in the
repository:

```json
{ "get_profile": true, "search_vouchers": true, "create_voucher": false }
```

It is found by `config.resolve_config_file`, the same search the `.env`
goes through: the per-user directory, then `config/` of a checkout, then the
working directory, last one found winning. One order for every configuration
file there is, because two files searched two ways would be two rules to
remember and the one remembered wrongly would be the one holding the
permissions. `LXO_MCP_TOOL_POLICY` overrides the search, and `--tools-file`
overrides that. A tool the file does not mention is **off**: the file is the
only gate there is, so anything it fails to say has to be a no, and a tool
arriving with an upgrade waits to be enabled rather than appearing on its own.
Writing a flag for every known tool rather than only for the exceptions is
what makes the file readable without knowing that rule.

**The classification computes a file, it is never consulted instead of one.**
`policy.preset` turns the classification into a complete set of flags —
`read-only`, `write` and `irreversible`, each containing the last. It is
written to disk and the disk is what is read afterwards, so the file always
says exactly what is allowed, tool by tool. A preset is a way of writing many
flags at once and nothing more.

**Where the classification comes from.** The `@classify` decorator records
`access`, `domain`, `effect` and `permanence` as the tool is defined, so
`policy.known_tools()` cannot drift away from the code it describes — which a
table maintained by hand somewhere else eventually would. It is **metadata,
not permission**: nothing reads it when a call arrives. A script selects on
`access`, an interface groups by `domain`, and both then write flags.

**`write` does not mean undoable, and the preset names cannot say so.** The
`irreversible` step covers `delete`, the one effect this API offers that
destroys a record, and `delete_article` is the one tool carrying it. Section 5
has the full inventory of what each write leaves behind, and it runs the other
way round from the preset names: the tool marked irreversible is the only one
whose result could be recreated exactly. What the step does not cover is a
creation that cannot be taken back, and there are five of those. They stay
under `write`, because the alternative is to put ordinary bookkeeping behind
a step named after deletion, and a preset that overstates its danger gets
ignored rather than read.

**`permanence` is the axis that does say so**, added on 2026-08-21 when the
configuration interface needed to warn about it and found the classification
had no word for it. Three values, and the difference between the last two is
the point:

| Value | Meaning | Tools |
|---|---|---|
| `""` | the API can remove it again | everything else |
| `"app"` | no call here removes it, but the web app deletes one without ceremony | `create_contact` |
| `"books"` | no call here removes it, and it is a bookkeeping record, so the web app deletes it only while nothing has bound it | `create_voucher`, `create_sales_document`, `upload_file`, `attach_file_to_voucher` |

A missing route is a gap a later API version could close. A bookkeeping
record is different in kind: from the Festschreibung on, § 146 AO wants it
unchanged and the remedy is a Storno rather than a deletion, whatever the API
grows.

**Nothing this API creates is bound at the moment it is created**, and the
second value was called `"law"` until 2026-08-22, which said otherwise. Two
things in this repository disprove it: `update_voucher` works, which a
festgeschrieben record would not allow, and `create_sales_document` produces
a draft unless the call asks for `finalize`. What the mark records is that
such a record *can become* permanent — through Festschreibung, an assigned
payment, a follow-on document or an export — while a contact never does.

Like the rest of the classification this decides nothing. It is there so that
an interface offering to switch these tools on can say which kind of
permanent it means, and so that the command line and the README can say it in
words.

**The domain is the module the tool lives in**, for every tool without
exception: `articles`, `contacts`, `diagnostics`, `files`, `master_data`,
`sales_documents`, `vouchers`. A tool that points at a sales document while
doing something else — `download_document` fetches its PDF, `get_deeplink`
builds a link to it — is grouped by what it does rather than by what it names,
because that is where a reader looks for it and where the code keeps it.
Anything else would need a second rule about which of the two wins.

**Enforcement happens twice, as defence in depth.** A disabled tool is left
out of the list, so it never reaches the model and costs no tokens, and a call
to one is refused by name with the file that would enable it. The listing
filter is in `PolicyServer`, one place for every tool there is, so a tool
added to a module later cannot quietly escape it.

**A server that offers nothing says so on stderr**, naming the file and the
command that writes one. From the client an empty tool list is
indistinguishable from a broken server, and the difference matters.

**Changing it while the server runs.** The file is read fresh on every
question rather than cached, so an edit takes effect on the next request — a
few hundred bytes of JSON is cheaper than a copy that can be wrong.
Enforcement is therefore always current. What is *shown* lags until the client
asks again — so it is told to. `PolicyServer` announces
`tools.listChanged: true`, binding the `NotificationOptions` once in its
constructor so that stdio and both HTTP transports are covered, and a watcher
sends `notifications/tools/list_changed` when the set of enabled tools
actually differs.

Three decisions in that watcher are worth stating:

- **It compares the visible set, not the file.** The configuration interface
  rewrites the whole policy file on every save, so a timestamp would announce
  a change on every click that changed nothing.
- **It starts when a session appears, not at construction.** Without a client
  there is nobody to tell, and a task polling in every process that merely
  builds a server — the test suite, `--tools show` — is a nuisance nobody
  asked for. The session comes from `_handle_list_tools`, the private hook,
  because that is the only place it is offered for a listing: the public
  `list_tools()` is called without it.
- **It notifies every session it has seen** and drops the ones that fail,
  which is one client over stdio and will be several over HTTP.

**Claude Desktop acts on it, verified 2026-08-22.** With the capability
announced, a permission changed in the configuration interface reached the
running client without restarting it. That is the whole point of the
exercise, and it was worth measuring rather than assuming: the same
notification sent *without* announcing the capability had never been shown to
do anything, see section 13.

**Nothing depends on it even so.** A client that ignores the notification, or
never receives one, still cannot call a tool that has been switched off: the
file is read again on every call. The notification saves a restart, it does
not enforce anything.

**Both directions take effect without a restart**, which is why the filter
sits in `PolicyServer.list_tools` rather than in `register_tool`. Every tool
is registered whatever the file says, and the file is read as the list is
built and again on every call.

It was the other way round until 2026-08-21, and the asymmetry that produced -
switching a tool off worked at once, switching one on needed the process
restarted - was a consequence of *where the check sat*, never a decision. It
is worth recording that it was briefly defended as one, on the grounds that
granting permission ought to be deliberate. That was a justification invented
for an accident.

What still lags is the client, which is not this server's to fix: a tool list
already fetched stays until the client asks again, and most ask once.

**What a tool declares:**

| Field | Values |
|---|---|
| `access` | `read` or `write` |
| `domain` | diagnostics, contacts, vouchers, files, and the groups still to be built |
| `effect` | write tools only: `create`, `update`, `delete` |

`ToolMeta.irreversible` is true for `delete` alone, which in this product is
not a figure of speech: what is deleted is gone, and what is created mostly
cannot be deleted at all. `book` and `finalize` were in this vocabulary until
2026-08-21, when the API turned out to have no state transitions to name them
after, see section 5. Nothing acts on it
yet. When something does it should be a separate confirmation rather than a
red label, or the flag is decoration.

The graphical interface below is the intended home for all of this, and
`sync` is what keeps a file fit for it: an interface renders one row per tool,
which is only possible while the file names every tool there is.

**Interface.** Today the command line: `--tools show` reports, `sync`
completes the file without deciding anything, and `read-only`, `write` and
`irreversible` overwrite it with that preset, each containing the last.
`--tools-file` says where to write it.

**Why `sync` is separate from the presets.** A preset overwrites, which is
right for starting a file and wrong for keeping one: an installation whose
owner has switched twelve tools off by hand loses all twelve. But a file
written before an upgrade does not mention the tools the upgrade brought, and
while those are correctly **off**, the file has stopped being a complete
picture of what exists — which is exactly what somebody reading or editing it
needs. `sync` writes the missing names in as `false` and every flag already
there back unchanged. **It cannot switch anything on**, which is the property
that makes it the one action safe to run unattended, from a post-install hook
or an upgrade script, while granting a permission stays a deliberate act. A
name in the file matching no tool is reported and not written back: it has no
effect and no decision attached to it, so keeping it would only make the file
harder to read, and dropping it in silence would leave somebody hunting for a
setting. The third
step exists separately because deleting is its own decision — reachable, but
only by naming it rather than by choosing the largest option. Everything it prints goes to stderr,
because it shares an entry point with the server and stdout carries the
JSON-RPC stream. The graphical version is the permissions page of section 7.1:
a table grouped by domain, one toggle per row, `read` and `write` marked,
irreversible effects flagged, permanent ones flagged separately, and the
connected organization shown at the top from `get_profile` — so it is never
in doubt which account the permissions being granted apply to.

**It shows what each tool costs in context, which nothing else here does.** A
tool that is on is sent to the model on every single request, description and
schemas alike, and section 8 measures that at around 2,032 characters per
tool with `create_sales_document` at more than double. The page carries a
per-row figure and a running total that follows the checkboxes, so a policy
can be chosen against a budget rather than against a guess. Characters are
what can be counted honestly — a token count would need a tokenizer for a
model this server does not know it is talking to, so the token figure beside
them is labelled as an estimate and derived from a fixed ratio.

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
pagination follow-ups and the read that an update makes before it writes.

**Parameters:** *r* is `LXO_MCP_RATE` (default `1.5` per second) and *b* is
`LXO_MCP_BURST` (default `2`). The rate sits deliberately **below** the
documented 2 per second, because the documentation says that enforcing the
limit without a buffer commonly produces 429s anyway once network jitter shifts
the arrival times. A shaper that aims exactly at the policer's threshold loses
every race the network decides.

The capacity is the more dangerous of the two. A generous local *b* would let
the server open with a burst that our own limiter considers conformant and
theirs does not — it would move the failure from our queue to their 429
without any warning that it had happened.

**Upstream *b* is 4**, measured 2026-08-21 and no longer a guess: five
concurrent requests after an idle stretch got four through and one refused,
four got four through. The idle stretch does not buy more, so the bucket is
shallow and fixed rather than a credit for quiet time.

**The default stays at `2` regardless**, and the measurement is the reason it
can stay there honestly rather than out of ignorance. The upstream limit is
**global across the account**: the web app, another integration, or a second
instance of this server all draw on the same four. A local *b* of 4 would be
conformant only while nothing else is running, which is not a property an
accounting integration should depend on. An operator who knows this server is
the only consumer can raise it to `4` and be exactly at the ceiling. `2` also
keeps the two calls of an update from being artificially separated, which was
the original reason for it. Both values are configurable, so an account that
behaves differently can be tuned without a code change, and open question 6 in
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
tell the two cases apart. **There is no idempotency key to lean on**, measured
2026-08-21 under three header names: the same POST sent twice creates two
documents every time, see open question 2. So this is not a rule waiting for
a better mechanism, it is the only correct behaviour the API allows. Instead the failure surfaces as an `UpstreamError`
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
- **Nothing this project writes ever recommends putting the key in a client's
  configuration file.** An MCP client will happily pass one through an `env`
  block, and the README showed that until 2026-08-22. It is the worse of the
  two places by some way: the file belongs to another program, which decides
  where it lives and when it rewrites it, it is readable in that client's own
  settings view, it travels to the next machine with the rest of that
  client's configuration, and it is the file people paste into a forum when
  an MCP setup will not start. The `.env` is documented here, synced by
  nothing, and written by the configuration interface without the key ever
  being displayed. Neither is a secret store, and the documentation says so
  rather than implying the `.env` is safe.
- Real tenant, organization, contact and voucher IDs never appear in versioned
  files. Documentation uses placeholders.
- **No filesystem path of the host machine is handed to the client.** Every
  message a tool returns reaches a model's context, and a path carries a user
  name and a directory layout with it while telling the caller nothing it can
  act on. A refusal names the tool and what to set, not the file. The person
  who can edit the file is at the machine, where stderr and the configuration
  interface both name it. The exception is a path the caller supplied or
  asked for — `download_file` answers with where it wrote the bytes, which is
  the point of calling it.
- Downloaded documents are real business records. They go to the download
  directory, which is gitignored, and are never committed.
- **What one installation is allowed to do is not a property of the code**,
  so `tools.json` and the `tool_profiles.json` beside it are gitignored under
  both their names — bare and under `config/`. A committed policy file would
  hand the next clone a set of permissions nobody there decided on, and a
  committed profile would describe somebody's account arrangement.
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

**Which status a stale version arrives as depends on the resource.** A
contact answers 406 naming `version`, an article answers **409**. Both end as
`ConflictError`, which is why the mapping reads the body rather than the
status alone.

No raw traceback ever reaches the client. Expected failures are `ToolError`
subclasses with concise, actionable messages.

**What a crash sends depends on the SDK version, and the floor stays at
2.0.0.** A traceback never travels on either, but on 2.0.0 an unanticipated
exception's own message does, and from 2.1 it does not. The declaration
remains `mcp>=2.0.0,<3` rather than being raised to close that: the
difference is a message this server never composed, in a path it does not
expect to reach, and narrowing what an installation may resolve to costs
more than it buys.

### 12.1 Why `ToolError` derives from the SDK's

The SDK sorts a failing tool call by the **type** of what was raised. Its own
`ToolError` means a failure the server anticipated: the message is handed to
the model and logged at INFO without a traceback. Anything else is a crash,
and from mcp 2.1.0 onward the text stays on the server while the model is told
only `Error executing tool <name>`. So the hierarchy above derives from
`mcp.server.mcpserver.exceptions.ToolError`, and without that inheritance
every sentence in the table would be written and none of them delivered.

The `ValueError` raised for an unknown preset or a rate of zero sits on the
other side of that line deliberately. It is a mistake in how the process was
configured, not an answer for the model, and withholding its text is right.

Measured 2026-09-02 over real stdio against mcp 2.1.1, upgrading from 2.0.0.
The same denial arrived as:

```
2.0.0  Error executing tool get_profile: get_profile is not enabled for this
       installation. The account owner decides that in the server's tool policy.
2.1.1  Error executing tool get_profile
```

**What the gates did and did not catch.** Twenty-one tests failed on the
bump, because they assert on the message text of what `MCPServer.call_tool`
raises, and that call re-raises through the same sorting. The suite is not
blind here. What it cannot see is anything further out: `call_tool` raises,
while a client is answered by `_handle_call_tool`, which converts. A change
to that conversion - the wire shape, the tool list, the annotations - passes
every test in this repository. Section 14.3 says how to look.

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
- **The URI is an MCP resource, registered per file.** A path only means
  something while client and server share a filesystem, which the stdio
  transport happens to give and the HTTP transport of section 6 will not. What
  holds either way is that the file is on the *server's* disk and the server is
  the one reading it, which is the shape MCP resources already have. Registered
  per file rather than behind one URI template, so each carries its own content
  type — a PDF and an XRechnung are not the same thing to a client deciding
  what to do with them.
- **The registry is filled from the download directory as the server starts**,
  not only by what the running process fetched. Measured over stdio on
  2026-08-21, the narrower version was a defect: a fresh process answered
  `resources/list` with an empty list and `resources/read` with "Unknown
  resource" for a file in its own download directory, which `read_download`
  read from disk in the same breath. The same files were reachable either way,
  so restricting the registration protected nothing and cost every URI its
  life at restart.
- **A client is told when the tool list changes, since 2026-08-22.** For
  resources it still is not, and the measurement below explains why the
  default is what it is. Measured against mcp 2.0.0 on 2026-08-21:
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

  **What that analysis missed is that `PolicyServer` is ours.** The default
  is what it is, but `create_initialization_options` takes the
  `NotificationOptions` and can be bound once in the constructor — where it
  covers stdio and both HTTP transports at a stroke, since all three call
  that same method. The conclusion drawn from the measurement, that a watcher
  would be "waste at best", followed from the flag being out of reach. It was
  not.

  So section 9.2 now describes a server that announces `tools.listChanged`
  and sends `notifications/tools/list_changed` when the set of enabled tools
  actually changes — and **Claude Desktop acts on it, measured 2026-08-22**
  over a real stdio handshake reporting `tools: {'listChanged': True}`. The
  two halves are separable and only one of them had ever been tried: sending
  the notification without announcing the capability leaves a conforming
  client free to ignore it, and whether any client did was never established.

  For **resources** the finding stands unchanged: nothing announces or sends
  anything, which is the second reason `read_download` exists, the first
  being that Claude Desktop does not follow a resource link.
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
- **`live/smoke.py` is run by hand and never collected by pytest.** Built
  2026-08-21. It takes a key from the normal configuration chain of section 7,
  refuses to start without one, calls `get_profile` first so whoever runs it
  sees which organization is about to be read, and performs **read-only**
  calls only. `pytest` does not find it because `testpaths` is `tests/` and
  this file is not in it. That was a filename until 2026-09-02: the script was
  called `smoke.py` rather than `test_smoke.py` and nothing else stood in the
  way, so a rename would have pointed CI at a live account. Both live checks
  moved to `live/` for that reason, which is the same argument as the one two
  bullets down - a directory pytest does not walk is a guarantee, a name it
  happens not to match is a convention.
- **It cannot write, structurally.** The server it builds is handed the
  `read-only` preset of section 9, so a writing tool is not merely unused in
  the script, it is absent from the server and refused if called. The script
  checks that too, on the tool list it was given. A promise that a script
  makes no writing call is worth less than a server that cannot make one.
- **A check that could not run is reported as skipped, never as passed.** An
  empty account has no article to read and no rendered document to download,
  and a live check that reported those as successes would be the same hole as
  a test that skips itself. The summary counts the three states apart.
- **It found something on its first run**, which is the argument for having
  it: `GET /v1/articles` refuses a page size below 25, alone among the list
  endpoints, and the tool's schema had allowed 1. Nothing offline could have
  caught that, because the mock answers whatever it is told to.
- **Upstream drift is invisible to CI.** The suite mocks HTTP completely, so
  it stays green through any change in Lexware's field names or response
  shapes. Only a live run catches that, and only someone holding an account
  can perform one. This is why statements about the API in this document carry
  **(to verify)** until a live call has confirmed them.
- **The open questions below could not be closed by CI**, and none of them was.
  Each was answered by a live call, or in one case by a decision not to make
  one: a question about write behaviour needs write calls against a disposable
  test account, see section 11.1, which is a deliberate act by the account
  owner rather than something automation initiates.

### 14.2 A shape is recorded, so drift can be seen rather than remembered

`smoke.py` asks whether the calls this server makes still work. That leaves a
question it cannot reach: whether the answers still look the same. Everything
null or empty is dropped on the way to the client, so a field that disappeared
upstream looks identical downstream, and a field that appeared is invisible by
construction.

`live/api_shape.py` reads every readable endpoint and writes what it saw into
a timestamped file under `live/shapes/`. Field names, JSON types, and the
values of a short list of closed vocabularies - `voucherStatus`, `taxType`,
`paymentStatus` and their neighbours, because a vocabulary that moved is drift
a type cannot show. Comparing two runs is then a `diff` rather than a reading
of the dated prose in section 5.

**What a capture may hold is a rule with a test behind it.** No id, no name,
no address, no amount, no date: those are records rather than shapes and
section 11 keeps them out of versioned files. `tests/test_api_shapes.py`
checks every capture for all four, because the files are long, they look alike
and a leak in one would survive review.

**A difference is not automatically drift.** These are the shapes of one
account, so a diff also moves when the account does: an optional field no
record happened to fill, a document type nobody had created yet. Read a diff
for what it says about the API, then check the account before concluding.

The first capture was taken 2026-09-02, covering nineteen endpoints. It found
four fields this repository had never named - `deliveryTerms`,
`organizationDefault`, `recurringTemplateId` and `userId` inside the `created`
block the profile tool drops. All four are additive and nothing reads them.
Whether they were new could not be settled, which is the argument for having
a baseline at all rather than an argument about those four fields.

### 14.3 The SDK is the second blind spot

Upstream drift is one direction a mocked suite cannot see. The other is the
layer on the near side: the MCP SDK, which sits between this code and the
client. The suite calls `MCPServer.call_tool` and asserts on what comes back
or on what it raises. A client never does that. It sends JSON-RPC over stdio
and is answered by `_handle_call_tool`, which converts a return value into a
result and an exception into an `is_error` result. Nothing in this repository
exercises that conversion, so a change to it is green all the way through.

**When the SDK version moves, drive the server the way a client does.** Spawn
`python -m benethos_lexware_office_mcp` with a scratch policy file and a
placeholder key, speak `initialize`, `tools/list` and `tools/call` to it over
its own stdin and stdout, and keep the answers. Do it once before the bump and
once after, then diff. Three things are worth capturing:

- **The tool list, byte for byte.** It is the largest thing this server sends
  and the whole of what the model knows about it. Byte-identical is the
  answer to want, and it is checkable: section 8 records the size.
- **An error the server means to send.** Call a tool the policy file disables.
  The guard refuses it before any HTTP, so the check is offline and
  deterministic, and it travels the exact path a real failure travels.
- **An argument the schema rejects.** That failure is raised by pydantic
  before the handler runs and is sorted differently, so it is worth watching
  separately from the one above.

This is what the 2.0.0 to 2.1.1 bump was checked with on 2026-09-02. The list
and the schemas came back byte-identical and the size stayed at 52,091, while
the error path had changed underneath, see section 12.1. Neither half of that
was predictable from the release notes alone, which is the argument for
sending the requests.

The probe is a scratch script, deliberately not a test. It spawns a process
and speaks a wire protocol, which is slow and brittle as a gate, and what it
guards is a decision rather than a behaviour: that the error hierarchy stays
on the SDK's anticipated-failure side of the line. `tests/test_errors.py`
asserts that decision directly, in a form that costs nothing to run.

## 15. Conventions

- Everything in the repository is English: code, comments, docstrings and
  documentation. Conversation with the user may be German. **One exception:**
  the text a person reads on screen in `configui/` is German, because Lexware
  Office is sold for German companies only and its own help centre rules out
  an Austrian or Swiss account holder, see section 7.1. Code, comments and
  docstrings in that package are English like everywhere else, and a message
  raised outside it is quoted into the page rather than translated.
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

- **every module in the table of section 4.** None is marked planned any
  more. The table is the list, so that this does not become a second one to
  keep in step.
- twenty-five tools in seven groups, over **stdio** and, since 0.2.0, over
  **streamable-HTTP** or **SSE** behind a required bearer token. Reading:
  `get_profile`, `search_contacts`, `get_contact`, `search_articles`,
  `get_article`, `search_vouchers`, `get_voucher`, `get_payments`,
  `get_sales_document`, `get_recurring_templates`, `get_master_data`,
  `download_file`, `download_document`, `read_download` and `get_deeplink`.
  Writing:
  `create_contact`, `update_contact`, `create_article`, `update_article`,
  `create_voucher`, `update_voucher`, `create_sales_document`, `upload_file`
  and `attach_file_to_voucher`. Irreversible: `delete_article`, and
  `create_sales_document` when it is asked to finalize
- one flag per tool in a JSON file, enforced when the list is built and again
  when a call arrives, with nothing enabled until that file says so and an
  edit taking effect in both directions without a restart. Presets and the
  file it writes come from the command line, `--tools` and `--tools-file`,
  and `--env-file` names the settings the same way
- **a client told when that list changes**: `tools.listChanged` announced and
  `notifications/tools/list_changed` sent when the set of enabled tools
  differs, which Claude Desktop acts on without a restart — measured
  2026-08-22, see section 9.2
- **a configuration interface in the browser**, `setup`, three pages: which
  files are in effect and where every value came from, the API key checked
  before it is written, and one checkbox per tool with what it costs the
  model in context, permission profiles and the policy file as a download.
  Never part of the server process, loopback only, see section 7.1
- **a container image and a Compose file**, two stages, non-root, 168 MB. The
  server on a loopback-published port and the configuration interface behind a
  `setup` profile on the same volume. A bearer token made on first start
  rather than baked in, and a process that ends when its settings file changes
  so the new ones take effect, see section 6
- one shared token bucket per process, retries decided per method and failure
  mode, upstream statuses mapped onto `ToolError` subclasses
- paging and filtering in the client, one page per call, never a walk over
  every page, and one page shape shared by every list tool
- writes that read before they replace, so an update changes only what it was
  given, and a stale `version` is refused before anything is sent
- binary downloads and multipart uploads through the same rate limiter and
  retry rules as every other call, and three ways to hand a downloaded file
  to a client: a path, an MCP resource, and the file rendered into the answer

Verified against a live account rather than assumed, and written up where it
belongs in section 5: the profile response shape, the per-endpoint page
ceiling, the 404 and 400 error bodies including the `IssueList`-only form, the
three-character minimum on the contact filters, the voucher type and status
enums, that a stale version arrives as 406 rather than 409, that a voucher PUT
must not echo its status, the upload contract and its 5 MiB ceiling, that
master data comes back as a bare list, that a key can be created inside a test
account, and that the bucket paces real calls (five tool calls at rate 1.5 took
2.69 seconds).

The contact and voucher tools were exercised against that account end to end:
records created, read back, searched, and updated in a way that proved the
merge keeps the fields the caller did not mention. The shapes in the test
fixtures are the shapes the API actually returned, and the enum values in the
voucher schemas were measured rather than taken from the documentation, which
does not list them.

**Feature complete.** Every tool of section 8 exists, every resource group of
section 4 is built, and every documented call is covered except the event
subscriptions, which section 2 rules out. The configuration
question of section 16.1 is answered too: `setup` serves the interface
described in section 7.1. Nothing on the API side is outstanding.

**What stood between here and 0.1.0 was not code**, and it was done in this
order:

1. ~~**A public repository.**~~ **Done 2026-08-22:**
   `github.com/benethos-hub/lexware-office-mcp`. `main` is protected and can
   only be reached through a pull request whose six checks are green, for the
   owner as well. Merges are squash or rebase, the history stays linear, and a
   merged branch deletes itself. Nothing is written to `main` directly any
   more.
2. ~~**CI.**~~ **Done 2026-08-22.** `.github/workflows/ci.yml` holds four
   jobs: `lint` (`ruff check`, the format check, `mypy` and `uv lock --check`),
   `test` across the Python matrix of section 6 with the coverage floor,
   `fresh-install`, which builds the wheel, installs it with no lockfile
   involved and asserts that an installation without a policy file offers no
   tools at all - the rule of section 9.2, which no offline test reaches
   because every one of them writes a policy file first - and `docker`, which
   builds the image and asserts the same rule against the artefact people
   actually run: the container generates its own bearer token, refuses a
   request that does not carry it, and answers `tools/list` with nothing. It
   also fails the build if a plain `up` would start the configuration
   interface, which belongs behind its profile. Only `linux/amd64` is built,
   because nothing publishes a second architecture yet. Every job passes with
   no key, no network and no account, see section 14.1.
   `.github/dependabot.yml` asks weekly about the dependency ranges, the
   pinned actions and the container base image.

   **The first run earned its keep**: green on 3.11 to 3.13 and red on 3.14,
   where a parameter description had silently disappeared from a tool schema.
   See section 6 for what changed in Python and why the workaround it broke
   was there.

   **A new job is not required by itself.** The six that block a merge are
   listed in the branch protection, so a job added later - `docker` with
   0.2.0, or a Python version added to the matrix - runs, may fail, and still
   lets the merge through until it is added to that list as well.
3. ~~**`config/.env.sample` inside the wheel.**~~ **Done 2026-08-22.** The
   sample moved into the package as `env.sample`, so it is installed with the
   code instead of sitting beside it, and `--settings-sample` prints it.
   Building the wheel now finds it among thirty-nine files. See section 16.1.
4. ~~**Publication to PyPI**~~, which is what makes the installation
   instructions in the README true for someone who has not cloned the
   repository.
   `.github/workflows/publish.yml` does it from a published release over
   Trusted Publishing, so no token is stored here. It needs a pending
   publisher on PyPI first, whose five fields the workflow header spells out.
   **The release itself:** a `release/X.Y.Z` branch that moves the CHANGELOG
   `[Unreleased]` section to a numbered one with its compare links, bumps the
   version pin in the README's client example, and brings the installation
   instructions in line, then a tag and a GitHub release on the merged commit,
   which is what triggers the upload.
5. **Publication of the image**, so that running this server in a container
   does not require cloning the repository first. The same workflow gained a
   second job that pushes `ghcr.io/benethos-hub/lexware-office-mcp` for
   `linux/amd64` and `linux/arm64`, authenticated by the automatic
   `GITHUB_TOKEN`, which is why the registry is ghcr and not one that needs an
   account and a stored secret. The two jobs are independent: a broken image
   does not withhold the upload to PyPI. `workflow_dispatch` runs the image
   half alone and tags it `edge`, since a release is otherwise the only way to
   exercise a workflow that triggers on one.

   **The metadata has to sit on the index, not only on the manifests.** A
   multi-architecture image is an index pointing at one manifest per
   architecture, and the package page reads the index. Labels in the image
   configuration are then present and read by nothing, which is how a package
   page comes to say "No description provided" about an image that carries a
   description. `DOCKER_METADATA_ANNOTATIONS_LEVELS: index,manifest` puts them
   in both places, and the job then reads the published index back and fails
   if the description, the source or the version is not on it - a release is a
   poor moment to discover that setting a value and it arriving are different
   things.

   **Measured on 2026-08-22 by running it**, which is the only way the
   metadata could be believed. `workflow_dispatch` pushed `edge`, the readback
   found both architectures and the description on the index, and the package
   page shows that description rather than "No description provided". The
   image was then pulled on a machine with no login and started from the pull:
   it generated its own token and refused a request without it. Contrary to
   the documented behaviour, the package did not need a visibility switch - it
   was public from the first push.
6. **What the build reaches for stays on a floating tag**, decided
   2026-08-23. The base image is `python:3.14-slim`, the uv binary comes from
   `ghcr.io/astral-sh/uv:0.12`, and the workflow actions are pinned by major
   version - except `astral-sh/setup-uv`, which carries a full version because
   it stopped publishing floating tags with its v8, so `@v10` resolves to
   nothing and fails a job before it starts. These follow their line rather
   than a digest, which means a security fix arrives without anyone acting -
   and that a build from today is not bit-for-bit the build from last week. Pinning digests reverses that
   trade: reproducible, and every patch waits for a pull request. For an image
   that holds an accounting credential, arriving patches are worth more than
   reproducible bytes, and nothing here needs a byte-identical rebuild to
   prove anything.

   What makes that safe to say is that all three are watched.
   `.github/dependabot.yml` covers the declared ranges, the actions and, since
   2026-08-23, the container base image - the one that ages silently, because
   an out-of-date base is not a build failure but unpatched system packages
   inside something people pull and run.

**The numbers below no longer mean what they were named for.** They were
assigned when the work was expected to arrive release by release, and it did
not: writing, the policy and the configuration interface all landed before
the first release rather than after it. So 0.1.0 is everything that has been
built, and the table below records releases only. The tool groups of section 8
keep the same split but are named for what they are — reading, writing and
irreversible — because they were never a release order and calling them phases
suggested they were.

| Release | Content | State |
|---|---|---|
| 0.1.0 | stdio transport, all twenty-five tools of section 8, the per-tool policy of section 9, the configuration interface of section 7.1, the client with its rate limiting, retries, error mapping, paging, downloads and uploads, and the offline suite | **released 2026-08-22** — every part of it is built and exercised against a live account |
| 0.2.0 | HTTP transport with its own bearer authentication, Docker image and Compose file | **released 2026-08-22** — `transport.py`, `Dockerfile` and `compose.yaml`, guarded by the `docker` job in CI, which is one of the seven checks a merge needs. The release publishes the image to ghcr beside the package on PyPI, and a client has reached the live account through the pulled image over HTTP |
| 0.2.1 | The published image on Python 3.14 | **released 2026-08-23** — no change to the package itself. The tags a user pulls, `latest` and the minor line, follow the release tag, so the base image moves only when a version number is spent on it |
| 0.2.2 | `--env-file` reads the file it names and no other | **released 2026-08-23** — the flag had promised that in its own help since it was added and read the named file after everything the search found, so it isolated nothing. See section 6. The search behind it follows one rule now as well, which is a decision rather than the fix |
| 0.2.3 | Error messages reach the model again under MCP SDK 2.1 | **released 2026-09-02** — the SDK began sorting a failing tool call by the type of what was raised, and this hierarchy derived from plain `Exception`, so every sentence it sends was replaced by "Error executing tool <name>". It reached installations rather than only this checkout: the declared range already allowed 2.1. See section 12.1. The lockfile was brought current in the same release, and Dependabot had been silent since it was configured because it read `pip` rather than `uv` |

**No feature release is planned between 0.2.3 and whatever a future API
version brings.** What was once listed as a phase of its own — booking a
voucher, and the ZUGFeRD and XRechnung download variants — turned out on
2026-08-21 to be one operation the API cannot perform and one that
`download_document` and `download_file` already do through `file_format`. A
number gets assigned when there is content for it, not before.

### 16.1 Answered: how a user configures the server

**Settled on 2026-08-21 by building the interface**, the third of the four
directions below. It is specified in section 7.1. The problem it was opened
for is recorded here as it stood, because the reasoning is what the interface
is answerable to.

**What was wrong**

- A user installing from PyPI gets **no sample**. The wheel packs the package
  directory only, and `config/.env.sample` sat beside it, so the ten settings
  existed only in the README. Verified by building the wheel: 38 files as of
  2026-08-22, none of them the sample. **Fixed the same day** by moving the
  sample into the package.
- There is **no way to create the file**. The only location that works for an
  installed package is the per-user config directory, and neither the
  directory nor the file is created by anything. A user would have to make
  both by hand from a path they have to look up first.
- **Nothing says which file is in effect.** Five sources are merged, and a
  setting that appears not to work gives no hint whether it was overridden, or
  read from a file the user has forgotten about.
- The failure a user met first was therefore a server that starts, lists its
  tools, and answers every one of them with "no API key".

**The four directions, and what became of them**

- **Ship the sample in the wheel** and name its target path in the error
  message. **Done**, though not by shipping a file beside the package: it
  moved *into* the package, which is the only place an installer copies from.
  `--settings-sample` prints it, so no path from the server's machine has to
  be named to hand it over.
- **A command that writes the file**, creating the directory and refusing to
  overwrite an existing one. **Superseded.** The interface writes it, and
  writes it by merging rather than by overwriting, which is what the
  objection to the original version was about.
- **A small local configuration interface.** **Chosen and built.** See
  section 7.1. It grew two things beyond the sketch: the context cost of each
  tool, and permission profiles with an export that carries them to another
  machine.
- **A read-only diagnostic** as a smaller version of the same idea. **Built
  as the overview page** rather than as a separate command: every candidate
  file, whether it exists, which value won and where it came from, without
  ever printing the key.

**Constraints that held, and were kept.** The key never enters a versioned
file and never appears in output — the interface neither displays it back nor
puts it in an export. A real environment variable still outranks every file,
and the page marks a setting it would be pointless to type over. The
interface works for an installed package and for a clone, and names the file
it is acting on rather than leaving it to be inferred.

### Open questions

Numbering is stable, so cross-references elsewhere keep pointing at the right
item. Answered questions stay in place with their answer.

1. ~~Exact maximum page size per endpoint.~~ **Answered 2026-08-20:** it is
   per endpoint, not one number. `voucherlist` caps at 250, `contacts`
   accepts 500 and refuses 1000. This project caps at 250 as the lowest
   ceiling measured. **Extended 2026-08-21:** there are floors as well.
   `/v1/articles` refuses anything below 25 with `size: MIN`, which no other
   list does. See section 5.
2. ~~Whether the API offers an idempotency key for POST.~~ **Answered
   2026-08-21: it does not.** Measured by posting the same credit note twice
   under one key, three times over with `Idempotency-Key`, `X-Idempotency-Key`
   and `Idempotency-Id`. Every pair produced **two** documents with different
   ids and a 201 each — an unknown header is ignored here exactly as an
   unknown query parameter is. The rule in section 10.2 that a failed POST is
   never retried therefore rests on a measurement rather than on caution, and
   there is no way to make one safe to repeat.
3. ~~File upload limits: maximum size, accepted MIME types, and whether
   `type=voucher` is the only accepted form value.~~ **Answered
   2026-08-20:** 5 MiB inclusive, PDF, JPEG, PNG and XML, and yes —
   `voucher` is the only accepted value. See section 5.
4. ~~The correct app base URL for deeplinks per account region.~~
   **Answered 2026-08-21:** `https://app.lexware.de` serves the permalinks,
   and `https://app.lexoffice.de` answers every one of them with a 301 to it,
   so the old host keeps working and neither is region-specific as far as can
   be seen from here. It stays configurable. The permalink shapes were
   measured the same day, see section 5.
5. ~~Whether any endpoint returns a partner or OAuth-only field that a plain
   API key cannot reach.~~ **Closed 2026-08-21.** The question assumed a
   second way in - a partner integration authorized by OAuth2, of the kind
   many vendors run beside an account key, which can see fields a plain key
   cannot. The documentation describes exactly one way in: the account
   owner's private key from `app.lexware.de/addons/public-api`, sent as a
   bearer token. No OAuth2 flow, no partner access, no scopes, no endpoint or
   field level restrictions appear anywhere in it. Nothing read against a live
   account has hinted at a truncated view either: every record carried what
   the web app shows for it. An **undocumented** partner programme cannot be
   ruled out from here, but it would be a question for Lexware rather than a
   measurement, and it would be moot for this server, which serves one account
   deliberately and is not a customer-facing integration.
6. ~~The upstream token bucket capacity, which is not documented.~~
   **Answered 2026-08-21: it is 4.** Measured after a 15 second idle stretch,
   which at the documented 2 per second would have accumulated 30 tokens if
   the bucket were deep. Five requests fired at once: four went through in
   1.33 seconds, the fifth was refused. Four fired at once went through
   cleanly. So the capacity is small and fixed, not a function of how long the
   key has been quiet. `LXO_MCP_BURST` stays at `2` anyway — see section 10.1
   for why the measurement does not simply become the default.
7. ~~Whether 429 responses carry a `Retry-After` header, and whether the
   block duration grows with repeated offences as the wording about permanent
   blocking suggests.~~ **Closed unanswered on 2026-08-22, by decision.**
   Answering it means provoking 429s against a production account on purpose,
   and the second half cannot be answered by anything but repeated offences -
   the behaviour the documentation says leads to a permanent block. This
   project does not probe its provider for limits it was asked not to test.
   The retry rules of section 10.1 assume no `Retry-After` and back off with
   jitter, which is the right behaviour whether or not the header is there,
   so nothing is waiting on the answer.
8. ~~Whether an API key can be generated inside a 30-day test account.~~
   **Answered 2026-08-20:** yes, and it works against the production endpoints.
   See section 11.1.

**Nothing is left that a test account could answer.** Questions 2 and 6 were
measured on 2026-08-21 and 5 was closed against the documentation the same
day. Question 7 is closed by decision rather than by measurement, see above.
The one 429 that did occur while measuring question 6 came back without a
`Retry-After` worth reading, and that remains the only observation there is.
