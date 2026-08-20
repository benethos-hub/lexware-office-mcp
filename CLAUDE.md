# Working guidelines for Claude

How to work in this repository. Read this before making changes. See
[SPECS.md](SPECS.md) for what the project is and does.

## Golden rules

1. **Read-only by default.** This server talks to a live accounting system
   holding real business records. `LXO_MCP_MODE` defaults to `read`, and
   nothing may weaken that default. Never call a write tool against an account
   that has not been explicitly confirmed as a test account — call
   `get_profile` first and check the organization.
2. **Virtual environment only.** Never the global Python or pip. A
   `uv`-created `.venv` counts, so `uv run ...` satisfies this rule. Without
   uv, invoke the project interpreter directly:
   - `.\.venv\Scripts\python.exe ...` (PowerShell)
   - `.venv/Scripts/python.exe ...` (Bash on Windows)
3. **English in the repo.** All code, comments, docstrings and documentation
   are English. Conversation with the user may be German.
4. **stdio is sacred.** stdout carries the MCP JSON-RPC stream. Never
   `print()` to stdout from server or library code, log to **stderr** only.
5. **One rate limiter.** Every outbound request passes the single
   `ratelimit.TokenBucket` that `client.py` owns — retries and pagination
   follow-ups included. The upstream limit is global across all endpoints, so a
   second bucket anywhere is a bug. See SPECS.md section 10.1.
6. **Secrets never travel.** The API key is never logged, never returned in a
   tool result, and redacted from error text. No real key, tenant ID,
   organization ID, voucher ID or customer record in any versioned file.
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
  server.py       # MCPServer instance, tool registration, CLI main()
  __main__.py     # enables `python -m benethos_lexware_office_mcp`
  config.py       # settings resolution, credential lookup
  client.py       # ALL HTTP access: auth, retries, error mapping
  ratelimit.py    # the one token bucket, clock injectable for tests
  policy.py       # permission tiers and enforcement
  formatting.py   # API JSON -> compact tool output
  payloads.py     # tool arguments -> API request bodies
  errors.py       # ToolError hierarchy
  tools/
    _base.py      # registration helper, tidies the docstring first
    <group>.py    # one module per resource group, thin tool definitions
                  # built: diagnostics, contacts, vouchers
tests/            # offline, httpx MockTransport (a read-only smoke.py is planned)
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
3. Expose it in the matching `tools/` module. The **docstring becomes the tool
   description** the model sees — write it for an LLM caller and say when to
   use this tool rather than a neighbouring one.
4. Give every parameter an `Annotated[type, Field(description=...)]`, use
   `Literal` for enums and `ge`/`le` for numeric bounds.
5. Classify it in `policy.py` (`read`, `write` or `full`). A write tool must
   not be reachable in `read` mode, at registration or at call time.
6. Record its API call cost in the tool table in SPECS.md section 8.
7. Add offline tests. Never hit the network in the suite.

Prefer grouping related endpoints behind one tool with an enum parameter over
one tool per path. Descriptions and schemas are sent on every request, so a
wide tool surface is paid for continuously.

## Verifying

- Tests: `uv run pytest -q` (must stay green, offline).
- Lint and format: `uv run ruff check .` and `uv run ruff format .`
  (CI checks `ruff format --check`).
- Types: `uv run mypy`.
- Coverage floor 80%:
  `uv run pytest --cov=benethos_lexware_office_mcp --cov-fail-under=80`.
- Inspect what the client actually sends to the model:
  ```
  uv run python -c "import asyncio,json;from benethos_lexware_office_mcp.server import mcp;print(json.dumps([t.model_dump() for t in asyncio.run(mcp.list_tools())],indent=2,default=str))"
  ```
- After changing tool signatures or docstrings, **fully restart Claude
  Desktop** (quit from the tray, not just close the window) to reload the tools.

**The gates above do not cover the upstream API changing.** The suite mocks
HTTP completely and stays green through any change in Lexware's field names or
response shapes. Verify anything new against the live API with a read-only
call before building on it, and mark unverified assumptions **(to verify)** in
SPECS.md rather than stating them as fact.

**A live check is always a manual run, never a gate.** No key ships with the
repository and none goes into CI, so anything automated has to pass with no
key, no network and no account. Never write a test that reaches the API, and
never write one that skips itself when no key is present — that reports green
while checking nothing. Live verification belongs in the separate read-only
script described in SPECS.md section 14.1.

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
