"""Named sets of permissions, saved so a use case can be picked again.

**A profile is not a second policy.** The server reads ``tools.json`` and
nothing else, exactly as before. Choosing a profile here fills in the form and
stops there — the file is written when the person presses save, by the same
code that writes any other change. Anything else would mean two files with a
say in what a live accounting system may be asked to do, and section 9.2 of
SPECS.md has one.

A profile stores **the names that were on**, not a flag per tool. That makes
it behave like the policy file it feeds: a name it does not carry is off. A
tool added by a later version is therefore off in every profile written before
it existed, which is the answer that needs no decision from anybody.

It also stores **which tools existed when it was written**, and that second
list is only there to tell those two cases apart. Without it, a tool that is
off because somebody switched it off looks exactly like a tool that is off
because it did not exist yet — and only the second is worth mentioning when a
profile is loaded.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

__all__ = [
    "PROFILE_FILE_NAME",
    "Profile",
    "ProfileError",
    "ProfileStore",
    "profile_file",
    "profile_from_stored",
]

logger = logging.getLogger(__name__)

PROFILE_FILE_NAME = "tool_profiles.json"

# Long enough for "Steuerberater, nur lesend", short enough to stay one line
# in a dropdown and one column in a table.
MAX_NAME_LENGTH = 60

_DOCUMENT_VERSION = 1


class ProfileError(ValueError):
    """A profile could not be saved under the name that was asked for."""


@dataclass(frozen=True, slots=True)
class Profile:
    """One saved set of permissions."""

    name: str
    tools: tuple[str, ...]
    saved: str = ""
    known: tuple[str, ...] = ()

    def flags(self, known: Iterable[str]) -> dict[str, bool]:
        """This profile as a flag per tool, for a form or for the file."""
        chosen = set(self.tools)
        return {name: name in chosen for name in known}

    def unknown(self, known: Iterable[str]) -> list[str]:
        """Names in the profile that are no longer tools."""
        return sorted(set(self.tools) - set(known))

    def newer_tools(self, known: Iterable[str]) -> list[str]:
        """Tools that did not exist when this profile was written.

        Empty for a profile that never recorded what existed — a hand-written
        one, or one from an older version. Saying nothing is right there:
        every tool it leaves off would otherwise be reported as new.
        """
        if not self.known:
            return []
        return sorted(set(known) - set(self.known))


def profile_file(policy_path: Path) -> Path:
    """Where the profiles for a given policy file live: right beside it.

    Deliberately derived from the policy path rather than searched for on its
    own. One account has one policy file and one set of profiles for it, and
    naming a different policy with ``--tools-file`` has to move both together
    or a profile would be offered for permissions it was never written for.
    """
    return policy_path.with_name(PROFILE_FILE_NAME)


class ProfileStore:
    """The saved profiles, read from disk on every question.

    Small, rarely written, and edited by a person with an editor as readily as
    through the interface — so a copy held in memory would be a copy that goes
    stale while a browser tab sits open.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def all(self) -> dict[str, Profile]:
        """Every saved profile, by name, sorted."""
        document = self._document()
        found: dict[str, Profile] = {}
        raw = document.get("profiles")
        if not isinstance(raw, dict):
            return found
        for name, body in raw.items():
            profile = profile_from_stored(str(name), body)
            if profile is not None:
                found[profile.name] = profile
        return {name: found[name] for name in sorted(found, key=str.casefold)}

    def get(self, name: str) -> Profile | None:
        return self.all().get(name.strip())

    def save(self, name: str, tools: Iterable[str], known: Iterable[str]) -> Profile:
        """Write a profile, replacing one of the same name.

        Replacing without asking is the caller's business to warn about: the
        interface asks, and a script that calls this has already decided.

        ``known`` is every tool that exists right now, recorded so that a
        later version can tell "switched off" from "did not exist yet".
        """
        clean = _valid_name(name)
        profile = Profile(
            name=clean,
            tools=tuple(sorted(set(tools))),
            saved=date.today().isoformat(),
            known=tuple(sorted(set(known))),
        )
        profiles = self.all()
        profiles[clean] = profile
        self._write(profiles)
        return profile

    def delete(self, name: str) -> bool:
        """Remove a profile. ``False`` when there was none by that name."""
        profiles = self.all()
        if name.strip() not in profiles:
            return False
        del profiles[name.strip()]
        self._write(profiles)
        return True

    def replace_all(self, profiles: dict[str, Profile]) -> None:
        """Write exactly these profiles, dropping whatever was there."""
        self._write(dict(profiles))

    def merge(self, profiles: dict[str, Profile]) -> list[str]:
        """Add these profiles, overwriting same-named ones.

        Returns the names that already existed, so an import can say what it
        is about to overwrite before it does.
        """
        current = self.all()
        overwritten = sorted(name for name in profiles if name in current)
        current.update(profiles)
        self._write(current)
        return overwritten

    def as_document(self) -> dict[str, Any]:
        """The stored form, for an export to carry."""
        return _document(self.all())

    def _document(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            # An unreadable profile file must not take the interface down with
            # it: profiles are a convenience, and the permissions themselves
            # live in another file entirely.
            logger.warning("Unreadable profiles at %s: %s", self._path, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, profiles: dict[str, Profile]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(_document(profiles), indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _document(profiles: dict[str, Profile]) -> dict[str, Any]:
    return {
        "version": _DOCUMENT_VERSION,
        "profiles": {
            name: {
                "saved": profile.saved,
                "tools": list(profile.tools),
                "known": list(profile.known),
            }
            for name, profile in sorted(profiles.items(), key=lambda x: x[0].casefold())
        },
    }


def profile_from_stored(name: str, body: Any) -> Profile | None:
    """One stored entry read back, or ``None`` when it is not a profile."""
    clean = name.strip()
    if not clean or not isinstance(body, dict):
        return None
    tools = body.get("tools")
    if not isinstance(tools, list):
        return None
    return Profile(
        name=clean[:MAX_NAME_LENGTH],
        tools=tuple(sorted({str(item) for item in tools if isinstance(item, str)})),
        saved=str(body.get("saved") or ""),
        known=tuple(sorted(_names(body.get("known")))),
    )


def _names(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if isinstance(item, str)}


def _valid_name(name: str) -> str:
    clean = " ".join(name.split())
    if not clean:
        raise ProfileError("Ein Profil braucht einen Namen.")
    if len(clean) > MAX_NAME_LENGTH:
        raise ProfileError(f"Der Name ist länger als {MAX_NAME_LENGTH} Zeichen.")
    return clean
