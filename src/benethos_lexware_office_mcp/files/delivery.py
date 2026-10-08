"""A downloaded file as content a client can use.

Four shapes, because the same bytes are worth different things: text a model
can read, an image it can see, a PDF turned into pictures of its pages so
that it can be seen at all, and a blob only the client can do anything with.
``read_download`` decides *whether* a file goes into the answer and how many
pages of it, this module decides *how* it goes in.

A download that stays on disk is an answer too, built by :func:`saved`: a
line to read and a link to follow, both naming the same file. :func:`deliver`
saves one and answers with it, :func:`load_inline` reads one back for
``read_download`` - the disk and the answer together, so the tools that
offer them stay thin.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import httpx
from mcp.types import (
    BlobResourceContents,
    CallToolResult,
    ContentBlock,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
)

from ..errors import NotFoundError, ValidationError
from ..settings import Settings
from . import rendering, resources, storage

__all__ = ["deliver", "inline", "load_inline", "saved"]

# Base64 costs roughly 1.37 times the file size in the answer, so this is a
# ceiling on damage rather than a working size. It is the same 5 MiB the API
# accepts for an upload, so there is one number to remember.
MAX_INLINE = 5 * 1024 * 1024

# Types a model can actually read. XML is the one that matters: an XRechnung
# is an invoice in text form.
TEXT_TYPES = ("application/xml", "text/xml", "application/json")


async def deliver(
    response: httpx.Response, settings: Settings, *, fallback: str
) -> CallToolResult:
    """Save a download and hand it to the client both ways."""
    name = storage.suggested_name(response, fallback)
    with storage.on_disk("save the download"):
        written = await asyncio.to_thread(_save, response.content, name, settings)
        mime = response.headers.get("content-type", resources.DEFAULT_TYPE)
        link = resources.link(written, mime)
    return saved(written, link, len(response.content))


def _save(content: bytes, name: str, settings: Settings) -> Path:
    """Write a download to disk, then keep the directory at its bound.

    Blocking, run in a thread. The file just written is the newest, so the
    clean-up that follows never takes it.
    """
    written = storage.save(content, name, storage.directory_for(settings))
    storage.prune_for(settings)
    return written


def load_inline(uri: str, settings: Settings, max_pages: int) -> CallToolResult:
    """Find a download, read it and build the answer. Blocking, run in a thread."""
    with storage.on_disk("read the download"):
        found = storage.resolve(
            uri[len(resources.SCHEME) :], storage.directory_for(settings)
        )
        if found is None:
            raise NotFoundError(
                "download", uri, hint=resources.gone(settings.downloads_kept())
            )
        payload = found.read_bytes()
    mime = storage.content_type_for(found)
    if len(payload) > MAX_INLINE:
        raise ValidationError(
            f"{uri} is {len(payload) / 1024 / 1024:.1f} MiB, too much to "
            "put in an answer. It is on disk already, so use the path the "
            "download reported."
        )
    return inline(uri, payload, mime, max_pages)


def saved(written: Path, link: ResourceLink, size: int) -> CallToolResult:
    """The answer to a download: where the file is, and the link to it.

    The structured half is what a model reads, the resource link is what a
    client acts on. Both name the same file, so neither has to be guessed at
    from the other.
    """
    summary = (
        f"Saved {written.name} ({size} bytes). Readable as the resource {link.uri}."
    )
    return CallToolResult(
        content=[TextContent(type="text", text=summary), link],
        structured_content={
            "path": str(written),
            "uri": link.uri,
            "mimeType": link.mime_type,
            "size": size,
        },
    )


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
        # Its messages end in a full stop of their own.
        reason = str(exc).rstrip(".")
        raise ValidationError(
            f"{uri} could not be rendered: {reason}. It may be encrypted or "
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
