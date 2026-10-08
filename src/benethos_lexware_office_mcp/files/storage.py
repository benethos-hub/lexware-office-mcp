"""Where downloaded files land on the local disk, and what leaves it.

Its own module because two things here are easy to get wrong and worth testing
on their own: the filename comes from the **server**, so it is treated as
untrusted input rather than as a path, and an existing file is never
overwritten. A download that silently replaces last month's invoice with this
month's is worse than one that fails.

The other direction lives here too: a file the model names for upload is
read under the one rule that bounds it, ``LXO_MCP_UPLOAD_DIR``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote

import httpx

from .. import logbook
from ..errors import ConfigError, ValidationError
from ..settings import Settings

__all__ = [
    "MAX_UPLOAD",
    "UPLOAD_TYPES",
    "content_type_for",
    "directory_for",
    "newest",
    "read_upload",
    "resolve",
    "save",
    "suggested_name",
]

# Anything outside this set is replaced. Deliberately narrow: a filename that
# reaches the disk should be boring.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

_FILENAME = re.compile(r'filename\s*=\s*"?([^";]+)"?', re.IGNORECASE)
# RFC 6266: `filename*=charset'language'percent-encoded`, which wins over a
# plain `filename` beside it.
_FILENAME_STAR = re.compile(
    r"filename\*\s*=\s*([\w!#$&+.^`|~-]+)'[^']*'([^;]+)", re.IGNORECASE
)

MAX_NAME = 120

# Names Windows reserves for devices, with or without an extension.
_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{n}" for n in range(10)}
    | {f"LPT{n}" for n in range(10)}
)


def directory_for(settings: Settings) -> Path:
    """Where this server writes downloads, created if it is not there yet."""
    target = settings.download_directory()
    target.mkdir(parents=True, exist_ok=True)
    return target


def prune(directory: Path, keep: int) -> int:
    """Delete all but the newest ``keep`` downloads, and say how many went.

    Newest by modification time, which a reused download renews. Only plain
    files: a subdirectory or a symbolic link was put there by someone else. A
    file that cannot be deleted - on Windows, one open in a viewer - is left
    for the next time rather than failing the call that triggered this.

    **Only what could be a download** is counted or deleted, see
    :func:`_could_be_a_download`. The directory can be named in the
    configuration interface, and a folder of somebody's own is not a cache.
    """
    if keep <= 0 or not directory.is_dir():
        return 0
    removed = 0
    for path in newest(directory, downloads_only=True)[keep:]:
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
    return removed


def newest(directory: Path, *, downloads_only: bool = False) -> list[Path]:
    """The plain files in ``directory``, newest first.

    Newest by modification time, which a reused download renews, and by name
    where two share one, so the order is the same on every call. A symbolic
    link or a subdirectory was put there by someone else and is skipped, and
    so is a file that goes between listing the directory and looking at it.

    One scan for the clean-up and the resource list, so the two cannot come
    to disagree about which files are the newest. They do differ in one
    thing, deliberately: ``downloads_only`` leaves out a file this server
    could not have written, which the clean-up must never delete and the
    list still names.
    """
    found: list[tuple[float, str, Path]] = []
    for path in directory.iterdir():
        try:
            if path.is_symlink() or not path.is_file():
                continue
            if downloads_only and not _could_be_a_download(path):
                continue
            found.append((path.stat().st_mtime, path.name, path))
        except OSError:
            continue
    found.sort(key=lambda entry: (-entry[0], entry[1]))
    return [path for _, _, path in found]


def _could_be_a_download(path: Path) -> bool:
    """Whether this server could have saved a download under this name.

    Every name it writes has been through :func:`_safe_name`, so it comes out
    unchanged, and a document has one of the extensions in
    :data:`CONTENT_TYPES`. ``Urlaub 2025.jpg`` and ``notes.docx`` fail one or
    the other and are left alone. ``report.pdf`` passes: a name alone cannot
    tell a download from a file of the same shape, which is why a directory
    named by hand is cleaned only when the bound is set as well.
    """
    return _safe_name(path.name) == path.name and path.suffix.lower() in CONTENT_TYPES


def prune_for(settings: Settings) -> int:
    """Clean the download directory these settings name, where they allow it.

    The directory is not created here, and no home to find it in is not an
    error: there is then nothing to clean.
    """
    keep = settings.downloads_kept()
    if keep is None:
        return 0
    try:
        directory = settings.download_directory()
    except ConfigError:
        return 0
    removed = prune(directory, keep)
    if removed:
        logbook.files.pruned(removed, keep)
    return removed


def suggested_name(response: httpx.Response, fallback: str) -> str:
    """The filename to save a response under, made safe first.

    ``Content-Disposition`` is written by the API, so it is sanitized the way
    any other remote input would be: the directory part is discarded, unusual
    characters are replaced, and a name that survives none of that falls back
    to the caller's own.
    """
    header = response.headers.get("content-disposition", "")
    cleaned = _safe_name(_header_name(header))
    if cleaned:
        return cleaned
    return _safe_name(fallback) or "download"


def _header_name(header: str) -> str:
    """The filename a ``Content-Disposition`` suggests, not yet made safe.

    The encoded form is decoded: read as it stands, `Rechnung%20M%C3%A4rz`
    reached the disk as `Rechnung_20M_C3_A4rz`. A charset Python does not
    know is read as UTF-8, and a byte that is no character in it is
    replaced, which the sanitizing then replaces again.
    """
    star = _FILENAME_STAR.search(header)
    if star:
        charset, encoded = star.group(1), star.group(2).strip()
        try:
            return unquote(encoded, encoding=charset, errors="replace")
        except LookupError:
            return unquote(encoded, errors="replace")
    plain = _FILENAME.search(header)
    return plain.group(1) if plain else ""


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
    cleaned = cleaned[:MAX_NAME]
    # On Windows `CON.pdf` is the console, whatever the extension, and
    # writing to it writes nowhere a file can be found again.
    if cleaned.split(".")[0].upper() in _DEVICES:
        cleaned = f"_{cleaned}"[:MAX_NAME]
    return cleaned


def save(content: bytes, name: str, directory: Path) -> Path:
    """Write ``content`` under ``name``, replacing nothing and repeating nothing.

    Two rules that pull in opposite directions, so both are stated:

    - A file whose contents differ is never overwritten. Replacing last
      month's invoice with this month's is worse than failing.
    - A file whose contents are **identical** is reused rather than copied.
      Downloading the same unchanged document four times used to leave four
      copies numbered up to ``-4``, which is not caution, it is litter.

    A reused file has its modification time renewed, because the resource
    list names the newest downloads and this one was just fetched.
    """
    for candidate in _candidates(name, directory):
        # Created exclusively rather than checked and then written: two
        # downloads at once - the tools run concurrently - could otherwise
        # both find a name free and the second overwrite the first.
        try:
            with candidate.open("xb") as out:
                out.write(content)
            return candidate
        except FileExistsError:
            pass
        if candidate.is_file() and candidate.read_bytes() == content:
            logbook.files.reused(len(content))
            candidate.touch()
            return candidate
    # Without the directory: this message can reach the client, and where
    # downloads land on somebody's disk is not the caller's business. The
    # filename is theirs already - it came from the document they asked for.
    raise FileExistsError(
        f"Too many files already named like {name!r} in the download directory."
    )


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
    was ever tied to a process. The result is checked to be inside
    ``directory``, because the name arrives from the caller.

    The name is tried as given first, then percent-decoded, then sanitized.
    A file this server saved has a sanitized name already, but the directory
    is listed as it is, and a file put there by hand - ``my invoice.pdf`` -
    was listed as a resource under its own name and then looked up here
    under a sanitized one it did not have.
    """
    base = directory.resolve()
    for attempt in dict.fromkeys(
        (_one_component(name), _one_component(unquote(name)), _safe_name(name))
    ):
        if not attempt:
            continue
        candidate = (directory / attempt).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def _one_component(name: str) -> str:
    """``name`` if it is a single path component as it stands, else empty."""
    if name in ("", ".", "..") or any(c in name for c in "/\\\x00"):
        return ""
    return name


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


