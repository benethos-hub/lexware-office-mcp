"""Downloads, uploads, deeplinks, and where a file lands on disk.

The upload facts asserted here were measured against a live account on
2026-08-20, because the documentation states none of them: the form part is
named ``file``, ``type`` is required and ``voucher`` is its only accepted
value, the answer is 202 with a **voucher id** alongside the file id, and the
ceiling is 5 MiB exactly.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp import policy, storage
from benethos_lexware_office_mcp.client import ClientProvider
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server

API_KEY = "test-key-0123456789"
FILE_ID = "PLACEHOLDER-FILE-1"
PDF = b"%PDF-1.4\ntrailer<</Root 1 0 R>>\n%%EOF\n"

UPLOADED = {"id": "PLACEHOLDER-FILE-2", "voucherId": "PLACEHOLDER-VOUCHER-9"}


@pytest.fixture(autouse=True)
def _restore_mode() -> Iterator[None]:
    previous = policy.active_mode()
    yield
    policy.set_active_mode(previous)


async def _no_sleep(_seconds: float) -> None:
    return None


class Recorder:
    """Answers with one canned response and remembers the request."""

    def __init__(
        self,
        content: bytes = PDF,
        status: int = 200,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
    ) -> None:
        self._content = content
        self._status = status
        self._headers = headers or {}
        self._json = json_body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._json is not None:
            return httpx.Response(self._status, json=self._json)
        return httpx.Response(
            self._status, content=self._content, headers=self._headers
        )

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def server_for(
    handler: Recorder, tmp_path: Path, mode: str = "read"
) -> tuple[Any, ClientProvider]:
    settings = Settings(api_key=API_KEY, mode=mode, download_path=tmp_path)  # type: ignore[arg-type]
    provider = ClientProvider(
        settings,
        transport=httpx.MockTransport(handler),
        bucket=TokenBucket(1000.0, 100, sleep=_no_sleep),
        sleep=_no_sleep,
    )
    return build_server(settings, provider), provider


# -- storage --------------------------------------------------------------


def response_with(disposition: str) -> httpx.Response:
    return httpx.Response(
        200, content=PDF, headers={"content-disposition": disposition}
    )


def test_the_servers_filename_is_used_when_it_is_ordinary() -> None:
    name = storage.suggested_name(
        response_with("inline; filename=invoice-2026-014.pdf;"), "fallback.pdf"
    )
    assert name == "invoice-2026-014.pdf"


def test_a_filename_that_is_a_path_is_reduced_to_its_last_part() -> None:
    """Content-Disposition is written by the server, so it is untrusted."""
    name = storage.suggested_name(
        response_with('attachment; filename="../../../etc/passwd"'), "fallback.pdf"
    )
    assert name == "passwd"
    assert "/" not in name


def test_a_windows_path_is_stripped_too() -> None:
    """The separator that matters is not always the platform's own."""
    name = storage.suggested_name(
        response_with(
            'attachment; filename="..\\\\..\\\\windows\\\\system32\\\\x.pdf"'
        ),
        "fallback.pdf",
    )
    assert name == "x.pdf"
    assert "\\" not in name


def test_unusual_characters_are_replaced() -> None:
    """A filename that reaches the disk should be boring."""
    name = storage.suggested_name(
        response_with('attachment; filename="Rechnung 2026 (final) & copy.pdf"'),
        "f.pdf",
    )
    assert all(c.isalnum() or c in "._-" for c in name), name
    assert name.endswith(".pdf")


def test_a_useless_filename_falls_back_to_the_callers_own() -> None:
    assert storage.suggested_name(
        response_with('attachment; filename=".."'), "f.pdf"
    ) == ("f.pdf")
    assert storage.suggested_name(httpx.Response(200, content=PDF), "f.pdf") == "f.pdf"


def test_a_download_never_replaces_an_existing_file(tmp_path: Path) -> None:
    """Overwriting last month's invoice with this month's is worse than failing."""
    first = storage.save(b"one", "invoice.pdf", tmp_path)
    second = storage.save(b"two", "invoice.pdf", tmp_path)

    assert first.name == "invoice.pdf"
    assert second.name == "invoice-2.pdf"
    assert first.read_bytes() == b"one"
    assert second.read_bytes() == b"two"


