"""Following DML into other triggers, and reading what the Apex tests exercised."""

from pathlib import Path

from absg.chain import ChainResolver
from absg.provenance import Poly
from absg.tests_apex import read_exercises, sizes_by_trigger
from helpers import cost_of, project_from, trigger

R = Poly.record()
ONE = Poly.const(1)


def test_a_bulk_insert_into_an_object_with_a_per_record_trigger_costs_r_through_the_chain():
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
    assert cost.own.soql.is_zero
    assert cost.chain_soql == R
    assert cost.total("soql_queries") == R


def test_a_per_record_insert_into_an_object_with_a_bulkified_trigger_costs_r_through_the_chain():
    project = project_from(
        {
            "C": trigger(
                "C",
                "Contact (after update)",
                "for (Contact c : Trigger.new) { insert new Case(ContactId = c.Id); }",
            ),
            "K": trigger(
                "K",
                "Case (before insert)",
                "List<Contact> cs = [SELECT Id FROM Contact];",
            ),
        }
    )
    cost = cost_of(project, "C")
    assert cost.chain_soql == R
    assert cost.own.dml_statements == R


def test_a_bulk_insert_into_an_object_with_a_bulkified_trigger_costs_a_constant():
    project = project_from(
        {
            "A": trigger(
                "A",
                "Account (after insert)",
                "List<Task> ts = new List<Task>();\n"
                "for (Account a : Trigger.new) { ts.add(new Task(WhatId = a.Id)); }\n"
                "insert ts;",
            ),
            "T": trigger("T", "Task (before insert)", "List<User> us = [SELECT Id FROM User];"),
        }
    )
    assert cost_of(project, "A").chain_soql == ONE


def test_chain_dml_rows_compose_with_the_rows_the_statement_carries():
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
                "Task (after insert)",
                "List<Event> es = new List<Event>();\n"
                "for (Task t : Trigger.new) { es.add(new Event(WhatId = t.WhatId)); }\n"
                "insert es;",
            ),
        }
    )
    cost = cost_of(project, "A")
    assert cost.total("dml_statements") == Poly.const(2)
    assert cost.total("dml_rows") == Poly.from_dict({1: 2})


def test_only_triggers_firing_on_the_operation_are_invoked():
    project = project_from(
        {
            "A": trigger("A", "Account (after insert)", "insert new Task();"),
            "T": trigger("T", "Task (before update)", "List<User> us = [SELECT Id FROM User];"),
        }
    )
    assert cost_of(project, "A").chain_soql.is_zero


def test_an_upsert_invokes_both_insert_and_update_triggers():
    project = project_from(
        {
            "A": trigger("A", "Account (after insert)", "upsert new Task();"),
            "T1": trigger("T1", "Task (before insert)", "List<User> us = [SELECT Id FROM User];"),
            "T2": trigger("T2", "Task (before update)", "List<User> us = [SELECT Id FROM User];"),
        }
    )
    assert cost_of(project, "A").chain_soql == Poly.const(2)


def test_a_publish_invokes_no_trigger():
    project = project_from(
        {"A": trigger("A", "Account (after insert)", "EventBus.publish(new Order_Event__e());")}
    )
    cost = cost_of(project, "A")
    assert cost.chain_soql.is_zero
    assert cost.own.dml_statements == ONE


def test_a_chain_three_triggers_deep_composes_all_the_way():
    project = project_from(
        {
            "A": trigger("A", "Account (after insert)", "insert new Task();"),
            "T": trigger("T", "Task (after insert)", "insert new Event();"),
            "E": trigger(
                "E",
                "Event (before insert)",
                "for (Event e : Trigger.new) { User u = [SELECT Id FROM User LIMIT 1]; }",
            ),
        }
    )
    cost = cost_of(project, "A")
    assert cost.chain_soql == ONE
    assert cost.total("dml_statements") == Poly.const(2)


def test_a_re_entrant_chain_with_no_guard_is_a_refusal():
    project = project_from(
        {
            "A": trigger(
                "A",
                "Account (after update)",
                "List<Account> up = new List<Account>();\n"
                "for (Account a : Trigger.new) { up.add(new Account(Id = a.Id)); }\n"
                "update up;",
            )
        }
    )
    cost = cost_of(project, "A")
    assert [r.reason for r in cost.refusals] == ["reentrant"]


def test_a_re_entrant_chain_behind_a_static_guard_is_stopped_and_bounded():
    project = project_from(
        {
            "A": trigger(
                "A",
                "Account (after update)",
                "if (!G.ran) { G.ran = true; List<Account> up = new List<Account>();\n"
                "for (Account a : Trigger.new) { up.add(new Account(Id = a.Id)); }\n"
                "update up; }",
            )
        },
        {"G": "public class G { public static Boolean ran = false; }"},
    )
    cost = cost_of(project, "A")
    assert cost.refusals == []
    assert cost.total("dml_statements") == ONE
    assert any("stopped by static guard" in s.detail for s in cost.chain_sites)


def test_a_chain_whose_rows_are_unbounded_is_a_refusal_on_the_chain():
    project = project_from(
        {
            "A": trigger(
                "A",
                "Account (after insert)",
                "List<Task> ts = [SELECT Id FROM Task]; update ts;",
            ),
            "T": trigger("T", "Task (before update)", "List<User> us = [SELECT Id FROM User];"),
        }
    )
    reasons = sorted(r.reason for r in cost_of(project, "A").refusals)
    assert reasons == ["unbounded_rows", "unbounded_rows"]


