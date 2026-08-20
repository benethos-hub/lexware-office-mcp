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

> **Status: design phase.**
> This repository currently contains the specification and this README. There
> is no installable package yet. Everything below describes the intended
> shape and is subject to change until 0.1.0 ships. See
> [SPECS.md](SPECS.md) for the full technical specification and the roadmap.

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

## Planned tools

Read tools, available in every mode:

| Tool | What it does |
|---|---|
| `get_profile` | Company profile and connection check |
| `search_contacts` | Find customers and vendors by name, email or number |
| `get_contact` | One contact with addresses and roles |
| `search_articles` | Find articles by title, number or GTIN |
| `get_article` | One article |
| `search_vouchers` | The central query — filter the voucher list by type, status, contact and date range |
| `get_sales_document` | Read an invoice, quotation, credit note, order confirmation, delivery note, dunning or down payment invoice |
| `get_voucher` | Read a bookkeeping voucher |
| `get_payments` | Payment status and open amount of a voucher |
| `get_recurring_templates` | Recurring invoice templates |
| `get_master_data` | Countries, payment conditions, posting categories, print layouts |
| `get_document_pdf` | Render a document and optionally save the PDF |
| `download_file` | Download a stored file by its ID |
| `get_deeplink` | Build a permalink into the Lexware Office web app |

Write tools, only with `LXO_MCP_MODE=write` or higher:

| Tool | What it does |
|---|---|
| `create_contact`, `update_contact` | Create and update customers and vendors |
| `create_article`, `update_article` | Create and update articles |
| `create_voucher`, `update_voucher` | Create and update bookkeeping vouchers |
| `create_sales_document` | Create a document, as a draft unless finalization is explicitly requested |
| `upload_file` | Upload a receipt |

## Requirements

- Python 3.11 or newer
- A Lexware Office account with the public API add-on enabled
- An API key from <https://app.lexware.de/addons/public-api>

## Getting an API key

1. Sign in to Lexware Office as the account owner.
2. Open the public API add-on at
   <https://app.lexware.de/addons/public-api>.
3. Create a key and copy it once — it is shown a single time.
4. Keep it out of any file that goes into version control. The server reads it
   from the environment or from a `.env` in your user config directory.

A key can be revoked on the same page at any time, which is the fastest way to
cut access if anything looks wrong.

## Planned installation

Once 0.1.0 is published:

```powershell
# Windows (PowerShell)
py -m venv "$env:USERPROFILE\mcp-lexware"
& "$env:USERPROFILE\mcp-lexware\Scripts\python.exe" -m pip install benethos-lexware-office-mcp
```

```bash
# Linux / macOS
python3 -m venv ~/mcp-lexware
~/mcp-lexware/bin/python -m pip install benethos-lexware-office-mcp
```

Then point Claude Desktop at it in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "lexware-office": {
      "command": "C:\\Users\\<you>\\mcp-lexware\\Scripts\\python.exe",
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

The test suite is fully offline. It mocks the HTTP layer and needs no API key,
so it can run in CI and on any machine. A separate read-only smoke script
exists for manual checks against a live account.

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
