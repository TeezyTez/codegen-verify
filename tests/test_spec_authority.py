import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

import config
from dafny_wrapper import VerificationResult
from spec_authority import SpecAuthority


PROBLEM = {
    "task_id": "HumanEval/test",
    "entry_point": "f",
    "prompt": '''def f(x: int) -> int:
    """Return x.
    >>> f(2)
    2
    """
''',
}
SPEC = """method f(x: int) returns (result: int)
    ensures result == x
"""


class FakeModel:
    provider = "fake"
    model = "fake"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def chat(self, system, user, **_kwargs):
        self.calls.append((system, user))
        return self.outputs.pop(0)


class FakeVerifier:
    def resolve(self, _spec):
        return VerificationResult(passed=True)


def approve(*_args, **_kwargs):
    return {"decision": "approve", "issues": [], "counterexamples": []}


def clean_mutation(*_args, **_kwargs):
    return {"mutants_total": 3, "mutants_verified": 0}


def authority(model, *, critic=approve, mutation=clean_mutation, repairs=1):
    return SpecAuthority(
        spec_model=model,
        critic_model=object(),
        probe_model=object(),
        verifier=FakeVerifier(),
        max_repairs=repairs,
        critic=critic,
        mutation_probe=mutation,
    )


def test_approved_spec_is_versioned_and_hashed(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_MUTATION_GUARD", True)
    monkeypatch.setattr(config, "ENABLE_SPEC_CRITIC", True)
    result = authority(FakeModel([SPEC])).assess(
        problem_id="HumanEval/test",
        problem_desc="Return x.",
        entry_point="f",
        task_ir=PROBLEM,
    )

    assert result.approved
    assert result.version == 1
    assert len(result.fingerprint) == 64
    assert result.structured is not None
    assert result.structured.requirements[0].id == "REQ-001"
    assert result.structured.clauses[0].id == "SPEC-POST-001"
    assert result.structured.clauses[0].status == "validated"


def test_structured_spec_bundle_preserves_explicit_requirement_mapping(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_MUTATION_GUARD", False)
    monkeypatch.setattr(config, "ENABLE_SPEC_CRITIC", False)
    bundle = {
        "clauses": [{
            "kind": "postcondition",
            "natural_language": "The result equals the input.",
            "formal_expression": "result == x",
            "related_requirements": ["REQ-001"],
            "confidence": 0.95,
        }],
        "formal_spec": SPEC,
    }

    result = authority(FakeModel([json.dumps(bundle)]), repairs=0).assess(
        problem_id="HumanEval/test",
        problem_desc="Return x.",
        entry_point="f",
        task_ir=PROBLEM,
    )

    clause = result.structured.clauses[0]
    assert result.approved
    assert clause.natural_language == "The result equals the input."
    assert clause.related_requirements == ("REQ-001",)


def test_mutation_failure_causes_bounded_regeneration(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_MUTATION_GUARD", True)
    monkeypatch.setattr(config, "ENABLE_SPEC_CRITIC", True)
    calls = {"count": 0}

    def mutation(*_args, **_kwargs):
        calls["count"] += 1
        return {"mutants_verified": 1 if calls["count"] == 1 else 0}

    model = FakeModel([SPEC, SPEC + "\n    ensures result >= x"])
    result = authority(model, mutation=mutation).assess(
        problem_id="HumanEval/test",
        problem_desc="Return x.",
        entry_point="f",
        task_ir=PROBLEM,
    )

    assert result.approved
    assert len(model.calls) == 2


def test_missing_mutation_evidence_abstains(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_MUTATION_GUARD", True)
    monkeypatch.setattr(config, "ENABLE_SPEC_CRITIC", True)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("Dafny unavailable")

    result = authority(FakeModel([SPEC]), mutation=unavailable).assess(
        problem_id="HumanEval/test",
        problem_desc="Return x.",
        entry_point="f",
        task_ir=PROBLEM,
    )

    assert result.decision == "abstain"
    assert "Dafny unavailable" in result.mutation["error"]


def test_revising_an_approved_spec_changes_version_and_fingerprint(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_MUTATION_GUARD", False)
    monkeypatch.setattr(config, "ENABLE_SPEC_CRITIC", False)
    model = FakeModel([SPEC, SPEC + "\n    ensures result >= x"])
    spec_authority = authority(model)
    first = spec_authority.assess(
        problem_id="HumanEval/test",
        problem_desc="Return x.",
        entry_point="f",
        task_ir=PROBLEM,
    )
    second = spec_authority.assess(
        problem_id="HumanEval/test",
        problem_desc="Return x.",
        entry_point="f",
        task_ir=PROBLEM,
        feedback="development counterexample",
        previous=first,
    )

    assert second.version == 2
    assert second.fingerprint != first.fingerprint
