# Concept: the configuration interface

Part of the [concept](../CONCEPT.md): section 7.1.

## 7.1 The configuration interface

`benethos-lexware-office-mcp setup` serves the configuration pages on
`127.0.0.1:8771` and opens a browser. **The port is one above the HTTP
transport's**, since 2026-10-08: both used `8770`, so `setup` beside a server
on its default port ended with "in use", and no document said why. The
Compose files already published the two that way. It writes the same `.env`
and `tools.json` the command line does, so the two are interchangeable and
neither owns the files.

**It is never part of the MCP server.** That process speaks JSON-RPC over
stdio and stdout belongs to the protocol. This is a separate command, started
by a person, that stops when they are done. The two share their configuration
modules and nothing else.

**Over stdio the server can start it, at the person's request**, since
2026-10-10. It offers an MCP prompt, `open_setup`, titled "Set up Lexware
Office", and picking it in the client starts `setup` as a detached process
with no hold on stdout, which opens the browser signed in. When the
port already answers it starts nothing. The reason is a client that runs the
server where nothing else can reach it: measured in a Windows Sandbox with
Claude Desktop from the Store, a server installed as a desktop extension runs
on a Python inside the app's container, and both the console script and the
`python.exe` of its environment fail when started from outside, because the
paths they were made with exist only inside. Started by the server, `setup`
runs inside as well, and it worked there on the first try. It writes the
per-user directory, which the container does not redirect, so a permission
saved there reached the running server as `tools/list_changed` the same
second.

