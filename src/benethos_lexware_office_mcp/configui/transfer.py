"""Carrying a configuration to another machine, and showing it first.

One JSON file holds the settings, the permissions and the saved profiles. It
does **not** hold the API key, and it never will: a file whose whole purpose
is to leave this machine is the last place a credential belongs, and the
second installation is usually a second account anyway. The bundle says so in
a field of its own rather than leaving the reader to notice the absence.

**An import writes nothing on the way in.** It is parsed, compared against
what is here now, and rendered as a list of what would change — which
settings, which tools go on, which profiles get overwritten. Only a second
request applies it. Permissions arriving from somewhere else are exactly the
kind of change that should not happen while somebody is still reading the
page, because the file they came from was written for a different account.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .profiles import Profile, profile_from_stored
from .stamp import now

__all__ = [
    "BUNDLE_KIND",
    "BUNDLE_VERSION",
    "Bundle",
    "Changes",
    "TransferError",
    "build",
    "compare",
    "dumps",
    "parse",
]

BUNDLE_KIND = "benethos-lexware-office-mcp/config"
BUNDLE_VERSION = 1

# Never exported, whatever else the .env holds. Matched by name rather than by
# a heuristic on the value, so a rename here is a deliberate act.
SECRET_KEYS: tuple[str, ...] = ("LXO_MCP_API_KEY",)

_KEY_NOTE = (
    "Der API-Schlüssel ist absichtlich nicht enthalten. Er wird auf der "
    "Zielinstallation unter Zugangsdaten eingetragen."
)


class TransferError(ValueError):
    """The file is not a configuration bundle from this server."""


@dataclass(frozen=True, slots=True)
class Bundle:
    """What a configuration file carries, once it has been read."""

    settings: dict[str, str] = field(default_factory=dict)
    tools: dict[str, bool] = field(default_factory=dict)
    profiles: dict[str, Profile] = field(default_factory=dict)
    created: str = ""
    version: str = ""


@dataclass(frozen=True, slots=True)
class Changes:
    """What applying a bundle would do to this installation."""

    settings: list[tuple[str, str, str]] = field(default_factory=list)
    turn_on: list[str] = field(default_factory=list)
    turn_off: list[str] = field(default_factory=list)
    unknown_tools: list[str] = field(default_factory=list)
    unmentioned_tools: list[str] = field(default_factory=list)
    new_profiles: list[str] = field(default_factory=list)
    overwritten_profiles: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        """Whether applying this would change nothing at all."""
        return not (
            self.settings
            or self.turn_on
            or self.turn_off
            or self.new_profiles
            or self.overwritten_profiles
        )


def build(
    settings: dict[str, str],
    tools: dict[str, bool],
    profiles: dict[str, Profile],
    *,
    version: str = "",
) -> dict[str, Any]:
    """The document to write out.

    ``settings`` is what the ``.env`` file holds, not what this process
    resolved. A value that only exists as a real environment variable belongs
    to the machine it is set on and would be wrong to carry anywhere.
    """
    carried = {
        key: value
        for key, value in sorted(settings.items())
        if key.startswith("LXO_MCP_") and key not in SECRET_KEYS
    }
    return {
        "kind": BUNDLE_KIND,
        "bundleVersion": BUNDLE_VERSION,
        "created": now(),
        "serverVersion": version,
        "apiKey": None,
        "apiKeyNote": _KEY_NOTE,
        "settings": carried,
        "tools": {name: bool(flag) for name, flag in sorted(tools.items())},
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


def parse(text: str) -> Bundle:
    """Read a bundle, or explain in one sentence why it is not one."""
    try:
        data = json.loads(text)
    except ValueError:
        raise TransferError("Das ist keine gültige JSON-Datei.") from None
    if not isinstance(data, dict):
        raise TransferError("Die Datei enthält kein Objekt.")
    if data.get("kind") != BUNDLE_KIND:
        raise TransferError(
            "Die Datei stammt nicht aus diesem Server. Erwartet wird ein "
            f"Export mit kind = {BUNDLE_KIND!r}."
        )
    if data.get("bundleVersion") != BUNDLE_VERSION:
        raise TransferError(
            f"Unbekannte Formatversion {data.get('bundleVersion')!r}. Diese "
            f"Version liest {BUNDLE_VERSION}."
        )

    settings = {
        str(key): str(value)
        for key, value in (data.get("settings") or {}).items()
        if str(key).startswith("LXO_MCP_") and str(key) not in SECRET_KEYS
    }
    tools = {str(name): bool(flag) for name, flag in (data.get("tools") or {}).items()}
    profiles: dict[str, Profile] = {}
    for name, body in (data.get("profiles") or {}).items():
        profile = profile_from_stored(str(name), body)
        if profile is not None:
            profiles[profile.name] = profile

    return Bundle(
        settings=settings,
        tools=tools,
        profiles=profiles,
        created=str(data.get("created") or ""),
        version=str(data.get("serverVersion") or ""),
    )


def compare(
    bundle: Bundle,
    *,
    current_settings: dict[str, str],
    current_tools: dict[str, bool],
    current_profiles: dict[str, Profile],
) -> Changes:
    """What would change, in the terms somebody would ask about.

    A tool the bundle does not mention keeps whatever it is set to now, so
    it appears as ``unmentioned_tools`` rather than as something to switch
    off. An import completes a policy file, it does not replace one.

    ``current_tools`` is the effective flag for every tool that exists here,
    so a name in the bundle that is not in it is a tool this installation does
    not have — an older or newer version at the other end. It is reported and
    then ignored: writing it into the policy file would put a decision there
    about something that cannot be called.
    """
    settings = [
        (key, current_settings.get(key, ""), value)
        for key, value in sorted(bundle.settings.items())
        if current_settings.get(key, "") != value
    ]
    turn_on = sorted(
        name
        for name, flag in bundle.tools.items()
        if flag and name in current_tools and not current_tools[name]
    )
    turn_off = sorted(
        name
        for name, flag in bundle.tools.items()
        if not flag and current_tools.get(name, False)
    )
    return Changes(
        settings=settings,
        turn_on=turn_on,
        turn_off=turn_off,
        unknown_tools=sorted(set(bundle.tools) - set(current_tools)),
        unmentioned_tools=sorted(set(current_tools) - set(bundle.tools)),
        new_profiles=sorted(
            name for name in bundle.profiles if name not in current_profiles
        ),
        # A profile that already says exactly this is not "overwritten" in any
        # sense worth warning about. Re-importing the same file would
        # otherwise announce damage it is not doing.
        overwritten_profiles=sorted(
            name
            for name, profile in bundle.profiles.items()
            if name in current_profiles
            and current_profiles[name].tools != profile.tools
        ),
    )
