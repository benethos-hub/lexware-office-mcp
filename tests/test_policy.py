"""Permission tiers: the ordering, the registration gate, the call-time gate."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from benethos_lexware_office_mcp import policy
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.errors import PermissionDeniedError
from benethos_lexware_office_mcp.policy import (
    active_mode,
    allows,
    required_tier,
    requires,
    set_active_mode,
    should_register,
)


@pytest.fixture(autouse=True)
def _restore_mode() -> Iterator[None]:
    previous = active_mode()
    yield
    set_active_mode(previous)


def test_default_tier_is_the_safest_one() -> None:
    """A server that forgets to configure itself must only be able to read.

    Asserted against the declared defaults rather than against ``_ACTIVE``,
    which is process-wide state that any earlier import or test can have
    moved. Reading it here would make this gate depend on what ran before it,
    and on whichever tier the developer happens to have in their own
    ``config/.env``.
    """
    assert policy.DEFAULT_MODE == "read"
    assert Settings().mode == "read"


@pytest.mark.parametrize(
    ("active", "needed", "expected"),
    [
        ("read", "read", True),
        ("read", "write", False),
        ("read", "full", False),
        ("write", "read", True),
        ("write", "write", True),
        ("write", "full", False),
        ("full", "read", True),
        ("full", "write", True),
        ("full", "full", True),
    ],
)
def test_tier_ordering(active: str, needed: str, expected: bool) -> None:
    assert allows(active, needed) is expected  # type: ignore[arg-type]


def test_registration_gate_hides_tools_above_the_tier() -> None:
    set_active_mode("read")
    assert should_register("read") is True
    assert should_register("write") is False
    assert should_register("full") is False


def test_call_gate_blocks_even_when_registration_was_bypassed() -> None:
    """A stale tool list on the client must not get a call through."""

    @requires("write")
    def create_something() -> str:
        return "created"

    set_active_mode("write")
    assert create_something() == "created"

    set_active_mode("read")
    with pytest.raises(PermissionDeniedError) as excinfo:
        create_something()
    assert "LXO_MCP_MODE=write" in str(excinfo.value)


async def test_call_gate_works_on_async_tools() -> None:
    @requires("full")
    async def delete_something() -> str:
        return "deleted"

    set_active_mode("full")
    assert await delete_something() == "deleted"

    set_active_mode("write")
    with pytest.raises(PermissionDeniedError):
        await delete_something()


def test_decorator_records_the_tier_in_the_registry() -> None:
    @requires("full")
    def finalize_something() -> None:
        return None

    assert required_tier("finalize_something") == "full"
    assert finalize_something.required_tier == "full"  # type: ignore[attr-defined]


def test_unknown_tier_is_rejected_at_definition_time() -> None:
    with pytest.raises(ValueError):
        requires("superuser")  # type: ignore[arg-type]


def test_unknown_mode_cannot_be_activated() -> None:
    with pytest.raises(ValueError):
        set_active_mode("superuser")  # type: ignore[arg-type]


def test_unregistered_tool_has_no_tier() -> None:
    assert required_tier("no_such_tool") is None
