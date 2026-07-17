"""
Analyze benchmark outputs for research reporting.

Usage:
    python analyze_results.py
    python analyze_results.py --input ../logs/benchmark_final.json
    python analyze_results.py --csv ../logs/benchmark_results.csv
"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import config


REPAIR_ROUTES = {
    "proof_repair": "proof_repair",
    "repair": "code_repair",
    "alignment_repair": "alignment_repair",
    "spec_strengthening": "spec_strengthening",
}

REPAIR_METRIC_NAMES = (
    "calls",
    "evaluated",
    "direct_successes",
    "regressions",
    "non_improvements",
    "contract_drifts",
    "preverify_rejections",
    "unevaluated",
)


def pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0.0%"
    return f"{numerator / denominator * 100:.1f}%"


def load_results(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("results", [])
    if isinstance(data, list):
        return data
    raise ValueError(f"Unsupported result file format: {path}")


def result_row(result: dict[str, Any], mutation: dict[str, Any] | None = None) -> dict[str, Any]:
    adequacy = result.get("spec_adequacy") or {}
    attribution = result.get("final_attribution") or {}
    flags = adequacy.get("flags") or []
    trace = result.get("research_trace") or []
    mutation = mutation or result.get("inloop_mutation_adequacy") or {}
    critic = result.get("spec_critic") or {}
    reconciliation_audit = critic.get("reconciliation_audit") or {}
    executable_checks = critic.get("executable_boundary_checks") or {}
    executable_dafny_errors = executable_checks.get("dafny_errors") or []
    if not isinstance(executable_dafny_errors, list):
        executable_dafny_errors = []
    executable_dafny_error_labels = _dafny_error_labels(executable_dafny_errors)
    critic_decision = critic.get("decision", result.get("critic_gate_status", "not_run"))
    attribution_category = attribution.get("category", "")
    repair_target = attribution.get("repair_target", "")
    if not attribution_category and critic_decision in {"reject", "abstain"}:
        attribution_category = f"critic_{critic_decision}"
        repair_target = repair_target or "spec_critic_gate"
    trace_stages = [event.get("stage", "") for event in trace]
    repair_path = _repair_path(trace_stages)
    repair_metrics = repair_trace_metrics(trace)

    row = {
        "task_id": result.get("task_id", ""),
        "entry_point": result.get("entry_point", ""),
        "passed": bool(result.get("passed", False)),
        "dafny_verified": bool(result.get("dafny_verified", False)),
        "humaneval_passed": bool(result.get("humaneval_passed", False)),
        "official_test_executed": bool(result.get("official_test_executed", False)),
        "verified_but_test_failed": bool(result.get("dafny_verified", False)) and not bool(result.get("humaneval_passed", False)),
        "rounds": result.get("rounds", ""),
        "time": result.get("time", ""),
        "spec_score": adequacy.get("score", ""),
        "spec_level": adequacy.get("level", "missing"),
        "spec_flags": ";".join(flags),
        "attribution_category": attribution_category,
        "repair_target": repair_target,
        "repair_path": repair_path,
        "proof_repair_attempted": repair_metrics["proof_repair"]["calls"] > 0,
        "code_repair_attempted": repair_metrics["code_repair"]["calls"] > 0,
        "alignment_repair_attempted": repair_metrics["alignment_repair"]["calls"] > 0,
        "spec_strengthening_attempted": repair_metrics["spec_strengthening"]["calls"] > 0,
        "behavior_loop_executed": "behavior_test" in trace_stages,
        "mutants_total": mutation.get("mutants_total", ""),
        "mutants_verified": mutation.get("mutants_verified", ""),
        "suspicious_mutants": mutation.get("suspicious_mutants", ""),
        "mutation_adequacy_risk": mutation.get("mutation_adequacy_risk", ""),
        "critic_decision": critic_decision,
        "critic_audit_decision": critic.get("audit_decision", ""),
        "critic_reconciliation_audit_decision": reconciliation_audit.get("decision", ""),
        "critic_provisional_audit_rejection_overturned": bool(
            critic.get("provisional_audit_rejection_overturned", False)
        ),
        "critic_audit_rejection_overturned": bool(
            critic.get("audit_rejection_overturned", False)
        ),
        "critic_confidence": critic.get("confidence", ""),
        "critic_provider": critic.get("critic_provider", ""),
        "critic_model": critic.get("critic_model", ""),
        "critic_review_passes": critic.get("review_passes", ""),
        "critic_issue_count": len(critic.get("issues") or []),
        "critic_counterexample_count": len(critic.get("counterexamples") or []),
        "critic_audit_protocol_failure": bool(critic.get("audit_protocol_failure", False)),
        "critic_probe_generation_status": (critic.get("probe_generation") or {}).get("status", ""),
        "critic_executable_probe_status": executable_checks.get("status", ""),
        "critic_executable_batches_run": _safe_int(
            executable_checks.get("batches_run", 0)
        ),
        "critic_required_approval_evidence_missing": _safe_int(
            executable_checks.get("required_approval_evidence_missing", 0)
        ),
        "critic_required_reject_evidence_missing": _safe_int(
            executable_checks.get("required_reject_evidence_missing", 0)
        ),
        "critic_executable_spec_not_executable": (
            executable_checks.get("status") == "not_executable"
        ),
        "critic_executable_dafny_error_count": _safe_int(
            executable_checks.get(
                "dafny_error_count", len(executable_dafny_errors)
            )
        ),
        "critic_executable_dafny_error_types": ";".join(
            executable_dafny_error_labels
        ),
        "critic_executable_dafny_errors": json.dumps(
            executable_dafny_errors, ensure_ascii=False, separators=(",", ":")
        ),
        "critic_precondition_status": (critic.get("public_precondition_review") or {}).get("status", ""),
        "critic_unreviewed_requires_count": len(critic.get("unreviewed_public_requires") or []),
        "critic_signature_gate_status": (critic.get("signature_gate") or {}).get("status", ""),
        "critic_repair_rounds": result.get("critic_repair_rounds", 0),
        "trace_stages": ";".join(trace_stages),
        "humaneval_error": result.get("humaneval_error") or result.get("error") or "",
    }
    for route, metrics in repair_metrics.items():
        for metric, value in metrics.items():
            row[f"{route}_{metric}"] = value
    return row


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for r in rows if r["passed"])
    dafny_verified = sum(1 for r in rows if r["dafny_verified"])
    humaneval_passed = sum(1 for r in rows if r["humaneval_passed"])
    verified_but_test_failed = sum(1 for r in rows if r["verified_but_test_failed"])

    adequacy_levels = Counter(r["spec_level"] for r in rows)
    attribution_categories = Counter(r["attribution_category"] or "missing" for r in rows)
    repair_targets = Counter(r["repair_target"] or "missing" for r in rows)
    mutation_risks = Counter(r["mutation_adequacy_risk"] or "missing" for r in rows)
    repair_paths = Counter(r["repair_path"] or "none" for r in rows)
    critic_decisions = Counter(r["critic_decision"] or "not_run" for r in rows)
    critic_audit_decisions = Counter(
        r["critic_audit_decision"] or "not_run" for r in rows
    )
    critic_reconciliation_audit_decisions = Counter(
        r["critic_reconciliation_audit_decision"] or "not_run" for r in rows
    )
    critic_probe_statuses = Counter(
        r["critic_executable_probe_status"] or "not_run" for r in rows
    )
    critic_dafny_error_types: Counter[str] = Counter()
    for row in rows:
        for label in str(row["critic_executable_dafny_error_types"]).split(";"):
            if label:
                critic_dafny_error_types[label] += 1
    critic_approved = sum(r["critic_decision"] == "approve" for r in rows)
    critic_approved_evaluated = sum(
        r["critic_decision"] == "approve" and r["official_test_executed"]
        for r in rows
    )
    critic_approved_correct = sum(
        r["critic_decision"] == "approve" and r["humaneval_passed"]
        for r in rows
    )
    critic_approved_wrong = sum(
        r["critic_decision"] == "approve"
        and r["official_test_executed"]
        and not r["humaneval_passed"]
        for r in rows
    )
    suspicious_mutants = sum(_safe_int(r["suspicious_mutants"]) for r in rows)
    flag_counter: Counter[str] = Counter()
    for row in rows:
        for flag in str(row["spec_flags"]).split(";"):
            if flag:
                flag_counter[flag] += 1

    avg_rounds = _avg_number(r["rounds"] for r in rows)
    avg_spec_score = _avg_number(r["spec_score"] for r in rows)

    summary = {
        "total": total,
        "passed": passed,
        "dafny_verified": dafny_verified,
        "humaneval_passed": humaneval_passed,
        "verified_but_test_failed": verified_but_test_failed,
        "pass_rate": pct(passed, total),
        "dafny_verified_rate": pct(dafny_verified, total),
        "humaneval_pass_rate": pct(humaneval_passed, total),
        "verified_but_test_failed_rate": pct(verified_but_test_failed, total),
        "avg_rounds": avg_rounds,
        "avg_spec_score": avg_spec_score,
        "adequacy_levels": dict(adequacy_levels),
        "attribution_categories": dict(attribution_categories),
        "repair_targets": dict(repair_targets),
        "mutation_risks": dict(mutation_risks),
        "repair_paths": dict(repair_paths),
        "critic_decisions": dict(critic_decisions),
        "critic_audit_decisions": dict(critic_audit_decisions),
        "critic_reconciliation_audit_decisions": dict(
            critic_reconciliation_audit_decisions
        ),
        "critic_executable_probe_statuses": dict(critic_probe_statuses),
        "critic_provisional_rejections_overturned": sum(
            r["critic_provisional_audit_rejection_overturned"] for r in rows
        ),
        "critic_final_rejections_overturned": sum(
            r["critic_audit_rejection_overturned"] for r in rows
        ),
        "critic_executable_batches_run": sum(
            _safe_int(r["critic_executable_batches_run"]) for r in rows
        ),
        "critic_required_approval_evidence_missing": sum(
            _safe_int(r["critic_required_approval_evidence_missing"])
            for r in rows
        ),
        "critic_required_reject_evidence_missing": sum(
            _safe_int(r["critic_required_reject_evidence_missing"])
            for r in rows
        ),
        "critic_tasks_missing_required_approval_evidence": sum(
            _safe_int(r["critic_required_approval_evidence_missing"]) > 0
            for r in rows
        ),
        "critic_tasks_missing_required_reject_evidence": sum(
            _safe_int(r["critic_required_reject_evidence_missing"]) > 0
            for r in rows
        ),
        "critic_executable_specs_not_executable": sum(
            r["critic_executable_spec_not_executable"] for r in rows
        ),
        "critic_executable_dafny_errors": sum(
            _safe_int(r["critic_executable_dafny_error_count"])
            for r in rows
        ),
        "critic_executable_dafny_error_types": dict(critic_dafny_error_types),
        "critic_audit_protocol_failures": sum(
            r["critic_audit_protocol_failure"] for r in rows
        ),
        "critic_unreviewed_requires": sum(
            _safe_int(r["critic_unreviewed_requires_count"]) for r in rows
        ),
        "critic_approved": critic_approved,
        "critic_approved_evaluated": critic_approved_evaluated,
        "critic_approved_correct": critic_approved_correct,
        "critic_approved_wrong": critic_approved_wrong,
        "critic_approval_coverage": pct(critic_approved, total),
        "critic_accepted_precision": pct(
            critic_approved_correct, critic_approved_evaluated
        ),
        "critic_issues": sum(_safe_int(r["critic_issue_count"]) for r in rows),
        "critic_counterexamples": sum(
            _safe_int(r["critic_counterexample_count"]) for r in rows
        ),
        # These legacy keys now deliberately mean calls and immediate verifier
        # successes, not "tasks that eventually passed".  A task can contain
        # several repair calls, each with a different immediate outcome.
        "proof_repair_attempted": _sum_metric(rows, "proof_repair", "calls"),
        "proof_repair_success": _sum_metric(rows, "proof_repair", "direct_successes"),
        "code_repair_attempted": _sum_metric(rows, "code_repair", "calls"),
        "code_repair_success": _sum_metric(rows, "code_repair", "direct_successes"),
        "alignment_repair_attempted": _sum_metric(rows, "alignment_repair", "calls"),
        "alignment_repair_success": _sum_metric(rows, "alignment_repair", "direct_successes"),
        "spec_strengthening_attempted": _sum_metric(rows, "spec_strengthening", "calls"),
        "spec_strengthening_success": _sum_metric(rows, "spec_strengthening", "direct_successes"),
        "proof_repair_tasks_attempted": sum(1 for r in rows if r["proof_repair_attempted"]),
        "code_repair_tasks_attempted": sum(1 for r in rows if r["code_repair_attempted"]),
        "alignment_repair_tasks_attempted": sum(1 for r in rows if r["alignment_repair_attempted"]),
        "spec_strengthening_tasks_attempted": sum(1 for r in rows if r["spec_strengthening_attempted"]),
        "behavior_loop_executed": sum(1 for r in rows if r["behavior_loop_executed"]),
        "suspicious_mutants": suspicious_mutants,
        "top_spec_flags": dict(flag_counter.most_common(12)),
    }
    for route in REPAIR_ROUTES.values():
        for metric in REPAIR_METRIC_NAMES:
            summary[f"{route}_{metric}"] = _sum_metric(rows, route, metric)

    implementation_routes = ("proof_repair", "code_repair", "alignment_repair")
    for metric in REPAIR_METRIC_NAMES:
        summary[f"repair_{metric}_total"] = sum(
            summary[f"{route}_{metric}"] for route in implementation_routes
        )
    return summary


def repair_trace_metrics(trace: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Measure every repair call against its immediate verifier outcome.

    The old report treated a repair route as successful whenever the *task*
    eventually passed.  That credits an early failed repair when a later,
    unrelated repair succeeds.  Here each non-skipped repair event is one call.
    Only the first following ``verify`` event can be its direct outcome, and a
    candidate rejected before verification can never inherit the result of the
    unchanged code that the graph may verify next.

    New traces expose ``candidate_verification`` and rollback metadata.  Older
    traces are supported by comparing the next verification with the preceding
    verification, using error class and count as a conservative fallback.
    """
    metrics = {
        route: {name: 0 for name in REPAIR_METRIC_NAMES}
        for route in REPAIR_ROUTES.values()
    }

    for index, event in enumerate(trace):
        route = REPAIR_ROUTES.get(str(event.get("stage", "")))
        if route is None:
            continue
        action = str(event.get("action", "")).strip().lower()
        if action == "skipped":
            continue

        route_metrics = metrics[route]
        route_metrics["calls"] += 1

        contract_drift = _event_has_contract_drift(event)
        if contract_drift:
            route_metrics["contract_drifts"] += 1

        # Alignment performs an internal verification and records this action
        # only after observing the regression.  Its following graph-level
        # verify runs the restored old code, so it must not be called a success.
        if action == "regression_rolled_back":
            route_metrics["evaluated"] += 1
            route_metrics["regressions"] += 1
            continue

        if _rejected_before_verification(event, action):
            route_metrics["preverify_rejections"] += 1
            continue

        next_verify_index = _find_next_stage(trace, index, "verify")
        if next_verify_index is None:
            route_metrics["unevaluated"] += 1
            continue

        next_verify = trace[next_verify_index]
        candidate = next_verify.get("candidate_verification") or next_verify.get("verification")
        if not isinstance(candidate, dict):
            route_metrics["unevaluated"] += 1
            continue

        route_metrics["evaluated"] += 1
        if bool(candidate.get("passed", False)):
            route_metrics["direct_successes"] += 1

        if _snapshot_has_contract_error(candidate) and not contract_drift:
            route_metrics["contract_drifts"] += 1

        previous_verify_index = _find_previous_stage(trace, index, "verify")
        previous = None
        if previous_verify_index is not None:
            previous = trace[previous_verify_index].get("verification")
        comparison = _compare_verification_snapshots(candidate, previous)
        rollback_reason = str(next_verify.get("rollback_reason", "")).lower()
        explicitly_rejected = bool(next_verify.get("candidate_rejected", False))
        if rollback_reason == "verification_regression" or comparison < 0:
            route_metrics["regressions"] += 1
        elif explicitly_rejected or (comparison == 0 and not candidate.get("passed", False)):
            route_metrics["non_improvements"] += 1

    return metrics


