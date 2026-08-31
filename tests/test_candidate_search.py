import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from agent import SpecGuidedAgent
from artifacts import AgentRequest, SpecArtifact, VerificationEvidence
from dafny_wrapper import ErrorInfo, VerificationResult


REQUEST = AgentRequest(
    problem_id="search",
    problem_desc="Return x.",
    entry_point="f",
    task_ir={"entry_point": "f", "prompt": "def f(x: int) -> int: ..."},
)


def _evidence(passed):
    return VerificationEvidence(VerificationResult(
        passed=passed,
        errors=[] if passed else [ErrorInfo(error_type="postcondition")],
        verified_count=1 if passed else 0,
        error_count=0 if passed else 1,
    ))


class Authority:
    def assess(self, **_kwargs):
        return SpecArtifact(
            text="method f(x: int) returns (r: int) ensures r == x",
            version=1,
            task_hash="task",
            decision="approve",
        )


class Synthesizer:
    last_guard_issues = ()

    def __init__(self):
        self.kinds = []

    def generate(self, **_kwargs):
        return "root"

    def repair(self, **kwargs):
        self.kinds.append(kwargs["repair_kind"])
        return kwargs["repair_kind"]


class Verification:
    def check(self, _spec, code, _entry):
        return _evidence(code == "proof")


def test_unknown_failure_branches_to_implementation_and_proof_candidates():
    synth = Synthesizer()
    agent = SpecGuidedAgent(
        spec_authority=Authority(),
        synthesizer=synth,
        verification=Verification(),
        max_repairs=1,
        search_width=2,
    )

    result = agent.run(REQUEST)

    assert result.status == "verified"
    assert synth.kinds == ["implementation", "proof"]
    assert result.attempts == 3
    assert {item["repair_kind"] for item in result.search["current_pool"]} >= {
        "implementation", "proof"
    }

