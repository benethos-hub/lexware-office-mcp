"""The page shell every screen is drawn into.

German, because this is the only surface a person reads and Lexware Office is
sold for German companies only — its own help centre rules out an Austrian or
Swiss company as the account holder. Code, comments and docstrings stay
English, as everywhere else in this repository.

No template engine and no stylesheet file. The whole interface is a handful of
pages served from a local process for a few minutes at a time, and every
dependency it does not have is one that cannot go stale between releases.
"""

from __future__ import annotations

from html import escape

__all__ = [
    "CLI_SOURCE",
    "DEFAULT_SOURCE",
    "ENV_SOURCE",
    "FILE_SOURCE",
    "OTHER_FILE_SOURCE",
    "esc",
    "note",
    "page",
    "source_badge",
]

# Where a setting actually comes from. Showing the file alone would be
# misleading exactly when it matters most: a real environment variable
# outranks it, and that is how a client starts this server with its own
# account. See config.py for the full precedence.
ENV_SOURCE = "Umgebung"
CLI_SOURCE = "Aufruf"
FILE_SOURCE = "Datei"
# The value applies, but it comes from a .env other than the one this
# interface writes to. Typing over it here would appear to work and change
# nothing, so it gets a badge of its own rather than being called "Datei".
OTHER_FILE_SOURCE = "andere Datei"
DEFAULT_SOURCE = "Default"

esc = escape

_CSS = """
  :root { color-scheme: light; }
  body { font-family: system-ui, sans-serif; max-width: 900px; margin: 1.5rem auto;
         padding: 0 1rem; line-height: 1.5; color: #1a1a1a; background: #fff; }
  nav { margin-bottom: 1.2rem; padding-bottom: .6rem; border-bottom: 1px solid #ddd;
        display: flex; align-items: center; gap: .8rem; flex-wrap: wrap; }
  nav a { text-decoration: none; color: #1a4d99; }
  nav a.here { font-weight: 700; color: #1a1a1a; }
  h1 { font-size: 1.5rem; }
  h2 { font-size: 1.15rem; margin-top: 2rem; }
  .chip { margin-left: auto; background: #eef4ff; color: #1a4d99;
          border: 1px solid #cddcff; border-radius: 999px;
          padding: .1rem .7rem; font-size: .85rem; font-weight: 600; }
  label.fld { display: block; margin-top: 1rem; font-weight: 600; }
  input[type=text], input[type=password], select, textarea {
          width: 100%; padding: .45rem; box-sizing: border-box; font-size: 1rem;
          font-family: inherit; }
  textarea { font-family: ui-monospace, Consolas, monospace; font-size: .85rem; }
  .hint { color: #555; font-size: .9rem; }
  .ok { color: #1a7f37; } .err { color: #b3261e; }
  code { background: #f0f0f0; padding: .1rem .3rem; border-radius: 3px;
         font-size: .92em; }
  button { padding: .45rem 1rem; font-size: 1rem; cursor: pointer; }
  table { border-collapse: collapse; width: 100%; margin: .6rem 0; }
  th, td { text-align: left; padding: .3rem .5rem; border-bottom: 1px solid #eee;
           vertical-align: top; }
  th { font-size: .8rem; text-transform: uppercase; letter-spacing: .04em;
       color: #555; }
  td.num { text-align: right; font-variant-numeric: tabular-nums;
           white-space: nowrap; color: #555; }
  .grp { border: 1px solid #e0e0e0; border-radius: 6px; margin: .8rem 0;
         padding: .4rem .8rem; }
  .grp h3 { margin: .4rem 0; font-size: 1rem; display: flex;
            justify-content: space-between; align-items: center; gap: .6rem;
            flex-wrap: wrap; }
  .grp .acts button { font-size: .78rem; padding: .15rem .5rem; }
  .tool { display: flex; align-items: center; gap: .5rem; padding: .15rem 0; }
  .tool .cost { margin-left: auto; font-size: .78rem; color: #666;
                font-variant-numeric: tabular-nums; white-space: nowrap; }
  .tag { font-size: .72rem; padding: .05rem .4rem; border-radius: 3px;
         white-space: nowrap; }
  .tag.read { background: #e7f0ff; color: #1a4d99; }
  .tag.write { background: #fff0e0; color: #9a5a00; }
  .tag.del { background: #fde0e0; color: #a11; }
  .tag.keep { background: #f0ecff; color: #4b3a99; }
  .bar { position: sticky; bottom: 0; background: #fff; padding: .6rem 0;
         border-top: 1px solid #ddd; display: flex; align-items: center;
         gap: 1rem; flex-wrap: wrap; }
  .src { font-size: .75rem; color: #555; background: #f0f0f0;
         border-radius: 3px; padding: .05rem .4rem; margin-left: .4rem; }
  .src.env { background: #fff0e0; color: #9a5a00; font-weight: 600; }
  .note { border-left: 3px solid #9a5a00; background: #fffaf3;
          padding: .6rem .8rem; margin: .8rem 0; }
  .note.good { border-color: #1a7f37; background: #f4fbf5; }
  .note.bad { border-color: #b3261e; background: #fff5f5; }
  .row { display: flex; gap: .6rem; align-items: flex-end; flex-wrap: wrap; }
  .row > * { flex: 0 0 auto; }
  .row .grow { flex: 1 1 12rem; }
"""

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
<style>{_CSS}</style></head><body>
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
    loud = source in (ENV_SOURCE, OTHER_FILE_SOURCE, CLI_SOURCE)
    css = "src env" if loud else "src"
    title = f' title="{esc(detail)}"' if detail else ""
    return f'<span class="{css}"{title}>aus: {esc(source)}</span>'
