# Concept: configuration

Part of the [concept](../CONCEPT.md): sections 7 and 7.2.

## 7. Configuration

| Env var | Meaning | Default |
|---|---|---|
| `LXO_MCP_API_KEY` | Lexware Office API key. Required. Visible ASCII only, `!` to `~`: a space or an invisible character copied along with it is refused with a `ConfigError`, since it cannot travel in a header. | — |
| — | `--env-file` names the `.env` rather than searching for one, and nothing else is read: naming a file replaces the search exactly as `--tools-file` does. The real environment still wins over it, the order Docker and uvicorn use, so a client can override one value without editing the file. A path that does not exist ends the process rather than falling back to the search: starting anyway would mean behaving in a way the command line appears to rule out. | search |
| `LXO_MCP_BASE_URL` | API base URL, for tests and sandboxes. `https://` with a host, or the start is refused: the key travels to it. | `https://api.lexware.io` |
| `LXO_MCP_APP_BASE_URL` | Web app base used to build deeplinks. `https://` with a host, as for the API. | `https://app.lexware.de` |
| `LXO_MCP_TOOL_POLICY` | The per-tool policy file, see [section 9.2](permissions.md#92-the-policy). Without it the file is searched the same way the `.env` is, so a `config/tools.json` in a checkout overrides an installed one. | `tools.json`, resolved |
| `LXO_MCP_DOWNLOAD_DIR` | Where downloaded documents are written. | user cache dir |
| `LXO_MCP_KEPT_DOWNLOADS` | How many downloads the directory keeps, newest by modification time, and how many `resources/list` names. Older ones are deleted at start and after each download, see [section 13](errors-and-output.md#13-output-format). Unset, the default cache directory keeps 100 and a directory named by `LXO_MCP_DOWNLOAD_DIR` keeps everything, since that may be somebody's own folder. `0` keeps everything anywhere, and the list stays at 100. | unset |
| `LXO_MCP_UPLOAD_DIR` | The one directory `upload_file` and `attach_file_to_voucher` may read from, subdirectories included, links resolved before the check. Unset, they read any file the process can read with an accepted extension, except one on a network share (section 7.2), which is what a local stdio server has always done - the model names the path, so this is the setting that decides what can leave the machine. An `.xml` counts as a document there: any XML file the process can read is sent, and only the API refuses one that is not an XRechnung. | unset, anywhere |
| `LXO_MCP_UPLOAD_URLS` | The URL prefixes the same two tools may fetch a file from, comma separated: a scheme and a host, optionally a port and the start of a path. A prefix, not a pattern, so no wildcard. Unset, no URL is fetched. `https://` for any host, `http://` for `127.0.0.1`, `::1` and `localhost` alone - any other is a `ConfigError` at startup, and in the configuration interface before the file is written. See section 7.2. | unset, none |
| `LXO_MCP_PDF_PAGES` | Pages of a PDF `read_download` renders when the call does not say. Deliberately not named after a page size: `LXO_MCP_PAGE_SIZE` counts rows of a search result, this counts sheets of a document, and one answering for the other would be a quiet mistake. No upstream ceiling exists to derive a maximum from, and a caller overrides it per call anyway - up to 100, the most one call renders even when it passes null for every page. | `10`, at most `100` |
| `LXO_MCP_TIMEOUT` | HTTP timeout in seconds. | `30` |
| `LXO_MCP_RATE` | Token bucket refill, requests per second, global. | `1.5` |
| `LXO_MCP_BURST` | Token bucket capacity. Upstream holds 4, measured. | `2` |
| `LXO_MCP_PAGE_SIZE` | Rows per page, sent upstream as `size`. | `25` |
| `LXO_MCP_LOG_LEVEL` | Level of this server's own lines on stderr. Both HTTP clients, this server's and the SDK's, and the SDK itself stay at `WARNING` whatever it says, because their `INFO` lines carry request URLs and error text. | `INFO` |
| `LXO_MCP_SETUP_PROMPT` | Offer the prompt that opens the configuration interface over stdio, see [section 7.1](configuration-interface.md#71-the-configuration-interface). Set, it is on only for a yes, as every switch reads an odd value. `0` withholds it, and the instructions and the refusal of a call without a key stop naming it. | on |
| `LXO_MCP_TRANSPORT` | `stdio`, `streamable-http` or `sse`, see [section 6](transport.md#6-transport-and-runtime). `--transport` wins. | `stdio` |
| `LXO_MCP_BEARER_TOKEN` | The shared secret every HTTP request must carry. An HTTP transport refuses to start without one, see [section 6](transport.md#6-transport-and-runtime). Visible ASCII only, as the key. Registered as a secret, so it is redacted like the key. | — |
| `LXO_MCP_GENERATE_BEARER_TOKEN` | Make a token at startup when none is set, and write it into the settings file. For a deployment with nobody to type one - the image sets it. | off |
| `LXO_MCP_HTTP_HOST` | Address to bind for an HTTP transport. Anything but loopback is said on stderr. | `127.0.0.1` |
| `LXO_MCP_HTTP_PORT` | Port to bind. | `8770` |
| `LXO_MCP_HTTP_PATH` | URL path the HTTP transport serves on. | `/mcp` |
| `LXO_MCP_ALLOWED_HOSTS` | `Host` values the DNS-rebinding guard accepts besides the loopback names, comma separated. | — |
| `LXO_MCP_EXIT_ON_CONFIG_CHANGE` | End the process when the settings file changes, for something that restarts it, see [section 6](transport.md#6-transport-and-runtime). | off |

Precedence, highest first: a real environment variable, `.env` in the working
directory, `config/.env` in the working directory, `config/.env` of the source
checkout the package runs from, and `.env` in the per-user config directory
resolved via `platformdirs`.

The fourth rule exists because a client such as Claude Desktop spawns the
server with a working directory of its own, so a clone had to be startable from
anywhere without repeating its configuration. It is limited to a **source
checkout**, decided by a `pyproject.toml` beside the `config/` directory. An
installed package sits in `site-packages`, which has none, so nothing is read
from there — configuration read out of a directory shared with every other
installed package is not a property this server should have. The invocation
outranks the installation, which is why the working directory sits above it.

**Without a home directory there is no per-user directory.** That happens
when `HOME` is unset or empty and the uid has no password database entry, as
under `env -i` with a foreign uid. platformdirs raises then, from 4.12 on,
where it used to answer a relative `~/.config/...` that landed below whatever
the working directory was. The search leaves that candidate out and the
other three still count, so a checkout or a working directory needs no home.
Only where no file exists anywhere, and the answer would be the place to
create one, does it end in a `ConfigError` that says to set `HOME` or to name
the files. The default download directory follows the same rule: a download
asks for `LXO_MCP_DOWNLOAD_DIR` or `HOME`, the server starts without
publishing any, and the configuration interface shows the message in place
of a path. A process ending on this does so in one line on stderr, not a
traceback.

**A `.env` is UTF-8, with or without a byte order mark.** A file in another
encoding, Windows-1252 from an older editor for instance, is refused with a
`ConfigError` naming the file and the first byte that is not UTF-8: in one
line on stderr, and on the page of the configuration interface, which cannot
write it either. Decoding it with replacement characters instead would turn a
`ü` in a directory into a path that does not exist, and an update would write
the replacement back over the original bytes. A `.env` that is there but
cannot be read, a permission refused or a directory in its place, is refused
the same way, since 2026-10-28: read as empty, it started the server without
its key and its settings, and an update would have written the new values
alone over the rest. Only a file that is not there is no error. The policy
file and its profiles are read with a byte order mark allowed as well, since
2026-10-08: read as plain UTF-8, a `tools.json` saved by a Windows editor was
broken JSON, and every tool was off.

No secret is ever read from a versioned file. `config/.env` is gitignored,
and the settings sample, which is committed and ships inside the package,
holds no key.

### 7.2 Uploads from a URL

**What it is for.** Another MCP server - a mailbox, say - issues a
short-lived signed link for an attachment, and the model hands that link to
`upload_file` or `attach_file_to_voucher`. The file goes from service to
service and never through the model's context: base64 of a 5 MiB PDF is
nearly seven million characters, and a model is no reliable copier of bytes
anyway. Neither server knows the other or holds anything of the other's.
What connects them is the URL and `LXO_MCP_UPLOAD_URLS`. Built 2026-10-15,
and verified live the same day against the second test account with
`live/upload_from_url.py`: a PDF served by `http.server` on 127.0.0.1 was
fetched and uploaded, a link one port off was refused without a request, the
local server was asked once and saw no `Authorization` header, and the log
line named `http://127.0.0.1` and nothing after it.

**One parameter, `source`, replaced `path`.** A value that starts with
`https://` or `http://`, in any case, is a URL. A `file:` URL is refused with
the advice to give the path itself, since it would be a path read past
`LXO_MCP_UPLOAD_DIR` in disguise. Anything else is a path, read as before,
with the one exception below. Two parameters would have needed a rule for
which wins when both are given, and a caller would have had to learn it. The
cost is a renamed argument: a caller that passed `path` by name is refused
until it lists the tools again. No tool is new, so a policy file reads
exactly as it did.

**A network path is read only from the upload directory's share.** Two
separators of either kind at the start, `\\host\share` or `//host/share`,
make a path that is refused unless `LXO_MCP_UPLOAD_DIR` names the same share.
Windows connects to the host on the first call that touches such a path,
`resolve()` included, and signs in as the user running the server: 21 seconds
against an address that did not answer, measured 2026-10-28, before the
directory check had refused anything. So the share is compared as text before
the file system is asked, the same way on every platform.

**No URL without the setting.** The model chooses the URL, and a model reads
email. Without a list, one prompt in a message could have this server fetch
from anywhere it can reach - a document server on the local network that
answers only from inside, say - and file what came back in the books. So
nothing is fetched until the account owner names the addresses, golden rule
1 again. A prefix is a scheme and a host, optionally a port and the start of
a path, and a URL is compared to it part by part rather than as text, which
would let `https://files.example.com` cover
`https://files.example.com.elsewhere.net`. No port means the scheme's
default. A path is covered by segments: `/inbox` covers `/inbox/a.pdf` and
not `/inboxes/a.pdf`. A URL with a user name before its host is covered by
nothing, and neither is one whose path steps up with `..`, written plainly
or percent-encoded, nor one with a backslash after decoding - a server that
decodes before it routes would be reading another path than the one
checked. For the same reason `..;` is refused, which a server in the Tomcat
tradition reads as `..` once it has dropped the parameter, and so is a `%`
still there after one decoding, which a server that decodes twice reads
again: `%252e%252e` is `..` to it. Added in the review of 2026-10-16. The
prefixes are held to the same rule, `settings.plain_path`, so a prefix no
URL could be plain under stops the start rather than matching nothing.
All of it is decided before a connection is opened, so a URL
outside the list is refused without a word about what is out there.

**A prefix, not a pattern.** There is no wildcard, for the host or anywhere
else: a host is written out in full, and to allow a whole host is to give it
without a path. A `*` is read as what it stands in the text, a host name,
and since no host is called that, `https://*` allows nothing. It is not
refused at startup, decided 2026-10-16: the documentation says what a prefix
is, and a wildcard that worked would hand the choice of host back to the
model, which is what the list is there to take from it.

**`http://` is for this machine alone.** It carries the file in the clear,
so a prefix with it is taken for `127.0.0.1`, `::1` and `localhost` and for
no other host. Any other stops the start with a `ConfigError`, and the
configuration interface refuses to write it: a setting that would send
receipts unencrypted across a network is a mistake to stop at once, not at
the first call. The names are compared, not resolved. In a container,
"this machine" is the container.

**Its own client.** A fetch never goes through `api/connection.py`: another
address, and no `Authorization` header, since the Lexware key goes to Lexware
and nowhere else. None of the API client's machinery applies either. No retry -
a link that failed once is for the model to fetch again or to ask for anew. No
token from the bucket, see [section 10.1](client.md#101-rate-limiting). **No
redirect is followed**, since one leads off the address that was allowed, and a
service that answers with one has to be allowed under the address that serves
the file. **Thirty seconds for the whole of it**, connecting and reading
together, fixed rather than a setting: `LXO_MCP_TIMEOUT` bounds each request to
Lexware, and a server sending a byte now and then would never trip a per-read
limit.

**A proxy is for other hosts.** A proxy the environment names, through
`HTTP_PROXY` or `HTTPS_PROXY`, is used for a fetch as it is for Lexware,
except from `127.0.0.1`, `::1` and `localhost`, which are fetched directly.
httpx makes no such exception of its own, so behind a corporate proxy or in
a container that sets one, a link to a service on this machine went to the
proxy: it cannot reach that service, and it was handed the link with its
key. Found in the review of 2026-10-16.

**The response is held to what the API takes before it is read.** A status
other than 200 is refused by its number, and the page that came with it is
never passed on: an error page is the other service's business. A
`Content-Length` above 5 MiB is refused unread. The body is then streamed and
cut off at 5 MiB whether a length was declared or not, so a missing or false
header changes nothing. **Nothing compressed is taken**: the request asks for
`identity`, and a response with any other `Content-Encoding` is refused
before its body is read. httpx inflates a chunk before a count can see it, so
one 64 KiB chunk of gzip came to some 63 MB in memory before the ceiling
stopped it, found in the review of 2026-10-16, and the four types the API
takes are compressed formats already. The `Content-Type` has to be one of the
four the API takes, read without its parameters, and `text/xml` counts as
`application/xml`, which RFC 7303 says it is. Any other type is refused
before the body is read.

**A response that says only "bytes" is known by its first bytes**, decided
2026-10-16. That is `application/octet-stream`, `binary/octet-stream` or no
`Content-Type` at all. A mail program often attaches a PDF that way, a
mailbox server hands on what the sender declared, and a file store serves
whatever it holds as bytes, so refusing it refused the commonest receipt
there is. The body is then read under the same ceiling, and its start has to
be one of the four: `%PDF-`, the PNG and JPEG signatures, or `<?xml` with or
without a byte order mark. Anything else is refused without a word of what it
was. A type the response did declare is never second-guessed: a PDF served
as `text/html` is still refused, since one of the two is wrong and the
response said which it meant. The first bytes say what a file claims to be,
not that it is whole, and the API refuses a broken one as it would from
disk.

**The name.** From `Content-Disposition`, else the last part of the URL's
path, else `receipt`, each sanitized as a download's name is, because a
server elsewhere wrote it. A name without an extension the API takes is
given the type's - the end of a signed link is a key more often than a
filename. A name whose extension says another type is refused rather than
renamed: one of the two is wrong, and nothing here can tell which. An XML
file is not checked for being an XRechnung, as from disk: the API refuses
one that is not, and a second check here could only disagree with it.

**One check for both.** A file read from disk and one fetched end in
`storage.accepted`, which holds the size, the type and the name's extension,
and refuses an empty file, which is no receipt whatever the API makes of it.
What each source checks earlier - a file's size before it is read, a
response's before it is streamed - is an early way out, not a second rule.

**A URL is a capability**, see
[section 11](data-and-secrets.md#11-data-and-secrets-policy). A log line
names its scheme and its host and never its path or query. A URL outside the
setting is a line by its scheme alone, saying the address was outside the list
and nothing was requested: the host was the model's choice, and a host name can
carry any text a prompt put into it - a customer's name, an IBAN. Whoever reads
the log learns why the call was refused, and the host itself is in the refusal
the model was given. The same line without a scheme says that no address is
allowed at all.
