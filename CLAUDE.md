# Working guidelines for Claude

How to work in this repository. Read this before making changes. See
[SPECS.md](SPECS.md) for what the project is and does.

## Golden rules

1. **Nothing is enabled by default.** This server talks to a live accounting
   system holding real business records. The `tools.json` policy file is the
   only thing that decides which tools exist, a tool it does not name is off,
   and an installation without the file offers none at all. Nothing may weaken
   that: no tool may register itself past the file, and no default may stand
   in for a decision nobody made. Never call a write tool against an account
   that has not been explicitly confirmed as a test account — call
   `get_profile` first and check the organization.
2. **Virtual environment only.** Never the global Python or pip. A
   `uv`-created `.venv` counts, so `uv run ...` satisfies this rule. Without
   uv, invoke the project interpreter directly:
   - `.\.venv\Scripts\python.exe ...` (PowerShell)
   - `.venv/Scripts/python.exe ...` (Bash on Windows)
3. **English in the repo.** All code, comments, docstrings and documentation
   are English. Conversation with the user may be German. **One exception,
   and only one:** the text a person reads on screen in `configui/` is
   German, because that interface has exactly one audience and Lexware Office
   is sold for German companies only. Code, comments and docstrings there are
   English like everywhere else, and a message raised outside `configui/` is
   quoted into the page rather than translated — a German paraphrase would be
   a second copy of a rule that lives in the code.
4. **stdio is sacred.** stdout carries the MCP JSON-RPC stream. Never
   `print()` to stdout from server or library code, log to **stderr** only.
5. **One rate limiter.** Every outbound request passes the single
   `ratelimit.TokenBucket` that `client.py` owns — retries and pagination
   follow-ups included. The upstream limit is global across all endpoints, so a
   second bucket anywhere is a bug. See SPECS.md section 10.1. **A throwaway
   probe script is not an exception**: build a `LexwareClient` rather than a
   bare `httpx.AsyncClient`, or the third request comes back 429 and the
   account has been told this key misbehaves.
6. **Secrets never travel.** The API key is never logged, never returned in a
   tool result, and redacted from error text. No real key, tenant ID,
   organization ID, voucher ID or customer record in any versioned file.
   **Nor does a filesystem path of this machine.** Anything handed to the
   client ends up in a model's context: a path carries a user name and a
   directory layout, and the caller cannot act on it anyway. Say what to set
   or which command to run, and let stderr name the file for the person
   sitting at the machine. The one exception is a path the caller supplied
   or asked for, such as a download's destination.
7. **The repo stands on its own.** State a convention as this project's
   decision. Do not reference the author's other repositories, local
   filesystem paths, or email addresses in versioned files.

## Environment

- Windows, PowerShell or Bash. Python 3.11-3.14.
- Set up: `uv sync --extra dev`. Without uv: `py -m venv .venv` then
  `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`.
- Run the server (stdio): `uv run benethos-lexware-office-mcp`, or
  `.\.venv\Scripts\python.exe -m benethos_lexware_office_mcp`.
- `LXO_MCP_API_KEY` must be set for anything that talks to the API. The test
  suite does not need it.

## Project layout

The planned structure, see SPECS.md section 4 for the full table.

```
src/benethos_lexware_office_mcp/
  server.py       # PolicyServer (an MCPServer that lists what the policy allows)
  __main__.py     # enables `python -m benethos_lexware_office_mcp`
  config.py       # settings resolution, credential lookup
  client.py       # ALL HTTP access: auth, retries, error mapping
  ratelimit.py    # the one token bucket, clock injectable for tests
  policy.py       # the tool policy file, and what a tool declares itself to be
  formatting.py   # API JSON -> compact tool output
  payloads.py     # tool arguments -> API request bodies
  storage.py      # where downloads land, filenames made safe first
  resources.py    # downloads published as MCP resources for the client
  rendering.py    # PDF pages -> PNG, the only module touching pypdfium2
  errors.py       # ToolError hierarchy
  envfile.py      # reading and writing a .env, comments left alone
  configui/       # the local configuration interface, `setup` serves it
                  # render, state, cost, probe, profiles, transfer,
                  # pages, app - never part of the MCP server process
  tools/
    _base.py      # registration helper, tidies the docstring first
    <group>.py    # one module per resource group, thin tool definitions
                  # built: diagnostics, contacts, vouchers,
                  #        sales_documents, files, master_data
tests/            # offline, httpx MockTransport
  smoke.py        # read-only live check, run by hand, never collected
```

