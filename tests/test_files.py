"""Downloads: the file on disk, the resource link, and both surviving a restart."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError

from benethos_lexware_office_mcp.files import resources, storage
from benethos_lexware_office_mcp.policy import known_tools
from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.settings import Settings
from helpers import (
    API_KEY,
    FILE_ID,
    PDF,
    recorder,
    server_with,
)


async def test_download_file_writes_the_bytes_and_reports_the_path(
    tmp_path: Path,
) -> None:
    handler = recorder(headers={"content-type": "application/pdf"})
    server, provider = server_with(handler, download_path=tmp_path)

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
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

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
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    await server.call_tool("download_file", {"file_id": FILE_ID})

    assert handler.last.headers["Accept"] == "application/pdf"
    await provider.aclose()


async def test_xml_is_asked_for_when_it_is_wanted(tmp_path: Path) -> None:
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    await server.call_tool("download_file", {"file_id": FILE_ID, "file_format": "xml"})

    assert handler.last.headers["Accept"] == "application/xml"
    await provider.aclose()


async def test_a_document_is_fetched_from_its_own_resource_path(
    tmp_path: Path,
) -> None:
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    await server.call_tool(
        "download_document",
        {"document_type": "credit-note", "document_id": "PLACEHOLDER-DOC-1"},
    )

    assert handler.last.url.path == "/v1/credit-notes/PLACEHOLDER-DOC-1/file"
    await provider.aclose()


async def test_the_result_names_the_file_both_ways(tmp_path: Path) -> None:
    """A path serves a client on this machine, a URI serves every other one."""
    handler = recorder(headers={"content-type": "application/pdf"})
    server, provider = server_with(handler, download_path=tmp_path)

    result = await server.call_tool("download_file", {"file_id": FILE_ID})

    payload = result.structured_content
    assert payload is not None
    assert set(payload) == {"path", "uri", "mimeType", "size"}
    assert Path(payload["path"]).name in payload["uri"]
    assert payload["uri"].startswith("lexware://download/")
    await provider.aclose()


async def test_a_resource_link_comes_back_with_the_result(tmp_path: Path) -> None:
    handler = recorder(headers={"content-type": "application/pdf"})
    server, provider = server_with(handler, download_path=tmp_path)

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
    handler = recorder(headers={"content-type": "application/pdf"})
    server, provider = server_with(handler, download_path=tmp_path)

    result = await server.call_tool("download_file", {"file_id": FILE_ID})
    uri = (result.structured_content or {})["uri"]

    contents = list(await server.read_resource(uri))
    assert len(contents) == 1
    assert contents[0].content == PDF
    assert contents[0].mime_type == "application/pdf"
    await provider.aclose()


async def test_nothing_is_published_before_a_download(tmp_path: Path) -> None:
    """Only what this server actually fetched is reachable."""
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    assert await server.list_resources() == []

    await server.call_tool("download_file", {"file_id": FILE_ID})

    listed = await server.list_resources()
    assert [r.name for r in listed] == [f"{FILE_ID}.pdf"]
    await provider.aclose()


async def test_the_same_document_twice_is_stored_once(tmp_path: Path) -> None:
    """Four downloads of one unchanged invoice used to leave four copies."""
    handler = recorder(headers={"content-type": "application/pdf"})
    server, provider = server_with(handler, download_path=tmp_path)

    results = [
        await server.call_tool("download_file", {"file_id": FILE_ID}) for _ in range(4)
    ]

    uris = {(r.structured_content or {})["uri"] for r in results}
    assert len(uris) == 1
    assert len(list(tmp_path.iterdir())) == 1
    await provider.aclose()


def test_a_reused_download_is_noted_without_its_name(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    storage.save(b"january", "Rechnung_Mustermann.pdf", tmp_path)

    with caplog.at_level(logging.DEBUG, logger="benethos_lexware_office_mcp"):
        storage.save(b"january", "Rechnung_Mustermann.pdf", tmp_path)

    assert "An identical download of 7 bytes was on disk, reused it" in caplog.text
    assert "Mustermann" not in caplog.text


async def test_a_document_that_changed_gets_its_own_file(tmp_path: Path) -> None:
    """The other half of the rule: nothing is ever overwritten."""
    directory = tmp_path
    first = storage.save(b"january", "invoice.pdf", directory)
    second = storage.save(b"february", "invoice.pdf", directory)

    assert first.name == "invoice.pdf"
    assert second.name == "invoice-2.pdf"
    assert first.read_bytes() == b"january"


async def test_a_content_type_with_parameters_is_reduced_to_the_type(
    tmp_path: Path,
) -> None:
    handler = recorder(headers={"content-type": "application/pdf;charset=UTF-8"})
    server, provider = server_with(handler, download_path=tmp_path)

    result = await server.call_tool("download_file", {"file_id": FILE_ID})

    assert (result.structured_content or {})["mimeType"] == "application/pdf"
    await provider.aclose()


async def test_a_downloaded_xml_is_published_as_xml(tmp_path: Path) -> None:
    """An XRechnung is not a PDF, and a client deciding what to do needs to know."""
    handler = recorder(
        content=b"<Invoice/>", headers={"content-type": "application/xml"}
    )
    server, provider = server_with(handler, download_path=tmp_path)

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
    assert set(tool.output_schema["properties"]) == {
        "path",
        "uri",
        "mimeType",
        "size",
    }


async def test_a_link_still_works_after_the_server_restarted(tmp_path: Path) -> None:
    """A process ends, the file does not.

    Measured over stdio on 2026-08-21: a freshly started server answered
    `resources/list` with an empty list and `resources/read` with "Unknown
    resource" for a file in its own download directory, while `read_download`
    read the same file without trouble. Every URI a previous run handed out
    died with that run.
    """
    (tmp_path / "invoice.pdf").write_bytes(PDF)
    handler = recorder()
    fresh, provider = server_with(handler, download_path=tmp_path)

    listed = await fresh.list_resources()
    assert [r.name for r in listed] == ["invoice.pdf"]
    assert listed[0].mime_type == "application/pdf"

    contents = list(await fresh.read_resource("lexware://download/invoice.pdf"))
    assert contents[0].content == PDF

    result = await fresh.call_tool(
        "read_download", {"uri": "lexware://download/invoice.pdf"}
    )

    assert (result.structured_content or {})["deliveredAs"] == "pages"
    assert any(b.type == "image" for b in result.content)
    await provider.aclose()


@pytest.mark.parametrize(
    "uri",
    ["lexware://download/my invoice.pdf", "lexware://download/my%20invoice.pdf"],
)
async def test_a_file_put_there_by_hand_is_readable_under_the_name_listed(
    tmp_path: Path, uri: str
) -> None:
    """Listed under its own name, it has to be found under that name too."""
    (tmp_path / "my invoice.pdf").write_bytes(PDF)
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    listed = await server.list_resources()
    assert [str(r.uri) for r in listed] == ["lexware://download/my invoice.pdf"]

    result = await server.call_tool("read_download", {"uri": uri})

    assert (result.structured_content or {})["deliveredAs"] == "pages"
    await provider.aclose()


async def test_downloads_are_not_resources_while_no_download_tool_is_on(
    tmp_path: Path,
) -> None:
    """The policy file decides the resources too, not only the tools.

    Before, every file in the download directory was listed and readable even
    with a policy that enabled nothing at all.
    """
    (tmp_path / "invoice.pdf").write_bytes(PDF)
    policy = tmp_path.parent / f"{tmp_path.name}-only-profile.json"
    policy.write_text('{"get_profile": true}', encoding="utf-8")
    settings = Settings(
        api_key=API_KEY, download_path=tmp_path, tool_policy_path=policy
    )
    server = build_server(settings)

    assert await server.list_resources() == []
    with pytest.raises(ResourceNotFoundError):
        await server.read_resource("lexware://download/invoice.pdf")

    policy.write_text('{"read_download": true}', encoding="utf-8")

    assert [r.name for r in await server.list_resources()] == ["invoice.pdf"]


def test_every_gating_tool_is_a_tool() -> None:
    """A misspelt name here would quietly keep the resources off for good."""
    assert set(resources.GATING_TOOLS) <= set(known_tools())


def test_a_symbolic_link_in_the_download_directory_is_not_published(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("not a download", encoding="utf-8")
    try:
        (tmp_path / "link.pdf").symlink_to(outside)
    except OSError:
        pytest.skip("this account may not create symbolic links")
    (tmp_path / "invoice.pdf").write_bytes(PDF)

    assert [r.name for r in resources.listed(tmp_path, 100)] == ["invoice.pdf"]


@pytest.mark.parametrize(
    "failure",
    [
        PermissionError(13, "Permission denied", "/home/someone/cache/x.pdf"),
        OSError(28, "No space left on device"),
        FileExistsError("Too many files already named like 'x.pdf'."),
    ],
    ids=["denied", "full", "collisions"],
)
async def test_a_download_that_cannot_be_saved_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: OSError
) -> None:
    """A tool error with the system's reason, not a crash and never the path."""

    def refuse(*_args: object) -> Path:
        raise failure

    monkeypatch.setattr(storage, "save", refuse)
    handler = recorder(headers={"content-type": "application/pdf"})
    server, provider = server_with(handler, download_path=tmp_path)

    with pytest.raises(ToolError, match="Could not save the download") as excinfo:
        await server.call_tool("download_file", {"file_id": FILE_ID})

    message = str(excinfo.value)
    assert (failure.strerror or str(failure)) in message
    assert "someone" not in message
    await provider.aclose()


