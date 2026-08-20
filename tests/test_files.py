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

from benethos_lexware_office_mcp import policy, rendering, storage
from benethos_lexware_office_mcp.client import ClientProvider
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server

API_KEY = "test-key-0123456789"
FILE_ID = "PLACEHOLDER-FILE-1"


def make_pdf(pages: int = 1) -> bytes:
    """A real PDF with real glyphs, built here rather than checked in.

    The stub that used to stand in for one was never a valid document. It was
    enough while a PDF was only ever copied around, and stopped being enough
    the moment the server started rendering it, which is exactly the kind of
    fixture that hides a feature not working.
    """
    stream = (
        b"BT /F1 12 Tf 1 0 0 1 60 760 Tm (Rechnung RE-2026-0142) Tj "
        b"0 -20 Td (Gesamtbetrag 2.200,91 EUR) Tj ET"
    )
    kids = " ".join(f"{4 + n} 0 R" for n in range(pages))
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        f"<</Type/Pages/Kids[{kids}]/Count {pages}>>".encode(),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    objects += [
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
        b"/Resources<</Font<</F1 3 0 R>>>>/Contents "
        + str(4 + pages).encode()
        + b" 0 R>>"
        for _ in range(pages)
    ]
    objects.append(
        b"<</Length "
        + str(len(stream)).encode()
        + b">>stream\n"
        + stream
        + b"\nendstream"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj".encode() + body + b"endobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{start}\n%%EOF\n"
    ).encode()
    return bytes(out)


PDF = make_pdf()

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


async def test_the_same_document_twice_is_stored_once(tmp_path: Path) -> None:
    """Four downloads of one unchanged invoice used to leave four copies."""
    handler = Recorder(headers={"content-type": "application/pdf"})
    server, provider = server_for(handler, tmp_path)

    results = [
        await server.call_tool("download_file", {"file_id": FILE_ID}) for _ in range(4)
    ]

    uris = {(r.structured_content or {})["uri"] for r in results}
    assert len(uris) == 1
    assert len(list(tmp_path.iterdir())) == 1
    await provider.aclose()


async def test_a_document_that_changed_gets_its_own_file(tmp_path: Path) -> None:
    """The other half of the rule: nothing is ever overwritten."""
    directory = tmp_path
    first = storage.save(b"january", "invoice.pdf", directory)
    second = storage.save(b"february", "invoice.pdf", directory)

    assert first.name == "invoice.pdf"
    assert second.name == "invoice-2.pdf"
    assert first.read_bytes() == b"january"


def test_reusing_a_copy_that_already_carries_a_counter(tmp_path: Path) -> None:
    """The match may be behind a name that was itself pushed aside once."""
    storage.save(b"january", "invoice.pdf", tmp_path)
    numbered = storage.save(b"february", "invoice.pdf", tmp_path)

    again = storage.save(b"february", "invoice.pdf", tmp_path)

    assert again == numbered
    assert len(list(tmp_path.iterdir())) == 2


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


async def test_a_pdf_comes_back_as_pictures_of_its_pages(tmp_path: Path) -> None:
    """A PDF itself cannot be displayed by every client, a picture can."""
    handler = Recorder(headers={"content-type": "application/pdf"})
    server, provider = server_for(handler, tmp_path)
    uri = await _downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri})

    payload = result.structured_content or {}
    assert payload["deliveredAs"] == "pages"
    assert payload["pages"] == 1
    assert payload["pagesShown"] == 1

    images = [b for b in result.content if b.type == "image"]
    assert len(images) == 1
    assert images[0].mime_type == "image/png"
    assert base64.b64decode(images[0].data).startswith(b"\x89PNG\r\n\x1a\n")
    await provider.aclose()


async def test_a_rendered_page_is_sized_for_a_model_to_read(tmp_path: Path) -> None:
    """Past the client's own resize threshold the extra pixels are discarded."""
    pages, total = rendering.pdf_pages_as_png(make_pdf())

    assert total == 1
    page = pages[0]
    assert max(page.width, page.height) == rendering.MAX_EDGE
    # A4 is taller than it is wide, and that has to survive rendering.
    assert page.height > page.width


