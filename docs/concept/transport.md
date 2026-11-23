# Concept: transport and runtime

Part of the [concept](../CONCEPT.md): section 6.

## 6. Transport and runtime

- **stdio is the default transport.** `MCPServer.run()` with the default
  stdio transport, launched as a subprocess by the client, and the only
  transport until 0.2.0.
- **HTTP since 0.2.0** (`--transport streamable-http` / `sse`) with `--host`,
  `--port`, `--path` and `--allowed-hosts`, in `transport/http.py`. **The bearer
  token is required, not offered**: an HTTP transport without
  `LXO_MCP_BEARER_TOKEN` refuses to start, because anyone who can reach the
  port can otherwise spend the account owner's credentials. It is one shared
  secret compared in constant time — the server speaks for one account and has
  no user to authorize, so an OAuth flow would be machinery for a case that
  does not exist. The SDK's DNS-rebinding `Host`/`Origin` guard sits on top of
  it, with the loopback names always kept and `--allowed-hosts` adding a
  container or proxy name to them. There is no `--allowed-origins`: two
  origins are derived from each allowed host, `http://` and `https://`, which
  is the only shape that has come up. Until 2026-10-08 only the first, so a
  browser behind a proxy ending TLS was refused.

  Neither guard makes the port safe on a network. They make it survivable on a
  machine shared with other processes, which is what a container published on a
  loopback port is. **`--host` and `--port` serve whichever of the two
  listening things this process is**, the transport or the configuration
  interface of
  [section 7.1](configuration-interface.md#71-the-configuration-interface),
  since a process is never both.
- **A changed settings file ends the process** when
  `LXO_MCP_EXIT_ON_CONFIG_CHANGE` says so, which the image and both Compose
  files set and nothing else does. Settings are read once, at startup: the key
  goes into a long-lived client and the one rate limiter of
  [section 10.1](client.md#101-rate-limiting) hangs off it, so rebuilding
  that in place would mean moving state between two clients. Ending instead
  hands the problem to whatever started the process, and a fresh one reads
  everything again - which is what lets a key saved in a browser reach a
  running server. Off by default, because ending is the whole of it where
  nothing restarts it.

  **One exception, since 2026-10-10: a key saved into a server that had none.**
  A server started before its first key was saved looks for one in the settings
  file at every API call, until it finds one, so the first setup works without
  a restart - as it already did for the permissions saved beside it. Measured
  in the Windows Sandbox of
  [section 7.1](configuration-interface.md#71-the-configuration-interface):
  the key was in the file, the connection test on the page succeeded, and the
  running server still refused every call until Claude Desktop was quit from
  the tray. Measured again with the change, in a fresh sandbox from the bundle
  of [section 16](../ROADMAP.md): the key saved in the browser was used by
  the next call, with no restart. Only the missing key is looked for. A key the
  process was given, from the file or from a variable, is never replaced under
  it, so a changed key still waits for a restart, and so does every other
  setting. The file is the one the configuration interface writes into, the
  named one or the one the search settles on, and a key read late is checked
  and kept out of every message like any other.

  The watch compares a **hash of the content**, not a timestamp: the
  configuration interface rewrites the whole file on every save, changed or
  not. Three further rules were bought with defects.

  **The baseline is the file as the settings were read from it**, taken
  just before they are, since 2026-10-08. Until then the watch took the
  file as it found it once two polls agreed, two to four seconds into the
  start, and a save in those seconds became the baseline: measured in a
  container, a key appended a second after the start never ended the
  process, which kept running without it. Taken before the read, a change
  landing in between ends the process once more than needed, which is the
  cheaper mistake. If the settings caught a save half done, the finished
  file is a change too, which is right, since that is what the process
  holds.

  **It is taken again after a generated bearer token has been written**, or
  the process would restart on its own first act.

  **Only a value that two reads in a row agree on counts as the current
  state**: a save truncates before it writes, so a poll landing inside one
  reads an empty file. CI found it, as a rewrite of identical content ending
  the process for nothing - a race that needs a loaded machine, which a
  developer's is not.

  **An open stream holds the end back for five seconds at most**, since
  2026-10-08. The watch asks uvicorn to shut down, and uvicorn waits for
  every connection to close, for as long as it takes unless it is given a
  bound. `SHUTDOWN_GRACE_SECONDS` is that bound, after which uvicorn cancels
  what is still running, says so in an error line and logs the traceback of
  each request it cancelled. The same bound applies when Ctrl+C or `docker
  stop` ends the process, and the latter sends SIGKILL after ten seconds.

  Measured 2026-09-30 over SSE: still running 75 seconds after the change,
  with sse-starlette 3.4.11 and 3.5.0 alike. **Not reproduced on
  2026-10-08**: sse-starlette closes its streams itself once uvicorn's
  `should_exit` is set, and over SSE and streamable HTTP alike, a bare
  stream or an initialized session, on Windows and in the image, with mcp
  2.2.0 and 2.3.0, the process ended 3.8 to 4.3 seconds after the change.
  What differed on 2026-09-30 is not known. The bound was measured with
  that drain switched off, which keeps a stream open the way it was then:
  without it the process still ran 40 seconds after the change, with it
  the process ended after 8.8, the poll and the grace period.

  **An SSE stream the server ends is answered once**, since 2026-11-23.
  The SDK's SSE endpoint returns a `Response()` once its stream has
  ended, and Starlette sends it as a second answer to the same request.
  uvicorn refused that with a traceback in the log, `RuntimeError:
  Expected ASGI message 'http.response.body', but got
  'http.response.start'`, and from sse-starlette 3.7.1 on `Unexpected
  ASGI message 'http.response.start' sent, after response already
  completed`. Measured: it came whenever the server ended an open stream,
  and not when the client closed it. `single_response` in
  `transport/http.py` sits around the SSE app alone and drops whatever
  arrives after the answer is complete, and a second start. Streamable
  HTTP never answered twice and is left without it. Upstream this is
  [python-sdk issue 883](https://github.com/modelcontextprotocol/python-sdk/issues/883),
  open since 2025-06-04, and the wrapper goes once the endpoint stops
  answering twice.
- **stdio is sacred.** stdout carries the JSON-RPC stream. Library and server
  code never `print()` to stdout, all logging goes to stderr through the one
  handler `logbook.configure` installs, uvicorn's included.
- **What Docker keeps of a container's output is capped**, since
  2026-09-29: both Compose files give every service the `json-file` driver
  with five files of 10 MB. Over HTTP uvicorn writes an access line of about
  60 bytes, on stderr beside this server's own lines, for every refused
  request and at `DEBUG` for every request - measured on the 0.3.0 image,
  when it still wrote every one of them to stdout. Without a cap Docker keeps
  all of it for the life of the container, and a restart, whether
  `unless-stopped` or the watch above, is the same container. The health
  check connects to the port without a request and adds nothing. A
  `docker run` sets the same cap with `--log-opt`, which the README shows.
- **The container files live in `containers/`**, since 2026-10-08:
  `images/lexware-office-mcp/Dockerfile`, and two Compose folders. Until
  then one `compose.yaml` in the root built from the checkout, and running
  the published image instead meant commenting two lines and uncommenting
  two others in each service, by hand, in a file that a pull would change
  again.

  `production/` runs the published image at the version `LXO_VERSION` in
  an `.env` beside it names, required rather than defaulted, so an update is
  one changed line and a `pull`. The folder needs nothing else from the
  repository. It keeps the project name the root file had,
  `benethos-lexware-office-mcp`, so its volumes carry over: measured
  2026-10-08, an `up` there replaced the container the root file had made
  and kept the generated token and a marker file in `/config`.

  `development/` builds from the checkout under a project of its own,
  `benethos-lexware-office-mcp-dev`, on 8780 and 8781 with volumes of its
  own. The two run side by side, and a trial never reaches the key, the
  token or the tools of an installation in operation. The settings the two
  pin are the same, which `tests/test_packaging.py` holds them to, so a
  trial tries what runs.

  **The variables Compose reads are named `LXO_`, not `LXO_MCP_`.** They
  sit in an `.env` like the server's own and are no setting of it: the
  version and the ports on the host. A distinct prefix keeps one from being
  read as the other, by a person or by the server's search, which takes an
  `.env` in the working directory and ignores names it does not know.

  **Both run the container hardened**: a read-only root file system,
  `/tmp` as a `tmpfs`, every Linux capability dropped and
  `no-new-privileges`. Every file this server writes goes through one atomic
  write into the directory of its target, so the `.env`, the policy file and
  the profiles land in `/config`, and downloads in `/downloads`. Measured
  2026-10-08 against the test account with the image built from the
  checkout: the token generated, a policy written, a restart on a changed
  `.env`, `get_profile`, an invoice downloaded and rendered into a page
  image, the configuration interface served - no traceback, no refused
  write. `tests/test_packaging.py` holds every service of both files to it.

  **No setup script**, left out on purpose: the first start needs no key
  material made outside the container. The server makes its token itself,
  and the configuration interface behind the `setup` profile takes the key.

  **HTTPS for the local network, and not for the internet**, decided
  2026-10-08. Until then no TLS proxy was shipped at all, since putting the
  server on a network seemed a decision for a proxy that authenticates.
  `production/` now has Caddy behind the profile `https`, on port 443 of
  every address, the one service a plain `up` leaves out besides `setup`
  and the one port beyond the loopback. Its `Caddyfile` passes `/mcp` on
  and nothing else: the configuration interface never goes through it, any
  other path is a 404, and a request without an `Authorization` header is
  answered 401 by Caddy, so a scan of the network never reaches the server,
  which checks the token itself as before. Caddy rewrites `Host` to the
  service's own name, which the server allows already, so the domain stays
  out of `LXO_MCP_ALLOWED_HOSTS` and any port a client uses works: Caddy
  answers for its domain alone, so the name has been checked by then. The
  server believes `X-Forwarded-For` from Caddy's fixed address and no
  other, through uvicorn's `FORWARDED_ALLOW_IPS`, so its log names the
  machine that asked. Caddy and the server share a network of their own
  for that address, and the project's default network stays as it was.
  Measured 2026-10-08 with the folder and the image of 0.4.2: without the
  root trusted the handshake fails, without a header Caddy answers 401,
  with a wrong token the server does, with the right one `initialize`
  answers, `/` and `/settings` are a 404, and the log names the client.

  **The certificate comes from Caddy's own CA by default**, `LXO_TLS` set
  to `internal`, whose root each client trusts once, and which the volume
  `caddy-data` keeps so a restart is no new root. `files` takes one of the
  operator's, `acme` a public CA's. The image is `caddy:2`, the major line
  unpinned, so a `pull` brings Caddy's security fixes. Dependabot watches
  the compose file and proposes the tag of the next line when one comes
  out, decided 2026-11-20.

  **A public address is not what this is for**, and the README says so.
  One static bearer token is all the server knows of who is asking, it has
  no expiry, no rotation but through `setup`, no limit on attempts and no
  identity per client, and behind it are tools that write to real books.
  Before the internet, it would need OAuth or at least expiring tokens that
  can be rotated, limits per address, and one identity per client with an
  audit of what each did, which is a work stream the size of the HTTP
  transport rather than a profile.

  **One instance for now, with the way to more left open.** Behind one
  Caddy several people share one key, one token and one `tools.json`.
  Different rights per person would be one server each, with its own
  volumes, token and policy, under `/mcp/<name>` through
  `LXO_MCP_HTTP_PATH`, and one more `handle` in the Caddyfile per instance.
  Nothing here stands in that way, and nothing of it is built until it is
  wanted.
- **CLI flags:** `--version`, `--settings-sample`, `--log-level`, `--tools`,
  `--tools-file` and `--env-file` for any run, `--transport`, `--host`,
  `--port`, `--path` and `--allowed-hosts` for the HTTP transport since 0.2.0,
  and for `setup` the same `--host` and `--port` with `--no-browser`,
  `--public-port` and `--exit-when-idle` beside them, see
  [section 7.1](configuration-interface.md#71-the-configuration-interface).
  `--mode` and `--download-dir` were planned here and never built: the mode is
  gone with the tier of
  [section 9.1](permissions.md#91-why-the-tier-was-removed), and the
  download directory stayed an environment setting because a client spawns the
  server and passes no arguments.
- **One `.env` applies, and the environment beats it.** A setting resolves as
  that one file, then the real environment, which has the last word - the
  order Docker and uvicorn use, and what lets a client override one value
  without rewriting a file. **An empty variable counts as unset**, since
  2026-10-08: Compose passes `${FOO}` as an empty string when `FOO` is
  undefined, and that used to replace the file's value with the default
  while the configuration interface named the file as the source.
  **The files themselves do not combine**, since
  2026-08-23: they used to merge key by key, so a value could arrive from a
  file nobody had named and no page could sensibly report where it came from.

  **`--env-file` replaces the search**, as `--tools-file` always did. Until
  0.2.2 the code read the named file *after* every file the search found,
  while its help text said "instead of looking for one", so a flag whose
  whole purpose was to make one client entry self-contained did not isolate
  anything: a setting the named file omitted was still answered by the
  machine.

  The other half is a decision: the search takes the highest candidate that
  exists rather than layering them, so both configuration files follow one
  rule and "which file is this value from" has one answer. The environment
  stays a separate layer because the container depends on it: the transport
  settings arrive as real variables while the key lives in the mounted file.
  `--log-level`, `--tools-file` and the transport flags `--transport`,
  `--host`, `--port`, `--path` and `--allowed-hosts` outrank the environment,
  because each is a decision about this one run. `--tools` and `--version`
  are actions rather than settings and have no equivalent at all.
- **Entry points:** `python -m benethos_lexware_office_mcp` or the
  `benethos-lexware-office-mcp` console script.
- **Python:** 3.11 to 3.15, all in the CI matrix. 3.15 joined on 2026-10-10,
  the day after its release: the suite passed on 3.15.0 with every compiled
  dependency as a wheel for it, and the stdio probe of
  [section 14.3](testing.md#143-the-sdk-is-the-second-blind-spot) answered
  byte for byte as on 3.14. The image moved to 3.15 on 2026-10-14, two days
  after `python:3.15-slim` was published.
- **3.14 changed how annotations reach a schema, measured 2026-08-22.** One
  parameter carries a description built at startup, because the default it
  states is configurable, and the finished annotation is attached after the
  definition - `from __future__ import annotations` would otherwise turn it
  into source text the SDK evaluates in module scope, where the per-process
  value does not exist. Up to 3.13 the wrapper `classify` returns and the
  function it wraps shared one annotations dictionary, so editing one reached
  the other, which is the function `inspect.signature` arrives at. Under PEP
  649 they no longer do: annotations are computed on demand from
  `__annotate__`, the wrapper materializes a dictionary of its own, and the
  original goes on answering from its source text. Both are set now, by
  replacing the dictionary rather than editing it, which drops `__annotate__`
  and leaves one answer for every reader. The offline suite is identical on
  every version and caught none of it - the matrix did. Since 2026-09-26 the
  call guard is put around the function when it is registered, after the
  annotation is attached, rather than by `classify` at definition: the guard
  answers to the policy of the server it is registered on, and there is no
  process-wide policy any more for a second server to overwrite.
