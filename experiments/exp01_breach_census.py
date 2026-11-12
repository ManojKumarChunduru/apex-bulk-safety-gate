"""Experiment 1: the breach census.

Question the README asks: over the fixture, how many triggers breach a limit, at what record
count, by which limit, from which loop provenance, and how many of those breaches exist only
because the DML invokes another trigger?
"""

from collections import Counter

from common import gate, pct, table, write


def main() -> None:
    result = gate()
    counts = result.counts()
    findings = [(t, f) for t in result.triggers for f in t.findings]
    at_records = [(t, f) for t, f in findings if f.breach_at <= result.policy.records]
    above = [(t, f) for t, f in findings if f.breach_at > result.policy.records]
    by_limit = Counter(f.limit for _, f in findings)
    by_provenance = Counter(
        "higher order" if f.higher_order else "per record" if f.per_record else "per invocation"
        for _, f in findings
    )
    via_chain = [(t, f) for t, f in findings if f.via_chain]
    chain_only = [(t, f) for t, f in via_chain if t.own_costs[f.limit] == "0"]
    payload = {
        "records": result.policy.records,
        "horizon": result.policy.horizon,
        "triggers_total": counts["triggers"],
        "objects_total": len({t.sobject.lower() for t in result.triggers}),
        "status_counts": {k: counts[k] for k in ("breach", "latent", "clean", "undecidable")},
        "findings_total": len(findings),
        "breaches_at_records": len(at_records),
        "breaches_above_records": len(above),
        "triggers_breaching_at_records": counts["breach"],
        "triggers_breaching_pct": pct(counts["breach"], counts["triggers"]),
        "by_limit": dict(by_limit),
        "by_provenance": dict(by_provenance),
        "via_chain": len(via_chain),
        "chain_only": len(chain_only),
        "findings": [
            {
                "trigger": t.name,
                "limit": f.limit,
                "cost": f.cost_formula,
                "breach_at": f.breach_at,
                "via_chain": f.via_chain,
                "provenance": "higher order"
                if f.higher_order
                else "per record"
                if f.per_record
                else "per invocation",
            }
            for t, f in findings
        ],
    }
    path = write("exp01_breach_census", payload)
    print(
        table(
            ["Trigger", "Limit", "Cost per invocation", "Breaches at", "Via chain"],
            [
                [
                    t.name,
                    f.limit,
                    f.cost_formula,
                    f"{f.breach_at:,}",
                    "yes" if f.via_chain else "no",
                ]
                for t, f in findings
            ],
        )
    )
    print()
    print(
        f"{counts['triggers']} triggers: {counts['breach']} breach at {result.policy.records}, "
        f"{counts['latent']} latent, {counts['clean']} clean, {counts['undecidable']} undecidable; "
        f"{len(findings)} findings, {len(via_chain)} via a chain, {len(chain_only)} chain only"
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
