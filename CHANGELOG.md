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

### Added

- `SPECS.md` — full technical specification: purpose and scope, naming, module
  layout, the upstream API surface, transport plan, configuration, the tool set
  per phase with its API call cost, the three-tier permission model, client
  behaviour, error mapping, output format, test strategy, roadmap and open
  questions. Notable decisions recorded there:
  - a **single process-wide token bucket**, because the upstream limit of 2
    requests per second is global across all endpoints rather than per endpoint
  - **method-aware retries**: a failed POST is never repeated, since a 5xx or
    timeout does not reveal whether the document was created and a duplicate
    invoice cannot be undone by the client
  - **no sandbox exists**, so development happens against free 30-day test
    accounts and the isolation comes from the account rather than the URL
- `README.md` — disclaimer block below the title, project overview, safety
  model, planned tools, API key setup, configuration reference, rate limit
  explanation and trademark notice.
- `CLAUDE.md` — working guidelines: golden rules, environment, the recipe for
  adding a tool, verification gates, conventions and the branch workflow.
- Installable package `benethos-lexware-office-mcp` with the console script of
  the same name and `python -m benethos_lexware_office_mcp`. Speaks stdio.
- Configuration from the environment, from a `.env` in the working directory,
  from `config/.env`, or from a `.env` in the per-user config directory, in
  that order of precedence: `LXO_MCP_API_KEY`, `LXO_MCP_MODE`, `LXO_MCP_BASE_URL`,
  `LXO_MCP_APP_BASE_URL`, `LXO_MCP_DOWNLOAD_DIR`, `LXO_MCP_TIMEOUT`,
  `LXO_MCP_RATE`, `LXO_MCP_BURST`, `LXO_MCP_PAGE_SIZE`, `LXO_MCP_LOG_LEVEL`.
- **`get_profile`**, the first tool. Shows which Lexware Office account the
  server is connected to and doubles as the connection check. Costs one API
  call.
- HTTP client for the API, with the single shared token bucket every request
  passes, retries decided per method and failure mode, and upstream statuses
  mapped onto concise errors. A failed POST is reported with its outcome
  marked unknown rather than retried. Repeated rate limiting trips a breaker
  that holds the bucket shut instead of hammering the API.
- `config/.env.sample` — a commented sample listing every setting with its
  default. Copy it to `config/.env` and fill in the key. The copy is
  gitignored, the sample is committed and holds no key.
- Permission tiers `read`, `write` and `full`, selectable with `--mode` or
  `LXO_MCP_MODE` and defaulting to `read`. Enforced twice: a tool above the
  tier is never registered, and the tier is checked again when a call arrives.
- Error hierarchy reported to the client, with the API key redacted from every
  message. A write whose outcome is unknown says so explicitly instead of
  looking like a clean failure.
- `LICENSE` — MIT.
- Repository scaffolding: `.gitignore` and `.gitattributes` (LF in the index,
  native on checkout).

### Notes

No code yet. The project is in the design phase, and section 16 of `SPECS.md`
lists the open questions that must be answered against the live API before
0.1.0 can be implemented.
