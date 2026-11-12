"""Render the architecture diagram to a committed SVG.

Reads the Mermaid source from the README fence labelled `mermaid-source`, renders it with the
mermaid library through Playwright (mermaid-cli as a fallback), turns htmlLabels off at both
levels so the file is valid SVG without <foreignObject>, rewrites the root element with explicit
width and height from the viewBox, paints an opaque background, and writes
docs/assets/architecture.svg plus a manifest. GitHub is never asked to render a Mermaid fence.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
OUT = ROOT / "docs" / "assets" / "architecture.svg"
MANIFEST = ROOT / "docs" / "assets" / "architecture.json"
CONFIG = {
    "startOnLoad": False,
    "htmlLabels": False,
    "theme": "neutral",
    "flowchart": {"htmlLabels": False, "useMaxWidth": False, "padding": 12, "nodeSpacing": 28},
}


def source_from_readme() -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(r"```mermaid-source\n(.*?)```", text, re.DOTALL)
    if not match:
        raise SystemExit("README has no ```mermaid-source fence")
    return match.group(1)


def find_mermaid_js() -> Path | None:
    candidates = []
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, check=True)
        candidates.append(Path(root.stdout.strip()))
    except (OSError, subprocess.CalledProcessError):
        pass
    candidates.append(Path("/opt/npm-tools/node_modules"))
    for base in candidates:
        for rel in (
            "mermaid/dist/mermaid.min.js",
            "@mermaid-js/mermaid-cli/node_modules/mermaid/dist/mermaid.min.js",
        ):
            path = base / rel
            if path.exists():
                return path
        found = sorted(base.glob("**/mermaid/dist/mermaid.min.js"))
        if found:
            return found[0]
    return None


def render_with_playwright(source: str, library: Path) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<html><body><div id='out'></div></body></html>")
        page.add_script_tag(path=str(library))
        svg = page.evaluate(
            """async ([source, config]) => {
                mermaid.initialize(config);
                const { svg } = await mermaid.render('arch', source);
                return svg;
            }""",
            [source, CONFIG],
        )
        browser.close()
    return svg


def render_with_mmdc(source: str) -> str:
    mmdc = shutil.which("mmdc")
    if mmdc is None:
        raise SystemExit("neither mermaid.min.js nor mmdc is available")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "arch.mmd"
        cfg = Path(tmp) / "config.json"
        out = Path(tmp) / "arch.svg"
        src.write_text(source, encoding="utf-8")
        cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
        subprocess.run(
            [mmdc, "-i", str(src), "-o", str(out), "-c", str(cfg), "-b", "white"],
            check=True,
            capture_output=True,
        )
        return out.read_text(encoding="utf-8")


def finish(svg: str) -> tuple[str, int, int]:
    if "<foreignObject" in svg:
        raise SystemExit("rendered SVG contains <foreignObject>; htmlLabels must be off")
    match = re.search(r'viewBox="([\d.\-]+) ([\d.\-]+) ([\d.\-]+) ([\d.\-]+)"', svg)
    if not match:
        raise SystemExit("rendered SVG has no viewBox")
    x, y, width, height = (float(v) for v in match.groups())
    width_px, height_px = int(round(width)), int(round(height))
    svg = re.sub(r'<svg([^>]*?)\s+width="[^"]*"', r"<svg\1", svg, count=1)
    svg = re.sub(r'<svg([^>]*?)\s+height="[^"]*"', r"<svg\1", svg, count=1)
    svg = re.sub(r'<svg([^>]*?)\s+style="[^"]*"', r"<svg\1", svg, count=1)
    svg = svg.replace("<svg", f'<svg width="{width_px}" height="{height_px}"', 1)
    background = f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#ffffff"/>'
    svg = re.sub(r"(<svg[^>]*>)", r"\1" + background, svg, count=1)
    return svg, width_px, height_px


def main() -> int:
    source = source_from_readme()
    library = find_mermaid_js()
    renderer = "playwright+mermaid.min.js" if library else "mmdc"
    svg = render_with_playwright(source, library) if library else render_with_mmdc(source)
    svg, width, height = finish(svg)
    OUT.write_text(svg, encoding="utf-8")
    MANIFEST.write_text(
        json.dumps(
            {
                "source": "README.md fence mermaid-source",
                "renderer": renderer,
                "width": width,
                "height": height,
                "htmlLabels": False,
                "foreignObject": "<foreignObject" in svg,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({width}x{height}) with {renderer}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
