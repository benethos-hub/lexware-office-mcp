"""The templates of the configuration interface: the environment, its
filters, ``render``, and the static files beside them.

**The only module that imports ``jinja2``**, which ``tests/test_layers.py``
holds it to. Everything else hands a template name and a context to
:func:`render` and gets bytes back.

Autoescaping is on for every template and nothing is marked safe, so a
profile name or a path a person typed shows as text. ``StrictUndefined``
makes a typo in a template raise rather than render an empty cell.
Formatting happens in the filters here, never in a template.

The static files are a fixed list, not a directory served as it is: a
request names one of them or is answered with a 404, so no path a browser
sends ever reaches the filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2

from .. import __version__

__all__ = ["STATIC_DIR", "STATIC_FILES", "TEMPLATE_DIR", "de", "render", "static"]

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"

# What `/static/<name>` can answer, and as which type.
STATIC_FILES: dict[str, str] = {
    "app.css": "text/css",
    "app.js": "text/javascript",
}


def de(number: float) -> str:
    """A number the way it is read here: 50.630 rather than 50,630."""
    return f"{number:,.0f}".replace(",", ".")


_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
    autoescape=True,
    undefined=jinja2.StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_environment.filters.update(de=de)
_environment.globals.update(VERSION=__version__)


def render(template: str, **context: Any) -> bytes:
    """One template with its context, as the UTF-8 a response sends."""
    return _environment.get_template(template).render(**context).encode("utf-8")


def static(name: str) -> tuple[bytes, str] | None:
    """A static file and its type, or ``None`` for a name not on the list."""
    kind = STATIC_FILES.get(name)
    if kind is None:
        return None
    return (STATIC_DIR / name).read_bytes(), kind
