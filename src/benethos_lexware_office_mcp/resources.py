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
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.resources import FunctionResource
from mcp.types import ResourceLink

__all__ = ["SCHEME", "publish", "uri_for"]

SCHEME = "lexware://download/"

DEFAULT_TYPE = "application/octet-stream"


def uri_for(name: str) -> str:
    """The URI a downloaded file is published under."""
    return f"{SCHEME}{name}"


def publish(server: MCPServer, path: Path, mime_type: str) -> ResourceLink:
    """Register a downloaded file as a resource and describe it as a link.

    Registration is per file rather than through one URI template, so that
    each entry carries its own content type — a template can only declare one,
    and a PDF and an XRechnung are not the same thing to a client deciding
    what to do with them. It also means only what this process actually
    downloaded is reachable, rather than every file that has ever accumulated
    in the download directory.
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
