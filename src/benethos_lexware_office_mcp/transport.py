"""The HTTP transport, and the two things standing in front of it.

stdio needs none of this: the client starts the server as its own child
process, and nothing else can talk to it. A port can be reached by anything
that can route to it, so the same tools need two guards before they are
served over HTTP.

**A bearer token, which is required.** Whoever reaches the endpoint can spend
the account owner's API key on real accounting records, so the server refuses
to start an HTTP transport without one. It is a single shared secret compared
in constant time, not an OAuth flow — the server speaks for one account and
has no user to authorize.

**The SDK's DNS-rebinding guard**, which checks the `Host` and `Origin`
headers against an allowlist. Its default is the loopback names, which is
right for a local process and wrong the moment a container or a proxy puts
another name in front: those add themselves through ``allowed_hosts``. The
loopback entries are always kept, so extending the list can never lock out
local access.

Neither guard makes the port safe to publish on a network. They make it
survivable on a machine shared with other processes, which is what a
container on a loopback-published port is.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import Settings
from .errors import ConfigError

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from mcp.server.mcpserver import MCPServer
    from starlette.types import ASGIApp, Receive, Scope, Send

__all__ = [
    "bearer_middleware",
    "require_bearer",
    "run_http",
    "transport_security",
    "watch_for_change",
]

log = logging.getLogger(__name__)

# How often the settings file is looked at. Slow enough to cost nothing, fast
# enough that a person who just saved the key does not wait for it.
CONFIG_POLL_SECONDS = 2.0

# What the SDK allows by default. Kept and only extended, so naming a
# container host never removes local access.
LOOPBACK_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")
LOOPBACK_ORIGINS = ("http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*")


def bearer_middleware(app: ASGIApp, token: str) -> ASGIApp:
    """Wrap an ASGI app so every HTTP request must carry the bearer token.

    Non-HTTP scopes pass through untouched, or the wrapped app's lifespan
    would never run and the session manager would never start.
    """
    expected = f"Bearer {token}".encode()

    async def guarded(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        provided = headers.get(b"authorization", b"")
        if not hmac.compare_digest(provided, expected):
            await _unauthorized(send)
            return

        await app(scope, receive, send)

    return guarded


async def _unauthorized(send: Send) -> None:
    """A 401 that says how to authenticate and nothing else.

    No hint about whether a token was sent, whether it was close, or what the
    server is. An unauthenticated caller learns only that it needs a token.
    """
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})


def transport_security(allowed_hosts: tuple[str, ...]) -> Any:
    """The DNS-rebinding policy: the loopback defaults plus what was named."""
    from mcp.server.transport_security import TransportSecuritySettings

    origins = tuple(f"http://{host}" for host in allowed_hosts)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[*LOOPBACK_HOSTS, *allowed_hosts],
        allowed_origins=[*LOOPBACK_ORIGINS, *origins],
    )


def require_bearer(settings: Settings) -> str:
    """The token, or a refusal to serve HTTP at all.

    Checked before anything is built, so the process stops with one line
    instead of starting, reporting its tools and then failing.
    """
    if not settings.bearer_token:
        raise ConfigError(
            "An HTTP transport needs a bearer token. Set LXO_MCP_BEARER_TOKEN "
            "to a long random string: anything that can reach the port can "
            "otherwise use this server's API key against real accounting "
            "records. stdio needs none of this, the client owns the process."
        )
    return settings.bearer_token


def http_app(server: MCPServer, settings: Settings) -> ASGIApp:
    """The ASGI app to serve, with the bearer guard already in front."""
    token = require_bearer(settings)

    security = transport_security(settings.allowed_hosts)
    if settings.transport == "sse":
        app = server.sse_app(
            sse_path=settings.http_path,
            transport_security=security,
            host=settings.http_host,
        )
    else:
        app = server.streamable_http_app(
            streamable_http_path=settings.http_path,
            transport_security=security,
            host=settings.http_host,
        )
    return bearer_middleware(app, token)


def _fingerprint(path: Path) -> str | None:
    """What the file says right now, or ``None`` while it does not exist.

    The content rather than the timestamp: the configuration interface writes
    the whole file on every save, and two saves inside one clock tick would
    look identical by mtime.
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def watch_for_change(
    path: Path,
    on_change: Callable[[], None],
    *,
    stop: threading.Event,
    poll: float = CONFIG_POLL_SECONDS,
) -> None:
    """Call ``on_change`` once the file differs from what it said at the start.

    Settings are read when the process starts and never again - the API key
    goes into a long-lived client, and the rate limiter that hangs off it is
    the one this process is allowed to have. Rebuilding that in place would
    mean moving state between two clients. Ending the process instead hands
    the problem to whatever started it, and a fresh one reads everything
    again. Nothing calls this unless something is there to restart it.
    """
    baseline = _fingerprint(path)
    while not stop.wait(poll):
        if _fingerprint(path) == baseline:
            continue
        # Saving is a truncate followed by a write, so a poll landing inside
        # one reads an empty or half-written file and sees a change that is
        # not there. Look once more before acting: a rewrite of identical
        # content - which is what the interface does on every save, changed
        # or not - is back to the baseline by then, while a real change stays
        # changed and costs one extra interval.
        if stop.wait(poll):
            return
        if _fingerprint(path) == baseline:
            continue
        log.info("%s changed, ending this process so it is started again", path.name)
        on_change()
        return


def run_http(
    server: MCPServer,
    settings: Settings,
    *,
    watch: Path | None = None,
) -> None:  # pragma: no cover - a socket and a signal, driven by hand
    """Serve over HTTP until interrupted, or until ``watch`` changes."""
    import uvicorn

    running = uvicorn.Server(
        uvicorn.Config(
            http_app(server, settings),
            host=settings.http_host,
            port=settings.http_port,
            log_level=settings.log_level.lower(),
        )
    )

    stop = threading.Event()
    if watch is not None:
        threading.Thread(
            target=watch_for_change,
            args=(watch, lambda: setattr(running, "should_exit", True)),
            kwargs={"stop": stop},
            name="settings-watch",
            daemon=True,
        ).start()

    try:
        running.run()
    finally:
        stop.set()
