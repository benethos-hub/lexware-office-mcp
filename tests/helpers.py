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
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from benethos_lexware_office_mcp.client import ClientProvider, LexwareClient
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import PolicyServer, build_server

__all__ = [
    "API_KEY",
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
    return ClientProvider(
        settings or Settings(api_key=API_KEY, **fields),
        transport=httpx.MockTransport(handler),
        bucket=bucket or fast_bucket(),
        sleep=no_sleep,
    )


def server_with(handler: Handler, **fields: Any) -> tuple[PolicyServer, ClientProvider]:
    """A server whose every tool answers from ``handler``, and its provider.

    The provider is returned too, so the test can close it. ``fields`` are
    :class:`Settings` fields, ``page_size`` or ``download_path`` say.
    """
    settings = Settings(api_key=API_KEY, **fields)
    provider = fast_provider(handler, settings=settings)
    return build_server(settings, provider), provider


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
