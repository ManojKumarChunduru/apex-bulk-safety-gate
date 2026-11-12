"""The cost model: what the reader charges, what it refuses, and where it draws the line."""

from absg.provenance import Poly
from helpers import cost_of, project_from, trigger

R = Poly.record()
ONE = Poly.const(1)


def own(body, classes=None, header="Account (before insert)"):
    project = project_from({"T": trigger("T", header, body)}, classes)
    return cost_of(project, "T").own


def test_a_query_outside_any_loop_costs_one_per_invocation():
    cost = own("List<Account> a = [SELECT Id FROM Account];")
    assert cost.soql == ONE


def test_a_query_inside_a_loop_over_trigger_new_costs_one_per_record():
    cost = own("for (Account a : Trigger.new) { Account b = [SELECT Id FROM Account LIMIT 1]; }")
    assert cost.soql == R


def test_a_query_inside_a_loop_over_trigger_old_costs_one_per_record():
    cost = own(
        "for (Account a : Trigger.old) { Account b = [SELECT Id FROM Account LIMIT 1]; }",
        header="Account (before delete)",
    )
    assert cost.soql == R


def test_a_query_inside_a_loop_over_newmap_values_costs_one_per_record():
    cost = own(
        "for (Account a : Trigger.newMap.values()) "
        "{ Account b = [SELECT Id FROM Account LIMIT 1]; }",
        header="Account (after update)",
    )
    assert cost.soql == R


def test_a_query_inside_a_loop_over_a_constant_list_costs_the_list_length():
    cost = own(
        "for (String s : new List<String>{'a', 'b', 'c'}) "
        "{ Integer n = [SELECT COUNT() FROM Account]; }"
    )
    assert cost.soql == Poly.const(3)


def test_a_query_inside_a_counted_loop_costs_the_literal_bound():
    cost = own("for (Integer i = 0; i < 5; i++) { Integer n = [SELECT COUNT() FROM Account]; }")
    assert cost.soql == Poly.const(5)


def test_a_counted_loop_with_a_less_or_equal_bound_runs_one_more_time():
    cost = own("for (Integer i = 0; i <= 5; i++) { Integer n = [SELECT COUNT() FROM Account]; }")
    assert cost.soql == Poly.const(6)


def test_a_counted_loop_over_trigger_new_size_is_per_record():
    cost = own(
        "for (Integer i = 0; i < Trigger.new.size(); i++) "
        "{ Integer n = [SELECT COUNT() FROM Account]; }"
    )
    assert cost.soql == R


def test_a_counted_loop_over_a_record_sized_collection_is_per_record():
    cost = own(
        "List<Account> accs = Trigger.new;\n"
        "for (Integer i = 0; i < accs.size(); i++) { Integer n = [SELECT COUNT() FROM Account]; }"
    )
    assert cost.soql == R


def test_a_counted_loop_with_a_variable_bound_is_a_refusal():
    cost = own(
        "Integer n = Trigger.size;\n"
        "for (Integer i = 0; i < n; i++) { Integer k = [SELECT COUNT() FROM Account]; }"
    )
    assert [r.reason for r in cost.refusals] == ["unbounded_loop"]


def test_a_counted_loop_without_a_bound_is_a_refusal():
    cost = own("for (Integer i = 0; ; i++) { Integer k = [SELECT COUNT() FROM Account]; }")
    assert [r.reason for r in cost.refusals] == ["unbounded_loop"]


def test_nested_loops_over_trigger_new_cost_r_squared():
    cost = own(
        "for (Account a : Trigger.new) { for (Account b : Trigger.new) {"
        " Integer n = [SELECT COUNT() FROM Account]; } }"
    )
    assert cost.soql == Poly.from_dict({2: 1})


def test_a_constant_loop_inside_a_record_loop_multiplies():
    cost = own(
        "for (Account a : Trigger.new) { for (Integer i = 0; i < 2; i++) {"
        " Integer n = [SELECT COUNT() FROM Account]; } }"
    )
    assert cost.soql == Poly.from_dict({1: 2})


def test_a_loop_over_a_query_result_with_a_cost_inside_is_a_refusal():
    cost = own(
        "for (Contact c : [SELECT Id FROM Contact]) "
        "{ Account a = [SELECT Id FROM Account LIMIT 1]; }"
    )
    assert cost.soql == ONE  # the loop header's own query is still charged
    assert [r.reason for r in cost.refusals] == ["unbounded_loop"]


