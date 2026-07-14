import sys
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from mutation_probe import generate_mutants, probe_spec_mutants


class RejectAllVerifier:
    def verify(self, _code):
        return SimpleNamespace(passed=False, error_count=1)


def _by_name(spec: str):
    return {mutant.name: mutant for mutant in generate_mutants(spec)}


def test_sequence_mutants_cover_identity_drop_reverse_and_duplicate():
    mutants = _by_name(
        "method transform(xs: seq<int>) returns (result: seq<int>)\n"
        "    ensures true"
    )

    assert "return_param_xs" in mutants
    assert "drop_first_xs" in mutants
    assert "drop_last_xs" in mutants
    assert "reverse_input_xs" in mutants
    assert "duplicate_input_xs" in mutants
    assert "else xs[..|xs| - 1]" in mutants["drop_last_xs"].code
    assert (
        "mutationIndex requires 0 <= mutationIndex < |xs|"
        in mutants["reverse_input_xs"].code
    )


def test_string_is_treated_as_a_character_sequence():
    mutants = _by_name(
        "method transform(text: string) returns (result: string)\n"
        "    ensures true"
    )

    assert {"return_param_text", "drop_last_text", "reverse_input_text"} <= mutants.keys()


def test_numeric_mutants_include_both_off_by_one_directions_and_negation():
    mutants = _by_name(
        "method transform(x: int) returns (result: int)\n"
        "    ensures true"
    )

    assert "param_plus_one_x" in mutants
    assert "param_minus_one_x" in mutants
    assert "negate_param_x" in mutants
    assert "negative_constant_return" in mutants
    assert "result := (x + 1);" in mutants["param_plus_one_x"].code
    assert "result := (x - 1);" in mutants["param_minus_one_x"].code


def test_collection_to_scalar_mutants_probe_length_relationships():
    mutants = _by_name(
        "method measure(xs: seq<int>) returns (result: int)\n"
        "    ensures true"
    )

    assert "input_length_xs" in mutants
    assert "input_length_plus_one_xs" in mutants
    assert "input_length_minus_one_xs" in mutants


def test_multi_return_mutants_assign_every_output():
    mutants = _by_name(
        "method classify(x: int) returns (value: int, ok: bool)\n"
        "    ensures true"
    )

    code = mutants["return_value_param_x"].code
    assert "value := x;" in code
    assert "ok := false;" in code


def test_optional_return_has_none_and_some_mutants():
    mutants = _by_name(
        "datatype Option<T> = None | Some(value: T)\n"
        "method maybe(x: int) returns (result: Option<int>)\n"
        "    ensures true"
    )

    assert "default_return" in mutants
    assert "wrap_param_some_x" in mutants
    assert "result := None;" in mutants["default_return"].code
    assert "result := Some(x);" in mutants["wrap_param_some_x"].code


def test_too_few_mutants_report_insufficient_instead_of_low():
    # With no inputs, a bool-returning method has only the two constant mutants.
    report = probe_spec_mutants(
        "method decide() returns (result: bool)\n    ensures true",
        verifier=RejectAllVerifier(),
    )

    assert report["mutants_total"] == 2
    assert report["mutants_verified"] == 0
    assert report["probe_strength"] == "insufficient"
    assert report["mutation_adequacy_risk"] == "insufficient"


def test_sufficient_rejected_mutants_can_report_low_risk():
    report = probe_spec_mutants(
        "method transform(x: int) returns (result: int)\n    ensures true",
        verifier=RejectAllVerifier(),
    )

    assert report["mutants_total"] >= report["minimum_mutants_required"]
    assert report["probe_strength"] == "sufficient"
    assert report["mutation_adequacy_risk"] == "low"
