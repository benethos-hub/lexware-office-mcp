"""Permission tiers and their enforcement.

Three tiers, ordered. ``read`` is the default and allows GET only. ``write``
adds creating and updating drafts and master records. ``full`` adds the
irreversible operations: finalizing a document, booking a voucher, deleting an
article.

Enforcement happens at two levels, deliberately (SPECS.md section 9):

1. **Registration.** A tool above the active tier is never registered, so it
   does not appear in ``list_tools`` and costs no tokens.
2. **Call.** :func:`requires` wraps the function so the tier is checked again
   when a call arrives. A client holding a stale tool list cannot smuggle one
   through.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from .config import Mode
from .errors import PermissionDeniedError

__all__ = [
    "DEFAULT_MODE",
    "active_mode",
    "allows",
    "required_tier",
    "requires",
    "set_active_mode",
    "should_register",
]

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
