"""Findings, verdicts, the four renderings, and the exit codes a pipeline reads."""

import io
import json

import pytest

from absg.cli import main
from absg.coverage import load_coverage
from absg.exit_codes import BREACH, CLEAN, MEANING, UNDECIDABLE, USAGE
from absg.limits import Policy
from absg.project import load_project
from absg.report import explain_text, render_html, render_json, render_markdown, render_text
from absg.verdict import run_gate
from helpers import COVERAGE, FIXTURE, policy, project_from, trigger


@pytest.fixture(scope="module")
def fixture_result():
    return run_gate(load_project(FIXTURE), Policy(), load_coverage(COVERAGE))


def run(args):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# ----- verdicts --------------------------------------------------------------------------


def test_a_trigger_with_no_cost_is_clean():
    project = project_from({"T": trigger("T", "Account (before insert)", "")})
    result = run_gate(project, Policy(), None)
    assert result.triggers[0].status == "clean"
    assert result.exit_code == CLEAN


def test_a_trigger_breaching_at_the_configured_records_is_a_breach_and_exit_1():
    project = project_from(
        {
            "T": trigger(
                "T",
                "Account (before insert)",
                "for (Account a : Trigger.new) { Account b = [SELECT Id FROM Account LIMIT 1]; }",
            )
        }
    )
    result = run_gate(project, Policy(), None)
    assert result.triggers[0].status == "breach"
    assert result.triggers[0].findings[0].breach_at == 101
    assert result.exit_code == BREACH


def test_a_breach_above_the_configured_records_but_within_the_horizon_is_latent_and_exit_0():
    project = project_from(
        {"T": trigger("T", "Account (before insert)", "Integer n = [SELECT COUNT() FROM Account];")}
    )
    result = run_gate(project, policy(horizon=30000), None)
    assert result.triggers[0].status == "latent"
    assert result.triggers[0].findings[0].breach_at == 20001
    assert result.exit_code == CLEAN


def test_raising_records_turns_a_latent_finding_into_a_breach():
    project = project_from(
        {"T": trigger("T", "Account (before insert)", "Integer n = [SELECT COUNT() FROM Account];")}
    )
    result = run_gate(project, policy(horizon=30000, records=25000), None)
    assert result.triggers[0].status == "breach"


def test_a_refusal_makes_the_trigger_undecidable_and_exit_2_when_nothing_breaches():
    project = project_from({"T": trigger("T", "Account (before insert)", "erp.X.go();")})
    result = run_gate(project, Policy(), None)
    assert result.triggers[0].status == "undecidable"
    assert result.exit_code == UNDECIDABLE


def test_a_breach_elsewhere_outranks_an_undecidable_trigger_in_the_exit_code():
    project = project_from(
        {
            "A": trigger("A", "Account (before insert)", "erp.X.go();"),
            "B": trigger(
                "B",
                "Case (before insert)",
                "for (Case c : Trigger.new) { Contact k = [SELECT Id FROM Contact LIMIT 1]; }",
            ),
        }
    )
    assert run_gate(project, Policy(), None).exit_code == BREACH


def test_a_finding_records_coefficients_cost_at_records_and_chain_origin():
    project = project_from(
        {
            "A": trigger("A", "Account (after insert)", "insert new Task();"),
            "T": trigger(
                "T",
                "Task (before insert)",
                "List<User> us = [SELECT Id FROM User];\n"
                "for (Task t : Trigger.new) { User u = [SELECT Id FROM User LIMIT 1]; }",
            ),
        }
    )
    result = run_gate(project, policy(horizon=30000), None)
    finding = result.by_name("T").findings[0]
    assert (finding.per_invocation, finding.per_record, finding.higher_order) == (1, 1, 0)
    assert finding.cost_at_records == 201
    assert finding.breach_at == 100
    assert not finding.via_chain
    chained = [f for f in result.by_name("A").findings if f.limit == "soql_queries"][0]
    assert chained.via_chain
    assert chained.cost_formula == "2"


def test_findings_are_one_per_limit_with_a_breach_size_only():
    project = project_from(
        {
            "T": trigger(
                "T",
                "Account (before insert)",
                "insert new Task(); List<Task> ts = [SELECT Id FROM Task];",
            )
        }
    )
    result = run_gate(project, policy(horizon=40000), None)
    assert sorted(f.limit for f in result.triggers[0].findings) == [
        "dml_statements",
        "soql_queries",
    ]


def test_coverage_is_joined_by_trigger_name_and_missing_entries_are_warnings(tmp_path):
    project = project_from({"T": trigger("T", "Account (before insert)", "")})
    path = tmp_path / "cov.json"
    path.write_text(
        json.dumps(
            [{"name": "no-map/Other", "totalLines": 1, "totalCovered": 1, "coveredPercent": 100}]
        )
    )
    result = run_gate(project, Policy(), load_coverage(path))
    assert result.triggers[0].coverage_pct is None
    assert result.warnings == ["T: not present in the coverage report"]
    assert result.coverage_loaded