# -- uploads --------------------------------------------------------------

# Exactly what the API takes, measured on 2026-08-20 rather than assumed:
# `.gif` is refused with `inacceptable_file_extension`, and `.xml` is accepted
# and parsed as an XRechnung — a file that is not one comes back as
# `invalid_xrechnung`. The web app states the same four types.
#
# The type is guessed from the extension rather than sniffed. The API
# validates the content anyway and rejects a mislabelled or damaged file, so a
# second opinion here would only be a second way to be wrong.
UPLOAD_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".xml": "application/xml",
}

# Verified 2026-08-20: 5 MiB exactly is still accepted, one byte more is
# refused with `max_file_size_exceeded`. Checked here so a caller finds out
# before spending a request on it.
MAX_UPLOAD = 5 * 1024 * 1024


def read_upload(raw_path: str, allowed: Path | None) -> tuple[bytes, str, str]:
    """Read a local file for upload, refusing what the API would refuse.

    ``allowed`` is ``LXO_MCP_UPLOAD_DIR``. The path comes from the model, so
    where one is set, the file has to resolve inside it - links followed
    first, so one placed in the directory cannot point out of it. What the
    operating system refuses is left to the caller to turn into an answer.

    **The directory is checked before the file is looked for.** The other
    way round, a path outside it was answered "no file" or "outside the
    directory" depending on whether it existed - which tells the model what
    is on the disk where it may not upload from.
    """
    try:
        path = Path(raw_path).expanduser()
    except RuntimeError:
        # `~` with no home directory to expand it to.
        raise ValidationError(
            f"No file at {raw_path}. Give the path to an existing receipt."
        ) from None
    if allowed is not None:
        try:
            path.resolve().relative_to(allowed.expanduser().resolve())
        except (OSError, ValueError, RuntimeError):
            # Without the directory: it describes this machine, and the
            # person who can change it knows where it is.
            raise ValidationError(
                f"{path.name} is outside the directory this server may upload "
                "from. Move the file there, or ask the account owner about "
                "LXO_MCP_UPLOAD_DIR."
            ) from None
    if not path.is_file():
        raise ValidationError(
            f"No file at {raw_path}. Give the path to an existing receipt."
        )

    size = path.stat().st_size
    if size > MAX_UPLOAD:
        raise ValidationError(
            f"{path.name} is {size / 1024 / 1024:.1f} MiB. The API accepts at "
            "most 5 MiB, so this was not sent."
        )

    content_type = UPLOAD_TYPES.get(path.suffix.lower())
    if content_type is None:
        accepted = ", ".join(sorted(UPLOAD_TYPES))
        found = path.suffix or "no extension"
        raise ValidationError(f"The API does not accept {found}. It takes: {accepted}.")
    return path.read_bytes(), path.name, content_type
