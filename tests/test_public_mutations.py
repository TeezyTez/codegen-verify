"""Mutation audit tests: successful mutants are review signals, never task scores."""
import importlib
import json

import pytest


def module():
    return importlib.import_module("generation.public_benchmark.mutations")


def declaration(tokens, kind="method"):
    return {"id": "Solve", "name": "Solve", "kind": kind, "header_tokens": tokens.split()}


def test_type_directed_constants_and_nested_multi_return_types():
    row = declaration("method Solve ( ) returns ( x : int , yes : bool , xs : seq < ( int , int ) > , items : set < int > )")
    plan = module().make_mutants(row)
    assert len(plan["mutants"]) == 7  # empty + 3 numeric x 2 boolean
    assignments = [r["implementation"] for r in plan["mutants"]]
    assert "{}" in assignments
    assert "{ x := -1; yes := true; xs := []; items := {}; }" in assignments
    assert [r["name"] for r in plan["outputs"]] == ["x", "yes", "xs", "items"]


def test_empty_array_string_and_unsupported_types_are_explicit():
    mod = module()
    plan = mod.make_mutants(declaration("method Solve ( ) returns ( a : array < real > , s : string )"))
    assert plan["mutants"][1]["implementation"] == "{ a := new real[0]; s := []; }"
    unsupported = mod.make_mutants(declaration("method Solve ( ) returns ( x : Custom )"))
    assert len(unsupported["mutants"]) == 1
    assert unsupported["skipped"][0]["code"] == "unsupported_output_type"


def test_large_cartesian_suite_discloses_bound():
    row = declaration("method Solve ( ) returns ( a : int , b : int , c : int , d : int , e : int )")
    plan = module().make_mutants(row, max_constants=8)
    assert plan["constant_combinations"] == 243
    assert plan["truncated"] is True
    assert len(plan["mutants"]) == 9


def test_parse_type_failures_are_not_counted_as_killed():
    mod = module()
    assert mod.classify_mutant({"status": "parse_error"}) == "inapplicable_parse"
    assert mod.classify_mutant({"status": "resolution_error"}) == "inapplicable_type"
    assert mod.classify_mutant({"status": "ok"}, {"status": "verification_failed"}) == "killed"
    assert mod.classify_mutant({"status": "ok"}, {"status": "verified"}) == "survived"
    assert mod.classify_mutant({"status": "ok"}, {"status": "timeout"}) == "timeout"


def test_explicit_ids_select_only_admitted_frozen_members(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    for ident, status in [("T1", "admitted"), ("T2", "admitted"), ("T3", "not_admitted")]:
        (tasks / (ident + ".json")).write_text(json.dumps({"id": ident, "status": status}))
    assert set(module().select_admitted(tmp_path)) == {"T1", "T2"}
    assert set(module().select_admitted(tmp_path, ["T2"])) == {"T2"}
    for invalid in (["T3"], ["missing"], ["T1", "T1"], []):
        with pytest.raises(ValueError):
            module().select_admitted(tmp_path, invalid)


def task(ensures):
    from generation.public_benchmark.task import PublicTask
    return PublicTask({"id": "MUT1", "source": "fixture", "source-id": "1",
        "vc-description": "Return the required constant.", "vc-preamble": "", "vc-helpers": "",
        "vc-spec": "method Solve() returns (y: int) ensures " + ensures,
        "vc-code": "PRIVATE_REFERENCE_DO_NOT_USE", "vc-postamble": ""}, family_id="fixture")


@pytest.mark.parametrize("ensures, body, expected", [
    ("y == 7", "{ y := 0; }", "killed"),
    ("y == 0", "{ y := 0; }", "survived"),
    ("y == 0", "{ y := true; }", "inapplicable_type"),
])
def test_real_dafny_distinguishes_killed_surviving_and_ill_typed_mutants(tmp_path, ensures, body, expected):
    from generation.public_benchmark.structure import inspect_source
    current = task(ensures)
    frozen = inspect_source(current.skeleton)
    mutant = {"id": "constant-zero", "kind": "constant", "implementation": body, "helpers": "", "values": {"y": "0"}}
    result = module().evaluate_mutant(current, frozen, ["Solve"], mutant, tmp_path / "mutant")
    assert result["status"] == expected, result
    if expected == "inapplicable_type":
        assert result["verification"] is None
    else:
        assert result["verification"]["executed"] is True
        assert result["verification"]["real_verifier"] is True
    assert "PRIVATE_REFERENCE" not in (tmp_path / "mutant" / "candidate.dfy").read_text()
    assert result["manual_review_required"] is (expected == "survived")
    assert json.loads((tmp_path / "mutant" / "result.json").read_text())["status"] == expected
    assert module().evaluate_mutant(current, frozen, ["Solve"], mutant, tmp_path / "mutant") == result
    (tmp_path / "mutant" / "candidate.dfy").write_text("tampered")
    with pytest.raises(ValueError, match="artifact integrity"):
        module().evaluate_mutant(current, frozen, ["Solve"], mutant, tmp_path / "mutant")
