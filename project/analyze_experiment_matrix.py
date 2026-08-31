"""Aggregate sharded experiment runs and compute paired condition comparisons."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


RUN_RE = re.compile(
    r"^(?P<condition>direct_1|direct_verify|spec_guided)_seed"
    r"(?P<seed>\d+)_shard(?P<shard>\d+)$"
)


def load_matrix(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        match = RUN_RE.fullmatch(run_dir.name)
        result_path = run_dir / "benchmark_final.json"
        if match is None or not result_path.exists():
            continue
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        for result in payload.get("results", []):
            usage = result.get("llm_usage") or {}
            rows.append({
                "condition": match.group("condition"),
                "seed": int(match.group("seed")),
                "shard": int(match.group("shard")),
                "task_id": result.get("task_id", ""),
                "passed": bool(result.get("passed")),
                "dafny_verified": bool(result.get("dafny_verified")),
                "verified_wrong": bool(result.get("verified_wrong")),
                "rounds": int(result.get("rounds", 0) or 0),
                "llm_calls": int(usage.get("calls", 0) or 0),
                "llm_tokens": int(usage.get("total_tokens", 0) or 0),
                "time_seconds": float(result.get("time", 0.0) or 0.0),
                "verifier_calls": int(result.get("verification_attempts", 0) or 0),
                "status": result.get("status", ""),
                "stop_reason": result.get("stop_reason", ""),
            })
    return rows


def _condition_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    passed = sum(row["passed"] for row in rows)
    tokens = sum(row["llm_tokens"] for row in rows)
    seconds = sum(row["time_seconds"] for row in rows)
    return {
        "task_runs": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "dafny_verified": sum(row["dafny_verified"] for row in rows),
        "verified_wrong": sum(row["verified_wrong"] for row in rows),
        "repair_success": sum(
            row["passed"] and row["rounds"] > 1 for row in rows
        ),
        "llm_calls": sum(row["llm_calls"] for row in rows),
        "llm_tokens": tokens,
        "verifier_calls": sum(row["verifier_calls"] for row in rows),
        "wall_seconds": round(seconds, 3),
        "average_tokens": round(tokens / total, 3) if total else 0.0,
        "average_seconds": round(seconds / total, 3) if total else 0.0,
    }


def _exact_mcnemar_p(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, k) for k in range(min(left_only, right_only) + 1))
    return round(min(1.0, 2.0 * tail / (2**discordant)), 6)


def summarize_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_seed: dict[str, dict[str, dict[str, int]]] = defaultdict(dict)
    for row in rows:
        grouped[row["condition"]].append(row)
    for condition, condition_rows in grouped.items():
        for seed in sorted({row["seed"] for row in condition_rows}):
            seed_rows = [row for row in condition_rows if row["seed"] == seed]
            by_seed[condition][str(seed)] = {
                "passed": sum(row["passed"] for row in seed_rows),
                "task_runs": len(seed_rows),
            }

    summaries = {
        condition: _condition_summary(condition_rows)
        for condition, condition_rows in sorted(grouped.items())
    }
    paired: dict[str, Any] = {}
    left = {
        (row["seed"], row["task_id"]): row
        for row in grouped.get("direct_1", [])
    }
    right = {
        (row["seed"], row["task_id"]): row
        for row in grouped.get("direct_verify", [])
    }
    keys = sorted(set(left) & set(right))
    if keys:
        both_pass = sum(left[key]["passed"] and right[key]["passed"] for key in keys)
        left_only = sum(left[key]["passed"] and not right[key]["passed"] for key in keys)
        right_only = sum(not left[key]["passed"] and right[key]["passed"] for key in keys)
        both_fail = len(keys) - both_pass - left_only - right_only
        paired = {
            "pairs": len(keys),
            "both_pass": both_pass,
            "direct_1_only": left_only,
            "direct_verify_only": right_only,
            "both_fail": both_fail,
            "net_pass_gain": right_only - left_only,
            "exact_mcnemar_p": _exact_mcnemar_p(left_only, right_only),
        }
        direct = summaries["direct_1"]
        verify = summaries["direct_verify"]
        paired["token_ratio"] = round(
            verify["average_tokens"] / direct["average_tokens"], 3
        ) if direct["average_tokens"] else None
        paired["time_ratio"] = round(
            verify["average_seconds"] / direct["average_seconds"], 3
        ) if direct["average_seconds"] else None

    return {
        "conditions": summaries,
        "by_seed": dict(by_seed),
        "direct_1_vs_direct_verify": paired,
    }


def write_rows(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a sharded experiment matrix")
    parser.add_argument("root", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()
    rows = load_matrix(args.root)
    summary = summarize_matrix(rows)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.csv:
        write_rows(rows, args.csv)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
