"""Putting a downloaded file into the answer: text, image, rendered pages or blob."""

from __future__ import annotations

import base64
import re
import struct
import threading
import zlib
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp.files import rendering
from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.settings import (
    DEFAULT_PDF_PAGES,
    MAX_PDF_PAGES,
    Settings,
)
from helpers import (
    API_KEY,
    FILE_ID,
    PDF,
    downloaded,
    make_pdf,
    recorder,
    server_with,
)


async def test_a_pdf_comes_back_as_pictures_of_its_pages(tmp_path: Path) -> None:
    """A PDF itself cannot be displayed by every client, a picture can."""
    handler = recorder(headers={"content-type": "application/pdf"})
    server, provider = server_with(handler, download_path=tmp_path)
    uri = await downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri})

    payload = result.structured_content or {}
    assert payload["deliveredAs"] == "pages"
    assert payload["pages"] == 1
    assert payload["pagesShown"] == 1

    images = [b for b in result.content if b.type == "image"]
    assert len(images) == 1
    assert images[0].mime_type == "image/png"
    assert base64.b64decode(images[0].data).startswith(b"\x89PNG\r\n\x1a\n")


async def test_a_rendered_page_is_sized_for_a_model_to_read(tmp_path: Path) -> None:
    """Past the client's own resize threshold the extra pixels are discarded."""
    pages, total = rendering.pdf_pages_as_png(make_pdf())

    assert total == 1
    page = pages[0]
    assert max(page.width, page.height) == rendering.MAX_EDGE
    # A4 is taller than it is wide, and that has to survive rendering.
    assert page.height > page.width


async def test_a_document_within_the_default_is_rendered_whole(
    tmp_path: Path,
) -> None:
    handler = recorder(
        content=make_pdf(pages=9), headers={"content-type": "application/pdf"}
    )
    server, provider = server_with(handler, download_path=tmp_path)
    uri = await downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri})

    payload = result.structured_content or {}
    assert payload["pages"] == 9
    assert payload["pagesShown"] == 9
    assert len([b for b in result.content if b.type == "image"]) == 9
    assert "all rendered" in result.content[0].text


async def test_a_longer_document_stops_at_the_default_and_says_so(
    tmp_path: Path,
) -> None:
    """A partial read must never look like a complete one."""
    handler = recorder(
        content=make_pdf(pages=14), headers={"content-type": "application/pdf"}
    )
    server, provider = server_with(handler, download_path=tmp_path)
    uri = await downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri})

    payload = result.structured_content or {}
    assert payload["pages"] == 14
    assert payload["pagesShown"] == DEFAULT_PDF_PAGES
    assert f"first {DEFAULT_PDF_PAGES}" in result.content[0].text


async def test_null_asks_for_all_of_them(tmp_path: Path) -> None:
    handler = recorder(
        content=make_pdf(pages=14), headers={"content-type": "application/pdf"}
    )
    server, provider = server_with(handler, download_path=tmp_path)
    uri = await downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri, "max_pages": None})

    payload = result.structured_content or {}
    assert payload["pagesShown"] == 14
    assert len([b for b in result.content if b.type == "image"]) == 14


async def test_the_default_is_stated_where_the_model_reads_it() -> None:
    """A silent cut-off is only acceptable if the schema admits to it."""
    server = build_server(Settings(api_key=API_KEY))
    tool = next(t for t in await server.list_tools() if t.name == "read_download")

    field = tool.input_schema["properties"]["max_pages"]
    assert field["default"] == DEFAULT_PDF_PAGES
    assert str(DEFAULT_PDF_PAGES) in field["description"]
    assert tool.description is not None
    assert str(DEFAULT_PDF_PAGES) in tool.description
    assert "max_pages" in tool.description


