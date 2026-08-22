"""The bearer guard and the rebinding allowlist in front of the HTTP transport.

Nothing here opens a socket. The middleware is an ASGI app, so it is called
the way a server would call it and its answer is read back from the messages
it sends.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from benethos_lexware_office_mcp import transport
from benethos_lexware_office_mcp.config import Settings, load_settings
from benethos_lexware_office_mcp.errors import ConfigError
from benethos_lexware_office_mcp.server import build_server, main

TOKEN = "a-token-that-is-not-a-real-one"


async def _inner(scope: Any, receive: Any, send: Any) -> None:
    """The app behind the guard. Answers 200 and records that it ran."""
    scope.setdefault("reached", [])
    scope["reached"].append(True)
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"through"})


async def _call(app: Any, scope: dict[str, Any]) -> tuple[int | None, bytes]:
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:  # pragma: no cover - never awaited
        return {"type": "http.request"}

    await app(scope, receive, send)
    status = next((m.get("status") for m in sent if m["type"].endswith("start")), None)
    body = b"".join(m.get("body", b"") for m in sent if m["type"].endswith("body"))
    return status, body


def _scope(authorization: str | None = None) -> dict[str, Any]:
    headers = (
        [] if authorization is None else [(b"authorization", authorization.encode())]
    )
    return {"type": "http", "headers": headers, "reached": []}


async def test_a_request_with_the_token_reaches_the_app() -> None:
    app = transport.bearer_middleware(_inner, TOKEN)
    scope = _scope(f"Bearer {TOKEN}")

    status, body = await _call(app, scope)

    assert status == 200
    assert body == b"through"
    assert scope["reached"] == [True]


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer",
        f"Bearer {TOKEN} ",
        f"bearer {TOKEN}",
        f"Bearer {TOKEN}x",
        f"Bearer {TOKEN[:-1]}",
        "Basic dXNlcjpwYXNz",
    ],
    ids=[
        "absent",
        "empty",
        "no value",
        "trailing space",
        "wrong case",
        "one character too many",
        "one character short",
        "another scheme",
    ],
)
async def test_anything_but_the_exact_token_is_refused(header: str | None) -> None:
    app = transport.bearer_middleware(_inner, TOKEN)
    scope = _scope(header)

    status, body = await _call(app, scope)

    assert status == 401
    assert body == b'{"error":"unauthorized"}'
    assert scope["reached"] == [], "the app behind the guard must not run"


async def test_the_refusal_says_how_to_authenticate_and_nothing_else() -> None:
    """A caller learns it needs a bearer token, not whether it was close."""
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:  # pragma: no cover - never awaited
        return {"type": "http.request"}

    await transport.bearer_middleware(_inner, TOKEN)(
        _scope("Bearer wrong"), receive, send
    )

    headers = dict(sent[0]["headers"])
    assert headers[b"www-authenticate"] == b"Bearer"
    assert TOKEN.encode() not in b"".join(m.get("body", b"") for m in sent)


async def test_a_lifespan_message_passes_through_unguarded() -> None:
    """Otherwise the session manager never starts and every request hangs."""
    scope: dict[str, Any] = {"type": "lifespan", "reached": []}

    async def inner(s: Any, receive: Any, send: Any) -> None:
        s["reached"].append(True)

    await transport.bearer_middleware(inner, TOKEN)(scope, None, None)

    assert scope["reached"] == [True]


def test_the_allowlist_keeps_the_loopback_entries() -> None:
    """Naming a container host must not lock the machine itself out."""
    security = transport.transport_security(("lexware-office-mcp:8770",))

    assert set(transport.LOOPBACK_HOSTS) <= set(security.allowed_hosts)
    assert "lexware-office-mcp:8770" in security.allowed_hosts
    assert "http://lexware-office-mcp:8770" in security.allowed_origins


def test_without_extra_hosts_only_loopback_is_allowed() -> None:
    security = transport.transport_security(())

    assert list(security.allowed_hosts) == list(transport.LOOPBACK_HOSTS)
    assert security.enable_dns_rebinding_protection is True


def test_http_without_a_bearer_token_is_refused() -> None:
    """The whole point: a port anyone can reach must not carry the API key."""
    settings = Settings(api_key="k", transport="streamable-http")

    with pytest.raises(ConfigError) as excinfo:
        transport.http_app(build_server(settings), settings)

    assert "LXO_MCP_BEARER_TOKEN" in str(excinfo.value)


def test_the_app_is_built_with_the_guard_in_front() -> None:
    settings = Settings(api_key="k", transport="streamable-http", bearer_token=TOKEN)

    app = transport.http_app(build_server(settings), settings)

    assert callable(app)
    assert app is not None


def test_the_cli_refuses_http_without_a_token_and_says_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One line on stderr, no traceback, and nothing started."""
    policy = tmp_path / "tools.json"
    policy.write_text('{"get_profile": true}', encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--transport",
                "streamable-http",
                "--tools-file",
                str(policy),
                "--log-level",
                "ERROR",
            ]
        )

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "", "stdout carries the JSON-RPC stream"
    assert "LXO_MCP_BEARER_TOKEN" in captured.err
    assert "Traceback" not in captured.err


