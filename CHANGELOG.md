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

Nothing has been released yet. This section describes what 0.1.0 will contain.

### Added

- **`get_profile`** — the first tool. Shows which Lexware Office account the
  server is connected to: organization, company name, tax setup, small-business
  status and the enabled business features. Doubles as the connection check,
  and costs one API call. The email address of the user who created the
  account, which the API returns alongside, is dropped rather than handed on.
- **The server itself** — installable as `benethos-lexware-office-mcp`, started
  through the console script of the same name or
  `python -m benethos_lexware_office_mcp`. Speaks **stdio**, which is what
  Claude Desktop and comparable local clients use. `--mode`, `--log-level` and
  `--version` on the command line, each winning over its environment variable.
- **Read-only by default.** Three permission tiers, `read`, `write` and `full`,
  selected with `--mode` or `LXO_MCP_MODE`. Enforced twice: a tool above the
  active tier is never registered, so it does not appear in the tool list at
  all, and the tier is checked again when a call arrives, so a client holding a
  stale list cannot get one through.
- **Configuration** from a real environment variable, a `.env` in the working
  directory, `config/.env` in the working directory, `config/.env` of the clone
  the server runs from, or a `.env` in the per-user config directory, in that
  order of precedence. The fourth rule means a clone configures itself no
  matter which directory it is started from, which is what a client such as
  Claude Desktop needs. Settings: `LXO_MCP_API_KEY`, `LXO_MCP_MODE`,
  `LXO_MCP_BASE_URL`, `LXO_MCP_APP_BASE_URL`, `LXO_MCP_DOWNLOAD_DIR`,
  `LXO_MCP_TIMEOUT`, `LXO_MCP_RATE`, `LXO_MCP_BURST`, `LXO_MCP_PAGE_SIZE` and
  `LXO_MCP_LOG_LEVEL`. Values are validated when they are read, so a page size
  the API would refuse fails at startup rather than mid-conversation.
- **`config/.env.sample`** — a commented sample listing every setting with its
  default and the reasoning behind it. Copy it to `config/.env` and fill in the
  key. That copy is gitignored, the sample is committed and holds no key.
- **Rate limiting that matches the account, not the endpoint.** The Lexware
  limit of two requests per second covers the whole API at once, so the server
  keeps a single token bucket that every request passes, retries included. It
  refills slightly below the documented rate by default, because the API
  documentation warns that aiming exactly at the limit still produces 429s once
  network jitter shifts the timing. Repeated rate limiting holds the bucket
  shut for a cool-down instead of hammering a limit that can block a key
  permanently.
- **Retries that cannot duplicate a document.** A failed `POST` is never
  repeated: a 5xx or a timeout does not say whether the invoice was created,
  and a duplicate with a consecutive number is not something the caller can
  undo. It is reported with its outcome marked unknown instead. A 429 is safe
  to repeat for any method, because the documentation states the call was not
  performed.
- **Errors written for the caller**, not stack traces: the key was rejected,
  the record changed since it was read, the resource does not exist. The API
  key is redacted from every message, and monetary values are passed through
  exactly as the API reported them, always with their currency.
- `README.md` and `LICENSE` (MIT).

### Not yet

Only `get_profile` exists. Searching contacts, articles and vouchers, reading
sales documents, downloading PDFs and every write operation are specified but
not built — see the roadmap in [SPECS.md](SPECS.md) section 16, along with the
questions still open against the live API. The HTTP transport is planned for
0.3.0 and will ship with its own authentication in front of the API key.
