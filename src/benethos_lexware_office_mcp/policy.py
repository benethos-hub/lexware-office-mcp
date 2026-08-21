"""What this installation may do: one flag per tool, in one file.

**The file decides, and nothing else does.** A tool set to ``true`` is listed
and callable, a tool set to ``false`` is neither, and a tool the file does not
mention is **off**. An installation without a policy file therefore offers
nothing at all - which is the state to be in when nobody has said yet what
this server is allowed to touch.

**The classification is metadata, not a gate.** Every tool declares what kind
of access it needs and which group it belongs to, recorded by :func:`classify`
where the tool is defined so it cannot drift away from the code. Nothing
consults it when a call arrives. It exists so that a person, an interface or a
script can *write* a sensible file - "the reading tools", "the voucher group"
- and what lands on disk is then the whole truth, tool by tool.

Enforcement happens at two levels, deliberately (SPECS.md section 9):

1. **Listing.** ``server.PolicyServer`` leaves a disabled tool out of
   ``list_tools``, so it never reaches the model and costs no tokens. The file
   is read as the list is built, not when the server starts, so enabling a
   tool works as immediately as disabling one.
2. **Call.** The wrapper :func:`classify` puts around the function checks
   again when a call arrives, so a client holding a stale tool list cannot
   smuggle one through.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar

from .errors import PermissionDeniedError

__all__ = [
    "Access",
    "Preset",
    "ToolMeta",
    "ToolPolicy",
    "active_policy",
    "classify",
    "grouped_tools",
    "known_tools",
    "preset",
    "set_active_policy",
]

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

Access = Literal["read", "write"]

# Write tools only. `delete`, `book` and `finalize` are irreversible in this
# product rather than merely inconvenient: a finalized invoice carries a
# consecutive number and can be corrected only by a further document.
# `book` and `finalize` were here too, and both were removed on 2026-08-21
# because the API cannot perform either on a record that exists: it has no
# state transitions at all. A document is created in its final state or not
# at all, and `finalize` is a query parameter on the creation rather than
# an operation. See SPECS.md section 5.
Effect = Literal["", "create", "update", "delete"]

IRREVERSIBLE: tuple[Effect, ...] = ("delete",)


@dataclass(frozen=True)
class ToolMeta:
    """What a tool is, for whoever writes the policy file.

    Never consulted to decide a call. An interface groups by ``domain``, a
    script selects by ``access``, and both then write flags.
    """

    access: Access
    domain: str
    effect: Effect = ""

    @property
    def irreversible(self) -> bool:
        """Whether undoing this needs a further document rather than an undo."""
        return self.effect in IRREVERSIBLE


# Tool name -> what it is. Filled by `classify` as the tool modules are
# imported, so the classification cannot drift away from the code it
# describes, which a table maintained by hand somewhere else eventually would.
_REGISTRY: dict[str, ToolMeta] = {}


def known_tools() -> dict[str, ToolMeta]:
    """Every tool that has been defined, and what it is."""
    return dict(_REGISTRY)


def grouped_tools() -> dict[str, list[str]]:
    """Tool names by domain, both sorted. For an interface to lay out."""
    groups: dict[str, list[str]] = {}
    for name, meta in _REGISTRY.items():
        groups.setdefault(meta.domain, []).append(name)
    return {domain: sorted(groups[domain]) for domain in sorted(groups)}


Preset = Literal["read-only", "write", "irreversible"]


def preset(kind: Preset) -> dict[str, bool]:
    """A complete set of flags, computed from the classification.

    This is the only thing the classification is for. The result is written to
    the file and the file is what is read afterwards, so a preset is a way of
    setting many flags at once and never a rule applied later.

    Three of them, each one containing the last:

    - ``read-only`` - queries only.
    - ``write`` - and creating and updating, but nothing whose effect cannot
      be undone.
    - ``irreversible`` - everything, deleting, booking and finalizing
      included. Its own step because that is a different decision, and it
      should be made by naming it rather than by picking the largest option.
    """
    if kind == "read-only":
        return {name: meta.access == "read" for name, meta in _REGISTRY.items()}
    if kind == "write":
        return {name: not meta.irreversible for name, meta in _REGISTRY.items()}
    if kind == "irreversible":
        return dict.fromkeys(_REGISTRY, True)
    raise ValueError(f"Unknown preset: {kind!r}")


class ToolPolicy:
    """The flags this installation runs under.

    Read from disk on every question rather than cached, so a file edited
    while the server runs takes effect on the next request. It is a few
    hundred bytes, and a copy held in memory is a copy that can be wrong.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path | None:
        """The file this policy reads, or ``None`` when there is none."""
        return self._path

    def exists(self) -> bool:
        """Whether there is a file at all. Nothing is enabled without one."""
        return self._path is not None and self._path.is_file()

    def _stored(self) -> dict[str, bool]:
        if not self.exists():
            return {}
        assert self._path is not None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # The file is edited by hand and by other programs, so a broken one
            # must not stop the server. It must not grant anything either: an
            # unreadable policy enables nothing, and says so on stderr.
            logger.warning("Unreadable tool policy %s: %s", self._path, exc)
            return {}
        if not isinstance(data, dict):
            logger.warning("Tool policy %s is not an object, ignoring it.", self._path)
            return {}
        return {str(key): bool(value) for key, value in data.items()}

    def enabled(self, name: str) -> bool:
        """Whether ``name`` may be listed and called.

        A tool the file does not name is off. Silence is a refusal here: the
        file is the only thing standing between a model and a live accounting
        system, so anything it fails to say has to be a no.
        """
        return self._stored().get(name, False)

    def as_map(self) -> dict[str, bool]:
        """The effective flag for every known tool."""
        stored = self._stored()
        return {name: stored.get(name, False) for name in sorted(_REGISTRY)}

    def sync(self) -> tuple[list[str], list[str]]:
        """Complete the file without changing a single decision in it.

        Every tool the file does not mention is added as ``false``, and every
        flag already there is written back exactly as it stood. **Nothing is
        ever switched on**, which is what makes this the one `--tools` action
        that can run unattended - after an upgrade, from a post-install hook -
        while the presets stay a deliberate act.

        Returns what was added and what was found that is no longer a tool.
        The second kind is not kept: a name that matches nothing has no effect
        and no decision attached to it, so writing it back would only make the
        file harder to read. It is reported rather than dropped in silence.
        """
        stored = self._stored()
        added = sorted(name for name in _REGISTRY if name not in stored)
        stale = sorted(name for name in stored if name not in _REGISTRY)
        self.save(stored)
        return added, stale

    def save(self, flags: dict[str, bool]) -> None:
        """Write a flag for every known tool, ignoring names that are not one.

        Every tool is written, including the ones that are off, so the file
        reads as a complete inventory rather than as a list that leaves the
        reader guessing what is missing and why.
        """
        if self._path is None:
            raise ValueError("This policy has no file to write to.")
        clean = {name: bool(flags.get(name, False)) for name in sorted(_REGISTRY)}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(clean, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )


# The policy this process enforces. Without a file nothing is enabled, which
# is what an installation nobody has configured should offer.
_POLICY = ToolPolicy()


def set_active_policy(policy: ToolPolicy) -> None:
    """Set the policy this process enforces. Called once during startup."""
    global _POLICY
    _POLICY = policy


def active_policy() -> ToolPolicy:
    """The policy this process is enforcing."""
    return _POLICY


def classify(access: Access, domain: str, effect: Effect = "") -> Callable[[F], F]:
    """Record what a tool is, and enforce the policy on every call.

    The metadata is for whoever writes the file. The wrapper is the second of
    the two gates: registration already leaves a disabled tool out, and this
    catches a call from a client whose tool list predates the change.
    """

    def decorate(func: F) -> F:
        name = func.__name__
        _REGISTRY[name] = ToolMeta(access=access, domain=domain, effect=effect)

        def guard() -> None:
            if not _POLICY.enabled(name):
                where = _POLICY.path or "the tool policy file"
                raise PermissionDeniedError(
                    f"{name} is not enabled for this installation. Set it to "
                    f"true in {where}."
                )

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                guard()
                return await func(*args, **kwargs)

            wrapper: Any = async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                guard()
                return func(*args, **kwargs)

            wrapper = sync_wrapper

        wrapper.tool_meta = _REGISTRY[name]
        return wrapper

    return decorate