def test_the_download_directory_is_created(tmp_path: Path) -> None:
    target = tmp_path / "not" / "there" / "yet"
    assert storage.directory_for(Settings(download_path=target)) == target
    assert target.is_dir()


# -- downloading ----------------------------------------------------------


async def test_download_file_writes_the_bytes_and_reports_the_path(
    tmp_path: Path,
) -> None:
    handler = Recorder(headers={"content-type": "application/pdf"})
    server, provider = server_for(handler, tmp_path)

    result = await server.call_tool("download_file", {"file_id": FILE_ID})

    payload = result.structured_content
    assert payload is not None
    written = Path(payload["path"])
    assert written.read_bytes() == PDF
    assert payload["mimeType"] == "application/pdf"
    assert payload["size"] == len(PDF)
    await provider.aclose()


async def test_the_bytes_do_not_come_back_in_the_answer(tmp_path: Path) -> None:
    """Base64 in a tool result costs context and nothing can read it."""
    handler = Recorder()
    server, provider = server_for(handler, tmp_path)

    result = await server.call_tool("download_file", {"file_id": FILE_ID})

    blocks = {b.type for b in result.content}
    assert "resource_link" in blocks
    assert not any(getattr(b, "data", None) for b in result.content)
    assert "blob" not in str(result.structured_content)
    await provider.aclose()


async def test_a_download_asks_for_the_format_rather_than_for_json(
    tmp_path: Path,
) -> None:
    """The client defaults to Accept: application/json, which is wrong here."""
    handler = Recorder()
    server, provider = server_for(handler, tmp_path)

    await server.call_tool("download_file", {"file_id": FILE_ID})

    assert handler.last.headers["Accept"] == "application/pdf"
    await provider.aclose()


async def test_xml_is_asked_for_when_it_is_wanted(tmp_path: Path) -> None:
    handler = Recorder()
    server, provider = server_for(handler, tmp_path)

    await server.call_tool("download_file", {"file_id": FILE_ID, "file_format": "xml"})

    assert handler.last.headers["Accept"] == "application/xml"
    await provider.aclose()


async def test_a_document_is_fetched_from_its_own_resource_path(
    tmp_path: Path,
) -> None:
    handler = Recorder()
    server, provider = server_for(handler, tmp_path)

    await server.call_tool(
        "download_document",
        {"document_type": "credit-note", "document_id": "PLACEHOLDER-DOC-1"},
    )

    assert handler.last.url.path == "/v1/credit-notes/PLACEHOLDER-DOC-1/file"
    await provider.aclose()


# -- deeplinks ------------------------------------------------------------


async def test_a_deeplink_costs_no_api_call(tmp_path: Path) -> None:
    handler = Recorder()
    server, provider = server_for(handler, tmp_path)

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
        {"target": "contact", "target_id": "PLACEHOLDER-CONTACT-1", "action": "edit"},
    )

    assert result.structured_content is not None
    assert result.structured_content["url"] == (
        "https://example.invalid/permalink/contacts/edit/PLACEHOLDER-CONTACT-1"
    )


async def test_a_file_link_carries_no_action(tmp_path: Path) -> None:
    """The one target whose permalink has a different shape."""
    server = build_server(Settings(api_key=API_KEY))

    result = await server.call_tool(
        "get_deeplink", {"target": "file", "target_id": FILE_ID, "action": "edit"}
    )

    assert result.structured_content is not None
    assert result.structured_content["url"].endswith(f"/permalink/files/{FILE_ID}")


# -- uploading ------------------------------------------------------------


async def test_upload_is_absent_in_read_mode() -> None:
    names = [tool.name for tool in await build_server(Settings()).list_tools()]
    assert "upload_file" not in names
    assert "download_file" in names


