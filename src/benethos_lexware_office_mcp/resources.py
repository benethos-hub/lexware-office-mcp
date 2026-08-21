"""Downloaded files, published so the client can fetch them.

A path is only useful to a client that shares a filesystem with the server.
Claude Desktop launches the server as a child process and does share one, but
that is a coincidence of the stdio transport rather than something to build
on: the HTTP transport of section 6 puts the server on another machine, and
the path stops meaning anything.

What holds in both cases is that the file is on the **server's** disk and the
server is the one reading it. MCP has exactly that shape — a resource the
client asks for by URI — so every download is registered as one and the tool
result carries a link to it. Nothing is transferred until the client asks,
which is why this is not simply base64 in the tool result: a 2 MiB PDF encodes
to roughly 2.7 MiB of context, spent whether or not anyone wanted the bytes.

**The registry follows the disk, not the process.** Registering only what a
process downloaded looked like caution and was a defect: measured over stdio
on 2026-08-21, a freshly started server answered ``resources/list`` with an
empty list and ``resources/read`` with "Unknown resource" for a file sitting
in its own download directory, which ``read_download`` then read without
trouble. A client is offered the same files either way, so the narrower
registration bought nothing and cost every URI its life at restart.

**What this still cannot do** is tell a client that the list has changed.
The SDK derives ``resources.listChanged`` from notification options that
``MCPServer`` does not expose, so it is advertised as ``false`` and no
``notifications/resources/list_changed`` is ever sent. A client that lists
once at startup — Claude Desktop does — sees what was on disk when it
started and nothing downloaded since. That is what ``read_download`` is for.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.resources import FunctionResource
from mcp.types import ResourceLink

from . import storage

__all__ = ["SCHEME", "publish", "publish_existing", "uri_for"]

SCHEME = "lexware://download/"

DEFAULT_TYPE = "application/octet-stream"


def uri_for(name: str) -> str:
    """The URI a downloaded file is published under."""
    return f"{SCHEME}{name}"


def publish_existing(server: MCPServer, directory: Path) -> int:
    """Register everything already in ``directory``, and say how many.

    Called once as the server is built, so a URI handed out by an earlier run
    still resolves. The directory is not created here: a server that has never
    downloaded anything has nothing to publish, and building one to list its
    tools should not leave a directory behind.
    """
    if not directory.is_dir():
        return 0
    count = 0
    for path in sorted(directory.iterdir()):
        if path.is_file():
            publish(server, path, storage.content_type_for(path))
            count += 1
    return count


def publish(server: MCPServer, path: Path, mime_type: str) -> ResourceLink:
    """Register a downloaded file as a resource and describe it as a link.

    Registration is per file rather than through one URI template, so that
    each entry carries its own content type — a template can only declare one,
    and a PDF and an XRechnung are not the same thing to a client deciding
    what to do with them.
    """
    kind = _plain(mime_type)
    uri = uri_for(path.name)
    size = path.stat().st_size

    server.add_resource(
        FunctionResource(
            uri=uri,
            name=path.name,
            title=path.name,
            description="Downloaded from Lexware Office by this server.",
            mime_type=kind,
            fn=lambda: path.read_bytes(),
        )
    )
    return ResourceLink(
        type="resource_link",
        uri=uri,
        name=path.name,
        title=path.name,
        description="Downloaded from Lexware Office by this server.",
        mime_type=kind,
        size=size,
    )


def _plain(mime_type: str) -> str:
    """``application/pdf;charset=UTF-8`` is a PDF. Parameters are not the type."""
    return (mime_type or DEFAULT_TYPE).split(";")[0].strip() or DEFAULT_TYPE
