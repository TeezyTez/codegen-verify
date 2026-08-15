import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

import pipeline
from dafny_wrapper import ErrorInfo, VerificationResult
from task_normalizer import normalize_humaneval_problem


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
    def test_signature_only_spec_agent_is_a_no_llm_baseline(self):
        task_ir = normalize_humaneval_problem({
            "task_id": "HumanEval/test",
            "entry_point": "f",
            "prompt": 'def f(x: int) -> int:\n    """Return x."""\n',
        }).to_dict()
        state = _state("", problem_id="HumanEval/test", problem_desc="Return x.", task_ir=task_ir)
        with patch.object(pipeline.config, "SPEC_GUIDANCE_MODE", "signature_only"), patch.object(
            pipeline, "spec_llm"
        ) as llm:
            update = pipeline.spec_agent(state)

        llm.assert_not_called()
        self.assertEqual(update["spec"], "method f(x: int) returns (result: int)")
        self.assertEqual(update["spec_adequacy"]["level"], "signature_only_baseline")

    def test_independent_mode_rejects_direct_reference_implementation(self):
        spec = """function Reference(x: int): int { x }

method f(x: int) returns (result: int)
    ensures result == Reference(x)
"""
        code = spec + "{ result := Reference(x); }"
        with patch.object(pipeline.config, "SPEC_GUIDANCE_MODE", "independent"):
            issues = pipeline._candidate_code_issues(spec, code, "f")
        self.assertTrue(any("independent implementation required" in issue for issue in issues))

    def test_verify_node_rechecks_independent_implementation_policy(self):
        spec = """function Reference(x: int): int { x }

method f(x: int) returns (result: int)
    ensures result == Reference(x)
"""
        code = spec + "{ result := Reference(x); }"
        with patch.object(pipeline.config, "SPEC_GUIDANCE_MODE", "independent"), patch.object(
            pipeline, "DafnyVerifier"
        ) as verifier:
            update = pipeline.verify_node(_state(code, spec=spec))

        verifier.assert_not_called()
        self.assertFalse(update["dafny_verified"])
        self.assertIn("independent implementation required", update["verification"].errors[0].message)

    def test_proof_repair_budget_routes_to_code_repair(self):
        state = _state("", repair_policy={"agent": "proof_repair_agent"}, proof_repair_attempts=1)
        with patch.object(pipeline.config, "MAX_PROOF_REPAIR_ATTEMPTS", 1):
            self.assertEqual(pipeline.decide_repair_route(state), "code_repair")

    def test_verification_spec_repair_invalidates_old_candidate(self):
        repaired_spec = """method f(x: int) returns (result: int)
    ensures result == x + 1
"""
        state = _state(
            GOOD_CODE,
            problem_desc="Return x plus one.",
            spec_adequacy={"flags": ["postcondition_ignores_inputs"]},
            last_attribution={"category": "spec_or_code_mismatch", "rationale": "weak contract"},
            repair_policy={"agent": "verification_spec_repair_agent"},
            verification_spec_repair_rounds=0,
        )
        with patch.object(pipeline, "repair_spec_with_llm", return_value={
            "repaired": True,
            "spec": repaired_spec,
            "adequacy": {"level": "strong_static", "flags": []},
            "attempts": 1,
        }), patch.object(pipeline, "spec_llm"):
            update = pipeline.verification_spec_repair_agent(state)

        self.assertTrue(update["verification_spec_repair_succeeded"])
        self.assertEqual(update["spec"], repaired_spec)
        self.assertEqual(update["code"], "")
        self.assertEqual(update["best_code"], "")
        self.assertEqual(update["critic_gate_status"], "pending")

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