def test_a_loop_over_a_query_result_with_no_cost_inside_is_fine():
    cost = own("for (Contact c : [SELECT Id FROM Contact]) { c.Phone = '1'; }")
    assert cost.soql == ONE
    assert cost.refusals == []


def test_a_query_inside_a_while_loop_is_a_refusal():
    cost = own("while (true) { Integer n = [SELECT COUNT() FROM Account]; }")
    assert [r.reason for r in cost.refusals] == ["unbounded_loop"]


def test_a_query_inside_a_do_loop_is_a_refusal():
    cost = own("do { Integer n = [SELECT COUNT() FROM Account]; } while (false);")
    assert [r.reason for r in cost.refusals] == ["unbounded_loop"]


def test_a_single_statement_loop_body_without_braces_is_costed():
    cost = own("for (Account a : Trigger.new) a.Name = [SELECT Name FROM Account LIMIT 1].Name;")
    assert cost.soql == R


def test_database_query_counts_as_soql():
    cost = own(
        "for (Account a : Trigger.new) "
        "{ List<SObject> r = Database.query('SELECT Id FROM Account'); }"
    )
    assert cost.soql == R


def test_database_count_query_and_query_locator_count_as_soql():
    cost = own(
        "Integer n = Database.countQuery('SELECT COUNT() FROM Account');\n"
        "Database.QueryLocator q = Database.getQueryLocator('SELECT Id FROM Account');"
    )
    assert cost.soql == Poly.const(2)


def test_a_sosl_bracket_counts_as_sosl_not_soql():
    cost = own("List<List<SObject>> r = [FIND 'x' IN ALL FIELDS RETURNING Account];")
    assert cost.sosl == ONE
    assert cost.soql.is_zero


def test_search_query_counts_as_sosl():
    cost = own("for (Account a : Trigger.new) { List<List<SObject>> r = Search.query('FIND x'); }")
    assert cost.sosl == R


def test_a_dml_on_a_new_record_costs_one_statement_and_one_row():
    cost = own("insert new Task(Subject = 'x');")
    assert cost.dml_statements == ONE
    assert cost.dml_rows == ONE
    assert cost.chains[0].sobject == "Task"
    assert cost.chains[0].operation == "insert"


def test_a_dml_inside_a_record_loop_costs_one_statement_per_record():
    cost = own("for (Account a : Trigger.new) { insert new Task(WhatId = a.Id); }")
    assert cost.dml_statements == R
    assert cost.dml_rows == R
    assert cost.chains[0].statements == R
    assert cost.chains[0].rows_per_statement == ONE


def test_a_dml_on_a_list_grown_per_record_costs_one_statement_and_r_rows():
    cost = own(
        "List<Task> tasks = new List<Task>();\n"
        "for (Account a : Trigger.new) { tasks.add(new Task(WhatId = a.Id)); }\n"
        "insert tasks;"
    )
    assert cost.dml_statements == ONE
    assert cost.dml_rows == R
    assert cost.chains[0].rows_per_statement == R


def test_a_dml_on_a_collection_literal_costs_its_item_count_in_rows():
    cost = own("insert new List<Task>{new Task(Subject = 'a'), new Task(Subject = 'b')};")
    assert cost.dml_rows == Poly.const(2)


def test_a_dml_on_a_list_filled_in_a_counted_loop_costs_the_bound_in_rows():
    cost = own(
        "List<Task> tasks = new List<Task>();\n"
        "for (Integer i = 0; i < 7; i++) { tasks.add(new Task(Subject = 'x')); }\n"
        "insert tasks;"
    )
    assert cost.dml_rows == Poly.const(7)


def test_a_dml_on_a_list_copied_from_trigger_new_is_r_rows():
    cost = own("List<Account> accs = Trigger.new.deepClone(); insert accs;")
    assert cost.dml_rows == R


def test_a_dml_on_a_map_built_from_trigger_new_is_r_rows():
    cost = own(
        "Map<Id, Account> m = new Map<Id, Account>(Trigger.new); update m.values();",
        header="Account (after update)",
    )
    assert cost.dml_rows == R


