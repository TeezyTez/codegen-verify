"""
HumanEval → Dafny 批量评测脚本
用法: python run_humaneval.py

对每个 HumanEval 问题：
1. 提取自然语言描述
2. 用 pipeline 生成 Dafny 规约 + 代码
3. Dafny 验证器检查
4. 统计结果
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
import time
import traceback
import argparse
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline import run_pipeline
from humaneval_tester import run_humaneval_test
from spec_adequacy import check_spec_adequacy
from research_trace import trace_event
from task_normalizer import (
    TaskNormalizationError,
    normalize_humaneval_problem,
    render_problem_description,
)
from experiment_manifest import create_run_directory, build_manifest, write_manifest
from llm_client import get_usage_metrics, reset_usage_metrics
from contract_utils import contract_fidelity_issues
import config


def load_humaneval():
    """加载 HumanEval 数据集"""
    problems = []
    with open(config.DATA_DIR / "HumanEval.jsonl", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            problems.append(d)
    print(f"[Data] 加载 {len(problems)} 个 HumanEval 问题")
    return problems


def extract_description(problem: dict) -> str:
    """兼容旧调用方：通过结构化 Task IR 渲染完整、无截断描述。"""
    return render_problem_description(normalize_humaneval_problem(problem))


def run_benchmark(
    problems,
    start=0,
    limit=5,
    *,
    evaluation_mode: str = "strict",
    repair_tests: dict[str, dict] | None = None,
    output_dir: Path | None = None,
):
    """批量运行评测"""
    results = []
    total = min(len(problems), start + limit)
    repair_tests = repair_tests or {}
    if evaluation_mode not in {"strict", "assisted"}:
        raise ValueError(f"Unknown evaluation mode: {evaluation_mode}")

    print(f"\n{'='*60}")
    print(f"开始评测: 共 {total - start} 个问题 (从 {start} 到 {total-1})")
    print(f"{'='*60}\n")

    for i in range(start, total):
        prob = problems[i]
        tid = prob["task_id"]
        entry = prob["entry_point"]
        try:
            task_ir = normalize_humaneval_problem(prob)
            desc = render_problem_description(task_ir)
        except TaskNormalizationError as exc:
            result = {
                "task_id": tid,
                "entry_point": entry,
                "passed": False,
                "unsupported": True,
                "error": f"task normalization failed: {exc}",
            }
            results.append(result)
            save_intermediate(results, i, output_dir=output_dir)
            continue

        if not task_ir.supported:
            result = {
                "task_id": tid,
                "entry_point": entry,
                "passed": False,
                "unsupported": True,
                "unsupported_reasons": list(task_ir.unsupported_reasons),
                "task_ir": task_ir.to_dict(),
            }
            print(f"\n[{i+1}/{total}] {tid} ({entry})")
            print(f"  UNSUPPORTED: {task_ir.unsupported_reasons}")
            results.append(result)
            save_intermediate(results, i, output_dir=output_dir)
            continue

        print(f"\n[{i+1}/{total}] {tid} ({entry})")
        print(f"  描述: {desc[:100]}...")
        print("-" * 40)

        try:
            start_time = time.time()
            dev_behavior_problem = None
            if evaluation_mode == "assisted":
                dev_behavior_problem = repair_tests.get(tid)
                if dev_behavior_problem:
                    dev_behavior_problem = {
                        "task_id": tid,
                        "entry_point": entry,
                        **dev_behavior_problem,
                    }
            final = run_pipeline(
                problem_id=tid,
                problem_desc=desc,
                max_rounds=config.MAX_REPAIR_ROUNDS,
                # Official HumanEval tests are never placed inside the search
                # loop. Assisted mode accepts only a separately supplied dev set.
                behavior_problem=dev_behavior_problem,
                entry_point=entry,
            )
            elapsed = time.time() - start_time

            dafny_verified = bool(final.get("dafny_verified", final.get("passed", False)))
            rounds = final.get("round", 0)
            code = final.get("code", "")

            dev_behavior_executed = bool(final.get("behavior_executed", False))
            dev_behavior_passed = bool(final.get("behavior_passed", False))
            dev_behavior_error = final.get("behavior_error") or None

            # Official tests are a final, one-shot holdout. Their diagnostics
            # are recorded only after the pipeline has stopped and are never
            # sent back to an agent.
            humaneval_passed = False
            humaneval_error = None
            official_test_executed = False
            if dafny_verified:
                print(f"  [HumanEval Holdout] 正在运行最终端到端测试...")
                official_test_executed = True
                try:
                    humaneval_passed, h_detail = run_humaneval_test(code, prob)
                    humaneval_error = h_detail.get("error")
                    mark = "PASS" if humaneval_passed else "FAIL"
                    print(f"  [HumanEval] {mark}")
                except Exception as eh:
                    print(f"  [HumanEval] 测试异常: {eh}")
                    humaneval_error = str(eh)

            # 最终通过 = Dafny 验证通过 && HumanEval 测试通过
            final_passed = dafny_verified and humaneval_passed
            spec = final.get("spec", "")
            spec_adequacy = check_spec_adequacy(
                spec=spec,
                problem_desc=desc,
                entry_point=entry,
                dafny_verified=dafny_verified,
                humaneval_passed=humaneval_passed,
            )
            research_trace = list(final.get("research_trace", []))
            if not any(event.get("stage") == "spec_adequacy_after_tests" for event in research_trace):
                research_trace.append(trace_event(
                    "spec_adequacy_after_tests",
                    rounds,
                    adequacy=spec_adequacy,
                    dafny_verified=dafny_verified,
                    humaneval_passed=humaneval_passed,
                ))

            result = {
                "task_id": tid,
                "entry_point": entry,
                "dafny_verified": dafny_verified,
                "humaneval_passed": humaneval_passed,
                "humaneval_error": humaneval_error,
                "official_test_executed": official_test_executed,
                "dev_behavior_executed": dev_behavior_executed,
                "dev_behavior_passed": dev_behavior_passed,
                "dev_behavior_error": dev_behavior_error,
                "evaluation_mode": evaluation_mode,
                "passed": final_passed,
                "rounds": rounds,
                "time": round(elapsed, 1),
                "code": code,
                "spec": spec,
                "spec_adequacy": spec_adequacy,
                "inloop_mutation_adequacy": final.get("mutation_adequacy", {}),
                "research_trace": research_trace,
                "final_attribution": final.get("last_attribution", {}),
                "verification_attempts": final.get("verification_attempts", 0),
                "contract_fidelity": not bool(contract_fidelity_issues(spec, code, entry)),
                "task_ir": task_ir.to_dict(),
            }

            status = "PASS" if final_passed else ("DAFNY_OK" if dafny_verified else "FAIL")
            print(f"  结果: {status}  rounds={rounds}  time={elapsed:.1f}s")

        except Exception as e:
            print(f"  错误: {e}")
            result = {
                "task_id": tid,
                "entry_point": entry,
                "passed": False,
                "error": str(e),
            }

        results.append(result)

        # 每轮保存中间结果
        save_intermediate(results, i, output_dir=output_dir)

    return results


def save_intermediate(results, idx, *, output_dir: Path | None = None):
    """保存中间结果"""
    out = {"total": len(results), "passed": sum(1 for r in results if r.get("passed")), "results": results}
    root = output_dir or config.LOG_DIR
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"benchmark_intermediate_{idx+1}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


def print_summary(results, *, output_dir: Path | None = None):
    """打印总结"""
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    unsupported = sum(1 for r in results if r.get("unsupported"))
    supported = total - unsupported
    dafny_passed = sum(1 for r in results if r.get("dafny_verified"))
    humaneval_passed = sum(1 for r in results if r.get("humaneval_passed"))
    total_rounds = sum(r.get("rounds", 0) for r in results if "rounds" in r)
    total_time = sum(r.get("time", 0) for r in results if "time" in r)

    print(f"\n{'='*60}")
    print(f" 评测总结 (端到端)")
    print(f"{'='*60}")
    print(f"  总数:              {total}")
    print(f"  Dafny 验证通过:    {dafny_passed} ({dafny_passed/total*100:.1f}%)" if total > 0 else "")
    print(f"  HumanEval 测试通过: {humaneval_passed} ({humaneval_passed/total*100:.1f}%)" if total > 0 else "")
    print(f"  端到端通过:        {passed} ({passed/total*100:.1f}%)")
    print(f"  失败:              {failed} ({failed/total*100:.1f}%)")
    print(f"  支持类型覆盖:       {supported}/{total} ({supported/total*100:.1f}%)" if total > 0 else "")
    print(f"  平均轮次:          {total_rounds/total:.2f}" if total > 0 else "")
    print(f"  总耗时:            {total_time:.1f}s ({total_time/60:.1f}min)")
    print()
    print(f"单题结果:")
    for r in results:
        hv = r.get("dafny_verified", False)
        ht = r.get("humaneval_passed", False)
        if hv and ht:
            mark = "OK"
        elif hv and not ht:
            mark = "V"  # verified only
        else:
            mark = "X"
        rd = r.get("rounds", "-")
        tm = r.get("time", "-")
        print(f"  {mark} {r['task_id']:20s}  rounds={rd}  time={tm}s")
    print(f"{'='*60}")

    # 保存最终结果
    summary = {
        "total": total,
        "dafny_verified": dafny_passed,
        "humaneval_passed": humaneval_passed,
        "passed": passed,
        "failed": failed,
        "supported": supported,
        "unsupported": unsupported,
        "coverage_rate": f"{supported/total*100:.1f}%" if total > 0 else "0%",
        "pass_rate": f"{passed/total*100:.1f}%" if total > 0 else "0%",
        "dafny_pass_rate": f"{dafny_passed/total*100:.1f}%" if total > 0 else "0%",
        "humaneval_pass_rate": f"{humaneval_passed/total*100:.1f}%" if total > 0 else "0%",
        "avg_rounds": round(total_rounds/total, 2) if total > 0 else 0,
        "total_time": round(total_time, 1),
        "results": results,
    }
    root = output_dir or config.LOG_DIR
    root.mkdir(parents=True, exist_ok=True)
    final_path = root / "benchmark_final.json"
    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"[Log] 最终结果已保存到 {final_path}")
    return summary


def load_repair_tests(path: Path | None) -> dict[str, dict]:
    """Load a separately curated dev-test set for assisted mode."""
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(text)
        if isinstance(data, dict) and "tests" not in data:
            return {
                task_id: ({"test": value} if isinstance(value, str) else value)
                for task_id, value in data.items()
            }
        rows = data.get("tests", []) if isinstance(data, dict) else data
    return {
        row["task_id"]: {key: value for key, value in row.items() if key != "task_id"}
        for row in rows
    }


def main():
    parser = argparse.ArgumentParser(description="HumanEval -> Dafny benchmark")
    parser.add_argument("--start", type=int, default=0, help="起始题目索引")
    parser.add_argument("--limit", type=int, default=5, help="评测题目数量")
    parser.add_argument("--rounds", type=int, default=None, help="最大修复轮次")
    parser.add_argument(
        "--mode",
        choices=("strict", "assisted"),
        default=config.EVALUATION_MODE,
        help="strict: official test only after search; assisted: use separate --repair-tests",
    )
    parser.add_argument(
        "--repair-tests",
        type=Path,
        default=None,
        help="Assisted mode only: separate JSON/JSONL dev tests; never the official HumanEval test file",
    )
    parser.add_argument("--output-dir", type=Path, default=None, help="Explicit unique run directory")
    args = parser.parse_args()

    if args.rounds is not None:
        config.MAX_REPAIR_ROUNDS = args.rounds

    if args.mode == "strict":
        # A strict benchmark can never be short-circuited by task-id templates.
        config.USE_TEMPLATE_FALLBACK = False
    if args.mode == "assisted" and args.repair_tests is None:
        parser.error("--mode assisted requires a separately curated --repair-tests file")

    problems = load_humaneval()
    selected = problems[args.start : min(len(problems), args.start + args.limit)]
    output_dir = args.output_dir or create_run_directory(
        f"humaneval_{args.mode}_{args.start}_{len(selected)}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(
        mode=args.mode,
        start=args.start,
        limit=args.limit,
        task_ids=[problem["task_id"] for problem in selected],
        data_path=config.DATA_DIR / "HumanEval.jsonl",
    )
    write_manifest(output_dir / "manifest.json", manifest)

    reset_usage_metrics()
    results = run_benchmark(
        problems,
        start=args.start,
        limit=args.limit,
        evaluation_mode=args.mode,
        repair_tests=load_repair_tests(args.repair_tests),
        output_dir=output_dir,
    )
    summary = print_summary(results, output_dir=output_dir)
    manifest["llm_usage"] = get_usage_metrics()
    manifest["summary"] = {key: value for key, value in summary.items() if key != "results"}
    manifest["completed"] = True
    write_manifest(output_dir / "manifest.json", manifest)
    print(f"[Run] 可复现实验目录: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