def test_by_name_raises_for_an_unknown_trigger(fixture_result):
    with pytest.raises(KeyError):
        fixture_result.by_name("Nope")


def test_counts_add_up_to_the_trigger_total(fixture_result):
    counts = fixture_result.counts()
    assert (
        counts["breach"] + counts["latent"] + counts["clean"] + counts["undecidable"]
        == counts["triggers"]
    )


def test_the_result_dict_is_json_serialisable_and_carries_the_policy(fixture_result):
    data = json.loads(render_json(fixture_result))
    assert data["policy"]["limits"]["soql_queries"] == 100
    assert data["policy"]["records"] == 200
    assert len(data["triggers"]) == 13


def test_smallest_breach_is_the_minimum_over_limits():
    project = project_from(
        {
            "T": trigger(
                "T",
                "Account (before insert)",
                "for (Account a : Trigger.new) { insert new Task(); "
                "Account b = [SELECT Id FROM Account LIMIT 1]; }",
            )
        }
    )
    verdict = run_gate(project, Policy(), None).triggers[0]
    assert verdict.smallest_breach() == 101


# ----- renderings ------------------------------------------------------------------------


def test_text_report_has_one_row_per_trigger_and_the_exit_line(fixture_result):
    text = render_text(fixture_result)
    for name in ("AccountTaskTrigger", "CaseAgeTrigger", "OrderTotalTrigger"):
        assert name in text
    assert text.rstrip().endswith(f"exit 1 ({MEANING[1]})")


def test_text_report_states_breach_sizes_and_tested_sizes(fixture_result):
    text = render_text(fixture_result)
    assert "breaches at 101 records via chain; tested at 100" in text
    assert "breaches at 6,601 records" in text


def test_text_report_lists_refusals_with_file_and_line(fixture_result):
    assert "undecidable, dynamic_dispatch: Type.forName(...)" in render_text(fixture_result)


def test_text_report_without_coverage_shows_not_applicable():
    project = project_from({"T": trigger("T", "Account (before insert)", "")})
    assert "n/a" in render_text(run_gate(project, Policy(), None))


def test_text_report_prints_warnings(tmp_path):
    project = project_from({"T": trigger("T", "Account (before insert)", "")})
    path = tmp_path / "cov.json"
    path.write_text("[]")
    assert "warning: T: not present" in render_text(
        run_gate(project, Policy(), load_coverage(path))
    )


def test_markdown_report_is_a_table_plus_bullets(fixture_result):
    md = render_markdown(fixture_result)
    assert md.startswith("## absg gate")
    assert "| Trigger | Object | Coverage | Tested at | Breaches at | Verdict |" in md
    assert "- `TaskAssignmentTrigger`: SOQL queries `r` per invocation" in md
    assert "- `LeadRoutingTrigger`: undecidable, dynamic_dispatch" in md


def test_html_report_has_the_three_framed_sections_and_a_verdict_badge(fixture_result):
    html = render_html(fixture_result)
    for anchor in ("coverage-against-breach-size", "findings", "undecidable", "end"):
        assert f"id='{anchor}'" in html
    assert "class='badge breach'" in html
    assert "<title>absg gate report</title>" in html


def test_html_report_says_so_when_every_trigger_is_bounded():
    project = project_from({"T": trigger("T", "Account (before insert)", "")})
    assert "Every trigger was bounded" in render_html(run_gate(project, Policy(), None))


def test_every_css_class_used_in_the_html_has_a_rule(fixture_result):
    import re

    html = render_html(fixture_result)
    used = set()
    for attr in re.findall(r"class='([^']+)'", html):
        used.update(attr.split())
    style = html.split("<style>")[1].split("</style>")[0]
    for cls in used:
        assert f".{cls}" in style, cls


def test_explain_text_lists_sites_costs_arithmetic_and_tests(fixture_result):
    text = explain_text(fixture_result.by_name("AccountTaskTrigger"), fixture_result)
    assert "AccountTaskHandler.createFollowUps(record)" in text
    assert "SOQL queries    r" in text
    assert "at 101 records via chain" in text
    assert "AccountTriggersTest.insertsOneHundredAccounts" in text


def test_explain_text_for_an_undecidable_trigger_lists_the_refusal(fixture_result):
    text = explain_text(fixture_result.by_name("OpportunitySyncTrigger"), fixture_result)
    assert "refusals:" in text
    assert "external_namespace: erp.SyncHandler.push()" in text
    assert "no limit breached within 10,000 records" in text


def test_explain_text_names_static_guards(fixture_result):
    text = explain_text(fixture_result.by_name("AccountRegionTrigger"), fixture_result)
    assert "static guards seen: RecursionGuard.regionRan" in text


# ----- CLI -------------------------------------------------------------------------------


