import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

import pipeline
from dafny_wrapper import ErrorInfo, VerificationResult


SPEC = """method f(x: int) returns (result: int)
    ensures result == x
"""
GOOD_CODE = SPEC + "{ result := x; }"


def _state(code: str, **updates):
    state = {
        "round": 1,
        "code": code,
        "spec": SPEC,
        "entry_point": "f",
        "behavior_problem": {},
        "research_trace": [],
        "best_code": "",
        "best_spec": "",
        "best_verification": VerificationResult(),
        "best_quality": [],
        "stagnation_count": 0,
        "verification_attempts": 0,
    }
    state.update(updates)
    return state


class PipelineGuardTests(unittest.TestCase):
    def test_helper_before_public_method_is_not_placeholder_injection(self):
        code = """function abs_diff(a: real, b: real): real {
    if a >= b then a - b else b - a
}
method close(numbers: seq<real>, threshold: real) returns (result: bool) {
    result := false;
}
"""
        self.assertEqual(pipeline._static_code_issues(code), [])

    def test_pure_function_let_binding_is_not_rejected(self):
        code = "function twice(x: int): int { var y := x + 1; y * 2 }"
        self.assertEqual(pipeline._static_code_issues(code), [])

    def test_contract_gate_rejects_drift_without_calling_dafny(self):
        drifted = """method f(x: int) returns (result: int)
    requires x > 0
    ensures result == x
{ result := x; }
"""
        with patch.object(pipeline, "DafnyVerifier") as verifier:
            update = pipeline.verify_node(_state(drifted))

        verifier.assert_not_called()
        self.assertFalse(update["dafny_verified"])
        self.assertEqual(update["verification"].errors[0].error_type, "contract")

    def test_failed_regression_rolls_back_to_best_candidate(self):
        best_result = VerificationResult(
            passed=False,
            errors=[ErrorInfo(error_type="postcondition", message="old proof gap")],
            verified_count=1,
            error_count=1,
        )
        regression = VerificationResult(
            passed=False,
            errors=[ErrorInfo(error_type="syntax", message="new syntax error")],
            error_count=1,
        )
        candidate = SPEC + "{ result := x + 0; }"
        with patch.object(pipeline.DafnyVerifier, "verify", return_value=regression):
            update = pipeline.verify_node(_state(
                candidate,
                best_code=GOOD_CODE,
                best_spec=SPEC,
                best_verification=best_result,
                best_quality=list(pipeline._verification_quality(best_result)),
            ))

        self.assertTrue(update["candidate_rejected"])
        self.assertEqual(update["code"], GOOD_CODE)
        self.assertIs(update["verification"], best_result)

    def test_better_failed_candidate_becomes_new_best(self):
        best_result = VerificationResult(
            passed=False,
            errors=[ErrorInfo(error_type="postcondition", message="old proof gap")],
            verified_count=1,
            error_count=2,
        )
        improved = VerificationResult(
            passed=False,
            errors=[ErrorInfo(error_type="postcondition", message="smaller proof gap")],
            verified_count=2,
            error_count=1,
        )
        candidate = SPEC + "{ result := x + 0; }"
        with patch.object(pipeline.DafnyVerifier, "verify", return_value=improved):
            update = pipeline.verify_node(_state(
                candidate,
                best_code=GOOD_CODE,
                best_spec=SPEC,
                best_verification=best_result,
                best_quality=list(pipeline._verification_quality(best_result)),
            ))

        self.assertFalse(update["candidate_rejected"])
        self.assertEqual(update["best_code"], candidate)
        self.assertIs(update["best_verification"], improved)

    def test_contract_failures_rank_below_proof_failures(self):
        contract = VerificationResult(
            errors=[ErrorInfo(error_type="contract")], error_count=1
        )
        proof = VerificationResult(
            errors=[ErrorInfo(error_type="postcondition")], error_count=1
        )
        self.assertLess(
            pipeline._verification_quality(contract),
            pipeline._verification_quality(proof),
        )


if __name__ == "__main__":
    unittest.main()