async def test_a_long_document_is_cut_off_and_says_so(tmp_path: Path) -> None:
    """Each page costs tokens by its dimensions, so the count is the budget."""
    handler = Recorder(
        content=make_pdf(pages=9), headers={"content-type": "application/pdf"}
    )
    server, provider = server_for(handler, tmp_path)
    uri = await _downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri})

    payload = result.structured_content or {}
    assert payload["pages"] == 9
    assert payload["pagesShown"] == rendering.MAX_PAGES
    assert len([b for b in result.content if b.type == "image"]) == rendering.MAX_PAGES
    assert "9 pages" in result.content[0].text
    await provider.aclose()


async def test_a_damaged_pdf_says_what_happened(tmp_path: Path) -> None:
    """Rather than a stack trace, or an empty answer that looks like success."""
    handler = Recorder(
        content=b"%PDF-1.4 not really", headers={"content-type": "application/pdf"}
    )
    server, provider = server_for(handler, tmp_path)
    uri = await _downloaded(server, handler)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("read_download", {"uri": uri})

    assert "could not be rendered" in str(excinfo.value)
    await provider.aclose()


async def test_something_that_is_not_a_document_still_comes_back_as_a_blob(
    tmp_path: Path,
) -> None:
    """The fallback is still there for anything with no better shape."""
    (tmp_path / "archive.bin").write_bytes(b"\x00\x01\x02")
    handler = Recorder()
    server, provider = server_for(handler, tmp_path)

    result = await server.call_tool(
        "read_download", {"uri": "lexware://download/archive.bin"}
    )

    assert (result.structured_content or {})["deliveredAs"] == "binary"
    assert result.content[0].type == "resource"
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
    handler = Recorder(
        content=png,
        headers={
            "content-type": "image/png",
            "content-disposition": "inline; filename=scan.png;",
        },
    )
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


async def test_rendering_does_not_touch_the_file_it_read(tmp_path: Path) -> None:
    """A download stays exactly what the API sent, whatever is shown from it."""
    handler = Recorder(headers={"content-type": "application/pdf"})
    server, provider = server_for(handler, tmp_path)
    downloaded = await server.call_tool("download_file", {"file_id": FILE_ID})
    path = Path((downloaded.structured_content or {})["path"])

    await server.call_tool(
        "read_download", {"uri": (downloaded.structured_content or {})["uri"]}
    )

    assert path.read_bytes() == PDF
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


# -- surviving a restart --------------------------------------------------


async def test_a_link_still_works_after_the_server_restarted(tmp_path: Path) -> None:
    """The registry lives in a process, the file does not.

    A URI handed out yesterday used to stop resolving today even though the
    file was sitting in the download directory, because only the in-memory
    registration knew about it.
    """
    (tmp_path / "invoice.pdf").write_bytes(PDF)
    handler = Recorder()
    fresh, provider = server_for(handler, tmp_path)

    assert await fresh.list_resources() == [], "nothing was downloaded by this process"

    result = await fresh.call_tool(
        "read_download", {"uri": "lexware://download/invoice.pdf"}
    )

    assert (result.structured_content or {})["deliveredAs"] == "pages"
    assert any(b.type == "image" for b in result.content)
    await provider.aclose()


async def test_the_content_type_comes_from_the_name_on_disk(tmp_path: Path) -> None:
    """Which is the name the API itself chose, in its Content-Disposition."""
    (tmp_path / "e-rechnung.xml").write_bytes(b"<Invoice/>")
    handler = Recorder()
    server, provider = server_for(handler, tmp_path)

    result = await server.call_tool(
        "read_download", {"uri": "lexware://download/e-rechnung.xml"}
    )

    assert (result.structured_content or {})["mimeType"] == "application/xml"
    assert (result.structured_content or {})["deliveredAs"] == "text"
    await provider.aclose()


async def test_a_uri_cannot_climb_out_of_the_download_directory(
    tmp_path: Path,
) -> None:
    """The name comes from the caller, so it is sanitized like any other input."""
    secret = tmp_path.parent / "secret.pdf"
    secret.write_bytes(b"not yours")
    handler = Recorder()
    server, provider = server_for(handler, tmp_path)

    with pytest.raises(ToolError):
        await server.call_tool(
            "read_download", {"uri": "lexware://download/../secret.pdf"}
        )
    await provider.aclose()
