"""Reading one setting's raw text into the value it stands for.

Every parser refuses what it cannot read with a :class:`ConfigError` naming
the setting, rather than falling back to a default nobody asked for.
"""

from __future__ import annotations

import math
from urllib.parse import urlsplit

from ..errors import ConfigError

__all__ = ["as_float", "as_int", "credential", "csv_tuple", "flag", "https_url"]


def csv_tuple(raw: str | None) -> tuple[str, ...]:
    """A comma-separated list from the environment or the command line.

    Blanks are dropped, so a trailing comma or a stray space is not an
    entry, and nothing means an empty tuple rather than a tuple of nothing.
    """
    if not raw:
        return ()
    return tuple(part for part in (piece.strip() for piece in raw.split(",")) if part)


def flag(raw: str | None) -> bool:
    """A switch from the environment. Absent is off, and so is anything odd."""
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def as_float(raw: str | None, fallback: float, *, name: str) -> float:
    if raw is None or raw.strip() == "":
        return fallback
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from None
    # float() takes "nan" and "inf". A nan rate makes every wait nan, so no
    # request is ever let through, and an infinite one switches the limiter
    # off - neither is a number anybody meant.
    if not math.isfinite(value):
        raise ConfigError(f"{name} must be a finite number, got {raw!r}.")
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero, got {value}.")
    return value


def credential(raw: str | None, *, name: str) -> str | None:
    """A key or a token, which travels in an HTTP header, or ``None``.

    Visible ASCII only. A header cannot carry anything else: a character
    outside ASCII - a zero-width space pasted along with the key - made
    every request fail to encode, and a control character had the HTTP
    library refuse the header and quote it. Neither is ever part of a key.
    The message never quotes the value, which is a secret.
    """
    if not raw:
        return None
    if not all("!" <= char <= "~" for char in raw):
        raise ConfigError(
            f"{name} contains a character a key never has, such as a space or "
            "an invisible one copied along with it. Copy the value again."
        )
    return raw


def https_url(raw: str | None, fallback: str, *, name: str) -> str:
    """A base URL, which has to be ``https://``.

    The API key travels to ``LXO_MCP_BASE_URL`` in a header on every request,
    so a plain ``http://`` address would send it in the clear, and one that is
    no URL at all would send it wherever the client makes of it.
    """
    value = (raw or fallback).rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ConfigError(f"{name} must be an https:// address, got {value!r}.")
    return value


def as_int(
    raw: str | None,
    fallback: int,
    *,
    name: str,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    if raw is None or raw.strip() == "":
        return fallback
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}.") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}.")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be at most {maximum}, got {value}.")
    return value
