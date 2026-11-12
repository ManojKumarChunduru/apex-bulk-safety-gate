"""The tokenizer and declaration reader: properties of the costing subset of Apex."""

import pytest

from absg.apex import (
    ApexSyntaxError,
    TypeName,
    matching_close,
    parse_class,
    parse_trigger,
    read_type,
    tokenize,
)


def kinds(source):
    return [t.kind for t in tokenize(source)]


def texts(source):
    return [t.text for t in tokenize(source)]


def test_a_select_bracket_becomes_one_soql_token():
    tokens = tokenize("x = [SELECT Id FROM Account WHERE Name = :n];")
    assert [t.kind for t in tokens] == ["ident", "punct", "soql", "punct"]
    assert tokens[2].text == "SELECT Id FROM Account WHERE Name = :n"


def test_a_find_bracket_becomes_one_sosl_token():
    tokens = tokenize("List<List<SObject>> r = [FIND 'x' IN ALL FIELDS RETURNING Account];")
    assert "sosl" in [t.kind for t in tokens]
    assert sum(1 for t in tokens if t.kind == "sosl") == 1


def test_a_bracket_that_is_an_index_stays_punctuation():
    assert kinds("x = items[0];") == [
        "ident",
        "punct",
        "ident",
        "punct",
        "number",
        "punct",
        "punct",
    ]


def test_select_is_matched_case_insensitively():
    assert "soql" in kinds("x = [ select Id from Account ];")


def test_a_nested_bracket_inside_a_query_does_not_end_it():
    tokens = tokenize("x = [SELECT Id FROM Account WHERE Id IN :ids[0]];")
    assert sum(1 for t in tokens if t.kind == "soql") == 1
    assert tokens[-1].is_punct(";")


def test_a_bracket_inside_a_string_inside_a_query_does_not_end_it():
    tokens = tokenize("x = [SELECT Id FROM Account WHERE Name = ']'];")
    assert tokens[2].kind == "soql"
    assert tokens[-1].is_punct(";")


def test_line_comments_are_dropped():
    assert texts("a = 1; // insert new Account()\nb = 2;") == [
        "a",
        "=",
        "1",
        ";",
        "b",
        "=",
        "2",
        ";",
    ]


def test_block_comments_are_dropped_and_lines_still_count():
    tokens = tokenize("/* one\ntwo */ x")
    assert tokens[0].text == "x"
    assert tokens[0].line == 2


def test_an_unterminated_block_comment_is_a_syntax_error():
    with pytest.raises(ApexSyntaxError):
        tokenize("/* never closed")


def test_string_contents_are_kept_but_quotes_are_not():
    tokens = tokenize("s = 'a\\'b';")
    assert tokens[2].kind == "string"
    assert tokens[2].text == "a\\'b"


def test_an_unterminated_string_is_a_syntax_error():
    with pytest.raises(ApexSyntaxError):
        tokenize("s = 'open")


def test_a_string_broken_by_a_newline_is_a_syntax_error():
    with pytest.raises(ApexSyntaxError):
        tokenize("s = 'open\nclosed';")


def test_an_unterminated_query_bracket_is_a_syntax_error():
    with pytest.raises(ApexSyntaxError):
        tokenize("x = [SELECT Id FROM Account")


def test_two_character_operators_are_single_tokens():
    assert texts("a <= b && c++") == ["a", "<=", "b", "&&", "c", "++"]


def test_line_numbers_follow_newlines():
    tokens = tokenize("a\n\nb")
    assert [t.line for t in tokens] == [1, 3]


def test_a_query_spanning_lines_advances_the_line_counter():
    tokens = tokenize("x = [SELECT Id\nFROM Account];\ny")
    assert tokens[-1].line == 3


def test_numbers_with_decimals_are_one_token():
    assert texts("x = 3.5;") == ["x", "=", "3.5", ";"]


def test_matching_close_finds_the_paired_brace():
    tokens = tokenize("{ a { b } c }")
    assert matching_close(tokens, 0) == len(tokens) - 1


def test_matching_close_raises_on_an_unbalanced_opener():
    tokens = tokenize("{ a { b }")
    with pytest.raises(ApexSyntaxError):
        matching_close(tokens, 0)


def test_read_type_reads_a_generic_list():
    type_name, j = read_type(tokenize("List<Account> accs"), 0)
    assert type_name == TypeName("List", ["Account"])
    assert j == 4


def test_read_type_reads_a_map_with_two_arguments():
    type_name, _ = read_type(tokenize("Map<Id, Contact> m"), 0)
    assert type_name.base == "Map"
    assert type_name.args == ["Id", "Contact"]
    assert type_name.element == "Contact"


def test_read_type_reads_a_nested_generic():
    type_name, _ = read_type(tokenize("Map<Id, List<Case>> m"), 0)
    assert type_name.args == ["Id", "List<Case>"]


def test_read_type_reads_an_array_suffix_as_a_list():
    type_name, _ = read_type(tokenize("Account[] accs"), 0)
    assert type_name.is_collection
    assert type_name.element == "Account"


def test_read_type_reads_a_dotted_name():
    type_name, j = read_type(tokenize("Schema.SObjectType x"), 0)
    assert type_name.base == "Schema.SObjectType"
    assert j == 3


def test_read_type_returns_none_at_punctuation():
    assert read_type(tokenize("= 1"), 0) == (None, 0)


def test_read_type_raises_on_an_unterminated_generic():
    with pytest.raises(ApexSyntaxError):
        read_type(tokenize("List<Account"), 0)


