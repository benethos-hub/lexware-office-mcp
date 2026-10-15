"""An upload fetched from a URL rather than read from this machine.

Another service hands the model a short-lived link, and the file travels from
service to service without passing through the model. What is tested here is
the fence around that: no URL without ``LXO_MCP_UPLOAD_URLS``, nothing sent
outside it, no redirect, a 5 MiB ceiling whether or not the size is declared,
only the types the API takes, and a link that never reaches a log line beyond
its scheme and host. Two handlers stand for two servers: ``fetch`` for the
one the file comes from, ``lexware`` for the API.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp.errors import ConfigError
from benethos_lexware_office_mcp.files import fetch
from benethos_lexware_office_mcp.files.storage import MAX_UPLOAD
from benethos_lexware_office_mcp.server import PolicyServer
from benethos_lexware_office_mcp.settings import load_settings
from helpers import (
    API_KEY,
    PDF,
    UPLOADED,
    Scripted,
    capture_lines,
    recorder,
    server_with,
)

INBOX = "https://files.example.com/inbox/"
LINK = "https://files.example.com/inbox/9f3c?sig=SECRET-QUERY"
VOUCHER = "PLACEHOLDER-VOUCHER-1"

TOOLS = ["upload_file", "attach_file_to_voucher"]


def served(
    content: bytes = PDF,
    *,
    status: int = 200,
    content_type: str | None = "application/pdf",
    headers: dict[str, str] | None = None,
) -> Scripted:
    """The other server, answering every request with one file."""
    sent = dict(headers or {})
    if content_type is not None:
        sent["Content-Type"] = content_type
    return Scripted(repeat=httpx.Response(status, content=content, headers=sent))


class Trickle(httpx.AsyncByteStream):
    """A body in chunks, counting how many were read, with no length declared."""

    def __init__(self, *chunks: bytes, pause: float = 0.0) -> None:
        self.chunks = chunks
        self.pause = pause
        self.read = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            if self.pause:
                await asyncio.sleep(self.pause)
            self.read += 1
            yield chunk


def streamed(body: Trickle, headers: dict[str, str] | None = None) -> Scripted:
    sent = {"Content-Type": "application/pdf", **(headers or {})}
    return Scripted(httpx.Response(200, headers=sent, stream=body))


def lexware() -> Scripted:
    return recorder(status=202, json_body=UPLOADED)


def server(
    api: Scripted, other: Scripted, *prefixes: str, tmp_path: Path
) -> PolicyServer:
    built, _ = server_with(
        api, fetch=other, download_path=tmp_path, upload_urls=prefixes
    )
    return built


def arguments(tool: str, source: str) -> dict[str, str]:
    if tool == "attach_file_to_voucher":
        return {"voucher_id": VOUCHER, "source": source}
    return {"source": source}


async def refused(server: PolicyServer, source: str, tool: str = "upload_file") -> str:
    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(tool, arguments(tool, source))
    return str(excinfo.value)


# -- the setting ----------------------------------------------------------


@pytest.mark.parametrize("tool", TOOLS)
async def test_without_the_setting_no_url_is_fetched(tool: str, tmp_path: Path) -> None:
    """Nothing is on without a decision, golden rule 1."""
    api, other = lexware(), served()

    message = await refused(server(api, other, tmp_path=tmp_path), LINK, tool)

    assert "LXO_MCP_UPLOAD_URLS" in message
    assert other.requests == []
    assert api.requests == []


@pytest.mark.parametrize("tool", TOOLS)
async def test_a_url_under_an_allowed_prefix_is_fetched_and_uploaded(
    tool: str, tmp_path: Path
) -> None:
    api, other = lexware(), served()

    await server(api, other, INBOX, tmp_path=tmp_path).call_tool(
        tool, arguments(tool, LINK)
    )

    assert str(other.last.url) == LINK
    assert len(api.requests) == 1
    assert PDF in api.last.content
    assert b'filename="9f3c.pdf"' in api.last.content


@pytest.mark.parametrize(
    "url",
    [
        "https://elsewhere.example.com/inbox/9f3c",
        "https://files.example.com.elsewhere.net/inbox/9f3c",
        "https://files.example.com:8443/inbox/9f3c",
        "http://files.example.com/inbox/9f3c",
        "https://files.example.com/outbox/9f3c",
        "https://files.example.com/inbox/../admin/9f3c",
        "https://files.example.com/inbox/%2e%2e/admin/9f3c",
        "https://files.example.com/inbox/..%2Fadmin",
        "https://files.example.com@elsewhere.net/inbox/9f3c",
    ],
    ids=[
        "host",
        "host as a prefix",
        "port",
        "scheme",
        "path",
        "dots",
        "encoded dots",
        "encoded slash",
        "user name",
    ],
)
async def test_a_url_outside_every_prefix_is_refused_before_a_request(
    url: str, tmp_path: Path
) -> None:
    api, other = lexware(), served()

    message = await refused(server(api, other, INBOX, tmp_path=tmp_path), url)

    assert "outside the addresses" in message
    assert other.requests == []
    assert api.requests == []


async def test_a_prefix_without_a_slash_covers_its_segment_and_no_other(
    tmp_path: Path,
) -> None:
    """`/inbox` covers `/inbox/a`, not `/inboxes/a`."""
    api, other = lexware(), served()
    built = server(api, other, "https://files.example.com/inbox", tmp_path=tmp_path)

    await built.call_tool(
        "upload_file", {"source": "https://files.example.com/inbox/a.pdf"}
    )
    message = await refused(built, "https://files.example.com/inboxes/a.pdf")

    assert len(other.requests) == 1
    assert "outside the addresses" in message


async def test_the_default_port_is_the_port_a_prefix_without_one_means(
    tmp_path: Path,
) -> None:
    api, other = lexware(), served()
    built = server(api, other, INBOX, tmp_path=tmp_path)

    await built.call_tool(
        "upload_file", {"source": "https://files.example.com:443/inbox/a.pdf"}
    )

    assert len(api.requests) == 1


async def test_a_prefix_with_a_port_takes_that_port_alone(tmp_path: Path) -> None:
    api, other = lexware(), served()
    built = server(api, other, "https://files.example.com:8443/", tmp_path=tmp_path)

    await built.call_tool(
        "upload_file", {"source": "https://files.example.com:8443/a.pdf"}
    )
    message = await refused(built, "https://files.example.com/a.pdf")

    assert len(other.requests) == 1
    assert "outside the addresses" in message


async def test_http_on_loopback_is_fetched(tmp_path: Path) -> None:
    """A service on the same machine, the one place plain http is taken."""
    api, other = lexware(), served()
    built = server(api, other, "http://127.0.0.1:8765/", tmp_path=tmp_path)

    await built.call_tool("upload_file", {"source": "http://127.0.0.1:8765/a.pdf"})

    assert len(api.requests) == 1


@pytest.mark.parametrize(
    "prefix", ["http://127.0.0.1:8765/", "http://localhost/", "http://[::1]:9000/x/"]
)
def test_http_is_allowed_for_loopback(prefix: str) -> None:
    settings = load_settings(env={"LXO_MCP_UPLOAD_URLS": prefix})

    assert settings.upload_urls == (prefix,)


def test_http_for_any_other_host_stops_the_start() -> None:
    with pytest.raises(ConfigError, match="only for a service on this machine"):
        load_settings(env={"LXO_MCP_UPLOAD_URLS": "http://files.example.com/"})


@pytest.mark.parametrize(
    "prefix",
    [
        "files.example.com",
        "ftp://files.example.com/",
        "https://",
        "https://user@files.example.com/",
        "https://files.example.com/?sig=1",
        "https://files.example.com/#top",
        "https://files.example.com/inbox/../",
        "https://files.example.com:port/",
    ],
)
def test_what_is_no_address_stops_the_start(prefix: str) -> None:
    with pytest.raises(ConfigError, match="LXO_MCP_UPLOAD_URLS takes addresses"):
        load_settings(env={"LXO_MCP_UPLOAD_URLS": prefix})


def test_the_setting_is_a_comma_separated_list() -> None:
    settings = load_settings(
        env={"LXO_MCP_UPLOAD_URLS": f" {INBOX} , http://127.0.0.1:8765/ ,"}
    )

    assert settings.upload_urls == (INBOX, "http://127.0.0.1:8765/")


async def test_a_file_url_is_refused_with_the_way_that_works(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.pdf"
    receipt.write_bytes(PDF)
    api, other = lexware(), served()

    message = await refused(
        server(api, other, INBOX, tmp_path=tmp_path), receipt.as_uri()
    )

    assert "Give the path on this machine itself" in message
    assert api.requests == []


async def test_a_path_is_read_as_before(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.pdf"
    receipt.write_bytes(PDF)
    api, other = lexware(), served()

    await server(api, other, INBOX, tmp_path=tmp_path).call_tool(
        "upload_file", {"source": str(receipt)}
    )

    assert other.requests == []
    assert b'filename="receipt.pdf"' in api.last.content


# -- the response ---------------------------------------------------------


async def test_a_redirect_is_not_followed(tmp_path: Path) -> None:
    api = lexware()
    other = served(status=302, headers={"Location": "https://elsewhere.net/a.pdf"})

    message = await refused(server(api, other, INBOX, tmp_path=tmp_path), LINK)

    assert "status 302" in message
    assert "redirect" in message
    assert len(other.requests) == 1
    assert api.requests == []


@pytest.mark.parametrize("status", [403, 404, 410, 500])
async def test_a_refusal_names_the_status_and_never_the_page(
    status: int, tmp_path: Path
) -> None:
    api = lexware()
    other = served(
        b"<html>internal details</html>", status=status, content_type="text/html"
    )

    message = await refused(server(api, other, INBOX, tmp_path=tmp_path), LINK)

    assert f"status {status}" in message
    assert "internal details" not in message
    assert api.requests == []


async def test_a_declared_length_above_the_ceiling_is_refused_unread(
    tmp_path: Path,
) -> None:
    body = Trickle(PDF)
    other = streamed(body, {"Content-Length": str(MAX_UPLOAD + 1)})
    api = lexware()

    message = await refused(server(api, other, INBOX, tmp_path=tmp_path), LINK)

    assert "5 MiB" in message
    assert body.read == 0
    assert api.requests == []


async def test_a_body_past_the_ceiling_is_cut_off_while_streaming(
    tmp_path: Path,
) -> None:
    """No length declared, so the count while reading is what holds."""
    mebibyte = b"x" * (1024 * 1024)
    body = Trickle(*[mebibyte] * 10)
    api = lexware()

    message = await refused(server(api, streamed(body), INBOX, tmp_path=tmp_path), LINK)

    assert "larger than 5 MiB" in message
    assert body.read == 6, "read on past the ceiling"
    assert api.requests == []


async def test_a_declared_length_that_lies_is_cut_off_all_the_same(
    tmp_path: Path,
) -> None:
    mebibyte = b"x" * (1024 * 1024)
    body = Trickle(*[mebibyte] * 10)
    other = streamed(body, {"Content-Length": "1000"})
    api = lexware()

    message = await refused(server(api, other, INBOX, tmp_path=tmp_path), LINK)

    assert "larger than 5 MiB" in message
    assert body.read == 6


async def test_a_body_of_exactly_five_mebibytes_without_a_length_is_sent(
    tmp_path: Path,
) -> None:
    body = Trickle(b"x" * (MAX_UPLOAD - 10), b"y" * 10)
    api = lexware()

    await server(api, streamed(body), INBOX, tmp_path=tmp_path).call_tool(
        "upload_file", {"source": LINK}
    )

    assert len(api.requests) == 1
    assert b"y" * 10 in api.last.content


@pytest.mark.parametrize(
    "content_type", ["text/html", "image/gif", "application/octet-stream", None]
)
async def test_a_type_the_api_does_not_take_is_refused(
    content_type: str | None, tmp_path: Path
) -> None:
    api = lexware()
    other = served(content_type=content_type)

    message = await refused(server(api, other, INBOX, tmp_path=tmp_path), LINK)

    assert "The API does not accept" in message
    assert api.requests == []


@pytest.mark.parametrize(
    ("content_type", "sent"),
    [
        ("application/pdf; charset=binary", b"application/pdf"),
        ("Application/PDF", b"application/pdf"),
        ("text/xml; charset=utf-8", b"application/xml"),
        ("image/jpeg", b"image/jpeg"),
    ],
)
async def test_a_type_is_read_without_its_parameters_and_text_xml_as_xml(
    content_type: str, sent: bytes, tmp_path: Path
) -> None:
    api = lexware()

    await server(
        api, served(content_type=content_type), INBOX, tmp_path=tmp_path
    ).call_tool("upload_file", {"source": LINK})

    assert b"Content-Type: " + sent in api.last.content


# -- the name -------------------------------------------------------------


@pytest.mark.parametrize(
    ("disposition", "url", "name"),
    [
        (
            'attachment; filename="../../Rechnung Mai.pdf"',
            LINK,
            b"Rechnung_Mai.pdf",
        ),
        ("attachment; filename*=UTF-8''Beleg%2042.pdf", LINK, b"Beleg_42.pdf"),
        ("", "https://files.example.com/inbox/scan-0042.pdf?sig=1", b"scan-0042.pdf"),
        ("", LINK, b"9f3c.pdf"),
        ("attachment", "https://files.example.com/inbox/", b"receipt.pdf"),
        ('attachment; filename="scan"', LINK, b"scan.pdf"),
    ],
    ids=["disposition", "encoded", "url path", "a key", "nothing", "no extension"],
)
async def test_the_name_comes_from_the_header_then_the_url_then_the_type(
    disposition: str, url: str, name: bytes, tmp_path: Path
) -> None:
    api = lexware()
    headers = {"Content-Disposition": disposition} if disposition else {}

    await server(api, served(headers=headers), INBOX, tmp_path=tmp_path).call_tool(
        "upload_file", {"source": url}
    )

    assert b'filename="' + name + b'"' in api.last.content


async def test_a_name_whose_extension_says_another_type_is_refused(
    tmp_path: Path,
) -> None:
    api = lexware()
    other = served(headers={"Content-Disposition": 'attachment; filename="photo.png"'})

    message = await refused(server(api, other, INBOX, tmp_path=tmp_path), LINK)

    assert "photo.png was served as application/pdf" in message
    assert api.requests == []


async def test_xml_that_is_no_xrechnung_is_refused_by_the_api_as_from_disk(
    tmp_path: Path,
) -> None:
    """No check of its own here, the API's is the one there is - for a file
    read from disk the same."""
    api = Scripted(
        repeat=(
            406,
            {
                "IssueList": [
                    {
                        "i18nKey": "invalid_xrechnung",
                        "source": "file",
                        "type": "validation_failure",
                    }
                ]
            },
        )
    )
    other = served(b"<note/>", content_type="text/xml")

    message = await refused(server(api, other, INBOX, tmp_path=tmp_path), LINK)

    assert "invalid_xrechnung" in message
    assert b'filename="9f3c.xml"' in api.last.content


# -- the request ----------------------------------------------------------


async def test_the_key_goes_to_lexware_and_never_to_the_other_server(
    tmp_path: Path,
) -> None:
    api, other = lexware(), served()

    await server(api, other, INBOX, tmp_path=tmp_path).call_tool(
        "upload_file", {"source": LINK}
    )

    assert "authorization" not in other.last.headers
    assert API_KEY not in str(other.last.headers)
    assert api.last.headers["authorization"] == f"Bearer {API_KEY}"


async def test_a_timeout_says_so(tmp_path: Path) -> None:
    api = lexware()
    other = Scripted(repeat=httpx.ReadTimeout("slow"))

    message = await refused(server(api, other, INBOX, tmp_path=tmp_path), LINK)

    assert "longer than 30 seconds" in message
    assert api.requests == []


async def test_the_time_limit_holds_for_the_whole_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server that sends a byte now and then never trips a read timeout."""
    monkeypatch.setattr(fetch, "TIMEOUT", 0.2)
    body = Trickle(*[b"x"] * 50, pause=0.02)
    api = lexware()

    message = await refused(server(api, streamed(body), INBOX, tmp_path=tmp_path), LINK)

    assert "longer than 30 seconds" in message
    assert body.read < 50
    assert api.requests == []