def _sum_metric(rows: list[dict[str, Any]], route: str, metric: str) -> int:
    return sum(_safe_int(row.get(f"{route}_{metric}", 0)) for row in rows)


def _find_next_stage(trace: list[dict[str, Any]], index: int, stage: str) -> int | None:
    for candidate_index in range(index + 1, len(trace)):
        if trace[candidate_index].get("stage") == stage:
            return candidate_index
    return None


def _find_previous_stage(trace: list[dict[str, Any]], index: int, stage: str) -> int | None:
    for candidate_index in range(index - 1, -1, -1):
        if trace[candidate_index].get("stage") == stage:
            return candidate_index
    return None


def _rejected_before_verification(event: dict[str, Any], action: str) -> bool:
    rejected_actions = {
        "candidate_rejected",
        "contract_preservation_failed",
        "fallback_original",
        "fallback_to_code_repair",
    }
    return action in rejected_actions or bool(event.get("candidate_rejected", False))


def _event_has_contract_drift(event: dict[str, Any]) -> bool:
    if str(event.get("action", "")).lower() == "contract_preservation_failed":
        return True
    if event.get("missing_contract_clauses"):
        return True
    issue_fields = (
        event.get("deterministic_issues") or [],
        event.get("static_issues") or [],
    )
    return any(
        "contract" in str(issue).lower()
        for issues in issue_fields
        for issue in issues
    )


