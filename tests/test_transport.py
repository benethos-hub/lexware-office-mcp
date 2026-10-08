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

from benethos_lexware_office_mcp import cli
from benethos_lexware_office_mcp.cli import main
from benethos_lexware_office_mcp.errors import ConfigError, redact
from benethos_lexware_office_mcp.logbook.output import PACKAGE
from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.settings import Settings, load_settings
from benethos_lexware_office_mcp.transport import http as transport
from benethos_lexware_office_mcp.transport import watch

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


@pytest.mark.parametrize("kind", ["websocket", "something-new"])
async def test_no_other_scope_gets_past_the_guard(kind: str) -> None:
    """Only lifespan is waved through. A websocket with the right token or
    without one is closed before it is accepted, since nothing serves one."""
    scope: dict[str, Any] = {
        "type": kind,
        "headers": [(b"authorization", f"Bearer {TOKEN}".encode())],
        "reached": [],
    }
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await transport.bearer_middleware(_inner, TOKEN)(scope, None, send)

    assert scope["reached"] == []
    if kind == "websocket":
        assert sent == [{"type": "websocket.close", "code": 1008}]


def test_the_allowlist_keeps_the_loopback_entries() -> None:
    """Naming a container host must not lock the machine itself out."""
    security = transport.transport_security(("lexware-office-mcp:8770",))

    assert set(transport.LOOPBACK_HOSTS) <= set(security.allowed_hosts)
    assert "lexware-office-mcp:8770" in security.allowed_hosts
    assert "http://lexware-office-mcp:8770" in security.allowed_origins


def test_a_named_host_is_allowed_behind_tls_too() -> None:
    """A proxy ending TLS: the browser's Origin is https for the same Host."""
    security = transport.transport_security(("mcp.example.invalid",))

    assert "https://mcp.example.invalid" in security.allowed_origins
    assert "http://mcp.example.invalid" in security.allowed_origins


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


