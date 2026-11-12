"""Experiment 3: resolution.

Question the README asks: for every breach, how far below the breach size did the tests stop,
and which breaches would the 200-record test that every bulkification guide recommends still
not reach?
"""

from common import gate, table, write


def main() -> None:
    result = gate()
    rows = []
    for t in result.triggers:
        for f in t.findings:
            tested = f.tested_largest
            rows.append(
                {
                    "trigger": t.name,
                    "limit": f.limit,
                    "breach_at": f.breach_at,
                    "tested_largest": tested,
                    "records_short": None if tested is None else f.breach_at - tested,
                    "ratio": None if not tested else round(f.breach_at / tested, 1),
                    "reached_by_200_record_test": f.breach_at <= 200,
                    "records_a_test_would_need": f.breach_at,
                }
            )
    above = [r for r in rows if not r["reached_by_200_record_test"]]
    shorts = [r["records_short"] for r in rows if r["records_short"] is not None]
    closest = min(
        rows, key=lambda r: r["records_short"] if r["records_short"] is not None else 10**9
    )
    largest_tested = max(t.tested.largest or 0 for t in result.triggers)
    payload = {
        "records": result.policy.records,
        "horizon": result.policy.horizon,
        "breaches_total": len(rows),
        "breaches_reached_by_200": len(rows) - len(above),
        "breaches_above_200": len(above),
        "breaches_above_200_names": [r["trigger"] for r in above],
        "smallest_breach_above_200": min(r["breach_at"] for r in above) if above else None,
        "largest_breach": max(r["breach_at"] for r in rows),
        "closest_miss": closest,
        "records_short_min": min(shorts),
        "records_short_max": max(shorts),
        "largest_tested_any_trigger": largest_tested,
        "resolution_floor_note": (
            "A clean verdict from a test at N records is a claim about N records. The gate's "
            "own recommended 200-record test has the same floor: a breach above 200 is invisible "
            "to it, and the table says how many records each one would take."
        ),
        "rows": rows,
    }
    path = write("exp03_resolution", payload)
    print(
        table(
            [
                "Trigger",
                "Limit",
                "Tested at",
                "Breaches at",
                "Short by",
                "Ratio",
                "200-record test",
            ],
            [
                [
                    r["trigger"],
                    r["limit"],
                    "?" if r["tested_largest"] is None else f"{r['tested_largest']:,}",
                    f"{r['breach_at']:,}",
                    "?" if r["records_short"] is None else f"{r['records_short']:,}",
                    "?" if r["ratio"] is None else f"{r['ratio']}x",
                    "reaches it" if r["reached_by_200_record_test"] else "misses it",
                ]
                for r in rows
            ],
        )
    )
    print()
    print(
        f"{len(rows)} breaches: {len(rows) - len(above)} reached by a 200-record test, "
        f"{len(above)} above 200 records (smallest {payload['smallest_breach_above_200']:,}); "
        f"closest miss {closest['trigger']} tested at {closest['tested_largest']} against a "
        f"breach at {closest['breach_at']}; largest test anywhere {largest_tested} records"
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