def _snapshot_has_contract_error(snapshot: dict[str, Any]) -> bool:
    return any(
        str(error.get("type", "")).lower() == "contract"
        for error in snapshot.get("errors", [])
        if isinstance(error, dict)
    )


def _compare_verification_snapshots(candidate: Any, previous: Any) -> int:
    """Return -1/0/1 when candidate is worse/equal/better than previous."""
    if not isinstance(candidate, dict) or not isinstance(previous, dict):
        return 0
    candidate_quality = _snapshot_quality(candidate)
    previous_quality = _snapshot_quality(previous)
    return (candidate_quality > previous_quality) - (candidate_quality < previous_quality)


def _snapshot_quality(snapshot: dict[str, Any]) -> tuple[int, int]:
    if bool(snapshot.get("passed", False)):
        return (3, 0)
    error_types = {
        str(error.get("type", "")).lower()
        for error in snapshot.get("errors", [])
        if isinstance(error, dict)
    }
    if "timeout" in error_types:
        rank = 0
    elif error_types & {"syntax", "type", "undefined", "assignment", "contract"}:
        rank = 1
    else:
        rank = 2
    return (rank, -_safe_int(snapshot.get("error_count", 0)))


def _dafny_error_labels(errors: list[Any]) -> list[str]:
    """Return stable aggregate labels while retaining raw diagnostics in CSV."""
    labels = []
    for error in errors:
        if not isinstance(error, dict):
            labels.append("unknown")
            continue
        error_type = str(error.get("error_type", "")).strip()
        subtype = str(error.get("subtype", "")).strip()
        if error_type and subtype and subtype != error_type:
            labels.append(f"{error_type}/{subtype}")
        else:
            labels.append(error_type or subtype or "unknown")
    return labels