Keep the layers separate: **tools stay thin** and delegate to `client.py`. Any
new HTTP call goes in `client.py`, never in a tool function.

## How to add or change a tool

1. Add the request to `client.py`, using `request()` so the shared limiter and
   the retry rules apply automatically. Never retry a POST yourself. Map
   the upstream status to the right `ToolError` subclass, and pass the page
   parameters through rather than walking every page.
2. Normalize the response in `formatting.py`. Drop null and empty fields, keep
   monetary values exactly as the API returned them, and always carry the
   currency. A paged list goes through `formatting.page`, so every list tool
   answers with the same envelope. A tool that **writes** builds its request
   body in `payloads.py`, never inline: an update has to read the record and
   merge, because the API replaces rather than patches.
3. Expose it in the matching `tools/` module, then write the docstring by the
   rule below.
4. Give every parameter an `Annotated[type, Field(description=...)]`, use
   `Literal` for enums and `ge`/`le` for numeric bounds.
5. Classify it with `@classify(access, domain)` — `read` or `write`, plus
   the group it belongs to, `effect` for a write tool, and `permanence` when
   what it writes cannot be removed through the API: `"app"` when only the
   web app can delete it, `"books"` when it is a bookkeeping record that can
   later be bound by a Festschreibung. Neither says the record is permanent
   at the moment it is written, see SPECS.md section 9.2. All of it is
   metadata for whoever writes the policy file, never a permission: the file
   alone decides. A new tool is **off** until the file
   names it, so run `--tools` after adding one, or it will not appear.
6. Record its API call cost in the tool table in SPECS.md section 8.
7. Add offline tests. Never hit the network in the suite.

Prefer grouping related endpoints behind one tool with an enum parameter over
one tool per path. Descriptions and schemas are sent on every request, so a
wide tool surface is paid for continuously.

## Writing a tool description

The **docstring becomes the tool description** the model reads, and it is sent
on **every** request for the life of the server. It is not documentation. It
is a briefing for a caller deciding, right now, whether to call this tool and
with what.

**Put in only what changes a decision:**

- what the tool does, in one line
- what it costs in API calls
- when to use it instead of a neighbouring tool, and what to fetch first
- how to read the result where that is not obvious from the schema
- what the API cannot take back, which is not the same as what cannot be
  undone: this server speaks for one interface, and the web app usually has
  a way. Say what this tool's caller can and cannot reach.

**Leave out:**

- **why** it is built this way. Design reasoning belongs in SPECS.md. A caller
  cannot act on it and pays for it every time.
- behaviour the caller has no choice about. That a download never overwrites
  is true and worth documenting — in the README, not here.
- anything the schema already says. Types, defaults and enum values are in the
  schema, so repeating them in prose buys nothing.

**Budget: under 700 characters.** Not a style rule but a ceiling that a
rewrite into explanation will cross. When one grows past it, the fix is
usually to move a paragraph into SPECS.md rather than to compress the wording.

Nothing enforces this automatically, deliberately: a character count is a poor
judge of whether a sentence earns its place, and a test would turn the
judgement into a number to be gamed. Look at the lengths when you touch a
docstring:

```
uv run python -c "import asyncio;from benethos_lexware_office_mcp.server import mcp;print(sorted(((len(t.description or ''),t.name) for t in asyncio.run(mcp.list_tools())),reverse=True))"
```

It lists what the policy file enables, so run it with a file that has
everything on or a tool you just touched will be missing from the answer.

The whole cost of the tool list, which is what a description is spent
against - schemas included, and they are the larger half:

```
uv run python -c "import asyncio,json;from benethos_lexware_office_mcp.server import mcp;print(sum(len(json.dumps(t.model_dump(exclude_none=True,by_alias=True),separators=(',',':'),default=str)) for t in asyncio.run(mcp.list_tools())))"
```

Section 8 of SPECS.md records the same rule, and carries the last
measurement of what the whole list costs.

## Verifying

