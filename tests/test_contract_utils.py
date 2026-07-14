import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from contract_utils import (
    bodyless_callable_names,
    build_direct_reference_program,
    check_contract_fidelity,
    parse_method_contract,
    restore_public_contract,
)


class ContractUtilsTests(unittest.TestCase):
    def test_multiline_contract_is_parsed(self):
        source = """method choose(xs: seq<int>) returns (result: int)
    requires |xs| > 0
    ensures forall i :: 0 <= i < |xs| ==>
        result >= xs[i]
    ensures result in xs

function Helper(x: int): int { x }
"""
        contract = parse_method_contract(source, "choose")
        self.assertIsNotNone(contract)
        self.assertEqual(contract.requires, ("|xs| > 0",))
        self.assertEqual(len(contract.ensures), 2)
        self.assertIn("result >= xs[i]", contract.ensures[0])

    def test_alpha_renamed_parameters_are_equivalent(self):
        spec = """method prefixes(string: string) returns (result: seq<string>)
    requires true
    ensures |result| == |string|
    ensures forall i :: 0 <= i < |result| ==> result[i] == string[..i+1]
"""
        code = """method prefixes(s: string) returns (out: seq<string>)
    ensures |out| == |s|
    ensures forall i :: 0 <= i < |out| ==> out[i] == s[..i+1]
{
    out := [];
}
"""
        self.assertTrue(check_contract_fidelity(spec, code, "prefixes").ok)

    def test_dropped_postcondition_is_rejected(self):
        spec = """method f(x: int) returns (result: int)
    ensures result >= x
    ensures result == x
"""
        code = """method f(x: int) returns (result: int)
    ensures result >= x
{ result := x; }
"""
        report = check_contract_fidelity(spec, code, "f")
        self.assertFalse(report.ok)
        self.assertTrue(any("missing ensures" in issue for issue in report.issues))

    def test_added_precondition_is_rejected(self):
        spec = """method f(x: int) returns (result: int)
    ensures result == x
"""
        code = """method f(x: int) returns (result: int)
    requires x > 0
    ensures result == x
{ result := x; }
"""
        report = check_contract_fidelity(spec, code, "f")
        self.assertFalse(report.ok)
        self.assertTrue(any("added/changed requires" in issue for issue in report.issues))

    def test_compact_body_does_not_become_part_of_last_clause(self):
        spec = """method f(x: int) returns (result: int)
    ensures result == x
"""
        code = """method f(x: int) returns (result: int)
    ensures result == x
{ result := x; }
"""
        self.assertTrue(check_contract_fidelity(spec, code, "f").ok)

    def test_grouped_parameter_declarations_are_preserved(self):
        contract = parse_method_contract(
            "method add(x, y: int) returns (result: int) ensures result == x + y",
            "add",
        )
        self.assertIsNotNone(contract)
        self.assertEqual([param.name for param in contract.params], ["x", "y"])
        self.assertEqual([param.typ for param in contract.params], ["int", "int"])

    def test_bound_quantifier_variables_may_be_alpha_renamed(self):
        spec = """method f(xs: seq<int>) returns (result: bool)
    ensures result == exists i, j :: 0 <= i < j < |xs| && xs[i] == xs[j]
"""
        code = """method f(xs: seq<int>) returns (result: bool)
    ensures result == exists a: int, b: int :: 0 <= a < b < |xs| && xs[a] == xs[b]
{ result := false; }
"""
        self.assertTrue(check_contract_fidelity(spec, code, "f").ok)

    def test_quantifier_body_changes_are_still_rejected(self):
        spec = """method f(xs: seq<int>) returns (result: bool)
    ensures result == exists i, j :: 0 <= i < j < |xs| && xs[i] == xs[j]
"""
        code = """method f(xs: seq<int>) returns (result: bool)
    ensures result == exists a, b :: 0 <= a < b < |xs| && xs[a] != xs[b]
{ result := false; }
"""
        self.assertFalse(check_contract_fidelity(spec, code, "f").ok)

    def test_restore_public_contract_keeps_helpers_and_method_body(self):
        spec = """method f(xs: seq<int>) returns (result: bool)
    ensures result == exists i, j :: 0 <= i < j < |xs| && xs[i] == xs[j]
"""
        candidate = """function Same(a: int, b: int): bool { a == b }

method f(xs: seq<int>) returns (result: bool)
    requires |xs| > 0
    ensures result == exists a, b :: 0 <= a < b < |xs| && Same(xs[a], xs[b])
{
    result := false;
}
"""
        restored = restore_public_contract(spec, candidate, "f")
        self.assertTrue(restored.startswith("function Same"))
        self.assertIn("{\n    result := false;\n}", restored)
        self.assertTrue(check_contract_fidelity(spec, restored, "f").ok)

    def test_build_direct_reference_program_uses_frozen_helper(self):
        spec = """function BelowZero(operations: seq<int>): bool {
    |operations| > 0 && operations[0] < 0
}

method below_zero(operations: seq<int>) returns (result: bool)
    ensures result == BelowZero(operations)
"""
        code = build_direct_reference_program(spec, "below_zero")
        self.assertIsNotNone(code)
        self.assertIn("result := BelowZero(operations);", code)
        self.assertEqual(code.count("function BelowZero"), 1)
        self.assertTrue(check_contract_fidelity(spec, code, "below_zero").ok)

    def test_direct_reference_requires_a_frozen_helper_definition(self):
        spec = """method f(x: int) returns (result: int)
    ensures result == Missing(x)
"""
        self.assertIsNone(build_direct_reference_program(spec, "f"))

    def test_direct_reference_rejects_bodyless_abstract_helper(self):
        spec = """method f(x: int) returns (result: int)
    ensures result == Abstract(x)

function Abstract(x: int): int
"""
        self.assertEqual(bodyless_callable_names(spec), {"Abstract"})
        self.assertIsNone(build_direct_reference_program(spec, "f"))

    def test_build_direct_reference_program_supports_multiple_returns(self):
        spec = """function Sum(xs: seq<int>): int {
    if |xs| == 0 then 0 else xs[0] + Sum(xs[1..])
}
function Product(xs: seq<int>): int {
    if |xs| == 0 then 1 else xs[0] * Product(xs[1..])
}
method sum_product(xs: seq<int>) returns (result0: int, result1: int)
    ensures result0 == Sum(xs)
    ensures result1 == Product(xs)
"""
        code = build_direct_reference_program(spec, "sum_product")
        self.assertIsNotNone(code)
        self.assertIn("result0 := Sum(xs);", code)
        self.assertIn("result1 := Product(xs);", code)


if __name__ == "__main__":
    unittest.main()
