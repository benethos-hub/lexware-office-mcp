"""The frame of the configuration interface: templates, static files, colours.

What every page shares rather than what one page says: the content security
policy and what it rules out, the two static files and nothing beside them,
the palette's contrast in both modes, and the rules the templates keep.
"""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import jinja2
import pytest

from benethos_lexware_office_mcp.configui import pages, probe, templates
from benethos_lexware_office_mcp.configui.app import ConfigServer, Handler
from benethos_lexware_office_mcp.configui.state import Installation
from benethos_lexware_office_mcp.settings import Settings

PAGES = ("/", "/credentials", "/permissions", "/settings")


@pytest.fixture
def base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_configuration_from_this_machine: None,
) -> Iterator[str]:
    monkeypatch.setattr(probe, "_last", None)
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    server = ConfigServer(("127.0.0.1", 0), Handler)
    server.installation = Installation(
        settings=Settings(tool_policy_path=tmp_path / "tools.json"),
        env_path=env,
        cwd=tmp_path,
    )
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def fetch(url: str) -> tuple[int, str, dict[str, str]]:
    try:
        with urllib.request.urlopen(url) as response:
            return (
                response.status,
                response.read().decode("utf-8"),
                dict(response.headers),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


# -- static files and the policy --------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind"), [("app.css", "text/css"), ("app.js", "text/javascript")]
)
def test_the_static_files_are_served(base: str, name: str, kind: str) -> None:
    status, body, headers = fetch(f"{base}/static/{name}")

    assert status == 200
    assert headers["Content-Type"].startswith(kind)
    assert body == (templates.STATIC_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "path",
    [
        "/static/",
        "/static/missing.css",
        "/static/../templates.py",
        "/static/%2e%2e/templates.py",
        "/static/app.css/x",
    ],
)
def test_nothing_else_is_served_from_there(base: str, path: str) -> None:
    """A fixed list, so no path a browser sends reaches the filesystem."""
    assert fetch(base + path)[0] == 404


@pytest.mark.parametrize("path", [*PAGES, "/static/app.css", "/nope"])
def test_every_response_carries_the_policy(base: str, path: str) -> None:
    policy = fetch(base + path)[2]["Content-Security-Policy"]

    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "form-action 'self'" in policy


@pytest.mark.parametrize("path", PAGES)
def test_no_page_has_inline_script_or_style(base: str, path: str) -> None:
    """The policy would block them, so one would be a page that breaks."""
    body = fetch(base + path)[1]

    assert re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", body) == []
    assert "<style" not in body
    assert " style=" not in body
    assert re.findall(r"\son[a-z]+=", body) == []


@pytest.mark.parametrize("path", PAGES)
def test_a_page_names_its_static_files(base: str, path: str) -> None:
    body = fetch(base + path)[1]

    assert '<link rel="stylesheet" href="/static/app.css">' in body
    assert '<script src="/static/app.js" defer></script>' in body


# -- the frame ---------------------------------------------------------------


@pytest.mark.parametrize("path", PAGES)
def test_the_sidebar_marks_the_page_it_is_on(base: str, path: str) -> None:
    body = fetch(base + path)[1]

    assert f'<a href="{path}" class="active" aria-current="page">' in body
    assert body.count('aria-current="page"') == 1


def test_the_footer_names_the_version(base: str) -> None:
    from benethos_lexware_office_mcp import __version__

    assert f"benethos-lexware-office-mcp {__version__}</footer>" in fetch(base)[1]


def test_an_unknown_address_is_a_page_in_the_frame(base: str) -> None:
    status, body, headers = fetch(base + "/nope")

    assert status == 404
    assert headers["Content-Type"].startswith("text/html")
    assert "Diese Adresse gibt es nicht." in body
    assert 'class="sidebar"' in body


def test_a_typo_in_a_template_raises_rather_than_rendering_nothing() -> None:
    with pytest.raises(jinja2.UndefinedError):
        templates.render("pages/error.html", title="x", here="")


def test_text_is_escaped(tmp_path: Path) -> None:
    page = pages.error("Abgelehnt", "<script>alert(1)</script>")

    body = page.html().decode("utf-8")

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<script>alert" not in body


# -- the rules the templates keep --------------------------------------------


def _templates() -> list[Path]:
    return sorted(templates.TEMPLATE_DIR.rglob("*.html"))


def test_no_template_marks_text_as_safe() -> None:
    """Everything a page shows is escaped. Markup comes from a macro."""
    marked = [
        path.name
        for path in _templates()
        if re.search(r"\|\s*safe\b|Markup\(", path.read_text(encoding="utf-8"))
    ]
    assert marked == []


def test_every_class_a_template_names_is_styled() -> None:
    """A class without a rule in app.css is a leftover or a typo."""
    css = (templates.STATIC_DIR / "app.css").read_text(encoding="utf-8")
    styled = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
    unstyled = set()
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        # Fixed names only, a class a template computes is left out.
        for names in re.findall(r'class="([^"{}]*)"', text):
            unstyled |= {f"{path.name}: {n}" for n in names.split() if n not in styled}
    assert not unstyled, sorted(unstyled)


def test_every_static_file_on_the_list_exists() -> None:
    assert sorted(templates.STATIC_FILES) == sorted(
        path.name for path in templates.STATIC_DIR.iterdir()
    )


# -- the palette ---------------------------------------------------------------


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-f]{6});", block))


def _contrast(a: str, b: str) -> float:
    def luminance(colour: str) -> float:
        parts = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = (
            p / 12.92 if p <= 0.03928 else ((p + 0.055) / 1.055) ** 2.4 for p in parts
        )
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_every_text_colour_is_readable_on_its_backgrounds() -> None:
    """WCAG AA for small text, 4.5:1, in light and in dark mode."""
    css = (templates.STATIC_DIR / "app.css").read_text(encoding="utf-8")
    split = css.index("@media (prefers-color-scheme: dark)")
    light = _tokens(css[:split])
    dark = {**light, **_tokens(css[split:])}
    texts = ("text", "text-muted", "text-faint", "accent", "ok", "err", "warn")
    pairs = [(t, b) for t in texts for b in ("bg", "surface", "surface-2")] + [
        ("on-accent", "accent"),
        ("accent", "accent-soft"),
        ("ok", "ok-soft"),
        ("err", "err-soft"),
        ("warn", "warn-soft"),
        ("text", "surface-2"),
    ]
    for mode, tokens in (("light", light), ("dark", dark)):
        for text, background in pairs:
            ratio = _contrast(tokens[text], tokens[background])
            assert ratio >= 4.5, f"{mode}: {text} on {background} is {ratio:.2f}:1"
