"""Carrying saved permission profiles to another installation.

One JSON file, and **profiles are all it holds**. Not the settings, not the
policy file, and not the API key.

That is narrower than it first was, deliberately. A bundle carrying the whole
configuration turned out to be carrying the wrong things: `LXO_MCP_TOOL_POLICY`
and `LXO_MCP_DOWNLOAD_DIR` are absolute paths describing one machine, and an
import that wrote the first of them would point the target installation at a
policy file that does not exist there - which means no tools at all, right
after an import that appeared to grant some. A profile has none of that
problem: it is a list of tool names, and a tool name means the same thing
everywhere.

**Importing profiles changes no permission.** It adds to the list this
installation can choose from, and `tools.json` is written when somebody
presses save on the permissions page, exactly as for a profile made by hand.
"""

from __future__ import annotations

import json
from typing import Any

from .profiles import Profile, profile_from_stored
from .stamp import now

__all__ = [
    "BUNDLE_KIND",
    "BUNDLE_VERSION",
    "TransferError",
    "build",
    "dumps",
    "parse",
]

BUNDLE_KIND = "benethos-lexware-office-mcp/profiles"
BUNDLE_VERSION = 1


class TransferError(ValueError):
    """The file is not a profile export from this server."""


def build(profiles: dict[str, Profile], *, version: str = "") -> dict[str, Any]:
    """The document to write out."""
    return {
        "kind": BUNDLE_KIND,
        "bundleVersion": BUNDLE_VERSION,
        "created": now(),
        "serverVersion": version,
        "profiles": {
            name: {
                "saved": profile.saved,
                "tools": list(profile.tools),
                "known": list(profile.known),
            }
            for name, profile in sorted(profiles.items(), key=lambda x: x[0].casefold())
        },
    }


def dumps(document: dict[str, Any]) -> str:
    """The document as the bytes that get downloaded, readable by a person."""
    return json.dumps(document, indent=1, ensure_ascii=False) + "\n"


def parse(text: str) -> dict[str, Profile]:
    """Read a profile export, or explain in one sentence why it is not one."""
    try:
        data = json.loads(text)
    except ValueError:
        raise TransferError("Das ist keine gültige JSON-Datei.") from None
    if not isinstance(data, dict):
        raise TransferError("Die Datei enthält kein Objekt.")
    if data.get("kind") != BUNDLE_KIND:
        raise TransferError(
            "Die Datei ist kein Profil-Export dieses Servers. Erwartet wird "
            f"kind = {BUNDLE_KIND!r}."
        )
    if data.get("bundleVersion") != BUNDLE_VERSION:
        raise TransferError(
            f"Unbekannte Formatversion {data.get('bundleVersion')!r}. Diese "
            f"Version liest {BUNDLE_VERSION}."
        )

    found: dict[str, Profile] = {}
    for name, body in (data.get("profiles") or {}).items():
        profile = profile_from_stored(str(name), body)
        if profile is not None:
            found[profile.name] = profile
    if not found:
        raise TransferError("Die Datei enthält kein einziges lesbares Profil.")
    return found
