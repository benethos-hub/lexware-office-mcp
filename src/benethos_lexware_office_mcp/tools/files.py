"""Downloading documents and receipts, uploading receipts, and deeplinks.

Downloads are written to the local download directory rather than returned as
bytes. A PDF in a tool result would be base64 in the model's context window,
which is expensive and useless: nothing downstream can read it. A path can be
opened.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .. import storage
from ..client import ClientProvider
from ..config import Settings
from ..errors import ValidationError
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
    ) -> dict[str, Any]:
        """Save a stored file, such as an uploaded receipt, to the download folder.

        Costs one API call. Returns the local path it was written to, the
        content type and the size in bytes. The file itself is not returned:
        a PDF in a tool result is unreadable base64 that only costs context,
        while a path can be opened.

        An existing file is never replaced. A second download of the same
        document is saved alongside the first with a counter in its name.

        Use `download_document` for an invoice or another sales document,
        which is rendered rather than stored.
        """
        response = await provider.get().file(file_id, MIME[file_format])
        return _store(response, settings, fallback=f"{file_id}.{file_format}")

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
    ) -> dict[str, Any]:
        """Save the rendered PDF of an invoice or another sales document.

        Costs one API call. Returns the local path, the content type and the
        size. As with `download_file`, nothing is replaced and the bytes stay
        out of the answer.

        A document is only rendered once it leaves draft, so a draft has
        nothing to download and the API says so. An XRechnung is XML by
        nature and its PDF is a preview, not a valid e-invoice. A ZUGFeRD
        document exists only as a PDF, with the XML inside it.
        """
        response = await provider.get().document_file(
            RESOURCES[document_type], document_id, MIME[file_format]
        )
        return _store(
            response, settings, fallback=f"{document_type}-{document_id}.{file_format}"
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
    if should_register("write", settings.mode):
        register_tool(server, upload_file)


def _store(response: Any, settings: Settings, *, fallback: str) -> dict[str, Any]:
    """Write a downloaded response into the download directory."""
    directory = storage.directory_for(settings)
    name = storage.suggested_name(response, fallback)
    written = storage.save(response.content, name, directory)
    return {
        "path": str(written),
        "mimeType": response.headers.get("content-type", "application/octet-stream"),
        "size": len(response.content),
    }


# Guessed from the extension rather than sniffed. The API validates the
# content anyway and rejects a mislabelled or damaged file, so a second
# opinion here would only be a second way to be wrong.
CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
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
