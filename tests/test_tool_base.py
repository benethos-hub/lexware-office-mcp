"""The helpers every tool module shares."""

from __future__ import annotations

import json

import pytest
from mcp.types import TextContent

from benethos_lexware_office_mcp.errors import ConflictError
from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.settings import Settings
from benethos_lexware_office_mcp.tools._base import require_version


async def test_a_tool_answering_with_a_record_publishes_no_schema_for_it() -> None:
    """The SDK's schema for `dict[str, Any]` says nothing, so it is not sent.

    What a call answers with stays as it was: the record as the structured
    half, and the same JSON as text for a client that reads content alone.
    Only the file tools declare an output schema, see `test_files.py`.
    """
    server = build_server(Settings())
    tools = {tool.name: tool for tool in await server.list_tools()}

    with_schema = {name for name, tool in tools.items() if tool.output_schema}
    assert with_schema == {"download_file", "download_document", "read_download"}

    result = await server.call_tool(
        "get_deeplink", {"target": "invoice", "target_id": "PLACEHOLDER-ID"}
    )

    assert result.structured_content == {
        "url": "https://app.lexware.de/permalink/invoices/view/PLACEHOLDER-ID"
    }
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text) == result.structured_content
    assert "\n  " in result.content[0].text, "indented, as the SDK writes it"


def test_a_matching_version_passes_silently() -> None:
    require_version({"version": 3}, 3, noun="contact", reader="get_contact")


def test_a_stale_version_names_the_record_and_the_tool_that_reads_it() -> None:
    """The advice has to be actionable: which record, and how to re-read it."""
    with pytest.raises(ConflictError) as excinfo:
        require_version({"version": 4}, 3, noun="voucher", reader="get_voucher")

    text = str(excinfo.value)
    assert "This voucher is at version 4" in text
    assert "written against version 3" in text
    assert "get_voucher" in text


def test_a_record_without_a_version_is_a_conflict_too() -> None:
    """None is not the version the caller quoted, so nothing is sent."""
    with pytest.raises(ConflictError):
        require_version({}, 0, noun="article", reader="get_article")