async def test_a_caller_who_only_wants_the_front_can_say_so(tmp_path: Path) -> None:
    """And is told what was left behind, rather than being let believe it is all."""
    handler = recorder(
        content=make_pdf(pages=9), headers={"content-type": "application/pdf"}
    )
    server, provider = server_with(handler, download_path=tmp_path)
    uri = await downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri, "max_pages": 2})

    payload = result.structured_content or {}
    assert payload["pages"] == 9
    assert payload["pagesShown"] == 2
    assert len([b for b in result.content if b.type == "image"]) == 2
    assert "first 2" in result.content[0].text


def test_red_is_rendered_red() -> None:
    """PDFium hands out BGR by default. Written into an RGB PNG unchanged,
    the red stamp on a dunning letter arrived blue."""
    red_page = make_pdf(stream=b"1 0 0 rg 0 0 595 842 re f")

    pages, _ = rendering.pdf_pages_as_png(red_page, max_edge=40)

    png = pages[0].png
    ihdr = png[16:29]
    width, _height, _depth, colour_type = struct.unpack(">IIBB", ihdr[:10])
    assert colour_type == 2  # RGB
    rows = zlib.decompress(_idat(png))
    first_pixel = rows[1:4]  # after the row's filter byte
    assert first_pixel == b"\xff\x00\x00", first_pixel
    assert len(rows) == (1 + width * 3) * pages[0].height


def _idat(png: bytes) -> bytes:
    data, offset = b"", 8
    while offset < len(png):
        (length,) = struct.unpack(">I", png[offset : offset + 4])
        tag = png[offset + 4 : offset + 8]
        if tag == b"IDAT":
            data += png[offset + 8 : offset + 8 + length]
        offset += 12 + length
    return data


def test_padding_at_the_end_of_a_row_is_not_part_of_the_image() -> None:
    """A bitmap row can be longer than its pixels. Two 1x1 rows padded to 4."""
    pixels = b"\x01\x02\x03\xee" + b"\x04\x05\x06\xee"

    png = rendering._png(pixels, 1, 2, 3, stride=4)

    assert zlib.decompress(_idat(png)) == b"\x00\x01\x02\x03\x00\x04\x05\x06"