async def test_an_upload_sends_the_part_and_the_type_the_api_demands(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "receipt.pdf"
    receipt.write_bytes(PDF)
    handler = Recorder(status=202, json_body=UPLOADED)
    server, provider = server_for(handler, tmp_path, mode="write")

    result = await server.call_tool("upload_file", {"path": str(receipt)})

    sent = handler.last.content
    assert b'name="file"' in sent
    assert b'filename="receipt.pdf"' in sent
    assert b'name="type"' in sent
    assert b"voucher" in sent
    assert result.structured_content is not None
    assert result.structured_content["voucherId"] == "PLACEHOLDER-VOUCHER-9"
    await provider.aclose()


async def test_an_upload_is_never_retried(tmp_path: Path) -> None:
    """A repeated upload is a second voucher for the same receipt."""
    receipt = tmp_path / "receipt.pdf"
    receipt.write_bytes(PDF)
    handler = Recorder(status=500, json_body={})
    server, provider = server_for(handler, tmp_path, mode="write")

    with pytest.raises(ToolError):
        await server.call_tool("upload_file", {"path": str(receipt)})

    assert len(handler.requests) == 1
    await provider.aclose()


async def test_a_file_that_is_too_large_is_refused_before_the_request(
    tmp_path: Path,
) -> None:
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"x" * (5 * 1024 * 1024 + 1))
    handler = Recorder(status=202, json_body=UPLOADED)
    server, provider = server_for(handler, tmp_path, mode="write")

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("upload_file", {"path": str(big)})

    assert "5 MiB" in str(excinfo.value)
    assert handler.requests == [], "the oversized file went out anyway"
    await provider.aclose()


async def test_exactly_five_mebibytes_is_still_offered(tmp_path: Path) -> None:
    """The measured ceiling is inclusive, so the guard must not be off by one."""
    edge = tmp_path / "edge.pdf"
    edge.write_bytes(b"x" * (5 * 1024 * 1024))
    handler = Recorder(status=202, json_body=UPLOADED)
    server, provider = server_for(handler, tmp_path, mode="write")

    await server.call_tool("upload_file", {"path": str(edge)})

    assert len(handler.requests) == 1
    await provider.aclose()


async def test_a_type_the_api_rejects_is_refused_here(tmp_path: Path) -> None:
    note = tmp_path / "note.txt"
    note.write_text("not a receipt", encoding="utf-8")
    handler = Recorder(status=202, json_body=UPLOADED)
    server, provider = server_for(handler, tmp_path, mode="write")

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("upload_file", {"path": str(note)})

    assert ".pdf" in str(excinfo.value)
    assert handler.requests == []
    await provider.aclose()


async def test_a_missing_file_says_so_plainly(tmp_path: Path) -> None:
    handler = Recorder(status=202, json_body=UPLOADED)
    server, provider = server_for(handler, tmp_path, mode="write")

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("upload_file", {"path": str(tmp_path / "nope.pdf")})

    assert "No file at" in str(excinfo.value)
    await provider.aclose()


async def test_a_directory_is_not_a_file(tmp_path: Path) -> None:
    handler = Recorder(status=202, json_body=UPLOADED)
    server, provider = server_for(handler, tmp_path, mode="write")

    with pytest.raises(ToolError):
        await server.call_tool("upload_file", {"path": str(tmp_path)})

    assert handler.requests == []
    await provider.aclose()


# -- handing the file to the client ---------------------------------------


async def test_the_result_names_the_file_both_ways(tmp_path: Path) -> None:
    """A path serves a client on this machine, a URI serves every other one."""
    handler = Recorder(headers={"content-type": "application/pdf"})
    server, provider = server_for(handler, tmp_path)

    result = await server.call_tool("download_file", {"file_id": FILE_ID})

    payload = result.structured_content
    assert payload is not None
    assert set(payload) == {"path", "uri", "mimeType", "size"}
    assert Path(payload["path"]).name in payload["uri"]
    assert payload["uri"].startswith("lexware://download/")
    await provider.aclose()


async def test_a_resource_link_comes_back_with_the_result(tmp_path: Path) -> None:
    handler = Recorder(headers={"content-type": "application/pdf"})
    server, provider = server_for(handler, tmp_path)

    result = await server.call_tool("download_file", {"file_id": FILE_ID})

    links = [b for b in result.content if b.type == "resource_link"]
    assert len(links) == 1
    assert links[0].mime_type == "application/pdf"
    assert links[0].size == len(PDF)
    await provider.aclose()


