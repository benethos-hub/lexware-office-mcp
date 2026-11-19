# Concept of the unofficial Lexware Office MCP server

> **Status: 0.10.2.** Every tool of [section 8](concept/tools.md#8-tools)
> is built, tested and exercised against a live account, and so is every module
> of [section 4](ARCHITECTURE.md), including the HTTP transport of
> [section 6](concept/transport.md#6-transport-and-runtime) and the
> configuration interface of
> [section 7.1](concept/configuration-interface.md#71-the-configuration-interface).
> The container image is published, a client has reached a live account through
> it over HTTP, and the Claude Desktop extension of
> [section 16](ROADMAP.md) has done the same from a fresh machine. Facts
> checked against a live account say so with their date, and these documents
> carry a great many of them because the API's own documentation turned out to
> be wrong more than once.

This file is the overview: what the project is, what is in scope, its
names and its conventions. Each topic has a file of its own in
[concept/](concept/), and four that stand on their own sit beside this
one. The sections keep their numbers: "section 9.2" in the code or in
another document names section 9.2, and the list below leads to it.

## The topics

| Topic | Sections | In short |
|---|---|---|
| [The upstream API](concept/upstream-api.md) | 5 | What the Lexware Office API offers and does, measured against a live account: endpoints, files, articles, recurring templates, writes, the one state transition, master data, voucher and document semantics. |
| [Transport and runtime](concept/transport.md) | 6 | stdio and HTTP, the bearer token, the host allowlist, how the process starts, runs and ends. |
| [Configuration](concept/configuration.md) | 7 and 7.2 | Every setting, where the settings file is found, and uploads from a URL. |
| [The configuration interface](concept/configuration-interface.md) | 7.1 | The local pages `setup` serves: what they show, what they write, the start code. |
| [Tools and prompts](concept/tools.md) | 8 | Every tool with its calls, the status tool, parameter conventions and the prompts. |
| [The permission model](concept/permissions.md) | 9 to 9.2 | Why the tier was removed, and the policy file that alone decides which tools exist. |
| [Client behaviour](concept/client.md) | 10 to 10.2 | The one rate limiter, and which requests are retried. |
| [Data and secrets](concept/data-and-secrets.md) | 11 and 11.1 | What never leaves the machine or enters the repository, and the test environment. |
| [Errors and output](concept/errors-and-output.md) | 12 to 13 | How a refusal becomes a `ToolError`, why it derives from the SDK's, and the shape of every answer. |
| [Testing](concept/testing.md) | 14 to 14.3 | The offline suite, the live checks, the shape captures and the SDK as a blind spot. |
| [Architecture](ARCHITECTURE.md) | 4 | The layers, every module and which may import which. |
| [Logging](LOGGING.md) | 11.2 | Every line on stderr: levels, the catalogue, what a line may never carry. |
| [Roadmap](ROADMAP.md) | 16 | What exists, release by release, how a user configures the server, and the open questions. |

Sections 1 to 3 and 15 follow below. How a release is made is in
[RELEASING.md](RELEASING.md).

## Every section

- [1 Purpose](#1-purpose)
- [2 Scope](#2-scope)
- [3 Naming](#3-naming)
- [4 Architecture](ARCHITECTURE.md)
- [5 Upstream API](concept/upstream-api.md#5-upstream-api)
- [6 Transport and runtime](concept/transport.md#6-transport-and-runtime)
- [7 Configuration](concept/configuration.md#7-configuration)
  - [7.1 The configuration interface](concept/configuration-interface.md#71-the-configuration-interface)
  - [7.2 Uploads from a URL](concept/configuration.md#72-uploads-from-a-url)
- [8 Tools](concept/tools.md#8-tools)
- [9 Permission model](concept/permissions.md#9-permission-model)
  - [9.1 Why the tier was removed](concept/permissions.md#91-why-the-tier-was-removed)
  - [9.2 The policy](concept/permissions.md#92-the-policy)
- [10 Client behaviour (`api/`)](concept/client.md#10-client-behaviour-api)
  - [10.1 Rate limiting](concept/client.md#101-rate-limiting)
  - [10.2 Retry safety](concept/client.md#102-retry-safety)
- [11 Data and secrets policy](concept/data-and-secrets.md#11-data-and-secrets-policy)
  - [11.1 Test environment](concept/data-and-secrets.md#111-test-environment)
  - [11.2 Logging](LOGGING.md)
- [12 Error handling](concept/errors-and-output.md#12-error-handling)
  - [12.1 Why `ToolError` derives from the SDK's](concept/errors-and-output.md#121-why-toolerror-derives-from-the-sdks)
- [13 Output format](concept/errors-and-output.md#13-output-format)
- [14 Testing](concept/testing.md#14-testing)
  - [14.1 Live checks are not a gate](concept/testing.md#141-live-checks-are-not-a-gate)
  - [14.2 A shape is recorded, so drift can be seen rather than remembered](concept/testing.md#142-a-shape-is-recorded-so-drift-can-be-seen-rather-than-remembered)
  - [14.3 The SDK is the second blind spot](concept/testing.md#143-the-sdk-is-the-second-blind-spot)
- [15 Conventions](#15-conventions)
- [16 Roadmap](ROADMAP.md)
  - [16.1 Answered: how a user configures the server](ROADMAP.md#161-answered-how-a-user-configures-the-server)

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

**Deliberately gated rather than excluded:** finalizing a document and deleting
an article. Both need a decision from the account owner rather than from a
model, and both are governed by the permission model in
[section 9](concept/permissions.md#9-permission-model). Booking a voucher
stood here too until 2026-08-21, when it looked like something this API cannot
do at all. On 2026-09-27 the one transition it does have turned up: an
`unchecked` voucher is booked by a PUT carrying `open`. It sits on
`update_voucher` as `finalize`, gated by `confirm` like the finalize of a sales
document - see [section 5](concept/upstream-api.md#5-upstream-api).

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
| MCP server `description`, `websiteUrl` and `icons` | what the registry entry says, sent once in the handshake for a client to show, since 2026-10-12, and `tests/test_server.py` keeps them equal |
| GitHub repo | `benethos-hub/lexware-office-mcp` (plain, for discoverability) |
| Container image | `ghcr.io/benethos-hub/benethos-lexware-office-mcp`, every release from 0.2.0 |
| Publishing environment | `pypi-benethos-lexware-office-mcp` |
| MCP Registry entry | `io.github.benethos-hub/benethos-lexware-office-mcp`, from 0.5.1 |
| Env var prefix | `LXO_MCP_` |
| README H1 | `# Unofficial Lexware Office MCP Server`, the icon from `assets/` before it |

"Lexware Office" is spelled out in prose because it names the integrated API,
not this project. No Lexware logos, brand colors, or domains containing
"lexware" are used, and the README carries a non-affiliation notice.

## 15. Conventions

- Everything in the repository is English: code, comments, docstrings and
  documentation. Conversation with the user may be German. **One exception:**
  the text a person reads on screen in `configui/` is German, because Lexware
  Office is sold for German companies only and its own help centre rules out an
  Austrian or Swiss account holder, see
  [section 7.1](concept/configuration-interface.md#71-the-configuration-interface).
  Code, comments and docstrings in that package are English like everywhere
  else, and a message raised outside it is quoted into the page rather than
  translated.
- Type hints everywhere, `from __future__ import annotations` at the top of
  every module.
- Virtual environment only, never the global interpreter. `uv sync --extra dev`
  is the recommended setup.
- `CHANGELOG.md` gets an entry under `[Unreleased]` in the same commit as the
  change it describes.
- No semicolons in prose.
- The commit identity is configured repo-locally rather than documented here,
  so a clone cannot silently inherit a different one from a global git config.
