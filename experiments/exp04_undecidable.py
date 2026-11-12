"""Experiment 4: the gate's own blind spot, and its agreement with the planted truth.

Question the README asks: which triggers does the gate refuse to bound, why, and what share of
the fixture is that? And against the ground truth written before the gate ran, what are its
precision and recall, with the resolution floor the fixture size imposes?
"""

import json
from collections import Counter

from common import GROUND_TRUTH, gate, pct, table, write


def main() -> None:
    result = gate()
    truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))["triggers"]
    undecidable = [t for t in result.triggers if t.status == "undecidable"]
    reasons = Counter(r["reason"] for t in undecidable for r in t.refusals)

    observed = {
        (t.name, f.limit, f.breach_at, f.via_chain) for t in result.triggers for f in t.findings
    }
    expected = {
        (name, f["limit"], f["breach_at"], f["via_chain"])
        for name, entry in truth.items()
        for f in entry["findings"]
    }
    true_positive = len(observed & expected)
    false_positive = len(observed - expected)
    false_negative = len(expected - observed)
    status_matches = sum(1 for t in result.triggers if truth[t.name]["status"] == t.status)
    refusal_matches = sum(
        1
        for t in result.triggers
        if sorted({r["reason"] for r in t.refusals}) == sorted(truth[t.name]["refusals"])
    )

    payload = {
        "triggers_total": len(result.triggers),
        "undecidable": len(undecidable),
        "undecidable_pct": pct(len(undecidable), len(result.triggers)),
        "undecidable_names": [t.name for t in undecidable],
        "reasons": dict(reasons),
        "refusals": [{"trigger": t.name, **r} for t in undecidable for r in t.refusals],
        "ground_truth": {
            "expected_findings": len(expected),
            "observed_findings": len(observed),
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision_pct": pct(true_positive, true_positive + false_positive),
            "recall_pct": pct(true_positive, true_positive + false_negative),
            "status_matches": status_matches,
            "refusal_matches": refusal_matches,
            "resolution_floor_findings": f"1 in {len(expected)}",
            "resolution_floor_triggers": f"1 in {len(result.triggers)}",
            "note": (
                "The fixture was written by the gate's author, so agreement with its own ground "
                "truth is a check on arithmetic and parsing, not on what the gate would find in "
                "code it has never seen. A measured zero false positives is 'below one in "
                f"{len(expected)}', not zero."
            ),
        },
    }
    path = write("exp04_undecidable", payload)
    print(
        table(
            ["Trigger", "Reason", "Construct", "Where"],
            [
                [t.name, r["reason"], r["construct"], f"{r['path'].rsplit('/', 1)[-1]}:{r['line']}"]
                for t in undecidable
                for r in t.refusals
            ],
        )
    )
    print()
    print(
        f"{len(undecidable)} of {len(result.triggers)} triggers undecidable "
        f"({payload['undecidable_pct']}%); against the planted truth: {true_positive} true "
        f"positive, {false_positive} false positive, {false_negative} false negative, "
        f"status agreement {status_matches} of {len(result.triggers)}"
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
