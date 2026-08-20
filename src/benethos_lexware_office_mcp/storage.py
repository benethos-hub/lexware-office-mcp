"""Where downloaded files land on the local disk.

Its own module because two things here are easy to get wrong and worth testing
on their own: the filename comes from the **server**, so it is treated as
untrusted input rather than as a path, and an existing file is never
overwritten. A download that silently replaces last month's invoice with this
month's is worse than one that fails.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath

import httpx

from .config import Settings, download_dir

__all__ = ["directory_for", "save", "suggested_name"]

# Anything outside this set is replaced. Deliberately narrow: a filename that
# reaches the disk should be boring.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

_FILENAME = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)

MAX_NAME = 120


def directory_for(settings: Settings) -> Path:
    """Where this server writes downloads, created if it is not there yet."""
    target = settings.download_path or download_dir()
    target.mkdir(parents=True, exist_ok=True)
    return target


def suggested_name(response: httpx.Response, fallback: str) -> str:
    """The filename to save a response under, made safe first.

    ``Content-Disposition`` is written by the API, so it is sanitized the way
    any other remote input would be: the directory part is discarded, unusual
    characters are replaced, and a name that survives none of that falls back
    to the caller's own.
    """
    header = response.headers.get("content-disposition", "")
    match = _FILENAME.search(header)
    raw = match.group(1) if match else ""
    cleaned = _safe_name(raw)
    if cleaned:
        return cleaned
    return _safe_name(fallback) or "download"


def _safe_name(raw: str) -> str:
    """One path component, or an empty string if nothing usable is left.

    Both separators are stripped, not just the platform's own: a name written
    on a server elsewhere can carry either, and ``..\\..\\`` is a traversal on
    Windows whatever produced it.
    """
    without_path = PureWindowsPath(PurePosixPath(raw.strip()).name).name
    cleaned = _UNSAFE.sub("_", without_path).strip("._")
    if cleaned in {"", ".", ".."}:
        return ""
    return cleaned[:MAX_NAME]


def save(content: bytes, name: str, directory: Path) -> Path:
    """Write ``content`` under ``name``, without ever replacing a file.

    A name already taken gets a counter before its extension, so repeated
    downloads of the same document accumulate rather than overwrite.
    """
    target = directory / name
    if not target.exists():
        target.write_bytes(content)
        return target

    stem, suffix = target.stem, target.suffix
    for counter in range(2, 1000):
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            candidate.write_bytes(content)
            return candidate
    raise FileExistsError(f"Too many files already named like {name!r} in {directory}.")