async def test_building_a_server_does_not_create_a_download_directory(
    tmp_path: Path,
) -> None:
    """Listing the tool surface should leave nothing behind."""
    empty = tmp_path / "never-used"
    build_server(Settings(api_key=API_KEY, download_path=empty))

    assert not empty.exists()


async def test_the_content_type_comes_from_the_name_on_disk(tmp_path: Path) -> None:
    """Which is the name the API itself chose, in its Content-Disposition."""
    (tmp_path / "e-rechnung.xml").write_bytes(b"<Invoice/>")
    handler = recorder()
    server, provider = server_with(handler, download_path=tmp_path)

    result = await server.call_tool(
        "read_download", {"uri": "lexware://download/e-rechnung.xml"}
    )

    assert (result.structured_content or {})["mimeType"] == "application/xml"
    assert (result.structured_content or {})["deliveredAs"] == "text"
    await provider.aclose()


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("download_file", {"file_id": FILE_ID}),
        (
            "download_document",
            {"document_type": "invoice", "document_id": "PLACEHOLDER-DOC-1"},
        ),
    ],
)
async def test_a_download_says_where_the_bytes_are_and_nothing_else(
    tool: str, args: dict[str, str], tmp_path: Path
) -> None:
    """A download answers one question, and a link into the web app is another.

    They were joined once and the join is what let a broken link ride along
    with a working download for two days.
    """
    handler = recorder(headers={"content-type": "application/pdf"})
    server, provider = server_with(handler, download_path=tmp_path)

    result = await server.call_tool(tool, args)

    assert "deeplink" not in (result.structured_content or {})
    assert "permalink" not in result.content[0].text
    await provider.aclose()


