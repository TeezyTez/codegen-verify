"""Group-aware summaries. Replay is never used for research estimates."""
from collections import defaultdict
import json
from pathlib import Path
import random
from statistics import mean


def cluster_interval(rows, key="success"):
    groups = defaultdict(list)
    for row in rows:
        groups[row["source_project"]].append(float(row[key]))
    if len(groups) < 2:
        return None
    # Source-project macro average; repeats remain inside their project cluster.
    values = [mean(v) for v in groups.values()]
    rng = random.Random(0)
    samples = sorted(mean(rng.choices(values, k=len(values))) for _ in range(2000))
    return [samples[49], samples[1949]]


def summarize(root):
    root = Path(root)
    groups = defaultdict(list)
    seen = set()
    for path in sorted(root.rglob("result.json")):
        row = json.loads(path.read_text())
        if row.get("protocol") != "fixed_contract_repair_v1":
            continue
        identity = (row["task_id"], row["condition"], row["replicate"], row["model_kind"])
        if identity in seen:
            raise ValueError(f"duplicate run identity: {identity}")
        seen.add(identity)
        groups[(row["model_kind"], row["condition"], row["mode"], row["split"])].append(row)
    output = {"research": [], "scripted_diagnostics": [], "missing_planned_runs": []}
    planned = root / "jobs.json"
    if planned.exists():
        output["missing_planned_runs"] = [job for job in json.loads(planned.read_text())
            if not (root / job["directory"] / "result.json").exists()]
    for (kind, condition, mode, split), rows in groups.items():
        project_rows, failure_rows = defaultdict(list), defaultdict(list)
        for row in rows:
            project_rows[row["source_project"]].append(row)
            failure_rows[row["failure_type"]].append(row)
        costs = [r["usage"]["cost_usd"] for r in rows]
        summary = {"condition": condition, "mode": mode, "split": split,
            "runs": len(rows), "accepted": sum(r["success"] for r in rows),
            "observed_rate": mean(r["success"] for r in rows),
            "source_macro_rate": mean(mean(r["success"] for r in v) for v in project_rows.values()),
            "source_cluster_ci95": cluster_interval(rows) if kind == "live_model" else None,
            "by_source": {k: {"runs": len(v), "accepted": sum(r["success"] for r in v)} for k,v in project_rows.items()},
            "by_failure_type": {k: {"runs": len(v), "accepted": sum(r["success"] for r in v)} for k,v in failure_rows.items()},
            "verifier_calls": sum(r["usage"]["verifier_calls"] for r in rows),
            "input_tokens": sum(r["usage"]["input_tokens"] for r in rows) if kind == "live_model" else None,
            "output_tokens": sum(r["usage"]["output_tokens"] for r in rows) if kind == "live_model" else None,
            "unknown_usage_calls": sum(r["usage"]["unknown_usage_calls"] for r in rows),
            "cost_usd": sum(costs) if all(c is not None for c in costs) else None,
            "seconds": sum(r["seconds"] for r in rows),
            "regressions": sum(r["regressions"] for r in rows),
            "lost_observability": sum(r.get("lost_observability", 0) for r in rows),
            "boundary_rejections": sum(r["boundary_rejections"] for r in rows),
            "mean_changed_lines": mean(r["changed_lines"] for r in rows)}
        output["research" if kind == "live_model" else "scripted_diagnostics"].append(summary)
    output["interpretation"] = "Scripted diagnostics test infrastructure only. No pass@k or method advantage inferred. Missing jobs must be resolved before inference."
    output["paired_research"] = []
    for (kind, condition, mode, split), rows in groups.items():
        if kind != "live_model" or condition != "dependency":
            continue
        left = {(r["task_id"], r["replicate"]): r for r in rows}
        for baseline in ("independent", "linear", "generic_agent", "no_dependencies", "no_schedule"):
            right = {(r["task_id"], r["replicate"]): r for r in groups.get((kind, baseline, mode, split), [])}
            keys = left.keys() & right.keys()
            diffs = [{"source_project": left[k]["source_project"],
                      "success": int(left[k]["success"]) - int(right[k]["success"])} for k in keys]
            if diffs:
                source_diffs = defaultdict(list)
                for row in diffs:
                    source_diffs[row['source_project']].append(row['success'])
                output["paired_research"].append({"method": condition, "baseline": baseline,
                    "mode": mode, "split": split, "matched_runs": len(diffs),
                    "unmatched_runs": len(left.keys() ^ right.keys()),
                    "task_run_mean_difference": mean(r['success'] for r in diffs),
                    "source_macro_difference": mean(mean(v) for v in source_diffs.values()),
                    "source_macro_ci95": cluster_interval(diffs)})
    return output