async def test_rendering_runs_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seconds of CPU on the loop would hold every other call up."""
    (tmp_path / "invoice.pdf").write_bytes(PDF)
    server, provider = server_with(recorder(), download_path=tmp_path)
    real = rendering.pdf_pages_as_png
    seen: list[int] = []

    def recording(*args: Any, **kwargs: Any) -> Any:
        seen.append(threading.get_ident())
        return real(*args, **kwargs)

    monkeypatch.setattr(rendering, "pdf_pages_as_png", recording)

    await server.call_tool("read_download", {"uri": "lexware://download/invoice.pdf"})

    assert seen and seen[0] != threading.get_ident()


async def test_every_page_means_at_most_the_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """null renders every page there is, up to MAX_PDF_PAGES and no further."""
    from benethos_lexware_office_mcp.tools import files as files_tools

    monkeypatch.setattr(files_tools, "MAX_PDF_PAGES", 2)
    (tmp_path / "long.pdf").write_bytes(make_pdf(pages=3))
    server, provider = server_with(recorder(), download_path=tmp_path)

    result = await server.call_tool(
        "read_download", {"uri": "lexware://download/long.pdf", "max_pages": None}
    )

    summary = result.structured_content or {}
    assert (summary["pages"], summary["pagesShown"]) == (3, 2)


async def test_asking_for_more_than_the_ceiling_is_refused(tmp_path: Path) -> None:
    server, provider = server_with(recorder(), download_path=tmp_path)

    with pytest.raises(ToolError):
        await server.call_tool(
            "read_download",
            {"uri": "lexware://download/x.pdf", "max_pages": DEFAULT_PDF_PAGES * 100},
        )


def test_asking_for_more_pages_than_there_are_is_not_an_error() -> None:
    pages, total = rendering.pdf_pages_as_png(make_pdf(pages=2), max_pages=50)
    assert total == 2
    assert len(pages) == 2


async def test_a_damaged_pdf_says_what_happened(tmp_path: Path) -> None:
    """Rather than a stack trace, or an empty answer that looks like success."""
    handler = recorder(
        content=b"%PDF-1.4 not really", headers={"content-type": "application/pdf"}
    )
    server, provider = server_with(handler, download_path=tmp_path)
    uri = await downloaded(server, handler)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("read_download", {"uri": uri})

    assert "could not be rendered" in str(excinfo.value)
    assert ".." not in str(excinfo.value), "PDFium's message ends in a full stop"


async def test_something_that_is_not_a_document_still_comes_back_as_a_blob(
    tmp_path: Path,
) -> None:
    """The fallback is still there for anything with no better shape."""
    (tmp_path / "archive.bin").write_bytes(b"\x00\x01\x02")
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    result = await server.call_tool(
        "read_download", {"uri": "lexware://download/archive.bin"}
    )

    assert (result.structured_content or {})["deliveredAs"] == "binary"
    assert result.content[0].type == "resource"


async def test_an_xrechnung_comes_back_as_readable_text(tmp_path: Path) -> None:
    """The case worth having: an e-invoice a model can actually use."""
    invoice = b'<?xml version="1.0"?><Invoice><Total>119.00</Total></Invoice>'
    handler = recorder(content=invoice, headers={"content-type": "application/xml"})
    server, provider = server_with(handler, download_path=tmp_path)
    uri = await downloaded(server, handler, fmt="xml")

    result = await server.call_tool("read_download", {"uri": uri})

    assert (result.structured_content or {})["deliveredAs"] == "text"
    assert result.content[0].type == "text"
    assert "119.00" in result.content[0].text


async def test_an_image_comes_back_as_an_image(tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"payload"
    handler = recorder(
        content=png,
        headers={
            "content-type": "image/png",
            "content-disposition": "inline; filename=scan.png;",
        },
    )
    server, provider = server_with(handler, download_path=tmp_path)
    uri = await downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri})

    assert (result.structured_content or {})["deliveredAs"] == "image"
    block = result.content[0]
    assert block.type == "image"
    assert block.mime_type == "image/png"
    assert base64.b64decode(block.data) == png


async def test_reading_costs_no_api_call(tmp_path: Path) -> None:
    """The file is already on the server's disk."""
    handler = recorder(headers={"content-type": "application/pdf"})
    server, provider = server_with(handler, download_path=tmp_path)
    uri = await downloaded(server, handler)
    before = len(handler.requests)

    await server.call_tool("read_download", {"uri": uri})

    assert len(handler.requests) == before


async def test_rendering_does_not_touch_the_file_it_read(tmp_path: Path) -> None:
    """A download stays exactly what the API sent, whatever is shown from it."""
    handler = recorder(headers={"content-type": "application/pdf"})
    server, provider = server_with(handler, download_path=tmp_path)
    downloaded = await server.call_tool("download_file", {"file_id": FILE_ID})
    path = Path((downloaded.structured_content or {})["path"])

    await server.call_tool(
        "read_download", {"uri": (downloaded.structured_content or {})["uri"]}
    )

    assert path.read_bytes() == PDF


async def test_only_this_servers_downloads_can_be_read(tmp_path: Path) -> None:
    """Not a file reader. Anything outside the published set is refused."""
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    for outside in (
        "file:///C:/Windows/win.ini",
        "/etc/passwd",
        "https://example.invalid/x",
    ):
        with pytest.raises(ToolError) as excinfo:
            await server.call_tool("read_download", {"uri": outside})
        assert "lexware://download/" in str(excinfo.value)


async def test_a_download_that_was_never_made_is_a_not_found(tmp_path: Path) -> None:
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(
            "read_download", {"uri": "lexware://download/never-fetched.pdf"}
        )

    assert "never-fetched.pdf" in str(excinfo.value)


