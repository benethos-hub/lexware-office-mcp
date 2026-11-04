"""The server over stdio, without a key, as a client speaks to it. Not a test.

The suite calls ``MCPServer.call_tool`` in-process. A client sends JSON-RPC
over stdio and is answered by the SDK, which turns a return value into a
result and an exception into an error result. The suite does not see that
conversion, and the 2.0.0 to 2.1.1 bump changed it while every test stayed
green, see SPECS.md section 14.3. This script spawns the server the way a
client does, under the interpreter it runs with, against a scratch policy
file and an empty settings file, and asserts what a client has to receive:

- the tool list holds the status and the tools the policy file enables, and
  every tool carries its annotations
- a tool the policy file disables is refused with the sentence this server
  writes, not with the SDK's bare "Error executing tool"
- an argument the tool does not take is refused with this server's sentence
- an argument of the wrong type is refused as an error result, not a crash
- the status answers with the version installed in this interpreter

Exits with 0 when every answer is as expected and with 1 otherwise. No key
and no network: nothing here reaches Lexware. ``.github/workflows/freshness.yml``
runs it on the newest versions the ranges allow and on the published
package, ``uv run python tests/stdio_check.py`` runs it on the checkout.
"""

from __future__ import annotations

import importlib.metadata
import json
import sys
import tempfile
import traceback
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

DISTRIBUTION = "benethos-lexware-office-mcp"
MODULE = "benethos_lexware_office_mcp"
ENABLED = ("get_profile", "get_contact")
DISABLED = "search_contacts"
# The whole conversation. A server that hangs on startup is a finding too.
TIMEOUT = 120.0

failures: list[str] = []


def check(condition: bool, what: str) -> None:
    if not condition:
        failures.append(what)


def parameters(scratch: Path) -> StdioServerParameters:
    """The server as a client launches it, kept away from this machine.

    An empty settings file replaces the search for one, so no real key is
    found. The policy file names exactly the tools under test. The package
    comes from the interpreter's own environment, not from a checkout.
    """
    settings = scratch / "empty.env"
    settings.write_text("", encoding="utf-8")
    policy = scratch / "tools.json"
    flags = dict.fromkeys(ENABLED, True) | {DISABLED: False}
    policy.write_text(json.dumps(flags), encoding="utf-8")
    env = get_default_environment() | {
        "PYTHONIOENCODING": "utf-8",
        "LXO_MCP_LOG_LEVEL": "ERROR",
        "LXO_MCP_TOOL_POLICY": str(policy),
    }
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", MODULE, "--env-file", str(settings)],
        cwd=str(scratch),
        env=env,
    )


def leaves(exc: BaseException) -> list[BaseException]:
    """The exceptions inside a group, since the client runs a task group."""
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for sub in exc.exceptions for leaf in leaves(sub)]
    return [exc]


def text_of(result: object) -> str:
    content = getattr(result, "content", None) or []
    first = content[0] if content else None
    return getattr(first, "text", "") or ""


async def converse(scratch: Path) -> None:
    version = importlib.metadata.version(DISTRIBUTION)
    async with stdio_client(parameters(scratch)) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            check(
                init.server_info.name == DISTRIBUTION,
                f"the server introduced itself as {init.server_info.name!r}",
            )

            listed = (await session.list_tools()).tools
            names = sorted(tool.name for tool in listed)
            check(
                names == sorted(("server_status", *ENABLED)),
                f"the tool list holds {names}",
            )
            without = [
                tool.name
                for tool in listed
                if tool.annotations is None or tool.annotations.read_only_hint is None
            ]
            check(not without, f"tools without annotations: {without}")

            refused = await session.call_tool(DISABLED, {})
            text = text_of(refused)
            check(
                refused.is_error is True
                and text.startswith(f"Error executing tool {DISABLED}: ")
                and "is not enabled" in text,
                f"a disabled tool answered is_error={refused.is_error} {text!r}",
            )

            unknown = await session.call_tool("get_profile", {"nonsense": 1})
            text = text_of(unknown)
            check(
                unknown.is_error is True and "takes no argument nonsense" in text,
                f"an unknown argument answered is_error={unknown.is_error} {text!r}",
            )

            wrong = await session.call_tool("get_contact", {"contact_id": ["x"]})
            text = text_of(wrong)
            check(
                wrong.is_error is True and "contact_id" in text,
                f"a wrong type answered is_error={wrong.is_error} {text!r}",
            )

            status = await session.call_tool("server_status", {})
            text = text_of(status)
            check(
                status.is_error is not True
                and text.startswith(f"name: {DISTRIBUTION}\nversion: {version}\n"),
                f"the status answered is_error={status.is_error} {text[:80]!r}",
            )
    print(
        f"stdio check: {DISTRIBUTION} {version}, "
        f"mcp {importlib.metadata.version('mcp')}, "
        f"{len(listed)} tools listed, {len(failures)} failures"
    )


async def main() -> int:
    with tempfile.TemporaryDirectory() as folder:
        try:
            with anyio.fail_after(TIMEOUT):
                await converse(Path(folder))
        except TimeoutError:
            failures.append(f"no answer within {TIMEOUT:.0f} s")
        except Exception as exc:  # noqa: BLE001 - every failure is a finding
            traceback.print_exception(exc, file=sys.stderr)
            failures.extend(f"{type(leaf).__name__}: {leaf}" for leaf in leaves(exc))
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(anyio.run(main))
