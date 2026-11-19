# Concept: testing

Part of the [concept](../CONCEPT.md): sections 14 to 14.3.

## 14. Testing

The suite that gates the project and the checks that touch a live account are
two different things, kept apart deliberately. Section 14.1 says why.

- Offline unit tests using `httpx.MockTransport`, no network in the suite, no
  API key needed to run it.
- Fixtures are anonymized copies of real response shapes, with placeholder IDs.
- Coverage floor 80 percent, measured over the offline suite alone and enforced
  by CI on the newest Python of the matrix, see [section 16](../ROADMAP.md).
- **The rate limiter is unit tested against an injected clock**, never against
  `time.sleep`, so the suite stays fast and deterministic. The properties worth
  asserting follow straight from the algorithm in
  [section 10.1](client.md#101-rate-limiting): the bucket is shared across
  different endpoints rather than duplicated per resource, a burst larger than
  *b* is spread out to the long-run rate *r*, refill saturates at *b* so an
  hour of idling does not buy an hour of tokens, a non-conformant request is
  delayed and never dropped, concurrent acquisitions cannot spend the same
  token twice, and a run of 429s trips the circuit breaker instead of retrying
  forever.
- Gates: `pytest -q`, `ruff check .`, `ruff format --check .`, `mypy` and
  `uv lock --check`.

### 14.1 Live checks are not a gate

No API key ships with this repository and none is ever placed in CI. A public
checkout cannot talk to Lexware at all, and that is the intended state: a key
held in a CI secret would put a real accounting system one merge away from a
workflow file that anyone able to open a pull request can edit.

The consequences are the point of writing this down.

- **The offline suite is the only gate.** Everything CI runs has to pass with
  no key, no network and no account. That is true today and stays true. A test
  that quietly skips when no key is present is not a gate, it is a hole that
  reports green.
- **`live/smoke.py` is run by hand and never collected by pytest.** Built
  2026-08-21. It takes a key from the normal configuration chain of
  [section 7](configuration.md#7-configuration), refuses to start without
  one, calls `get_profile` first so whoever runs it sees which organization is
  about to be read, and performs **read-only** calls only. `pytest` does not
  find it because `testpaths` is `tests/` and this file is not in it. That was
  a filename until 2026-09-02: the script was called `smoke.py` rather than
  `test_smoke.py` and nothing else stood in the way, so a rename would have
  pointed CI at a live account. Both live checks moved to `live/` for that
  reason, which is the same argument as the one two bullets down - a directory
  pytest does not walk is a guarantee, a name it happens not to match is a
  convention.
- **It cannot write, structurally.** The server it builds is handed the
  `read-only` preset of [section 9](permissions.md#9-permission-model), so a
  writing tool is not merely unused in the script, it is absent from the server
  and refused if called. The script checks that too, on the tool list it was
  given. A promise that a script makes no writing call is worth less than a
  server that cannot make one.
- **`live/upload_from_url.py` is the one live script that writes**, built
  2026-10-15 for [section 7.2](configuration.md#72-uploads-from-a-url). An
  upload creates a voucher the API cannot delete, so the script takes the
  organization it may write to as a required argument and stops before anything
  is written when `get_profile` reports another. The check golden rule 1 asks
  for is then done by the script rather than remembered by whoever runs it. Its
  server enables `get_profile` and `upload_file` alone. Since the review of
  2026-10-16 it takes the company name and the `organizationId` both, since a
  test account may carry the real one's name, and it requires `--env-file`:
  left to look, it read the configuration the server runs with every day, which
  is the real account's.
- **A check that could not run is reported as skipped, never as passed.** An
  empty account has no article to read and no rendered document to download,
  and a live check that reported those as successes would be the same hole as
  a test that skips itself. The summary counts the three states apart.
- **It found something on its first run**, which is the argument for having it:
  `GET /v1/articles` refuses a page size below 25, alone among the list
  endpoints, and the tool's schema had allowed 1. Nothing offline could have
  caught that, because the mock answers whatever it is told to. The same
  happened to `server_status` on 2026-10-29: asked right after the other
  checks, its check of Lexware found no token free and sent nothing, which is
  why it now waits a second for one, see [section 8](tools.md#8-tools). The
  script calls it both ways and holds the answer to the core's order, a
  reachable account, a key taken and no part of the key in the text.
- **Upstream drift is invisible to CI.** The suite mocks HTTP completely, so it
  stays green through any change in Lexware's field names or response shapes.
  Only a live run catches that, and only someone holding an account can perform
  one. This is why statements about the API in these documents carry **(to
  verify)** until a live call has confirmed them.
- **The open questions below could not be closed by CI**, and none of them was.
  Each was answered by a live call, or in one case by a decision not to make
  one: a question about write behaviour needs write calls against a disposable
  test account, see [section 11.1](data-and-secrets.md#111-test-environment),
  which is a deliberate act by the account owner rather than something
  automation initiates.

### 14.2 A shape is recorded, so drift can be seen rather than remembered

`live/smoke.py` asks whether the calls this server makes still work. That
leaves a
question it cannot reach: whether the answers still look the same. Everything
null or empty is dropped on the way to the client, so a field that disappeared
upstream looks identical downstream, and a field that appeared is invisible by
construction.

`live/api_shape.py` reads every readable endpoint and writes what it saw into
a timestamped file under `live/shapes/`. Field names, JSON types, and the
values of a short list of closed vocabularies - `voucherStatus`, `taxType`,
`paymentStatus` and their neighbours, because a vocabulary that moved is drift
a type cannot show. Comparing two runs is then a `diff` rather than a reading
of the dated prose in [section 5](upstream-api.md#5-upstream-api).

**What a capture may hold is a rule with a test behind it.** No id, no name, no
address, no amount, no date: those are records rather than shapes and
[section 11](data-and-secrets.md#11-data-and-secrets-policy) keeps them
out of versioned files. `tests/test_api_shapes.py` checks every capture for all
four, because the files are long, they look alike and a leak in one would
survive review.

**A difference is not automatically drift.** These are the shapes of one
account, so a diff also moves when the account does: an optional field no
record happened to fill, a document type nobody had created yet. Read a diff
for what it says about the API, then check the account before concluding.

The first capture was taken 2026-09-02, covering nineteen endpoints. It found
four fields this repository had never named - `deliveryTerms`,
`organizationDefault`, `recurringTemplateId` and `userId` inside the `created`
block the profile tool drops. All four are additive and nothing reads them.
Whether they were new could not be settled, which is the argument for having
a baseline at all rather than an argument about those four fields.

### 14.3 The SDK is the second blind spot

Upstream drift is one direction a mocked suite cannot see. The other is the
layer on the near side: the MCP SDK, which sits between this code and the
client. The suite calls `MCPServer.call_tool` and asserts on what comes back
or on what it raises. A client never does that. It sends JSON-RPC over stdio
and is answered by `_handle_call_tool`, which converts a return value into a
result and an exception into an `is_error` result. `tests/test_stdio.py`
exercises the success path of that conversion, a status call answered as
text, and nothing in the suite exercises the error path, so a change to it
is green all the way through.

**When the SDK version moves, drive the server the way a client does.** Spawn
`python -m benethos_lexware_office_mcp` with a scratch policy file and a
placeholder key, speak `initialize`, `tools/list` and `tools/call` to it over
its own stdin and stdout, and keep the answers. Do it once before the bump and
once after, then diff. Three things are worth capturing:

- **The tool list, byte for byte.** It is the largest thing this server sends
  and the whole of what the model knows about it. Byte-identical is the answer
  to want, and it is checkable: [section 8](tools.md#8-tools) records the size.
- **An error the server means to send.** Call a tool the policy file disables.
  The guard refuses it before any HTTP, so the check is offline and
  deterministic, and it travels the exact path a real failure travels.
- **An argument the schema rejects.** That failure is raised by pydantic
  before the handler runs and is sorted differently, so it is worth watching
  separately from the one above.

This is what the 2.0.0 to 2.1.1 bump was checked with on 2026-09-02. The list
and the schemas came back byte-identical and the size stayed at 52,091, while
the error path had changed underneath, see
[section 12.1](errors-and-output.md#121-why-toolerror-derives-from-the-sdks).
Neither half of that was predictable from the release notes alone, which is the
argument for sending the requests.

The diff is a scratch run, deliberately not a test. It spawns a process and
speaks a wire protocol, which is slow and brittle as a gate, and what it
guards is a decision rather than a behaviour: that the error hierarchy stays
on the SDK's anticipated-failure side of the line. `tests/test_errors.py`
asserts that decision directly, in a form that costs nothing to run.

**Since 2026-11-04 the fixed half of the probe is a script**,
`tests/stdio_check.py`, outside the suite by its name. It spawns the server
under the interpreter it runs with, against a scratch policy file and an empty
settings file, and asserts what a client has to receive whatever the SDK
version: the tool list with the status and the enabled tools, each with its
annotations, a disabled tool refused with this server's sentence rather than
the SDK's bare "Error executing tool", an unknown argument refused the same
way, an argument of the wrong type answered as an error result rather than a
crash, and the status naming the version installed in that interpreter. It
exits with 0 or 1 and needs no key and no network. Of the mutations measured on
2026-11-04 in a container, the suite missed two: the wire conversion dropping
every error text, and `tools/list` dropping the annotations. The script sees
both. `.github/workflows/freshness.yml` runs it daily and after every run of
Publish on the newest versions the ranges allow, from the checkout, and on the
published package installed from PyPI, see [section 16](../ROADMAP.md). The
byte diff stays the check for a bump of `mcp`, since it sees what no fixed
assertion asks for.
