"""Record a replay of the gate's real output as a GIF and an MP4.

A replay, not a screen recording: each command runs once and its stdout, stderr, exit code and
wall time are captured; a self-contained HTML player then types the command and reveals the
captured output paced by that command's measured duration; Playwright records the page; ffmpeg
transcodes to an MP4 and a two-pass palette GIF. Every line of terminal text is captured output,
and docs/evidence/manifest.json lists every command with its exit code.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "evidence"
COVERAGE = "fixture/coverage/test-result-codecoverage.json"
SEGMENTS = [
    ("the policy the gate compares against", ["absg", "limits"]),
    (
        "the verdict at 200 records, next to coverage and the largest tested size",
        ["absg", "gate", "--project", "fixture", "--coverage", COVERAGE],
    ),
    (
        "the closest miss: tested at 100, breaches at 101, through a chain",
        ["absg", "explain", "AccountTaskTrigger", "--project", "fixture"],
    ),
    (
        "the same project at one Bulk API batch: bulkified triggers breach too",
        ["absg", "gate", "--project", "fixture", "--records", "10000"],
    ),
    ("every figure in the documents is re-measured", ["python", "tools/check_numbers.py"]),
]
WIDTH, HEIGHT, FPS, GIF_WIDTH, COLOURS = 960, 600, 6, 800, 32


def run_segment(argv: list[str]) -> dict:
    if argv[0] == "absg":
        argv = [sys.executable, "-m", "absg", *argv[1:]]
    elif argv[0] == "python":
        argv = [sys.executable, *argv[1:]]
    started = time.perf_counter()
    completed = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    return {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exit_code": completed.returncode,
        "wall_seconds": round(time.perf_counter() - started, 3),
    }


def player_html(segments: list[dict]) -> str:
    data = json.dumps(segments)
    return f"""<!doctype html><html><head><meta charset='utf-8'><style>
html, body {{ margin: 0; background: #0f172a; }}
#term {{ width: {WIDTH}px; height: {HEIGHT}px; box-sizing: border-box; padding: 18px 22px;
  font: 13px/1.35 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: #e2e8f0;
  white-space: pre; overflow: hidden; }}
.cmd {{ color: #7dd3fc; }} .cmt {{ color: #94a3b8; }}
.err {{ color: #fca5a5; }} .ok {{ color: #86efac; }}
</style></head><body><div id='term'></div><script>
const segments = {data};
const term = document.getElementById('term');
const sleep = ms => new Promise(r => setTimeout(r, ms));
function trim() {{
  const lines = term.innerHTML.split('\\n');
  const max = Math.floor(({HEIGHT} - 36) / (13 * 1.35));
  if (lines.length > max) term.innerHTML = lines.slice(lines.length - max).join('\\n');
}}
async function type(text, cls) {{
  for (const ch of text) {{ term.innerHTML += ch; await sleep(28); }}
}}
async function main() {{
  for (const s of segments) {{
    term.innerHTML += "<span class='cmt'># " + s.title + "</span>\\n";
    term.innerHTML += "<span class='cmd'>$ </span>";
    await type(s.command.replace(/&/g,'&amp;').replace(/</g,'&lt;'), 'cmd');
    term.innerHTML += '\\n';
    await sleep(250);
    const out = (s.stdout + (s.stderr ? "\\n" + s.stderr : "")).replace(/\\s+$/, '');
    const lines = out.split('\\n');
    const pace = Math.max(12, Math.min(90, (s.wall_seconds * 1000) / Math.max(lines.length, 1)));
    for (const line of lines) {{
      term.innerHTML += line.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '\\n';
      trim();
      await sleep(pace);
    }}
    const cls = s.exit_code === 0 ? 'ok' : 'err';
    term.innerHTML += "<span class='" + cls + "'>exit " + s.exit_code + "</span>\\n\\n";
    trim();
    await sleep(1400);
  }}
  document.title = 'done';
}}
main();
</script></body></html>"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is required to transcode the recording")
    run_segment(["absg", "limits"])  # warm the import so the first segment's pacing is honest
    segments = []
    for title, argv in SEGMENTS:
        captured = run_segment(argv)
        segments.append({"title": title, "command": " ".join(argv), **captured})
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    player = EVIDENCE / "player.html"
    player.write_text(player_html(segments), encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={"width": WIDTH, "height": HEIGHT},
                record_video_dir=tmp,
                record_video_size={"width": WIDTH, "height": HEIGHT},
            )
            page = context.new_page()
            page.goto(player.as_uri())
            page.wait_for_function("document.title === 'done'", timeout=180_000)
            page.wait_for_timeout(800)
            video = page.video
            context.close()
            browser.close()
            webm = Path(video.path())
        mp4 = EVIDENCE / "demo.mp4"
        gif = EVIDENCE / "demo.gif"
        palette = Path(tmp) / "palette.png"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(webm),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "28",
                "-preset",
                "veryslow",
                "-an",
                str(mp4),
            ],
            check=True,
        )
        filters = f"fps={FPS},scale={GIF_WIDTH}:-1:flags=lanczos"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(webm),
                "-vf",
                f"{filters},palettegen=max_colors={COLOURS}:stats_mode=diff",
                str(palette),
            ],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(webm),
                "-i",
                str(palette),
                "-lavfi",
                f"{filters} [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5"
                ":diff_mode=rectangle",
                str(gif),
            ],
            check=True,
        )
    manifest = {
        "kind": "replay of captured stdout, paced by measured wall time; not a screen recording",
        "recorded": {"width": WIDTH, "height": HEIGHT},
        "gif": {"fps": FPS, "width": GIF_WIDTH, "colours": COLOURS, "bytes": gif.stat().st_size},
        "mp4": {"bytes": mp4.stat().st_size},
        "segments": [
            {k: v for k, v in s.items() if k not in {"stdout", "stderr"}}
            | {"stdout_lines": s["stdout"].count("\n"), "stderr_lines": s["stderr"].count("\n")}
            for s in segments
        ],
        "note": "wall_seconds are pacing data for the replay and are not published as results",
    }
    (EVIDENCE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {gif} ({gif.stat().st_size / 1e6:.1f} MB)")
    print(f"wrote {mp4} ({mp4.stat().st_size / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
