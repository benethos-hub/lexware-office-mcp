"""Classification is metadata. The file is the gate.

The two used to be one thing: a tier both described a tool and decided whether
it could be called. Splitting them is what these tests are about — that
`classify` still records what a tool is, that nothing consults it when a call
arrives, and that the policy alone answers "may this run".
"""

from __future__ import annotations

import pytest

from benethos_lexware_office_mcp.errors import PermissionDeniedError
from benethos_lexware_office_mcp.policy import (
    ToolMeta,
    ToolPolicy,
    classify,
    grouped_tools,
    guarded,
    known_tools,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Everything(ToolPolicy):
    """A policy that says yes, for testing what the classification does not do."""

    def enabled(self, name: str) -> bool:
        return True


class Nothing(ToolPolicy):
    def enabled(self, name: str) -> bool:
        return False


# -- what the classification records --------------------------------------


def test_the_decorator_records_what_a_tool_is() -> None:
    @classify("write", "articles", "delete")
    def sample_deleting_tool() -> str:
        return "ran"

    meta = known_tools()["sample_deleting_tool"]

    assert meta == ToolMeta(access="write", domain="articles", effect="delete")
    assert meta.irreversible


def test_a_reading_tool_is_not_irreversible() -> None:
    assert not ToolMeta(access="read", domain="contacts").irreversible


def test_an_update_is_reversible_a_deletion_is_not() -> None:
    """Only the effects that cannot be taken back are marked."""
    assert not ToolMeta("write", "contacts", "update").irreversible
    assert ToolMeta("write", "contacts", "delete").irreversible


def test_every_shipped_tool_is_classified() -> None:
    """A tool without metadata cannot be grouped or selected by a script."""
    for name, meta in known_tools().items():
        assert meta.access in ("read", "write"), name
        assert meta.domain, name


def test_the_shipped_tools_are_grouped_by_domain() -> None:
    groups = grouped_tools()

    assert "get_profile" in groups["diagnostics"]
    assert "create_voucher" in groups["vouchers"]
    assert "upload_file" in groups["files"]
    assert groups["contacts"] == sorted(groups["contacts"])


# -- what it deliberately does not do -------------------------------------


async def test_a_write_tool_runs_when_the_file_allows_it() -> None:
    """The classification is not a permission. Only the file is.

    A `write` tool used to be refused by the tier whatever any file said.
    Now the file is the whole answer, and saying `write` about a tool tells a
    script how to group it and nothing more.
    """

    @classify("write", "contacts", "create")
    async def sample_creating_tool() -> str:
        return "ran"

    assert await guarded(sample_creating_tool, Everything())() == "ran"


async def test_a_read_tool_is_refused_when_the_file_says_so() -> None:
    @classify("read", "contacts")
    async def sample_reading_tool() -> str:
        return "ran"

    with pytest.raises(PermissionDeniedError) as excinfo:
        await guarded(sample_reading_tool, Nothing())()

    assert "not enabled" in str(excinfo.value)


def test_the_gate_works_on_a_plain_function_too() -> None:
    """Not every tool has to be a coroutine, so both wrappers are checked."""

    @classify("read", "diagnostics")
    def sample_sync_tool() -> str:
        return "ran"

    assert guarded(sample_sync_tool, Everything())() == "ran"

    with pytest.raises(PermissionDeniedError):
        guarded(sample_sync_tool, Nothing())()


@pytest.mark.parametrize("value", ['"false"', '"true"', "1", '"yes"', "null", "[]"])
def test_only_json_true_enables_a_tool(tmp_path, caplog, value: str) -> None:
    """`bool("false")` is true, so a coercing reader would enable what the
    file meant to refuse. Anything but the literal `true` is off, and said."""
    path = tmp_path / "tools.json"
    path.write_text(f'{{"create_voucher": {value}}}', encoding="utf-8")

    assert not ToolPolicy(path).enabled("create_voucher")
    assert "create_voucher" in caplog.text


def test_json_true_and_false_are_read_without_a_warning(tmp_path, caplog) -> None:
    path = tmp_path / "tools.json"
    path.write_text('{"get_profile": true, "create_voucher": false}', encoding="utf-8")

    policy = ToolPolicy(path)

    assert policy.enabled("get_profile")
    assert not policy.enabled("create_voucher")
    assert caplog.text == ""


def test_the_refusal_names_the_tool_but_never_a_path() -> None:
    """This message reaches the client, and from there a model's context.

    Which tool was refused is what the caller can act on. Where the file
    sits on somebody's disk is not, and it carries a user name and a
    directory layout along with it.
    """

    @classify("read", "diagnostics")
    def sample_named_tool() -> str:
        return "ran"

    policy = ToolPolicy(__import__("pathlib").Path("/home/someone/secret/tools.json"))

    with pytest.raises(PermissionDeniedError) as excinfo:
        guarded(sample_named_tool, policy)()

    message = str(excinfo.value)
    assert "sample_named_tool" in message
    assert "someone" not in message
    assert "tools.json" not in message
    assert "/" not in message and "\\" not in message
