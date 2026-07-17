import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from analyze_results import repair_trace_metrics, result_row, summarize, write_csv


def verification(passed: bool, errors: int = 0, error_type: str = "postcondition"):
    return {
        "passed": passed,
        "verified_count": 1 if passed else 0,
        "error_count": errors,
        "errors": [] if passed else [{"type": error_type, "message": "failure"}],
    }


def verify_event(passed: bool, errors: int = 0, error_type: str = "postcondition", **extra):
    event = {
        "stage": "verify",
        "round": 1,
        "verification": verification(passed, errors, error_type),
    }
    event.update(extra)
    return event


class RepairTraceMetricTests(unittest.TestCase):
    def test_embedded_inloop_mutation_report_is_used_without_sidecar(self):
        row = result_row({
            "task_id": "t",
            "inloop_mutation_adequacy": {
                "mutants_total": 6,
                "mutants_verified": 0,
                "suspicious_mutants": 0,
                "mutation_adequacy_risk": "low",
            },
        })
        self.assertEqual(row["mutants_total"], 6)
        self.assertEqual(row["mutation_adequacy_risk"], "low")

    def test_eventual_task_pass_does_not_credit_earlier_failed_proof_repair(self):
        trace = [
            verify_event(False, 2),
            {"stage": "proof_repair", "round": 1, "action": "proof_repaired"},
            verify_event(False, 1),
            {"stage": "repair", "round": 2, "action": "candidate_accepted_for_verification"},
            verify_event(True),
        ]
        row = result_row({"task_id": "t", "passed": True, "research_trace": trace})
        summary = summarize([row])

        self.assertEqual(row["proof_repair_calls"], 1)
        self.assertEqual(row["proof_repair_direct_successes"], 0)
        self.assertEqual(row["code_repair_direct_successes"], 1)
        self.assertEqual(summary["proof_repair_success"], 0)
        self.assertEqual(summary["code_repair_success"], 1)

    def test_calls_are_counted_per_attempt_not_per_task(self):
        trace = [
            verify_event(False, 3),
            {"stage": "proof_repair", "action": "proof_repaired"},
            verify_event(False, 2),
            {"stage": "proof_repair", "action": "proof_repaired"},
            verify_event(True),
        ]
        metrics = repair_trace_metrics(trace)["proof_repair"]

        self.assertEqual(metrics["calls"], 2)
        self.assertEqual(metrics["evaluated"], 2)
        self.assertEqual(metrics["direct_successes"], 1)

    def test_contract_drift_fallback_cannot_inherit_code_repair_success(self):
        trace = [
            verify_event(False, 2),
            {
                "stage": "proof_repair",
                "action": "contract_preservation_failed",
                "missing_contract_clauses": ["missing ensures result == x"],
            },
            {"stage": "repair", "action": "candidate_accepted_for_verification"},
            verify_event(True),
        ]
        metrics = repair_trace_metrics(trace)

        self.assertEqual(metrics["proof_repair"]["contract_drifts"], 1)
        self.assertEqual(metrics["proof_repair"]["preverify_rejections"], 1)
        self.assertEqual(metrics["proof_repair"]["direct_successes"], 0)
        self.assertEqual(metrics["code_repair"]["direct_successes"], 1)

    def test_worse_candidate_is_a_regression_and_equal_candidate_is_stagnation(self):
        worse = verification(False, 3)
        equal = verification(False, 1)
        trace = [
            verify_event(False, 1),
            {"stage": "proof_repair", "action": "proof_repaired"},
            verify_event(
                False,
                1,
                candidate_verification=worse,
                candidate_rejected=True,
                rollback_reason="non_monotonic_verification",
            ),
            {"stage": "proof_repair", "action": "proof_repaired"},
            verify_event(
                False,
                1,
                candidate_verification=equal,
                candidate_rejected=True,
                rollback_reason="non_monotonic_verification",
            ),
        ]
        metrics = repair_trace_metrics(trace)["proof_repair"]

        self.assertEqual(metrics["regressions"], 1)
        self.assertEqual(metrics["non_improvements"], 1)

    def test_candidate_rejected_before_verify_is_never_a_direct_success(self):
        trace = [
            verify_event(False, 1),
            {"stage": "repair", "action": "candidate_rejected", "candidate_rejected": True},
            # The graph may reverify unchanged best-so-far code; that result is
            # not an outcome of the rejected candidate.
            verify_event(True),
        ]
        metrics = repair_trace_metrics(trace)["code_repair"]

        self.assertEqual(metrics["calls"], 1)
        self.assertEqual(metrics["preverify_rejections"], 1)
        self.assertEqual(metrics["evaluated"], 0)
        self.assertEqual(metrics["direct_successes"], 0)

    def test_alignment_internal_verification_rollback_is_reported_as_regression(self):
        trace = [
            verify_event(True),
            {
                "stage": "alignment_repair",
                "action": "regression_rolled_back",
                "rollback_reason": "verification_regression",
            },
            verify_event(True),
        ]
        metrics = repair_trace_metrics(trace)["alignment_repair"]

        self.assertEqual(metrics["calls"], 1)
        self.assertEqual(metrics["evaluated"], 1)
        self.assertEqual(metrics["regressions"], 1)
        self.assertEqual(metrics["direct_successes"], 0)

    def test_missing_followup_verify_is_unevaluated(self):
        metrics = repair_trace_metrics(
            [{"stage": "proof_repair", "action": "proof_repaired"}]
        )["proof_repair"]
        self.assertEqual(metrics["calls"], 1)
        self.assertEqual(metrics["unevaluated"], 1)

    def test_csv_contains_repair_audit_columns(self):
        row = result_row({"task_id": "t", "research_trace": []})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            write_csv([row], path)
            header = path.read_text(encoding="utf-8-sig").splitlines()[0]

        self.assertIn("proof_repair_direct_successes", header)
        self.assertIn("code_repair_contract_drifts", header)
        self.assertIn("critic_reconciliation_audit_decision", header)
        self.assertIn("critic_executable_dafny_errors", header)

    def test_critic_decision_and_evidence_are_reported(self):
        row = result_row({
            "task_id": "t",
            "critic_gate_status": "rejected",
            "critic_repair_rounds": 1,
            "spec_critic": {
                "decision": "reject",
                "confidence": 0.9,
                "critic_provider": "deepseek",
                "critic_model": "deepseek-chat",
                "review_passes": 2,
                "issues": [{"severity": "high"}],
                "counterexamples": [{"input": "[-1]"}],
            },
        })
        summary = summarize([row])

        self.assertEqual(row["critic_decision"], "reject")
        self.assertEqual(row["critic_counterexample_count"], 1)
        self.assertEqual(row["attribution_category"], "critic_reject")
        self.assertEqual(row["repair_target"], "spec_critic_gate")
        self.assertEqual(summary["critic_decisions"], {"reject": 1})

    def test_critic_reconciliation_and_executable_diagnostics_are_aggregated(self):
        reconciled = result_row({
            "task_id": "reconciled",
            "spec_critic": {
                "decision": "approve",
                "audit_decision": "reject",
                "reconciliation_audit": {"decision": "approve"},
                "provisional_audit_rejection_overturned": True,
                "audit_rejection_overturned": True,
                "executable_boundary_checks": {
                    "status": "passed",
                    "batches_run": 3,
                    "required_approval_evidence_missing": 2,
                    "required_reject_evidence_missing": 1,
                },
            },
        })
        invalid = result_row({
            "task_id": "invalid",
            "spec_critic": {
                "decision": "reject",
                "executable_boundary_checks": {
                    "status": "not_executable",
                    "dafny_error_count": 2,
                    "dafny_errors": [
                        {
                            "error_type": "resolution",
                            "subtype": "unknown_identifier",
                            "message": "unknown name",
                        },
                        {
                            "error_type": "verification",
                            "subtype": "verification",
                            "message": "postcondition failed",
                        },
                    ],
                },
            },
        })

        summary = summarize([reconciled, invalid])

        self.assertEqual(
            reconciled["critic_reconciliation_audit_decision"], "approve"
        )
        self.assertTrue(
            reconciled["critic_provisional_audit_rejection_overturned"]
        )
        self.assertTrue(reconciled["critic_audit_rejection_overturned"])
        self.assertEqual(reconciled["critic_executable_batches_run"], 3)
        self.assertEqual(invalid["critic_executable_dafny_error_count"], 2)
        self.assertEqual(len(json.loads(invalid["critic_executable_dafny_errors"])), 2)
        self.assertEqual(
            invalid["critic_executable_dafny_error_types"],
            "resolution/unknown_identifier;verification",
        )
        self.assertEqual(
            summary["critic_reconciliation_audit_decisions"],
            {"approve": 1, "not_run": 1},
        )
        self.assertEqual(summary["critic_provisional_rejections_overturned"], 1)
        self.assertEqual(summary["critic_final_rejections_overturned"], 1)
        self.assertEqual(summary["critic_executable_batches_run"], 3)
        self.assertEqual(summary["critic_required_approval_evidence_missing"], 2)
        self.assertEqual(summary["critic_required_reject_evidence_missing"], 1)
        self.assertEqual(summary["critic_tasks_missing_required_approval_evidence"], 1)
        self.assertEqual(summary["critic_tasks_missing_required_reject_evidence"], 1)
        self.assertEqual(summary["critic_executable_specs_not_executable"], 1)
        self.assertEqual(summary["critic_executable_dafny_errors"], 2)
        self.assertEqual(
            summary["critic_executable_dafny_error_types"],
            {"resolution/unknown_identifier": 1, "verification": 1},
        )

    def test_old_results_default_new_critic_diagnostics_without_failure(self):
        row = result_row({"task_id": "legacy", "spec_critic": {"decision": "approve"}})
        summary = summarize([row])

        self.assertEqual(row["critic_reconciliation_audit_decision"], "")
        self.assertFalse(row["critic_provisional_audit_rejection_overturned"])
        self.assertFalse(row["critic_audit_rejection_overturned"])
        self.assertEqual(row["critic_executable_batches_run"], 0)
        self.assertEqual(row["critic_executable_dafny_errors"], "[]")
        self.assertEqual(
            summary["critic_reconciliation_audit_decisions"], {"not_run": 1}
        )
        self.assertEqual(summary["critic_executable_specs_not_executable"], 0)
        self.assertEqual(summary["critic_executable_dafny_errors"], 0)

    def test_critic_selective_risk_metrics_use_only_executed_holdouts(self):
        rows = [
            result_row({
                "task_id": "correct",
                "official_test_executed": True,
                "humaneval_passed": True,
                "spec_critic": {"decision": "approve"},
            }),
            result_row({
                "task_id": "wrong",
                "official_test_executed": True,
                "humaneval_passed": False,
                "spec_critic": {"decision": "approve"},
            }),
            result_row({
                "task_id": "withheld",
                "official_test_executed": False,
                "spec_critic": {"decision": "abstain"},
            }),
        ]

        summary = summarize(rows)

        self.assertEqual(summary["critic_approved"], 2)
        self.assertEqual(summary["critic_approved_evaluated"], 2)
        self.assertEqual(summary["critic_approved_correct"], 1)
        self.assertEqual(summary["critic_approved_wrong"], 1)
        self.assertEqual(summary["critic_approval_coverage"], "66.7%")
        self.assertEqual(summary["critic_accepted_precision"], "50.0%")


if __name__ == "__main__":
    unittest.main()
