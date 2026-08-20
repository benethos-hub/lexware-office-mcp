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


def profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize ``GET /v1/profile``.

    The response is small and its exact field set is **(to verify)** against a
    live account, so nothing is renamed or dropped by name here. Inventing a
    mapping from documentation alone would silently discard fields the API
    actually returns. Compacting is enough until the shape is confirmed.
    """
    return dict(compact(payload))
