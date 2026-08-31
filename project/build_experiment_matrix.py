"""Generate deterministic benchmark jobs without starting paid model calls."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable


DEFAULT_BUDGET = {
    "max_model_calls": 12,
    "max_total_tokens": 50000,
    "max_verifier_calls": 30,
    "max_wall_seconds": 900,
    "max_candidates": 8,
}


def build_jobs(
    *,
    conditions: Iterable[str],
    seeds: Iterable[int],
    total_tasks: int,
    shard_size: int,
    rounds: int,
    mode: str = "strict",
    budget: dict[str, int | float] | None = None,
    search_width: int = 2,
    supported_only: bool = False,
) -> list[dict[str, Any]]:
    if total_tasks <= 0 or shard_size <= 0:
        raise ValueError("total_tasks and shard_size must be positive")
    jobs: list[dict[str, Any]] = []
    limits = {**DEFAULT_BUDGET, **(budget or {})}
    shard_count = math.ceil(total_tasks / shard_size)
    for condition in conditions:
        if condition not in {"spec_guided", "direct_1", "direct_verify"}:
            raise ValueError(f"unknown condition: {condition}")
        for seed in seeds:
            for shard in range(shard_count):
                start = shard * shard_size
                limit = min(shard_size, total_tasks - start)
                job_id = f"{condition}_seed{seed:02d}_shard{shard:03d}"
                command = [
                    "python", "project/run_humaneval.py",
                    "--condition", condition,
                    "--mode", mode,
                    "--start", str(start),
                    "--limit", str(limit),
                    "--rounds", str(0 if condition == "direct_1" else rounds),
                    "--seed", str(seed),
                    "--replicate-id", str(seed),
                    "--max-model-calls", str(limits["max_model_calls"]),
                    "--max-total-tokens", str(limits["max_total_tokens"]),
                    "--max-verifier-calls", str(limits["max_verifier_calls"]),
                    "--max-wall-seconds", str(limits["max_wall_seconds"]),
                    "--max-candidates", str(limits["max_candidates"]),
                    "--search-width", str(search_width),
                ]
                if supported_only:
                    command.append("--supported-only")
                jobs.append({
                    "job_id": job_id,
                    "condition_id": condition,
                    "seed": seed,
                    "replicate_id": seed,
                    "start": start,
                    "limit": limit,
                    "rounds": 0 if condition == "direct_1" else rounds,
                    "mode": mode,
                    "budget": dict(limits),
                    "search_width": search_width,
                    "supported_only": supported_only,
                    "command": command,
                })
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a reproducible experiment job matrix")
    parser.add_argument("--conditions", nargs="+", default=["direct_1", "direct_verify", "spec_guided"])
    parser.add_argument("--seeds", nargs="+", type=int, default=list(range(10)))
    parser.add_argument("--total-tasks", type=int, default=164)
    parser.add_argument("--shard-size", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--mode", choices=("strict", "assisted"), default="strict")
    parser.add_argument("--max-model-calls", type=int, default=12)
    parser.add_argument("--max-total-tokens", type=int, default=50000)
    parser.add_argument("--max-verifier-calls", type=int, default=30)
    parser.add_argument("--max-wall-seconds", type=float, default=900)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--search-width", type=int, default=2)
    parser.add_argument("--supported-only", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("experiments/generated_jobs.json"))
    args = parser.parse_args()

    jobs = build_jobs(
        conditions=args.conditions,
        seeds=args.seeds,
        total_tasks=args.total_tasks,
        shard_size=args.shard_size,
        rounds=args.rounds,
        mode=args.mode,
        budget={
            "max_model_calls": args.max_model_calls,
            "max_total_tokens": args.max_total_tokens,
            "max_verifier_calls": args.max_verifier_calls,
            "max_wall_seconds": args.max_wall_seconds,
            "max_candidates": args.max_candidates,
        },
        search_width=args.search_width,
        supported_only=args.supported_only,
    )
    payload = {
        "schema_version": 1,
        "official_test_feedback_allowed": False,
        "job_count": len(jobs),
        "jobs": jobs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(jobs)} jobs to {args.output}")


if __name__ == "__main__":
    main()
