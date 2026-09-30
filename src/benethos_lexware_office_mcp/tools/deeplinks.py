"""Links into the web app, built from ids the caller already holds.

One tool and no API call. A download says where bytes are, a deeplink says
where a person should click, and the two stay apart so that neither can be
wrong about the other, see SPECS.md section 13.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from ..api.client import ClientProvider
from ..policy import classify
from ..records.types import RESOURCES, LinkTarget
from ..settings import Settings
from ._base import register_tool

__all__ = ["permalink", "register"]

LINK_RESOURCES: dict[str, str] = {
    **RESOURCES,
    "contact": "contacts",
    "voucher": "vouchers",
}


def register(server: MCPServer, settings: Settings, provider: ClientProvider) -> None:
    """Register the deeplink tool. The policy file decides the rest."""

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

        The link is not checked for existence, and a wrong id still produces
        one. Take the id from a search rather than from memory.
        """
        return {"url": permalink(settings, target, target_id, action)}

    register_tool(server, get_deeplink)


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
    # Encoded whole: the id comes from the model, and a slash, `?` or `#` in
    # it would otherwise make a link to some other page of the app.
    return f"{base}/permalink/{resource}/{action}/{quote(target_id, safe='')}"
