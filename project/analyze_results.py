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
    mutation = mutation or {}
    trace_stages = [event.get("stage", "") for event in trace]
    repair_path = _repair_path(trace_stages)

    return {
        "task_id": result.get("task_id", ""),
        "entry_point": result.get("entry_point", ""),
        "passed": bool(result.get("passed", False)),
        "dafny_verified": bool(result.get("dafny_verified", False)),
        "humaneval_passed": bool(result.get("humaneval_passed", False)),
        "verified_but_test_failed": bool(result.get("dafny_verified", False)) and not bool(result.get("humaneval_passed", False)),
        "rounds": result.get("rounds", ""),
        "time": result.get("time", ""),
        "spec_score": adequacy.get("score", ""),
        "spec_level": adequacy.get("level", "missing"),
        "spec_flags": ";".join(flags),
        "attribution_category": attribution.get("category", ""),
        "repair_target": attribution.get("repair_target", ""),
        "repair_path": repair_path,
        "proof_repair_attempted": "proof_repair" in trace_stages,
        "alignment_repair_attempted": "alignment_repair" in trace_stages,
        "spec_strengthening_attempted": "spec_strengthening" in trace_stages,
        "behavior_loop_executed": "behavior_test" in trace_stages,
        "mutants_total": mutation.get("mutants_total", ""),
        "mutants_verified": mutation.get("mutants_verified", ""),
        "suspicious_mutants": mutation.get("suspicious_mutants", ""),
        "mutation_adequacy_risk": mutation.get("mutation_adequacy_risk", ""),
        "trace_stages": ";".join(trace_stages),
        "humaneval_error": result.get("humaneval_error") or result.get("error") or "",
    }


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
    suspicious_mutants = sum(_safe_int(r["suspicious_mutants"]) for r in rows)
    flag_counter: Counter[str] = Counter()
    for row in rows:
        for flag in str(row["spec_flags"]).split(";"):
            if flag:
                flag_counter[flag] += 1

    avg_rounds = _avg_number(r["rounds"] for r in rows)
    avg_spec_score = _avg_number(r["spec_score"] for r in rows)

    return {
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
        "proof_repair_attempted": sum(1 for r in rows if r["proof_repair_attempted"]),
        "proof_repair_success": sum(1 for r in rows if r["proof_repair_attempted"] and r["passed"]),
        "alignment_repair_attempted": sum(1 for r in rows if r["alignment_repair_attempted"]),
        "alignment_repair_success": sum(1 for r in rows if r["alignment_repair_attempted"] and r["passed"]),
        "spec_strengthening_attempted": sum(1 for r in rows if r["spec_strengthening_attempted"]),
        "spec_strengthening_success": sum(1 for r in rows if r["spec_strengthening_attempted"] and r["passed"]),
        "behavior_loop_executed": sum(1 for r in rows if r["behavior_loop_executed"]),
        "suspicious_mutants": suspicious_mutants,
        "top_spec_flags": dict(flag_counter.most_common(12)),
    }


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
        "alignment_repair_attempted",
        "spec_strengthening_attempted",
        "behavior_loop_executed",
        "mutants_total",
        "mutants_verified",
        "suspicious_mutants",
        "mutation_adequacy_risk",
        "trace_stages",
        "humaneval_error",
    ]
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
    print(
        "\nRepair route success:"
        f"\n  proof_repair: {summary['proof_repair_success']}/{summary['proof_repair_attempted']}"
        f"\n  alignment_repair: {summary['alignment_repair_success']}/{summary['alignment_repair_attempted']}"
        f"\n  spec_strengthening: {summary['spec_strengthening_success']}/{summary['spec_strengthening_attempted']}"
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