async def test_the_description_sends_the_model_to_the_tool_that_links() -> None:
    """The routes only help if the description names them and says when.

    A result carrying `path` and `uri` is useless if the model has to guess
    which one its client can act on, and neither download carries a link any
    more, so both have to name the tool that does.
    """
    server = build_server(Settings(api_key=API_KEY))
    tools = {t.name: t for t in await server.list_tools()}

    stored = tools["download_file"].description or ""
    for route in ("`path`", "`uri`", "read_download"):
        assert route in stored, route
    for name in ("download_file", "download_document"):
        assert "get_deeplink" in (tools[name].description or ""), name


# -- the list is bounded, the directory is not ------------------------------


def _aged(directory: Path, names: list[str]) -> None:
    """One file per name, each a minute younger than the one before."""
    for age, name in enumerate(reversed(names)):
        path = directory / name
        path.write_bytes(PDF)
        stamp = 1_800_000_000 - age * 60
        os.utime(path, (stamp, stamp))


async def test_the_list_names_the_newest_downloads_first_and_no_more(
    tmp_path: Path,
) -> None:
    """The directory grows with every document, and the SDK sends it whole."""
    _aged(tmp_path, ["a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf"])
    server, provider = server_with(
        recorder(), download_path=tmp_path, listed_downloads=3
    )

    listed = await server.list_resources()

    assert [r.name for r in listed] == ["e.pdf", "d.pdf", "c.pdf"]
    await provider.aclose()


