"""Shared plumbing for the experiments: run the gate on the fixture, write JSON, print a table."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from absg.coverage import load_coverage  # noqa: E402
from absg.limits import Policy  # noqa: E402
from absg.project import load_project  # noqa: E402
from absg.tests_apex import read_exercises  # noqa: E402
from absg.verdict import GateResult, run_gate  # noqa: E402

FIXTURE = ROOT / "fixture"
COVERAGE = FIXTURE / "coverage" / "test-result-codecoverage.json"
OUT = ROOT / "docs" / "experiments"
GROUND_TRUTH = FIXTURE / "EXPECTED_FINDINGS.json"


def gate(**policy_overrides) -> GateResult:
    policy = Policy()
    for key, value in policy_overrides.items():
        setattr(policy, key, value)
    return run_gate(load_project(FIXTURE), policy, load_coverage(COVERAGE))


def exercises():
    return read_exercises(load_project(FIXTURE))


def write(name: str, payload: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def table(headers: list[str], rows: list[list]) -> str:
    cells = [[str(c) for c in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))]
    lines.append("  ".join("-" * w for w in widths))
    lines.extend("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) for row in cells)
    return "\n".join(lines)


def pct(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0
