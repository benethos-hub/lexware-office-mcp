"""A live upload fetched from a URL, against a confirmed test account.

**Run by hand. Never a gate, never in CI, never collected by pytest**, see
SPECS.md section 14.1. Unlike `smoke.py` this one **writes**: the upload
creates an `unchecked` voucher, and the API cannot delete a voucher - only
the web app can, while nothing has bound it. So it refuses to write unless
`--expect-company` and `--expect-organization` both name what `get_profile`
reports, which is the check golden rule 1 asks for before any write, done by
the script rather than remembered by the person running it. The id as well
as the name, since a test account may carry the same company name as the
real one. And it reads the `.env` that `--env-file` names and no other: left
to look, the server finds the configuration it runs with every day, which is
the real account's.

    uv run python live/upload_from_url.py --env-file test.env
        --expect-company "Test Inc" --expect-organization <organizationId>

What it does: a `http.server` on 127.0.0.1 serves a small PDF out of a
temporary directory, `LXO_MCP_UPLOAD_URLS` is set to that address alone,
and `upload_file` is given the link. Before the write, a link one port off
is checked to be refused without a request. After it, the local server is
asked what it was sent: one request, for the file, and no `Authorization`
header. The server is built with a policy that enables `get_profile` and
`upload_file` and nothing else.

Identifiers are masked in the output, as in `smoke.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import http.server
import re
import sys
import tempfile
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from benethos_lexware_office_mcp.api.client import ClientProvider  # noqa: E402
from benethos_lexware_office_mcp.logbook import configure  # noqa: E402
from benethos_lexware_office_mcp.policy import ToolPolicy  # noqa: E402
from benethos_lexware_office_mcp.server import build_server  # noqa: E402
from benethos_lexware_office_mcp.settings import load_settings  # noqa: E402

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def mask(value: Any) -> str:
    return _UUID.sub("<id>", str(value))


def receipt_pdf(text: str) -> bytes:
    """A one-page PDF with a line of text, valid enough for the API to take."""
    stream = f"BT /F1 14 Tf 60 760 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[4 0 R]/Count 1>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
        b"/Resources<</Font<</F1 3 0 R>>>>/Contents 5 0 R>>",
        b"<</Length "
        + str(len(stream)).encode()
        + b">>stream\n"
        + stream
        + b"\nendstream",
    ]
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


class Served:
    """A file server on a free loopback port, remembering what it was asked."""

    def __init__(self, directory: Path) -> None:
        seen: list[tuple[str, dict[str, str]]] = []

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=str(directory), **kwargs)

            def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
                seen.append((self.path, dict(self.headers.items())))
                super().do_GET()

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return None

        self.seen = seen
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> Served:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


async def run(env_file: Path, company: str, organization: str) -> int:
    settings = load_settings(env_file=env_file)
    if not settings.api_key:
        print("No API key. This script needs a live test account.", file=sys.stderr)
        return 2

    # The server's own lines, as a person would read them on stderr: the
    # fetch named by scheme and host, the libraries held at WARNING.
    configure("INFO", sys.stderr)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"url-probe-{stamp}.pdf"
    with (
        tempfile.TemporaryDirectory() as files,
        tempfile.TemporaryDirectory() as config,
        Served(Path(files)) as served,
    ):
        (Path(files) / name).write_bytes(receipt_pdf(f"url-probe {stamp}"))
        policy_path = Path(config) / "tools.json"
        ToolPolicy(policy_path).save({"get_profile": True, "upload_file": True})
        prefix = f"http://127.0.0.1:{served.port}/"
        settings = replace(
            settings, tool_policy_path=policy_path, upload_urls=(prefix,)
        )
        provider = ClientProvider(settings)
        server = build_server(settings, provider)
        try:
            return await _steps(server, served, (company, organization), prefix, name)
        finally:
            await provider.aclose()


async def _steps(
    server: Any,
    served: Served,
    expected: tuple[str, str],
    prefix: str,
    name: str,
) -> int:
    tools = sorted(tool.name for tool in await server.list_tools())
    print(f"\nTools offered: {', '.join(tools)}")

    profile = (await server.call_tool("get_profile", {})).structured_content or {}
    found = (profile.get("companyName"), profile.get("organizationId"))
    print(f"Account: {found[0]!r}, organization {mask(found[1])}")
    if found != expected:
        print(
            "Not the account named by --expect-company and "
            "--expect-organization. Nothing was written.",
            file=sys.stderr,
        )
        return 1

    elsewhere = f"http://127.0.0.1:{served.port + 1}/{name}"
    try:
        await server.call_tool("upload_file", {"source": elsewhere})
    except Exception as exc:  # noqa: BLE001 - the refusal is what is checked
        refused = "outside the addresses" in str(exc)
    else:
        refused = False
    print(f"  {'ok  ' if refused else 'FAIL'} a link one port off is refused")
    if not refused or served.seen:
        print("The fence did not hold. Stopped before writing.", file=sys.stderr)
        return 1

    result = await server.call_tool("upload_file", {"source": prefix + name})
    answer = result.structured_content or {}
    print(f"  ok   uploaded as file {mask(answer.get('id'))}")
    print(f"       voucher {mask(answer.get('voucherId'))}, unchecked, {name}")

    paths = [path for path, _ in served.seen]
    sent_auth = any(
        key.lower() == "authorization" for _, headers in served.seen for key in headers
    )
    one = paths == [f"/{name}"]
    print(f"  {'ok  ' if one else 'FAIL'} the local server was asked once: {paths}")
    print(f"  {'FAIL' if sent_auth else 'ok  '} no Authorization header reached it")
    return 0 if one and not sent_auth and answer.get("voucherId") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Upload a test PDF fetched from a URL on 127.0.0.1 to a confirmed "
            "test account. Writes one unchecked voucher the API cannot delete."
        )
    )
    parser.add_argument(
        "--expect-company",
        required=True,
        metavar="NAME",
        help="the companyName get_profile must report, or nothing is written",
    )
    parser.add_argument(
        "--expect-organization",
        required=True,
        metavar="ID",
        help="the organizationId get_profile must report, or nothing is written",
    )
    parser.add_argument(
        "--env-file",
        required=True,
        metavar="PATH",
        help="the test account's .env, read instead of looking for one",
    )
    args = parser.parse_args(argv)
    env_file = Path(args.env_file).expanduser()
    if not env_file.is_file():
        print(f"Not a file: {env_file}", file=sys.stderr)
        return 2
    return asyncio.run(run(env_file, args.expect_company, args.expect_organization))


if __name__ == "__main__":
    sys.exit(main())