# -- the settings watcher ----------------------------------------------------


def test_a_changed_settings_file_ends_the_process(tmp_path: Path) -> None:
    """Not a reload: a fresh process is the only way every setting moves."""
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_API_KEY=first\n", encoding="utf-8")
    ended = threading.Event()
    stop = threading.Event()
    looking = threading.Event()

    watcher = threading.Thread(
        target=transport.watch_for_change,
        args=(env, ended.set),
        kwargs={"stop": stop, "poll": 0.01, "ready": looking},
        daemon=True,
    )
    watcher.start()
    assert looking.wait(5), "the watch never took its baseline"
    env.write_text("LXO_MCP_API_KEY=second\n", encoding="utf-8")

    assert ended.wait(5), "the change was not noticed"
    stop.set()
    watcher.join(timeout=5)


def test_an_untouched_file_ends_nothing(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_API_KEY=first\n", encoding="utf-8")
    ended = threading.Event()
    stop = threading.Event()
    looking = threading.Event()

    watcher = threading.Thread(
        target=transport.watch_for_change,
        args=(env, ended.set),
        kwargs={"stop": stop, "poll": 0.01, "ready": looking},
        daemon=True,
    )
    watcher.start()
    assert looking.wait(5), "the watch never took its baseline"
    assert not ended.wait(0.2)

    stop.set()
    watcher.join(timeout=5)
    assert not ended.is_set()


def test_the_same_content_written_again_is_not_a_change(tmp_path: Path) -> None:
    """The interface rewrites the whole file on every save, changed or not."""
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_API_KEY=same\n", encoding="utf-8")
    ended = threading.Event()
    stop = threading.Event()
    looking = threading.Event()

    watcher = threading.Thread(
        target=transport.watch_for_change,
        args=(env, ended.set),
        kwargs={"stop": stop, "poll": 0.01, "ready": looking},
        daemon=True,
    )
    watcher.start()
    assert looking.wait(5), "the watch never took its baseline"
    env.write_text("LXO_MCP_API_KEY=same\n", encoding="utf-8")
    assert not ended.wait(0.2)

    stop.set()
    watcher.join(timeout=5)


def test_a_file_that_appears_later_counts_as_a_change(tmp_path: Path) -> None:
    """A container starts before anyone has configured it."""
    env = tmp_path / ".env"
    ended = threading.Event()
    stop = threading.Event()
    looking = threading.Event()

    watcher = threading.Thread(
        target=transport.watch_for_change,
        args=(env, ended.set),
        kwargs={"stop": stop, "poll": 0.01, "ready": looking},
        daemon=True,
    )
    watcher.start()
    assert looking.wait(5), "the watch never took its baseline"
    env.write_text("LXO_MCP_API_KEY=written-now\n", encoding="utf-8")

    assert ended.wait(5)
    stop.set()
    watcher.join(timeout=5)


def test_a_file_caught_mid_save_is_not_a_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A save truncates before it writes, and a poll can land in between.

    CI caught this as a failing rewrite test: the empty read counted as a
    change and the process ended for nothing. Driven through the fingerprint
    rather than through a real write, because a race reproduced by timing is
    a test that passes when the machine is busy.
    """
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_API_KEY=same\n", encoding="utf-8")
    settled = "the-content"
    # Two agreeing reads, then the emptiness in the middle of a save, then the
    # same content back. Every read after the list is the settled one.
    reads = iter([settled, settled, "", settled])
    monkeypatch.setattr(transport, "_fingerprint", lambda _: next(reads, settled))

    ended = threading.Event()
    stop = threading.Event()
    looking = threading.Event()
    watcher = threading.Thread(
        target=transport.watch_for_change,
        args=(env, ended.set),
        kwargs={"stop": stop, "poll": 0.01, "ready": looking},
        daemon=True,
    )
    watcher.start()
    assert looking.wait(5), "the watch never took its baseline"
    assert not ended.wait(0.3)

    stop.set()
    watcher.join(timeout=5)
    assert not ended.is_set()


def test_a_change_that_stays_changed_still_ends_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Waiting for the file to settle costs an interval, it swallows nothing."""
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_API_KEY=first\n", encoding="utf-8")
    reads = iter(["before", "before", "after"])
    monkeypatch.setattr(transport, "_fingerprint", lambda _: next(reads, "after"))

    ended = threading.Event()
    stop = threading.Event()
    looking = threading.Event()
    watcher = threading.Thread(
        target=transport.watch_for_change,
        args=(env, ended.set),
        kwargs={"stop": stop, "poll": 0.01, "ready": looking},
        daemon=True,
    )
    watcher.start()
    assert looking.wait(5), "the watch never took its baseline"

    assert ended.wait(5)
    stop.set()
    watcher.join(timeout=5)


def test_ending_on_a_change_is_off_unless_asked_for() -> None:
    """Outside a container nothing would start it again, so it must not end."""
    assert load_settings({}).exit_on_config_change is False
    assert load_settings({"LXO_MCP_EXIT_ON_CONFIG_CHANGE": "1"}).exit_on_config_change
