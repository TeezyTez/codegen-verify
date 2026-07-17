"""Replay the independent Spec Critic against frozen benchmark specifications.

This is a post-hoc evaluation utility: it never repairs a specification and it
never feeds official HumanEval outcomes back into the Critic.  When requested,
the official oracle is executed only after the gate decision has been frozen.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from contract_utils import build_direct_reference_program
from dafny_wrapper import DafnyVerifier
from humaneval_tester import run_humaneval_test
from llm_client import (
    critic_llm,
    get_usage_metrics,
    reset_usage_metrics,
    semantic_probe_llm,
)
from spec_critic import review_spec_with_llm
from task_normalizer import normalize_humaneval_problem, render_problem_description


def load_humaneval_by_id(path: Path | None = None) -> dict[str, dict[str, Any]]:
    data_path = path or (config.DATA_DIR / "HumanEval.jsonl")
    with data_path.open(encoding="utf-8") as handle:
        return {
            problem["task_id"]: problem
            for line in handle
            if (problem := json.loads(line))
        }


def _reuse_probe_suite(previous_report: dict[str, Any]) -> dict[str, Any] | None:
    generation = previous_report.get("probe_generation") or {}
    probes = previous_report.get("generated_probes") or []
    if generation.get("status") != "generated" or not probes:
        return None
    return {**generation, "probes": probes}


def evaluate_direct_reference(
    *,
    spec: str,
    entry_point: str,
    official_problem: dict[str, Any],
) -> dict[str, Any]:
    """Run the holdout only after the Critic decision, for post-hoc labels."""
    program = build_direct_reference_program(spec, entry_point)
    if not program:
        return {"status": "not_applicable", "passed": False}
    verification = DafnyVerifier().verify(program)
    if not verification.passed:
        return {
            "status": "not_executable",
            "passed": False,
            "dafny_error_count": verification.error_count,
        }
    passed, detail = run_humaneval_test(program, official_problem)
    return {
        "status": "passed" if passed else "failed",
        "passed": bool(passed),
        "error": detail.get("error"),
        "failing_input": detail.get("failing_input"),
        "expected": detail.get("expected"),
        "actual": detail.get("actual"),
    }


def replay(
    *,
    benchmark_path: Path,
    task_ids: list[str],
    reuse_probes: bool = False,
    with_official_oracle: bool = False,
) -> dict[str, Any]:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    frozen_by_id = {
        result["task_id"]: result
        for result in benchmark.get("results", [])
        if result.get("task_id")
    }
    missing = [task_id for task_id in task_ids if task_id not in frozen_by_id]
    if missing:
        raise ValueError("tasks missing from benchmark: " + ", ".join(missing))
    official_by_id = load_humaneval_by_id()

    reset_usage_metrics()
    results = []
    for task_id in task_ids:
        frozen = frozen_by_id[task_id]
        official_problem = official_by_id[task_id]
        task_ir = normalize_humaneval_problem(official_problem)
        problem_desc = render_problem_description(task_ir)
        previous_report = frozen.get("spec_critic") or {}
        probe_suite = _reuse_probe_suite(previous_report) if reuse_probes else None
        started = time.perf_counter()
        try:
            report = review_spec_with_llm(
                critic_llm(),
                problem_desc=problem_desc,
                spec=frozen.get("spec", ""),
                entry_point=frozen.get("entry_point", task_ir.entry_point),
                probe_llm=semantic_probe_llm(),
                task_ir=task_ir.to_dict(),
                probe_suite=probe_suite,
            )
            error = ""
        except Exception as exc:  # keep a multi-task replay inspectable
            report = {
                "decision": "abstain",
                "confidence": 0.0,
                "summary": "Critic replay raised an exception.",
                "error": f"{type(exc).__name__}: {exc}",
            }
            error = report["error"]

        result = {
            "task_id": task_id,
            "entry_point": frozen.get("entry_point", task_ir.entry_point),
            "old_decision": previous_report.get("decision", "not_run"),
            "new_decision": report.get("decision", "abstain"),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "reused_probe_suite": probe_suite is not None,
            "error": error,
            "report": report,
        }
        # This label is deliberately computed only after new_decision exists.
        if with_official_oracle:
            result["posthoc_official_oracle"] = evaluate_direct_reference(
                spec=frozen.get("spec", ""),
                entry_point=result["entry_point"],
                official_problem=official_problem,
            )
        results.append(result)
        oracle = result.get("posthoc_official_oracle", {})
        print(
            f"{task_id}: {result['old_decision']} -> {result['new_decision']} "
            f"oracle={oracle.get('status', 'not_run')} "
            f"time={result['elapsed_seconds']:.1f}s",
            flush=True,
        )

    approved = sum(item["new_decision"] == "approve" for item in results)
    correct = sum(
        item.get("posthoc_official_oracle", {}).get("passed") is True
        for item in results
    )
    accepted_wrong = sum(
        item["new_decision"] == "approve"
        and item.get("posthoc_official_oracle", {}).get("passed") is False
        for item in results
        if "posthoc_official_oracle" in item
    )
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_benchmark": str(benchmark_path.resolve()),
        "fresh_probes": not reuse_probes,
        "official_oracle_is_posthoc_only": bool(with_official_oracle),
        "critic_config": {
            "provider": config.CRITIC_PROVIDER,
            "model": config.CRITIC_MODEL,
            "probe_provider": config.CRITIC_PROBE_PROVIDER,
            "probe_model": config.CRITIC_PROBE_MODEL,
            "temperature": config.CRITIC_TEMPERATURE,
            "critic_max_tokens": config.CRITIC_MAX_TOKENS,
            "probe_max_tokens": config.CRITIC_PROBE_MAX_TOKENS,
            "critic_parse_retries": config.MAX_CRITIC_PARSE_RETRIES,
            "probe_parse_retries": config.MAX_CRITIC_PROBE_PARSE_RETRIES,
            "review_passes": config.CRITIC_REVIEW_PASSES,
            "min_probes": config.MIN_CRITIC_PROBES,
            "max_probes": config.MAX_CRITIC_PROBES,
            "max_executed_probes": config.MAX_EXECUTED_CRITIC_PROBES,
            "require_precondition_evidence": (
                config.CRITIC_REQUIRE_PRECONDITION_EVIDENCE
            ),
        },
        "task_ids": task_ids,
        "summary": {
            "total": len(results),
            "approved": approved,
            "rejected": sum(item["new_decision"] == "reject" for item in results),
            "abstained": sum(item["new_decision"] == "abstain" for item in results),
            "oracle_correct": correct if with_official_oracle else None,
            "accepted_wrong": accepted_wrong if with_official_oracle else None,
        },
        "usage": get_usage_metrics(),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--task-ids", nargs="+", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--reuse-probes",
        action="store_true",
        help="Reuse the source run's frozen NL probe suite instead of generating a fresh one.",
    )
    parser.add_argument(
        "--with-official-oracle",
        action="store_true",
        help="Run official tests post-hoc after every Critic decision.",
    )
    args = parser.parse_args()
    payload = replay(
        benchmark_path=args.input,
        task_ids=args.task_ids,
        reuse_probes=args.reuse_probes,
        with_official_oracle=args.with_official_oracle,
    )
    output = args.output or args.input.with_name(
        "critic_replay_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False), flush=True)
    print(f"Saved: {output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