async def test_something_far_too_large_is_refused_rather_than_inlined(
    tmp_path: Path,
) -> None:
    """Base64 of a big file would swallow the whole answer."""
    huge = b"%PDF-1.4" + b"x" * (5 * 1024 * 1024 + 1)
    handler = recorder(content=huge, headers={"content-type": "application/pdf"})
    server, provider = server_with(handler, download_path=tmp_path)
    uri = await downloaded(server, handler)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("read_download", {"uri": uri})

    assert "MiB" in str(excinfo.value)


async def test_the_description_says_which_form_to_expect() -> None:
    """Every kind is named, so the model knows what it is about to receive.

    Asserted on the content rather than on a sentence, so that rewording the
    description does not fail the test while dropping a kind does.
    """
    server = build_server(Settings(api_key=API_KEY))
    tool = next(t for t in await server.list_tools() if t.name == "read_download")

    assert tool.description is not None
    for kind in ("XML", "text", "PDF", "pages", "Image", "binary"):
        assert kind in tool.description, kind
    assert "No API call" in tool.description


async def test_a_download_that_cannot_be_read_back_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "invoice.pdf").write_bytes(PDF)
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    def locked(_self: Path) -> bytes:
        raise PermissionError(13, "Permission denied", str(tmp_path))

    monkeypatch.setattr(Path, "read_bytes", locked)

    with pytest.raises(ToolError, match="Permission denied") as excinfo:
        await server.call_tool(
            "read_download", {"uri": "lexware://download/invoice.pdf"}
        )

    assert str(tmp_path) not in str(excinfo.value)


async def test_a_uri_cannot_climb_out_of_the_download_directory(
    tmp_path: Path,
) -> None:
    """The name comes from the caller, so it is sanitized like any other input."""
    secret = tmp_path.parent / "secret.pdf"
    secret.write_bytes(b"not yours")
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    with pytest.raises(ToolError):
        await server.call_tool(
            "read_download", {"uri": "lexware://download/../secret.pdf"}
        )


async def test_the_page_default_follows_the_configuration(tmp_path: Path) -> None:
    """An operator with a tight context budget can lower it once, not per call."""
    handler = recorder(
        content=make_pdf(pages=8), headers={"content-type": "application/pdf"}
    )
    server, provider = server_with(handler, download_path=tmp_path, pdf_pages=2)
    uri = await downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri})

    assert (result.structured_content or {})["pagesShown"] == 2


async def test_a_configured_default_is_stated_in_the_schema_too() -> None:
    """Otherwise the model would plan around a number that is not in force."""
    server = build_server(Settings(api_key=API_KEY, pdf_pages=4))
    tool = next(t for t in await server.list_tools() if t.name == "read_download")

    field = tool.input_schema["properties"]["max_pages"]
    assert field["default"] == 4
    assert "Defaults to 4" in field["description"]
    assert tool.description is not None
    assert "first 4" in tool.description
    # As a word: the description names the ceiling, 100, as well.
    assert not re.search(rf"\b{DEFAULT_PDF_PAGES}\b", tool.description), (
        "the built-in default leaked"
    )


async def test_the_caller_still_outranks_the_configuration(tmp_path: Path) -> None:
    handler = recorder(
        content=make_pdf(pages=8), headers={"content-type": "application/pdf"}
    )
    server, provider = server_with(handler, download_path=tmp_path, pdf_pages=2)
    uri = await downloaded(server, handler)

    result = await server.call_tool("read_download", {"uri": uri, "max_pages": None})

    assert (result.structured_content or {})["pagesShown"] == 8


async def test_the_description_says_null_stops_at_the_ceiling(tmp_path: Path) -> None:
    """It said to pass null if the rest matters, and null renders 100."""
    server, provider = server_with(recorder(), download_path=tmp_path)

    tools = {tool.name: tool for tool in await server.list_tools()}
    description = tools["read_download"].description or ""

    assert f"null for up to {MAX_PDF_PAGES}" in description
    assert "{limit}" not in description