def test_a_refusal_inside_an_invoked_trigger_propagates_with_its_name():
    project = project_from(
        {
            "A": trigger("A", "Account (after insert)", "insert new Task();"),
            "T": trigger("T", "Task (before insert)", "erp.Sync.push(Trigger.new);"),
        }
    )
    refusal = cost_of(project, "A").refusals[0]
    assert refusal.reason == "external_namespace"
    assert refusal.construct.startswith("via T:")


def test_own_costs_are_computed_once_per_trigger():
    project = project_from({"A": trigger("A", "Account (after insert)", "insert new Task();")})
    resolver = ChainResolver(project)
    assert resolver.own_cost("A") is resolver.own_cost("A")


def test_targets_are_matched_case_insensitively_on_the_object():
    project = project_from(
        {
            "A": trigger("A", "Account (after insert)", "insert new task();"),
            "T": trigger("T", "TASK (before insert)", "List<User> us = [SELECT Id FROM User];"),
        }
    )
    assert cost_of(project, "A").chain_soql == ONE


TEST_CLASS = """
@IsTest
private class SomeTest {
    @IsTest
    static void one() { insert new Account(Name = 'a'); }

    @IsTest
    static void hundred() {
        List<Account> accs = new List<Account>();
        for (Integer i = 0; i < 100; i++) { accs.add(new Account(Name = 'b' + i)); }
        insert accs;
        update accs;
    }

    @IsTest
    static void literal() {
        insert new List<Contact>{new Contact(LastName = 'a'), new Contact(LastName = 'b')};
    }

    @IsTest
    static void loaded() { List<SObject> rows = Test.loadData(Case.sObjectType, 'Cases'); }

    @IsTest
    static void queried() { List<Lead> ls = [SELECT Id FROM Lead]; update ls; }

    static void notATest() { insert new Task(); }
}
"""


def project_with_tests(tmp_path: Path | None = None):
    project = project_from(
        {
            "A": trigger("A", "Account (before insert, after update)", ""),
            "C": trigger("C", "Contact (before insert)", ""),
            "K": trigger("K", "Case (before insert)", ""),
            "L": trigger("L", "Lead (after update)", ""),
            "T": trigger("T", "Task (before insert)", ""),
        },
        {"SomeTest": TEST_CLASS},
    )
    if tmp_path is not None:
        csv = tmp_path / "Cases.csv"
        csv.write_text("Subject,Origin\na,Web\nb,Web\nc,Web\n\n")
        project.static_resources["cases"] = csv
    return project


def test_a_single_record_insert_is_an_exercise_of_one():
    exercises = read_exercises(project_with_tests())
    one = [e for e in exercises if e.test_method == "one"][0]
    assert (one.sobject, one.operation, one.records) == ("Account", "insert", 1)


def test_a_list_filled_in_a_counted_loop_is_an_exercise_of_the_bound():
    exercises = [e for e in read_exercises(project_with_tests()) if e.test_method == "hundred"]
    assert [(e.operation, e.records) for e in exercises] == [("insert", 100), ("update", 100)]


def test_a_collection_literal_is_an_exercise_of_its_item_count():
    literal = [e for e in read_exercises(project_with_tests()) if e.test_method == "literal"][0]
    assert literal.records == 2


def test_test_loaddata_counts_the_rows_of_the_committed_csv_without_the_header(tmp_path):
    loaded = [e for e in read_exercises(project_with_tests(tmp_path)) if e.test_method == "loaded"]
    assert loaded[0].records == 3
    assert "Cases.csv" in loaded[0].note


def test_test_loaddata_with_a_missing_resource_is_unknown():
    loaded = [e for e in read_exercises(project_with_tests()) if e.test_method == "loaded"][0]
    assert loaded.records is None
    assert "not in the project" in loaded.note


def test_a_dml_on_a_query_result_is_unknown():
    queried = [e for e in read_exercises(project_with_tests()) if e.test_method == "queried"][0]
    assert queried.records is None
    assert queried.sobject == "Lead"


def test_methods_without_a_test_annotation_are_ignored():
    assert not [e for e in read_exercises(project_with_tests()) if e.test_method == "notATest"]


def test_tested_size_is_the_largest_known_record_count_per_trigger(tmp_path):
    sizes = sizes_by_trigger(project_with_tests(tmp_path))
    assert sizes["A"].largest == 100
    assert sizes["C"].largest == 2
    assert sizes["K"].largest == 3
    assert sizes["T"].largest is None


def test_tested_size_counts_unresolved_exercises():
    sizes = sizes_by_trigger(project_with_tests())
    assert sizes["L"].largest is None
    assert sizes["L"].unknown == 1


def test_an_exercise_matches_a_trigger_only_on_the_events_it_declares():
    sizes = sizes_by_trigger(project_with_tests())
    assert sorted(e.operation for e in sizes["A"].exercises) == ["insert", "insert", "update"]


def test_exercise_and_tested_size_to_dict_are_serialisable():
    sizes = sizes_by_trigger(project_with_tests())
    data = sizes["A"].to_dict()
    assert data["trigger"] == "A"
    assert data["exercises"][0]["test"] == "SomeTest.one"


def test_an_exercise_whose_statement_count_is_not_constant_is_unknown():
    project = project_from(
        {"A": trigger("A", "Account (before insert)", "")},
        {
            "T": "@IsTest private class T { @IsTest static void m() { "
            "List<Account> accs = [SELECT Id FROM Account]; "
            "for (Account a : accs) { insert new Account(Name = a.Name); } } }"
        },
    )
    assert read_exercises(project) == []
