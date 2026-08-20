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

- **Read-only by default.** Out of the box the server registers read tools
  only. Nothing can be created, changed or deleted.
- Write tools appear only when the account owner sets `LXO_MCP_MODE=write`,
  and the irreversible operations — finalizing a document, booking a voucher,
  deleting an article — need `full` on top of an explicit `confirm` argument.
- The permission tier is checked twice, once when tools are registered and
  again when a call arrives, so a stale tool list on the client cannot slip
  past it.
- The API key is never logged, never returned in a tool result, and redacted
  from error messages.

## Tools

**Built** means it works today. The rest are specified in
[SPECS.md](SPECS.md) and not implemented yet.

Read tools, available in every mode:

| Tool | What it does | Status |
|---|---|---|
| `get_profile` | Company profile and connection check | **built** |
| `search_contacts` | Find customers and vendors by name, email, number or role | **built** |
| `get_contact` | One contact with addresses, roles and version | **built** |
| `search_articles` | Find articles by title, number or GTIN | planned |
| `get_article` | One article | planned |
| `search_vouchers` | The central query — filter the voucher list by type, status, contact, date range and what is still open | **built** |
| `get_sales_document` | Read an invoice, quotation, credit note, order confirmation, delivery note, dunning or down payment invoice | planned |
| `get_voucher` | Read a bookkeeping voucher, by id or by its document number | **built** |
| `get_payments` | Payment status and open amount of a voucher | **built** |
| `get_recurring_templates` | Recurring invoice templates | planned |
| `get_master_data` | Countries, payment conditions, posting categories, print layouts | planned |
| `download_document` | Save the rendered PDF or XML of a sales document | **built** |
| `download_file` | Save a stored file, such as an uploaded receipt | **built** |
| `get_deeplink` | Build a permalink into the Lexware Office web app, without an API call | **built** |

Write tools, only with `LXO_MCP_MODE=write` or higher:

| Tool | What it does | Status |
|---|---|---|
| `create_contact` | Create a customer or vendor | **built** |
| `update_contact` | Change one, without touching what you did not name | **built** |
| `create_article`, `update_article` | Create and update articles | planned |
| `create_voucher` | Record a bookkeeping voucher | **built** |
| `update_voucher` | Change one that is already recorded | **built** |
| `create_sales_document` | Create a document, as a draft unless finalization is explicitly requested | planned |
| `upload_file` | Upload a receipt, which also creates its voucher | **built** |

`update_contact` and `update_voucher` cost two API calls rather than one.
The API replaces a record instead of patching it, so the current one is read
first and the change is laid on top. Without that, changing only an email
address would empty out the addresses, the note and everything else. Both
also need the `version` you last read: if the record changed in between, the
update is refused and nothing is written.

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

`upload_file` accepts PDF, JPEG, PNG and XML, at most 5 MiB per file, which
is what the API takes. An XML file is treated as an XRechnung and is
rejected if it is not one.

## Requirements

- Python 3.11 or newer
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

## Configuration

| Variable | Meaning | Default |
|---|---|---|
| `LXO_MCP_API_KEY` | Your Lexware Office API key. Required. | — |
| `LXO_MCP_MODE` | `read`, `write` or `full` | `read` |
| `LXO_MCP_BASE_URL` | API base URL | `https://api.lexware.io` |
| `LXO_MCP_APP_BASE_URL` | Web app base for deeplinks | `https://app.lexware.de` |
| `LXO_MCP_DOWNLOAD_DIR` | Where downloaded documents land | user cache directory |
| `LXO_MCP_TIMEOUT` | HTTP timeout in seconds | `30` |
| `LXO_MCP_RATE` | Requests per second, global across all endpoints | `1.5` |
| `LXO_MCP_BURST` | Token bucket capacity | `2` |
| `LXO_MCP_PAGE_SIZE` | Rows per page a search requests and returns | `25` |
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
the suite above and never part of it. A read-only smoke script for that is
planned and does not exist yet, see [SPECS.md](SPECS.md) section 14.1.

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
