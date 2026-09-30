"""A downloaded file as content a client can use.

Four shapes, because the same bytes are worth different things: text a model
can read, an image it can see, a PDF turned into pictures of its pages so
that it can be seen at all, and a blob only the client can do anything with.
``read_download`` decides *whether* a file goes into the answer and how many
pages of it, this module decides *how* it goes in.
"""

from __future__ import annotations

import base64
from typing import Any

from mcp.types import (
    BlobResourceContents,
    CallToolResult,
    ContentBlock,
    EmbeddedResource,
    ImageContent,
    TextContent,
)

from ..errors import ValidationError
from . import rendering

__all__ = ["TEXT_TYPES", "inline"]

# Types a model can actually read. XML is the one that matters: an XRechnung
# is an invoice in text form.
TEXT_TYPES = ("application/xml", "text/xml", "application/json")


def inline(
    uri: str, payload: bytes, mime: str, max_pages: int | None = None
) -> CallToolResult:
    """The content block that makes this file usable, by its type."""
    summary = {"uri": uri, "mimeType": mime, "size": len(payload)}

    if mime == "application/pdf":
        return _rendered(uri, payload, summary, max_pages)

    if mime.startswith("text/") or mime in TEXT_TYPES:
        text = payload.decode("utf-8", errors="replace")
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content={**summary, "deliveredAs": "text"},
        )

    encoded = base64.b64encode(payload).decode("ascii")
    if mime.startswith("image/"):
        return CallToolResult(
            content=[ImageContent(type="image", data=encoded, mime_type=mime)],
            structured_content={**summary, "deliveredAs": "image"},
        )

    return CallToolResult(
        content=[
            EmbeddedResource(
                type="resource",
                resource=BlobResourceContents(uri=uri, mime_type=mime, blob=encoded),
            )
        ],
        structured_content={**summary, "deliveredAs": "binary"},
    )


def _rendered(
    uri: str, payload: bytes, summary: dict[str, Any], max_pages: int | None
) -> CallToolResult:
    """A PDF as pictures of its pages."""
    try:
        pages, total = rendering.pdf_pages_as_png(payload, max_pages=max_pages)
    except Exception as exc:  # pypdfium2 raises its own errors
        raise ValidationError(
            f"{uri} could not be rendered: {exc}. It may be encrypted or "
            "damaged. The file itself is on disk either way."
        ) from exc

    if not pages:
        raise ValidationError(f"{uri} has no pages to show.")

    blocks: list[ContentBlock] = [
        TextContent(
            type="text",
            text=(
                f"{total} page{'s' if total != 1 else ''}, all rendered."
                if len(pages) == total
                else f"{total} pages, showing the first {len(pages)}."
            ),
        )
    ]
    blocks += [
        ImageContent(
            type="image",
            data=base64.b64encode(page.png).decode("ascii"),
            mime_type="image/png",
        )
        for page in pages
    ]
    return CallToolResult(
        content=blocks,
        structured_content={
            **summary,
            "deliveredAs": "pages",
            "pages": total,
            "pagesShown": len(pages),
        },
    )
