"""Uploading receipts, and attaching one to a voucher that exists.

The facts asserted here were measured against a live account on 2026-08-20,
because the documentation states none of them: the form part is named
``file``, ``type`` is required and ``voucher`` is its only accepted value,
the answer is 202 with a **voucher id** alongside the file id, and the
ceiling is 5 MiB exactly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp.api.client import ClientProvider
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.server import build_server
from helpers import (
    PDF,
    UPLOADED,
    Scripted,
    recorder,
    server_with,
)


async def test_the_file_tools_are_offered_when_the_policy_names_them(
    tmp_path: Path,
) -> None:
    """The group is complete, and nothing else decides which half appears."""
    flags = tmp_path / "tools.json"
    flags.write_text('{"download_file": true, "upload_file": true}', encoding="utf-8")

    names = [
        tool.name
        for tool in await build_server(Settings(tool_policy_path=flags)).list_tools()
    ]

    assert set(names) == {"download_file", "upload_file"}


async def test_an_upload_sends_the_part_and_the_type_the_api_demands(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "receipt.pdf"
    receipt.write_bytes(PDF)
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = server_with(handler, download_path=tmp_path)

    result = await server.call_tool("upload_file", {"path": str(receipt)})

    sent = handler.last.content
    assert b'name="file"' in sent
    assert b'filename="receipt.pdf"' in sent
    assert b'name="type"' in sent
    assert b"voucher" in sent
    assert result.structured_content is not None
    assert result.structured_content["voucherId"] == "PLACEHOLDER-VOUCHER-9"
    await provider.aclose()


def upload_server(
    handler: Scripted, tmp_path: Path, allowed: Path
) -> tuple[Any, ClientProvider]:
    return server_with(handler, download_path=tmp_path, upload_path=allowed)


@pytest.mark.parametrize("tool", ["upload_file", "attach_file_to_voucher"])
async def test_an_upload_outside_the_upload_directory_is_refused(
    tmp_path: Path, tool: str
) -> None:
    """The model names the path, so this setting decides what can leave."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    elsewhere = tmp_path / "private.pdf"
    elsewhere.write_bytes(PDF)
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = upload_server(handler, tmp_path, inbox)

    arguments = {"path": str(elsewhere), "voucher_id": "PLACEHOLDER-VOUCHER-1"}
    if tool == "upload_file":
        del arguments["voucher_id"]
    with pytest.raises(ToolError, match="LXO_MCP_UPLOAD_DIR") as excinfo:
        await server.call_tool(tool, arguments)

    assert str(inbox) not in str(excinfo.value)
    assert handler.requests == []
    await provider.aclose()