def test_sobject_of_a_scalar_type_is_the_type_itself():
    assert TypeName("Account").sobject == "Account"


def test_element_of_a_scalar_type_is_none():
    assert TypeName("Account").element is None


CLASS = """
@IsTest
private class Sample {
    public static Boolean ran = false;
    private static final Map<String, String> NAMES = new Map<String, String>{'a' => 'b'};
    public Integer count { get; set; }
    public Sample() { count = 0; }
    @IsTest
    static void checksSomething() { System.assert(true); }
    static testMethod void oldStyle() { System.assert(true); }
    public void instanceMethod(List<Account> accs, final Id ownerId) { insert accs; }
    public abstract void noBody();
    public class Inner { public void go() { } }
    public enum Kind { A, B }
}
"""


def test_parse_class_reads_the_name_and_annotations():
    decl = parse_class(CLASS)
    assert decl.name == "Sample"
    assert decl.is_test


def test_parse_class_reads_static_booleans():
    assert parse_class(CLASS).static_booleans() == {"ran"}


def test_parse_class_reads_a_field_initializer_with_a_collection_literal():
    field = parse_class(CLASS).fields["NAMES"]
    assert field.is_static
    assert field.type.base == "Map"
    assert field.initializer[0].is_ident("new")


def test_parse_class_reads_a_property_without_treating_its_accessors_as_methods():
    decl = parse_class(CLASS)
    assert "count" in decl.fields
    assert "get" not in decl.methods


def test_parse_class_reads_the_constructor_under_the_class_name():
    assert "Sample" in parse_class(CLASS).methods


def test_parse_class_marks_istest_and_testmethod_methods_as_tests():
    decl = parse_class(CLASS)
    assert decl.methods["checksSomething"].is_test
    assert decl.methods["oldStyle"].is_test
    assert not decl.methods["instanceMethod"].is_test


def test_parse_class_reads_parameters_with_a_final_modifier():
    params = parse_class(CLASS).methods["instanceMethod"].params
    assert [p.name for p in params] == ["accs", "ownerId"]
    assert params[0].type.element == "Account"


def test_parse_class_skips_an_abstract_method_with_no_body():
    assert "noBody" not in parse_class(CLASS).methods


def test_parse_class_reads_inner_classes_and_skips_enums():
    decl = parse_class(CLASS)
    assert "Inner" in decl.inner_classes
    assert "go" in decl.inner_classes["Inner"].methods
    assert "Kind" not in decl.inner_classes


def test_parse_class_reads_an_interface_as_an_empty_declaration():
    decl = parse_class("public interface IRouter { void route(List<Lead> leads); }")
    assert decl.name == "IRouter"
    assert decl.methods == {}


def test_parse_class_rejects_a_file_with_no_class():
    with pytest.raises(ApexSyntaxError):
        parse_class("public static void x() { }")


def test_parse_class_rejects_a_class_with_no_body():
    with pytest.raises(ApexSyntaxError):
        parse_class("public class X")


def test_parse_class_rejects_an_unreadable_member():
    with pytest.raises(ApexSyntaxError):
        parse_class("public class X { = 3; }")


def test_parse_class_reads_an_initializer_block_without_a_member():
    decl = parse_class("public class X { static { System.debug('x'); } public void a() { } }")
    assert list(decl.methods) == ["a"]


def test_parse_class_reads_an_annotation_with_arguments():
    decl = parse_class("@IsTest(SeeAllData=false) private class X { }")
    assert decl.is_test


TRIGGER = "trigger T on Account (before insert, after update) { System.debug(1); }"


def test_parse_trigger_reads_name_object_and_events():
    decl = parse_trigger(TRIGGER)
    assert decl.name == "T"
    assert decl.sobject == "Account"
    assert decl.events == {("before", "insert"), ("after", "update")}


def test_parse_trigger_fires_on_is_by_event_regardless_of_timing():
    decl = parse_trigger(TRIGGER)
    assert decl.fires_on("insert")
    assert decl.fires_on("update")
    assert not decl.fires_on("delete")


def test_parse_trigger_body_excludes_the_braces():
    assert parse_trigger(TRIGGER).body[0].is_ident("System")
    assert not parse_trigger(TRIGGER).body[-1].is_punct("}")


def test_parse_trigger_reads_a_custom_object_name():
    assert parse_trigger("trigger T on Order_Line__c (after insert) { }").sobject == "Order_Line__c"


@pytest.mark.parametrize(
    "source",
    [
        "class T { }",
        "trigger T Account (before insert) { }",
        "trigger T on Account before insert { }",
        "trigger T on Account (sideways insert) { }",
        "trigger T on Account () { }",
        "trigger T on Account (before insert)",
    ],
)
def test_parse_trigger_rejects_malformed_headers(source):
    with pytest.raises(ApexSyntaxError):
        parse_trigger(source)


def test_parse_class_rejects_an_unreadable_parameter_list():
    with pytest.raises(ApexSyntaxError):
        parse_class("public class X { public void a(List<Account>) { } }")


def test_parse_class_reads_a_trailing_modifier_without_a_member():
    decl = parse_class("public class X { public }")
    assert decl.methods == {}


def test_parse_class_reads_a_field_declared_without_a_semicolon_at_the_end():
    decl = parse_class("public class X { Integer n = 3 }")
    assert "n" in decl.fields


def test_parse_trigger_reads_a_namespaced_object():
    assert parse_trigger("trigger T on pkg.Thing__c (before insert) { }").sobject == "pkg.Thing__c"
