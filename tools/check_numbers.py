"""Fail the build when a document quotes a figure the code no longer produces.

Reads docs/metrics.json (written by collect_metrics.py) and holds every checked document to it.
A metric is guarded by anchor phrases: the exact wording with `{}` where the value goes and
`{m:other}` where a neighbouring metric's value goes, so a table cell is pinned by the cells
beside it rather than by its bare digits. Three checks run:

1. Presence: at least one anchor of every metric appears, on one line, in some checked document.
2. Staleness: any occurrence of an anchor's wording with a different number is a stale claim.
3. The banner's text nodes carry the headline figures and are checked the same way.

Then a reverse scan lists the numbers in the README that no metric accounts for, with code
spans, fences, URLs and HTML attributes excluded, so a figure nothing re-measures is visible.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METRICS = ROOT / "docs" / "metrics.json"
NUMBER = r"(\d[\d,]*(?:\.\d+)?)"
ALLOWED_UNANCHORED = {
    "3.11",
    "3.12",
    "3.13",
    "2026",
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "350",  # the About text limit
    "62.0",  # the fixture's API version
    "99",  # the "75 to 99%" coverage bucket label
    "50,000",  # the query rows limit, excluded from the policy on purpose (ADR-005)
}


def variants(value) -> list[str]:
    if isinstance(value, bool):
        return [str(value)]
    if isinstance(value, int):
        return [f"{value:,}", str(value)] if value >= 1000 else [str(value)]
    if isinstance(value, float):
        text = f"{value:g}"
        if value == int(value):
            return [f"{value:.1f}", str(int(value))]
        return [text]
    return [str(value)]


def normalise(text: str) -> str:
    return text.replace(",", "")


def substitute_neighbours(anchor: str, metrics: dict) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in metrics:
            raise SystemExit(f"anchor {anchor!r} names unknown metric {key!r}")
        return variants(metrics[key])[0]

    return re.sub(r"\{m:([a-z0-9_]+)\}", repl, anchor)


def phrases(anchor: str, value, metrics: dict) -> list[str]:
    filled = substitute_neighbours(anchor, metrics)
    return [filled.replace("{}", v) for v in variants(value)]


def pattern(anchor: str, metrics: dict) -> re.Pattern:
    filled = substitute_neighbours(anchor, metrics)
    parts = [re.escape(p) for p in filled.split("{}")]
    return re.compile(NUMBER.join(parts))


def strip_code(markdown: str) -> str:
    """Remove fenced blocks, inline code, URLs and HTML attribute values for the reverse scan."""
    keep_lines = lambda m: "\n" * m.group(0).count("\n")  # noqa: E731
    text = re.sub(r"```.*?```", keep_lines, markdown, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"<[^>]+>", keep_lines, text, flags=re.DOTALL)
    text = re.sub(r"\]\([^)]*\)", " ", text)
    return text


def banner_text(path: Path) -> str:
    svg = path.read_text(encoding="utf-8")
    text = re.sub(r"<style>.*?</style>", " ", svg, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def main() -> int:
    payload = json.loads(METRICS.read_text(encoding="utf-8"))
    metrics, anchors = payload["metrics"], payload["anchors"]
    documents = {}
    missing_docs = []
    for rel in payload["checked_documents"]:
        path = ROOT / rel
        if not path.exists():
            missing_docs.append(rel)
            continue
        documents[rel] = path.read_text(encoding="utf-8")

    gaps: list[str] = []
    stale: list[str] = []
    for key, value in metrics.items():
        if key not in anchors:
            if isinstance(value, int | float) and not isinstance(value, bool) and value < 6:
                gaps.append(f"{key} = {value}: small number with no anchor phrase")
            continue
        found = False
        for anchor in anchors[key]:
            wanted = phrases(anchor, value, metrics)
            if any(any(p in text for p in wanted) for text in documents.values()):
                found = True
            regex = pattern(anchor, metrics)
            for rel, text in documents.items():
                for match in regex.finditer(text):
                    if normalise(match.group(1)) not in {normalise(v) for v in variants(value)}:
                        line = text.count("\n", 0, match.start()) + 1
                        stale.append(
                            f"{rel}:{line}: {match.group(0)!r} but {key} is {variants(value)[0]}"
                        )
        if not found:
            gaps.append(
                f"{key} = {variants(value)[0]}: none of {anchors[key]} found in any document"
            )

    banner = payload.get("banner")
    if banner:
        path = ROOT / banner["path"]
        if not path.exists():
            missing_docs.append(banner["path"])
        else:
            text = banner_text(path)
            for key, anchor in banner["figures"].items():
                wanted = phrases(anchor, metrics[key], metrics)
                if not any(p in text for p in wanted):
                    gaps.append(
                        f"banner: {key} = {variants(metrics[key])[0]}: {anchor!r} not in the banner"
                    )
                for match in pattern(anchor, metrics).finditer(text):
                    if normalise(match.group(1)) not in {
                        normalise(v) for v in variants(metrics[key])
                    }:
                        stale.append(
                            f"banner: {match.group(0)!r} but {key} is {variants(metrics[key])[0]}"
                        )

    known = {normalise(v) for value in metrics.values() for v in variants(value)}
    unanchored = []
    readme = documents.get("README.md", "")
    for line_number, line in enumerate(strip_code(readme).splitlines(), start=1):
        for number in re.findall(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?(?![\w.])", line):
            if normalise(number) not in known and number not in ALLOWED_UNANCHORED:
                unanchored.append(f"README.md:{line_number}: {number}")

    for item in missing_docs:
        print(f"MISSING  {item}")
    for item in gaps:
        print(f"GAP      {item}")
    for item in stale:
        print(f"STALE    {item}")
    for item in unanchored:
        print(f"UNANCHORED {item}")
    checked = sum(1 for k in metrics if k in anchors)
    print(
        f"checked {checked} anchored metrics across {len(documents)} documents: "
        f"{len(gaps)} gaps, {len(stale)} stale, {len(missing_docs)} missing documents, "
        f"{len(unanchored)} unanchored README numbers"
    )
    return 1 if gaps or stale or missing_docs else 0


if __name__ == "__main__":
    sys.exit(main())
