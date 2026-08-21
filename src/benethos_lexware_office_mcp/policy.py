"""Permission tiers, the per-tool policy, and their enforcement.

Two independent gates, and a tool has to pass **both**.

**The tier** is coarse and comes from ``LXO_MCP_MODE``. Three of them,
ordered: ``read`` is the default and allows GET only, ``write`` adds creating
and updating drafts and master records, ``full`` adds the irreversible
operations - finalizing a document, booking a voucher, deleting an article.

**The policy file** is fine and names one flag per tool. It answers the
question the tier cannot: raising the tier so a quotation may be drafted also
hands over every other write tool in the server. A tool the file disables is
not listed and cannot be called, whatever the tier says.

The file is the truth. The tier and the classification are only used to
*compute* a file - :func:`preset` turns "everything" or "reading only" into a
complete set of flags, and what lands on disk then says exactly what is
allowed, tool by tool. A group is a convenience for writing the file, never a
thing consulted afterwards.

Enforcement happens at two levels, deliberately (SPECS.md section 9):

1. **Registration.** A tool above the active tier, or switched off by the
   file, is never registered: it does not appear in ``list_tools`` and costs
   no tokens.
2. **Call.** :func:`requires` wraps the function so both are checked again
   when a call arrives. A client holding a stale tool list cannot smuggle one
   through.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar

from .config import Mode
from .errors import PermissionDeniedError

__all__ = [
    "DEFAULT_MODE",
    "Preset",
    "ToolPolicy",
    "active_mode",
    "active_policy",
    "allows",
    "known_tools",
    "preset",
    "required_tier",
    "requires",
    "set_active_mode",
    "set_active_policy",
    "should_register",
]

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# Higher number means more dangerous. Comparing the numbers is the whole
# permission check.
_ORDER: dict[str, int] = {"read": 0, "write": 1, "full": 2}

# Tool name -> tier it needs. Populated by the `requires` decorator, so the
# registry cannot drift away from the code it describes.
_REGISTRY: dict[str, Mode] = {}

# The tier this process runs at. Deliberately starts at the safest value, so a
# server that forgets to configure itself can only read.
DEFAULT_MODE: Mode = "read"
_ACTIVE: Mode = DEFAULT_MODE


def set_active_mode(mode: Mode) -> None:
    """Set the tier this process runs at. Called once during startup."""
    global _ACTIVE
    if mode not in _ORDER:
        raise ValueError(f"Unknown mode: {mode!r}")
    _ACTIVE = mode


def active_mode() -> Mode:
    """The tier this process is currently running at."""
    return _ACTIVE


def allows(active: Mode, needed: Mode) -> bool:
    """Whether a process running at ``active`` may perform a ``needed`` action."""
    return _ORDER[active] >= _ORDER[needed]


def should_register(needed: Mode, active: Mode | None = None) -> bool:
    """Whether a tool needing ``needed`` should be registered at all."""
    return allows(active if active is not None else _ACTIVE, needed)


def required_tier(name: str) -> Mode | None:
    """The tier a registered tool needs, or ``None`` if it is unknown."""
    return _REGISTRY.get(name)


def known_tools() -> dict[str, Mode]:
    """Every tool that has been defined, and the tier it needs.

    Filled by :func:`requires` as the tool modules are imported, so it cannot
    drift away from the code it describes - which a table maintained by hand
    somewhere else eventually would.
    """
    return dict(_REGISTRY)


Preset = Literal["all", "read-only"]


def preset(kind: Preset) -> dict[str, bool]:
    """A complete set of flags, computed from the tiers.

    The classification exists to write a file, not to be consulted instead of
    one. ``read-only`` leaves the reading tools on and turns everything else
    off. ``all`` turns everything on and leaves the tier to do its own work.
    """
    if kind == "all":
        return dict.fromkeys(_REGISTRY, True)
    if kind == "read-only":
        return {name: tier == "read" for name, tier in _REGISTRY.items()}
    raise ValueError(f"Unknown preset: {kind!r}")


class ToolPolicy:
    """Which tools this installation lists, one flag per tool.

    Read from disk on every question rather than cached, so a file edited
    while the server runs takes effect on the next request. It is a few
    hundred bytes, and a copy held in memory is a copy that can be wrong.

    A tool the file does not mention is **enabled**. The file exists to take
    something away, and a tool arriving with an upgrade is already covered by
    the tier it declares, which is the gate that holds back the dangerous
    ones.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path | None:
        """The file this policy reads, or ``None`` when there is none."""
        return self._path

    def _stored(self) -> dict[str, bool]:
        if self._path is None or not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # The file is edited by hand, so a broken one must not stop the
            # server. It must not silently grant anything either: the tier
            # still applies, and the warning goes to stderr.
            logger.warning("Ignoring unreadable tool policy %s: %s", self._path, exc)
            return {}
        if not isinstance(data, dict):
            logger.warning("Tool policy %s is not an object, ignoring it.", self._path)
            return {}
        return {str(key): bool(value) for key, value in data.items()}

    def enabled(self, name: str) -> bool:
        """Whether ``name`` may be listed and called."""
        return self._stored().get(name, True)

    def as_map(self) -> dict[str, bool]:
        """The effective flag for every known tool."""
        stored = self._stored()
        return {name: stored.get(name, True) for name in sorted(_REGISTRY)}

    def save(self, flags: dict[str, bool]) -> None:
        """Write a flag for every known tool, ignoring names that are not one.

        Every tool is written even when it is on, so the file reads as a
        complete inventory rather than as a list of exceptions to a rule the
        reader has to know already.
        """
        if self._path is None:
            raise ValueError("This policy has no file to write to.")
        clean = {name: bool(flags.get(name, False)) for name in sorted(_REGISTRY)}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(clean, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )


# The policy this process enforces. Without a file every tool is enabled and
# the tier is the only gate, which is what an installation that has never been
# configured should get.
_POLICY = ToolPolicy()


def set_active_policy(policy: ToolPolicy) -> None:
    """Set the policy this process enforces. Called once during startup."""
    global _POLICY
    _POLICY = policy


def active_policy() -> ToolPolicy:
    """The policy this process is enforcing."""
    return _POLICY


def requires(tier: Mode) -> Callable[[F], F]:
    """Mark a tool with the tier it needs and enforce it on every call.

    The check reads the active tier at call time rather than at import time,
    so it reflects how the process was actually configured.
    """
    if tier not in _ORDER:
        raise ValueError(f"Unknown tier: {tier!r}")

    def decorate(func: F) -> F:
        name = func.__name__
        _REGISTRY[name] = tier

        def guard() -> None:
            if not allows(_ACTIVE, tier):
                raise PermissionDeniedError(
                    f"{name} needs permission tier '{tier}', but this server "
                    f"runs at '{_ACTIVE}'. Set LXO_MCP_MODE={tier} to enable "
                    f"it. Only do that against an account you are willing to "
                    f"have changed."
                )
            if not _POLICY.enabled(name):
                raise PermissionDeniedError(
                    f"{name} is switched off for this installation. Set it to "
                    f"true in {_POLICY.path} to enable it."
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

        wrapper.required_tier = tier
        return wrapper

    return decorate
