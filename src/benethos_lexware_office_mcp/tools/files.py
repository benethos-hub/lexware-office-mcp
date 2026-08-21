"""Downloading documents and receipts, uploading receipts, and deeplinks.

A download is written to the server's download directory and handed to the
client twice over: as a **path**, which is what a client sharing the machine
wants, and as a **resource link**, which is what everyone else needs. See
:mod:`..resources` for why the bytes are not simply put in the tool result.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import (
    BlobResourceContents,
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    TextContent,
)
from pydantic import BaseModel, Field

from .. import rendering, resources, storage
from ..client import ClientProvider
from ..config import Settings
from ..errors import NotFoundError, ValidationError
from ..policy import classify
from ._base import register_tool
from .sales_documents import RESOURCES, DocumentType

__all__ = ["register"]

# Deeplinks reach further than documents do, but not to a stored file:
# the web app has no page for one. Verified 2026-08-21, see SPECS.md
# section 5.
LinkTarget = Literal[
    "invoice",
    "quotation",
    "credit-note",
    "order-confirmation",
    "delivery-note",
    "dunning",
    "down-payment-invoice",
    "contact",
    "voucher",
]

LINK_RESOURCES: dict[str, str] = {
    **RESOURCES,
    "contact": "contacts",
    "voucher": "vouchers",
}


class Download(BaseModel):
    """What a download reports back.

    Declared as a model rather than a bare dict so the schema the client sees
    says what the fields are. `path` and `uri` name the same file: the path is
    usable when the client shares a machine with the server, the URI when it
    does not.
    """

    path: str = Field(description="Where the file was written on the server.")
    uri: str = Field(
        description=(
            "Resource URI for the same file. Read it to get the bytes, "
            "wherever the server runs."
        )
    )
    mimeType: str = Field(description="The file's content type.")
    size: int = Field(description="Size in bytes.")
    # No deeplink. A download reports where the bytes are, and a link into
    # the web app is `get_deeplink`'s answer to a different question. Keeping
    # them apart is what stops one from being wrong about the other, see
    # SPECS.md section 13.


class Delivered(BaseModel):
    """What `read_download` reports alongside the content it delivers."""

    uri: str = Field(description="The download that was read.")
    mimeType: str = Field(description="The file's content type.")
    size: int = Field(description="Size in bytes.")
    deliveredAs: str = Field(
        description=(
            "How the content was put into the answer: 'text' for something "
            "readable such as an XRechnung, 'image' for a picture, 'pages' "
            "for a PDF rendered to images, or 'binary' for anything the "
            "client has to handle itself."
        )
    )
    pages: int | None = Field(
        None, description="How many pages the document has, for a PDF."
    )
    pagesShown: int | None = Field(
        None, description="How many of them were rendered into this answer."
    )


# Base64 costs roughly 1.37 times the file size in the answer, so this is a
# ceiling on damage rather than a working size. It is the same 5 MiB the API
# accepts for an upload, so there is one number to remember.
MAX_INLINE = 5 * 1024 * 1024

# Types a model can actually read. XML is the one that matters: an XRechnung
# is an invoice in text form.
TEXT_TYPES = ("application/xml", "text/xml", "application/json")

Format = Literal["pdf", "xml"]

MIME: dict[str, str] = {"pdf": "application/pdf", "xml": "application/xml"}

# Verified 2026-08-20: 5 MiB exactly is still accepted, one byte more is
# refused with `max_file_size_exceeded`. Checked here so a caller finds out
# before spending a request on it.
MAX_UPLOAD = 5 * 1024 * 1024


def max_pages_field(default: int) -> Any:
    """The `max_pages` annotation, carrying the default this process uses.

    Built here rather than written into the signature because
    ``from __future__ import annotations`` turns every annotation into its own
    source text, which the MCP SDK later evaluates in **module** scope. An
    f-string over the per-process settings would name a local that does not
    exist there. Assigning the finished object to ``__annotations__`` after
    the definition sidesteps that: the SDK evaluates strings and leaves real
    objects alone.
    """
    return Annotated[
        int | None,
        Field(
            description=(
                "For a PDF, how many pages to render from the front. "
                f"Defaults to {default}. Pass null for every page, and expect "
                "roughly two thousand tokens per page."
            ),
            ge=1,
        ),
    ]


FormatField = Annotated[
    Format,
    Field(
        description=(
            "Which representation to fetch. 'pdf' is what almost everything "
            "has. 'xml' only exists for an XRechnung, and asking for it "
            "otherwise is a not-found."
        )
    ),
]


def register(server: MCPServer, settings: Settings, provider: ClientProvider) -> None:
    """Register the file tools. The policy file decides the rest."""

    @classify("read", "files")
    async def download_file(
        file_id: Annotated[
            str,
            Field(
                description=(
                    "The file's Lexware id. A bookkeeping voucher lists the "
                    "ids of its attachments in its `files` field."
                )
            ),
        ],
        file_format: FormatField = "pdf",
    ) -> Download:
        """Save a stored file, such as an uploaded receipt. One API call.

        The bytes are not in this answer. Two ways to reach them:

        - `path` — the file on the server's disk. Works if the client runs on
          that machine.
        - `uri` — pass it to `read_download` to put the content in the
          conversation, or read it as a resource.

        For a link a person can click, call `get_deeplink` with the voucher
        that lists this file. The web app has no page for the file itself.

        Use `download_document` for a sales document, which is rendered
        rather than stored.
        """
        response = await provider.get().file(file_id, MIME[file_format])
        return _deliver(
            response,
            server,
            settings,
            fallback=f"{file_id}.{file_format}",
        )

    @classify("read", "files")
    async def download_document(
        document_type: Annotated[
            DocumentType,
            Field(description="Which kind of sales document this is."),
        ],
        document_id: Annotated[
            str,
            Field(
                description=(
                    "The document's Lexware id, as returned by search_vouchers."
                )
            ),
        ],
        file_format: FormatField = "pdf",
    ) -> Download:
        """Save the rendered PDF of an invoice or another sales document.

        One API call. Reports `path` and `uri` and keeps the bytes out of the
        answer, exactly as `download_file` does. For a link a person can
        click, call `get_deeplink` with the same id.

        A draft has not been rendered and cannot be downloaded. An XRechnung
        is XML by nature and its PDF is only a preview. A ZUGFeRD document is
        a PDF with the XML inside it.
        """
        response = await provider.get().document_file(
            RESOURCES[document_type], document_id, MIME[file_format]
        )
        return _deliver(
            response,
            server,
            settings,
            fallback=f"{document_type}-{document_id}.{file_format}",
        )

    @classify("read", "files")
    async def get_deeplink(
        target: Annotated[
            LinkTarget,
            Field(description="What the link should point at."),
        ],
        target_id: Annotated[
            str,
            Field(
                description=(
                    "The Lexware id of a record of that exact type. A file id "
                    "is not the id of the voucher it hangs on, and the "
                    "mismatch still builds a link — one that leads nowhere."
                )
            ),
        ],
        action: Annotated[
            Literal["view", "edit"],
            Field(
                description=(
                    "Whether to open the record or open it for editing. A "
                    "contact has a single page and always opens on it."
                )
            ),
        ] = "view",
    ) -> dict[str, Any]:
        """Build a link that opens a record in the Lexware Office web app.

        Costs **no** API call: the link is assembled from ids you already
        have. Use it whenever a person should look at something themselves,
        rather than describing where to click.

        The link is not checked for existence. An id that does not exist opens
        the list of that record type instead of an error.
        """
        return {"url": permalink(settings, target, target_id, action)}

    @classify("read", "files")
    async def read_download(
        uri: Annotated[
            str,
            Field(
                description=(
                    "The `uri` a download reported, of the form "
                    "lexware://download/... Only files this server downloaded "
                    "can be read."
                )
            ),
        ],
        max_pages: int | None = settings.pdf_pages,
    ) -> Delivered:
        """Put the contents of a downloaded file into this conversation.

        No API call. Use it when the client cannot open the `path` or follow
        the `uri`, or when the content itself is the answer.

        What arrives depends on the file: XML as **text**, so an XRechnung can
        be read. PDF as **pictures of its pages**, first {pages} unless
        `max_pages` says otherwise — check `pages` against `pagesShown` and
        raise it, or pass null, if the rest matters. Images as images.
        Anything else as an embedded binary.
        """
        if not uri.startswith(resources.SCHEME):
            raise ValidationError(
                f"{uri!r} is not a download from this server. Pass the `uri` "
                f"a download reported, which starts with {resources.SCHEME}."
            )
        # Resolved from disk at call time, which is what kept this tool
        # working while `resources/read` was still answering from a registry
        # that only knew the running process. The registry follows the disk
        # now too, and this stays the direct route: no list to consult, no
        # client feature to depend on.
        found = storage.resolve(
            uri[len(resources.SCHEME) :], storage.directory_for(settings)
        )
        if found is None:
            raise NotFoundError("download", uri)

        payload = found.read_bytes()
        mime = storage.content_type_for(found)
        if len(payload) > MAX_INLINE:
            raise ValidationError(
                f"{uri} is {len(payload) / 1024 / 1024:.1f} MiB, too much to "
                "put in an answer. It is on disk already, so use the path the "
                "download reported."
            )
        return _inline(uri, payload, mime, max_pages)

    # The page default is configurable, so both the schema and the description
    # have to state the value this process actually uses rather than a number
    # baked into the source. See `max_pages_field` for why the annotation is
    # attached here instead of written into the signature. `replace` rather
    # than `format`, which would choke on any brace added to the text later.
    read_download.__annotations__["max_pages"] = max_pages_field(settings.pdf_pages)
    read_download.__doc__ = (read_download.__doc__ or "").replace(
        "{pages}", str(settings.pdf_pages)
    )

    @classify("write", "files", "create")
    async def upload_file(
        path: Annotated[
            str,
            Field(
                description=(
                    "Path to the file on this machine, for example a scanned "
                    "receipt. PDFs and images are accepted, at most 5 MiB."
                )
            ),
        ],
    ) -> dict[str, Any]:
        """Upload a receipt, which also creates a bookkeeping voucher for it.

        Writes real accounting data and **cannot be undone**: the answer
        carries a `voucherId` as well as a file id, and that voucher cannot be
        deleted through the API. Confirm the organization with `get_profile`
        first. One API call, never retried.

        Takes PDF, JPEG, PNG or XML, at most 5 MiB. An XML file is treated as
        an XRechnung.
        """
        content, name, content_type = _read_upload(path)
        return dict(await provider.get().upload_file(content, name, content_type))

    register_tool(server, download_file)
    register_tool(server, download_document)
    register_tool(server, get_deeplink)
    register_tool(server, read_download)
    register_tool(server, upload_file)


def permalink(
    settings: Settings, target: str, target_id: str, action: str = "view"
) -> str:
    """A link into the web app for one record.

    Assembled from ids the caller already holds, so it costs no API call.
    Only ``get_deeplink`` calls this: a download says where bytes are, and
    that is a different question from where a person should click.

    Every shape here was requested against the live app on 2026-08-21 rather
    than taken from the documentation, which is where the two known corners
    come from: a contact answers only to ``view``, and a stored file has no
    permalink at all and so is not a target.
    """
    base = settings.app_base_url.rstrip("/")
    resource = LINK_RESOURCES[target]
    if target == "contact":
        action = "view"
    return f"{base}/permalink/{resource}/{action}/{target_id}"


def _inline(uri: str, payload: bytes, mime: str, max_pages: int | None = None) -> Any:
    """Choose the content block that makes this file usable.

    Four shapes, because the same bytes are worth different things: text a
    model can read, an image it can see, a PDF turned into pictures of its
    pages so that it can be seen at all, and a blob only the client can do
    anything with.
    """
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
) -> Any:
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

    blocks: list[Any] = [
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


def _deliver(
    response: Any,
    server: MCPServer,
    settings: Settings,
    *,
    fallback: str,
) -> Any:
    """Save a download and hand it to the client both ways.

    The structured half is what a model reads, the resource link is what a
    client acts on. Both name the same file, so neither has to be guessed at
    from the other.

    Returns a ``CallToolResult`` while the tools that call it declare
    :class:`Download`. That is deliberate: the SDK derives the output schema
    from the annotation and passes a ``CallToolResult`` through unchanged once
    its structured content validates against that schema, so declaring the
    payload buys a real schema without giving up the content blocks.
    """
    directory = storage.directory_for(settings)
    name = storage.suggested_name(response, fallback)
    written = storage.save(response.content, name, directory)
    mime = response.headers.get("content-type", resources.DEFAULT_TYPE)
    link = resources.publish(server, written, mime)

    payload = {
        "path": str(written),
        "uri": link.uri,
        "mimeType": link.mime_type,
        "size": len(response.content),
    }
    summary = (
        f"Saved {written.name} ({len(response.content)} bytes). "
        f"Readable as the resource {link.uri}."
    )
    return CallToolResult(
        content=[TextContent(type="text", text=summary), link],
        structured_content=payload,
    )


# Exactly what the API takes, measured on 2026-08-20 rather than assumed:
# `.gif` is refused with `inacceptable_file_extension`, and `.xml` is accepted
# and parsed as an XRechnung — a file that is not one comes back as
# `invalid_xrechnung`. The web app states the same four types.
#
# The type is guessed from the extension rather than sniffed. The API
# validates the content anyway and rejects a mislabelled or damaged file, so a
# second opinion here would only be a second way to be wrong.
CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".xml": "application/xml",
}


def _read_upload(raw_path: str) -> tuple[bytes, str, str]:
    """Read a local file for upload, refusing what the API would refuse."""
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise ValidationError(
            f"No file at {raw_path}. Give the path to an existing receipt."
        )

    size = path.stat().st_size
    if size > MAX_UPLOAD:
        raise ValidationError(
            f"{path.name} is {size / 1024 / 1024:.1f} MiB. The API accepts at "
            "most 5 MiB, so this was not sent."
        )

    content_type = CONTENT_TYPES.get(path.suffix.lower())
    if content_type is None:
        accepted = ", ".join(sorted(CONTENT_TYPES))
        found = path.suffix or "no extension"
        raise ValidationError(f"The API does not accept {found}. It takes: {accepted}.")
    return path.read_bytes(), path.name, content_type
