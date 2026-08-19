"""Compact analysis for the current spec-guided agent result schema."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import config


def load_results(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    raise ValueError("expected a result list or an object containing results")


def result_row(result: dict[str, Any]) -> dict[str, Any]:
    spec_artifact = result.get("spec_artifact") or {}
    critic = result.get("spec_critic") or spec_artifact.get("critic_report") or {}
    mutation = result.get("inloop_mutation_adequacy") or spec_artifact.get("mutation") or {}
    verification = result.get("verification_evidence") or {}
    structured = spec_artifact.get("structured") or {}
    requirements = result.get("requirement_analysis") or {}
    plan = result.get("plan") or {}
    diagnoses = result.get("diagnoses") or []
    traceability = result.get("traceability") or {}
    usage = result.get("llm_usage") or {}
    trace = result.get("research_trace") or []
    status = result.get("status") or (
        "passed" if result.get("passed") else
        "dafny_only" if result.get("dafny_verified") else
        result.get("critic_gate_status", "failed")
    )
    mutants_total = int(mutation.get("mutants_total", 0) or 0)
    mutants_verified = int(mutation.get("mutants_verified", 0) or 0)
    spec_strength = (
        round((mutants_total - mutants_verified) / mutants_total, 4)
        if mutants_total else 0.0
    )
    clauses = structured.get("clauses") or []
    clause_mapping = plan.get("clause_mapping") or {}
    return {
        "task_id": result.get("task_id", ""),
        "status": status,
        "passed": bool(result.get("passed")),
        "dafny_verified": bool(result.get("dafny_verified")),
        "humaneval_passed": bool(result.get("humaneval_passed")),
        "official_test_executed": bool(result.get("official_test_executed")),
        "spec_decision": spec_artifact.get("decision") or critic.get("decision", ""),
        "spec_version": int(spec_artifact.get("version", 0) or 0),
        "critic_confidence": float(critic.get("confidence", 0.0) or 0.0),
        "requirement_count": len(requirements.get("requirements") or structured.get("requirements") or []),
        "spec_clause_count": len(clauses),
        "plan_clause_coverage": round(len(set(clause_mapping) & {item.get("id") for item in clauses}) / len(clauses), 4) if clauses else 0.0,
        "mutants_total": mutants_total,
        "mutants_verified": mutants_verified,
        "spec_strength": spec_strength,
        "mutation_risk": mutation.get("mutation_adequacy_risk", ""),
        "spec_drift": bool((spec_artifact.get("drift_report") or {}).get("changed")),
        "reference_collapse": bool(verification.get("reference_collapse")),
        "last_failure_type": diagnoses[-1].get("category", "") if diagnoses else "",
        "trace_nodes": len(traceability.get("nodes") or []),
        "trace_links": len(traceability.get("links") or []),
        "llm_calls": int(usage.get("calls", 0) or 0),
        "llm_tokens": int(usage.get("total_tokens", 0) or 0),
        "llm_latency_seconds": float(usage.get("latency_seconds", 0.0) or 0.0),
        "verification_attempts": int(result.get("verification_attempts", 0) or 0),
        "repair_events": sum(1 for event in trace if event.get("stage") == "repair"),
        "time_seconds": float(result.get("time", 0.0) or 0.0),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    return {
        "total": total,
        "passed": sum(1 for row in rows if row["passed"]),
        "dafny_verified": sum(1 for row in rows if row["dafny_verified"]),
        "spec_approved": sum(1 for row in rows if row["spec_decision"] == "approve"),
        "spec_rejected": sum(1 for row in rows if row["spec_decision"] == "reject"),
        "spec_abstained": sum(1 for row in rows if row["spec_decision"] == "abstain"),
        "reference_collapses": sum(1 for row in rows if row["reference_collapse"]),
        "verification_attempts": sum(row["verification_attempts"] for row in rows),
        "repair_events": sum(row["repair_events"] for row in rows),
        "failure_type_counts": dict(Counter(row["last_failure_type"] for row in rows if row["last_failure_type"])),
        "average_spec_strength": round(
            sum(row["spec_strength"] for row in rows) / total, 4
        ) if total else 0.0,
        "wall_time_seconds": round(sum(row["time_seconds"] for row in rows), 3),
        "llm_calls": sum(row["llm_calls"] for row in rows),
        "llm_tokens": sum(row["llm_tokens"] for row in rows),
        "llm_latency_seconds": round(sum(row["llm_latency_seconds"] for row in rows), 3),
        "status_counts": dict(Counter(row["status"] for row in rows)),
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(result_row({}).keys())
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a spec-guided agent run")
    parser.add_argument("input", type=Path, help="benchmark_final.json")
    parser.add_argument("--csv", type=Path, default=config.LOG_DIR / "benchmark_results.csv")
    args = parser.parse_args()

    rows = [result_row(result) for result in load_results(args.input)]
    write_csv(rows, args.csv)
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
