# Concept: tools and prompts

Part of the [concept](../CONCEPT.md): section 8.

## 8. Tools

Tool count is kept deliberately low. Descriptions and schemas are sent on
every request, so a wide surface is paid for continuously. Related endpoints
are therefore grouped behind one tool with an enum parameter rather than
exposed one tool per path.

**What the tool list actually costs, measured 2026-08-21, again on
2026-08-22 with the annotations below, again on 2026-08-23 after
`create_voucher` lost a parameter that could not work, and twice on
2026-09-27, the second time after the documentation review added
`voucher_number`, three sort properties and `finalize`, on 2026-09-30
after the four price fields of a sales line became optional for a text
line, and on 2026-10-08 after `document_type` took the voucher list's
spelling as well and `read_download` stopped suggesting that null renders
every page, on 2026-10-10 after `search_vouchers` lost the two flags
the API ignored, and on 2026-10-12 after the twenty-two tools that answer
with a record stopped publishing an output schema, and on 2026-10-15 after
the two upload tools took a URL as well as a path, on 2026-10-29
after `server_status` joined them, on 2026-11-07 after its
description grew by two sentences, and on 2026-11-09 after `get_article`
named its neighbours.** Serialized as the compact JSON a
`tools/list` answer is, twenty-six tools come to **52,332 characters**,
around 2,000 each, of which `server_status` is 788. Roughly 13,500 to
16,000 tokens, estimated at 3.2 to 3.8 characters per token rather than
counted with a tokenizer.

| Part | Characters | Share |
|---|---|---|
| Input schemas | 34,571 | 66% |
| Tool descriptions, the part under a ceiling | 11,856 | 23% |
| Output schemas, the three file tools alone | 2,567 | 5% |
| Annotations | 1,108 | 2% |
| Names, titles and the rest | ~2,230 | 4% |

The figures move whenever a description is touched, so they carry a date
rather than a promise. `CLAUDE.md` holds the one-liner that measures them.

**Annotations, and why they cost what they cost.** Every tool carries the MCP
hints, derived in `tools/_base.py` from what `@classify` already recorded
rather than written out per tool: a tool cannot then say one thing to the
policy file and another to a client. `read_only_hint` follows `access`, which
makes it true for `download_document` and `download_file` although both save a
file. The protocol defines the hint as "does not modify its environment", and
the only changes they make are a new file in the download directory and, in the
default cache, the oldest downloads deleted past the bound of section 13:
nothing in Lexware, never an overwrite, and nowhere but the directory the
settings name. Deriving the hint from somewhere else would mark the two as
writing in the `read-only` preset they belong to, so the derivation stays and
this sentence is the record of the decision. `destructive_hint` is false for a
create, which only adds, and true for an update or a delete - this API replaces
a record rather than patching it. `idempotent_hint` is the same distinction
seen from the other side: a second create is a second record, since there is no
idempotency key (question 2, [section 16](../ROADMAP.md)), while a repeated
update spends a version it no longer has and a repeated delete finds nothing
left, so neither changes the books twice.

`open_world_hint` is the one stated only where it differs from the protocol's
assumption, which is `get_deeplink` and `read_download` - the two tools that
answer without reaching the API. Stating it on the other twenty-four would
have cost 21 characters each to repeat a default. On a writing tool the three
hints above are stated either way, including where they match the default: a
client that does not fill defaults in would otherwise read "this deletes
things" as nothing at all, and that is not a saving worth 900 characters. A
reading tool carries `readOnlyHint` alone, since the protocol gives the
other two a meaning only where that one is false.

