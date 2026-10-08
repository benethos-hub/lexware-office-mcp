"""What every offline suite builds before its first assertion.

A client that never sleeps, a provider around it, a server on top, and a
transport handler that answers a script and remembers what it was asked. Ten
files carried their own copy of each, every one a little different, so a
change to how a client is built was ten edits and a fixture that behaved
differently across the suite by accident.

Nothing here touches the network or the clock: the bucket is huge and its
sleep returns at once, and so does the client's. The one exception is the
configuration interface at the end, served on a loopback port and driven by
a browser of a cookie jar and forms, as its suites did with a copy each.
"""

from __future__ import annotations

import http.cookiejar
import io
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from benethos_lexware_office_mcp.api.client import ClientProvider, LexwareClient
from benethos_lexware_office_mcp.api.ratelimit import TokenBucket
from benethos_lexware_office_mcp.configui.app import ConfigServer
from benethos_lexware_office_mcp.configui.app import Handler as PageHandler
from benethos_lexware_office_mcp.configui.state import Installation
from benethos_lexware_office_mcp.logbook import configure
from benethos_lexware_office_mcp.logbook.output import PACKAGE
from benethos_lexware_office_mcp.server import PolicyServer, build_server
from benethos_lexware_office_mcp.settings import Settings

__all__ = [
    "API_KEY",
    "Browser",
    "serving",
    "signed_in",
    "FILE_ID",
    "OPEN_PROVIDERS",
    "PDF",
    "UPLOADED",
    "write_policy",
    "downloaded",
    "make_pdf",
    "recorder",
    "Answer",
    "Handler",
    "Scripted",
    "always",
    "capture_lines",
    "fast_bucket",
    "fast_client",
    "fast_provider",
    "no_sleep",
    "server_with",
]

# Long enough to be registered as a secret, see `errors.register_secret`, so
# a test that asserts redaction is asserting something.
API_KEY = "test-key-0123456789"

Handler = Callable[[httpx.Request], httpx.Response]

# One scripted answer: a status and a JSON payload, a whole response, or an
# exception the transport raises instead of answering.
Answer = tuple[int, Any] | httpx.Response | Exception


async def no_sleep(_seconds: float) -> None:
    return None


def fast_bucket() -> TokenBucket:
    """A bucket that never makes anybody wait."""
    return TokenBucket(1000.0, 100, sleep=no_sleep)


def fast_client(
    handler: Handler,
    *,
    settings: Settings | None = None,
    bucket: TokenBucket | None = None,
    sleep: Any = no_sleep,
    **fields: Any,
) -> LexwareClient:
    """A client against ``handler``, with the API key set and no real time.

    ``fields`` go into the :class:`Settings` beside the key, ``settings``
    replaces the whole object. ``bucket`` and ``sleep`` are for a test about
    waiting, which records the waits rather than skipping them.
    """
    return LexwareClient(
        settings or Settings(api_key=API_KEY, **fields),
        transport=httpx.MockTransport(handler),
        bucket=bucket or fast_bucket(),
        sleep=sleep,
    )


# Every provider a test builds, closed by the `providers_closed` fixture in
# conftest.py once the test is over, whether it passed or not. Closing it as
# the test's last line was skipped by the first failing assert before it, and
# left a client open behind every failure.
OPEN_PROVIDERS: list[ClientProvider] = []


def fast_provider(
    handler: Handler,
    *,
    settings: Settings | None = None,
    bucket: TokenBucket | None = None,
    **fields: Any,
) -> ClientProvider:
    """The one provider a server takes, against ``handler``.

    ``fields`` go into the :class:`Settings` beside the key. ``settings``
    replaces that whole object, for a test about the settings themselves.
    """
    provider = ClientProvider(
        settings or Settings(api_key=API_KEY, **fields),
        transport=httpx.MockTransport(handler),
        bucket=bucket or fast_bucket(),
        sleep=no_sleep,
    )
    OPEN_PROVIDERS.append(provider)
    return provider


def server_with(handler: Handler, **fields: Any) -> tuple[PolicyServer, ClientProvider]:
    """A server whose every tool answers from ``handler``, and its provider.

    The provider is returned too, for a test that looks at it. It is closed
    after the test either way. ``fields`` are :class:`Settings` fields,
    ``page_size`` or ``download_path`` say.
    """
    settings = Settings(api_key=API_KEY, **fields)
    provider = fast_provider(handler, settings=settings)
    return build_server(settings, provider), provider


def capture_lines(caplog: Any, level: str) -> Any:
    """``caplog`` catching this package's lines at ``level``.

    Logging is configured first the way the server configures itself, so a
    test reads the lines a person would see on stderr - into a buffer here,
    since stderr belongs to pytest.
    """
    configure(level, io.StringIO())
    caplog.set_level(getattr(logging, level), logger=PACKAGE)
    return caplog


def write_policy(path: Path, flags: Mapping[str, bool]) -> Path:
    """A policy file holding exactly ``flags``, as a person might write one.

    Raw JSON rather than ``ToolPolicy.save``, which completes and normalizes
    what it is given: a test about reading the file wants the file it names.
    Every test has a file with every tool on already, from conftest.py, so
    this is for a test that needs some other answer.
    """
    path.write_text(json.dumps(dict(flags)), encoding="utf-8")
    return path


