"""The page shell every screen is drawn into.

German, because this is the only surface a person reads and Lexware Office is
sold for German companies only — its own help centre rules out an Austrian or
Swiss company as the account holder. Code, comments and docstrings stay
English, as everywhere else in this repository.

No template engine and no stylesheet file. The whole interface is a handful of
pages served from a local process for a few minutes at a time, and every
dependency it does not have is one that cannot go stale between releases.
The stylesheet and the scripts are strings in :mod:`.assets`.
"""

from __future__ import annotations

from html import escape

from .assets import CSS

__all__ = [
    "CLI_SOURCE",
    "DEFAULT_SOURCE",
    "ENV_SOURCE",
    "FILE_SOURCE",
    "SEARCH_SOURCE",
    "esc",
    "note",
    "page",
    "source_badge",
]

# Where a setting actually comes from. Showing the file alone would be
# misleading exactly when it matters most: a real environment variable
# outranks it, and that is how a client starts this server with its own
# account. See settings/locations.py for the full precedence.
ENV_SOURCE = "Umgebung"
CLI_SOURCE = "Aufruf"
# Nobody named this file: the search of section 7 found it when the process
# started, and it has been held since. Not a built-in default, which is the
# name of a file rather than a path to one.
SEARCH_SOURCE = "Suche"
FILE_SOURCE = "Datei"
# The value applies, but it comes from a .env other than the one this
# interface writes to. Typing over it here would appear to work and change
# nothing, so it gets a badge of its own rather than being called "Datei".
DEFAULT_SOURCE = "Default"

esc = escape

_LINKS: tuple[tuple[str, str], ...] = (
    ("/", "Übersicht"),
    ("/credentials", "Zugangsdaten"),
    ("/permissions", "Rechte"),
)


def page(title: str, body: str, *, here: str = "", chip: str = "") -> bytes:
    """One complete HTML document, ready to send."""
    links = " · ".join(
        f'<a href="{href}"{" class=here" if href == here else ""}>{esc(label)}</a>'
        for href, label in _LINKS
    )
    badge = f'<span class="chip">{esc(chip)}</span>' if chip else ""
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Lexware Office MCP</title>
<style>{CSS}</style></head><body>
<nav>{links}{badge}</nav>
<h1>{esc(title)}</h1>
{body}
</body></html>""".encode()


def note(text: str, kind: str = "") -> str:
    """A boxed remark. ``kind`` is ``good``, ``bad``, or nothing for a warning."""
    return f'<div class="note {kind}">{text}</div>'


def source_badge(source: str, detail: str = "") -> str:
    """Where a displayed value came from, marked when the file lost.

    ``detail`` becomes the tooltip, which is where a full path belongs: it
    answers "which file?" for the one person who asks, without putting a
    hundred characters of Windows path into every row.
    """
    loud = source in (ENV_SOURCE, CLI_SOURCE)
    css = "src env" if loud else "src"
    title = f' title="{esc(detail)}"' if detail else ""
    return f'<span class="{css}"{title}>aus: {esc(source)}</span>'
