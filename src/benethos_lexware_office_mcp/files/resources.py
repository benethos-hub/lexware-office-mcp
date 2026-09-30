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

**The list names the newest downloads only**, ``LXO_MCP_LISTED_DOWNLOADS`` of
them. Nothing deletes a download, so the directory grows with every distinct
document, and the SDK sends the list whole: it does not page. An older file
is not hidden, only unlisted - its link still reads, and so does
``read_download``.

**What this still cannot do** is tell a client that the list has changed.
The SDK derives ``resources.listChanged`` from notification options that
``MCPServer`` does not expose, so it is advertised as ``false`` and no
``notifications/resources/list_changed`` is ever sent. A client that lists
once at startup — Claude Desktop does — sees what was on disk when it
started and nothing downloaded since. That is what ``read_download`` is for.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.mcpserver.exceptions import ResourceError
from mcp.types import Resource, ResourceLink

from . import storage

__all__ = ["GATING_TOOLS", "SCHEME", "link", "listed", "read", "uri_for"]

SCHEME = "lexware://download/"

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


def listed(directory: Path | None, limit: int) -> list[Resource]:
    """The newest ``limit`` downloads in ``directory``, newest first.

    Newest by the file's modification time. Each entry carries its own
    content type, from the name on disk - a PDF and an
    XRechnung are not the same thing to a client deciding what to do with
    them, which is also why this is a list of files rather than one URI
    template, which can declare only one type.

    A symbolic link is skipped. Nothing this server writes is one, so a link
    in the directory was put there by someone else and could point anywhere.
    The directory is not created: a server that has never downloaded anything
    lists nothing.
    """
    if directory is None or limit <= 0 or not directory.is_dir():
        return []
    found: list[tuple[float, str, Path]] = []
    for path in directory.iterdir():
        try:
            if path.is_symlink() or not path.is_file():
                continue
            found.append((path.stat().st_mtime, path.name, path))
        except OSError:
            continue  # gone between listing the directory and looking at it
    found.sort(key=lambda entry: (-entry[0], entry[1]))
    return [
        Resource(
            uri=uri_for(path.name),
            name=path.name,
            title=path.name,
            description=_DESCRIPTION,
            mime_type=_plain(storage.content_type_for(path)),
        )
        for _, _, path in found[:limit]
    ]


def read(directory: Path | None, uri: str) -> list[ReadResourceContents] | None:
    """The bytes behind a download URI, or ``None`` when there is no such file.

    Looked up the way ``read_download`` looks it up, so a link either works in
    both or in neither: the name is checked to stay inside the directory,
    since it arrives from the client.
    """
    if directory is None or not uri.startswith(SCHEME):
        return None
    found = storage.resolve(uri[len(SCHEME) :], directory)
    if found is None:
        return None
    try:
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


def link(path: Path, mime_type: str) -> ResourceLink:
    """A download as the link a tool result carries."""
    return ResourceLink(
        type="resource_link",
        uri=uri_for(path.name),
        name=path.name,
        title=path.name,
        description=_DESCRIPTION,
        mime_type=_plain(mime_type),
        size=path.stat().st_size,
    )


def _plain(mime_type: str) -> str:
    """``application/pdf;charset=UTF-8`` is a PDF. Parameters are not the type."""
    return (mime_type or DEFAULT_TYPE).split(";")[0].strip() or DEFAULT_TYPE