async def test_the_downloaded_file_can_be_read_back_as_a_resource(
    tmp_path: Path,
) -> None:
    """The whole point: the client asks the server for the bytes, by URI."""
    handler = Recorder(headers={"content-type": "application/pdf"})
    server, provider = server_for(handler, tmp_path)

    result = await server.call_tool("download_file", {"file_id": FILE_ID})
    uri = (result.structured_content or {})["uri"]

    contents = list(await server.read_resource(uri))
    assert len(contents) == 1
    assert contents[0].content == PDF
    assert contents[0].mime_type == "application/pdf"
    await provider.aclose()


async def test_nothing_is_published_before_a_download(tmp_path: Path) -> None:
    """Only what this server actually fetched is reachable."""
    handler = Recorder()
    server, provider = server_for(handler, tmp_path)

    assert await server.list_resources() == []

    await server.call_tool("download_file", {"file_id": FILE_ID})

    listed = await server.list_resources()
    assert [r.name for r in listed] == [f"{FILE_ID}.pdf"]
    await provider.aclose()


async def test_two_downloads_are_two_resources(tmp_path: Path) -> None:
    """The second file is saved beside the first, so it needs its own URI."""
    handler = Recorder(headers={"content-type": "application/pdf"})
    server, provider = server_for(handler, tmp_path)

    first = await server.call_tool("download_file", {"file_id": FILE_ID})
    second = await server.call_tool("download_file", {"file_id": FILE_ID})

    uris = {
        (first.structured_content or {})["uri"],
        (second.structured_content or {})["uri"],
    }
    assert len(uris) == 2
    assert {str(r.uri) for r in await server.list_resources()} == uris
    await provider.aclose()


async def test_a_content_type_with_parameters_is_reduced_to_the_type(
    tmp_path: Path,
) -> None:
    handler = Recorder(headers={"content-type": "application/pdf;charset=UTF-8"})
    server, provider = server_for(handler, tmp_path)

    result = await server.call_tool("download_file", {"file_id": FILE_ID})

    assert (result.structured_content or {})["mimeType"] == "application/pdf"
    await provider.aclose()


async def test_a_downloaded_xml_is_published_as_xml(tmp_path: Path) -> None:
    """An XRechnung is not a PDF, and a client deciding what to do needs to know."""
    handler = Recorder(
        content=b"<Invoice/>", headers={"content-type": "application/xml"}
    )
    server, provider = server_for(handler, tmp_path)

    result = await server.call_tool(
        "download_file", {"file_id": FILE_ID, "file_format": "xml"}
    )

    listed = await server.list_resources()
    assert listed[0].mime_type == "application/xml"
    assert (result.structured_content or {})["mimeType"] == "application/xml"
    await provider.aclose()


async def test_the_download_tools_declare_what_they_return(tmp_path: Path) -> None:
    """A generic object schema tells the model nothing about path versus uri."""
    server = build_server(Settings(api_key=API_KEY))
    tool = next(t for t in await server.list_tools() if t.name == "download_file")

    assert tool.output_schema is not None
    assert set(tool.output_schema["properties"]) == {"path", "uri", "mimeType", "size"}


# -- what may be uploaded, measured against the API -----------------------


async def test_an_xrechnung_may_be_uploaded(tmp_path: Path) -> None:
    """Verified 2026-08-20: .xml is accepted and parsed as an XRechnung."""
    invoice = tmp_path / "e-rechnung.xml"
    invoice.write_bytes(b"<Invoice/>")
    handler = Recorder(status=202, json_body=UPLOADED)
    server, provider = server_for(handler, tmp_path, mode="write")

    await server.call_tool("upload_file", {"path": str(invoice)})

    assert b'name="file"' in handler.last.content
    assert b"application/xml" in handler.last.content
    await provider.aclose()


async def test_a_gif_is_refused_because_the_api_refuses_it(tmp_path: Path) -> None:
    """Measured, not assumed: `inacceptable_file_extension`."""
    image = tmp_path / "scan.gif"
    image.write_bytes(b"GIF89a")
    handler = Recorder(status=202, json_body=UPLOADED)
    server, provider = server_for(handler, tmp_path, mode="write")

    with pytest.raises(ToolError):
        await server.call_tool("upload_file", {"path": str(image)})

    assert handler.requests == []
    await provider.aclose()


