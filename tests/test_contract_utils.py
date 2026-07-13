import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from contract_utils import check_contract_fidelity, parse_method_contract


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


if __name__ == "__main__":
    unittest.main()
