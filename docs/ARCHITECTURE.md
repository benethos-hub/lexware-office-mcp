# Architecture

Section 4 of the [concept](CONCEPT.md).

```
a person   --browser-->  configui/ (setup, localhost, on request only)
                                             |  writes the .env and tools.json
                                             |  the server reads
                                             v
MCP client --stdio/HTTP--> transport/ --> server.py (PolicyServer)
                                             |  policy.py decides, on every
                                             |  listing and every call
                                             v
                                        tools/*.py (thin definitions)
                     +-----------------------+----------------------+
                     v                       v                      v
                 records/                  api/                  files/
             types, payloads,     client: one method per    storage, fetch,
             formatting           endpoint. connection:     resources,
                                  auth, retries, the one    rendering, delivery
                                  ratelimit.TokenBucket          |
                                             |                   | an upload's URL,
                                             v                   v if allowed
                               https://api.lexware.io/v1/...   another service

beneath every layer: errors.py, settings/, logbook/ (stderr only)
```

| Module | Responsibility |
|--------|----------------|
| `server.py` | The `PolicyServer`, an `MCPServer` listing only what the policy file allows, and `build_server`, which makes one from the settings and fills the tool registry. |
| `cli.py` | The console script and `python -m`: the arguments, `--tools`, `setup`, `--settings-sample`, what a start reports on stderr, and handing the server to the transport the command line asked for. |
| `__main__.py` | Enables `python -m benethos_lexware_office_mcp`. |
| `__init__.py` | `__version__`, read from the installed distribution, which every module may import. |
| `py.typed` | Says the package ships its type hints. |
| `env.sample` | The commented settings sample, shipped with the package so that `--settings-sample` prints it. `tests/test_env_sample.py` holds it to what the loader reads. |
| `errors.py` | `ToolError` and its subclasses, and `redact`, which every message passes on its way out. Every layer raises these, so the module depends on nothing else in the package. |
| `settings/` | Settings resolution and credential lookup, see [section 7](concept/configuration.md#7-configuration) for the precedence. `Settings` and `load_settings` in the package itself, `locations` for the directories, the search and the one file that applies, `parse` for reading one value and the path rule a setting shares with a fetched URL, `envfile` for the file itself. |
| `settings/envfile.py` | Reading a `.env` and writing one back without disturbing comments, ordering or settings this project knows nothing about. One parser, used by the server and by the interface, so a displayed value cannot differ from a read one. |
| `logbook/` | Every line on stderr, see [section 11.2](LOGGING.md). `output` is the one handler and the levels, `access` cuts uvicorn's request line down, `tally` counts a tool call's API calls, `_describe` says what of an exception or an id a line may carry, and `lifecycle`, `policy`, `api`, `calls`, `files` and `configui` are the catalogue: one function per line, and no other module imports `logging`. |
| `records/types.py` | Every enumeration a tool takes and every model its arguments are built from, plus the two models the file tools answer with. The schema a client sees is generated from these, so this is the vocabulary of the whole tool list, in one place. |
| `records/payloads.py` | Tool arguments to API request bodies. The other direction from `formatting.py`, and not symmetric with it: a response is trimmed, a request has to be complete. See [section 5](concept/upstream-api.md#5-upstream-api) on why an update starts from the record it is changing. |
| `records/formatting.py` | API JSON to compact, token-frugal tool output, including the page envelope every list endpoint shares. |
| `api/connection.py` | The mechanics of every request: auth header, rate limiting, retry and backoff, the breaker after repeated 429s, and a refusal handed to `refusal.from_response`. Nothing else talks to the API. |
| `api/client.py` | `LexwareClient`, a connection with one method per endpoint, and `ClientProvider`, which hands out the one client a process may have, so every tool shares one connection pool and one rate limiter. It also holds `Health`, what the status check of [section 8](concept/tools.md#8-tools) last found, and carries the transport an upload fetched from a URL travels by, which only the test suite sets. Here rather than as an argument of `build_server`, decided 2026-10-16: `files` may not import `api`, the upload tools hold the provider already, and a second path into the server for one test seam would cost more than it says. |
| `api/ratelimit.py` | The token bucket, with an injectable clock so it can be tested against virtual time. |
| `api/refusal.py` | `from_response`, which reads a refused request's body for the field it blames in the two shapes the API uses, and picks the `ToolError` that says so. |
| `files/storage.py` | Where downloads land on disk, how a file is read for upload, and the one check every upload passes, read or fetched: its size, its type, and a name whose extension says that type. Its own module because the filename comes from the server and is treated as untrusted input, because a file whose contents differ is never overwritten, because one whose contents match is reused rather than copied, and because the directory is a cache kept to its newest downloads, see [section 13](concept/errors-and-output.md#13-output-format). |
| `files/fetch.py` | An upload fetched from a URL instead of read from disk, under `LXO_MCP_UPLOAD_URLS`, see [section 7.2](concept/configuration.md#72-uploads-from-a-url). A client of its own, never the API's: no key, no retries, no rate limiter, no redirects, 30 seconds and 5 MiB. The one place besides `api/connection.py` that opens a connection, and never to Lexware. |
| `files/resources.py` | Downloaded files as MCP resources, so a client that does not share a filesystem with the server can still get the bytes. Both the list, bounded to the newest downloads, and the reads are answered from the download directory, not from a registry. See [section 13](concept/errors-and-output.md#13-output-format). |
| `files/rendering.py` | PDF pages to PNG images, the only way a PDF becomes visible in a client that cannot display one. The single place allowed to touch `pypdfium2`. |
| `files/delivery.py` | A download as an answer: a file saved to disk, with the clean-up that follows, and answered as a line and a resource link, or a download read back and put into the conversation as text, image, rendered pages or a blob, whichever makes the bytes usable to a client. The tools in `tools/files.py` only register and delegate to it. |
| `policy.py` | The policy file, what a tool declares itself to be, and the enforcement of both, see [section 9](concept/permissions.md#9-permission-model). |
| `transport/stdio.py` | The default transport: the client starts the process and owns stdin and stdout. See [section 6](concept/transport.md#6-transport-and-runtime). |
| `transport/http.py` | The HTTP transport: the bearer guard in front of it, a generated token written into the settings file where that was asked for, the DNS-rebinding allowlist, and around the SSE app a wrapper that lets each request be answered once. Nothing here is reached under stdio. See [section 6](concept/transport.md#6-transport-and-runtime). |
| `transport/watch.py` | The watch that ends an HTTP process when its settings file changes, for a deployment that restarts it. |
| `transport/setup_prompt.py` | Over stdio, the prompt a person picks in the client to open the configuration interface: `setup` started as a detached process. See [section 7.1](concept/configuration-interface.md#71-the-configuration-interface). |
| `configui/` | The local configuration interface, see [section 7.1](concept/configuration-interface.md#71-the-configuration-interface). A separate command, never part of the server process. `templates` is the one module importing Jinja2, with the templates under `templates/` and the stylesheet and the script under `static/`, `state` which files apply and where each value came from, `cost` what a tool costs the model, `probe` the one API call it makes, `stamp` when something was written, `profiles` named sets of permissions, `transfer` reading and writing a policy file, `pages` each screen as a template and its context, `actions` what each form does, as functions from a form to a page, `app` the HTTP server, its guards and the routing. |
| `tools/_base.py` | Registration helper, tidies a docstring before it becomes a tool description. Registers every tool but `server_status`: what is offered is decided when the list is built, not here. Wraps each one in the line it writes per call, see [section 11.2](LOGGING.md). |
| `tools/status.py` | `server_status`, the one tool the policy file does not decide, see [sections 8](concept/tools.md#8-tools) and [9.2](concept/permissions.md#92-the-policy). Registered past `_base`'s helper, so neither the policy guard nor the call line is put around it. What it knows of Lexware is `api/client.Health`. |
| `tools/diagnostics.py` | Profile and connection check. |
| `tools/contacts.py` | Contacts, read and written. |
| `tools/articles.py` | Articles, read, written and deleted. |
| `tools/vouchers.py` | Voucher list, bookkeeping vouchers and payment status. |
| `tools/sales_documents.py` | The seven sales document types, and the templates that repeat them. The path segment each type lives behind is `records/types.py`, beside the type. |
| `tools/files.py` | Upload, download, rendered documents. |
| `tools/deeplinks.py` | Links into the web app, built from ids without an API call. Classified under `files`, so the policy file and the interface group it as before. |
| `tools/master_data.py` | Countries, payment conditions, posting categories, print layouts. |
| `prompts/` | The recipes a person picks in the client, each a subclass of `_base.Prompt` in the module of its name: `open_items.py`, `missing_receipts.py`, `contact_overview.py`. `_base.py` holds the class and the two texts every recipe shares, the one on withheld tools and the rules of the books. Offered whatever the policy file says, see [section 8](concept/tools.md#8-tools). |

**Layer rule:** tool functions stay thin. Every endpoint is a method on
`api/client.py` and every request goes through `api/connection.py`, never
through a tool function.

**Import rule.** The package is layered, and `tests/test_layers.py` reads
every import statement to hold it there. A layer imports only what sits
below it, and a row allows what the layer uses and no more, so a change
that needs another layer adds it on purpose:

| Layer | May import |
|-------|------------|
| `errors` | nothing |
| `logbook` | `errors` |
| `settings` | `errors`, `logbook` |
| `records` | `errors` |
| `api` | `errors`, `logbook`, `settings` |
| `files` | `errors`, `logbook`, `settings` |
| `policy` | `errors`, `logbook`, `settings` |
| `tools` | all of the above, never `server`, `transport`, `cli` or `configui` |
| `prompts` | nothing: a recipe names tools, it never imports them |
| `server` | `tools`, `prompts`, `policy`, `api`, `files` and the three of the foundation |
| `transport` | the three of the foundation, and the SDK's server type rather than this one |
| `configui` | `api`, `policy`, `server` and the three of the foundation, imported by `cli` alone, and Jinja2 in `configui/templates.py` alone |
| `cli` | everything but `prompts`, which only `server` imports, and imported by nothing but `python -m` |
| `__main__` | `cli` |

Two things the table does not follow from, decided 2026-09-30. `errors` is
the one module every layer raises from, so `server` and `transport` import it
like everything else does. And `configui` is not a peer of `cli` but below
it, since `setup` is a command the console script starts. A new module or
subpackage fails the test until it has a row, which is the price of the
table and the reason it keeps.