def _safe_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _avg_number(values) -> float:
    nums = []
    for value in values:
        if isinstance(value, (int, float)):
            nums.append(float(value))
        elif isinstance(value, str) and value.strip():
            try:
                nums.append(float(value))
            except ValueError:
                pass
    if not nums:
        return 0.0
    return round(sum(nums) / len(nums), 2)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "task_id",
        "entry_point",
        "passed",
        "dafny_verified",
        "humaneval_passed",
        "official_test_executed",
        "verified_but_test_failed",
        "rounds",
        "time",
        "spec_score",
        "spec_level",
        "spec_flags",
        "attribution_category",
        "repair_target",
        "repair_path",
        "proof_repair_attempted",
        "code_repair_attempted",
        "alignment_repair_attempted",
        "spec_strengthening_attempted",
        "behavior_loop_executed",
        "mutants_total",
        "mutants_verified",
        "suspicious_mutants",
        "mutation_adequacy_risk",
        "critic_decision",
        "critic_audit_decision",
        "critic_reconciliation_audit_decision",
        "critic_provisional_audit_rejection_overturned",
        "critic_audit_rejection_overturned",
        "critic_confidence",
        "critic_provider",
        "critic_model",
        "critic_review_passes",
        "critic_issue_count",
        "critic_counterexample_count",
        "critic_audit_protocol_failure",
        "critic_probe_generation_status",
        "critic_executable_probe_status",
        "critic_executable_batches_run",
        "critic_required_approval_evidence_missing",
        "critic_required_reject_evidence_missing",
        "critic_executable_spec_not_executable",
        "critic_executable_dafny_error_count",
        "critic_executable_dafny_error_types",
        "critic_executable_dafny_errors",
        "critic_precondition_status",
        "critic_unreviewed_requires_count",
        "critic_signature_gate_status",
        "critic_repair_rounds",
        "trace_stages",
        "humaneval_error",
    ]
    for route in REPAIR_ROUTES.values():
        fieldnames.extend(f"{route}_{metric}" for metric in REPAIR_METRIC_NAMES)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(summary: dict[str, Any], csv_path: Path) -> None:
    print("\n=== Benchmark Summary ===")
    print(f"Total:                       {summary['total']}")
    print(f"End-to-end passed:           {summary['passed']} ({summary['pass_rate']})")
    print(f"Dafny verified:              {summary['dafny_verified']} ({summary['dafny_verified_rate']})")
    print(f"HumanEval passed:            {summary['humaneval_passed']} ({summary['humaneval_pass_rate']})")
    print(f"Verified but test failed:    {summary['verified_but_test_failed']} ({summary['verified_but_test_failed_rate']})")
    print(f"Average repair rounds:       {summary['avg_rounds']}")
    print(f"Average spec adequacy score: {summary['avg_spec_score']}")

    _print_counter("Spec adequacy levels", summary["adequacy_levels"])
    _print_counter("Failure attribution", summary["attribution_categories"])
    _print_counter("Repair targets", summary["repair_targets"])
    _print_counter("Repair paths", summary["repair_paths"])
    _print_counter("Mutation adequacy risks", summary["mutation_risks"])
    _print_counter("Independent Critic decisions", summary["critic_decisions"])
    _print_counter("Independent Critic audit decisions", summary["critic_audit_decisions"])
    _print_counter(
        "Independent Critic reconciliation decisions",
        summary["critic_reconciliation_audit_decisions"],
    )
    _print_counter(
        "Executable Critic probe outcomes",
        summary["critic_executable_probe_statuses"],
    )
    print(
        "Critic selective gate:"
        f"\n  approval coverage: {summary['critic_approval_coverage']}"
        f"\n  officially evaluated approvals: {summary['critic_approved_evaluated']}"
        f"\n  correct/wrong approvals: {summary['critic_approved_correct']}/"
        f"{summary['critic_approved_wrong']}"
        f"\n  accepted precision: {summary['critic_accepted_precision']}"
        f"\n  audit protocol failures: {summary['critic_audit_protocol_failures']}"
        f"\n  unresolved public requires: {summary['critic_unreviewed_requires']}"
    )
    print(
        "Critic rejection reconciliation:"
        f"\n  provisional overturns: "
        f"{summary['critic_provisional_rejections_overturned']}"
        f"\n  final certified overturns: "
        f"{summary['critic_final_rejections_overturned']}"
    )
    print(
        "Critic executable evidence:"
        f"\n  batches run: {summary['critic_executable_batches_run']}"
        f"\n  missing required approval evidence: "
        f"{summary['critic_required_approval_evidence_missing']}"
        f" ({summary['critic_tasks_missing_required_approval_evidence']} tasks)"
        f"\n  missing required reject evidence: "
        f"{summary['critic_required_reject_evidence_missing']}"
        f" ({summary['critic_tasks_missing_required_reject_evidence']} tasks)"
        f"\n  non-executable Dafny specs: "
        f"{summary['critic_executable_specs_not_executable']}"
        f"\n  Dafny diagnostics: {summary['critic_executable_dafny_errors']}"
    )
    _print_counter(
        "Critic executable Dafny diagnostic types",
        summary["critic_executable_dafny_error_types"],
    )
    print(
        "Critic evidence:"
        f" issues={summary['critic_issues']}"
        f" counterexamples={summary['critic_counterexamples']}"
    )
    print("\nRepair direct verifier outcomes (success/calls):")
    for route in REPAIR_ROUTES.values():
        print(
            f"  {route}: {summary[f'{route}_direct_successes']}/"
            f"{summary[f'{route}_calls']}"
        )
    print(
        "Repair audit totals (proof/code/alignment only):"
        f"\n  evaluated: {summary['repair_evaluated_total']}"
        f"\n  regressions: {summary['repair_regressions_total']}"
        f"\n  non_improvements: {summary['repair_non_improvements_total']}"
        f"\n  contract_drifts: {summary['repair_contract_drifts_total']}"
        f"\n  rejected_before_verify: {summary['repair_preverify_rejections_total']}"
        f"\n  unevaluated: {summary['repair_unevaluated_total']}"
        f"\n  behavior_loop_executed: {summary['behavior_loop_executed']}"
    )
    print(f"\nSuspicious mutants: {summary['suspicious_mutants']}")
    _print_counter("Top spec flags", summary["top_spec_flags"])

    print(f"\nCSV written to: {csv_path}")