**It does not weaken [section 9](permissions.md#9-permission-model) where
the client keeps prompts to the person.** A prompt is user-controlled in MCP,
not the model's to call, and this one reaches no data and changes nothing
itself: what the page saves is decided by the person in front of it. That guard
is the client's prompt handling, not anything the server can enforce. A client
that hands its prompts to the model - agent frameworks, the SDK's own client,
some editors - lets the model open a signed-in page, and with a browser tool
beside it tick boxes under *Rechte* and read the bearer token, though never the
key. So `LXO_MCP_SETUP_PROMPT=0` withholds the prompt, decided 2026-10-15 as a
variable that defaults to on: Claude Desktop, the client it exists for, keeps
prompts to the person. So does Claude Code, which lists it among its slash
commands, and picked there it opened the interface, tried 2026-10-29 with a
session started by `--mcp-config`. Over HTTP it is not offered, since a remote
client would open a page on a machine it does not sit at. The prompt always
answers with the same sentence, because Claude Desktop holds a prompt's answer
against the text the extension declared and rejects any other as a possible
injection - measured, it said "Failed to attach prompt" while the browser
opened anyway. What happened goes to stderr instead. Since 0.10.0 both
manifests set `prompts_generated` and Desktop compares no prompt, see
[section 8](tools.md#8-tools), but an extension that updates itself
installed from 0.9.1 or earlier still compares, so the sentence stays. `setup`
is handed `--env-file` and `--tools-file` only when the server was started with
them, so a person who never configured a client is not told to put arguments
into one, and it inherits the server's environment, so a value a variable holds
shows as such on its pages.

**It ends itself after 30 minutes without a request**, `--exit-when-idle
30`, which the prompt passes and nothing else does. Nobody started it from
a terminal, so no window is there to close it, and while it runs it holds
the Python it was started with. Measured in the sandbox: an interface left
running from an earlier try kept Claude Desktop from removing the
extension, whose folder stayed behind with the old manifest in it, and the
next install did not replace it. Every connection counts as use, and it
ends the way Beenden does, after an action that is writing a file.

Over stdio the instructions a client receives name the prompt too. Without
that a model facing an empty tool list guessed at a broken connection, which
is what happened in the sandbox before the prompt existed. Since
`server_status` the list is never empty, and the instructions name the
prompt for a list that holds nothing else.

**Loopback by default, and loopback names only.** The pages have no password,
which is defensible exactly as long as they cannot be reached from another
machine, and the start code below closes them to the rest of the machine as
well. `--host` can bind another address, because a container has to: a
process on the container's own loopback cannot be reached through a
published port, and there the host-side publish on `127.0.0.1` is what keeps
it local. Whatever is bound, **a request is answered only if its `Host` names
`127.0.0.1`, `localhost` or `::1`.** That stops DNS rebinding - a page
elsewhere pointing a name it owns at this machine and reading the pages,
bearer token included, as its own origin - because a browser sends the name
the page used. **It is not access control.** `Host` is a header the caller
writes, and anything on the network that reaches a `0.0.0.0` bind can send
`Host: localhost` and be answered. Outside a container a bind beyond
loopback exposes the pages, and the start says so. Every
response carries `Cache-Control: no-store` for the same token. Every
state-changing request is guarded twice, because a page in another tab must
not be able to rewrite credentials or permissions: the `Origin` or `Referer`
has to name the loopback host **and port** the request went to, and a random
token from a `SameSite=Strict` cookie has to come back in the form. The port
matters because loopback alone admits any local program's page, and the token
has to be one this process issued, because cookies are not scoped by port: a
page on another local port can set the cookie to a value of its choosing and
put the same value in its form. Every value under the cookie's name is tried,
so one planted beside the real one does not win, and the header is read by
hand, since the standard library's parser drops all of it over one foreign
cookie it finds illegal. **A request another site started gets no new
cookie.** `SameSite=Strict` keeps the cookie off it, but a top-level
navigation may still set one, and a new session in the answer would replace
the signed-in one, so any page could sign the browser out with a link. Such
a request, `Sec-Fetch-Site` `cross-site` or `same-site` without a cookie
this process knows, gets a page with a link to the same address, which the
browser follows with the cookie. At most 100 sessions that never gave the
start code are kept, the oldest goes first, since every request without a
cookie makes one.

**A port in use ends the start.** On Windows `SO_REUSEADDR`, which the
standard library's HTTP server sets, lets a second process bind a port
another is listening on, and connections keep going to the first - so a
second interface came up, and the key typed into the browser reached the
old one or another program. It is off there, and a taken port ends `setup`
with one line. Elsewhere the option only allows a restart while old
connections linger, and stays on.

The API base URLs must be `https://`. The key travels to `LXO_MCP_BASE_URL` on
every request, so the page cannot be used to point it somewhere in the clear,
and `load_settings` refuses the same for the server.

**The pages are German.** This is the only surface a person reads, and
Lexware Office is sold for German companies only — its own help centre rules
out an Austrian or Swiss company as the account holder, so a language switch
would be machinery for a case that does not exist. Code, comments and
docstrings stay English, and so do the messages `settings/` raises: those are
quoted into the page rather than translated, because a German paraphrase
would be a second copy of a rule that lives in the code.

**Reworked, decided 2026-10-08.** The three pages of August had grown out of
one afternoon: the overview was a table of fourteen settings with their
variable names and the same path six times over, the credentials page held
the key, the HTTP token and every other setting in one form, the permissions
page put the legend and the profiles before the boxes and the save button
after twenty-five rows, and a reload after a save repeated the post. The
rework gave the interface a template engine, a frame, four pages and a
start code, built the same day in that order: the engine and the frame
with the three pages moved one to one, then the four pages below with
Post/Redirect/Get and a question before every destructive action, then the
start code.

**The engine.** Jinja2, imported in exactly one module, `configui/templates.py`,
with autoescaping on and `StrictUndefined`, so a typo in a template raises
instead of rendering an empty cell. The one filter lives there as well,
German numbers, and the source badge is a macro. A path is not shortened but
folded, behind its file's name. The templates are package data
under `configui/templates/`. `base.html` holds the sidebar, the top bar with
the heading, the line under it and the page's primary action, the message,
the content and a footer with the version. `components/ui.html` holds the
macros every page is built from: a card, a field, the source badge, a tag, a
notice, the CSRF field, an action with a question before it. A page has no
markup of its own for any of these. `pages/` has one file per page,
`partials/` the pieces of one page, such as the sidebar, the message and a
tool group. The server stays the standard library's threading HTTP server: a
web framework would be a second one in the package, for four forms.
`pages.py` builds the context of each page and nothing else, `actions.py`
answers with a redirect, a page and its message, or a download rather than
bytes, and the page shell and the inline assets of August are gone.
`state.py` changed in two places: the names of a value's source moved in
from the page shell, and a setting's display reads a `Settings`, so the
settings page reads its defaults the same way. `probe.py`, `profiles.py`,
`transfer.py`, `stamp.py` and `cost.py` did not change. `tests/test_layers.py`
confines `jinja2` to that one module, and checks that the server starts
without loading it: the console script imports `configui` for every start,
so `configui.start` imports the pages only when it runs.

**Static files and a content security policy.** The stylesheet and the one
script are files under `configui/static/`, served under `/static/`, and
every response carries `Content-Security-Policy: default-src 'self'`. No
inline style, no inline script, no inline handler. The script carries the
file picker of the import, the live counter of the permissions page and the
question a form asks through `data-confirm`. What the counter needs, the
cost of each tool and whether it reads or removes, is on the checkbox as a
`data-` attribute rather than in a script block. Until step 2 the stylesheet
and two scripts were strings sent inline with every page, which was the
right size for a page opened for minutes and had no answer to a policy. The
policy names `base-uri`, `form-action` and `frame-ancestors` beside
`default-src`, which does not cover them, and the static files are a fixed
list: a request names one of the two or is answered with a 404, so no path
a browser sends reaches the filesystem.

**The look.** Colour tokens in a light, bluish palette, dark mode following
the system setting, and three state colours, green, amber and red, each with
a soft background for tags and notices. Every text colour keeps 4.5:1
against every background it is used on, in both modes, and a test computes
that from the stylesheet. The sidebar collapses to a top bar below 860 px.

**Four pages.** Each has a heading, one line under it saying what the page is
for, and its primary action at the top right.

| Page | What it answers |
|---|---|
| Overview (`Übersicht`) | A card *Stand* with three rows and their tags: the key stored or missing, the permissions as n of 25 on with what they cost or no file yet, the last connection test with the account or never run. The first red row is the next step and links to the page that does it. A card *Client* with the `"args"` entry to copy, and the warning that a server without `--env-file` reads another file only when that is true. A card *Dateien* with each file's name and state, the full path folded. |
| Credentials (`Zugangsdaten`) | The key, checked against the API before it is written unless that is declined, and the connection test as a card beside it. The HTTP token as a folded card, open only when the transport is not stdio, *Neu erzeugen* with a question before it. |
| Permissions (`Rechte`) | The counter and *Rechte speichern* at the top right, the presets as a bar, then one card per domain with its group switches and the tool rows with mark and cost. The legend, the profiles and import and export folded underneath, deleting a profile with a question before it. |
| Settings (`Einstellungen`) | The thirteen settings that are no secret, in four cards: the connection (the two base URLs, the timeout, the rate, the burst), the output (rows per page, PDF pages, the log level), the files (the download directory, the cache, the upload directory, the addresses an upload may be fetched from), the setup (whether the client is offered the prompt that opens the interface, a choice of on, off and the default). The placeholder shows what empty means, the source badge stays. A value held by an environment variable is marked as such and offered as no field, since typing over it would change nothing. |

The settings page reads a value in effect and a default the same way, so
the placeholder of an empty field is what empty means rather than what
applies right now. That is the default, unless another setting changes it:
with a download directory named, an empty cache count keeps every download,
so each placeholder is read from the file as it is with that one field
emptied. The log level is a choice of the levels the server
knows rather than free text. On the overview an untested connection is not
red: only a button ever tests it, so it is no fault, and the next step is
the first row that is.

**Forms.** Every form that goes through answers with a redirect and one
message, shown once at the top of the next page. The message is held in the
process beside the session cookie that already exists for CSRF, never in the
URL, so a link cannot put words into the interface. A refused form comes
back at once with what was typed and the reason at the top, with status 400,
and the key is never shown again. A refusal raised in `settings/` is quoted,
not translated, as above. Every destructive action asks first.

**The start code.** `setup` makes a random code at start, writes the address
with the code to stderr and opens the browser with a code of its own, see
below. Without a valid code every page shows one field, *Code eingeben*, and
the static files are the one thing served without it, since that page needs
them too. After the first valid request the session cookie carries the
sign-in, and a redirect takes the code out of the URL, to the page the
address named or, for any other address, to the overview. A code in an
address that a browser says another page opened, `Sec-Fetch-Site`
`cross-site` or `same-site`, is not tried, since a GET never meets the
`Origin` check and a page elsewhere could send codes in a loop. The field is
a form like any other, behind the `Origin` and CSRF checks. After five wrong
codes every further wrong one is answered two seconds later, and those
answers go out one at a time, so a loop cannot fill the log faster in
parallel either. A right code is checked first and never waits behind them,
or a script looping wrong codes would keep the person out, and it starts the
count over. The code is 16 random bytes, so the wait is not what protects it:
it keeps a stray script from filling the log. With `--no-browser` and in a
container the line is on stderr and in the container's log, where the
operator reads anyway. **The browser gets a code of its own, spent by its
first sign-in**, since 2026-10-15. The address is handed to the browser as an
argument, and on Linux and macOS it stays in that process's command line for
as long as the browser runs, which another user of the same machine may list.
Opened with the start code, that was a sign-in for the whole run, and a
`setup` the prompt started had no `--no-browser` to avoid it, since nobody
reads its stderr. So the browser is opened with a second random code, and the
first sign-in with it spends it: what stays in the command line opens nothing
afterwards. The printed code is unchanged, for the terminal and the log. A
browser that lost its session after that signs in with the printed code, or,
when the prompt started the interface, from the prompt again once the
interface has ended itself after its idle time. The code closes the pages to
other processes and users of the same machine, which the host and origin
checks above never did. It does not make a bind beyond loopback safe, since
it travels in the clear over HTTP, and the warning at the start stays. A
password was weighed and dropped: it needs a stored hash, a way to reset it
and a first run that creates it, for a page that runs for minutes and ends. A
code has no secret that outlives its process.

**Beenden ends it from the page**, added 2026-10-08 beside the start code.
The interface is meant to run for minutes and nothing stops it, so the way
out sits in the sidebar of every page, with a question first, rather than
only in a terminal that may be behind other windows. It is a form behind
every guard a form has, the start code included, so a stranger can end
nothing. The answer goes out first and the server stops a second later,
long enough for the browser to fetch the stylesheet, from a thread of its
own, since `shutdown` waits for the serving loop the request is part of.
That thread waits for a running action to finish, because the request
threads are daemons and a save cut off halfway would be the one harm, and
a form arriving meanwhile is answered with a 503. In a container the
process ends and the `setup` service, which has no restart policy, stays
stopped.

**Rules for every page, the four and any later one.** A page is one template
under `pages/` and one entry in the sidebar. A route reads the form, calls
one function of `actions.py` and renders or redirects, and decides nothing
itself. A template gets the context it needs and computes nothing `pages.py`
can pass. Every page has a test that renders it and one per form, and every
page still renders without a browser, which is how the working guidelines
say to read one. Checklist for a new page: the template, the entry, the
context function, the tests, a row in the table above, and a changelog entry
only when a person notices.

**What does not change.** The command and its flags, `--port`, `--host`,
`--no-browser`, `--env-file` and `--tools-file`, and the port. `--public-port`
and `--exit-when-idle` were added after the rework: the first for a container
published under another port, it changes the port the printed address names and
nothing else, the second ends the interface after that many minutes without a
request, which the prompt passes. The three files, their formats, the search of
[section 7](configuration.md#7-configuration) and the pinning below. The URLs
of the pages and the posts, with `/settings` as a page, `/code` and `/static/`
added. The guards above: loopback, the `Host` check, `Origin` with the port,
the CSRF token, `no-store`, and `SO_REUSEADDR` off on Windows. The `setup`
service of both Compose files, whose comments now say where the code is. The
server, `settings/`, `policy.py` and the transport are not touched. The image
grows by Jinja2 and MarkupSafe, 1.2 MB with their bytecode, measured on
2026-10-08 in an installed environment.

**Both processes fix their files when they start, and never move them.** The
server pins its policy file in `build_server`, the interface pins its own in
`Installation`. The search of [section 7](configuration.md#7-configuration) can
answer differently the moment a file appears somewhere, and a process that
quietly changed which permissions it enforces — or edits — is the harder one to
reason about. Deleting the pinned file therefore disables everything rather
than promoting the next candidate, which is the safer of the two failures. What
still takes effect without a restart is the *content* of that file, read fresh
on every question: only its identity is fixed.

**The two can still disagree, and only one direction can fix it from here.**
A client usually starts the server with `--env-file` and `--tools-file`, and
`setup` is started separately and cannot see those arguments. So the overview
prints the `"args"` entry that would make the client match the files this
interface holds, and names the other way round as well — starting `setup`
with the same arguments.

**Five answers to "where did this value come from", not three.** A real
environment variable, the command line for the one setting it can name, the
`.env` this interface writes to, the search itself for a policy file nobody
named, and the built-in default. The fourth exists because a resolved path is
not a default.

There used to be a sixth — *another* `.env` the search also read — and it went
away with the merge on 2026-08-23. One file applies now, so a neighbouring one
cannot supply a value here. What replaced it is a statement about the whole
file rather than about a value: when this interface is editing a `.env` that a
server would not read, the overview says so beside the paths, because saving
would otherwise report success for work that never reaches the server.

**With no policy file the boxes open on read-only.** A blank form is a poor
starting point for a decision, and the alternative — every box empty — reads as
an invitation to tick things at random rather than as a proposal. It changes
nothing about [section 9.2](permissions.md#92-the-policy): no file still means
no tool but `server_status`, and nothing is written until somebody saves. Ticks
that do not describe the file are labelled as such at the top of the page,
which is the condition under which showing them is honest. Once a file exists
the boxes follow it, including a file that deliberately enables nothing.

**What a tool costs is shown next to it.** [Section 8](tools.md#8-tools)
measures the tool list at around 2,000 characters per tool, sent on every
request for the life of the server. The permissions page puts that number on
each row and totals it live, because switching a tool on is a budget decision
as well as a permission one and nothing else in the project makes that visible.
The total includes `server_status`, which has no box since no file decides it,
and is sent all the same.

**The marks are explained on the page, not in a tooltip.** Each row carries
what the tool does — `lesend`, `schreibend · create`, `schreibend · delete` —
and, where it applies, what becomes of what it writes: `nur App` for a record
only the web app deletes, `nur App · Buchhaltung` for one that enters the
books and can be bound later. A legend above the groups says what each of
those means, because a tooltip is a poor place for the one distinction this
page exists to make.

**Neither permanence mark claims a record is gone forever, or bound now.** The
wording here said `bleibt dauerhaft` on all five, which was wrong twice over:
the web app deletes most of it, and nothing is festgeschrieben at the moment it
is created. The legend now says that outright and names the four things that do
bind a record. Worth noticing for its own sake — the same overstatement was in
the tool descriptions until 2026-08-21 and was corrected there, then written
again here from memory rather than from
[section 5](upstream-api.md#5-upstream-api).

**Creating a profile and overwriting one are two buttons, not one.** A name
that is already taken is refused rather than silently replacing what is
there, and the match ignores case and spacing: "nur lesend" beside "Nur
lesend" is one profile to everybody except a dictionary, and the list sorts
case-insensitively, so the two would sit next to each other looking
identical. Replacing a profile is done by selecting it and pressing the
button that says so.

**Profiles are a convenience, never a second policy.** A profile is a named
list of enabled tool names, stored in `tool_profiles.json` beside the policy
file it belongs to. Loading one fills in the checkboxes and stops there — the
file is written when a person presses save, by the code that writes any other
change. Two files with a say in what may be asked of a live accounting system
would contradict [section 9.2](permissions.md#92-the-policy), which has one.

A profile also records **which tools existed when it was written**. Without
that, a tool that is off because somebody switched it off looks exactly like
a tool that is off because it did not exist yet, and only the second is worth
mentioning when a profile is loaded. A profile that never recorded it — one
written by hand — says nothing rather than announcing every omission.

**Timestamps carry microseconds and a UTC offset**, in profiles and on the
export alike. The offset because a bundle is made to travel and two local
times from two zones would order wrongly. Microseconds because that is what
`datetime` holds — and because nanoseconds would be decoration: measured on
2026-08-21, 200,000 consecutive `time.time_ns()` calls returned **nine**
distinct values, so the wall clock behind them advances about once a
millisecond, and Windows moves that resolution around depending on what else
is running. Six digits of clock beats six digits of clock and three of
padding, because somebody eventually relies on the difference.

**One policy file can be carried to another installation, and nothing else
can.** The download is a policy file in the shape `tools.json` already
has: one flag per tool, no wrapper, no format version. It is written the way
a save writes the file, from what the server makes of it, so a file edited
by hand comes out complete - every known tool named, a name that is no tool
dropped, only `true` read as on. So it can be dropped
into another installation's config directory or named with `--tools-file`,
and a file written by `--tools` reads here — one format for one thing, rather
than a second one wrapping it.

**Reading one follows the rule `--tools sync` follows.** A tool the file does
not name is off, which is what an unmentioned tool means everywhere else in
this project, so a file written before a tool existed leaves that tool
switched off rather than guessing. How many those are is said out loud, and a
name that is no longer a tool is reported and dropped. Reading only fills the
checkboxes: `tools.json` is written on save, as it is for a loaded profile,
which keeps one rule for how that file comes to be written.

**Two wider formats were built first and taken out again on 2026-08-22.** The
first carried the settings, the permissions and the profiles together, and
the settings were the problem: `LXO_MCP_TOOL_POLICY` and
`LXO_MCP_DOWNLOAD_DIR` are absolute paths describing one machine, and an
import writing the first would have pointed the target installation at a
policy file that does not exist there — nothing but `server_status`,
immediately after an import that appeared to grant some. The second
carried the profiles alone, which was safe but answered a question nobody
had: a profile is a convenience of this interface, while the policy file is
the thing an installation actually runs on.

No format carried the API key, and this one has nowhere to put a setting at
all.
