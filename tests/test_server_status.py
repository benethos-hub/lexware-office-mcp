"""``server_status``: the one tool the policy file does not decide.

Its answer is read by a model and by whoever asks in a chat, so the order and
the spelling of every line are part of what is tested, not only the values.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

from benethos_lexware_office_mcp import __version__
from benethos_lexware_office_mcp.api import client as client_module
from benethos_lexware_office_mcp.api.client import Health
from benethos_lexware_office_mcp.api.ratelimit import TokenBucket
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools, preset
from benethos_lexware_office_mcp.server import PolicyServer, build_server
from benethos_lexware_office_mcp.settings import Settings
from benethos_lexware_office_mcp.tools import status
from helpers import API_KEY, Scripted, fast_provider, server_obeying

CORE = ["name", "version", "transport", "python", "mcp", "uptime_seconds"]


def text_of(result: CallToolResult) -> str:
    assert result.is_error is not True
    assert result.structured_content is None
    [block] = result.content
    assert isinstance(block, TextContent)
    return block.text


def fields(text: str) -> list[tuple[str, str]]:
    """The answer's lines as pairs, a block's key with an empty value."""
    pairs = []
    for line in text.splitlines():
        key, _, value = line.partition(":")
        pairs.append((key, value.strip()))
    return pairs


def refusing(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no request was expected, got {request.url}")


# -- the core -------------------------------------------------------------


async def test_the_core_names_its_fields_in_order_without_a_request() -> None:
    provider = fast_provider(refusing)
    server = build_server(Settings(api_key=API_KEY), provider)

    answer = dict(fields(text_of(await server.call_tool("server_status", {}))))

    assert list(answer) == CORE
    assert answer["name"] == "benethos-lexware-office-mcp"
    assert answer["version"] == __version__
    assert answer["transport"] == "stdio"
    assert answer["python"] == ".".join(str(n) for n in sys.version_info[:3])
    assert answer["mcp"].count(".") >= 1
    assert answer["uptime_seconds"].isdigit()


async def test_the_transport_is_the_one_this_process_runs() -> None:
    server = build_server(Settings(transport="streamable-http"))

    answer = dict(fields(text_of(await server.call_tool("server_status", {}))))

    assert answer["transport"] == "streamable-http"


async def test_the_uptime_counts_from_when_the_server_was_built() -> None:
    now = [100.0]
    server = MCPServer(name="benethos-lexware-office-mcp")
    status.register(
        server,
        Settings(),
        fast_provider(refusing),
        clock=lambda: now[0],
    )
    now[0] = 518.9

    answer = dict(fields(text_of(await server.call_tool("server_status", {}))))

    assert answer["uptime_seconds"] == "418"


async def test_it_writes_no_line_at_info(lines: pytest.LogCaptureFixture) -> None:
    """A status question is not an activity, so the call log stays quiet."""
    server = build_server(Settings())

    await server.call_tool("server_status", {})

    assert [r for r in lines.records if r.levelno >= logging.INFO] == []


# -- outside the policy ---------------------------------------------------


async def test_it_is_offered_and_answers_without_a_policy_file(tmp_path: Path) -> None:
    server = build_server(Settings(tool_policy_path=tmp_path / "absent.json"))

    assert [t.name for t in await server.list_tools()] == ["server_status"]
    assert text_of(await server.call_tool("server_status", {}))


async def test_a_file_that_switches_it_off_is_not_obeyed(tmp_path: Path) -> None:
    server = server_obeying(tmp_path, {"server_status": False})

    assert [t.name for t in await server.list_tools()] == ["server_status"]
    assert text_of(await server.call_tool("server_status", {}))


async def test_a_policy_that_fails_to_answer_is_not_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = server_obeying(tmp_path, {})

    def broken(self: ToolPolicy, name: str) -> bool:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(ToolPolicy, "enabled", broken)

    assert text_of(await server.call_tool("server_status", {}))


def test_it_is_no_tool_a_policy_or_a_preset_can_name() -> None:
    """Not in the registry, so neither the interface nor `--tools` shows it."""
    assert status.NAME not in known_tools()
    assert status.NAME not in preset("irreversible")


async def test_it_says_it_reads_and_changes_nothing() -> None:
    server = build_server(Settings())
    tool = next(t for t in await server.list_tools() if t.name == "server_status")

    assert tool.title == "Server status"
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.output_schema is None


# -- the form -------------------------------------------------------------


def test_a_block_is_indented_two_spaces_below_its_key() -> None:
    block: status.Block = [("a", "1"), ("b", [("c", "2"), ("d", [("e", "3")])])]

    assert status.render(block) == ["a: 1", "b:", "  c: 2", "  d:", "    e: 3"]


# -- details --------------------------------------------------------------

PROFILE = {"organizationId": "PLACEHOLDER-ORG-ID", "companyName": "Example GmbH"}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def checked(
    *answers: Any, clock: Clock | None = None, **settings: Any
) -> tuple[PolicyServer, Scripted]:
    """A server whose status check meets ``answers``, against ``clock``."""
    handler = Scripted(*answers)
    provider = fast_provider(handler, **settings)
    provider.health = Health(provider, clock=clock or Clock())
    return build_server(Settings(api_key=API_KEY, **settings), provider), handler


async def details_of(server: PolicyServer) -> dict[str, str]:
    """The details part as ``block.field`` -> value."""
    text = text_of(await server.call_tool("server_status", {"details": True}))
    head, _, rest = text.partition("\ndetails:\n")
    assert [key for key, _ in fields(head)] == CORE
    found: dict[str, str] = {}
    block = ""
    for line in rest.splitlines():
        if line.startswith("    "):
            key, _, value = line.strip().partition(": ")
            found[f"{block}.{key}"] = value
        else:
            assert line.startswith("  ") and line.endswith(":"), line
            block = line.strip().removesuffix(":")
    return found


async def test_details_false_sends_nothing() -> None:
    server, handler = checked((200, PROFILE))

    await server.call_tool("server_status", {"details": False})

    assert handler.calls == 0


async def test_details_name_every_field_in_order() -> None:
    server, handler = checked((200, PROFILE))

    assert list(await details_of(server)) == [
        "upstream.reachable",
        "upstream.checked_seconds_ago",
        "upstream.token_set",
        "upstream.token_valid",
        "policy.file_loaded",
    ]
    assert handler.calls == 1
    assert handler.methods == ["GET"]
    assert handler.path == "/v1/profile"


async def test_an_account_that_answers_takes_the_key() -> None:
    server, _ = checked((200, PROFILE))

    found = await details_of(server)

    assert found["upstream.reachable"] == "yes"
    assert found["upstream.checked_seconds_ago"] == "0"
    assert found["upstream.token_set"] == "yes"
    assert found["upstream.token_valid"] == "yes"


async def test_a_second_ask_within_sixty_seconds_sends_nothing() -> None:
    clock = Clock()
    server, handler = checked((200, PROFILE), clock=clock)
    await details_of(server)
    clock.now += 59.6

    found = await details_of(server)

    assert handler.calls == 1
    assert found["upstream.checked_seconds_ago"] == "59"
    clock.now += 0.4
    assert (await details_of(server))["upstream.checked_seconds_ago"] == "0"
    assert handler.calls == 2


async def test_a_refused_key_is_not_sent_again() -> None:
    clock = Clock()
    server, handler = checked((401, {"message": "Unauthorized"}), clock=clock)
    found = await details_of(server)
    clock.now += 600

    again = await details_of(server)

    assert found["upstream.reachable"] == "yes"
    assert found["upstream.token_valid"] == "no"
    assert again["upstream.token_valid"] == "no"
    assert again["upstream.checked_seconds_ago"] == "600"
    assert handler.calls == 1


async def test_a_key_saved_after_a_refusal_is_checked_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over stdio a key saved in the interface reaches this process unrestarted."""
    server, handler = checked((401, {}), (200, PROFILE))
    await details_of(server)
    monkeypatch.setattr(Settings, "require_api_key", lambda self: "another-key-0123")

    found = await details_of(server)

    assert handler.calls == 2
    assert found["upstream.token_valid"] == "yes"


