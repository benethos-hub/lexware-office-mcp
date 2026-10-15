"""Downloaded files, offered as MCP resources so the client can fetch them.

A path is only useful to a client that shares a filesystem with the server.
Claude Desktop launches the server as a child process and does share one, but
that is a coincidence of the stdio transport rather than something to build
on: the HTTP transport of section 6 puts the server on another machine, and
the path stops meaning anything.

What holds in both cases is that the file is on the **server's** disk and the
server is the one reading it. MCP has exactly that shape — a resource the
client asks for by URI — so every download is offered as one and the tool
result carries a link to it. Nothing is transferred until the client asks,
which is why this is not simply base64 in the tool result: a 2 MiB PDF encodes
to roughly 2.7 MiB of context, spent whether or not anyone wanted the bytes.

**Answered from the disk, at the moment it is asked.** ``resources/list``
and ``resources/read`` both look at the download directory rather than at a
registry. A file that is there is readable under its link whatever process
wrote it, one that is gone is gone from the list at once, and a server start
reads nothing. Registering only what a process downloaded was a defect once
already: measured over stdio on 2026-08-21, a fresh server answered "Unknown
resource" for a file in its own directory that ``read_download`` read in the
same breath. Registering everything at startup fixed that, and cost a start
that read the whole directory and a registry that only grew.

**The list names the newest downloads only**, ``LXO_MCP_KEPT_DOWNLOADS`` of
them, because the SDK sends it whole: it does not page. Where the directory
is cleaned to the same number, which is the cache directory by default, the
list is the directory. Where it is not, an older file is only unlisted - its
link still reads, and so does ``read_download``.

**What this does not do** is tell a client that the list has changed.
``PolicyServer`` binds the notification options itself and announces
``tools.listChanged`` with them, but not ``resources.listChanged``, and no
``notifications/resources/list_changed`` is sent after a download. A client
that lists once at startup — Claude Desktop does — sees what was on disk
when it started and nothing downloaded since. That is what
``read_download`` is for.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.mcpserver.exceptions import ResourceError
from mcp.types import Resource, ResourceLink

from . import storage

__all__ = [
    "GATING_TOOLS",
    "MAX_INLINE",
    "SCHEME",
    "gone",
    "link",
    "listed",
    "name_of",
    "read",
    "too_large",
]

SCHEME = "lexware://download/"

# Base64 costs roughly 1.37 times the file size in the answer, so this is a
# ceiling on damage rather than a working size. It is the same 5 MiB the API
# accepts for an upload, so there is one number to remember. It bounds both
# ways a download's bytes reach a client: `read_download` and a resource read.
MAX_INLINE = 5 * 1024 * 1024

# The tools a download resource belongs to. A resource is a way of handing out
# a file one of them produced, so it is reachable exactly while at least one of
# them is enabled - never as a side door that outlives the policy switching
# them all off.
GATING_TOOLS = ("download_file", "download_document", "read_download")

DEFAULT_TYPE = "application/octet-stream"

_DESCRIPTION = "Downloaded from Lexware Office by this server."


def uri_for(name: str) -> str:
    """The URI a downloaded file is offered under."""
    return f"{SCHEME}{name}"


def name_of(uri: str) -> str | None:
    """The file name a download URI carries, or ``None`` when it is none.

    Only the scheme is taken off. Whether the name stays inside the
    directory is ``storage.resolve``'s to check, since it arrives from the
    client.
    """
    return uri[len(SCHEME) :] if uri.startswith(SCHEME) else None


def listed(directory: Path | None, limit: int) -> list[Resource]:
    """The newest ``limit`` downloads in ``directory``, newest first.

    Newest by the file's modification time, which a reused download renews,
    so the list is the files fetched most recently. Each entry carries its own
    content type, from the name on disk - a PDF and an
    XRechnung are not the same thing to a client deciding what to do with
    them, which is also why this is a list of files rather than one URI
    template, which can declare only one type - and its size, for a client
    weighing a read. No ``title``: it would repeat ``name``, which is what a
    client shows when there is none, and the list is sent whole.

    A symbolic link is skipped. Nothing this server writes is one, so a link
    in the directory was put there by someone else and could point anywhere.
    The directory is not created: a server that has never downloaded anything
    lists nothing.
    """
    if directory is None or limit <= 0 or not directory.is_dir():
        return []
    return [
        Resource(
            uri=uri_for(path.name),
            name=path.name,
            description=_DESCRIPTION,
            mime_type=_plain(storage.content_type_for(path)),
            size=_size(path),
        )
        for path in storage.newest(directory)[:limit]
    ]


def _size(path: Path) -> int | None:
    """The file's size, or nothing for a file that went since it was listed."""
    try:
        return path.stat().st_size
    except OSError:
        return None


def read(directory: Path | None, uri: str) -> list[ReadResourceContents] | None:
    """The bytes behind a download URI, or ``None`` when there is no such file.

    Looked up the way ``read_download`` looks it up, so a link either works in
    both or in neither: the name is checked to stay inside the directory,
    since it arrives from the client.
    """
    name = name_of(uri)
    if directory is None or name is None:
        return None
    found = storage.resolve(name, directory)
    if found is None:
        return None
    try:
        size = found.stat().st_size
        if size > MAX_INLINE:
            raise ResourceError(too_large(uri, size))
        content = found.read_bytes()
    except OSError as exc:
        # The reason and never the path, as everywhere a local file fails.
        raise ResourceError(
            f"{found.name} could not be read: {exc.strerror or 'the system refused'}."
        ) from None
    return [
        ReadResourceContents(
            content=content, mime_type=_plain(storage.content_type_for(found))
        )
    ]


def too_large(uri: str, size: int) -> str:
    """Why a download is not put in an answer whole, and where it is instead."""
    return (
        f"{uri} is {size / 1024 / 1024:.1f} MiB, too much to put in an answer. "
        "It is on disk already, so use the path the download reported."
    )


def gone(kept: int | None) -> str:
    """What to do about a download that is not on disk.

    The likeliest reason is the bound the directory is kept at, and the remedy
    is the same whatever the reason: the document is still in Lexware Office.
    No path, as everywhere a caller is told about a local file.
    """
    if kept is None:
        return "Download the document again."
    return (
        f"This server keeps the newest {kept} downloads, so it may have been "
        "removed. Download the document again."
    )


def link(path: Path, mime_type: str) -> ResourceLink:
    """A download as the link a tool result carries."""
    return ResourceLink(
        type="resource_link",
        uri=uri_for(path.name),
        name=path.name,
        description=_DESCRIPTION,
        mime_type=_plain(mime_type),
        size=path.stat().st_size,
    )


def _plain(mime_type: str) -> str:
    """``application/pdf;charset=UTF-8`` is a PDF. Parameters are not the type."""
    return (mime_type or DEFAULT_TYPE).split(";")[0].strip() or DEFAULT_TYPE
