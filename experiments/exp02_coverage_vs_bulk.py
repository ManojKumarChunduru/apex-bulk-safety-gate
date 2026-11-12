"""Experiment 2: coverage against the bulk verdict.

Question the README asks: of the triggers the coverage report calls fully covered, how many
breach a governor limit at 200 records, and how many records did the tests behind them
actually push through?
"""

from collections import Counter, defaultdict

from common import exercises, gate, pct, table, write


def bucket(coverage_pct: float | None) -> str:
    if coverage_pct is None:
        return "not in report"
    if coverage_pct >= 100.0:
        return "100%"
    if coverage_pct >= 75.0:
        return "75 to 99%"
    return "below 75%"


def main() -> None:
    result = gate()
    crosstab: dict[str, Counter] = defaultdict(Counter)
    for t in result.triggers:
        crosstab[bucket(t.coverage_pct)][t.status] += 1
    fully = [t for t in result.triggers if t.coverage_pct is not None and t.coverage_pct >= 100.0]
    fully_breaching = [t for t in fully if t.status == "breach"]
    fully_undecidable = [t for t in fully if t.status == "undecidable"]

    per_method: dict[str, int | None] = {}
    for e in exercises():
        key = f"{e.test_class}.{e.test_method}"
        current = per_method.get(key)
        if e.records is None:
            per_method.setdefault(key, None)
        elif current is None or e.records > current:
            per_method[key] = e.records
    single = sorted(k for k, v in per_method.items() if v == 1)
    bulk = sorted(k for k, v in per_method.items() if v is not None and v >= 200)
    breaching_tested = {t.name: t.tested.largest for t in fully_breaching}

    payload = {
        "records": result.policy.records,
        "crosstab": {b: dict(c) for b, c in crosstab.items()},
        "fully_covered": len(fully),
        "fully_covered_breaching": len(fully_breaching),
        "fully_covered_breaching_pct": pct(len(fully_breaching), len(fully)),
        "fully_covered_undecidable": len(fully_undecidable),
        "fully_covered_breaching_names": sorted(t.name for t in fully_breaching),
        "fully_covered_breaching_tested": breaching_tested,
        "largest_test_behind_a_breach": max(v for v in breaching_tested.values() if v is not None),
        "apex_test_methods": len(per_method),
        "apex_test_methods_single_record": len(single),
        "apex_test_methods_single_record_names": single,
        "apex_test_methods_at_200_or_more": len(bulk),
        "apex_test_methods_at_200_or_more_names": bulk,
        "per_method_largest": per_method,
    }
    path = write("exp02_coverage_vs_bulk", payload)
    statuses = ["breach", "latent", "clean", "undecidable"]
    print(
        table(
            ["Coverage bucket", *statuses, "total"],
            [
                [b, *[crosstab[b][s] for s in statuses], sum(crosstab[b].values())]
                for b in ("100%", "75 to 99%", "below 75%", "not in report")
                if b in crosstab
            ],
        )
    )
    print()
    print(
        f"{len(fully_breaching)} of {len(fully)} fully covered triggers breach at "
        f"{result.policy.records} records ({payload['fully_covered_breaching_pct']}%); the tests "
        f"behind them exercise at most {payload['largest_test_behind_a_breach']} records"
    )
    print(
        f"{len(single)} of {len(per_method)} Apex test methods exercise one record; "
        f"{len(bulk)} exercise 200 or more"
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