async def test_a_key_the_api_knows_but_keeps_from_the_profile_is_taken() -> None:
    server, _ = checked((403, {}))

    found = await details_of(server)

    assert found["upstream.reachable"] == "yes"
    assert found["upstream.token_valid"] == "yes"


@pytest.mark.parametrize(
    "answer",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), (503, {})],
    ids=["no connection", "timeout", "server error"],
)
async def test_no_answer_is_unreachable_once_and_not_retried(answer: Any) -> None:
    server, handler = checked(answer)

    found = await details_of(server)

    assert handler.calls == 1
    assert found["upstream.reachable"] == "no"
    assert found["upstream.token_valid"] == "unknown"
    assert found["upstream.checked_seconds_ago"] == "0"


async def test_a_rate_limited_answer_is_an_answer() -> None:
    server, handler = checked((429, {}), (200, PROFILE))

    found = await details_of(server)

    assert handler.calls == 1
    assert found["upstream.reachable"] == "yes"
    assert found["upstream.token_valid"] == "unknown"


async def test_without_a_key_nothing_is_sent(tmp_path: Path) -> None:
    handler = Scripted((200, PROFILE))
    settings = Settings(tool_policy_path=tmp_path / "absent.json")
    server = build_server(settings, fast_provider(handler, settings=settings))

    found = await details_of(server)

    assert handler.calls == 0
    assert found["upstream.reachable"] == "unknown"
    assert found["upstream.checked_seconds_ago"] == "never"
    assert found["upstream.token_set"] == "no"
    assert found["upstream.token_valid"] == "unknown"