def test_a_token_asked_for_is_made_and_written_where_the_settings_live(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The container case: nobody to type a secret, so one is made at start."""
    env = tmp_path / ".env"
    env.write_text("# kept\nLXO_MCP_API_KEY=k\n", encoding="utf-8")
    settings = Settings(
        api_key="k", transport="streamable-http", generate_bearer_token=True
    )

    with caplog.at_level("WARNING", logger=PACKAGE):
        ready = transport.bearer_ready(settings, env)

    token = ready.bearer_token
    assert token is not None and len(token) >= 40
    written = env.read_text(encoding="utf-8")
    assert f"LXO_MCP_BEARER_TOKEN={token}" in written
    assert written.startswith("# kept\nLXO_MCP_API_KEY=k\n")
    assert load_settings(env_file=env).bearer_token == token
    # Named in the log by its file, never by its value, and scrubbed from any
    # error text from now on.
    assert ".env" in caplog.text
    assert token not in caplog.text
    assert redact(f"x {token} x") == "x <redacted> x"


def test_a_token_already_set_is_kept_and_nothing_is_written(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_API_KEY=k\n", encoding="utf-8")
    settings = Settings(
        api_key="k",
        transport="streamable-http",
        bearer_token=TOKEN,
        generate_bearer_token=True,
    )

    assert transport.bearer_ready(settings, env).bearer_token == TOKEN
    assert env.read_text(encoding="utf-8") == "LXO_MCP_API_KEY=k\n"


def test_no_token_and_none_asked_for_is_a_refusal_that_writes_nothing(
    tmp_path: Path,
) -> None:
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_API_KEY=k\n", encoding="utf-8")
    settings = Settings(api_key="k", transport="streamable-http")

    with pytest.raises(ConfigError, match="LXO_MCP_BEARER_TOKEN"):
        transport.bearer_ready(settings, env)

    assert env.read_text(encoding="utf-8") == "LXO_MCP_API_KEY=k\n"


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
        target=watch.watch_for_change,
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
        target=watch.watch_for_change,
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
        target=watch.watch_for_change,
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
        target=watch.watch_for_change,
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
    monkeypatch.setattr(watch, "_fingerprint", lambda _: next(reads, settled))

    ended = threading.Event()
    stop = threading.Event()
    looking = threading.Event()
    watcher = threading.Thread(
        target=watch.watch_for_change,
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
    monkeypatch.setattr(watch, "_fingerprint", lambda _: next(reads, "after"))

    ended = threading.Event()
    stop = threading.Event()
    looking = threading.Event()
    watcher = threading.Thread(
        target=watch.watch_for_change,
        args=(env, ended.set),
        kwargs={"stop": stop, "poll": 0.01, "ready": looking},
        daemon=True,
    )
    watcher.start()
    assert looking.wait(5), "the watch never took its baseline"

    assert ended.wait(5)
    stop.set()
    watcher.join(timeout=5)


def test_a_change_before_the_watch_starts_still_ends_the_process(
    tmp_path: Path,
) -> None:
    """Measured against what the settings were read from, not what it finds.

    Without that the watch took its baseline two polls into the start, and a
    key saved in those seconds was the baseline: measured 2026-10-08 in a
    container, the server kept running without the key it had been given.
    """
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_API_KEY=read-at-start\n", encoding="utf-8")
    read_from = watch.snapshot(env)
    env.write_text("LXO_MCP_API_KEY=saved-while-starting\n", encoding="utf-8")
    ended = threading.Event()
    stop = threading.Event()

    watcher = threading.Thread(
        target=watch.watch_for_change,
        args=(env, ended.set),
        kwargs={"stop": stop, "poll": 0.01, "since": read_from},
        daemon=True,
    )
    watcher.start()

    assert ended.wait(5), "a change made while starting was taken as the start"
    stop.set()
    watcher.join(timeout=5)


def test_the_file_as_it_was_read_is_not_a_change(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_API_KEY=same\n", encoding="utf-8")
    ended = threading.Event()
    stop = threading.Event()
    looking = threading.Event()

    watcher = threading.Thread(
        target=watch.watch_for_change,
        args=(env, ended.set),
        kwargs={
            "stop": stop,
            "poll": 0.01,
            "ready": looking,
            "since": watch.snapshot(env),
        },
        daemon=True,
    )
    watcher.start()
    assert looking.wait(5)
    assert not ended.wait(0.2)

    stop.set()
    watcher.join(timeout=5)


def _start_watched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env_text: str,
    while_reading: str | None = None,
) -> tuple[Path, watch.Snapshot | None]:
    """Run the CLI up to the transport, and return what the watch is given.

    ``while_reading`` is written into the .env right after the settings were
    read from it, the way a save lands while a server starts.
    """
    env = tmp_path / ".env"
    env.write_text(env_text, encoding="utf-8")
    policy = tmp_path / "tools.json"
    policy.write_text("{}", encoding="utf-8")
    given: dict[str, Any] = {}
    real_load = cli.load_settings

    def load_then_save(*args: Any, **kwargs: Any) -> Settings:
        settings = real_load(*args, **kwargs)
        if while_reading is not None:
            env.write_text(while_reading, encoding="utf-8")
        return settings

    def served(*args: Any, **kwargs: Any) -> None:
        given.update(kwargs)

    monkeypatch.setattr(cli, "load_settings", load_then_save)
    monkeypatch.setattr(cli, "run_http", served)
    monkeypatch.setenv("LXO_MCP_EXIT_ON_CONFIG_CHANGE", "1")
    monkeypatch.setenv("LXO_MCP_DOWNLOAD_DIR", str(tmp_path / "dl"))
    main(
        [
            "--transport",
            "streamable-http",
            "--env-file",
            str(env),
            "--tools-file",
            str(policy),
        ]
    )
    return env, given["since"]


def test_a_save_while_the_server_starts_is_a_change_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, since = _start_watched(
        tmp_path,
        monkeypatch,
        f"LXO_MCP_BEARER_TOKEN={TOKEN}\n",
        while_reading=f"LXO_MCP_BEARER_TOKEN={TOKEN}\nLXO_MCP_API_KEY=late\n",
    )

    assert since is not None
    assert since != watch.snapshot(env), "the watch would take the save as the start"


def test_a_token_this_process_wrote_is_not_a_change_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Or a fresh container would end over its own first act, every time."""
    monkeypatch.setenv("LXO_MCP_GENERATE_BEARER_TOKEN", "1")
    env, since = _start_watched(tmp_path, monkeypatch, "LXO_MCP_LOG_LEVEL=INFO\n")

    assert "LXO_MCP_BEARER_TOKEN=" in env.read_text(encoding="utf-8")
    assert since == watch.snapshot(env)


def test_a_shutdown_waits_for_open_streams_for_a_bounded_time() -> None:
    """A client's stream need not end because the server would like it to.

    Measured 2026-10-08 over SSE with the stream library's own drain switched
    off, which is how the stream behaved on 2026-09-30: without the bound the
    process still ran 40 seconds after its .env changed, with it the process
    ended 8.8 seconds after, the poll and the grace period.
    """
    config = transport.uvicorn_config(
        lambda *_: None,  # type: ignore[arg-type]
        Settings(transport="sse", bearer_token=TOKEN),
    )

    assert config.timeout_graceful_shutdown == transport.SHUTDOWN_GRACE_SECONDS
    assert 0 < transport.SHUTDOWN_GRACE_SECONDS <= 10


def test_ending_on_a_change_is_off_unless_asked_for() -> None:
    """Outside a container nothing would start it again, so it must not end."""
    assert load_settings({}).exit_on_config_change is False
    assert load_settings({"LXO_MCP_EXIT_ON_CONFIG_CHANGE": "1"}).exit_on_config_change


# -- Ctrl+C -----------------------------------------------------------------


@pytest.mark.parametrize("transport_name", ["stdio", "streamable-http"])
def test_an_interrupt_ends_in_a_line_and_130_not_a_traceback(
    transport_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """uvicorn raises SIGINT again once it has shut down, and stdio ends in it.

    Either way the transport's call ends in a KeyboardInterrupt, which is what
    the fake does here.
    """

    def interrupted(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_stdio", interrupted)
    monkeypatch.setattr(cli, "run_http", interrupted)
    env = tmp_path / ".env"
    env.write_text(
        f"LXO_MCP_BEARER_TOKEN={TOKEN}\nLXO_MCP_DOWNLOAD_DIR={tmp_path / 'dl'}\n",
        encoding="utf-8",
    )
    policy = tmp_path / "tools.json"
    policy.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--transport",
                transport_name,
                "--env-file",
                str(env),
                "--tools-file",
                str(policy),
            ]
        )

    assert excinfo.value.code == 130
    assert excinfo.value.__cause__ is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines()[-1].endswith("server: Stopped by an interrupt")
    assert "Traceback" not in captured.err