class Scripted:
    """Answers a scripted sequence, and remembers what it was sent.

    Each answer is a ``(status, payload)`` pair, a ready ``httpx.Response``,
    or an exception to raise. When the script runs out, ``repeat`` answers
    every further request - ``(200, {})`` unless said otherwise - which is
    what a test that only ever wants one canned answer relies on.
    """

    def __init__(self, *responses: Answer, repeat: Answer = (200, {})) -> None:
        self._responses = list(responses)
        self._repeat = repeat
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self._responses.pop(0) if self._responses else self._repeat
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, httpx.Response):
            if answer is self._repeat:
                # A fresh one per request: a response remembers the request
                # it answered, and two calls must not share that.
                return httpx.Response(
                    answer.status_code, content=answer.content, headers=answer.headers
                )
            return answer
        status, payload = answer
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json=payload)

    @property
    def calls(self) -> int:
        return len(self.requests)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    @property
    def methods(self) -> list[str]:
        return [request.method for request in self.requests]

    @property
    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(str(self.last.url)).query)

    @property
    def path(self) -> str:
        return urlparse(str(self.last.url)).path

    def body(self, index: int) -> Any:
        return json.loads(self.requests[index].content)


def always(payload: Any, status: int = 200) -> Scripted:
    """A handler that answers every request with the same JSON."""
    return Scripted(repeat=(status, payload))


# -- files ----------------------------------------------------------------

FILE_ID = "PLACEHOLDER-FILE-1"


def make_pdf(pages: int = 1, stream: bytes | None = None) -> bytes:
    """A real PDF with real glyphs, built here rather than checked in.

    The stub that used to stand in for one was never a valid document. It was
    enough while a PDF was only ever copied around, and stopped being enough
    the moment the server started rendering it, which is exactly the kind of
    fixture that hides a feature not working.
    """
    stream = stream or (
        b"BT /F1 12 Tf 1 0 0 1 60 760 Tm (Rechnung RE-2026-0142) Tj "
        b"0 -20 Td (Gesamtbetrag 2.200,91 EUR) Tj ET"
    )
    kids = " ".join(f"{4 + n} 0 R" for n in range(pages))
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        f"<</Type/Pages/Kids[{kids}]/Count {pages}>>".encode(),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    objects += [
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
        b"/Resources<</Font<</F1 3 0 R>>>>/Contents "
        + str(4 + pages).encode()
        + b" 0 R>>"
        for _ in range(pages)
    ]
    objects.append(
        b"<</Length "
        + str(len(stream)).encode()
        + b">>stream\n"
        + stream
        + b"\nendstream"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj".encode() + body + b"endobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{start}\n%%EOF\n"
    ).encode()
    return bytes(out)


PDF = make_pdf()

UPLOADED = {"id": "PLACEHOLDER-FILE-2", "voucherId": "PLACEHOLDER-VOUCHER-9"}


def recorder(
    content: bytes = PDF,
    status: int = 200,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
) -> Scripted:
    """A handler that answers every request with one canned file, or one JSON."""
    if json_body is not None:
        return Scripted(repeat=(status, json_body))
    return Scripted(
        repeat=httpx.Response(status, content=content, headers=headers or {})
    )


async def downloaded(server: Any, handler: Scripted, fmt: str = "pdf") -> str:
    """Download the one canned file through the server, and answer its URI."""
    result = await server.call_tool(
        "download_file", {"file_id": FILE_ID, "file_format": fmt}
    )
    return (result.structured_content or {})["uri"]


# --- the configuration interface --------------------------------------------


class Stay(urllib.request.HTTPRedirectHandler):
    """Answers a redirect with the redirect itself, rather than following it."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Browser:
    """Just enough of one for the configuration interface: a cookie jar,
    forms, and the CSRF token.

    It follows a redirect as a browser does, unless ``follow`` says not to.
    """

    # The server it talks to, for a test about the start code.
    server: ConfigServer

    def __init__(self, base: str) -> None:
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.staying = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), Stay()
        )

    def get(self, path: str) -> tuple[int, str, dict[str, str]]:
        return self._open(urllib.request.Request(self.base + path))

    def token(self) -> str:
        """Any page with a form carries it: it is the session cookie, echoed back."""
        _, body, _ = self.get("/credentials")
        found = re.search(r'name="_csrf" value="([^"]+)"', body)
        assert found, "the page carried no CSRF token"
        return found.group(1)

    def post(
        self,
        path: str,
        fields: dict[str, object],
        *,
        origin: bool = True,
        csrf: str | None = "",
        follow: bool = True,
    ) -> tuple[int, str, dict[str, str]]:
        pairs: list[tuple[str, str]] = []
        for key, value in fields.items():
            if isinstance(value, (list, tuple)):
                pairs.extend((key, str(item)) for item in value)
            else:
                pairs.append((key, str(value)))
        if csrf == "":
            csrf = self.token()
        if csrf is not None:
            pairs.append(("_csrf", csrf))
        request = urllib.request.Request(
            self.base + path, data=urlencode(pairs).encode("utf-8")
        )
        if origin:
            request.add_header("Origin", self.base)
        return self._open(request, follow=follow)

    def _open(
        self, request: urllib.request.Request, *, follow: bool = True
    ) -> tuple[int, str, dict[str, str]]:
        opener = self.opener if follow else self.staying
        try:
            with opener.open(request) as response:
                return (
                    response.status,
                    response.read().decode("utf-8"),
                    dict(response.headers),
                )
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


@contextmanager
def serving(installation: Installation) -> Iterator[ConfigServer]:
    """The configuration interface on a free loopback port, in a thread."""
    server = ConfigServer(("127.0.0.1", 0), PageHandler)
    server.installation = installation
    # A short poll interval only so that shutdown() returns promptly: the
    # default half second would be spent in the teardown of every test.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def signed_in(server: ConfigServer) -> Browser:
    """A browser signed in the way the address the start prints signs one in."""
    browser = Browser(f"http://127.0.0.1:{server.server_address[1]}")
    browser.get(f"/?code={server.code}")
    browser.server = server
    return browser
