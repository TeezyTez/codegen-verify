import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from dafny_wrapper import ErrorInfo, VerificationResult
from repair_policy import choose_repair_policy


def test_spec_mismatch_routes_back_to_spec_repair():
    verification = VerificationResult(
        passed=False,
        errors=[ErrorInfo(error_type="postcondition", message="might not hold")],
        error_count=1,
    )
    decision = choose_repair_policy(
        verification,
        {"category": "spec_or_code_mismatch"},
        {"flags": ["postcondition_ignores_inputs"]},
        [],
    )
    assert decision.target == "spec"
    assert decision.agent == "verification_spec_repair_agent"


def test_syntax_error_stays_on_code_even_when_spec_is_weak():
    verification = VerificationResult(
        passed=False,
        errors=[ErrorInfo(error_type="syntax", message="parse error")],
        error_count=1,
    )
    decision = choose_repair_policy(
        verification,
        {"category": "spec_or_code_mismatch"},
        {"flags": ["postcondition_ignores_inputs"]},
        [],
    )
    assert decision.agent == "code_repair_agent"
