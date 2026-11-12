"""Re-measure every published figure into docs/metrics.json.

Nothing in this file is typed by hand. The test count and coverage come from the junit and
coverage reports pytest wrote (or from a run this script starts when they are absent), every
other number comes from the experiment JSON or from the gate itself, and the anchor phrases are
the exact wording the documents must use. `tools/check_numbers.py` then holds the documents to
these values.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

from absg.coverage import load_coverage  # noqa: E402
from absg.limits import Policy  # noqa: E402
from absg.project import load_project  # noqa: E402
from absg.verdict import run_gate  # noqa: E402

REPORTS = ROOT / "reports"
EXPERIMENTS = ROOT / "docs" / "experiments"
FIXTURE = ROOT / "fixture"
COVERAGE_REPORT = FIXTURE / "coverage" / "test-result-codecoverage.json"
CHECKED_DOCUMENTS = [
    "README.md",
    "fixture/README.md",
    "docs/adr/ADR-001-count-provenance-not-line-coverage.md",
    "docs/adr/ADR-002-purpose-built-extractor-with-a-refusal-set.md",
    "docs/adr/ADR-003-breach-size-not-a-boolean.md",
    "docs/adr/ADR-004-standard-library-and-a-limits-policy.md",
    "docs/adr/ADR-005-what-a-committed-fixture-cannot-establish.md",
]


def run_tests() -> None:
    REPORTS.mkdir(exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={REPORTS / 'junit.xml'}",
            "--cov=absg",
            f"--cov-report=json:{REPORTS / 'coverage.json'}",
            f"--cov-report=xml:{REPORTS / 'coverage.xml'}",
        ],
        cwd=ROOT,
        check=True,
    )


def run_experiments() -> None:
    for script in sorted((ROOT / "experiments").glob("exp*.py")):
        subprocess.run(
            [sys.executable, str(script)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL
        )


def read_junit() -> int:
    root = ET.parse(REPORTS / "junit.xml").getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    total = sum(int(s.get("tests", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    if failures:
        raise SystemExit(f"junit reports {failures} failing tests; refusing to publish metrics")
    return total - skipped


def read_coverage() -> float:
    data = json.loads((REPORTS / "coverage.json").read_text(encoding="utf-8"))
    return round(float(data["totals"]["percent_covered"]), 1)


def load(name: str) -> dict:
    return json.loads((EXPERIMENTS / f"{name}.json").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-tests", action="store_true", help="read reports/ instead of running pytest"
    )
    parser.add_argument(
        "--skip-experiments", action="store_true", help="read docs/experiments/ as is"
    )
    args = parser.parse_args()
    if not args.skip_tests or not (REPORTS / "junit.xml").exists():
        run_tests()
    if not args.skip_experiments:
        run_experiments()

    exp01, exp02, exp03, exp04 = (
        load("exp01_breach_census"),
        load("exp02_coverage_vs_bulk"),
        load("exp03_resolution"),
        load("exp04_undecidable"),
    )
    policy = Policy()
    result = run_gate(load_project(FIXTURE), policy, load_coverage(COVERAGE_REPORT))
    closest = exp03["closest_miss"]
    truth = exp04["ground_truth"]

    metrics: dict[str, int | float | str] = {
        "tests_total": read_junit(),
        "coverage_line_pct": read_coverage(),
        "triggers_total": exp01["triggers_total"],
        "objects_total": exp01["objects_total"],
        "triggers_breach": exp01["status_counts"]["breach"],
        "triggers_latent": exp01["status_counts"]["latent"],
        "triggers_clean": exp01["status_counts"]["clean"],
        "triggers_undecidable": exp04["undecidable"],
        "undecidable_pct": exp04["undecidable_pct"],
        "breaches_total": exp01["findings_total"],
        "breaches_at_200": exp01["breaches_at_records"],
        "breaches_above_200": exp03["breaches_above_200"],
        "smallest_breach_above_200": exp03["smallest_breach_above_200"],
        "largest_breach": exp03["largest_breach"],
        "chain_breaches": exp01["via_chain"],
        "chain_only_breaches": exp01["chain_only"],
        "triggers_fully_covered": exp02["fully_covered"],
        "fully_covered_breaching": exp02["fully_covered_breaching"],
        "fully_covered_breaching_pct": exp02["fully_covered_breaching_pct"],
        "fully_covered_undecidable": exp02["fully_covered_undecidable"],
        "largest_test_behind_breach": exp02["largest_test_behind_a_breach"],
        "apex_test_methods": exp02["apex_test_methods"],
        "apex_single_record": exp02["apex_test_methods_single_record"],
        "apex_bulk": exp02["apex_test_methods_at_200_or_more"],
        "largest_tested_any": exp03["largest_tested_any_trigger"],
        "closest_tested": closest["tested_largest"],
        "closest_breach": closest["breach_at"],
        "closest_short": closest["records_short"],
        "planted_breaches": truth["expected_findings"],
        "true_positive": truth["true_positive"],
        "false_positive": truth["false_positive"],
        "false_negative": truth["false_negative"],
        "limit_soql": policy.value("soql_queries"),
        "limit_sosl": policy.value("sosl_queries"),
        "limit_dml_statements": policy.value("dml_statements"),
        "limit_dml_rows": policy.value("dml_rows"),
        "limit_soql_async": policy.limits["soql_queries"].async_,
        "chunk_size": policy.chunk_size,
        "horizon": policy.horizon,
        "records": policy.records,
        "refusal_reasons": len(exp04["reasons"]),
    }
    anchors: dict[str, list[str]] = {
        "tests_total": ["{} tests"],
        "coverage_line_pct": ["{}% line coverage"],
        "triggers_total": ["{} triggers in the fixture", "{} triggers over"],
        "objects_total": ["over {} objects"],
        "triggers_breach": ["{} triggers breach at 200", "{} of them breach at 200"],
        "triggers_latent": ["{} breach only above 200"],
        "triggers_clean": ["{} clean within the horizon"],
        "triggers_undecidable": [
            "{} of {m:triggers_total} triggers undecidable",
            "{} triggers undecidable",
        ],
        "undecidable_pct": ["{}% of the fixture undecidable"],
        "breaches_total": ["{} breaches in all"],
        "breaches_at_200": ["{} breaches at or below 200"],
        "breaches_above_200": ["{} breaches above 200"],
        "smallest_breach_above_200": ["the smaller at {} records"],
        "largest_breach": ["the larger at {} records"],
        "chain_breaches": ["{} breaches through a chain"],
        "chain_only_breaches": ["{} exist only through the chain"],
        "triggers_fully_covered": ["{} triggers at 100%"],
        "fully_covered_breaching": [
            "{} of {m:triggers_fully_covered} fully covered triggers breach"
        ],
        "fully_covered_breaching_pct": ["{}% of the fully covered"],
        "fully_covered_undecidable": ["{} fully covered triggers undecidable"],
        "largest_test_behind_breach": ["exercise at most {} records"],
        "apex_test_methods": ["{} Apex test methods"],
        "apex_single_record": ["{} of {m:apex_test_methods} Apex test methods exercise one record"],
        "apex_bulk": ["{} exercise 200 or more"],
        "largest_tested_any": ["largest test anywhere exercises {} records"],
        "closest_tested": ["tested at {} records and breaches at {m:closest_breach}"],
        "closest_breach": ["tested at {m:closest_tested} records and breaches at {}"],
        "closest_short": ["{} record short"],
        "planted_breaches": ["{} planted breaches", "below one in {}"],
        "true_positive": ["{} true positives"],
        "false_positive": ["{} false positives"],
        "false_negative": ["{} false negatives"],
        "limit_soql": ["{} SOQL queries"],
        "limit_sosl": ["{} SOSL queries"],
        "limit_dml_statements": ["{} DML statements"],
        "limit_dml_rows": ["{} DML rows"],
        "limit_soql_async": ["{} for asynchronous"],
        "chunk_size": ["chunks of {}"],
        "horizon": ["horizon of {} records"],
        "records": ["verdict at {} records"],
        "refusal_reasons": ["{} refusal reasons"],
    }

    # Per-trigger table cells, pinned by the row's literal name and its neighbours.
    for t in result.triggers:
        key = t.name.replace("Trigger", "").lower()
        coverage = int(t.coverage_pct) if t.coverage_pct is not None else 0
        metrics[f"row_{key}_coverage"] = coverage
        metrics[f"row_{key}_tested"] = t.tested.largest if t.tested.largest is not None else 0
        anchors[f"row_{key}_coverage"] = [f"`{t.name}` | {t.sobject} | {{}}% |"]
        anchors[f"row_{key}_tested"] = [
            f"`{t.name}` | {t.sobject} | {{m:row_{key}_coverage}}% | {{}} |"
        ]
        breach = t.smallest_breach()
        if breach is not None:
            metrics[f"row_{key}_breach"] = breach
            anchors[f"row_{key}_breach"] = [
                f"`{t.name}` | {t.sobject} | {{m:row_{key}_coverage}}% | "
                f"{{m:row_{key}_tested}} | {{}} |"
            ]

    payload = {
        "metrics": metrics,
        "anchors": anchors,
        "checked_documents": CHECKED_DOCUMENTS,
        "banner": {
            "path": "docs/assets/banner.svg",
            "figures": {
                "fully_covered_breaching": "{} of {m:triggers_fully_covered}",
                "largest_test_behind_breach": "tests stop at {}",
                "breaches_above_200": "{} more above 200",
                "triggers_undecidable": "{} undecidable",
            },
        },
        "note": "every value here is produced by running the suite, the experiments and the gate",
    }
    out = ROOT / "docs" / "metrics.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out} with {len(metrics)} metrics")
    for key in (
        "tests_total",
        "coverage_line_pct",
        "fully_covered_breaching",
        "breaches_above_200",
        "triggers_undecidable",
    ):
        print(f"  {key} = {metrics[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
