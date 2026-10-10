# /// script
# requires-python = ">=3.11"
# dependencies = ["resvg-py==0.5.0"]
# ///
"""Render icon.png from icon.svg, the fallback for clients that show no SVG.

Run it after every change to the SVG and commit both files together:

    uv run assets/render_icon.py

uv reads the dependency above and runs the script in a throwaway environment,
so the renderer never enters the project's own dependencies. resvg is pinned
because another version may draw the same SVG a few pixels differently.
"""

from __future__ import annotations

from pathlib import Path

import resvg_py

SIZE = 512
HERE = Path(__file__).resolve().parent
SVG = HERE / "icon.svg"
PNG = HERE / "icon.png"


def main() -> None:
    png = resvg_py.svg_to_bytes(
        svg_string=SVG.read_text(encoding="utf-8"), width=SIZE, height=SIZE
    )
    PNG.write_bytes(png)
    print(f"{PNG.name}: {SIZE}x{SIZE}, {len(png)} bytes")


if __name__ == "__main__":
    main()