async def test_no_connection_says_so(tmp_path: Path) -> None:
    api = lexware()
    other = Scripted(repeat=httpx.ConnectError("refused"))

    message = await refused(server(api, other, INBOX, tmp_path=tmp_path), LINK)

    assert "could not be fetched from files.example.com: no connection" in message


# -- the log --------------------------------------------------------------


async def test_a_line_names_the_scheme_and_the_host_and_nothing_after(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    lines = capture_lines(caplog, "DEBUG")

    await server(lexware(), served(), INBOX, tmp_path=tmp_path).call_tool(
        "upload_file", {"source": LINK}
    )

    assert "from https://files.example.com in" in lines.text
    assert "9f3c" not in lines.text
    assert "SECRET-QUERY" not in lines.text
    assert "inbox" not in lines.text


async def test_a_failed_fetch_is_a_line_without_the_link(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    lines = capture_lines(caplog, "DEBUG")

    await refused(server(lexware(), served(status=404), INBOX, tmp_path=tmp_path), LINK)

    assert (
        "Fetching an upload from https://files.example.com failed: UpstreamError 404"
        in lines.text
    )
    assert "SECRET-QUERY" not in lines.text
    assert "9f3c" not in lines.text


async def test_a_url_outside_the_setting_leaves_no_host_in_the_log(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """The model chose that host, and a host name can carry anything."""
    lines = capture_lines(caplog, "DEBUG")

    await refused(
        server(lexware(), served(), INBOX, tmp_path=tmp_path),
        "https://mustermann-gmbh.example.net/a.pdf",
    )

    assert (
        "Refused to fetch an upload over https: the address is outside "
        "LXO_MCP_UPLOAD_URLS, nothing was requested"
    ) in lines.text
    assert "upload_file refused: ValidationError" in lines.text
    assert "mustermann" not in lines.text


async def test_without_the_setting_the_log_says_that_is_why(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    lines = capture_lines(caplog, "DEBUG")

    await refused(server(lexware(), served(), tmp_path=tmp_path), LINK)

    assert "LXO_MCP_UPLOAD_URLS allows no address, nothing was requested" in (
        lines.text
    )
    assert "files.example.com" not in lines.text


# -- the tool list --------------------------------------------------------


@pytest.mark.parametrize("tool", TOOLS)
async def test_the_same_tools_take_a_source_and_no_path(
    tool: str, tmp_path: Path
) -> None:
    """No tool is new, so a policy file written before reads as it did."""
    built, _ = server_with(lexware(), download_path=tmp_path)
    listed = {t.name: t for t in await built.list_tools()}

    properties = listed[tool].input_schema["properties"]

    assert "source" in properties
    assert "path" not in properties
    assert "URL" in properties["source"]["description"]