def test_a_dml_on_a_query_result_counts_the_statement_but_refuses_the_rows():
    cost = own("List<Contact> cs = [SELECT Id FROM Contact]; update cs;")
    assert cost.dml_statements == ONE
    assert [r.reason for r in cost.refusals] == ["unbounded_rows"]


def test_a_dml_on_an_unknown_variable_is_a_refusal():
    cost = own("update mystery;")
    assert [r.reason for r in cost.refusals] == ["unknown_target"]


def test_database_insert_is_a_dml_with_the_first_argument_as_target():
    cost = own("insert new Task(Subject = 'x'); Database.insert(new Task(Subject = 'y'), false);")
    assert cost.dml_statements == Poly.const(2)


def test_eventbus_publish_is_a_dml_statement():
    cost = own(
        "List<Order_Event__e> events = new List<Order_Event__e>();\n"
        "for (Account a : Trigger.new) { events.add(new Order_Event__e()); }\n"
        "EventBus.publish(events);"
    )
    assert cost.dml_statements == ONE
    assert cost.dml_rows == R


def test_a_static_call_into_a_project_class_is_costed_at_the_call_site_multiplier():
    classes = {
        "H": "public class H { public static void go(List<Account> accs) { "
        "Integer n = [SELECT COUNT() FROM Account]; } }"
    }
    cost = own("for (Account a : Trigger.new) { H.go(Trigger.new); }", classes)
    assert cost.soql == R


def test_a_parameter_receives_the_provenance_of_its_argument():
    classes = {
        "H": "public class H { public static void go(List<Account> accs) { "
        "for (Account a : accs) { Integer n = [SELECT COUNT() FROM Account]; } } }"
    }
    assert own("H.go(Trigger.new);", classes).soql == R


def test_a_scalar_parameter_passed_a_record_is_an_element_not_a_collection():
    classes = {
        "H": "public class H { public static void go(Account a) { "
        "insert new Task(WhatId = a.Id); } }"
    }
    cost = own("for (Account a : Trigger.new) { H.go(a); }", classes)
    assert cost.dml_statements == R
    assert cost.dml_rows == R


def test_a_missing_argument_leaves_the_parameter_unbounded():
    classes = {
        "H": "public class H { public static void go(List<Account> accs) { "
        "for (Account a : accs) { Integer n = [SELECT COUNT() FROM Account]; } } }"
    }
    cost = own("H.go();", classes)
    assert [r.reason for r in cost.refusals] == ["unbounded_loop"]


def test_an_instance_method_through_a_constructor_is_costed():
    classes = {
        "H": "public class H { public H() { } public void go(List<Account> accs) { "
        "for (Account a : accs) { insert new Task(WhatId = a.Id); } } }"
    }
    assert own("new H().go(Trigger.new);", classes).dml_statements == R


def test_a_constructor_with_a_cost_is_costed():
    classes = {"H": "public class H { public H() { Integer n = [SELECT COUNT() FROM Account]; } }"}
    assert own("for (Account a : Trigger.new) { H h = new H(); }", classes).soql == R


def test_an_instance_method_through_a_typed_variable_is_costed():
    classes = {
        "H": "public class H { public void go() { Integer n = [SELECT COUNT() FROM Account]; } }"
    }
    assert own("H h = new H(); h.go();", classes).soql == ONE


def test_a_method_called_on_this_or_bare_within_a_class_is_costed():
    classes = {
        "H": "public class H { public static void go() { helper(); this.other(); } "
        "static void helper() { Integer n = [SELECT COUNT() FROM Account]; } "
        "void other() { Integer n = [SELECT COUNT() FROM Account]; } }"
    }
    assert own("H.go();", classes).soql == Poly.const(2)


def test_a_recursive_method_is_a_refusal_not_an_infinite_loop():
    classes = {
        "H": "public class H { public static void go(Integer n) { "
        "Integer k = [SELECT COUNT() FROM Account]; go(n - 1); } }"
    }
    cost = own("H.go(3);", classes)
    assert [r.reason for r in cost.refusals] == ["recursion"]
    assert cost.soql == ONE


def test_a_call_to_a_method_the_class_does_not_declare_is_a_refusal():
    classes = {"H": "public class H { }"}
    assert [r.reason for r in own("H.go();", classes).refusals] == ["unreadable"]


