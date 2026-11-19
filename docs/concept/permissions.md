# Concept: the permission model

Part of the [concept](../CONCEPT.md): sections 9 to 9.2.

## 9. Permission model

**One file decides, tool by tool.** There is no level above it and no group
beside it. A tool is enabled or it is not, and the answer is in the same place
for all of them.

### 9.1 Why the tier was removed

The first design had a coarse `LXO_MCP_MODE` of `read`, `write` and `full`
above the file, as a ceiling an operator could pin. It was dropped on
2026-08-21, and the reasoning is worth keeping because the trade is real.

**What it cost.** A level is a bundle, and a bundle is always wrong for
somebody: raising it to `write` so a quotation could be drafted also handed
over receipt upload and voucher creation. Two gates also meant two places to
look when a tool was missing, and the answer "it is in the file but the tier
withholds it" is a confusing one to arrive at.

**What was given up.** A deployment can no longer be pinned read-only
independently of any file. Whoever can write the policy file can enable
anything in it. Where that matters — a container, a shared machine — the file
is the thing to protect, with the permissions of the filesystem rather than
with a second mechanism inside this server.

**What replaced the safety.** The default moved from "read-only" to
**nothing**: a tool the file does not name is off, and an installation without
a file offers no tools but `server_status`. The old default let a fresh
installation read a live accounting system without anybody having decided
that. This one does not.

### 9.2 The policy

**The file is the truth.** `tools.json`, one flag per tool, never in the
repository:

```json
{ "get_profile": true, "search_vouchers": true, "create_voucher": false }
```

It is found by `settings.locations.resolve_config_file`, the same search the `.env`
goes through: the per-user directory, then `config/` of a checkout, then the
working directory, last one found winning. One order for every configuration
file there is, because two files searched two ways would be two rules to
remember and the one remembered wrongly would be the one holding the
permissions. `LXO_MCP_TOOL_POLICY` overrides the search, and `--tools-file`
overrides that. A tool the file does not mention is **off**: the file is the
only gate there is, so anything it fails to say has to be a no, and a tool
arriving with an upgrade waits to be enabled rather than appearing on its own.
Writing a flag for every known tool rather than only for the exceptions is
what makes the file readable without knowing that rule.

**The classification computes a file, it is never consulted instead of one.**
`policy.preset` turns the classification into a complete set of flags —
`read-only`, `write` and `irreversible`, each containing the last. It is
written to disk and the disk is what is read afterwards, so the file always
says exactly what is allowed, tool by tool. A preset is a way of writing many
flags at once and nothing more.

**Where the classification comes from.** The `@classify` decorator records
`access`, `domain`, `effect` and `permanence` as the tool is defined, so
`policy.known_tools()` cannot drift away from the code it describes — which a
table maintained by hand somewhere else eventually would. It is **metadata,
not permission**: nothing reads it when a call arrives. A script selects on
`access`, an interface groups by `domain`, and both then write flags.

