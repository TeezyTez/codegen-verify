import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from analyze_experiment_matrix import load_matrix, summarize_matrix


def _write_run(root, name, results):
    run = root / name
    run.mkdir()
    (run / "benchmark_final.json").write_text(
        json.dumps({"results": results}), encoding="utf-8"
    )


def test_matrix_summary_pairs_conditions_and_reports_cost(tmp_path):
    common = {"llm_usage": {"calls": 1, "total_tokens": 10}, "time": 1.0}
    _write_run(tmp_path, "direct_1_seed00_shard000", [
        {**common, "task_id": "t1", "passed": True, "dafny_verified": True, "rounds": 1},
        {**common, "task_id": "t2", "passed": False, "rounds": 1},
    ])
    _write_run(tmp_path, "direct_verify_seed00_shard000", [
        {**common, "task_id": "t1", "passed": False, "rounds": 4},
        {
            **common,
            "task_id": "t2",
            "passed": True,
            "dafny_verified": True,
            "rounds": 2,
            "llm_usage": {"calls": 2, "total_tokens": 30},
            "time": 3.0,
            "verification_attempts": 2,
        },
    ])

    summary = summarize_matrix(load_matrix(tmp_path))

    assert summary["conditions"]["direct_1"]["passed"] == 1
    assert summary["conditions"]["direct_verify"]["repair_success"] == 1
    assert summary["direct_1_vs_direct_verify"]["direct_1_only"] == 1
    assert summary["direct_1_vs_direct_verify"]["direct_verify_only"] == 1
    assert summary["direct_1_vs_direct_verify"]["exact_mcnemar_p"] == 1.0
