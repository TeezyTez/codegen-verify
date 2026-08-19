import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from agent import SpecGuidedAgent
from artifacts import AgentRequest, SpecArtifact, VerificationEvidence
from dafny_wrapper import ErrorInfo, VerificationResult


REQUEST = AgentRequest(
    problem_id="test",
    problem_desc="Return x.",
    entry_point="f",
    task_ir={"entry_point": "f", "prompt": "def f(x: int) -> int: ..."},
)


def artifact(version=1, decision="approve"):
    return SpecArtifact(
        text="method f(x: int) returns (result: int) ensures result == x",
        version=version,
        task_hash="task",
        decision=decision,
    )


def evidence(passed, error_type="postcondition", verified=0, errors=1):
    return VerificationEvidence(
        VerificationResult(
            passed=passed,
            errors=[] if passed else [ErrorInfo(error_type=error_type)],
            verified_count=verified,
            error_count=0 if passed else errors,
        )
    )


class FakeAuthority:
    def __init__(self, specs):
        self.specs = list(specs)
        self.calls = []

    def assess(self, **kwargs):
        self.calls.append(kwargs)
        return self.specs.pop(0)


class FakeSynthesizer:
    def __init__(self):
        self.generated = 0
        self.repaired = 0

    def generate(self, **_kwargs):
        self.generated += 1
        return f"candidate-{self.generated}"

    def repair(self, **_kwargs):
        self.repaired += 1
        return f"repair-{self.repaired}"


class FakeVerification:
    def __init__(self, results):
        self.results = list(results)
        self.codes = []

    def check(self, _spec, code, _entry):
        self.codes.append(code)
        return self.results.pop(0)


def test_rejected_spec_stops_before_candidate_generation():
    authority = FakeAuthority([artifact(decision="reject")])
    synth = FakeSynthesizer()
    agent = SpecGuidedAgent(
        spec_authority=authority,
        synthesizer=synth,
        verification=FakeVerification([]),
    )

    result = agent.run(REQUEST)

    assert result.status == "spec_rejected"
    assert synth.generated == 0
    assert result.requirement_analysis.requirements[0].id == "REQ-001"
    assert any(node.kind == "requirement" for node in result.traceability.nodes)


def test_verification_evidence_drives_bounded_repair():
    synth = FakeSynthesizer()
    verifier = FakeVerification([
        evidence(False, "syntax"),
        evidence(False, "postcondition", verified=1),
        evidence(True, verified=2),
    ])
    agent = SpecGuidedAgent(
        spec_authority=FakeAuthority([artifact()]),
        synthesizer=synth,
        verification=verifier,
        max_repairs=2,
    )

    result = agent.run(REQUEST)

    assert result.status == "verified"
    assert result.attempts == 3
    assert synth.repaired == 2
    assert verifier.codes == ["candidate-1", "repair-1", "repair-2"]
    assert [item.category for item in result.diagnoses] == ["CODE_ERROR", "UNKNOWN"]
    assert any(link.relation == "repaired_by" for link in result.traceability.links)


def test_development_counterexample_reopens_spec_authority():
    authority = FakeAuthority([artifact(1), artifact(2)])
    synth = FakeSynthesizer()
    verifier = FakeVerification([evidence(True), evidence(True)])
    dev_results = iter([
        (False, {"error": "x=2 expected 2 got 3"}),
        (True, {"error": None}),
    ])
    request = AgentRequest(
        problem_id=REQUEST.problem_id,
        problem_desc=REQUEST.problem_desc,
        entry_point=REQUEST.entry_point,
        task_ir=REQUEST.task_ir,
        development_problem={"entry_point": "f", "test": "def check(candidate): pass"},
    )
    agent = SpecGuidedAgent(
        spec_authority=authority,
        synthesizer=synth,
        verification=verifier,
        max_spec_revisions=1,
        development_runner=lambda *_args: next(dev_results),
    )

    result = agent.run(request)

    assert result.status == "verified"
    assert len(authority.calls) == 2
    assert authority.calls[1]["previous"].version == 1
    assert "expected 2 got 3" in authority.calls[1]["feedback"]
    assert synth.generated == 2
