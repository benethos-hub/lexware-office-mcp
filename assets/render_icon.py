# /// script
# requires-python = ">=3.11"
# dependencies = ["resvg-py==0.5.0"]
# ///
"""Render the PNGs in brand/ from brand/icon.svg.

- icon.png, 512x512, the fallback for clients that show no SVG.
- social-preview.png, 1280x640, the image GitHub shows when the repository
  link is shared. It is uploaded by hand under Settings > General > Social
  preview, there is no API for it.

The organisation's brand check in CI wants all three in brand/, and each PNG
committed with or after the last change to the SVG. The copies directly in
this folder are the addresses 0.5.2 and earlier link to, and are not
rendered any more.

Run it after every change to the SVG or to the text below and commit the
results together:

    uv run assets/render_icon.py

uv reads the dependency above and runs the script in a throwaway environment,
so the renderer never enters the project's own dependencies. resvg is pinned
because another version may draw the same SVG a few pixels differently. The
preview's text is set in the system's sans-serif font, so it was rendered on
Windows (Segoe UI) and looks a little different elsewhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import resvg_py

HERE = Path(__file__).resolve().parent / "brand"
ICON_SVG = HERE / "icon.svg"
ICON_PNG = HERE / "icon.png"
ICON_SIZE = 512
PREVIEW_PNG = HERE / "social-preview.png"
PREVIEW_WIDTH, PREVIEW_HEIGHT = 1280, 640

# The preview's words. Unofficial is spelled out and nothing borrows
# Lexware's look: the icon and the colours are the project's own. No version
# number, since the image is uploaded by hand and would fall behind.
PREVIEW = """\
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640"
     viewBox="0 0 1280 640">
  <defs>
    <radialGradient id="sp-bg" cx="0.3" cy="0.4" r="0.9">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="55%" stop-color="#F5F6FE"/>
      <stop offset="100%" stop-color="#E4E8FC"/>
    </radialGradient>
    <filter id="sp-shadow" x="-20%" y="-20%" width="140%" height="150%">
      <feDropShadow dx="0" dy="14" stdDeviation="16" flood-color="#312E81"
                    flood-opacity="0.22"/>
    </filter>
  </defs>
  <rect width="1280" height="640" fill="url(#sp-bg)"/>
  <rect x="0" y="628" width="1280" height="12" fill="#4F46E5"/>
  <g filter="url(#sp-shadow)">{icon}</g>
  <g font-family="Segoe UI, Inter, Helvetica, Arial, sans-serif">
    <text x="380" y="200" font-family="Consolas, Menlo, monospace" font-size="26"
          fill="#4F46E5">benethos-lexware-office-mcp</text>
    <g font-size="56" font-weight="700" fill="#1E1B4B">
      <text x="380" y="272">Unofficial Lexware Office</text>
      <text x="380" y="338">MCP Server</text>
    </g>
    <g font-size="25" fill="#475569">
      <text x="380" y="398">Invoices, vouchers, contacts and articles for any</text>
      <text x="380" y="434">MCP client, with only the tools you switch on.</text>
    </g>
    {chips}
    <text x="380" y="584" font-size="18" fill="#64748B"
          >The public API with your own key. Not affiliated with Lexware.</text>
  </g>
</svg>
"""

CHIPS = ("PyPI", "Docker", "Claude Desktop extension", "MCP Registry")


def _chips(x: int, y: int) -> str:
    """Rounded labels in one row. Widths are estimated from the text length."""
    parts = []
    for label in CHIPS:
        width = round(len(label) * 9.3) + 40
        parts.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="38" rx="19" '
            'fill="#4F46E5" fill-opacity="0.08" '
            'stroke="#4F46E5" stroke-opacity="0.45"/>'
            f'<text x="{x + width / 2}" y="{y + 26}" font-size="19" fill="#312E81" '
            f'text-anchor="middle">{label}</text>'
        )
        x += width + 14
    return "".join(parts)


def _icon(x: int, y: int, size: int) -> str:
    """icon.svg as a nested svg, its ids prefixed so they cannot clash."""
    svg = ICON_SVG.read_text(encoding="utf-8")
    svg = re.sub(r'id="([^"]+)"', r'id="ic-\1"', svg)
    svg = re.sub(r"url\(#([^)]+)\)", r"url(#ic-\1)", svg)
    return re.sub(
        r"<svg [^>]*>",
        f'<svg x="{x}" y="{y}" width="{size}" height="{size}" viewBox="0 0 256 256">',
        svg,
        count=1,
    )


def render(svg: str, width: int, height: int, target: Path) -> None:
    png = resvg_py.svg_to_bytes(svg_string=svg, width=width, height=height)
    target.write_bytes(png)
    print(f"{target.name}: {width}x{height}, {len(png)} bytes")


def main() -> None:
    render(ICON_SVG.read_text(encoding="utf-8"), ICON_SIZE, ICON_SIZE, ICON_PNG)
    preview = PREVIEW.format(icon=_icon(80, 200, 240), chips=_chips(380, 478))
    render(preview, PREVIEW_WIDTH, PREVIEW_HEIGHT, PREVIEW_PNG)


if __name__ == "__main__":
    main()
