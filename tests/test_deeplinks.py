"""Links into the web app, built without an API call.

Every shape here was requested against the live app on 2026-08-21 rather than
taken from the documentation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.settings import Settings
from helpers import (
    API_KEY,
    FILE_ID,
    recorder,
    server_with,
)


async def test_a_deeplink_costs_no_api_call(tmp_path: Path) -> None:
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    result = await server.call_tool(
        "get_deeplink", {"target": "invoice", "target_id": "PLACEHOLDER-DOC-1"}
    )

    assert handler.requests == []
    assert result.structured_content is not None
    assert result.structured_content["url"].endswith(
        "/permalink/invoices/view/PLACEHOLDER-DOC-1"
    )
    await provider.aclose()


async def test_the_edit_action_and_the_configured_base_are_used(
    tmp_path: Path,
) -> None:
    settings = Settings(api_key=API_KEY, app_base_url="https://example.invalid/")
    server = build_server(settings)

    result = await server.call_tool(
        "get_deeplink",
        {"target": "invoice", "target_id": "PLACEHOLDER-DOC-1", "action": "edit"},
    )

    assert result.structured_content is not None
    assert result.structured_content["url"] == (
        "https://example.invalid/permalink/invoices/edit/PLACEHOLDER-DOC-1"
    )


async def test_an_id_cannot_steer_the_link_elsewhere() -> None:
    """The id comes from the model. A slash or a `?` must stay inside it."""
    server = build_server(Settings(api_key=API_KEY))

    result = await server.call_tool(
        "get_deeplink", {"target": "invoice", "target_id": "../../settings?x=1#y"}
    )

    assert result.structured_content is not None
    assert result.structured_content["url"].endswith(
        "/permalink/invoices/view/..%2F..%2Fsettings%3Fx%3D1%23y"
    )


async def test_a_contact_always_opens_on_its_one_page(tmp_path: Path) -> None:
    """Verified 2026-08-21: the app answers `contacts/edit/{id}` with a 404.

    A contact is edited on the page it is viewed on, so asking to edit one
    has to produce the link that works rather than the link that was asked
    for.
    """
    server = build_server(Settings(api_key=API_KEY))

    result = await server.call_tool(
        "get_deeplink",
        {"target": "contact", "target_id": "PLACEHOLDER-CONTACT-1", "action": "edit"},
    )

    assert result.structured_content is not None
    assert result.structured_content["url"].endswith(
        "/permalink/contacts/view/PLACEHOLDER-CONTACT-1"
    )


async def test_a_stored_file_is_not_a_link_target(tmp_path: Path) -> None:
    """Verified 2026-08-21: `permalink/files/{id}` is a 404 in the web app.

    There is no page for a stored file, so offering one as a target would
    only produce links that go nowhere.
    """
    server = build_server(Settings(api_key=API_KEY))

    with pytest.raises(ToolError):
        await server.call_tool("get_deeplink", {"target": "file", "target_id": FILE_ID})
