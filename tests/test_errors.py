"""Error hierarchy, and the guarantee that a secret never leaves in a message."""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError as AnticipatedFailure

from benethos_lexware_office_mcp import errors
from benethos_lexware_office_mcp.errors import (
    NotFoundError,
    ToolError,
    UpstreamError,
    redact,
    register_secret,
)


@pytest.fixture(autouse=True)
def _clean_secrets() -> None:
    """Keep the module-level secret set from leaking between tests."""
    errors._SECRETS.clear()


def test_every_error_is_a_tool_error() -> None:
    for name in errors.__all__:
        attr = getattr(errors, name)
        if isinstance(attr, type) and issubclass(attr, Exception):
            assert issubclass(attr, ToolError)


def test_every_error_is_the_kind_the_sdk_hands_to_the_model() -> None:
    """The one thing that decides whether these sentences are ever read.

    The SDK sorts a failing tool call by the type of what was raised. An
    anticipated failure - its own `ToolError` - reaches the model with the
    message written here. Anything else is a crash: the text stays on the
    server and the model is told only which tool failed. So a hierarchy that
    derived from plain `Exception` would still compose careful, actionable
    wording and deliver none of it, while every mock in this suite went on
    passing.

    Measured against mcp 2.1.1 over real stdio before this test was written:
    without the inheritance the client received `Error executing tool
    get_profile`, with it the whole sentence. See SPECS.md section 12.1.
    """
    for name in errors.__all__:
        attr = getattr(errors, name)
        if isinstance(attr, type) and issubclass(attr, Exception):
            assert issubclass(attr, AnticipatedFailure), (
                f"{name} would reach the model as a crash, message withheld"
            )


def test_registered_secret_is_stripped_from_a_message() -> None:
    register_secret("super-secret-api-key")
    error = ToolError("request failed with key super-secret-api-key")
    assert "super-secret-api-key" not in error.message
    assert "<redacted>" in error.message


def test_short_values_are_not_registered() -> None:
    """Redacting a two-character string would mangle unrelated text."""
    register_secret("ab")
    assert redact("a table of abbreviations") == "a table of abbreviations"


def test_empty_secret_is_ignored() -> None:
    register_secret(None)
    register_secret("")
    assert errors._SECRETS == set()


def test_not_found_names_the_resource_and_id() -> None:
    error = NotFoundError("invoice", "abc-123")
    assert "invoice" in error.message
    assert "abc-123" in error.message


def test_unknown_outcome_tells_the_caller_to_check() -> None:
    """A failed write must never look like a clean failure."""
    error = UpstreamError("Gateway timeout.", outcome_unknown=True)
    assert error.outcome_unknown is True
    assert "outcome is unknown" in error.message
    assert "before trying again" in error.message


def test_known_outcome_stays_short() -> None:
    error = UpstreamError("Gateway timeout.")
    assert error.outcome_unknown is False
    assert "outcome is unknown" not in error.message
