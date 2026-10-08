"""Downloading documents and receipts, and uploading receipts.

A download is written to the server's download directory and handed to the
client twice over: as a **path**, which is what a client sharing the machine
wants, and as a **resource link**, which is what everyone else needs. See
:mod:`..resources` for why the bytes are not simply put in the tool result.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult
from pydantic import Field

from ..api.client import ClientProvider
from ..errors import ValidationError
from ..files import delivery, resources, storage
from ..policy import classify
from ..records import formatting
from ..records.types import RESOURCES, Delivered, Download, Format
from ..settings import MAX_PDF_PAGES, Settings
from ._base import DocumentIdField, DocumentTypeField, UploadPath, register_tool

__all__ = ["register"]


MIME: dict[str, str] = {"pdf": "application/pdf", "xml": "application/xml"}


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
                f"Defaults to {default}. Pass null for every page, up to "
                f"{MAX_PDF_PAGES}, and expect roughly two thousand tokens per page."
            ),
            ge=1,
            le=MAX_PDF_PAGES,
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


# A download answers with content blocks as well as data, so its tools return
# a `CallToolResult` and name the model its structured half has to match as
# `Annotated` metadata. The SDK takes the output schema from that model and
# checks the result's structured content against it, so a client sees the
# model's schema and the blocks travel as they were built.
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
    ) -> Annotated[CallToolResult, Download]:
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
        return await delivery.deliver(
            response,
            settings,
            fallback=f"{file_id}.{file_format}",
        )

    @classify("read", "files")
    async def download_document(
        document_type: DocumentTypeField,
        document_id: DocumentIdField,
        file_format: FormatField = "pdf",
    ) -> Annotated[CallToolResult, Download]:
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
        return await delivery.deliver(
            response,
            settings,
            fallback=f"{document_type}-{document_id}.{file_format}",
        )

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
    ) -> Annotated[CallToolResult, Delivered]:
        """Put the contents of a downloaded file into this conversation.

        No API call. Use it when the client cannot open the `path` or follow
        the `uri`, or when the content itself is the answer.

        What arrives depends on the file: XML as **text**, so an XRechnung can
        be read. PDF as **pictures of its pages**, first {pages} unless
        `max_pages` says otherwise — check `pages` against `pagesShown` and
        raise it, or pass null for up to {limit}, if the rest matters. Images
        as images.
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
        pages = MAX_PDF_PAGES if max_pages is None else min(max_pages, MAX_PDF_PAGES)
        # Reading and rendering run in a worker thread. Rendering a long PDF
        # takes seconds of CPU, and on the event loop every other call this
        # server is answering would wait for it.
        return await asyncio.to_thread(delivery.load_inline, uri, settings, pages)

    # The page default is configurable, so both the schema and the description
    # have to state the value this process actually uses rather than a number
    # baked into the source. See `max_pages_field` for why the annotation is
    # attached here instead of written into the signature. `replace` rather
    # than `format`, which would choke on any brace added to the text later.
    # `classify` returns a wrapper, and the schema is built from the function
    # `inspect.signature` arrives at, which follows `__wrapped__` down to the
    # original. Both are set, and by **replacing** the dict rather than editing
    # it: since Python 3.14 (PEP 649) annotations are computed on demand from
    # `__annotate__`, and editing the dict the wrapper materializes leaves the
    # original still answering from its own source text. Assigning a whole dict
    # drops `__annotate__`, so the value below is what every reader sees.
    field = max_pages_field(settings.pdf_pages)
    for fn in (read_download, inspect.unwrap(read_download)):
        fn.__annotations__ = dict(fn.__annotations__) | {"max_pages": field}
    read_download.__doc__ = (
        (read_download.__doc__ or "")
        .replace("{pages}", str(settings.pdf_pages))
        .replace("{limit}", str(MAX_PDF_PAGES))
    )

    @classify("write", "files", "create", permanence="books")
    async def upload_file(
        path: UploadPath,
    ) -> dict[str, Any]:
        """Upload a receipt, which also creates a bookkeeping voucher for it.

        Writes real accounting data, and **the API cannot take it back**:
        the answer carries a `voucherId` as well as a file id, and no call
        here deletes a voucher. Correcting one is a job for the web app.
        Confirm the organization with `get_profile` first. One API call,
        never retried.

        Takes PDF, JPEG, PNG or XML, at most 5 MiB. An XML file is treated as
        an XRechnung. The voucher starts `unchecked`: `update_voucher` fills
        it in, and its `finalize` books it.
        """
        content, name, content_type = await asyncio.to_thread(
            storage.read_upload, path, settings.upload_path
        )
        return formatting.compact_object(
            await provider.get().upload_file(content, name, content_type)
        )

    @classify("write", "files", "create", permanence="books")
    async def attach_file_to_voucher(
        voucher_id: Annotated[
            str,
            Field(
                description=(
                    "The voucher to hang the file on, by id from "
                    "search_vouchers. It has to exist already."
                )
            ),
        ],
        path: UploadPath,
    ) -> dict[str, Any]:
        """Attach a file to a voucher that already exists.

        Use this rather than `upload_file` when the voucher is there: that one
        creates a **new** voucher for every file, and a voucher cannot be
        deleted through the API, so the wrong choice leaves one behind for
        good.

        Writes to the account, and **the API cannot take it back**: there
        is no call that detaches a file. Confirm the organization with
        `get_profile` first. One API call, never retried.

        Takes PDF, JPEG, PNG or XML, at most 5 MiB. The answer is the new file
        id, which `download_file` reads back.
        """
        content, name, content_type = await asyncio.to_thread(
            storage.read_upload, path, settings.upload_path
        )
        return formatting.compact_object(
            await provider.get().attach_file(voucher_id, content, name, content_type)
        )

    register_tool(server, download_file)
    register_tool(server, download_document)
    register_tool(server, read_download)
    register_tool(server, upload_file)
    register_tool(server, attach_file_to_voucher)
