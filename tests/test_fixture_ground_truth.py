"""The fixture's planted ground truth, and the bug the first run against it revealed."""

import json

import pytest

from absg.coverage import load_coverage
from absg.limits import Policy
from absg.project import load_project
from absg.provenance import Poly
from absg.verdict import run_gate
from helpers import COVERAGE, FIXTURE, cost_of, project_from, trigger

EXPECTED = json.loads((FIXTURE / "EXPECTED_FINDINGS.json").read_text())


@pytest.fixture(scope="module")
def result():
    return run_gate(load_project(FIXTURE), Policy(), load_coverage(COVERAGE))


def observed(result):
    out = {}
    for t in result.triggers:
        out[t.name] = {
            "status": t.status,
            "findings": [
                {"limit": f.limit, "breach_at": f.breach_at, "via_chain": f.via_chain}
                for f in t.findings
            ],
            "refusals": sorted({r["reason"] for r in t.refusals}),
            "tested_largest": t.tested.largest,
        }
    return out


def expected():
    return {
        name: {
            "status": e["status"],
            "findings": e["findings"],
            "refusals": sorted(e["refusals"]),
            "tested_largest": e["tested_largest"],
        }
        for name, e in EXPECTED["triggers"].items()
    }


def test_the_gate_reports_exactly_the_planted_findings(result):
    assert observed(result) == expected()


def test_the_ground_truth_covers_every_trigger_in_the_fixture(result):
    assert set(EXPECTED["triggers"]) == {t.name for t in result.triggers}


def test_every_planted_carrier_file_exists():
    for entry in EXPECTED["triggers"].values():
        assert (FIXTURE / entry["carrier"]).exists(), entry["carrier"]


def test_the_planted_record_count_is_the_default_verdict_count(result):
    assert EXPECTED["records"] == result.policy.records == 200


def test_four_of_the_fully_covered_triggers_breach_at_two_hundred_records(result):
    fully = [t for t in result.triggers if t.coverage_pct == 100.0]
    breaching = [t for t in fully if t.status == "breach"]
    assert len(fully) == 11
    assert sorted(t.name for t in breaching) == [
        "AccountTaskTrigger",
        "ContactEmailTrigger",
        "OpportunityStageTrigger",
        "TaskAssignmentTrigger",
    ]


def test_the_tests_behind_every_breaching_trigger_stop_below_its_breach_size(result):
    for t in result.triggers:
        if t.status == "breach":
            assert t.tested.largest is not None
            assert t.tested.largest < t.smallest_breach()


def test_the_two_latent_breaches_sit_inside_one_bulk_api_batch(result):
    latent = {t.name: t.smallest_breach() for t in result.triggers if t.status == "latent"}
    assert latent == {"OrderLineRollupTrigger": 5001, "OrderTotalTrigger": 6601}
    assert all(200 < size <= 10000 for size in latent.values())


def test_the_constant_status_loop_costs_three_queries_not_three_per_record(result):
    assert result.by_name("OrderTotalTrigger").costs["soql_queries"] == "3"


def test_the_account_task_chain_costs_a_query_per_account_without_containing_one(result):
    verdict = result.by_name("AccountTaskTrigger")
    assert verdict.costs["soql_queries"] == "r"
    assert verdict.findings[0].via_chain
    assert not any(s["kind"] == "soql" for s in verdict.sites)


def test_the_guarded_re_entrant_trigger_is_bounded_and_the_unguarded_one_is_not(result):
    assert result.by_name("AccountRegionTrigger").status == "clean"
    assert result.by_name("CaseAgeTrigger").refusals[0]["reason"] == "reentrant"


def test_the_undecidable_share_is_three_of_thirteen(result):
    counts = result.counts()
    assert counts["undecidable"] == 3
    assert counts["triggers"] == 13


def test_the_fixture_result_is_deterministic_across_runs(result):
    again = run_gate(load_project(FIXTURE), Policy(), load_coverage(COVERAGE))
    assert json.dumps(again.to_dict(), sort_keys=True) == json.dumps(
        result.to_dict(), sort_keys=True
    )


def test_a_collection_grown_by_add_is_seen_even_though_add_is_a_qualified_call():
    """Pins the bug the first run against the fixture revealed.

    `tasks.add(...)` is both a call on a variable and the way a collection grows, and the
    reader handled the call first and returned past the growth. On the fixture that read
    `insert tasks` as an insert of zero rows, so AccountTaskTrigger reported clean instead
    of breaching at the 101st record, and every Apex test read as exercising one record
    (the 100, 200 and 251-record tests included). The growth is now applied inside the
    qualified-call path, so the two readings of `.add(` agree.
    """
    project = project_from(
        {
            "A": trigger(
                "A",
                "Account (after insert)",
                "List<Task> ts = new List<Task>();\n"
                "for (Account a : Trigger.new) { ts.add(new Task(WhatId = a.Id)); }\n"
                "insert ts;",
            ),
            "T": trigger(
                "T",
                "Task (before insert)",
                "for (Task t : Trigger.new) { User u = [SELECT Id FROM User LIMIT 1]; }",
            ),
        }
    )
    cost = cost_of(project, "A")
    assert cost.own.dml_rows == Poly.record()
    assert cost.total("soql_queries") == Poly.record()
