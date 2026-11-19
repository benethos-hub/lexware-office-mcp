# Concept: data and secrets

Part of the [concept](../CONCEPT.md): sections 11 and 11.1.

## 11. Data and secrets policy

These rules are absolute for this repository.

- Real API keys live only in `.env` files that are gitignored. Never in code,
  documentation, tests, commit messages or memory files.
- **Nothing this project writes ever recommends putting the key in a client's
  configuration file.** An MCP client will happily pass one through an `env`
  block, and the README showed that until 2026-08-22. It is the worse of the
  two places by some way: the file belongs to another program, which decides
  where it lives and when it rewrites it, it is readable in that client's own
  settings view, it travels to the next machine with the rest of that
  client's configuration, and it is the file people paste into a forum when
  an MCP setup will not start. The `.env` is documented here, synced by
  nothing, and written by the configuration interface without the key ever
  being displayed. Neither is a secret store, and the documentation says so
  rather than implying the `.env` is safe.
- Real tenant, organization, contact and voucher IDs never appear in versioned
  files. Documentation uses placeholders.
- **No filesystem path of the host machine is handed to the client.** Every
  message a tool returns reaches a model's context, and a path carries a user
  name and a directory layout with it while telling the caller nothing it can
  act on. A refusal names the tool and what to set, not the file. The person
  who can edit the file is at the machine, where stderr and the configuration
  interface both name it. The exception is a path the caller supplied or
  asked for — `download_file` answers with where it wrote the bytes, which is
  the point of calling it.
- **A URL an upload is fetched from is a capability, like a token.** A signed
  link carries its key in the path or the query, and is as good as the key for
  as long as it lives. A log line names its scheme and host, never more, and
  the host only where `LXO_MCP_UPLOAD_URLS` allows it - one outside was chosen
  by the model, and its line names the scheme alone. The Lexware key never
  travels with a fetch: its client is not the API's, see
  [section 7.2](configuration.md#72-uploads-from-a-url).
- Downloaded documents are real business records. They go to the download
  directory, which is gitignored, and are never committed.
- **What one installation is allowed to do is not a property of the code**,
  so `tools.json` and the `tool_profiles.json` beside it are gitignored under
  both their names — bare and under `config/`. A committed policy file would
  hand the next clone a set of permissions nobody there decided on, and a
  committed profile would describe somebody's account arrangement.
- When summarizing an API response into a lasting file, real values are
  replaced by placeholders first.
- **Write operations are exercised against a Lexware account the user has
  explicitly confirmed as a test account.** There is no technical guard on the
  API side once a key has write access, only care at the call site. Before any
  write during development, `get_profile` is called and the returned
  organization checked against the confirmed one.

### 11.1 Test environment

**There is no sandbox.** The API is exposed by a single gateway at
`https://api.lexware.io`, and the reference documentation contains no notion of
a staging or sandbox host. Every call, from any key, reaches the production
system.

What Lexware offers instead is a **test account**, and the vendor recommends it
for exactly this purpose: "Wir empfehlen für die Entwicklung von Anbindungen,
welche die Public API verwenden, die Verwendung von Lexware Office
Test-Accounts." They can be created at any time, are free of charge, and are
valid for **30 days**. Aside from a few exclusions such as Elster they provide
the full feature set of the Lexware XL edition.

Three consequences follow, and they shape how this project is developed.

- **The isolation is the account, not the URL.** A test key and a live key
  differ only in their value, and both address the same base URL. Nothing on
  the wire distinguishes them, so a wrong key in the environment reaches real
  bookkeeping with no warning. This is precisely why `get_profile` is called
  and its organization checked before any write, rather than trusted to
  configuration.
- **A test account expires after 30 days.** Nothing may depend on data
  surviving in it. Test fixtures live in the repository as anonymized copies of
  response shapes, never as records that have to exist upstream, and the
  offline suite must stay runnable with no account at all.
- **An empty account answers few questions.** The open questions about page
  sizes and bucket capacity need an account holding enough contacts and
  vouchers to paginate. A freshly created test account has to be populated
  before it can measure anything.

**Confirmed on 2026-08-20:** an API key can be generated inside a test
account, and it reaches the ordinary production endpoints. A key from a
freshly created test account returned its profile, paged the voucher list and
read master data. This was open question 8, and it was the one everything else
depended on.
