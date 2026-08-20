"""PDF pages as PNG images.

A PDF cannot be handed to every client as a PDF. Claude Desktop maps a binary
resource onto an image block when it builds its own API request, and
``application/pdf`` is not a permitted image type there, so the request is
refused outright (SPECS.md section 13). Rendering the pages is what makes a
document visible at all in such a client, confirmed against Claude Desktop on
2026-08-20 rather than merely reasoned about.

Two choices worth stating, both measured rather than assumed on 2026-08-20
against a two-page A4 invoice:

**Why PDFium and not the obvious library.** PyMuPDF is faster and better
known, and it is AGPL-3.0 or a commercial licence from Artifex. This project
is MIT, so that is not a licence it can take. ``pypdfium2`` wraps the same
PDFium that Chrome uses, under BSD-3-Clause and Apache-2.0, and ships a 3.7 MiB
wheel for every platform this project supports.

**Why no imaging library.** Encoding a PNG from raw pixels is zlib plus four
chunks. Pillow would add a second dependency to save fifteen lines, and the
adaptive filtering it would bring turned out to make these images *larger*: on
a rendered page the rows are mostly white, which zlib already compresses well,
while a per-row filter adds entropy at every glyph edge. Measured at 1400 px:
48.9 KiB unfiltered against 57.3 KiB with PNG's Up filter.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import pypdfium2

__all__ = ["MAX_EDGE", "RenderedPage", "pdf_pages_as_png"]

# Claude resizes anything larger before it looks at it, so rendering past this
# spends bytes on pixels that get thrown away. 1400 sits under that ceiling
# and still resolves invoice text: an A4 page becomes 990x1400.
MAX_EDGE = 1400

# No page limit by default: a document that is cut off silently is worse than
# a long answer, because the caller cannot tell which half they are looking
# at. A page costs roughly (width * height) / 750 tokens whatever it weighs in
# bytes, so a long document is expensive — `max_pages` is there for a caller
# who knows they only need the front of one.

# Colour rather than grayscale. Grayscale would be a third of the bytes, but an
# image is charged by its dimensions and not by its weight, so the saving is in
# transfer only — and a red overdue stamp on an invoice is information.
_CHANNEL_COLOUR_TYPE = {1: 0, 3: 2, 4: 6}


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """One page of a document, ready to be handed to a client."""

    number: int
    png: bytes
    width: int
    height: int


def pdf_pages_as_png(
    data: bytes, *, max_edge: int = MAX_EDGE, max_pages: int | None = None
) -> tuple[list[RenderedPage], int]:
    """Render a PDF's pages, and say how many it has in total.

    Every page unless ``max_pages`` says otherwise. The total is returned
    either way, so a caller that did limit it can tell what it left behind.

    Raises ``pypdfium2`` errors for a document that cannot be opened, which
    the caller turns into something a person can act on.
    """
    document = pypdfium2.PdfDocument(data)
    try:
        total = len(document)
        wanted = total if max_pages is None else min(total, max_pages)
        pages = []
        for index in range(wanted):
            page = document[index]
            width_pt, height_pt = page.get_size()
            longest = max(width_pt, height_pt) or 1
            bitmap = page.render(scale=max_edge / longest)
            try:
                pages.append(
                    RenderedPage(
                        number=index + 1,
                        png=_png(
                            bytes(bitmap.buffer),
                            bitmap.width,
                            bitmap.height,
                            bitmap.n_channels,
                        ),
                        width=bitmap.width,
                        height=bitmap.height,
                    )
                )
            finally:
                bitmap.close()
        return pages, total
    finally:
        document.close()


def _png(pixels: bytes, width: int, height: int, channels: int) -> bytes:
    """Encode raw pixel rows as a PNG.

    Every row carries filter type 0, which measured smaller than the
    alternatives on rendered pages. See the module docstring.
    """
    colour_type = _CHANNEL_COLOUR_TYPE.get(channels)
    if colour_type is None:
        raise ValueError(f"Cannot encode {channels} channels as PNG.")

    stride = width * channels
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        raw += pixels[row * stride : (row + 1) * stride]

    header = struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def _chunk(tag: bytes, data: bytes) -> bytes:
    """One PNG chunk: length, tag, payload, CRC over tag and payload."""
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )
