import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from artifacts import AgentRequest, VerificationEvidence
from budget import BudgetLedger
from dafny_wrapper import VerificationResult
from experiment_conditions import DirectAgent


REQUEST = AgentRequest(
    problem_id="direct",
    problem_desc="Return x.",
    entry_point="f",
    task_ir={
        "task_id": "direct",
        "entry_point": "f",
        "prompt": 'def f(x: int) -> int:\n    """Return x."""\n',
    },
)


class Synthesizer:
    def __init__(self):
        self.repairs = 0

    def generate(self, _request, _signature):
        return "candidate"

    def repair(self, *_args):
        self.repairs += 1
        return "repaired"


class Verification:
    def __init__(self, passed):
        self.passed = passed
        self.calls = 0

    def check(self, *_args):
        self.calls += 1
        return VerificationEvidence(VerificationResult(
            passed=self.passed,
            verified_count=1 if self.passed else 0,
            error_count=0 if self.passed else 1,
        ))


def test_direct_one_is_a_real_single_shot_no_spec_baseline():
    synth = Synthesizer()
    verification = Verification(False)
    result = DirectAgent(
        condition_id="direct_1",
        synthesizer=synth,
        verification=verification,
        budget=BudgetLedger(),
        max_repairs=9,
    ).run(REQUEST)

    assert result.condition_id == "direct_1"
    assert result.spec.decision == "not_applicable"
    assert result.attempts == 1
    assert verification.calls == 1
    assert synth.repairs == 0
    assert result.stop_reason == "single_shot"