def test_type_forname_is_a_dynamic_dispatch_refusal():
    cost = own("Type t = Type.forName('X'); Object o = t.newInstance();")
    assert [r.reason for r in cost.refusals] == ["dynamic_dispatch"]


def test_a_three_segment_call_into_an_unknown_namespace_is_a_refusal():
    cost = own("erp.SyncHandler.push(Trigger.new);")
    assert [(r.reason, r.construct) for r in cost.refusals] == [
        ("external_namespace", "erp.SyncHandler.push()")
    ]


def test_a_two_segment_call_on_an_unknown_class_is_a_refusal():
    cost = own("Mystery.run(Trigger.new);")
    assert [r.reason for r in cost.refusals] == ["external_namespace"]


def test_platform_calls_cost_nothing_and_are_recorded_as_sites():
    cost = own("System.debug(Trigger.new.size()); String s = String.valueOf(3);")
    assert cost.refusals == []
    assert cost.soql.is_zero
    assert any(s.kind == "platform" for s in cost.sites)


def test_a_custom_setting_or_sobject_static_call_is_a_platform_call():
    cost = own(
        "Routing__c r = Routing__c.getInstance(); Schema.SObjectType t = Account.sObjectType;"
    )
    assert cost.refusals == []


def test_a_static_field_of_the_owning_class_is_not_a_foreign_namespace():
    classes = {
        "H": "public class H { static final Map<String, String> M = new Map<String, String>(); "
        "public static String go(String k) { return M.get(k); } }"
    }
    assert own("String s = H.go('a');", classes).refusals == []


def test_a_static_boolean_read_in_an_if_is_recorded_as_a_guard():
    classes = {"G": "public class G { public static Boolean ran = false; }"}
    cost = own("if (!G.ran) { G.ran = true; }", classes)
    assert cost.guards == {"G.ran"}


def test_a_static_boolean_of_the_owning_class_is_a_guard_when_read_bare():
    classes = {
        "H": "public class H { static Boolean ran = false; "
        "public static void go() { if (ran) { return; } ran = true; } }"
    }
    assert own("H.go();", classes).guards == {"H.ran"}


def test_a_non_boolean_static_in_an_if_is_not_a_guard():
    classes = {"G": "public class G { public static Integer count = 0; }"}
    assert own("if (G.count > 0) { }", classes).guards == set()


def test_a_query_in_an_if_condition_is_charged():
    cost = own("for (Account a : Trigger.new) { if ([SELECT COUNT() FROM Account] > 0) { } }")
    assert cost.soql == R


def test_a_query_in_a_return_statement_is_charged():
    classes = {
        "H": "public class H { public static Integer go() "
        "{ return [SELECT COUNT() FROM Account]; } }"
    }
    assert own("Integer n = H.go();", classes).soql == ONE


def test_try_catch_finally_blocks_are_walked():
    cost = own(
        "try { Integer n = [SELECT COUNT() FROM Account]; } catch (Exception e) { "
        "Integer k = [SELECT COUNT() FROM Account]; } "
        "finally { Integer j = [SELECT COUNT() FROM Account]; }"
    )
    assert cost.soql == Poly.const(3)


def test_switch_blocks_are_walked():
    cost = own(
        "switch on Trigger.new[0].Type { when 'A' { Integer n = [SELECT COUNT() FROM Account]; } "
        "when else { } }"
    )
    assert cost.soql == ONE


def test_a_cast_does_not_hide_provenance():
    cost = own(
        "List<Account> accs = (List<Account>) Trigger.new;\n"
        "for (Account a : accs) { insert new Task(WhatId = a.Id); }"
    )
    assert cost.dml_statements == R


def test_a_collection_declared_without_a_value_starts_empty():
    cost = own("List<Task> tasks; tasks = new List<Task>(); insert tasks;")
    assert cost.dml_rows.is_zero


def test_reassigning_a_variable_replaces_its_provenance():
    cost = own("List<Account> accs = Trigger.new; accs = new List<Account>(); insert accs;")
    assert cost.dml_rows.is_zero


def test_async_calls_are_recorded_and_not_charged():
    cost = own("System.enqueueJob(new Q());", {"Q": "public class Q { }"})
    assert cost.soql.is_zero
    assert any(s.kind == "async" for s in cost.sites)


def test_a_dml_on_trigger_new_itself_is_an_unknown_target():
    cost = own("update Trigger.new;", header="Account (after update)")
    assert [r.reason for r in cost.refusals] == ["unknown_target"]