def _print_counter(title: str, counter: dict[str, int]) -> None:
    print(f"\n{title}:")
    if not counter:
        print("  (none)")
        return
    for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {key}: {value}")


def _repair_path(trace_stages: list[str]) -> str:
    paths = []
    if "spec_strengthening" in trace_stages:
        paths.append("spec_strengthening")
    if "proof_repair" in trace_stages:
        paths.append("proof_repair")
    if "alignment_repair" in trace_stages:
        paths.append("alignment_repair")
    if "repair" in trace_stages:
        paths.append("code_repair")
    return "+".join(paths) if paths else "none"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Codegen Verify benchmark results")
    parser.add_argument(
        "--input",
        type=Path,
        default=config.LOG_DIR / "benchmark_final.json",
        help="Path to benchmark_final.json",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=config.LOG_DIR / "benchmark_results.csv",
        help="Where to write the flattened CSV table",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=config.LOG_DIR / "benchmark_summary.json",
        help="Where to write aggregate summary JSON",
    )
    parser.add_argument(
        "--mutation-json",
        type=Path,
        default=config.LOG_DIR / "mutation_adequacy.json",
        help="Optional mutation adequacy report to merge when present",
    )
    args = parser.parse_args()

    results = load_results(args.input)
    mutation_index = load_mutation_index(args.mutation_json)
    rows = [result_row(result, mutation_index.get(result.get("task_id", ""))) for result in results]
    summary = summarize(rows)

    write_csv(rows, args.csv)
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    with open(args.summary_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print_summary(summary, args.csv)


def load_mutation_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("results", data if isinstance(data, list) else [])
    return {row.get("task_id", ""): row for row in rows}


if __name__ == "__main__":
    main()
