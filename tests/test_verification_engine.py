import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from dafny_wrapper import ErrorInfo, VerificationResult
from verification_engine import VerificationEngine


SPEC = """method f(x: int) returns (result: int)
    ensures result == x
"""


class FakeVerifier:
    def __init__(self, result=None):
        self.result = result or VerificationResult(passed=True, verified_count=1)
        self.calls = []

    def verify(self, code):
        self.calls.append(code)
        return self.result


def test_contract_drift_is_rejected_before_dafny():
    verifier = FakeVerifier()
    engine = VerificationEngine(verifier)
    drifted = """method f(x: int) returns (result: int)
    requires x > 0
    ensures result == x
{ result := x; }
"""

    evidence = engine.check(SPEC, drifted, "f")

    assert not evidence.passed
    assert evidence.contract_issues
    assert verifier.calls == []


def test_reference_helper_collapse_is_rejected_by_default():
    verifier = FakeVerifier()
    engine = VerificationEngine(verifier)
    spec = """function Reference(x: int): int { x }
method f(x: int) returns (result: int)
    ensures result == Reference(x)
"""
    code = spec + "{ result := Reference(x); }"

    evidence = engine.check(spec, code, "f")

    assert not evidence.passed
    assert evidence.reference_collapse
    assert verifier.calls == []


def test_independent_implementation_can_verify_against_helper_spec():
    verifier = FakeVerifier()
    engine = VerificationEngine(verifier)
    spec = """function Reference(x: int): int { x }
method f(x: int) returns (result: int)
    ensures result == Reference(x)
"""
    code = spec + "{ result := x; }"

    evidence = engine.check(spec, code, "f")

    assert evidence.passed
    assert verifier.calls == [code]


def test_proof_failure_ranks_above_language_failure():
    language = VerificationResult(
        errors=[ErrorInfo(error_type="syntax")], error_count=1
    )
    proof = VerificationResult(
        errors=[ErrorInfo(error_type="postcondition")], error_count=1
    )

    language_evidence = VerificationEngine(FakeVerifier(language)).check(
        SPEC, SPEC + "{ result := x; }", "f"
    )
    proof_evidence = VerificationEngine(FakeVerifier(proof)).check(
        SPEC, SPEC + "{ result := x; }", "f"
    )

    assert language_evidence.quality < proof_evidence.quality

