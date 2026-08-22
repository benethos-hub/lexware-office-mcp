# Unofficial Lexware Office MCP Server

[![CI](https://github.com/benethos-hub/lexware-office-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/lexware-office-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/benethos-lexware-office-mcp)](https://pypi.org/project/benethos-lexware-office-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/benethos-lexware-office-mcp)](https://pypi.org/project/benethos-lexware-office-mcp/)
[![Coverage](https://img.shields.io/badge/coverage-96%25-brightgreen)](https://github.com/benethos-hub/lexware-office-mcp/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/benethos-hub/lexware-office-mcp/blob/main/LICENSE)

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
>   use at your own risk. See [LICENSE](https://github.com/benethos-hub/lexware-office-mcp/blob/main/LICENSE).
> - For **commercial use**, review Lexware's API terms and your own retention
>   and documentation duties.

An [MCP](https://modelcontextprotocol.io) server that connects an MCP client
such as Claude Desktop to a [Lexware Office](https://www.lexware.de/) account
through the official
[public REST API](https://developers.lexware.io/docs/). Ask about invoices,
contacts, articles and vouchers in plain language, and let the client fetch
them for you.

> **Status: 0.1.0, the first release.**
> The server runs over stdio and handles contacts, vouchers and documents:
> find them, read them, create them, change them, see what is still unpaid,
> download a PDF and upload a receipt. `get_profile` answers which account
> is connected. Every tool in the table below is built, and each was
> exercised against a live account. An HTTP transport, a container image and
> a Compose file are what 0.2.0 is for. See [SPECS.md](https://github.com/benethos-hub/lexware-office-mcp/blob/main/SPECS.md) for the full
> technical specification and the roadmap.

## Why this exists

Lexware Office holds the day-to-day accounting of a small business. Most
questions about it are read questions — what is still unpaid, what did this
customer order, which receipt belongs to that expense — and those are exactly
the questions an assistant answers well once it can see the data. This server
makes that possible without exporting anything, using an API key the account
owner generates and can revoke.

## Safety first

The server points at a real accounting system, so the defaults are cautious.

**Run it read-only unless you have a reason not to.** This server can change
real accounting records - create a contact, record a voucher, issue an invoice,
attach a receipt - and it is the assistant that decides when to call such a
tool, not you. `--tools read-only` gives it everything it needs to answer
questions about the books, which is what most people want it for: search,
read, and download. Nothing in that set writes.

Turn a write tool on when you have a job for it, and know what it leaves
behind. This API cannot delete a bookkeeping voucher at all, so a wrong one
is corrected in the web app rather than withdrawn here, and a finalized
invoice is a real document with a number that has been used. If you are not
sure which tools you need, read-only is the honest starting point - the
permissions page adds one later in a click, and a client that honours
`notifications/tools/list_changed`, as Claude Desktop does, picks it up
without a restart.

- **Nothing is enabled until you say so.** A fresh installation has no
  policy file, and a server without one offers no tools at all. What this
  server may do is a decision somebody made, never a default that happened.
- **One flag per tool**, in a JSON file you write with `--tools`, tick
  through `setup`, or edit by hand. Not a level, not a group:
  `create_contact` on and `upload_file` off is an ordinary thing to want, and
  there is no combination the file cannot express.
- **What a tool costs you is visible while you decide.** Every enabled tool
  is sent to the assistant on every request, and the permissions page puts
  that number on each row.
- The file is checked twice, once when the tool list is built and again when a
  call arrives, so a stale tool list on the client cannot slip past it.
- The API key is never logged, never returned in a tool result, and redacted
  from error messages. **It belongs in the `.env` and nowhere else** — not in
  your client's configuration file, which another program owns and rewrites,
  and which is the one people screenshot when they ask for help. Nor does any
  path from your machine reach the assistant.

## Tools

**Built** means it works today. The rest are specified in
[SPECS.md](https://github.com/benethos-hub/lexware-office-mcp/blob/main/SPECS.md) and not implemented yet.

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
| `create_sales_document` | Create an invoice, quotation, credit note, order confirmation, delivery note or dunning — a draft unless you ask for it to be issued, which the assistant may only do on your explicit instruction | **built** |
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
| `delete_article` | Remove an article. The API cannot bring it back. Takes `confirm: true`, and sends nothing without it | **built** |

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

- [uv](https://docs.astral.sh/uv/getting-started/installation/), which brings
  its own Python and the `uvx` command every example below uses
- Python 3.11 or newer, if you would rather bring your own. Installing pulls
  in the MCP SDK, httpx, platformdirs and pypdfium2, the last of these to
  render PDF pages
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

**1. Install uv**, if you have not already — the
[uv installation page](https://docs.astral.sh/uv/getting-started/installation/)
covers every platform. It brings `uvx`, and that is the only thing needed
here.

**2. Configure the server.** Nothing has to be installed for this: `uvx`
fetches the package and runs it.

```bash
uvx benethos-lexware-office-mcp setup
```

That opens the interface described under
[Configuring it in a browser](#configuring-it-in-a-browser): key, settings and
one checkbox per tool. Everything it does can also be done by hand — start a
settings file with `uvx benethos-lexware-office-mcp --settings-sample >
config/.env`, put the key in it, and use `--tools` as described below.

Check that it works:

```bash
uvx benethos-lexware-office-mcp --help
```

**3. Point Claude Desktop at it** in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "benethos-lexware-office-mcp": {
      "command": "uvx",
      "args": ["benethos-lexware-office-mcp"]
    }
  }
}
```

No path from your machine appears in there, which is the point: `uvx` looks
the package up by name. Two things worth knowing about that entry:

- **Pin a version** for stability: `"args": ["benethos-lexware-office-mcp==0.1.0"]`.
  Without a pin, `uvx` takes the newest release it can resolve, and a client
  restart is enough to change what it runs.
- **`uvx` has to be on the `PATH` the client uses**, which is not always the
  one your terminal has — some GUI clients pass a reduced environment. If the
  server does not start, put the absolute path to `uvx` in `command`, and
  restart the client fully rather than reloading it.

**Would rather have a command of your own?**
`uv tool install benethos-lexware-office-mcp` gives you
`benethos-lexware-office-mcp` without the `uvx` in front, which is worth it if
you change permissions from the command line often. It buys nothing else: the
same version can be pinned either way, and a warm start differs by tens of
milliseconds. One thing to know — uv installs it into its own tool directory,
which is **not on the `PATH` of a fresh install**. It says so when it
finishes. Run `uv tool update-shell` and open a new terminal.

**From the sources instead**, to develop or to run something unreleased:

```bash
git clone https://github.com/benethos-hub/lexware-office-mcp
cd lexware-office-mcp
uv sync
uv run benethos-lexware-office-mcp setup
```

A client then needs the interpreter of that checkout's virtual environment,
`command` pointing at `.venv/Scripts/python.exe` on Windows or
`.venv/bin/python` elsewhere, with `args` of `["-m",
"benethos_lexware_office_mcp"]`.

**No key in there, on purpose.** The server finds it in the `.env`. A client's
configuration file is the wrong place for a credential: it is not yours —
another program owns it, decides where it lives and when it rewrites it. It is
the file people screenshot when they ask for help with an MCP setup, it is
readable in the client's own settings view, and it travels to the next machine
with the rest of that client's configuration. The `.env` is at least a file
this project documents, that nothing syncs on your behalf, and that the
configuration interface writes without ever showing the key back to you.

That `.env` is already the part worth being careful with. It holds a
credential for a live accounting system, so keep it out of version control,
out of shared folders and out of backups other people can read. When you stop
using the server, delete it **and revoke the key** under Extensions, Public
API — revoking is the only step that actually ends access.

**4. Restart Claude Desktop fully** — quit it from the tray rather than
closing the window. That is for the configuration file you just edited, which
a client reads once at startup, and it is what a changed setting in the `.env`
needs too — the server reads those at startup as well. It is **not** needed
for permissions: change those later and the running client is told, see
[Switching individual tools off](#switching-individual-tools-off).

## Configuring it in a browser

```bash
uvx benethos-lexware-office-mcp setup
```

Three pages on `127.0.0.1`, closed with Ctrl+C. They write the same files the
command line does, so you can use either or both. The screens are in German,
because Lexware Office is sold for German companies only, and each is named
below by what it does with its label in brackets.

**Overview** (`Übersicht`) — which `.env` and which `tools.json` are actually
in effect, what every setting resolves to and where that value came from,
whether each file exists yet, how many tools are on and what they cost. A
connection test on the button, never on page load.

**Credentials** (`Zugangsdaten`) — the API key, checked against the API before
it is saved unless you say otherwise, and the settings that are not secret. The
key is never shown back to you, never logged and never exported. If an
environment variable is setting it, the page says so, because that would
override whatever you save.

**Permissions** (`Rechte`) — one checkbox per tool, grouped, with the presets
as buttons. On a fresh installation with no policy file yet, the reading tools
come pre-ticked as a starting point — a proposal in a form, not a permission:
there is still no file and therefore still no tool until you press save, and
the page says so. Each row carries what that tool costs the assistant in
context, and the total follows your ticks: every enabled tool is sent to the
model on **every** request, so switching one on is a budget decision as well as
a permission one. Writing tools are marked, and the ones whose result the API
cannot take back are marked separately: `nur App` for a contact, which Lexware
Office deletes without ceremony, and `nur App · Buchhaltung` for a record that
enters the books. Neither means it is stuck — nothing is festgeschrieben when
it is created, and a legend on the page names the four things that do bind a
record later.

Profiles live here too. Save the current selection under a name, load it
later. Loading only fills the boxes: nothing reaches `tools.json` until you
press save. A name that is already taken is refused rather than quietly
replacing what is there — case and spacing do not make a second profile — and
replacing one is its own button beside the list. They are stored in
`tool_profiles.json` beside the policy file.

The **policy file itself** can be downloaded and read back in from the same
page — the file as it is, so it works on another installation with or
without this interface, and a `tools.json` written by `--tools` reads here.
Reading one only ticks the boxes, and saving is still a separate press. A tool
the file does not mention stays **off** and the page says how many those
are, which is what `--tools sync` does on the command line.

Two things worth knowing. It **binds `127.0.0.1` and nothing else** — the
pages have no password, which is only defensible while they cannot be reached
from another machine, so there is no option to change it. And it is a
**separate command**: the MCP server never serves HTTP, and a client such as
Claude Desktop starts that one, not this.

`--port N` moves it, `--no-browser` only prints the address, and `--env-file`
and `--tools-file` say which files it edits. Unlike everywhere else those
files do not have to exist yet.

**If your client starts the server with `--tools-file`, give `setup` the same
argument** — otherwise it edits a different file and reports success. Both
processes fix their files when they start and never change them afterwards,
and neither can see how the other was started. The overview prints the
`"args"` line that makes your client match the files the interface is
holding, which is the easier direction.

## Switching individual tools off

One JSON file decides what this server offers, and nothing else does. Either
tick the boxes under `setup` above, or start the file with

```
uvx benethos-lexware-office-mcp --tools read-only
```

which writes every tool into `tools.json`, reading ones on and the rest off,
and prints what it did. Three presets, each containing the last:

| | enables |
|---|---|
| `--tools read-only` | queries only |
| `--tools write` | and creating and updating |
| `--tools irreversible` | and deleting an article |
| `--tools sync` | changes no flag, only adds the tools the file has not heard of |

`--tools show` only reports. **`--tools-file PATH` says where to write**, and
works with all of them — `--tools write --tools-file ./tools.json` creates the
file there.

**A preset overwrites the whole file**, so hand edits are lost. Use one to
start a file, not to update one. After an upgrade brings new tools, run
`--tools sync`: it writes them in as off, leaves every flag you set alone, and
never switches anything on. That last part is why it is the only one of these
safe to run from a script.

The third step is its own because it is its own decision: what is deleted is
gone, so it should be chosen by naming it rather than by picking the largest
option. Exactly one tool carries such an effect, `delete_article`, and that is
not a temporary state of affairs — an article is the only thing this API can
delete, and there is no way to book, finalize or void anything after the fact
either.

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
edit takes effect at once in both directions — no restart. The server also
**tells the client** when the set of enabled tools changes, so it fetches the
list again by itself: Claude Desktop picks a change up while it is running.
Nothing depends on it either way, since a tool that has been switched off
cannot be called whatever list the client is still showing. If yours does not
notice, restart it — Claude Desktop by quitting it from the tray.

Each tool also declares what it is — reading or writing, which group it
belongs to, and whether what it writes can be removed again. That
classification is what `--tools read-only` selects on and what the browser
interface groups and marks by. It never decides a call: only the file does.

## Configuration

### Where a value comes from, and which one wins

Six sources, **lowest first** — a later one overrides an earlier one:

1. the built-in default
2. `.env` in the per-user configuration directory
3. `config/.env` of the checkout the server runs from, if it runs from one
4. `config/.env` and then `.env` in the working directory
5. the file `--env-file` names, which is read **after** all of those rather
   than instead of them: it was named rather than found, so it outranks them
6. **a real environment variable**, which beats every file

The last one is the one that surprises people. A setting exported in your
shell, put in a client's `env` block, or pinned in a Compose file **cannot be
changed by editing a `.env`** — not by hand, and not through `setup`. The
value is written, the file is correct, and nothing happens.

The configuration interface says so rather than letting you find out: each
setting carries a badge naming its source, and one that an environment
variable is holding is marked as such. When something you saved seems to be
ignored, that badge is the answer.

**In a container this is not an edge case.** `compose.yaml` pins the
transport, the bind address, the port and the allowed hosts as real
environment variables, because those belong to the container rather than to
the installation inside it. Everything else — the API key, the HTTP token,
the limits — is left to the config volume, which is what makes the
configuration interface able to change it.

The same order applies to the policy file, and `LXO_MCP_TOOL_POLICY` and
`--tools-file` name one directly. The interface pins whichever file it found
when it started, so the page cannot swap its own subject out from under you.

### Naming the files

`--env-file PATH` names a settings file instead of searching, and pairs with
`--tools-file` so that one entry in a client's configuration carries its own
account and its own permissions:

```json
"args": ["--env-file", "/path/to/test.env",
         "--tools-file", "/path/to/test-tools.json"]
```

A path that does not exist is refused rather than quietly falling back to the
search — except under `setup`, which exists partly to create one.

`setup` writes this file for you.

### The settings

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
| `LXO_MCP_TRANSPORT` | `stdio`, `streamable-http` or `sse` | `stdio` |
| `LXO_MCP_BEARER_TOKEN` | Shared secret every HTTP request must carry. Required for an HTTP transport | — |
| `LXO_MCP_HTTP_HOST` | Address to bind for an HTTP transport | `127.0.0.1` |
| `LXO_MCP_HTTP_PORT` | Port to bind | `8770` |
| `LXO_MCP_HTTP_PATH` | URL path the transport serves on | `/mcp` |
| `LXO_MCP_ALLOWED_HOSTS` | `Host` values to accept besides loopback, comma separated | — |
| `LXO_MCP_GENERATE_BEARER_TOKEN` | Make a token at startup if none is set and write it to the settings file | off |
| `LXO_MCP_EXIT_ON_CONFIG_CHANGE` | End the process when the settings file changes, for something that restarts it | off |

Every setting above is in use. `LXO_MCP_PAGE_SIZE` is capped at 250, which is
the lowest page size any endpoint accepts, and a larger value is refused at
startup rather than turning into an API error later.

## Transport

The first releases speak **stdio** only, which is what Claude Desktop and
comparable local clients use. An HTTP transport is planned for 0.2.0 and will
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
key, so it runs anywhere. Two kinds of test leave the process without leaving
the machine: three start the server as a real subprocess and speak MCP to it
over stdio, which is also what proves that nothing writes to stdout on the
startup path, and the configuration interface is driven through a real
loopback HTTP server with a real cookie jar, because its CSRF guards are only
worth testing the way a browser meets them.

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
it. See [SPECS.md](https://github.com/benethos-hub/lexware-office-mcp/blob/main/SPECS.md) section 14.1 for why a live check is not a gate.

Contributions and issues are welcome once the first release is out. Until
then, [SPECS.md](https://github.com/benethos-hub/lexware-office-mcp/blob/main/SPECS.md) is the place where design decisions are recorded,
including the open questions still to be resolved against the live API.

## License

MIT. See [LICENSE](https://github.com/benethos-hub/lexware-office-mcp/blob/main/LICENSE).

## Trademarks and affiliation

This project is **not affiliated with, endorsed by, or sponsored by Lexware,
Haufe-Lexware GmbH & Co. KG, or any of their subsidiaries.** "Lexware" and
"Lexware Office" are trademarks of their respective owners and are used here
only to name the API this software integrates with, in a descriptive sense.

The software talks exclusively to the documented public API using credentials
that the account owner supplies and can revoke. Use of that API is governed by
Lexware's own terms, which you accept independently of this project.
