# Concept: client behaviour

Part of the [concept](../CONCEPT.md): sections 10 to 10.2.

## 10. Client behaviour (`api/`)

- One shared `httpx.AsyncClient` with `Authorization: Bearer` set once, a
  connection pool, and `LXO_MCP_TIMEOUT`.
- **Rate limiting:** a single process-wide token bucket, see section 10.1.
- **Retries:** method-aware, see section 10.2. A 429 is always safe to retry,
  a failed POST is never retried, and 4xx other than 429 is never retried.
- **Pagination:** search tools request one page and report the page metadata.
  A caller that wants more asks for the next page. The client does not silently
  walk every page of a large account.
- **Error mapping:** upstream status to `ToolError` subclass, see
  [section 12](errors-and-output.md#12-error-handling).
- **Secrets:** the API key is never logged, never echoed in a tool result, and
  redacted from any error text before it leaves the process.

### 10.1 Rate limiting

The upstream limit is 2 requests per second, applied as a token bucket **across
all endpoints of the API at once**. That single sentence decides the design.

It is Lexware's limit, so it is Lexware's requests the bucket counts. An upload
fetched from a URL, see [section 7.2](configuration.md#72-uploads-from-a-url),
goes to another server and does not take a token: it would spend the account's
allowance on traffic the account never sees. The upload that follows the fetch
does take one, and so does the status check of [section 8](tools.md#8-tools),
which waits a second for it at most and otherwise sends nothing.

#### The algorithm, and which half of it we implement

The [token bucket](https://en.wikipedia.org/wiki/Token_bucket) has three
parameters: a bucket of capacity **b** tokens, a token added every **1/r**
seconds, and a cost of **n** tokens per unit of work. Tokens arriving at a full
bucket are discarded. Work costing *n* tokens is **conformant** when the bucket
holds at least *n*, which are then removed, and **non-conformant** otherwise,
in which case the bucket is left untouched. Here *n* is 1 for every request,
because the limit counts calls and not payload bytes. The long-run average is
capped at *r*, while *b* sets how much of an idle period may be spent at once.

The interesting part is what happens to a non-conformant request. The
literature gives three treatments, and Lexware and this server pick different
ones from the same list:

| Side | Treatment | Effect |
|---|---|---|
| Lexware | **policing** — drop | 429, and the documentation is explicit that "the actual call will not be performed" |
| This server | **shaping** — enqueue | the call waits until enough tokens have accumulated, then goes out |

So both sides run the same algorithm and only the penalty differs. That is why
the local bucket has to be at least as strict as the remote one: a request our
shaper lets through early is a request their policer destroys. The third
treatment, marking a request non-conformant and sending it anyway, has no
meaning for an HTTP client and is not used.

The queueing variant of the **leaky bucket** was considered and rejected. It
would emit a perfectly even stream with no jitter at all, but it also forbids
any burst, so a tool that legitimately costs two calls would always eat a full
`1/r` gap in the middle. Mirroring the upstream model is both simpler and
closer to how the account is actually metered.

#### Implementation

```
acquire(n = 1):
    now    = monotonic()
    tokens = min(b, tokens + (now - last_refill) * r)
    last_refill = now
    if tokens >= n:
        tokens -= n
        return                      # conformant, send immediately
    wait (n - tokens) / r seconds   # shaping: enqueue, do not drop
    then retry
```

Four details that matter:

- **Continuous refill, no background task.** Tokens are recomputed from the
  elapsed time on each acquisition, so an idle server costs nothing and there
  is no timer to keep alive. Fractional tokens are kept, matching the fluid
  formulation of the algorithm.
- **A monotonic clock, never the wall clock.** An NTP correction or a
  daylight-saving step must not hand out free tokens or stall the server for an
  hour.
- **One lock around the whole acquisition.** Two concurrent tool calls in the
  same event loop must not both read the same token count and spend it twice.
  Waiters are served in arrival order so a chatty tool cannot starve a quiet
  one.
- **The wait is awaited, not slept.** `asyncio.sleep`, so the server keeps
  answering other MCP traffic while a call is queued behind the bucket.

**One bucket per process, not one per endpoint or per tool.** The limiter is a
single object owned by the client module and shared by every request, whatever
resource it targets. A per-resource limiter would let five idle endpoints hand
out five buckets worth of tokens and blow the global budget while each one
believes it is well behaved. There is exactly one bucket, and every call to
Lexware acquires a token from it before the request is issued, including
retries, pagination follow-ups and the read that an update makes before it
writes.

**Parameters:** *r* is `LXO_MCP_RATE` (default `1.5` per second) and *b* is
`LXO_MCP_BURST` (default `2`). The rate sits deliberately **below** the
documented 2 per second, because the documentation says that enforcing the
limit without a buffer commonly produces 429s anyway once network jitter shifts
the arrival times. A shaper that aims exactly at the policer's threshold loses
every race the network decides.

The capacity is the more dangerous of the two. A generous local *b* would let
the server open with a burst that our own limiter considers conformant and
theirs does not — it would move the failure from our queue to their 429
without any warning that it had happened.

**Upstream *b* is 4**, measured 2026-08-21 and no longer a guess: five
concurrent requests after an idle stretch got four through and one refused,
four got four through. The idle stretch does not buy more, so the bucket is
shallow and fixed rather than a credit for quiet time.

**The default stays at `2` regardless**, and the measurement is the reason it
can stay there honestly rather than out of ignorance. The upstream limit is
**global across the account**: the web app, another integration, or a second
instance of this server all draw on the same four. A local *b* of 4 would be
conformant only while nothing else is running, which is not a property an
accounting integration should depend on. An operator who knows this server is
the only consumer can raise it to `4` and be exactly at the ceiling. `2` also
keeps the two calls of an update from being artificially separated, which was
the original reason for it. Both values are configurable, so an account that
behaves differently can be tuned without a code change, and open question 6 in
[section 16](../ROADMAP.md) is what would let the default be raised with
evidence.

**What the budget comes to in practice.** The documented ceiling is a rate, not
a quota, so it is easiest to read as a steady gap between calls:

| | rate *r* | sustained per minute | gap between calls |
|---|---|---|---|
| Lexware documented ceiling | 2 per second | 120 | 500 ms |
| Server default (`LXO_MCP_RATE`) | 1.5 per second | 90 | 667 ms |

The per-minute figure is a consequence, **not a quota that can be banked**.
A fixed window of 120 per minute would permit all 120 in one burst at the end
of the minute. A token bucket never does: whatever the minute's total, the
instantaneous allowance is only ever the *b* tokens currently in the bucket,
and after that the pace returns to *r*. A client that has been idle can start
with a burst of *b*, and that is the entire concession.

At the default this means a broad question stays comfortable. A quarter of
invoices at 25 rows per page is 20 pages, so 20 calls, roughly 13 seconds.
Reading 50 documents in full is 50 calls, about 33 seconds. The limit only
becomes the bottleneck when a caller walks thousands of rows, which is exactly
the case [section 13](errors-and-output.md#13-output-format) caps by returning
one page at a time.

**No parallel fan-out.** Every request passes the bucket *before* it is issued,
rather than being fired concurrently and throttled afterwards. That is not the
same as one request at a time — while tokens remain, up to *b* calls go out
back to back, which is the whole point of a token bucket. What is ruled out is
a tool spawning a batch of calls and leaving the limiter to sort out the
aftermath. A tool that needs several calls acquires for each one in turn and
simply takes longer. The `Calls` column in [section 8](tools.md#8-tools) states
what each tool costs, so a caller can reason about it.

**The client-side limiter is necessary, not sufficient.** The budget belongs to
the Lexware account, not to this process. A second server instance, another
integration, or a script the user runs by hand all draw from the same 2 per
second. 429 handling therefore stays mandatory and is never treated as a bug in
the limiter.

**Backing off for real.** On 429 the request is retried with exponential
backoff and jitter, honouring `Retry-After` when it is present - in full: the
jitter shortens the computed delay, never the one the server asked for. After a small
number of consecutive 429s the client stops retrying, drains the bucket for a
cool-down window, and returns `RateLimitError` to the caller. This is a
deliberate circuit breaker rather than politeness — the documentation states
that a client which does not reduce its rate stays blocked permanently, so
retrying harder is the one response that can turn a transient problem into a
dead API key.

**Authorization requests are separate.** The authorization server has its own
undocumented limits. Should a future release ever obtain tokens rather than
using a static API key, those calls get their own conservative bucket and are
never counted against the resource budget.

### 10.2 Retry safety

Retrying is not uniformly safe, and the difference matters more here than in
most APIs, because a duplicate request can create a second invoice in someone's
bookkeeping. A duplicate is not a technical annoyance to be cleaned up later —
it is a document with a consecutive number that the account owner has to cancel
by hand. The rule is therefore decided per HTTP method and per failure mode,
not per status code alone.

| Failure | GET | PUT, DELETE | POST |
|---|---|---|---|
| 429 | retry | retry | **retry** |
| 5xx | retry | retry | **never** |
| timeout, connection reset | retry | retry | **never** |
| 4xx other than 429 | never | never | never |

**Why 429 is the exception.** The documentation states that on 429 "the actual
call will not be performed". The request never reached the resource, so
repeating it cannot duplicate anything. This is the one failure mode where the
upstream tells us the outcome with certainty.

**Why a failed POST is never retried.** A 5xx or a timeout says nothing about
whether the document was created. The request may have been executed and only
the response lost. Retrying then risks a second invoice, and the client cannot
tell the two cases apart. **There is no idempotency key to lean on**, measured
2026-08-21 under three header names: the same POST sent twice creates two
documents every time, see open question 2. So this is not a rule waiting for
a better mechanism, it is the only correct behaviour the API allows. Instead the failure surfaces as an `UpstreamError`
whose message says explicitly that the outcome is unknown and that the caller
must check whether the document exists before trying again. Losing a request is
recoverable, silently issuing two invoices is not.

**Why PUT is safe.** Beyond being idempotent, an update carries the `version`
it read. If the first attempt succeeded, the version has moved on and the retry
fails with 409 rather than applying the change twice. Optimistic locking makes
the retry self-protecting.

**Why a PUT or DELETE out of retries is an unknown outcome as well.** The
retry is safe, the last failure is not certain: any of the three attempts may
have been carried out with only its answer lost, the last one included. So
when the retries run out on a timeout, a lost connection or a 5xx, the
`UpstreamError` says the outcome is unknown, exactly as for a POST. Reported
as a plain failure, the caller sent the update again, into a stale version or
a 404.

**Why a DELETE retried into a 404 has succeeded.** A second delete of the same
article is a 404, measured 2026-08-21. So when an attempt timed out, lost its
connection or got a 5xx and the retry then finds nothing, the likeliest reading
is that the first attempt removed it - and passing the 404 on would tell the
caller the article never existed, right after this call destroyed it. The
client returns success in that one case. A 404 after nothing but a 429 stays a
404, since a 429 is certain not to have been performed.

**Why `Retry-After` is honoured only up to eight seconds.** The wait happens
inside a tool call. A header of `86400` held the call for a day and `inf` for
ever, so a value beyond `BACKOFF_CAP`, or one that is not a finite number,
ends the call at once with a `RateLimitError` that says so. A value within the
cap is honoured as before.

**Why an unreadable answer to a write is an unknown outcome.** A 2xx means the
write was accepted. A body that then is not a JSON object - empty, HTML from a
proxy, a cut-off stream - leaves the caller not knowing what was created, which
is the same position as a lost response. It is reported the same way, as an
`UpstreamError` whose message says the outcome is unknown, and never as a bare
decoding error that would read like a failure worth retrying.

Open question 2 is what would change this table: if the API offers an
idempotency key, POST could be retried safely and the asymmetry would
disappear.