def test_gate_on_the_fixture_exits_1_and_prints_the_table():
    code, out, err = run(["gate", "--project", str(FIXTURE), "--coverage", str(COVERAGE)])
    assert code == BREACH
    assert "TaskAssignmentTrigger" in out
    assert err == ""


def test_gate_json_output_parses():
    code, out, _ = run(["gate", "--project", str(FIXTURE), "--json"])
    assert code == BREACH
    assert json.loads(out)["counts"]["triggers"] == 13


def test_gate_markdown_output_is_a_job_summary():
    _, out, _ = run(["gate", "--project", str(FIXTURE), "--markdown"])
    assert out.startswith("## absg gate")


def test_gate_html_option_writes_the_report(tmp_path):
    target = tmp_path / "out" / "report.html"
    code, _, _ = run(["gate", "--project", str(FIXTURE), "--html", str(target)])
    assert code == BREACH
    assert "absg gate report" in target.read_text()


def test_gate_with_async_context_still_breaches_on_the_fixture():
    code, out, _ = run(["gate", "--project", str(FIXTURE), "--context", "async"])
    assert code == BREACH
    assert "breaches at 201 records" in out


def test_gate_with_a_policy_file_changes_the_limit(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"limits": {"soql_queries": {"sync": 50}}}))
    _, out, _ = run(["gate", "--project", str(FIXTURE), "--policy", str(path)])
    assert "breaches at 51 records" in out


def test_gate_with_a_bad_policy_file_exits_3(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"limits": {"heap": {"sync": 1}}}))
    code, _, err = run(["gate", "--project", str(FIXTURE), "--policy", str(path)])
    assert code == USAGE
    assert "unknown limit" in err


def test_gate_with_a_missing_project_exits_3(tmp_path):
    code, _, err = run(["gate", "--project", str(tmp_path)])
    assert code == USAGE
    assert "sfdx-project.json" in err


def test_gate_with_a_broken_trigger_exits_3_and_names_the_file(tmp_path):
    (tmp_path / "sfdx-project.json").write_text(
        json.dumps({"packageDirectories": [{"path": "src"}]})
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Bad.trigger").write_text("trigger Bad { }")
    code, _, err = run(["gate", "--project", str(tmp_path)])
    assert code == USAGE
    assert "Bad.trigger" in err


def test_gate_with_a_malformed_coverage_report_exits_3(tmp_path):
    path = tmp_path / "cov.json"
    path.write_text("{}")
    code, _, err = run(["gate", "--project", str(FIXTURE), "--coverage", str(path)])
    assert code == USAGE
    assert "coverage" in err


def test_gate_with_a_nonpositive_record_count_exits_3():
    code, _, err = run(["gate", "--project", str(FIXTURE), "--records", "0"])
    assert code == USAGE
    assert "records" in err


def test_gate_on_a_clean_project_exits_0(tmp_path):
    (tmp_path / "sfdx-project.json").write_text(
        json.dumps({"packageDirectories": [{"path": "src"}]})
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "T.trigger").write_text("trigger T on Account (before insert) { }")
    code, out, _ = run(["gate", "--project", str(tmp_path)])
    assert code == CLEAN
    assert "exit 0" in out


def test_explain_prints_the_trigger_and_exits_0():
    code, out, _ = run(["explain", "TaskAssignmentTrigger", "--project", str(FIXTURE)])
    assert code == 0
    assert out.startswith("TaskAssignmentTrigger on Task")


def test_explain_of_an_unknown_trigger_exits_3_and_lists_the_known_ones():
    code, _, err = run(["explain", "Nope", "--project", str(FIXTURE)])
    assert code == USAGE
    assert "AccountDedupeTrigger" in err


def test_limits_prints_every_limit_with_its_reason():
    code, out, _ = run(["limits"])
    assert code == 0
    assert "soql_queries" in out
    assert "101st record" in out


def test_limits_json_is_the_policy_table():
    _, out, _ = run(["limits", "--json"])
    assert [row["name"] for row in json.loads(out)][:4] == [
        "soql_queries",
        "sosl_queries",
        "dml_statements",
        "dml_rows",
    ]


def test_limits_with_a_policy_file_shows_the_override(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"limits": {"soql_queries": {"sync": 90}}}))
    _, out, _ = run(["limits", "--policy", str(path)])
    assert "     90 queries" in out


def test_limits_with_a_bad_policy_file_exits_3(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text("[]")
    code, _, _ = run(["limits", "--policy", str(path)])
    assert code == USAGE


def test_usage_errors_exit_3():
    assert run(["gate", "--records", "many"])[0] == USAGE
    assert run([])[0] == USAGE


def test_version_and_help_exit_0():
    assert run(["--version"])[0] == 0
    assert run(["--help"])[0] == 0


def test_python_m_absg_runs_the_cli():
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "absg", "limits"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0
    assert "dml_rows" in completed.stdout
