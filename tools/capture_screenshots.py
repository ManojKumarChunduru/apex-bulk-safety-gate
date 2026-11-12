"""Section-framed screenshots of the real HTML report, with the verdict badge read back.

Builds the report fresh with `absg gate --html`, opens it in Chromium, frames each shot by the
document offset of a named heading rather than by a pixel crop (so a longer table moves the
frame instead of cutting it), and reads the computed style of the verdict badge, failing the run
if it is invisible. Writes docs/evidence/report-*.png and a manifest naming each image's
headings and the badge reading.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / "report.html"
EVIDENCE = ROOT / "docs" / "evidence"
FRAMES = [
    ("report-coverage.png", "coverage-against-breach-size", "findings"),
    ("report-findings.png", "findings", "undecidable"),
    ("report-undecidable.png", "undecidable", "end"),
]


def build_report() -> int:
    REPORT.parent.mkdir(exist_ok=True)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "absg",
            "gate",
            "--project",
            "fixture",
            "--coverage",
            "fixture/coverage/test-result-codecoverage.json",
            "--html",
            str(REPORT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in (0, 1, 2):
        raise SystemExit(f"absg gate failed with {completed.returncode}: {completed.stderr}")
    return completed.returncode


def main() -> int:
    from playwright.sync_api import sync_playwright

    exit_code = build_report()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    manifest = {"report": "reports/report.html", "gate_exit_code": exit_code, "images": []}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1180, "height": 900}, device_scale_factor=2)
        page.goto(REPORT.as_uri())
        page.wait_for_load_state("load")
        badge = page.evaluate(
            """() => {
              const badge = document.querySelector('p.verdict .badge');
              if (!badge) return null;
              const style = getComputedStyle(badge);
              return {text: badge.textContent, colour: style.color,
                      background: style.backgroundColor,
                      visible: badge.offsetWidth > 0 && badge.offsetHeight > 0};
            }"""
        )
        if badge is None or not badge["visible"]:
            raise SystemExit("the verdict badge is missing or has no size")
        if badge["colour"] == badge["background"]:
            raise SystemExit(f"the verdict badge is invisible: {badge}")
        manifest["badge"] = badge
        for filename, start, end in FRAMES:
            offsets = page.evaluate(
                """([start, end]) => {
                  const a = document.getElementById(start);
                  const b = document.getElementById(end);
                  if (!a || !b) return null;
                  const top = a.getBoundingClientRect().top + window.scrollY;
                  const bottom = b.getBoundingClientRect().top + window.scrollY;
                  return {top, bottom};
                }""",
                [start, end],
            )
            if offsets is None:
                raise SystemExit(f"heading {start!r} or {end!r} no longer exists in the report")
            top = max(int(offsets["top"]) - 12, 0)
            height = int(offsets["bottom"]) - top - 8
            page.screenshot(
                path=str(EVIDENCE / filename),
                full_page=True,
                clip={"x": 0, "y": top, "width": 1180, "height": max(height, 80)},
            )
            manifest["images"].append(
                {"file": f"docs/evidence/{filename}", "from": start, "to": end, "height": height}
            )
        browser.close()
    (EVIDENCE / "screenshots.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    for image in manifest["images"]:
        print(f"wrote {image['file']} ({image['from']} to {image['to']})")
    print(f"badge: {badge['text']} {badge['colour']} on {badge['background']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