async def test_behind_the_breaker_nothing_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check takes from the one bucket, and waits a moment for it at most."""
    monkeypatch.setattr(client_module, "CHECK_WAIT", 0.05)
    handler = Scripted((200, PROFILE))
    bucket = TokenBucket(2.0, 2)
    bucket.drain(30.0)
    settings = Settings(api_key=API_KEY)
    provider = fast_provider(handler, settings=settings, bucket=bucket)
    server = build_server(settings, provider)

    found = await details_of(server)

    assert handler.calls == 0
    assert found["upstream.reachable"] == "unknown"
    assert found["upstream.checked_seconds_ago"] == "never"
    assert found["upstream.token_set"] == "yes"


async def test_a_token_due_in_a_moment_is_waited_for() -> None:
    """Measured 2026-10-29: right after two calls, a check that never waited
    sent nothing and answered `never`, less than a second before a token was due."""
    handler = Scripted((200, PROFILE))
    bucket = TokenBucket(20.0, 1)
    await bucket.acquire()
    settings = Settings(api_key=API_KEY)
    server = build_server(
        settings, fast_provider(handler, settings=settings, bucket=bucket)
    )

    found = await details_of(server)

    assert handler.calls == 1
    assert found["upstream.reachable"] == "yes"


async def test_the_check_spends_a_token_of_the_one_bucket() -> None:
    handler = Scripted((200, PROFILE))
    bucket = TokenBucket(2.0, 2)
    settings = Settings(api_key=API_KEY)
    server = build_server(
        settings, fast_provider(handler, settings=settings, bucket=bucket)
    )

    await details_of(server)

    assert bucket.tokens < 2


async def test_it_does_not_fail_when_the_transport_raises() -> None:
    server, _ = checked(RuntimeError("the transport broke"))

    found = await details_of(server)

    assert found["upstream.reachable"] == "unknown"
    assert found["upstream.token_valid"] == "unknown"
    assert found["upstream.checked_seconds_ago"] == "0"


async def test_no_secret_and_nothing_of_the_account_appears() -> None:
    server, _ = checked((200, PROFILE))

    text = text_of(await server.call_tool("server_status", {"details": True}))

    pieces = {API_KEY[i : i + 4] for i in range(len(API_KEY) - 3)}
    assert not [piece for piece in pieces if piece in text]
    assert "Example GmbH" not in text
    assert "PLACEHOLDER" not in text


async def test_the_check_writes_no_line_at_info(
    lines: pytest.LogCaptureFixture,
) -> None:
    server, _ = checked(httpx.ConnectError("refused"))

    await details_of(server)

    assert [r for r in lines.records if r.levelno >= logging.INFO] == []


@pytest.mark.parametrize(
    ("content", "loaded"),
    [(None, "no"), ("{not json", "no"), ('["get_profile"]', "no"), ("{}", "yes")],
    ids=["missing", "unreadable", "not an object", "empty"],
)
async def test_the_policy_says_whether_its_file_was_read(
    tmp_path: Path, content: str | None, loaded: str
) -> None:
    policy = tmp_path / "tools.json"
    if content is not None:
        policy.write_text(content, encoding="utf-8")
    server, _ = checked((200, PROFILE), tool_policy_path=policy)

    assert (await details_of(server))["policy.file_loaded"] == loaded