async def test_a_file_too_old_to_be_listed_is_still_readable(tmp_path: Path) -> None:
    """Unlisted is not hidden: a link handed out earlier keeps working."""
    _aged(tmp_path, ["old.pdf", "new.pdf"])
    server, provider = server_with(
        recorder(), download_path=tmp_path, listed_downloads=1
    )

    assert [r.name for r in await server.list_resources()] == ["new.pdf"]
    contents = list(await server.read_resource("lexware://download/old.pdf"))
    assert contents[0].content == PDF
    result = await server.call_tool(
        "read_download", {"uri": "lexware://download/old.pdf"}
    )
    assert (result.structured_content or {})["deliveredAs"] == "pages"
    await provider.aclose()


async def test_a_limit_of_zero_lists_nothing_and_still_reads(tmp_path: Path) -> None:
    (tmp_path / "invoice.pdf").write_bytes(PDF)
    server, provider = server_with(
        recorder(), download_path=tmp_path, listed_downloads=0
    )

    assert await server.list_resources() == []
    contents = list(await server.read_resource("lexware://download/invoice.pdf"))
    assert contents[0].content == PDF
    await provider.aclose()


async def test_a_file_removed_from_disk_is_gone_from_the_list_and_the_link(
    tmp_path: Path,
) -> None:
    """Answered from the disk, so a deleted download leaves no entry behind."""
    (tmp_path / "invoice.pdf").write_bytes(PDF)
    server, provider = server_with(recorder(), download_path=tmp_path)
    assert [r.name for r in await server.list_resources()] == ["invoice.pdf"]

    (tmp_path / "invoice.pdf").unlink()

    assert await server.list_resources() == []
    with pytest.raises(ResourceNotFoundError):
        await server.read_resource("lexware://download/invoice.pdf")
    await provider.aclose()


async def test_a_name_that_leaves_the_directory_is_not_read(tmp_path: Path) -> None:
    """The URI arrives from the client, so its name is not trusted."""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (tmp_path / "secret.pdf").write_bytes(PDF)
    server, provider = server_with(recorder(), download_path=downloads)

    with pytest.raises(ResourceNotFoundError):
        await server.read_resource("lexware://download/../secret.pdf")
    with pytest.raises(ResourceNotFoundError):
        await server.read_resource("lexware://download/..%2Fsecret.pdf")
    await provider.aclose()


async def test_a_directory_not_made_yet_lists_nothing_and_reads_nothing(
    tmp_path: Path,
) -> None:
    """A server that has never downloaded anything, and no error for it."""
    server = build_server(Settings(api_key=API_KEY, download_path=tmp_path / "none"))

    assert await server.list_resources() == []
    with pytest.raises(ResourceNotFoundError):
        await server.read_resource("lexware://download/invoice.pdf")
