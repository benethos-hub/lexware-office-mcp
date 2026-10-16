"""What the live scripts share: masked ids, and a receipt to upload.

Beside them rather than in the package, since nothing the server runs needs
either, and outside ``testpaths`` like them. The suite has its own PDF in
``tests/helpers.py``: it never imports from here, since a test that reached
into ``live/`` would be one step from reaching an account.
"""

from __future__ import annotations

import re
from typing import Any

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_SEEN: dict[str, str] = {}


def mask(value: Any) -> str:
    """Replace every id with a stable placeholder, so a report can travel."""

    def substitute(match: re.Match[str]) -> str:
        return _SEEN.setdefault(match.group(0), f"<id-{len(_SEEN) + 1}>")

    return _UUID.sub(substitute, str(value))


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