- Tests: `uv run pytest -q` (must stay green, offline).
- Lint and format: `uv run ruff check .` and `uv run ruff format .`
  (CI checks `ruff format --check`).
- Types: `uv run mypy`.
- Lockfile in step with `pyproject.toml`: `uv lock --check`.
- The coverage badge in the README is **static** on purpose, so nothing
  updates it. Re-read the percentage below and adjust it whenever it moves.
- Coverage floor 80%:
  `uv run pytest --cov=benethos_lexware_office_mcp --cov-fail-under=80`.
  Add `--no-sync` while a client is running this server from the checkout:
  `--cov` reinstalls the package first, and a running server holds the console
  script open, so the run fails on a locked file rather than on a test.
- Inspect what the client actually sends to the model:
  ```
  uv run python -c "import asyncio,json;from benethos_lexware_office_mcp.server import mcp;print(json.dumps([t.model_dump() for t in asyncio.run(mcp.list_tools())],indent=2,default=str))"
  ```
- After changing tool signatures or docstrings, **fully restart Claude
  Desktop** (quit from the tray, not just close the window) to reload the tools.
- The configuration interface renders without a browser, so a change to a
  page can be read as text:
  ```
  uv run benethos-lexware-office-mcp setup --no-browser --port 8790       --env-file scratch/.env --tools-file scratch/tools.json
  ```
  Point it at scratch files rather than at your own configuration - it
  writes what it is told to write. Its tests cover the pages and the routes,
  so a rendering change that matters should fail one of them first.

**The gates above do not cover the upstream API changing.** The suite mocks
HTTP completely and stays green through any change in Lexware's field names or
response shapes. Verify anything new against the live API with a read-only
call before building on it, and mark unverified assumptions **(to verify)** in
SPECS.md rather than stating them as fact.

**A live check is always a manual run, never a gate.** No key ships with the
repository and none goes into CI, so anything automated has to pass with no
key, no network and no account. Never write a test that reaches the API, and
never write one that skips itself when no key is present — that reports green
while checking nothing. Live verification belongs in `tests/smoke.py`:

```
uv run python tests/smoke.py
```

It is read-only, builds its server with the `read-only` preset so a writing
tool is not there to be called, and reports a check it could not run as
skipped rather than as passed. Add to it whenever a live measurement is worth
repeating. See SPECS.md section 14.1.

## Conventions

- Type hints everywhere, `from __future__ import annotations` at the top.
- Surface expected failures as `ToolError` subclasses with concise messages.
  Never leak a raw traceback to the client.
- Keep responses small. The client's token budget is a real constraint.
- **No semicolons in prose** — README, docstrings, commit messages, docs. Code
  is unaffected.
- `CHANGELOG.md` gets an entry under `[Unreleased]` in the same commit as the
  change it describes, never in a later pass. It records what changed **for
  someone using this server** — tools, parameters, output, configuration,
  behaviour, dependencies, packaging. It is not a work log. Conversations,
  research, decisions that were considered and dropped, and edits to the
  development guidelines do **not** get an entry. Where such a thing matters,
  it belongs in `SPECS.md` as a design decision or in `README.md` as something
  a user needs to know, and if it belongs in neither it does not belong in the
  repository at all.

## Git and commits

- Commit only when the user asks. Clear, descriptive messages.
- The commit identity is configured repo-locally. Verify it survives a
  re-clone or re-init, because a global identity would otherwise be used
  instead.
- End commit messages with
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Ship changes on a branch. One work stream, one branch — a branch covers the
  piece of work being done including the fixes found along the way, not one
  branch per file. Open the next branch when the *topic* changes, not when the
  file does.
- **A branch carries as many commits as the work needs.** Commit whenever
  something is worth recording, but do not treat every commit as the end of the
  work stream. Corrections, review findings and documentation about the work
  itself — a changelog entry, a README the branch just made wrong — belong on
  the same branch. What does not is a **new subject**: specifying a feature this
  branch is not building is its own work stream, even though it is only a
  document. Say so before writing it, rather than adding it quietly.
- **While the project has no remote**, merge into `main` yourself once the work
  stream is genuinely finished — the feature works, the gates are green, and
  nothing about it is still open. Then delete the branch. Merging after each
  commit defeats the point of branching. Once a remote exists, the merge goes
  through a pull request instead and `main` is no longer written directly.
