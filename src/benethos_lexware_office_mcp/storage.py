"""Where downloaded files land on the local disk.

Its own module because two things here are easy to get wrong and worth testing
on their own: the filename comes from the **server**, so it is treated as
untrusted input rather than as a path, and an existing file is never
overwritten. A download that silently replaces last month's invoice with this
month's is worse than one that fails.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath, PureWindowsPath

import httpx

from .config import Settings, download_dir

__all__ = [
    "content_type_for",
    "directory_for",
    "resolve",
    "save",
    "suggested_name",
]

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
    """Write ``content`` under ``name``, replacing nothing and repeating nothing.

    Two rules that pull in opposite directions, so both are stated:

    - A file whose contents differ is never overwritten. Replacing last
      month's invoice with this month's is worse than failing.
    - A file whose contents are **identical** is reused rather than copied.
      Downloading the same unchanged document four times used to leave four
      copies numbered up to ``-4``, which is not caution, it is litter.
    """
    for candidate in _candidates(name, directory):
        if not candidate.exists():
            candidate.write_bytes(content)
            return candidate
        if candidate.read_bytes() == content:
            return candidate
    raise FileExistsError(f"Too many files already named like {name!r} in {directory}.")


def _candidates(name: str, directory: Path) -> Iterator[Path]:
    """The plain name first, then the same name with a counter."""
    target = directory / name
    yield target
    stem, suffix = target.stem, target.suffix
    for counter in range(2, 1000):
        yield directory / f"{stem}-{counter}{suffix}"


def resolve(name: str, directory: Path) -> Path | None:
    """The downloaded file called ``name``, or ``None``.

    Used instead of an in-memory registry so a link keeps working after the
    server restarts: the file is on disk either way, and only the registration
    was ever tied to a process. The name is sanitized and the result checked
    to be inside ``directory``, because the name arrives from the caller.
    """
    safe = _safe_name(name)
    if not safe:
        return None
    candidate = (directory / safe).resolve()
    try:
        candidate.relative_to(directory.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


# Enough to tell a client what it is holding. Anything unlisted is handed over
# as an opaque download rather than guessed at.
CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".xml": "application/xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
}


def content_type_for(path: Path) -> str:
    """The content type of a saved file, from its extension."""
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