# -- reading a download into the answer -----------------------------------


async def _downloaded(server: Any, handler: Recorder, fmt: str = "pdf") -> str:
    result = await server.call_tool(
        "download_file", {"file_id": FILE_ID, "file_format": fmt}
    )
    return (result.structured_content or {})["uri"]


async def test_a_pdf_comes_back_as_an_embedded_binary(tmp_path: Path) -> None:
    """Nothing can read it, so it is handed over for the client to deal with."""
    handler = Recorder(headers={"content-type": "application/pdf"})
    server, provider = server_for(handler, tmp_path)
    uri = await _downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri})

    assert (result.structured_content or {})["deliveredAs"] == "binary"
    block = result.content[0]
    assert block.type == "resource"
    assert base64.b64decode(block.resource.blob) == PDF
    await provider.aclose()


async def test_an_xrechnung_comes_back_as_readable_text(tmp_path: Path) -> None:
    """The case worth having: an e-invoice a model can actually use."""
    invoice = b'<?xml version="1.0"?><Invoice><Total>119.00</Total></Invoice>'
    handler = Recorder(content=invoice, headers={"content-type": "application/xml"})
    server, provider = server_for(handler, tmp_path)
    uri = await _downloaded(server, handler, fmt="xml")

    result = await server.call_tool("read_download", {"uri": uri})

    assert (result.structured_content or {})["deliveredAs"] == "text"
    assert result.content[0].type == "text"
    assert "119.00" in result.content[0].text
    await provider.aclose()


async def test_an_image_comes_back_as_an_image(tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"payload"
    handler = Recorder(content=png, headers={"content-type": "image/png"})
    server, provider = server_for(handler, tmp_path)
    uri = await _downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri})

    assert (result.structured_content or {})["deliveredAs"] == "image"
    block = result.content[0]
    assert block.type == "image"
    assert block.mime_type == "image/png"
    assert base64.b64decode(block.data) == png
    await provider.aclose()


async def test_reading_costs_no_api_call(tmp_path: Path) -> None:
    """The file is already on the server's disk."""
    handler = Recorder(headers={"content-type": "application/pdf"})
    server, provider = server_for(handler, tmp_path)
    uri = await _downloaded(server, handler)
    before = len(handler.requests)

    await server.call_tool("read_download", {"uri": uri})

    assert len(handler.requests) == before
    await provider.aclose()


async def test_only_this_servers_downloads_can_be_read(tmp_path: Path) -> None:
    """Not a file reader. Anything outside the published set is refused."""
    handler = Recorder()
    server, provider = server_for(handler, tmp_path)

    for outside in (
        "file:///C:/Windows/win.ini",
        "/etc/passwd",
        "https://example.invalid/x",
    ):
        with pytest.raises(ToolError) as excinfo:
            await server.call_tool("read_download", {"uri": outside})
        assert "lexware://download/" in str(excinfo.value)
    await provider.aclose()


async def test_a_download_that_was_never_made_is_a_not_found(tmp_path: Path) -> None:
    handler = Recorder()
    server, provider = server_for(handler, tmp_path)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(
            "read_download", {"uri": "lexware://download/never-fetched.pdf"}
        )

    assert "never-fetched.pdf" in str(excinfo.value)
    await provider.aclose()


async def test_something_far_too_large_is_refused_rather_than_inlined(
    tmp_path: Path,
) -> None:
    """Base64 of a big file would swallow the whole answer."""
    huge = b"%PDF-1.4" + b"x" * (5 * 1024 * 1024 + 1)
    handler = Recorder(content=huge, headers={"content-type": "application/pdf"})
    server, provider = server_for(handler, tmp_path)
    uri = await _downloaded(server, handler)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("read_download", {"uri": uri})

    assert "MiB" in str(excinfo.value)
    await provider.aclose()


async def test_the_description_says_which_form_to_expect() -> None:
    server = build_server(Settings(api_key=API_KEY))
    tool = next(t for t in await server.list_tools() if t.name == "read_download")
    assert tool.description is not None
    assert "XML arrives as text" in tool.description
    assert "no** API call" in tool.description or "no API call" in tool.description
