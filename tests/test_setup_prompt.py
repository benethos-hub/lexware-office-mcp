"""The prompt that opens the configuration interface, over stdio alone.

Nothing here starts a process: the probe for a running interface and the
start itself are handed in, and the one test of the real start replaces
``subprocess.Popen``.
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from benethos_lexware_office_mcp import cli, logbook
from benethos_lexware_office_mcp.server import SETUP_PROMPT_TITLE, build_server
from benethos_lexware_office_mcp.settings import Settings
from benethos_lexware_office_mcp.transport import setup_prompt
from benethos_lexware_office_mcp.transport.setup_prompt import (
    SETUP_PROMPT,
    SETUP_PROMPT_TEXT,
    offer_setup,
    setup_command,
)

PORT = 8771


def _server(tmp_path: Path, transport: str = "stdio") -> Any:
    return build_server(
        Settings(tool_policy_path=tmp_path / "tools.json", transport=transport)
    )


def _offered(
    tmp_path: Path, *, running: bool = False, started: list[list[str]] | None = None
) -> Any:
    server = _server(tmp_path)
    record = started if started is not None else []
    offer_setup(
        server,
        port=PORT,
        env_file=None,
        tools_file=None,
        listening=lambda port: running and port == PORT,
        start=lambda command: record.append(list(command)),
    )
    return server


def _pick(server: Any) -> str:
    result = asyncio.run(server.get_prompt(SETUP_PROMPT))
    [message] = result.messages
    assert message.role == "user"
    text: str = message.content.text
    return text


# -- what a client lists ------------------------------------------------------


def test_the_prompt_is_listed_with_its_title(tmp_path: Path) -> None:
    [prompt] = asyncio.run(_offered(tmp_path).list_prompts())

    assert prompt.name == SETUP_PROMPT
    assert prompt.title == SETUP_PROMPT_TITLE
    assert not prompt.arguments


def test_the_prompt_is_there_while_no_tool_is(tmp_path: Path) -> None:
    """The moment it is needed most: no policy file, so an empty tool list."""
    server = _offered(tmp_path)

    assert asyncio.run(server.list_tools()) == []
    assert [p.name for p in asyncio.run(server.list_prompts())] == [SETUP_PROMPT]


# -- what picking it does -----------------------------------------------------


def test_picking_it_starts_setup_once_and_answers_the_one_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    started: list[list[str]] = []
    server = _offered(tmp_path, started=started)

    with caplog.at_level("INFO"):
        text = _pick(server)

    assert text == SETUP_PROMPT_TEXT
    assert started == [setup_command(None, None)]
    assert f"on port {PORT}" in caplog.text


def test_a_running_interface_is_not_started_again(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """And the answer is the same: Claude Desktop rejects any other text."""
    started: list[list[str]] = []
    server = _offered(tmp_path, running=True, started=started)

    with caplog.at_level("INFO"):
        text = _pick(server)

    assert text == SETUP_PROMPT_TEXT
    assert started == []
    assert "not started again" in caplog.text


def test_a_start_that_fails_still_answers_the_one_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def refuse(command: Sequence[str]) -> None:
        raise OSError(2, "gone")

    server = _server(tmp_path)
    offer_setup(
        server,
        port=PORT,
        env_file=None,
        tools_file=None,
        listening=lambda port: False,
        start=refuse,
    )

    with caplog.at_level("WARNING"):
        text = _pick(server)

    assert text == SETUP_PROMPT_TEXT
    assert "could not be started" in caplog.text


def test_setup_is_started_on_the_files_the_server_was_given(tmp_path: Path) -> None:
    """Only those: naming the defaults would ask for client arguments."""
    env, policy = tmp_path / "test.env", tmp_path / "tools.json"
    base = [sys.executable, "-m", "benethos_lexware_office_mcp", "setup"]

    assert setup_command(None, None) == base
    assert setup_command(env, policy) == [
        *base,
        "--env-file",
        str(env),
        "--tools-file",
        str(policy),
    ]


def test_the_started_process_has_no_hold_on_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stdout is the JSON-RPC stream, and the child outlives the server."""
    seen: dict[str, Any] = {}

    def popen(command: Sequence[str], **kwargs: Any) -> None:
        seen.update(kwargs, command=list(command))

    monkeypatch.setattr(setup_prompt.subprocess, "Popen", popen)

    setup_prompt._start(["setup"])

    assert seen["command"] == ["setup"]
    for stream in ("stdin", "stdout", "stderr"):
        assert seen[stream] is subprocess.DEVNULL
    if sys.platform == "win32":
        assert seen["creationflags"] & subprocess.DETACHED_PROCESS
    else:
        assert seen["start_new_session"] is True


def test_the_probe_sees_whether_the_port_answers() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert setup_prompt._listening(port)

    assert not setup_prompt._listening(port)


# -- where it is offered ------------------------------------------------------


def _run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *argv: str
) -> list[dict[str, Any]]:
    offered: list[dict[str, Any]] = []
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda **_: Settings(tool_policy_path=tmp_path / "tools.json"),
    )
    monkeypatch.setattr(
        cli, "offer_setup", lambda server, **kwargs: offered.append(kwargs)
    )
    monkeypatch.setattr(cli, "run_stdio", lambda server: None)
    monkeypatch.setattr(cli, "run_http", lambda server, settings, **_: None)
    monkeypatch.setattr(cli, "bearer_ready", lambda settings, path: settings)
    cli.main(list(argv))
    return offered


def test_the_command_line_offers_it_over_stdio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    [offered] = _run(monkeypatch, tmp_path)

    assert offered["port"] == cli.configui.DEFAULT_PORT
    assert offered["env_file"] is None
    assert offered["tools_file"] is None


def test_a_named_policy_file_is_handed_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    named = tmp_path / "named.json"

    [offered] = _run(monkeypatch, tmp_path, "--tools-file", str(named))

    assert offered["tools_file"] == named


def test_over_http_there_is_no_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A remote client would open a page on a machine it does not sit at."""
    assert _run(monkeypatch, tmp_path, "--transport", "streamable-http") == []


# -- what the model and the log are told ----------------------------------------


def test_the_instructions_name_the_prompt_over_stdio_alone(tmp_path: Path) -> None:
    stdio = _server(tmp_path).instructions
    http = _server(tmp_path, "streamable-http").instructions

    assert f'"{SETUP_PROMPT_TITLE}"' in stdio
    assert SETUP_PROMPT_TITLE not in http
    assert stdio.startswith(http)


@pytest.mark.parametrize(("transport", "named"), [("stdio", True), ("sse", False)])
def test_the_missing_policy_warning_names_the_prompt_where_it_exists(
    transport: str, named: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """The title is spelled out in the log line, so it is held to the server's."""
    with caplog.at_level("WARNING"):
        logbook.lifecycle.no_policy(Path("tools.json"), transport)

    assert (f'"{SETUP_PROMPT_TITLE}"' in caplog.text) is named
    assert "`benethos-lexware-office-mcp setup`" in caplog.text
