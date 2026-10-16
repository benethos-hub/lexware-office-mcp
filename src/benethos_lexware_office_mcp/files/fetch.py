"""A file to upload, fetched from a URL rather than read from this machine.

Another service - a mailbox server, say - hands the model a short-lived link
to an attachment, and the model hands the link on. The file goes from service
to service and never passes through the model's context, and neither server
knows the other: what connects them is a URL and the one setting that allows
it, ``LXO_MCP_UPLOAD_URLS``.

**A URL is a capability, like a token.** A signed link carries its key in the
path or the query, so neither reaches a log line: a line names the scheme and
the host, and only a host the setting names, see ``logbook.files``.

**Its own client, never the API's.** Another address, no ``Authorization``
header - the Lexware key goes to Lexware and nowhere else - and none of the
API client's retries or rate limiting, which exist for an account this is not
talking to. The rules, in the order they apply:

- the address is checked against the setting before anything is sent, so a
  URL outside it is refused without a word about what is out there
- no redirect is followed: one leads off the address that was allowed
- 30 seconds for the whole of it, connecting and reading together
- a ``Content-Length`` above 5 MiB is refused before the body is read, and
  the body is cut off at 5 MiB whether one was sent or not
- the ``Content-Type`` has to be one the API takes, or say no more than
  that the file is bytes, and then the first bytes have to be one
- the name comes from ``Content-Disposition`` or the URL, see
  :func:`.storage.upload_name`

What arrives then passes the check a file read from disk passes, see
:func:`.storage.accepted`.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import SplitResult, unquote, urlsplit

import httpx

from .. import __version__, logbook
from ..errors import ToolError, UpstreamError, ValidationError
from ..settings import Settings
from . import storage

__all__ = ["TIMEOUT", "is_url", "upload_from"]

# Connecting and reading together, not each: a server that trickles one byte
# a second would otherwise hold a call open for as long as it liked.
TIMEOUT = 30.0

_SCHEMES = ("https://", "http://")
_DEFAULT_PORTS = {"https": 443, "http": 80}

# The XML type RFC 7303 names beside `application/xml`, and which many a
# server sends. Both are the same thing to the API.
_ALIASES = {"text/xml": "application/xml"}

# Types that say a file is bytes and nothing more. A mail program attaching a
# PDF does this often, and so does a store that serves whatever it holds:
# the first bytes decide then, and only between the types the API takes.
_UNSAID = ("application/octet-stream", "binary/octet-stream", "")
_SIGNATURES = (
    (b"%PDF-", storage.UPLOAD_TYPES[".pdf"]),
    (b"\x89PNG\r\n\x1a\n", storage.UPLOAD_TYPES[".png"]),
    (b"\xff\xd8\xff", storage.UPLOAD_TYPES[".jpg"]),
    (b"<?xml", storage.UPLOAD_TYPES[".xml"]),
    (b"\xef\xbb\xbf<?xml", storage.UPLOAD_TYPES[".xml"]),
)


def is_url(source: str) -> bool:
    """Whether ``source`` names a URL to fetch rather than a path to read.

    A ``file:`` URL is neither, and is refused: it would be a path in
    disguise, read past ``LXO_MCP_UPLOAD_DIR`` by whatever opened it.
    """
    lowered = source.strip().lower()
    if lowered.startswith("file:"):
        raise ValidationError(
            "A file: URL is not fetched. Give the path on this machine itself."
        )
    return lowered.startswith(_SCHEMES)


async def upload_from(
    source: str,
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> storage.Upload:
    """What an upload tool sends: ``source`` read from disk, or fetched.

    ``transport`` is for the test suite, as the API client's is.
    """
    if is_url(source):
        return await fetch(source.strip(), settings.upload_urls, transport=transport)
    return await asyncio.to_thread(storage.read_upload, source, settings.upload_path)


async def fetch(
    url: str,
    allowed: tuple[str, ...],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> storage.Upload:
    """Fetch ``url`` for upload, if ``allowed`` names its address."""
    target = _within(url, allowed)
    scheme, host = target.scheme, target.hostname or ""
    started = time.perf_counter()
    try:
        async with asyncio.timeout(TIMEOUT):
            upload = await _get(url, host, target.path, transport)
    except ToolError as exc:
        logbook.files.not_fetched(scheme, host, exc)
        raise
    except (TimeoutError, httpx.TimeoutException):
        error = _failed(f"Fetching the file from {host} took longer than 30 seconds")
        error.code = "timeout"
        logbook.files.not_fetched(scheme, host, error)
        raise error from None
    except httpx.InvalidURL:
        raise ValidationError("This is not a URL that can be fetched.") from None
    except httpx.HTTPError:
        error = _failed(f"The file could not be fetched from {host}: no connection")
        error.code = "connection"
        logbook.files.not_fetched(scheme, host, error)
        raise error from None
    logbook.files.fetched(
        scheme, host, len(upload.content), logbook.tally.ms_since(started)
    )
    return upload


async def _get(
    url: str, host: str, path: str, transport: httpx.AsyncBaseTransport | None
) -> storage.Upload:
    """The response, refused at the first rule it breaks, body read last."""
    label = f"The file from {host}"
    async with (
        httpx.AsyncClient(
            transport=transport,
            timeout=TIMEOUT,
            follow_redirects=False,
            headers={"User-Agent": f"benethos-lexware-office-mcp/{__version__}"},
        ) as client,
        client.stream("GET", url) as response,
    ):
        # Nothing of the body is read before these, and none of it is ever
        # passed on: an error page is the other service's business.
        status = response.status_code
        if status != 200:
            redirect = (
                ", a redirect, which is not followed" if 300 <= status < 400 else ""
            )
            error = _failed(
                f"The file was not fetched from {host} (status {status}{redirect})"
            )
            error.status = status
            raise error
        declared = _declared_length(response)
        if declared is not None and declared > storage.MAX_UPLOAD:
            raise storage.too_large(label, declared)
        content_type = _content_type(response)
        unsaid = content_type in _UNSAID
        if not unsaid and content_type not in storage.UPLOAD_TYPES.values():
            raise storage.not_accepted(content_type)
        content = await _capped(response, label)
        if unsaid:
            content_type = _sniffed(content, content_type)
        name = storage.upload_name(
            response.headers.get("content-disposition", ""), path, content_type
        )
    return storage.accepted(content, name, content_type, label=label)


def _within(url: str, allowed: tuple[str, ...]) -> SplitResult:
    """``url`` taken apart, if one of the ``allowed`` prefixes covers it.

    Compared part by part rather than as text: as text,
    ``https://files.example.com`` would cover
    ``https://files.example.com.elsewhere.net`` as well. The scheme, the
    host and the port have to be the prefix's own - no port means the
    scheme's - and the path has to be the prefix's or lie below it. A path
    that steps up with ``..``, written plainly or percent-encoded, is under
    no prefix, whatever it starts with.
    """
    if not allowed:
        logbook.files.none_allowed()
        raise ValidationError(
            "This server fetches no URL for upload: no address is allowed in "
            "LXO_MCP_UPLOAD_URLS. Give a path on this machine, or ask the "
            "account owner to allow the address."
        )
    try:
        target = urlsplit(url)
        port = _port(target)
    except ValueError:
        raise ValidationError("This is not a URL that can be fetched.") from None
    if target.hostname and "@" not in target.netloc and _plain(target.path):
        for prefix in allowed:
            base = urlsplit(prefix)
            if (target.scheme, target.hostname, port) == (
                base.scheme,
                base.hostname,
                _port(base),
            ) and _under(target.path, base.path):
                return target
    # By the scheme alone, which `is_url` held to http or https. The host is
    # the model's choice and stays out of the log.
    logbook.files.not_allowed(target.scheme)
    raise ValidationError(
        f"{target.hostname or 'This URL'} is outside the addresses this server "
        "may fetch uploads from, so nothing was requested. Ask the account "
        "owner about LXO_MCP_UPLOAD_URLS."
    )


def _port(parts: SplitResult) -> int:
    return parts.port or _DEFAULT_PORTS.get(parts.scheme, 0)


def _plain(path: str) -> bool:
    """Whether ``path`` stays where it says, decoded as a server might decode it."""
    decoded = unquote(path)
    return "\\" not in decoded and not any(
        segment in (".", "..") for segment in decoded.split("/")
    )


def _under(path: str, base: str) -> bool:
    """Whether ``path`` is ``base`` or below it, segment by segment.

    ``/inbox`` covers ``/inbox`` and ``/inbox/a.pdf``, not ``/inboxes``. A
    base ending in a slash covers what follows it.
    """
    if not base or base == "/" or base.endswith("/"):
        return (path or "/").startswith(base or "/")
    return path == base or path.startswith(f"{base}/")


def _declared_length(response: httpx.Response) -> int | None:
    """The ``Content-Length`` the response states, if it states a number."""
    try:
        return int(response.headers.get("content-length", ""))
    except ValueError:
        return None


def _content_type(response: httpx.Response) -> str:
    """The response's type without its parameters, an alias read as its name."""
    raw = response.headers.get("content-type", "").split(";")[0].strip().lower()
    return _ALIASES.get(raw, raw)


def _sniffed(content: bytes, declared: str) -> str:
    """The type ``content`` starts as, of those the API takes.

    Only for a response that did not say, and only by the first bytes: a
    file that starts as a PDF and is none is the API's to refuse, as one
    read from disk under a ``.pdf`` name would be.
    """
    for signature, content_type in _SIGNATURES:
        if content.startswith(signature):
            return content_type
    served = f"served as {declared}" if declared else "without a content type"
    raise storage.not_accepted(
        f"a file {served} that does not start as any type it takes"
    )


async def _capped(response: httpx.Response, label: str) -> bytes:
    """The body, read until it passes the ceiling and not a byte longer.

    Counted after decoding, which is what is uploaded, so a compressed
    response cannot unpack into more than it was allowed.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > storage.MAX_UPLOAD:
            raise storage.too_large(label)
        chunks.append(chunk)
    return b"".join(chunks)


def _failed(what: str) -> UpstreamError:
    return UpstreamError(f"{what}, so nothing was sent to Lexware.")
