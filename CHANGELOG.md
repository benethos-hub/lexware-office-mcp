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
- `LICENSE` — MIT.
- Repository scaffolding: `.gitignore` and `.gitattributes` (LF in the index,
  native on checkout).

### Notes

No code yet. The project is in the design phase, and section 16 of `SPECS.md`
lists the open questions that must be answered against the live API before
0.1.0 can be implemented.