These are hints, and the protocol says a client must not make tool-use
decisions on them from a server it does not trust. Nothing here enforces
anything - the policy file of [section 9](permissions.md#9-permission-model)
does that, twice, and neither gate consults an annotation.

**An output schema is published where it says something.** The three file tools
declare one, because a generic object schema tells the model nothing about
`path` versus `uri`, see [section 13](errors-and-output.md#13-output-format).
The other twenty-two answer with a record, and until 2026-10-12 the SDK read
their `dict[str, Any]` as a structured tool and published `{"type": "object",
"additionalProperties": true}` with a generated title for each: 1,773
characters per listing that no client could act on. `tools/_base.py` now
registers those tools as unstructured and builds the result the SDK would have
built, with the same serializer, so the answer a client receives is
byte-identical to before, record and text both, and only the schema is gone.
Checked the way [section 14.3](testing.md#143-the-sdk-is-the-second-blind-spot)
says, over stdio, before and after.

Two things follow, and neither was obvious before the measurement.

**The 700-character ceiling governs a fifth of the cost.** Of the 34,382
characters of input schema measured on 2026-10-15, before `server_status`
added 189, 13,686 are prose from `Field(description=...)` and
the remaining 20,696 are structure the schema generator emits: types,
defaults, `$defs`, `anyOf` branches and generated titles. Parameter prose is
under no ceiling at all and is not visible while writing a docstring, which is
where it should be watched: `create_voucher` spends 1,634 characters on
sixteen parameter descriptions, nearly three times its own description.

**The six structured tools carry half of it.** `create_sales_document` (5,307),
`create_voucher` (4,192), `update_voucher` (4,114), `create_contact` (3,976),
`update_contact` (3,926) and `search_vouchers` (3,433) come to 48% of the total
between them. Every one of them takes a record's worth of arguments, and the
largest takes a nested model of line items on top. The policy file of
[section 9](permissions.md#9-permission-model) is therefore also a context
lever, not only a permission one: a `read-only` installation sends 23,415
characters, `server_status` included, a little under half.

The numbers move whenever a description does, so they are a measurement with
a date on it rather than a budget. What is stable is the shape: schemas cost
three times what descriptions cost, and the tools that take structured
arguments cost three to four times what the simple ones do.

### The status tool

| Tool | Inputs | Output | Calls |
|---|---|---|---|
| `server_status` | `details` | plain text, see below | 0, with `details` at most 1 every 60 seconds |

**Why it exists.** A client shows neither the server's version nor whether
Lexware answers, and a model cannot read the `serverInfo` of the handshake.
One tool answers both, and with every other tool off it is the one a model
can still ask, which is why it sits outside the policy file, see section
9.2. Its description is short, since it is sent on every request. Two
of its sentences answer what a model misread twice in one Claude Desktop
test on 2026-11-07: that a policy file not loaded is why no other tool is
there, and that an answer from before the settings changed no longer
says how the server is.

**The answer is plain text**, one `key: value` per line, a block as a line
`name:` with its fields indented two spaces below it. No structured content,
since a model reads the text anyway. Truth is `yes`, `no` or `unknown`, a
duration is whole seconds with the unit in the key, a point in time is how
many seconds ago, never a date. The core, always, answered from memory:

```
name: benethos-lexware-office-mcp
version: 0.10.2
transport: stdio
python: 3.15.2
mcp: 2.3.0
uptime_seconds: 418
```

`uptime_seconds` counts from where the server is built, which every
transport passes through. It is the one thing the core remembers. Anything
that needs a counter, a cache or a request is under `details`, which with
`details: true` follows as a line `details:` and two blocks:

```
details:
  upstream:
    reachable: yes
    checked_seconds_ago: 0
    token_set: yes
    token_valid: yes
  policy:
    file_loaded: yes
```

- `reachable` is whether Lexware answered, below 500. A 5xx is no better
  than no answer for whoever asked.
- `token_set` is whether a key is configured, never the key or any part of
  it, its length or a hash. `token_valid` is whether the API took it: a 401
  is no, and a 403 is a key the API knows that may not read this path, so it
  is yes.
- `file_loaded` is whether the policy file was there and read as flags. A
  broken file enables nothing, as a missing one does, so both are no. No
  path and no list of tools: the list the client holds is what the file
  allows, and a key might still be refused a path, which only a call shows.

**The check of Lexware**, `Health` in `api/client.py` and `Connection.probe`
beside the request mechanics, is one `GET /v1/profile`, the cheapest call there
is, whose answer is read for its status alone. It is one attempt: no retry, no
status turned into an error, and a 429 does not count towards the breaker of
[section 10.1](client.md#101-rate-limiting). It takes its token from the one
bucket and waits a second for it at most, in which the bucket refills one and a
half at its default rate. Behind the breaker, or behind a queue of calls, it
sends nothing and answers with the last check. It first took only a token free
at that moment, and measured against the test account on 2026-10-29 it then
sent nothing right after two calls and answered `never`, less than a second
before a token was due. It waits five seconds for an answer at most, whatever
`LXO_MCP_TIMEOUT` says. One check stands for 60 seconds per process, and a call
in between is answered with it and its true age. Nothing checks on its own:
without a call with `details`, no request is sent at all. A key the API refused
is not sent again until another is set, which over stdio can happen without a
restart, see section
6. Without a key nothing is sent and `checked_seconds_ago` is `never`. It
writes no line at `INFO`: a status question is not an activity, and a
check that failed is in the answer anyway.

**A field is added, never removed or changed.** A new one goes after the
others of its block. One that has to mean something else gets a new name.
Should a field ever have to go, the answer's first line becomes
`schema: 2`, and without it the answer is version 1.

### Read tools

| Tool | Inputs | Output | Calls |
|---|---|---|---|
| `get_profile` | — | `{organizationId, companyName, connectionId, taxType, smallBusiness, businessFeatures}`. Verified against a live account 2026-08-20. The `created` block the API also returns is **dropped**: it carries the setting-up user's email address, which the tool does not need and which has no business reaching a language model. Doubles as the connection check. | 1 |
| `search_contacts` | `name`, `email`, `number`, `role` (customer/vendor/any), `page`, `size` | `{contacts: [{id, version, name, type, roles, customerNumber, vendorNumber, email, phone, archived?}], page: {number, size, totalElements, totalPages, last}}`. The filter is named `name` rather than `query`, because it matches names only and calling it a query would promise a full-text search the API does not offer. `name` and `email` carry the API's three-character minimum in the schema. The response's `sort` block is dropped, and `archived` appears only when true. Built and verified against live records 2026-08-20. | 1 |
| `get_contact` | `contact_id` | the full contact including addresses, roles and `version`, with `organizationId` dropped: it is identical on every record and `get_profile` already answers it. A drop-list, not an allow-list, so a field added upstream still surfaces. Built and verified against live records 2026-08-20. | 1 |
| `search_articles` | `article_number`, `gtin`, `article_type`, `page`, `size` | `{articles: [{id, version, title, articleNumber, type, unitName, price, archived?}], page: {...}}`. **No `query`.** It was specified here and dropped on 2026-08-21 when the endpoint turned out to filter on three fields and to ignore every other parameter silently, so a text search would have answered with the whole catalogue while looking like it had searched. Both filters match in full. `description` and `note` are dropped from a row and kept by `get_article`. There is no `currency`: an article's price block carries none. Built and verified live 2026-08-21. | 1 |
| `get_article` | `article_id` | the article in full, `organizationId` dropped, including the price block and `version`. The block carries a net and a gross figure with the tax rate between them and `leadingPrice` saying which of the two was entered - dropping either half would leave a number that cannot be checked. Built and verified live 2026-08-21. | 1 |
| `search_vouchers` | `voucher_type`, `voucher_status`, `contact_id`, `voucher_number`, `date_from`, `date_to`, `archived`, `sort`, `page`, `size` | `{vouchers: [{id, voucherType, voucherStatus, voucherNumber, voucherDate, dueDate, contactName, totalAmount, openAmount, currency, archived?}], page: {...}}`. The central discovery tool, and the only way to find a document at all. `voucher_type` and `voucher_status` default to `any` because the API requires them, so the tool always sends both. `createdDate` and `updatedDate` are dropped from the rows: they say when somebody typed it in, not when the document is dated. `voucher_number` matches the whole number, ignoring case, never a prefix, and combines with the other filters - measured 2026-09-27, when it turned out the filter had been in the documentation since 2021 while this table said it did not exist. **What is still outstanding is `voucher_status`**: `open` lists the overdue documents as well, `overdue` only those, and the API refuses `overdue` beside any other state. Until 2026-10-10 the tool also offered `only_open` and `only_overdue`, sent as `onlyOpen` and `onlyOverdue`, which the endpoint ignores without a word and the documentation never listed: measured that day against the test account, the same rows came back with and without them, paid ones included (issue #95). Built and verified live 2026-08-20. | 1 |
| `get_sales_document` | `document_type` (invoice, quotation, credit-note, order-confirmation, delivery-note, dunning, down-payment-invoice, and the four hyphenated ones also as `search_vouchers` spells them in `voucherType`, `creditnote` and the like, since 2026-10-08), `document_id` | the document as the API holds it: recipient, line items with their unit prices, totals, tax breakdown, payment and shipping conditions, and `version`. A drop-list of one, `organizationId`, rather than an allow-list: the seven types differ field by field and an allow-list would swallow whatever makes a dunning a dunning. Built and verified live 2026-08-21, in both `open` and `draft`. | 1 |
| `get_voucher` | `voucher_id` **or** `voucher_number` | the bookkeeping voucher with its lines, posting categories, tax type and `version`. Takes a number as well as an id. The lookup goes through `/v1/vouchers?voucherNumber=`, which answers with the whole voucher in one call. The documentation marks that filter deprecated in favour of `voucherlist`'s own, which would cost a second call for the record - it still answers, measured 2026-09-27. Until then this table said `voucherlist` could not filter by number, which was never measured and is false. A number matching several vouchers is refused with their ids rather than guessed at. Built and verified live 2026-08-20. | 1 |
| `get_payments` | `voucher_id` | `{openAmount, paymentStatus, currency, voucherType, voucherStatus, paymentItems}`. An `openAmount` of 0 is the answer to "is it settled" and is reported, not dropped. Refused by the API for a voucher that is not booked yet. Built and verified live 2026-08-20. | 1 |
| `get_recurring_templates` | `template_id`, `sort`, `page`, `size` | with an id the template itself, without one `{templates: [...], page: {...}}`. One tool rather than two because there is nothing to search by: the endpoint takes paging and a `sort` and ignores anything else, and a second tool would have cost a second description for the same call. `sort` is a `Literal` of the four dates the API named when it refused `title`, each way round. Nothing but `organizationId` is dropped, because the API already sends a shorter row in a list than it sends for one record — see [section 5](upstream-api.md#5-upstream-api), which is also why the tool says to read by id for the lines. Built and verified live 2026-08-21. | 1 |
| `get_master_data` | `kind` (countries, payment-conditions, posting-categories, print-layouts), `search`, `limit` | `{kind, total, matched?, shown, entries}`. Nothing is dropped from a row: every field of these four decides something, including a `contactRequired` of false. What is trimmed is the number of rows, because two of the lists run into the hundreds and none of them pages, so the whole list arrives whatever the caller wanted. `search` matches every text a row carries except its id, which is one parameter instead of one per field and narrows by name, group, country code or category type alike. `matched` appears only when a search was given, where it would otherwise restate `total`. Built and verified live 2026-08-21. | 1 |
| `download_document` | `document_type`, `document_id`, `file_format` (pdf/xml) | `{path, uri, mimeType, size}` plus a `resource_link` block, the same delivery as `download_file`. Renamed from the planned `get_document_pdf`, which promised a format the tool does not always fetch, and reduced to **one** behaviour and **one** call: it downloads and saves. The planned variant that returned a `documentFileId` without saving was dropped, because the only thing a caller could do with that id is hand it to `download_file` — the same work through a second tool, and the two were measured on 2026-08-21 to return the same bytes. Verified live the same day against a real invoice, in both the rendered and the draft case. | 1 |
| `download_file` | `file_id`, `file_format` (pdf/xml) | `{path, uri, mimeType, size}` plus a `resource_link` block. No deeplink: a download reports where the bytes are, and a link into the web app is `get_deeplink`'s answer to a different question. The two were joined until 2026-08-21, which is how a link to a route that does not exist rode along with a download that worked. The bytes stay out of the answer and are fetched by the client from `uri` when it wants them, see [section 13](errors-and-output.md#13-output-format). An existing file is never replaced. Built and verified live 2026-08-20. | 1 |
| `read_download` | `uri` | `{uri, mimeType, size, deliveredAs, pages?, pagesShown?}` plus the content itself. The fallback for a client that does not follow resource links: it puts a downloaded file into the answer as text, as an image, as **rendered page images for a PDF**, or as an embedded binary, depending on what the file is. Refuses anything outside `lexware://download/`, so it is not a file reader, and refuses above 5 MiB. Built 2026-08-20 after Claude Desktop turned out not to resolve resource links. | 0 |
| `get_deeplink` | `target`, `target_id`, `action` (view/edit) | `{url}`. `target` reaches past the sales documents to contacts and vouchers, since the permalink shape is the same for them and the extra entries cost nothing. A stored file is **not** a target and a contact ignores `edit`, both because the app answers those with a 404, see [section 5](upstream-api.md#5-upstream-api). Built 2026-08-20, corrected against the live app 2026-08-21. | 0 |

### Write tools

| Tool | Inputs | Calls | Notes |
|---|---|---|---|
| `create_contact` | `kind` (company/person), `name`, `roles`, `first_name`, `salutation`, `email`, `phone`, `billing_address`, `shipping_address`, `vat_registration_id`, `tax_number`, `note` | 1 | Returns the id and version the API answers with, not the record. The customer and vendor numbers are assigned by Lexware, so they are only visible after reading the contact back. The parameters are flat rather than the API's nested object because the API itself allows only one billing address, one shipping address and one entry per email or phone type, so flat loses nothing. Addresses are the exception and stay structured, since they have five fields each. Built 2026-08-20. |
| `update_contact` | `contact_id`, `version`, then the same fields, all optional | 2 | Reads the record and lays the given fields on top, because a PUT replaces rather than patches. An email address or a phone number replaces the whole block, filed under the category the contact already used when it used one: merged in, a new address under `business` sat beside the old one under `office`, measured 2026-09-27. The `version` the caller passes is checked against the record before anything is sent, so a stale one costs one read and no write. Built 2026-08-20. |

| Tool | Notes |
|---|---|
| `create_contact` / `update_contact` | **Built 2026-08-20**, see the read table above for what they cost. |
| `create_article` / `update_article` | **Built 2026-08-21.** `create_article` takes the four fields the API insists on - title, type, unit and a price with its tax rate - plus a side, `NET` or `GROSS`, saying which figure the price is. The other is computed upstream rather than here: an amount this project derived and sent would be a number nobody checked. `update_article` reads, merges and replaces like `update_contact`, and sends only the leading figure whenever the price, the side or the rate changes, so a new rate is never sent beside two prices it contradicts. The API would tolerate that - measured 2026-09-27, a new rate beside both old prices is accepted and the other side recomputed, for `NET` and `GROSS` alike - but a body should not depend on it. |
| `delete_article` | **Built 2026-08-21**, and the first tool in the whole server carrying an irreversible effect. Takes `confirm: true` and sends nothing without it. The record is removed rather than archived - verified live: 204, then 404 on the same id. |
| `create_voucher` / `update_voucher` | **Built 2026-08-20.** `create_voucher` takes the type, date, tax type and lines, and adds the totals up from the lines unless the caller states them, which is arithmetic the API insists on rather than a number being invented. The document number is required, and no status can be asked for - both measured 2026-08-23, see [section 5](upstream-api.md#5-upstream-api). `update_voucher` reads, merges and replaces like `update_contact`, and additionally strips the fields a voucher refuses on the way back in. It adds the totals up again only when it writes new lines - the tool takes no tax type, so a voucher keeps the one it has - and otherwise sends the ones it read: a voucher made from an upload holds no lines, and adding up nothing gave it a total of zero. `use_collective_contact` moves a voucher back from a named contact, measured 2026-09-27. `finalize`, with `confirm`, books an `unchecked` voucher such as `upload_file` leaves behind, and is refused for any other status before anything is written - so a receipt goes from upload to the books without the web app, verified live 2026-09-27. Neither can be undone: the API cannot delete a voucher. |
| `create_sales_document` | **Built 2026-08-21.** Six types, `down-payment-invoice` left out because it has no POST. The per-type requirement of [section 5](upstream-api.md#5-upstream-api) is checked here rather than upstream, so a missing `shipping_date` costs no request and the message names the field. Addresses by `contact_id` only: a one-time address would add a nested model to the largest schema in the server for a case `create_contact` already covers. `finalize` needs `confirm` beside it. Line items carry the price on the side the document's `tax_type` names, and the totals are left to the API. |
| `attach_file_to_voucher` | **Built 2026-08-21.** Hangs a file on a voucher that already exists, which `upload_file` cannot do: that one creates a voucher per file. Same `source`, same validation, same 5 MiB ceiling, same four types, and the answer is the file id alone. Neither the attachment nor a wrongly created voucher can be removed, so the description names the neighbouring tool rather than leaving the caller to find the difference. |
| `upload_file` | **Built 2026-08-20.** Takes a path on the machine the server runs on, and since 2026-10-15 a URL as well, in one parameter `source` that replaced `path`: a value starting `https://` or `http://` is fetched, see [section 7.2](configuration.md#72-uploads-from-a-url), anything else is read from disk. Accepts PDF, JPEG, PNG and XML, and refuses a missing file, any other extension and anything above 5 MiB before spending a request. The answer carries a `voucherId` as well as a file id, because uploading creates a voucher, and the docstring says so where a caller will read it. That voucher starts `unchecked`, and since 2026-09-27 the docstring also names `update_voucher` and its `finalize` as the way to fill it in and book it. |

### Irreversible tools

`delete_article` is **built**, and is what the `confirm: true` convention was
written for: the argument defaults to false, nothing is sent without it, and
the refusal says what would have happened. `create_sales_document` takes the
same argument for `finalize`, which is the other irreversible thing that can
be asked for here.

**And that is all of them, with one addition.** Booking a voucher was listed
here as a third and dropped on 2026-08-21 as impossible. On 2026-09-27 it
turned out possible for an `unchecked` voucher, and `update_voucher` takes
`finalize` with the same `confirm` for it. Nothing else can be booked,
finalized or voided after the fact, see
[section 5](upstream-api.md#5-upstream-api).

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
  before an update), how to read a result the schema does not explain, and what
  the API cannot take back - which is not the same as what cannot be undone,
  since the web app usually has a way and this server can only speak for the
  interface it uses. Design reasoning stays in these documents, where it is
  paid for once. **Under 700 characters**, which is a ceiling a rewrite into
  explanation will cross rather than a limit on wording — the fix when one
  grows past it is to move a paragraph into them. Not enforced by a test on
  purpose: a character count cannot judge whether a sentence earns its place,
  and making it a gate would turn the judgement into a number to be gamed.
- IDs are Lexware UUIDs. No tool invents, guesses or assembles an ID. A caller
  that has only a name uses `search_contacts` or `search_vouchers` first.

### Prompts

Three prompts in `prompts/` are recipes a person picks in the client, Claude
Desktop from the "+" menu, Claude Code as a slash command. Each returns one
user message that names the tools to call, in which order, and the traps of
the books to mind. A prompt asks Lexware nothing and writes no log line, the
tool calls it leads to write theirs. Every recipe reads and none writes.

| Prompt | Arguments | Tools it chains |
|--------|-----------|-----------------|
| `open_items` | `contact?` (every contact when empty) | `search_contacts` for a contact, `search_vouchers` with status open and 250 rows, quotations, order confirmations and delivery notes left out, split into owed to the company and owed by it, `get_deeplink` for each overdue document |
| `missing_receipts` | `period?` (a month, a quarter or a year, the last complete month when empty) | `search_vouchers` over the twelve months before the period and the period itself, oldest first, every page, `get_recurring_templates`, `get_deeplink`. Fixed rules for the rhythm of each contact and direction (monthly, quarterly, yearly), what is expected in the period, what is not due yet, what has likely ended, and the drafts and unchecked vouchers of the period |
| `contact_overview` | `contact` (a name, or a customer or vendor number) | `search_contacts`, `get_contact`, `search_vouchers` twice, the latest 25 and the open ones, `get_deeplink` for the contact |

**Offered whatever the policy file says.** A prompt is user-controlled in
MCP, it reaches no data and calls nothing, and the model it hands a message
to is left with the tools the file allows. So the list of prompts does not
follow the file, and every recipe opens by saying that a tool missing from
the list was withheld: name it, and leave out the step that needs it rather
than working around it. Following the file would also have made the prompt
list change at runtime, which no client has been told to expect, and Claude
Desktop declares its prompts in the extension's manifest anyway.

**Both extensions leave their tools and prompts to the server.** Their
manifests set `tools_generated` and `prompts_generated` and keep the two
lists for the installation dialog to show, every tool and every prompt. A
declared list is otherwise a contract: Claude Desktop refuses a prompt it
does not declare, and holds a declared one's answer against its text, with
each argument written as `${arguments.<name>}`, dropping one that differs as
a possible injection. The extension that updates itself keeps the manifest
it was installed with while the server moves on, so every later prompt or
changed word would be refused there, and in the pinned one a prompt with an
optional argument beside a required one cannot match at all. The flags end
both. An extension that updates itself installed from 0.9.1 or earlier has
no flag and declares the setup prompt alone, so it lists a recipe and
refuses it until it is installed again.

Measured 2026-11-11 in Claude Desktop 5.1231.2, with bundles that ran the
same server and differed in their manifest alone. Desktop lists every
prompt the server offers, declared or not, so the menu says nothing about
the manifest. Without the flag a recipe the manifest does not declare is
refused when it is attached, logged as "attempted undeclared prompt", with
"Failed to attach prompt" in the window. A declared one is logged as
"content matches declared template (<n> chars)". With `prompts_generated`
Desktop logs "skipping prompt verification" when it starts the extension
and checks no prompt at all, and the setup prompt still opens the
interface. With `tools_generated` and `server_status` left out of the
declared tools, the tool was listed and the call answered. Without that
flag the case was not measured, and no log line ever checked a tool.

**What an optional argument left out becomes** depends on the form. With
the recipe's only argument left empty, Desktop put the empty string into
the template: `open_items` matched at 2300 characters, where the template
with its placeholder standing would have been 2320, and `missing_receipts`
the same. Measured on another server the same day, an optional argument
left out beside a required one is not sent, and Desktop leaves
`${arguments.<name>}` standing in the template it compares with, which no
answer can match. Under the flags neither is compared. A recipe still has
no branch in it: an argument goes into the text as it was given, an
optional one defaults to the empty string, and the text says in words what
an empty one means, so a client that does compare finds the declared text.

**A bad request is the client's mistake, and answered as one.** The SDK
raises a plain `ValueError` for a prompt name it does not know and for a
required argument left out, which its dispatcher answers with code 0 and a
whole traceback on stderr, as if the server had broken. `PolicyServer`
checks both first and answers with invalid parameters and no log line. An
empty string counts as left out. The name a client sent is not repeated.

`missing_receipts` reads the rhythm from the voucher list alone, so it costs
one call per 250 vouchers of the twelve months before the period and the
period itself, and one for the templates. It needs no bank statement and no
file, and reports a gap as a question: a voucher a rhythm expects may never
have been issued.

`tests/test_prompts.py` holds every tool a recipe names to the registry, every
parameter to a tool's schema, every field in backticks to the shape captures of
[section 14.2](testing.md#142-a-shape-is-recorded-so-drift-can-be-seen-rather-than-remembered),
every page size and link target to what the tools accept, and every text to the
one with its placeholders filled in. `tests/test_mcpb.py` holds the manifest to
the texts, and `build.py --sync-manifest` writes them, the tools beside them,
so nothing is copied by hand. The prompt that opens the configuration interface
is not one of these: it starts a process, is offered over stdio only and lives
in `transport/setup_prompt.py`.