**`write` does not mean undoable, and the preset names cannot say so.** The
`irreversible` step covers `delete`, the one effect this API offers that
destroys a record, and `delete_article` is the one tool carrying it.
[Section 5](upstream-api.md#5-upstream-api) has the full inventory of what
each write leaves behind, and it runs the other way round from the preset
names: the tool marked irreversible is the only one whose result could be
recreated exactly. What the step does not cover is a creation that cannot be
taken back, and there are five of those. They stay under `write`, because the
alternative is to put ordinary bookkeeping behind a step named after deletion,
and a preset that overstates its danger gets ignored rather than read.

**`permanence` is the axis that does say so**, added on 2026-08-21 when the
configuration interface needed to warn about it and found the classification
had no word for it. Three values, and the difference between the last two is
the point:

| Value | Meaning | Tools |
|---|---|---|
| `""` | the API can remove it again | everything else |
| `"app"` | no call here removes it, but the web app deletes one without ceremony | `create_contact` |
| `"books"` | no call here removes it, and it is a bookkeeping record, so the web app deletes it only while nothing has bound it | `create_voucher`, `create_sales_document`, `upload_file`, `attach_file_to_voucher` |

A missing route is a gap a later API version could close. A bookkeeping
record is different in kind: from the Festschreibung on, § 146 AO wants it
unchanged and the remedy is a Storno rather than a deletion, whatever the API
grows.

**Nothing this API creates is bound at the moment it is created**, and the
second value was called `"law"` until 2026-08-22, which said otherwise. Two
things in this repository disprove it: `update_voucher` works, which a
festgeschrieben record would not allow, and `create_sales_document` produces
a draft unless the call asks for `finalize`. What the mark records is that
such a record *can become* permanent — through Festschreibung, an assigned
payment, a follow-on document or an export — while a contact never does.

Like the rest of the classification this decides nothing. It is there so that
an interface offering to switch these tools on can say which kind of
permanent it means, and so that the command line and the README can say it in
words.

**The domain is the module the tool lives in**: `articles`, `contacts`,
`diagnostics`, `files`, `master_data`, `sales_documents`, `vouchers`, with
one exception, `get_deeplink`, which lives in `deeplinks.py` and is
classified under `files`. A tool that points at a sales document while doing
something else — `download_document` fetches its PDF, `get_deeplink` builds a
link to it — is grouped by what it does rather than by what it names, because
that is where a reader looks for it. Anything else would need a second rule
about which of the two wins. `server_status` has no domain, since it is
classified nowhere.

**Enforcement happens twice, as defence in depth.** A disabled tool is left
out of the list, so it never reaches the model and costs no tokens, and a call
to one is refused by name with the file that would enable it. The listing
filter is in `PolicyServer`, one place for every tool there is, so a tool
added to a module later cannot quietly escape it.

**One tool the file does not decide: `server_status`**, decided
2026-10-29. It reads no record and writes nothing, and with every other
tool off it is what a model can still ask, so it can say why the list is
what it is instead of guessing at a fault. `PolicyServer` lists it and lets
its call through before it asks the file, so a file that names it changes
nothing and one that cannot be read does not stand in its way. It is not in
the registry `classify` fills, so no preset, `--tools`, the configuration
interface or a saved file knows it. The rule it is the exception to stands
otherwise as it was: no other tool exists without the file naming it.

**A server that offers nothing else says so on stderr**, naming the file and
the command that writes one. From the client a list of the status alone
says little more than an empty one, and the difference matters.

**Changing it while the server runs.** The file is read fresh on every
question rather than cached, so an edit takes effect on the next request — a
few hundred bytes of JSON is cheaper than a copy that can be wrong.
Enforcement is therefore always current. What is *shown* lags until the client
asks again — so it is told to. `PolicyServer` announces
`tools.listChanged: true`, binding the `NotificationOptions` once in its
constructor so that stdio and both HTTP transports are covered, and a watcher
sends `notifications/tools/list_changed` when the set of enabled tools
actually differs.

Three decisions in that watcher are worth stating:

- **It compares the visible set, not the file.** The configuration interface
  rewrites the whole policy file on every save, so a timestamp would announce
  a change on every click that changed nothing.
- **It starts when a connection appears, not at construction.** Without a client
  there is nobody to tell, and a task polling in every process that merely
  builds a server — the test suite, `--tools show` — is a nuisance nobody
  asked for. The session comes from `_handle_list_tools`, the private hook,
  because that is the only place it is offered for a listing: the public
  `list_tools()` is called without it. `_handle_list_resources` keeps it
  the same way, since a client that listed the downloads is one to tell
  about the next, see [section 13](errors-and-output.md#13-output-format).
- **It notifies every connection it has seen** and drops the ones that
  fail, which is one client over stdio and will be several over HTTP.
  The same round tells them about a new download. The connection and
  not the request's session: the SDK builds a `ServerSession` for each
  request and lets it go with the answer, so a weak set of sessions was
  empty whenever there was something to tell. Found 2026-10-16, when the
  first download notification went to zero sessions over stdio, and the
  log showed the tool notification had last reached one on 2026-10-03.
  The tests had not noticed because they handed the server a session
  they held themselves, so `tests/test_list_changed.py` now also
  connects a real client through the SDK's runner and waits for the
  notification to arrive. Claude Desktop, same day: it starts the server
  twice, one process answers the listings and another the calls, so a
  connection is kept from a call as well as from a listing.
- **A 2026-07-28 client is told on its listen stream.** The SDK serves
  that protocol beside the handshake on the same transport, stdio
  included, measured 2026-10-16 with mcp 2.0.0 and 2.3.0, and there a
  change notification travels only on a `subscriptions/listen` stream the
  client opened, fed from the bus `MCPServer` keeps. Sent on the
  connection, it is dropped without an error. So every notification is
  published on the bus as well, and only a connection whose own channel
  carries it is counted as told. The same holds for a streamable HTTP
  client with no GET stream open, which has no channel at all. Found in the
  review of 2026-10-16. `tests/test_list_changed.py` opens a listen stream
  through the SDK's runner and waits for the notification on it.

**Claude Desktop acts on it, verified 2026-08-22.** With the capability
announced, a permission changed in the configuration interface reached the
running client without restarting it. That is the whole point of the
exercise, and it was worth measuring rather than assuming: the same
notification sent *without* announcing the capability had never been shown to
do anything, see [section 13](errors-and-output.md#13-output-format).

**Nothing depends on it even so.** A client that ignores the notification, or
never receives one, still cannot call a tool that has been switched off: the
file is read again on every call. The notification saves a restart, it does
not enforce anything.

**Both directions take effect without a restart**, which is why the filter
sits in `PolicyServer.list_tools` rather than in `register_tool`. Every tool
is registered whatever the file says, and the file is read as the list is
built and again on every call.

It was the other way round until 2026-08-21, and the asymmetry that produced -
switching a tool off worked at once, switching one on needed the process
restarted - was a consequence of *where the check sat*, never a decision. It
is worth recording that it was briefly defended as one, on the grounds that
granting permission ought to be deliberate. That was a justification invented
for an accident.

What still lags is the client, which is not this server's to fix: a tool list
already fetched stays until the client asks again, and most ask once.

**What a tool declares:**

| Field | Values |
|---|---|
| `access` | `read` or `write` |
| `domain` | the group it belongs to, one per module in `tools/` but `deeplinks.py`, whose tool counts under files: diagnostics, contacts, articles, vouchers, sales_documents, files, master_data |
| `effect` | write tools only: `create`, `update`, `delete` |
| `permanence` | what the API cannot take back of what the tool writes: empty when a call here removes it again, `app` when only the web app deletes it, `books` when it is a bookkeeping record that a Festschreibung can later bind, see [section 5](upstream-api.md#5-upstream-api) |

`ToolMeta.irreversible` is true for `delete` alone, which in this product is
not a figure of speech: what is deleted is gone, and what is created mostly
cannot be deleted at all. `book` and `finalize` were in this vocabulary until
2026-08-21, when the API seemed to have no state transitions to name them
after. The one it has, booking an unchecked voucher, is `finalize` on
`update_voucher`, behind the same `confirm` as the finalize of a sales
document, see [section 8](tools.md#8-tools).

The permissions page of
[section 7.1](configuration-interface.md#71-the-configuration-interface)
is the home for all of this, and `sync` is what keeps a file fit for it: an
interface renders one row per tool, which is only possible while the file names
every tool there is.

**Interface.** On the command line `--tools show` reports, `sync`
completes the file without deciding anything, and `read-only`, `write` and
`irreversible` overwrite it with that preset, each containing the last.
`--tools-file` says where to write it.

**Why `sync` is separate from the presets.** A preset overwrites, which is
right for starting a file and wrong for keeping one: an installation whose
owner has switched twelve tools off by hand loses all twelve. But a file
written before an upgrade does not mention the tools the upgrade brought, and
while those are correctly **off**, the file has stopped being a complete
picture of what exists — which is exactly what somebody reading or editing it
needs. `sync` writes the missing names in as `false` and every flag already
there back unchanged. **It cannot switch anything on**, which is the property
that makes it the one action safe to run unattended, from a post-install hook
or an upgrade script, while granting a permission stays a deliberate act. A
name in the file matching no tool is reported and not written back: it has no
effect and no decision attached to it, so keeping it would only make the file
harder to read, and dropping it in silence would leave somebody hunting for a
setting. The third step exists separately because deleting is its own decision
— reachable, but only by naming it rather than by choosing the largest option.
Everything it prints goes to stderr, because it shares an entry point with the
server and stdout carries the JSON-RPC stream. The graphical version is the
permissions page of
[section 7.1](configuration-interface.md#71-the-configuration-interface):
a table grouped by domain, one toggle per row, `read` and `write` marked,
irreversible effects flagged, permanent ones flagged separately, and the
connected organization shown at the top from `get_profile` — so it is never in
doubt which account the permissions being granted apply to.

**It shows what each tool costs in context, which nothing else here does.** A
tool that is on is sent to the model on every single request, description and
schemas alike, and [section 8](tools.md#8-tools) measures that at around 2,000
characters per tool with `create_sales_document` at more than double. The page
carries a per-row figure and a running total that follows the checkboxes, so a
policy can be chosen against a budget rather than against a guess. Characters
are what can be counted honestly — a token count would need a tokenizer for a
model this server does not know it is talking to, so the token figure beside
them is labelled as an estimate and derived from a fixed ratio.
