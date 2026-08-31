"""Normalize heterogeneous specification checks into one evidence grid."""

from __future__ import annotations

from typing import Any, Mapping

from artifacts import SpecHarnessEvidence


def build_spec_harness(
    *,
    decision: str,
    structural_issues: tuple[str, ...] | list[str] = (),
    traceability_issues: tuple[str, ...] | list[str] = (),
    adequacy: Mapping[str, Any] | None = None,
    mutation: Mapping[str, Any] | None = None,
    critic_report: Mapping[str, Any] | None = None,
) -> SpecHarnessEvidence:
    """Build a conservative grid; unavailable evidence remains explicitly unknown."""

    adequacy = dict(adequacy or {})
    mutation = dict(mutation or {})
    critic = dict(critic_report or {})
    executable = dict(critic.get("executable_boundary_checks") or {})
    preconditions = dict(critic.get("public_precondition_review") or {})

    mutants_total = int(mutation.get("mutants_total", 0) or 0)
    mutants_verified = int(mutation.get("mutants_verified", 0) or 0)
    checks_scheduled = int(executable.get("checks_scheduled", 0) or 0)
    checks_run = int(executable.get("checks_run", 0) or 0)
    executable_status = str(executable.get("status") or "not_run")

    cells: dict[str, dict[str, Any]] = {
        "well_formed": {
            "status": "passed" if not structural_issues else "failed",
            "issues": list(structural_issues),
        },
        "traceability": {
            "status": "passed" if not traceability_issues else "unknown",
            "issues": list(traceability_issues),
        },
        "precondition_correctness": {
            "status": preconditions.get("status", "unknown"),
            "unresolved": list(preconditions.get("unresolved_clauses") or []),
        },
        "positive_examples": {
            "status": executable_status,
            "scheduled": checks_scheduled,
            "executed": checks_run,
        },
        "negative_implementations": {
            "status": (
                "passed" if mutants_total > 0 and mutants_verified == 0
                else "failed" if mutants_verified > 0
                else "unknown"
            ),
            "total": mutants_total,
            "rejected": max(0, mutants_total - mutants_verified),
            "survived": mutants_verified,
        },
        "postcondition_correctness": {
            "status": executable_status,
            "source": "task-grounded executable probes" if executable else "unavailable",
        },
        "postcondition_completeness": {
            "status": (
                "passed" if mutants_total > 0 and mutants_verified == 0
                else "failed" if mutants_verified > 0
                else "unknown"
            ),
            "mutation_kill_rate": (
                round((mutants_total - mutants_verified) / mutants_total, 4)
                if mutants_total else None
            ),
        },
        "equivalence_or_uniqueness": {"status": "unknown", "reason": "not measured"},
        "metamorphic_consistency": {"status": "unknown", "reason": "not measured"},
    }
    unknown = tuple(name for name, cell in cells.items() if cell.get("status") in {"unknown", "not_run"})
    failed = tuple(name for name, cell in cells.items() if cell.get("status") in {"failed", "execution_error", "not_executable"})
    return SpecHarnessEvidence(
        decision=decision,
        cells=cells,
        missing_evidence=unknown,
        failed_cells=failed,
        risk=("high" if failed else "medium" if unknown else "low"),
    )
