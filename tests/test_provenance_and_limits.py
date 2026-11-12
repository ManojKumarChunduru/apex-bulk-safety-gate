"""Polynomials in r, provenance, and the breach-size arithmetic."""

import json

import pytest

from absg.limits import (
    DEFAULT_LIMITS,
    Policy,
    PolicyError,
    breach_size,
    cost_at,
    load_policy,
)
from absg.provenance import Poly, Provenance


def test_adding_polynomials_adds_coefficients_by_degree():
    assert (Poly.const(2) + Poly.record()).as_dict() == {0: 2, 1: 1}


def test_multiplying_a_record_term_by_itself_gives_r_squared():
    assert (Poly.record() * Poly.record()).as_dict() == {2: 1}


def test_multiplying_by_a_constant_scales_every_coefficient():
    assert (Poly.const(3) * (Poly.const(1) + Poly.record())).as_dict() == {0: 3, 1: 3}


def test_composition_substitutes_the_inner_polynomial_for_r():
    outer = Poly.const(1) + Poly.record()  # 1 + r
    inner = Poly.const(5)  # r := 5
    assert outer.compose(inner).as_dict() == {0: 6}


def test_composition_with_r_is_the_identity():
    outer = Poly.from_dict({0: 2, 1: 3, 2: 1})
    assert outer.compose(Poly.record()) == outer


def test_evaluation_sums_terms():
    assert Poly.from_dict({0: 2, 1: 3, 2: 1}).evaluate(4) == 2 + 12 + 16


def test_zero_coefficients_are_dropped():
    assert Poly.from_dict({0: 0, 1: 2}).coeffs == ((1, 2),)
    assert Poly.from_dict({0: 0}).is_zero


def test_describe_reads_as_arithmetic():
    assert Poly.from_dict({0: 1, 1: 2, 2: 1}).describe() == "1 + 2r + r^2"
    assert Poly.record().describe() == "r"
    assert Poly.from_dict({3: 4}).describe() == "4r^3"
    assert Poly().describe() == "0"


def test_degree_of_the_zero_polynomial_is_zero():
    assert Poly().degree == 0
    assert Poly.record().degree == 1


def test_of_builds_from_keyword_degrees():
    assert Poly.of(d0=1, d1=2) == Poly.from_dict({0: 1, 1: 2})


def test_record_provenance_is_bounded_by_r():
    assert Provenance.record().size == Poly.record()
    assert Provenance.record().is_bounded


def test_unbounded_provenance_has_no_size():
    assert not Provenance.unbounded("query").is_bounded


def test_growing_a_constant_collection_inside_a_record_loop_makes_it_record_sized():
    grown = Provenance.const(0).grow(Poly.record())
    assert grown.kind == "record"
    assert grown.size == Poly.record()
    assert "per-record" in grown.note


def test_growing_a_constant_collection_outside_a_loop_adds_one():
    grown = Provenance.const(2).grow(Poly.const(1))
    assert grown.kind == "const"
    assert grown.size == Poly.const(3)


def test_growing_inside_an_unbounded_loop_makes_the_collection_unbounded():
    assert not Provenance.const(0).grow(None).is_bounded


def test_growing_an_unbounded_collection_keeps_it_unbounded():
    assert Provenance.unbounded("x").grow(Poly.const(1)).kind == "unbounded"


def test_cost_at_sums_whole_chunks_and_the_remainder():
    poly = Poly.const(3) + Poly.record()  # 3 + r per invocation
    assert cost_at(poly, 200, 200) == 203
    assert cost_at(poly, 450, 200) == 2 * 203 + 3 + 50


def test_cost_at_zero_records_is_zero():
    assert cost_at(Poly.record(), 0, 200) == 0


def test_one_query_per_record_breaches_at_the_101st_record():
    assert breach_size(Poly.record(), 100, 200, 10000) == 101


def test_one_statement_per_record_breaches_at_the_151st_record():
    assert breach_size(Poly.record(), 150, 200, 10000) == 151