async def test_an_upload_inside_the_upload_directory_is_sent(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    (inbox / "2026").mkdir(parents=True)
    receipt = inbox / "2026" / "receipt.pdf"
    receipt.write_bytes(PDF)
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = upload_server(handler, tmp_path, inbox)

    await server.call_tool("upload_file", {"path": str(receipt)})

    assert len(handler.requests) == 1
    await provider.aclose()


async def test_a_path_that_climbs_out_of_the_upload_directory_is_refused(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (tmp_path / "private.pdf").write_bytes(PDF)
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = upload_server(handler, tmp_path, inbox)

    with pytest.raises(ToolError, match="outside"):
        await server.call_tool(
            "upload_file", {"path": str(inbox / ".." / "private.pdf")}
        )

    assert handler.requests == []
    await provider.aclose()


async def test_an_attachment_hangs_on_a_voucher_that_already_exists(
    tmp_path: Path,
) -> None:
    """Measured 2026-08-21: the part is `file` and there is no `type` field,
    which is where this differs from `/v1/files` - and the answer is the file
    id alone, because no voucher was created for it."""
    receipt = tmp_path / "receipt.pdf"
    receipt.write_bytes(PDF)
    handler = recorder(status=202, json_body={"id": "PLACEHOLDER-FILE-9"})
    server, provider = server_with(handler, download_path=tmp_path)

    result = await server.call_tool(
        "attach_file_to_voucher",
        {"voucher_id": "PLACEHOLDER-VOUCHER-1", "path": str(receipt)},
    )

    sent = handler.last.content
    assert handler.last.url.path == "/v1/vouchers/PLACEHOLDER-VOUCHER-1/files"
    assert b'name="file"' in sent
    assert b'filename="receipt.pdf"' in sent
    assert b'name="type"' not in sent, (
        "the collection endpoint wants it, this one does not"
    )
    assert result.structured_content == {"id": "PLACEHOLDER-FILE-9"}
    await provider.aclose()


async def test_an_attachment_is_never_retried(tmp_path: Path) -> None:
    """A repeat would hang a second copy on the same voucher, and there is no
    way to take either off again."""
    receipt = tmp_path / "receipt.pdf"
    receipt.write_bytes(PDF)
    handler = recorder(status=500, json_body={})
    server, provider = server_with(handler, download_path=tmp_path)

    with pytest.raises(ToolError):
        await server.call_tool(
            "attach_file_to_voucher",
            {"voucher_id": "PLACEHOLDER-VOUCHER-1", "path": str(receipt)},
        )

    assert len(handler.requests) == 1
    await provider.aclose()


async def test_an_attachment_refuses_the_same_files_an_upload_does(
    tmp_path: Path,
) -> None:
    """Both go through the same check, so neither spends a request on a file
    the API would reject."""
    wrong = tmp_path / "notes.txt"
    wrong.write_text("hello", encoding="utf-8")
    handler = recorder(status=202, json_body={"id": "PLACEHOLDER-FILE-9"})
    server, provider = server_with(handler, download_path=tmp_path)

    with pytest.raises(ToolError):
        await server.call_tool(
            "attach_file_to_voucher",
            {"voucher_id": "PLACEHOLDER-VOUCHER-1", "path": str(wrong)},
        )

    assert handler.requests == []
    await provider.aclose()


async def test_the_two_upload_tools_say_which_is_which() -> None:
    """The difference is one voucher too many, and it cannot be undone, so it
    belongs in the description rather than in a document nobody reads."""
    server = build_server(Settings())
    tools = {tool.name: tool for tool in await server.list_tools()}

    attach = tools["attach_file_to_voucher"].description or ""
    upload = tools["upload_file"].description or ""

    assert "upload_file" in attach, "it names the neighbour it is not"
    assert "creates a bookkeeping voucher" in upload
    assert len(attach) < 700, "the description budget, see CLAUDE.md"


async def test_an_upload_is_never_retried(tmp_path: Path) -> None:
    """A repeated upload is a second voucher for the same receipt."""
    receipt = tmp_path / "receipt.pdf"
    receipt.write_bytes(PDF)
    handler = recorder(status=500, json_body={})
    server, provider = server_with(handler, download_path=tmp_path)

    with pytest.raises(ToolError):
        await server.call_tool("upload_file", {"path": str(receipt)})

    assert len(handler.requests) == 1
    await provider.aclose()


async def test_a_file_that_is_too_large_is_refused_before_the_request(
    tmp_path: Path,
) -> None:
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"x" * (5 * 1024 * 1024 + 1))
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = server_with(handler, download_path=tmp_path)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("upload_file", {"path": str(big)})

    assert "5 MiB" in str(excinfo.value)
    assert handler.requests == [], "the oversized file went out anyway"
    await provider.aclose()


async def test_exactly_five_mebibytes_is_still_offered(tmp_path: Path) -> None:
    """The measured ceiling is inclusive, so the guard must not be off by one."""
    edge = tmp_path / "edge.pdf"
    edge.write_bytes(b"x" * (5 * 1024 * 1024))
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = server_with(handler, download_path=tmp_path)

    await server.call_tool("upload_file", {"path": str(edge)})

    assert len(handler.requests) == 1
    await provider.aclose()


async def test_a_type_the_api_rejects_is_refused_here(tmp_path: Path) -> None:
    note = tmp_path / "note.txt"
    note.write_text("not a receipt", encoding="utf-8")
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = server_with(handler, download_path=tmp_path)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("upload_file", {"path": str(note)})

    assert ".pdf" in str(excinfo.value)
    assert handler.requests == []
    await provider.aclose()


async def test_a_missing_file_says_so_plainly(tmp_path: Path) -> None:
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = server_with(handler, download_path=tmp_path)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("upload_file", {"path": str(tmp_path / "nope.pdf")})

    assert "No file at" in str(excinfo.value)
    await provider.aclose()


async def test_a_directory_is_not_a_file(tmp_path: Path) -> None:
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = server_with(handler, download_path=tmp_path)

    with pytest.raises(ToolError):
        await server.call_tool("upload_file", {"path": str(tmp_path)})

    assert handler.requests == []
    await provider.aclose()


async def test_an_xrechnung_may_be_uploaded(tmp_path: Path) -> None:
    """Verified 2026-08-20: .xml is accepted and parsed as an XRechnung."""
    invoice = tmp_path / "e-rechnung.xml"
    invoice.write_bytes(b"<Invoice/>")
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = server_with(handler, download_path=tmp_path)

    await server.call_tool("upload_file", {"path": str(invoice)})

    assert b'name="file"' in handler.last.content
    assert b"application/xml" in handler.last.content
    await provider.aclose()


async def test_a_gif_is_refused_because_the_api_refuses_it(tmp_path: Path) -> None:
    """Measured, not assumed: `inacceptable_file_extension`."""
    image = tmp_path / "scan.gif"
    image.write_bytes(b"GIF89a")
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = server_with(handler, download_path=tmp_path)

    with pytest.raises(ToolError):
        await server.call_tool("upload_file", {"path": str(image)})

    assert handler.requests == []
    await provider.aclose()


async def test_a_file_that_cannot_be_read_for_upload_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = tmp_path / "receipt.pdf"
    receipt.write_bytes(PDF)
    handler = recorder(status=202, json_body=UPLOADED)
    server, provider = server_with(handler, download_path=tmp_path)

    def locked(_self: Path) -> bytes:
        raise PermissionError(13, "Permission denied", str(receipt))

    monkeypatch.setattr(Path, "read_bytes", locked)

    with pytest.raises(ToolError, match="Could not read the file to upload"):
        await server.call_tool("upload_file", {"path": str(receipt)})

    assert handler.requests == []
    await provider.aclose()
