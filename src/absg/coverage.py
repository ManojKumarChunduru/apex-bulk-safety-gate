"""The coverage report, read for exactly one thing: the percentage each trigger was given.

This file exists so the gate can place its verdict next to the number the deploy gate trusts.
The report is the JSON that `sf apex run test --code-coverage --output-dir <dir>` writes as
`test-result-codecoverage.json`: a list of entries, one per class or trigger, each with a name,
a line count and a covered percentage. The gate validates the shape at the boundary and refuses
a malformed file with the usage exit code, because a coverage number read from a file it only
half understood would be a worse input than none. ADR-005 records that the fixture's copy of
this file is declared, not produced by a CLI run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class CoverageError(ValueError):
    pass


@dataclass(frozen=True)
class CoverageEntry:
    name: str
    total_lines: int
    total_covered: int
    covered_percent: float


def _bare_name(name: str) -> str:
    # The CLI writes names such as "no-map/AccountTrigger"; keep the part after the last slash.
    return name.rsplit("/", 1)[-1]


def load_coverage(path: str | Path) -> dict[str, CoverageEntry]:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CoverageError(f"cannot read coverage report {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CoverageError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(data, list):
        raise CoverageError(f"{path}: expected a JSON array of coverage entries")
    entries: dict[str, CoverageEntry] = {}
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise CoverageError(f"{path}: entry {index} is not an object")
        for key in ("name", "totalLines", "totalCovered", "coveredPercent"):
            if key not in item:
                raise CoverageError(f"{path}: entry {index} is missing {key!r}")
        name = item["name"]
        if not isinstance(name, str) or not name:
            raise CoverageError(f"{path}: entry {index} has a non-string name")
        total_lines, total_covered = item["totalLines"], item["totalCovered"]
        if not isinstance(total_lines, int) or not isinstance(total_covered, int):
            raise CoverageError(f"{path}: entry {name!r} line counts must be integers")
        if total_lines < 0 or total_covered < 0 or total_covered > total_lines:
            raise CoverageError(
                f"{path}: entry {name!r} has {total_covered} covered of {total_lines} lines"
            )
        percent = item["coveredPercent"]
        if isinstance(percent, bool) or not isinstance(percent, int | float):
            raise CoverageError(f"{path}: entry {name!r} coveredPercent must be a number")
        if not 0 <= percent <= 100:
            raise CoverageError(f"{path}: entry {name!r} coveredPercent {percent} is out of range")
        lines = item.get("lines")
        if lines is not None:
            if not isinstance(lines, dict):
                raise CoverageError(f"{path}: entry {name!r} lines must be an object")
            if len(lines) != total_lines:
                raise CoverageError(
                    f"{path}: entry {name!r} lists {len(lines)} lines "
                    f"but totalLines is {total_lines}"
                )
            covered_lines = sum(1 for v in lines.values() if v == 1)
            if covered_lines != total_covered:
                raise CoverageError(
                    f"{path}: entry {name!r} marks {covered_lines} lines covered "
                    f"but totalCovered is {total_covered}"
                )
        bare = _bare_name(name)
        if bare in entries:
            raise CoverageError(f"{path}: duplicate coverage entry for {bare!r}")
        entries[bare] = CoverageEntry(bare, total_lines, total_covered, float(percent))
    return entries
