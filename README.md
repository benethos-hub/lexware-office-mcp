# Unofficial Lexware Office MCP Server

> **Disclaimer**
>
> - This project is **not affiliated with, endorsed by, or sponsored by
>   Lexware or Haufe-Lexware GmbH & Co. KG**. "Lexware" and "Lexware Office"
>   are trademarks of their respective owners.
> - It uses the **documented public API** with an API key you generate and can
>   revoke yourself. Use of that API is governed by Lexware's own terms, which
>   you accept independently of this project. The API can change at any time,
>   and requests may be rate limited or blocked.
> - It reaches **real accounting records**. Write access is off by default. If
>   you enable it, anything created through the API is a real and legally
>   relevant record — a finalized document cannot be withdrawn through the API.
> - Data may be incomplete or out of date. **Nothing here is tax, accounting
>   or legal advice.** Do not rely on it for filings, audits, or your
>   bookkeeping obligations.
> - Provided "as is", without warranty. Intended for personal and professional
>   use at your own risk. See [LICENSE](LICENSE).
> - For **commercial use**, review Lexware's API terms and your own retention
>   and documentation duties.

An [MCP](https://modelcontextprotocol.io) server that connects an MCP client
such as Claude Desktop to a [Lexware Office](https://www.lexware.de/) account
through the official
[public REST API](https://developers.lexware.io/docs/). Ask about invoices,
contacts, articles and vouchers in plain language, and let the client fetch
them for you.

> **Status: 0.1.0 in progress, not published yet.**
> The server runs over stdio and handles contacts, vouchers and documents:
> find them, read them, create them, change them, see what is still unpaid,
> download a PDF and upload a receipt. `get_profile` answers which account
> is connected. The rest of the tools below are specified but not built, and
> the table says which is which. There is no PyPI release yet, so
> installation means cloning the repository. See [SPECS.md](SPECS.md) for
> the full technical specification and the roadmap.

## Why this exists

Lexware Office holds the day-to-day accounting of a small business. Most
questions about it are read questions — what is still unpaid, what did this
customer order, which receipt belongs to that expense — and those are exactly
the questions an assistant answers well once it can see the data. This server
makes that possible without exporting anything, using an API key the account
owner generates and can revoke.

## Safety first

The server points at a real accounting system, so the defaults are cautious.

- **Nothing is enabled until you say so.** A fresh installation has no
  policy file, and a server without one offers no tools at all. What this
  server may do is a decision somebody made, never a default that happened.
- **One flag per tool**, in a JSON file you write with `--tools` and edit by
  hand. Not a level, not a group: `create_contact` on and `upload_file` off is
  an ordinary thing to want, and there is no combination the file cannot
  express.
- The file is checked twice, once when the tool list is built and again when a
  call arrives, so a stale tool list on the client cannot slip past it.
- The API key is never logged, never returned in a tool result, and redacted
  from error messages.

## Tools

**Built** means it works today. The rest are specified in
[SPECS.md](SPECS.md) and not implemented yet.

Read tools:

| Tool | What it does | Status |
|---|---|---|
| `get_profile` | Company profile and connection check | **built** |
| `search_contacts` | Find customers and vendors by name, email, number or role | **built** |
| `get_contact` | One contact with addresses, roles and version | **built** |
| `search_articles` | List articles, filtered by number, barcode or kind. The API offers no search by title | **built** |
| `get_article` | One article with its price block and version | **built** |
| `search_vouchers` | The central query — filter the voucher list by type, status, contact, date range and what is still open | **built** |
| `get_sales_document` | Read an invoice, quotation, credit note, order confirmation, delivery note, dunning or down payment invoice in full | **built** |
| `get_voucher` | Read a bookkeeping voucher, by id or by its document number | **built** |
| `get_payments` | Payment status and open amount of a voucher | **built** |
| `get_recurring_templates` | Templates that issue invoices on a schedule, one or a page of them | **built** |
| `get_master_data` | Countries, payment conditions, posting categories and print layouts, with a search to narrow them | **built** |
| `download_document` | Save the rendered PDF or XML of a sales document | **built** |
| `download_file` | Save a stored file, such as an uploaded receipt | **built** |
| `read_download` | Put a downloaded file into the answer, for clients that cannot follow a resource link | **built** |
| `get_deeplink` | Build a permalink to a sales document, contact or voucher in the web app, without an API call | **built** |

Write tools. These change real accounting records, so enable them one at a time and against an account you are willing to have changed:

| Tool | What it does | Status |
|---|---|---|
| `create_contact` | Create a customer or vendor | **built** |
| `update_contact` | Change one, without touching what you did not name | **built** |
| `create_article` | Add an article to the catalogue | **built** |
| `update_article` | Change one, without touching what you did not name | **built** |
| `create_voucher` | Record a bookkeeping voucher | **built** |
| `update_voucher` | Change one that is already recorded | **built** |
| `create_sales_document` | Create an invoice, quotation, credit note, order confirmation, delivery note or dunning — a draft unless finalization is confirmed | **built** |
| `upload_file` | Upload a receipt, which also creates its voucher | **built** |
| `attach_file_to_voucher` | Hang a file on a voucher that already exists | **built** |

`update_contact` and `update_voucher` cost two API calls rather than one.
The API replaces a record instead of patching it, so the current one is read
first and the change is laid on top. Without that, changing only an email
address would empty out the addresses, the note and everything else. Both
also need the `version` you last read: if the record changed in between, the
update is refused and nothing is written.

One tool deletes, and it is the only one:

| Tool | What it does | Status |
|---|---|---|
| `delete_article` | Remove an article for good. Takes `confirm: true`, and sends nothing without it | **built** |

It is the only member of the `--tools irreversible` step so far, so that step
is the only way to switch it on. An article is also the only thing this API
lets you delete, which is the other half of the point:

`--tools write` is not the same as undoable. Nothing that preset enables
deletes a record, but two of its tools create one that cannot be removed
afterwards.

**A bookkeeping voucher cannot be deleted through the API.** There is no
endpoint for it, so a wrong `create_voucher` has to be corrected in the
Lexware Office web app. Pass `unchecked` to record an entry for review
rather than booking it straight away. The same applies to `upload_file`:
uploading a receipt also creates the voucher that goes with it, so it
leaves a record behind even though its name only mentions the file.

Downloads are written into the download directory on the machine the server
runs on, and reported two ways: a **path**, which is what you want when the
client and the server share that machine, and a **resource URI**, which the
client can read to get the bytes wherever the server is. The file itself
never travels inside the tool result, because base64 costs roughly 1.37
times the file size in context and no model can read a PDF anyway. An
existing file is never replaced: a second download is saved beside the
first with a counter in its name.

The resource list is filled from the download directory when the server
starts, so a URI stays readable after a restart. What the server cannot do is
announce a *new* download: the MCP SDK gives it no way to send a
list-changed notification, so a client that lists once at startup will not see
anything fetched later in the session.

Between that and Claude Desktop not following resource links at all,
`read_download` is the route that always works. It takes the same URI and puts
the content into the answer. What arrives depends on the file:

| File | Arrives as |
|---|---|
| XML | text, so an XRechnung can actually be read |
| PDF | pictures of its pages, the first 10 by default |
| Image | the image |
| Anything else | an embedded binary for the client to handle |

A PDF is rendered rather than passed through because Claude Desktop turns
an embedded binary into an image block when it calls the API, and
`application/pdf` is not a permitted image type there, so the whole
request is refused. Rendering costs no API call either, since the file is
already on the server.

A link into the web app is a separate tool. `get_deeplink` turns an id into
a URL for a browser, costs no API call, and is the route that still works when
the client can display neither the file nor a resource link: somebody opens it
themselves. A download does not carry one — it answers where the bytes are,
which is a different question, and the two were joined once long enough for a
broken link to ride along with a working download.

`upload_file` accepts PDF, JPEG, PNG and XML, at most 5 MiB per file, which
is what the API takes. An XML file is treated as an XRechnung and is
rejected if it is not one.

## Requirements

- Python 3.11 or newer. Installing pulls in the MCP SDK, httpx,
  platformdirs and pypdfium2, the last of these to render PDF pages
- A Lexware Office account with the public API add-on enabled
- An API key from <https://app.lexware.de/addons/public-api>

## Getting an API key

1. Sign in to Lexware Office as the account owner.
2. Open the public API add-on at
   <https://app.lexware.de/addons/public-api>.
3. Create a key and copy it once — it is shown a single time.
4. Keep it out of any file that goes into version control. Put it in
   `config/.env`, which is gitignored, or pass it as an environment variable.
   A key in `config/.env` is found no matter which directory the server is
   started from, so a client such as Claude Desktop needs no key of its own in
   its configuration file.

A key can be revoked on the same page at any time, which is the fastest way to
cut access if anything looks wrong.

## Installation

There is no PyPI release yet, so this means cloning the repository. With
[uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/benethos-hub/lexware-office-mcp
cd lexware-office-mcp
uv sync
cp config/.env.sample config/.env    # then put your API key in it
```

Check that it works:

```bash
uv run benethos-lexware-office-mcp --help
```

Then point Claude Desktop at it in `claude_desktop_config.json`. Use the
interpreter from the virtual environment directly, so no generated launcher is
involved:

```json
{
  "mcpServers": {
    "lexware-office": {
      "command": "C:\path\to\lexware-office-mcp\.venv\Scripts\python.exe",
      "args": ["-m", "benethos_lexware_office_mcp"],
      "env": {
        "LXO_MCP_API_KEY": "<your api key>"
      }
    }
  }
}
```

Restart Claude Desktop fully — quit it from the tray rather than closing the
window — so the tool list is reloaded.

## Switching individual tools off

One JSON file decides what this server offers, and nothing else does. Start
it with

```
benethos-lexware-office-mcp --tools read-only
```

which writes every tool into `tools.json`, reading ones on and the rest off,
and prints what it did. Three presets, each containing the last:

| | enables |
|---|---|
| `--tools read-only` | queries only |
| `--tools write` | and creating and updating |
| `--tools irreversible` | and deleting, booking, finalizing |

`--tools show` only reports. **`--tools-file PATH` says where to write**, and
works with all three — `--tools write --tools-file ./tools.json` creates the
file there.

The third step is its own because it is its own decision: deleting a record or
booking a voucher should be chosen by naming it, not by picking the largest
option. Nothing ships with such an effect yet.

Without `--tools-file`, the file is searched exactly like the `.env`, lowest
precedence first:

1. the per-user configuration directory
2. `config/` of a checkout, when you are running from the sources
3. `config/` and then the root of the working directory

The last one found wins, and a file nobody has created yet resolves to the
first. After that, edit it:

```json
{
 "create_contact": false,
 "search_contacts": true,
 "upload_file": false
}
```

A tool set to `false` is not listed and cannot be called. **A tool the file
does not mention is also off** — silence is a refusal, so a tool that arrives
with an upgrade waits for you rather than appearing on its own. No file at all
means no tools at all, which is why `--tools` is part of setting the server up.

The file is read as the tool list is built and again on every call, so an
edit takes effect at once in both directions — no restart. What lags is the
client: most ask for the tool list once, when they start, and go on showing
what they were told then. Claude Desktop is restarted by quitting it from the
tray.

Each tool also declares what it is — reading or writing, and which group it
belongs to. That classification is what `--tools read-only` selects on, and
what an interface would group by. It never decides a call: only the file
does.

## Configuration

Settings come from a `.env` file, found the same way the policy file is, or
from real environment variables, which win over it. `--env-file PATH` names
one instead of searching, and pairs with `--tools-file` so that one entry in a
client's configuration carries its own account and its own permissions:

```json
"args": ["--env-file", "/path/to/test.env",
         "--tools-file", "/path/to/test-tools.json"]
```

A path that does not exist is refused rather than quietly falling back to the
search.

| Variable | Meaning | Default |
|---|---|---|
| `LXO_MCP_API_KEY` | Your Lexware Office API key. Required. | — |
| `LXO_MCP_TOOL_POLICY` | Per-tool on/off file, see below | `tools.json` in the config directory |
| `LXO_MCP_BASE_URL` | API base URL | `https://api.lexware.io` |
| `LXO_MCP_APP_BASE_URL` | Web app base for deeplinks | `https://app.lexware.de` |
| `LXO_MCP_DOWNLOAD_DIR` | Where downloaded documents land | user cache directory |
| `LXO_MCP_TIMEOUT` | HTTP timeout in seconds | `30` |
| `LXO_MCP_RATE` | Requests per second, global across all endpoints | `1.5` |
| `LXO_MCP_BURST` | Token bucket capacity. The account's own bucket holds 4 | `2` |
| `LXO_MCP_PAGE_SIZE` | Rows per page a search requests and returns | `25` |
| `LXO_MCP_PDF_PAGES` | Pages of a PDF `read_download` renders by default | `10` |
| `LXO_MCP_LOG_LEVEL` | Log level on stderr | `INFO` |

Every setting above is in use. `LXO_MCP_PAGE_SIZE` is capped at 250, which is
the lowest page size any endpoint accepts, and a larger value is refused at
startup rather than turning into an API error later.

## Transport

The first releases speak **stdio** only, which is what Claude Desktop and
comparable local clients use. An HTTP transport is planned for 0.3.0 and will
ship with its own bearer authentication in front of the API key, because
anyone who can reach an unprotected port could otherwise spend your Lexware
credentials. Until that authentication exists, HTTP stays unavailable rather
than insecure.

## Example prompts

Once the server is connected, prompts like these are the intended use:

- "Which invoices are still open, and which of them are overdue?"
- "Show me everything we billed customer Muster GmbH this quarter."
- "What does invoice RE-2024-0142 contain, and has it been paid?"
- "Find the article with number A-1007 and tell me its current price."
- "Download the PDF of the last credit note we issued."
- "Give me a link to open voucher X in Lexware Office."

## Rate limits

The Lexware API allows two requests per second, enforced with a
[token bucket](https://en.wikipedia.org/wiki/Token_bucket). That budget is
**global** — it covers all endpoints of the API at the same time, so reading a
contact and reading an invoice draw from the same allowance.

The server mirrors this with a single token bucket shared by every request in
the process, refilling slightly below the documented rate by default. Lexware
notes that enforcing the limit exactly, without a buffer, tends to produce 429s
anyway once network jitter shifts the arrival times, so the default leaves
headroom. Requests are serialized through that bucket rather than fired in
parallel, which means a broad question touching many documents gets slower
instead of blocked.

Two things worth knowing:

- The budget belongs to your **account**, not to this process. A second
  instance of the server, another integration, or a script you run yourself all
  spend from the same two per second.
- Lexware warns that a client which keeps hammering after a 429 can stay
  blocked permanently. The server therefore backs off exponentially and gives
  up after a few attempts rather than retrying harder.

The account's bucket was measured on 2026-08-21 and holds **four**: five
requests fired at once got four through and one refused. The default of `2`
leaves half of that for everything else drawing on the same account — the web
app, another integration, a second instance of this server. Raise it to `4`
only if you know this server is the only consumer.

Both limiter values are configurable via `LXO_MCP_RATE` and `LXO_MCP_BURST` if
your account behaves differently.

## Development

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

The test suite is fully offline. It mocks the HTTP layer and needs no API
key, so it runs anywhere. Three of the tests start the server as a real
subprocess and speak MCP to it over stdio, which is also what proves that
nothing writes to stdout on the startup path.

No API key ships with this repository and none belongs in CI, so a checkout
can never talk to Lexware on its own. Checking the server against the real API
is therefore always a deliberate local run with a key you supply, separate from
the suite above and never part of it:

```
uv run python tests/smoke.py
uv run python tests/smoke.py --env-file path/to/.env
```

It reads your account and writes nothing to it. The server it builds gets the
`read-only` preset, so the writing tools are not there to be called at all. It
prints what it checked, what the account had nothing for, and what failed, and
it masks record ids so the report can be pasted somewhere. `pytest` never runs
it. See [SPECS.md](SPECS.md) section 14.1 for why a live check is not a gate.

Contributions and issues are welcome once the first release is out. Until
then, [SPECS.md](SPECS.md) is the place where design decisions are recorded,
including the open questions still to be resolved against the live API.

## License

MIT. See [LICENSE](LICENSE).

## Trademarks and affiliation

This project is **not affiliated with, endorsed by, or sponsored by Lexware,
Haufe-Lexware GmbH & Co. KG, or any of their subsidiaries.** "Lexware" and
"Lexware Office" are trademarks of their respective owners and are used here
only to name the API this software integrates with, in a descriptive sense.

The software talks exclusively to the documented public API using credentials
that the account owner supplies and can revoke. Use of that API is governed by
Lexware's own terms, which you accept independently of this project.
