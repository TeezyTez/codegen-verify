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
    """从 HumanEval 问题中提取自然语言描述（适合 Dafny 生成）"""
    prompt = problem["prompt"]
    entry = problem["entry_point"]

    # 提取 docstring（在函数签名和 def 之间的注释）
    lines = prompt.split("\n")
    doc_lines = []
    in_doc = False
    for line in lines:
        if '"""' in line:
            in_doc = not in_doc
            continue
        if in_doc:
            doc_lines.append(line.strip())

    doc = " ".join(doc_lines).strip()

    # 提取函数签名
    sig_lines = [l for l in lines if l.startswith("def ")]
    sig = sig_lines[0] if sig_lines else f"def {entry}(...)"

    # 提取测试用例（从 docstring 里的 >>> 部分）
    tests = []
    in_test = False
    for line in lines:
        if line.strip().startswith(">>>"):
            in_test = True
        if in_test and line.strip():
            tests.append(line.strip())
        elif in_test and not line.strip():
            break

    # 组装成适合 Dafny 的描述
    desc = f"""请用 Dafny 语言实现以下函数。

函数说明：{doc[:200] if doc else "无说明"}

原函数签名（Python）：{sig}

实现要求：
1. 方法名：{entry}
2. 输入输出类型对应到 Dafny 类型（int → int, float → real, List → seq, bool → bool, str → string）
3. 确保后置条件能覆盖核心功能
4. 代码必须通过 Dafny 验证"""

    if tests:
        desc += f"\n\n测试示例：\n" + "\n".join(tests[:5])

    return desc


def run_benchmark(problems, start=0, limit=5):
    """批量运行评测"""
    results = []
    total = min(len(problems), start + limit)
    passed_count = 0

    print(f"\n{'='*60}")
    print(f"开始评测: 共 {total - start} 个问题 (从 {start} 到 {total-1})")
    print(f"{'='*60}\n")

    for i in range(start, total):
        prob = problems[i]
        tid = prob["task_id"]
        entry = prob["entry_point"]
        desc = extract_description(prob)

        print(f"\n[{i+1}/{total}] {tid} ({entry})")
        print(f"  描述: {desc[:100]}...")
        print("-" * 40)

        try:
            start_time = time.time()
            final = run_pipeline(
                problem_id=tid,
                problem_desc=desc,
                max_rounds=config.MAX_REPAIR_ROUNDS
            )
            elapsed = time.time() - start_time

            passed = final.get("passed", False)
            rounds = final.get("round", 0)
            code = final.get("code", "")

            # Dafny 验证通过后，额外用 HumanEval 原始测试用例验证
            humaneval_passed = False
            humaneval_error = None
            if passed:
                print(f"  [HumanEval] 正在运行端到端测试...")
                try:
                    humaneval_passed, h_detail = run_humaneval_test(code, prob)
                    humaneval_error = h_detail.get("error")
                    mark = "PASS" if humaneval_passed else "FAIL"
                    print(f"  [HumanEval] {mark}")
                except Exception as eh:
                    print(f"  [HumanEval] 测试异常: {eh}")
                    humaneval_error = str(eh)

            # 最终通过 = Dafny 验证通过 && HumanEval 测试通过
            final_passed = passed and humaneval_passed
            spec = final.get("spec", "")
            spec_adequacy = check_spec_adequacy(
                spec=spec,
                problem_desc=desc,
                entry_point=entry,
                dafny_verified=passed,
                humaneval_passed=humaneval_passed,
            )
            research_trace = list(final.get("research_trace", []))
            research_trace.append(trace_event(
                "spec_adequacy_after_tests",
                rounds,
                adequacy=spec_adequacy,
                dafny_verified=passed,
                humaneval_passed=humaneval_passed,
            ))

            result = {
                "task_id": tid,
                "entry_point": entry,
                "dafny_verified": passed,
                "humaneval_passed": humaneval_passed,
                "humaneval_error": humaneval_error,
                "passed": final_passed,
                "rounds": rounds,
                "time": round(elapsed, 1),
                "code": code,
                "spec": spec,
                "spec_adequacy": spec_adequacy,
                "research_trace": research_trace,
                "final_attribution": final.get("last_attribution", {}),
            }

            passed_count += 1 if final_passed else 0
            status = "PASS" if final_passed else ("DAFNY_OK" if passed else "FAIL")
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
        save_intermediate(results, i)

    return results


def save_intermediate(results, idx):
    """保存中间结果"""
    out = {"total": len(results), "passed": sum(1 for r in results if r.get("passed")), "results": results}
    path = config.LOG_DIR / f"benchmark_intermediate_{idx+1}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


def print_summary(results):
    """打印总结"""
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
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
        "pass_rate": f"{passed/total*100:.1f}%" if total > 0 else "0%",
        "dafny_pass_rate": f"{dafny_passed/total*100:.1f}%" if total > 0 else "0%",
        "humaneval_pass_rate": f"{humaneval_passed/total*100:.1f}%" if total > 0 else "0%",
        "avg_rounds": round(total_rounds/total, 2) if total > 0 else 0,
        "total_time": round(total_time, 1),
        "results": results,
    }
    with open(config.LOG_DIR / "benchmark_final.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"[Log] 最终结果已保存到 logs/benchmark_final.json")


def main():
    parser = argparse.ArgumentParser(description="HumanEval -> Dafny benchmark")
    parser.add_argument("--start", type=int, default=0, help="起始题目索引")
    parser.add_argument("--limit", type=int, default=5, help="评测题目数量")
    parser.add_argument("--rounds", type=int, default=None, help="最大修复轮次")
    args = parser.parse_args()

    if args.rounds is not None:
        config.MAX_REPAIR_ROUNDS = args.rounds

    problems = load_humaneval()
    results = run_benchmark(problems, start=args.start, limit=args.limit)
    print_summary(results)


if __name__ == "__main__":
    main()