def test_a_dml_on_a_query_bracket_directly_refuses_rows_but_counts_the_statement():
    cost = own("update [SELECT Id FROM Contact];")
    assert cost.dml_statements == ONE
    assert cost.chains[0].sobject == "Contact"
    assert [r.reason for r in cost.refusals] == ["unbounded_rows"]


def test_sites_carry_file_and_line():
    cost = own("\nfor (Account a : Trigger.new) {\n  insert new Task();\n}")
    dml = [s for s in cost.sites if s.kind == "dml"][0]
    assert dml.path == "triggers/T.trigger"
    assert dml.line == 4


def test_a_site_to_dict_describes_the_multiplier():
    cost = own("for (Account a : Trigger.new) { insert new Task(); }")
    dml = [s.to_dict() for s in cost.sites if s.kind == "dml"][0]
    assert dml["multiplier"] == "r"


def test_a_refusal_to_dict_names_the_construct():
    cost = own("erp.SyncHandler.push(Trigger.new);")
    assert cost.refusals[0].to_dict()["construct"] == "erp.SyncHandler.push()"


def test_a_chain_site_to_dict_describes_rows():
    cost = own("for (Account a : Trigger.new) { insert new Task(); }")
    assert cost.chains[0].to_dict()["rows_per_statement"] == "1"


def test_test_loaddata_is_a_chain_with_a_resource_and_no_rows():
    cost = own("List<SObject> rows = Test.loadData(Account.sObjectType, 'Accounts');")
    assert cost.chains[0].resource == "Accounts"
    assert cost.chains[0].rows_per_statement is None


def test_test_loaddata_without_a_literal_resource_is_a_refusal():
    cost = own(
        "String name = 'Accounts'; List<SObject> rows = Test.loadData(Account.sObjectType, name);"
    )
    assert [r.reason for r in cost.refusals] == ["unknown_target"]


def test_a_dml_inside_an_unbounded_loop_is_a_refusal():
    cost = own("for (Contact c : [SELECT Id FROM Contact]) { insert new Task(WhoId = c.Id); }")
    assert [r.reason for r in cost.refusals] == ["unbounded_loop"]


def test_an_empty_collection_constructor_as_a_dml_target_is_zero_rows():
    cost = own("insert new List<Task>();")
    assert cost.dml_rows.is_zero
    assert cost.chains[0].sobject == "Task"


def test_a_dml_on_a_new_expression_without_a_type_is_an_unknown_target():
    cost = own("insert new;")
    assert [r.reason for r in cost.refusals] == ["unknown_target"]


def test_a_dml_on_a_variable_with_no_sobject_type_is_an_unknown_target():
    cost = own("Integer n = 3; insert n;")
    assert [r.reason for r in cost.refusals] == ["unknown_target"]


def test_a_loop_over_one_indexed_trigger_record_runs_once():
    cost = own("for (Account a : Trigger.new[0]) { Integer n = [SELECT COUNT() FROM Account]; }")
    assert cost.soql == ONE


def test_the_size_of_trigger_new_is_record_provenance_for_a_bound():
    cost = own(
        "Integer n = Trigger.new.size();\n"
        "for (Integer i = 0; i < n; i++) { Integer k = [SELECT COUNT() FROM Account]; }"
    )
    assert cost.soql == R


def test_a_known_collection_member_keeps_the_collection_provenance():
    cost = own("Set<Id> ids = Trigger.newMap.keySet(); Set<Id> copy = ids.clone(); update copy;")
    assert [r.reason for r in cost.refusals] == ["unknown_target"]


def test_a_constructor_call_with_an_empty_argument_list_and_a_chained_method():
    classes = {
        "H": "public class H { public void go() { Integer n = [SELECT COUNT() FROM Account]; } }"
    }
    assert own("new H().go();", classes).soql == ONE


def test_an_unreadable_constructor_expression_is_unbounded():
    cost = own("List<Account> accs = new; for (Account a : accs) { insert new Task(); }")
    assert [r.reason for r in cost.refusals] == ["unbounded_loop"]


def test_a_statement_ending_the_block_without_a_semicolon_is_still_read():
    cost = own("Integer n = [SELECT COUNT() FROM Account]")
    assert cost.soql == ONE
