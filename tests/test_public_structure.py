"""Integration tests exercise the installed Dafny parser, not a substitute grammar."""
import importlib
import pytest


def adapter():
    return importlib.import_module("generation.public_benchmark.structure")


SOURCE = """
predicate Positive(x: int) { x > 0 }
function Inc(x: int): int { x + 1 }
lemma IncPositive(x: int)
  requires Positive(x)
  ensures Positive(Inc(x))
{}
method Run(x: int) returns (y: int)
  requires Positive(x)
  ensures y == Inc(x)
{
  IncPositive(x);
  y := Inc(x);
}
"""


def test_real_ast_declarations_contract_regions_and_resolved_dependencies():
    report = adapter().inspect_source(SOURCE)
    assert report["status"] == "ok", report
    assert report["trusted_ast"] is True
    declarations = {d["name"]: d for d in report["declarations"]}
    assert set(declarations) == {"Positive", "Inc", "IncPositive", "Run"}
    assert set(declarations["Run"]["depends_on"]) == {"Positive", "Inc", "IncPositive"}
    assert "ensures" in declarations["Run"]["header"]
    assert "ensures" not in declarations["Run"]["body"]
    assert declarations["Run"]["verifier_names"] == ["Run"]
    assert set(report["expected_verifier_targets"]) == set(declarations)


@pytest.mark.parametrize("source, code", [
    ("method M() { assume true; }", "assume"),
    ("method M() ensures false { expect false; }", "assume"),
    ("method M() { var x: int; x :| assume true; }", "assume"),
    ("method {:axiom} M() {}", "attribute"),
    ("method {:verify false} M() {}", "attribute"),
    ("method {:extern} M() {}", "attribute"),
    ("method M()", "missing_body"),
    ("lemma M() ensures true", "missing_body"),
    ("method M() decreases * {}", "nontermination"),
    ("method M() { while false invariant true }", "missing_body"),
    ("lemma M() { forall x: int ensures x == x }", "missing_body"),
    ('include "absent.dfy"\nmethod M() {}', "external_source"),
    ('module {:options "--allow-axioms"} A { method M() {} }', "attribute"),
    ("module A { method M() {} }", "unsupported_declaration"),
])
def test_trust_bypasses_and_unsupported_structures_fail_closed(source, code):
    report = adapter().inspect_source(source)
    assert report["status"] == "rejected", report
    assert any(f["code"] == code for f in report["findings"]), report


def test_comments_and_strings_are_not_trust_constructs():
    report = adapter().inspect_source('method M() { // assume false;\n print "assume {:axiom} include"; }')
    assert report["status"] == "ok", report


def test_resolution_failure_is_not_trusted_acceptance():
    report = adapter().inspect_source("method M() { Unknown(); }")
    assert report["status"] == "resolution_error"


def test_frozen_comparison_allows_only_authorized_body_changes():
    structure = adapter()
    original = structure.inspect_source(SOURCE)
    changed = structure.inspect_source(SOURCE.replace("y := Inc(x);", "y := x + 1;"))
    assert structure.compare_frozen(original, changed, {"Run"}) == []
    mutated = structure.inspect_source(SOURCE.replace("ensures y == Inc(x)", "ensures y >= x"))
    assert structure.compare_frozen(original, mutated, {"Run"})
    helper = structure.inspect_source(SOURCE.replace("x + 1", "x + 2"))
    assert structure.compare_frozen(original, helper, {"Run"})


def test_new_helper_cannot_shadow_fixed_contract_binding():
    structure = adapter()
    original = structure.inspect_source("function P(x: int): bool { x > 0 } method M(x: int) requires P(x) {}")
    candidate = structure.inspect_source("function P(x: int): bool { x > 0 } method M(x: int, P: int -> bool) requires P(x) {}")
    assert candidate["status"] != "ok" or structure.compare_frozen(original, candidate, {"M"})


def test_contracts_exclude_resolver_inferred_decreases():
    report = adapter().inspect_source("method M(x: int) {}")
    assert report["status"] == "ok", report
    assert report["declarations"][0]["contracts"]["Decreases"] == []
    assert "decreases" not in report["declarations"][0]["signature"]


def test_frozen_contract_ignores_comment_and_whitespace_changes():
    structure = adapter()
    a = structure.inspect_source("method M(x:int) ensures x == x {}")
    b = structure.inspect_source("method M ( x : int ) // contract\n ensures x == x { }")
    assert structure.compare_frozen(a, b, {"M"}) == []


def test_unsupported_higher_order_call_is_explicitly_rejected():
    report = adapter().inspect_source("method M(f: int -> int) { var x := f(0); }")
    assert report["status"] == "rejected", report
    assert any(f["code"] == "unsupported_dependency" for f in report["findings"])


def test_builtin_array_member_is_resolved_but_not_a_user_dependency():
    report = adapter().inspect_source("method M(a: array<int>) requires a.Length > 0 {}")
    assert report["status"] == "ok", report
    declaration = report["declarations"][0]
    assert declaration["depends_on"] == []
    assert declaration["builtin_references"] == ["array.Length"]