def test_three_queries_per_invocation_breach_at_the_34th_chunk():
    assert breach_size(Poly.const(3), 100, 200, 10000) == 33 * 200 + 1


def test_one_query_per_invocation_does_not_breach_within_a_bulk_api_batch():
    assert breach_size(Poly.const(1), 100, 200, 10000) is None


def test_one_query_per_invocation_breaches_at_the_101st_chunk_given_a_larger_horizon():
    assert breach_size(Poly.const(1), 100, 200, 30000) == 100 * 200 + 1


def test_a_zero_cost_never_breaches():
    assert breach_size(Poly(), 100, 200, 10000) is None


def test_a_quadratic_cost_breaches_early():
    assert breach_size(Poly.from_dict({2: 1}), 100, 200, 10000) == 11


def test_a_per_invocation_query_moves_the_per_record_breach_one_record_earlier():
    # 1 + r per invocation: 200 records cost 201, so the 101st query is on the 100th record
    assert breach_size(Poly.const(1) + Poly.record(), 100, 200, 10000) == 100


def test_default_limits_match_the_documented_synchronous_values():
    policy = Policy()
    assert policy.value("soql_queries") == 100
    assert policy.value("sosl_queries") == 20
    assert policy.value("dml_statements") == 150
    assert policy.value("dml_rows") == 10000


def test_async_context_doubles_the_soql_limit_only():
    policy = Policy(context="async")
    assert policy.value("soql_queries") == 200
    assert policy.value("dml_statements") == 150


def test_every_default_limit_carries_a_reason():
    assert all(limit.reason for limit in DEFAULT_LIMITS)


def test_describe_lists_limits_and_the_three_record_counts():
    names = [row["name"] for row in Policy().describe()]
    assert names == [
        "soql_queries",
        "sosl_queries",
        "dml_statements",
        "dml_rows",
        "chunk_size",
        "horizon",
        "records",
    ]


def test_overrides_change_a_limit_value():
    policy = Policy()
    policy.apply_overrides({"limits": {"soql_queries": {"sync": 90}}})
    assert policy.value("soql_queries") == 90
    assert policy.limits["soql_queries"].async_ == 200


def test_overrides_change_chunk_size_horizon_and_records():
    policy = Policy()
    policy.apply_overrides({"chunk_size": 100, "horizon": 500, "records": 50, "context": "async"})
    assert (policy.chunk_size, policy.horizon, policy.records, policy.context) == (
        100,
        500,
        50,
        "async",
    )


@pytest.mark.parametrize(
    "overrides",
    [
        [],
        {"colour": 1},
        {"limits": {"heap": {"sync": 1}}},
        {"limits": {"soql_queries": 5}},
        {"limits": {"soql_queries": {"sync": 0}}},
        {"limits": {"soql_queries": {"sync": True}}},
        {"limits": {"soql_queries": {"async": "many"}}},
        {"chunk_size": -1},
        {"horizon": "far"},
        {"context": "sideways"},
    ],
)
def test_malformed_overrides_are_refused(overrides):
    with pytest.raises(PolicyError):
        Policy().apply_overrides(overrides)


def test_load_policy_reads_a_file_and_applies_context_and_records(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"limits": {"dml_statements": {"sync": 100}}}))
    policy = load_policy(path, "sync", 300)
    assert policy.value("dml_statements") == 100
    assert policy.records == 300


def test_load_policy_rejects_a_missing_file(tmp_path):
    with pytest.raises(PolicyError):
        load_policy(tmp_path / "missing.json", "sync", None)


def test_load_policy_rejects_invalid_json(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text("{")
    with pytest.raises(PolicyError):
        load_policy(path, "sync", None)


def test_load_policy_rejects_a_bad_context_or_record_count():
    with pytest.raises(PolicyError):
        load_policy(None, "sideways", None)
    with pytest.raises(PolicyError):
        load_policy(None, "sync", 0)
