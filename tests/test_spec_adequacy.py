import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from spec_adequacy import check_spec_adequacy


def test_prefix_spec_without_executable_reference_is_flagged_without_score_penalty():
    spec = """method below_zero(operations: seq<int>) returns (result: bool)
    ensures result <==> exists i :: 0 <= i < |operations|
"""
    desc = "Fixed Dafny signature: method below_zero(operations: seq<int>) returns (result: bool)\nReturn true if a prefix balance is below zero."
    report = check_spec_adequacy(spec, desc, "below_zero")
    assert "proof_friendly_reference_missing" in report["flags"]
    assert report["score"] >= 85


def test_executable_reference_satisfies_proof_friendliness_signal():
    spec = """function BelowZero(operations: seq<int>): bool {
    if |operations| == 0 then false else operations[0] < 0 || BelowZero(operations[1..])
}
method below_zero(operations: seq<int>) returns (result: bool)
    ensures result == BelowZero(operations)
"""
    desc = "Return true if a prefix balance is below zero."
    report = check_spec_adequacy(spec, desc, "below_zero")
    assert "proof_friendly_reference_missing" not in report["flags"]


def test_sequence_result_without_reference_is_flagged():
    spec = """method duplicate(xs: seq<int>) returns (result: seq<int>)
    ensures |result| == 2 * |xs|
"""
    report = check_spec_adequacy(spec, "Return a list with each input duplicated.", "duplicate")
    assert "proof_friendly_reference_missing" in report["flags"]


def test_executable_sequence_reference_suppresses_duplicate_shape_flags():
    spec = """function Prefixes(s: string): seq<string> {
    if |s| == 0 then [] else Prefixes(s[..|s|-1]) + [s]
}
method all_prefixes(s: string) returns (result: seq<string>)
    ensures result == Prefixes(s)
"""
    report = check_spec_adequacy(
        spec,
        "Return all non-empty prefixes of a string.",
        "all_prefixes",
    )
    assert report["evidence"]["executable_result_reference"] is True
    assert "prefix_task_without_prefix_condition" not in report["flags"]
    assert "sequence_task_without_element_or_length_condition" not in report["flags"]


def test_longest_task_requests_executable_reference_helper():
    spec = """datatype Option<T> = None | Some(value: T)
method longest(xs: seq<string>) returns (result: Option<string>)
    ensures result.None? <==> |xs| == 0
"""
    report = check_spec_adequacy(
        spec,
        "Return the longest string, choosing the first on ties.",
        "longest",
    )
    assert "proof_friendly_reference_missing" in report["flags"]
