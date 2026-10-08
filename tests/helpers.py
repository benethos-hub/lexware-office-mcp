"""What every offline suite builds before its first assertion.

A client that never sleeps, a provider around it, a server on top, and a
transport handler that answers a script and remembers what it was asked. Ten
files carried their own copy of each, every one a little different, so a
change to how a client is built was ten edits and a fixture that behaved
differently across the suite by accident.

Nothing here touches the network or the clock: the bucket is huge and its
sleep returns at once, and so does the client's.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from benethos_lexware_office_mcp.api.client import ClientProvider, LexwareClient
from benethos_lexware_office_mcp.api.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import PolicyServer, build_server
from benethos_lexware_office_mcp.settings import Settings

__all__ = [
    "API_KEY",
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


def fast_client(handler: Handler, **settings: Any) -> LexwareClient:
    """A client against ``handler``, with the API key set and no real time."""
    return LexwareClient(
        Settings(api_key=API_KEY, **settings),
        transport=httpx.MockTransport(handler),
        bucket=fast_bucket(),
        sleep=no_sleep,
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
