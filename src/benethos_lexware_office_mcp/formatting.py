"""API JSON to compact tool output.

The client's token budget is a real constraint, so every response is trimmed
before it leaves. Two rules matter more than brevity:

- **Monetary values pass through untouched.** Never rounded, never
  reformatted, and never separated from their currency. This is accounting
  data, and a helpfully tidied number is a wrong number.
- **Zero and false survive.** Only ``None`` and empty containers are dropped.
  An open amount of ``0`` is the answer to "is it paid", not noise.
"""

from __future__ import annotations

from typing import Any

__all__ = ["compact", "profile"]


def compact(value: Any) -> Any:
    """Drop nulls and empty containers, recursively.

    ``0``, ``0.0`` and ``False`` are kept on purpose: they carry meaning in
    accounting data. Only ``None``, ``""``, ``[]`` and ``{}`` go.
    """
    if isinstance(value, dict):
        cleaned = {k: compact(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if not _is_empty(v)}
    if isinstance(value, list):
        items = [compact(v) for v in value]
        return [v for v in items if not _is_empty(v)]
    return value


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str | list | dict | tuple):
        return len(value) == 0
    return False


# `created` carries `userEmail` and `userName`, which are the address of the
# person who set the account up. The tool answers *which organization* is
# connected, so that person's identity is neither needed nor ours to hand to a
# language model. Dropped rather than compacted. Confirmed against a live
# account on 2026-08-20.
PROFILE_DROP = ("created",)


def profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize ``GET /v1/profile``.

    Keeps every field the API returns except the ones in
    :data:`PROFILE_DROP`, so a field added upstream shows up rather than being
    silently discarded by an allow-list.
    """
    kept = {k: v for k, v in payload.items() if k not in PROFILE_DROP}
    return dict(compact(kept))
