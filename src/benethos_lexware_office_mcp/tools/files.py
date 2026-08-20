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
from ..policy import requires, should_register
from ._base import register_tool

__all__ = ["register"]

# The seven sales document types, and the path segment each one lives under.
# The segments are plural and kebab-cased, which is also what the web app's
# permalinks use.
DocumentType = Literal[
    "invoice",
    "quotation",
    "credit-note",
    "order-confirmation",
    "delivery-note",
    "dunning",
    "down-payment-invoice",
]

RESOURCES: dict[str, str] = {
    "invoice": "invoices",
    "quotation": "quotations",
    "credit-note": "credit-notes",
    "order-confirmation": "order-confirmations",
    "delivery-note": "delivery-notes",
    "dunning": "dunnings",
    "down-payment-invoice": "down-payment-invoices",
}

# Deeplinks reach further than documents do.
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
    "file",
]

LINK_RESOURCES: dict[str, str] = {
    **RESOURCES,
    "contact": "contacts",
    "voucher": "vouchers",
    "file": "files",
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
    """Register the file tools allowed at the active permission tier."""

    @requires("read")
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
        """Save a stored file, such as an uploaded receipt, and hand it over.

        Costs one API call. The file is written to the server's download
        directory and reported two ways: a `path`, which is usable when the
        client runs on the same machine as this server, and a `uri` under
        which the same bytes can be fetched with a resource read, which works
        whatever machine the server is on. The bytes themselves are not put in
        the result, because that is base64 nothing can read and everything
        pays for.

        An existing file is never replaced. A second download of the same
        document is saved alongside the first with a counter in its name.

        Use `download_document` for an invoice or another sales document,
        which is rendered rather than stored.
        """
        response = await provider.get().file(file_id, MIME[file_format])
        return _deliver(response, server, settings, fallback=f"{file_id}.{file_format}")

    @requires("read")
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

        Costs one API call. Reports a `path` and a `uri` exactly as
        `download_file` does, and as there, nothing is overwritten and the
        bytes stay out of the answer.

        A document is only rendered once it leaves draft, so a draft has
        nothing to download and the API says so. An XRechnung is XML by
        nature and its PDF is a preview, not a valid e-invoice. A ZUGFeRD
        document exists only as a PDF, with the XML inside it.
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

    @requires("read")
    async def get_deeplink(
        target: Annotated[
            LinkTarget,
            Field(description="What the link should point at."),
        ],
        target_id: Annotated[str, Field(description="The Lexware id of that record.")],
        action: Annotated[
            Literal["view", "edit"],
            Field(
                description=(
                    "Whether to open the record or open it for editing. A "
                    "record that cannot be edited opens for viewing instead. "
                    "Ignored for a file, which has only one link."
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
        base = settings.app_base_url.rstrip("/")
        resource = LINK_RESOURCES[target]
        if target == "file":
            return {"url": f"{base}/permalink/{resource}/{target_id}"}
        return {"url": f"{base}/permalink/{resource}/{action}/{target_id}"}

    @requires("read")
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
    ) -> Delivered:
        """Put the contents of a downloaded file into this conversation.

        Costs **no** API call: the file is already on the server. Use this
        when the client cannot follow the resource link a download returned,
        or when the content itself is the answer.

        What comes back depends on what the file is, because the useful form
        differs. **XML arrives as text**, which is the case worth knowing
        about: an XRechnung becomes readable, so its amounts and dates can
        actually be used. **A PDF arrives as pictures of its pages**, since a
        PDF itself cannot be displayed by every client. An image arrives as an
        image. Anything else arrives as an embedded binary for the client to
        handle.

        A long PDF is cut off after the first few pages, and the result says
        how many pages it has and how many were shown. Prefer the `path` or
        the resource `uri` when the client can use them directly.
        """
        if not uri.startswith(resources.SCHEME):
            raise ValidationError(
                f"{uri!r} is not a download from this server. Pass the `uri` "
                f"a download reported, which starts with {resources.SCHEME}."
            )
        # Resolved from disk rather than from the resource registry, which
        # only knows what this process downloaded. The file outlives the
        # process, so a link handed out before a restart still works.
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
        return _inline(uri, payload, mime)

    @requires("write")
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
        """Upload a receipt and let Lexware create the voucher for it.

        Writes to real accounting data, and does more than the name suggests:
        the API answers with both a file id and a **new bookkeeping voucher**
        built around it. Confirm with `get_profile` which organization is
        connected before calling this, and expect a voucher to appear that
        nobody explicitly asked for. It cannot be deleted through the API.

        Costs one API call, which is never retried, because a repeated upload
        is a second voucher for the same receipt.

        PDFs and images are accepted, plain text is not, and the limit is 5
        MiB. A file that is too large is refused here before a request is
        spent on it.
        """
        content, name, content_type = _read_upload(path)
        return dict(await provider.get().upload_file(content, name, content_type))

    if should_register("read", settings.mode):
        register_tool(server, download_file)
        register_tool(server, download_document)
        register_tool(server, get_deeplink)
        register_tool(server, read_download)
    if should_register("write", settings.mode):
        register_tool(server, upload_file)


def _inline(uri: str, payload: bytes, mime: str) -> Any:
    """Choose the content block that makes this file usable.

    Four shapes, because the same bytes are worth different things: text a
    model can read, an image it can see, a PDF turned into pictures of its
    pages so that it can be seen at all, and a blob only the client can do
    anything with.
    """
    summary = {"uri": uri, "mimeType": mime, "size": len(payload)}

    if mime == "application/pdf":
        return _rendered(uri, payload, summary)

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


def _rendered(uri: str, payload: bytes, summary: dict[str, Any]) -> Any:
    """A PDF as pictures of its pages."""
    try:
        pages, total = rendering.pdf_pages_as_png(payload)
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
                f"{total} page{'s' if total != 1 else ''}, showing "
                f"{len(pages)} as images."
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
    response: Any, server: MCPServer, settings: Settings, *, fallback: str
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
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=(
                    f"Saved {written.name} ({len(response.content)} bytes). "
                    f"Readable as the resource {link.uri}."
                ),
            ),
            link,
        ],
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
