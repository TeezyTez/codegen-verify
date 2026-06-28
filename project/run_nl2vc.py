"""
NL2VC-60 → Dafny Pipeline 评测脚本
基于 NL2VC-60 数据集（arXiv:2604.22601）

相较于 HumanEval，NL2VC-60 的优势：
1. 自带 ground-truth Dafny spec（已验证正确）
2. 自带 ground-truth Dafny code（已验证正确）
3. 提供 uDebug 测试套件（功能验证）
4. 可以评测 LLM 生成的规约和代码与 ground-truth 的吻合度

用法:
    python run_nl2vc.py                          # 默认跑全部 60 题
    python run_nl2vc.py --start 0 --limit 10     # 只跑前 10 题
    python run_nl2vc.py --list                   # 列出所有问题
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
import os
import time
import argparse
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline import run_pipeline
import config


# ============================================================
# 数据加载
# ============================================================

def load_nl2vc():
    """
    加载 NL2VC-60 数据集
    数据格式（JSONL 每行）:
    {
        "id": "uva_11934",              // UVa 问题编号
        "title": "Magic Formula",       // 问题标题
        "description": "...",           // 自然语言问题描述（详细）
        "short_desc": "...",            // 简短的函数级描述（喂给 Spec Agent）
        "problem_type": "math",         // 问题类型
        "ground_truth_spec": "...",     // Ground-truth Dafny 方法签名+规约
        "ground_truth_code": "...",     // Ground-truth 完整 Dafny 实现
        "ground_truth_entry": "MagicFormula",  // 入口方法名
        "udebug_tests": [               // uDebug 测试用例
            {"input": [1,2,3,4,5], "expected": 3},
            ...
        ],
        "difficulty": "easy",           // 难度: easy/medium/hard
        "tags": ["math", "counting"]
    }
    """
    path = config.DATA_DIR / "NL2VC-60.jsonl"
    if not path.exists():
        print(f"[Data] ❌ 数据集不存在: {path}")
        print("[Data] 请从以下地址下载后放入 data/ 目录:")
        print("  GitHub: (待作者公开)")
        print("  arXiv:  https://arxiv.org/abs/2604.22601")
        print("  联系作者: Md Erfan <merfan@crimson.ua.edu>")
        sys.exit(1)

    problems = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            problems.append(d)
    print(f"[Data] ✅ 加载 {len(problems)} 个 NL2VC-60 问题")
    return problems


def list_problems(problems):
    """列出数据集中的所有问题"""
    print(f"\n{'='*70}")
    print(f"NL2VC-60 数据集列表（共 {len(problems)} 题）")
    print(f"{'='*70}")
    for i, p in enumerate(problems):
        tags = ", ".join(p.get("tags", []))
        diff = p.get("difficulty", "?")
        print(f"  {i+1:3d}. [{diff}] {p['id']:20s} {p.get('title','?'):30s} ({tags})")
    print(f"{'='*70}")


# ============================================================
# 评测核心
# ============================================================

def evaluate_problem(problem: dict, max_rounds: int = 3):
    """
    对单个 NL2VC-60 问题运行完整评测
    返回包含多层指标的评测结果
    """
    prob_id = problem["id"]
    title = problem.get("title", "?")
    desc = problem["short_desc"]
    gt_spec = problem.get("ground_truth_spec", "")
    gt_code = problem.get("ground_truth_code", "")
    gt_entry = problem.get("ground_truth_entry", "")
    udebug_tests = problem.get("udebug_tests", [])

    print(f"\n{'='*60}")
    print(f"[{prob_id}] {title}")
    print(f"{'='*60}")

    # ---- Step 1: 运行 Pipeline（Spec Agent → Code Agent → Verify → Repair） ----
    try:
        start_time = time.time()
        final = run_pipeline(
            problem_id=prob_id,
            problem_desc=desc,
            max_rounds=max_rounds
        )
        elapsed = time.time() - start_time
    except Exception as e:
        print(f"  [Error] Pipeline 异常: {e}")
        return {
            "task_id": prob_id,
            "title": title,
            "error": str(e),
            "passed": False,
        }

    gen_spec = final.get("spec", "")
    gen_code = final.get("code", "")
    passed_dafny = final.get("passed", False)
    rounds = final.get("round", 0)
    history = final.get("history", [])

    # ---- Step 2: 规约正确性评估（核心指标！） ----
    spec_metrics = evaluate_spec_quality(gen_spec, gt_spec, prob_id)

    # ---- Step 3: 代码结构相似度评估 ----
    code_metrics = evaluate_code_similarity(gen_code, gt_code, gt_entry)

    # ---- Step 4: 功能正确性（如果 Dafny 验证通过且有 uDebug 测试） ----
    functional_metrics = {"test_passed": False, "tested": False}
    if passed_dafny and udebug_tests:
        functional_metrics = run_udebug_tests(gen_code, gt_entry, udebug_tests)
    elif passed_dafny:
        functional_metrics = {"tested": False, "note": "无 uDebug 测试用例"}

    # ---- 汇总 ----
    result = {
        "task_id": prob_id,
        "title": title,
        "dafny_verified": passed_dafny,
        "rounds": rounds,
        "time": round(elapsed, 1),

        # 规约质量
        "spec": spec_metrics,
        "generated_spec": gen_spec,

        # 代码质量
        "code": code_metrics,
        "generated_code": gen_code,

        # 功能正确性
        "functional": functional_metrics,

        # 整体通过 = Dafny 验证 + 功能测试通过
        "passed": passed_dafny and functional_metrics.get("test_passed", True),

        "ground_truth_entry": gt_entry,
    }

    print_individual_result(result)
    return result


# ============================================================
# 规约质量评估
# ============================================================

def evaluate_spec_quality(gen_spec: str, gt_spec: str, prob_id: str) -> dict:
    """
    评估生成的 Dafny 规约与 ground-truth 的吻合度。

    指标:
    1. exact_match: 精确字符串匹配
    2. method_match: 方法签名是否一致
    3. precondition_match: requires 子句相似度
    4. postcondition_match: ensures 子句相似度
    5. llm_judge_score: LLM 评判的语义相似度 (0-1)
    """
    import re

    metrics = {
        "exact_match": (gen_spec.strip() == gt_spec.strip()),
        "method_match": False,
        "has_requires": False,
        "has_ensures": False,
        "llm_judge_score": None,
    }

    # 提取方法名
    gt_method_match = re.search(r'method\s+(\w+)', gt_spec)
    gen_method_match = re.search(r'method\s+(\w+)', gen_spec)
    if gt_method_match and gen_method_match:
        metrics["method_match"] = (gt_method_match.group(1) == gen_method_match.group(1))

    # 检查规约结构
    metrics["has_requires"] = "requires" in gen_spec
    metrics["has_ensures"] = "ensures" in gen_spec

    # 用 LLM 做语义相似度评估（标注为 "非 gating" 的参考评估）
    try:
        from llm_client import spec_llm
        llm = spec_llm()
        judge_response = llm.chat(
            system="""你是一个 Dafny 规约评估专家。
比较两个 Dafny 规约的语义等价性。输出 JSON:
{
    "score": 0.0-1.0,
    "reason": "简要说明",
    "missing_conditions": ["缺失的约束"],
    "extra_unnecessary": ["多余的约束"]
}""",
            user=f"""Ground-truth 规约:
{gt_spec}

生成的规约:
{gen_spec}

请评估它们在语义上是否等价（能否互相替代）。"""
        )
        # 尝试解析 JSON
        try:
            if "```json" in judge_response:
                json_str = judge_response.split("```json")[1].split("```")[0].strip()
            elif "```" in judge_response:
                json_str = judge_response.split("```")[1].split("```")[0].strip()
            else:
                json_str = judge_response
            judge_data = json.loads(json_str)
            metrics["llm_judge_score"] = judge_data.get("score")
            metrics["llm_judge_reason"] = judge_data.get("reason", "")
            metrics["missing_conditions"] = judge_data.get("missing_conditions", [])
            metrics["extra_unnecessary"] = judge_data.get("extra_unnecessary", [])
        except:
            metrics["llm_judge_note"] = "无法解析 LLM judge 输出"
    except Exception as e:
        metrics["llm_judge_error"] = str(e)

    return metrics


# ============================================================
# 代码相似度评估
# ============================================================

def evaluate_code_similarity(gen_code: str, gt_code: str, entry: str) -> dict:
    """
    评估生成的 Dafny 代码与 ground-truth 的相似度。

    指标:
    1. exact_match: 精确匹配
    2. structural_match: 去除空白和注释后的结构匹配度
    3. num_loops: 循环数量对比
    4. num_invariants: 不变量数量对比
    """
    import re

    metrics = {
        "exact_match": (gen_code.strip() == gt_code.strip()),
    }

    # 去除空白/注释后的简化比较
    def normalize(s):
        s = re.sub(r'//.*', '', s)
        s = re.sub(r'/\*.*?\*/', '', s, flags=re.DOTALL)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    metrics["structural_match"] = (normalize(gen_code) == normalize(gt_code))

    # 循环数量
    gen_loops = len(re.findall(r'\bwhile\b', gen_code))
    gt_loops = len(re.findall(r'\bwhile\b', gt_code))
    metrics["num_loops"] = {"generated": gen_loops, "ground_truth": gt_loops}

    # invariant 数量
    gen_invariants = len(re.findall(r'\binvariant\b', gen_code))
    gt_invariants = len(re.findall(r'\binvariant\b', gt_code))
    metrics["num_invariants"] = {"generated": gen_invariants, "ground_truth": gt_invariants}

    # 方法存在性
    metrics["has_entry_method"] = entry in gen_code

    # 代码行数对比
    metrics["loc"] = {
        "generated": len(gen_code.strip().split('\n')),
        "ground_truth": len(gt_code.strip().split('\n')),
    }

    return metrics


# ============================================================
# uDebug 功能测试
# ============================================================

def run_udebug_tests(dafny_code: str, entry_point: str, test_cases: list) -> dict:
    """
    用 uDebug 测试用例验证 Dafny 代码的功能正确性。

    策略: 将 Dafny 编译为 Python，然后对每个测试用例运行输入/输出验证。
    """
    # 复用已有的 Dafny → Python 编译流程
    # 但 NL2VC-60 的测试用例是纯输入/输出格式，不需要 check() 函数
    try:
        from humaneval_tester import parse_method_signature, _to_dafny_single, _from_dafny_val
        import subprocess
        import tempfile

        clean_code = dafny_code
        if "```dafny" in clean_code:
            clean_code = clean_code.split("```dafny")[1].split("```")[0].strip()
        elif "```" in clean_code:
            clean_code = clean_code.split("```")[1].split("```")[0].strip()

        # 解析方法签名
        params, returns = parse_method_signature(clean_code, entry_point)
        if params is None:
            return {"test_passed": False, "tested": True, "error": "无法解析方法签名"}

        # 编译 Dafny → Python
        module_code = f"module NL2VCTestModule {{\n{clean_code}\n}}"
        tmp_dfy = tempfile.NamedTemporaryFile(mode='w', suffix='.dfy', delete=False, encoding='utf-8')
        tmp_dfy.write(module_code)
        tmp_dfy.close()
        outdir = tempfile.mkdtemp()

        r = subprocess.run(
            [config.DAFNY_PATH, 'translate', 'py', tmp_dfy.name,
             '--allow-warnings',
             '--output', os.path.join(outdir, 'out'),
             '--include-runtime'],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode != 0:
            os.unlink(tmp_dfy.name)
            return {
                "test_passed": False,
                "tested": True,
                "error": f"Dafny 编译失败: {(r.stderr or r.stdout)[:300]}",
                "passed": 0,
                "total": len(test_cases),
            }

        # 导入模块并执行测试
        py_dir = os.path.join(outdir, 'out-py')
        if py_dir not in sys.path:
            sys.path.insert(0, py_dir)

        if 'NL2VCTestModule' in sys.modules:
            del sys.modules['NL2VCTestModule']

        import _dafny as dafny_runtime
        mod = __import__('NL2VCTestModule')
        dafny_method_py = entry_point.replace("_", "__")
        dafny_fn = getattr(mod.default__, dafny_method_py)

        def run_one(*args):
            dafny_args = [_to_dafny_single(a, params[i][1]) for i, a in enumerate(args) if i < len(params)]
            result = dafny_fn(*dafny_args)
            if returns and len(returns) > 0:
                rname, rtype = returns[0]
                if len(returns) > 1:
                    return tuple(_from_dafny_val(result[i] if isinstance(result, tuple) else result, returns[i][1])
                                 for i in range(len(returns)))
                return _from_dafny_val(result, rtype)
            return result

        passed = 0
        failed_cases = []
        for tc in test_cases:
            try:
                inp = tc.get("input", [])
                expected = tc.get("expected")
                actual = run_one(*inp) if isinstance(inp, list) else run_one(inp)
                if actual == expected:
                    passed += 1
                else:
                    failed_cases.append({"input": inp, "expected": expected, "actual": actual})
            except Exception as e:
                failed_cases.append({"input": tc.get("input"), "error": str(e)})

        os.unlink(tmp_dfy.name)
        return {
            "test_passed": passed == len(test_cases),
            "tested": True,
            "passed": passed,
            "total": len(test_cases),
            "failed_cases": failed_cases[:5],  # 只保留前 5 个失败
        }

    except Exception as e:
        return {
            "test_passed": False,
            "tested": True,
            "error": f"uDebug 测试异常: {type(e).__name__}: {e}",
        }


# ============================================================
# 结果输出
# ============================================================

def print_individual_result(result: dict):
    """打印单个问题的结果"""
    pid = result["task_id"]
    print(f"\n  [{pid}] 结果汇总:")
    print(f"    Dafny 验证:  {'✅' if result.get('dafny_verified') else '❌'}")
    print(f"    轮次:        {result.get('rounds', '-')}")
    print(f"    耗时:        {result.get('time', '-')}s")

    # 规约质量
    spec = result.get("spec", {})
    print(f"    规约匹配:")
    print(f"      exact_match:  {'✅' if spec.get('exact_match') else '❌'}")
    if spec.get("llm_judge_score") is not None:
        print(f"      LLM 语义评分: {spec['llm_judge_score']:.2f}")
        if spec.get("missing_conditions"):
            print(f"      缺失条件: {', '.join(spec['missing_conditions'][:3])}")
        if spec.get("extra_unnecessary"):
            print(f"      多余条件: {', '.join(spec['extra_unnecessary'][:3])}")

    # 代码结构
    code = result.get("code", {})
    print(f"    代码结构:")
    print(f"      exact_match:  {'✅' if code.get('exact_match') else '❌'}")
    print(f"      loops:        {code.get('num_loops', {}).get('generated', '-')} vs {code.get('num_loops', {}).get('ground_truth', '-')}")
    print(f"      invariants:   {code.get('num_invariants', {}).get('generated', '-')} vs {code.get('num_invariants', {}).get('ground_truth', '-')}")

    # 功能测试
    func = result.get("functional", {})
    if func.get("tested"):
        print(f"    uDebug 测试:")
        passed = func.get("passed", 0)
        total = func.get("total", 0)
        mark = "✅" if func.get("test_passed") else "❌"
        print(f"      {mark} {passed}/{total} 通过")


def print_summary(results: list):
    """打印总结报告"""
    total = len(results)
    if total == 0:
        print("\n[Summary] 没有结果")
        return

    dafny_passed = sum(1 for r in results if r.get("dafny_verified"))
    func_tested = sum(1 for r in results if r.get("functional", {}).get("tested"))
    func_passed = sum(1 for r in results if r.get("functional", {}).get("test_passed"))
    spec_exact_match = sum(1 for r in results if r.get("spec", {}).get("exact_match"))
    code_exact_match = sum(1 for r in results if r.get("code", {}).get("exact_match"))

    llm_scores = [r.get("spec", {}).get("llm_judge_score") for r in results
                   if r.get("spec", {}).get("llm_judge_score") is not None]
    avg_llm_score = sum(llm_scores) / len(llm_scores) if llm_scores else None

    avg_rounds = sum(r.get("rounds", 0) for r in results if "rounds" in r) / max(total, 1)
    total_time = sum(r.get("time", 0) for r in results if "time" in r)

    print(f"\n{'='*60}")
    print(f"  NL2VC-60 评测总结")
    print(f"{'='*60}")
    print(f"  总问题数:              {total}")
    print(f"  Dafny 验证通过:        {dafny_passed}/{total} ({dafny_passed/total*100:.1f}%)")
    print(f"  uDebug 测试通过:       {func_passed}/{func_tested}" + (f" ({func_passed/func_tested*100:.1f}%)" if func_tested else ""))
    print(f"  规约 exact match:      {spec_exact_match}/{total} ({spec_exact_match/total*100:.1f}%)")
    print(f"  代码 exact match:      {code_exact_match}/{total} ({code_exact_match/total*100:.1f}%)")
    if avg_llm_score is not None:
        print(f"  规约平均语义分 (LLM):  {avg_llm_score:.3f}")
    print(f"  平均修复轮次:          {avg_rounds:.2f}")
    print(f"  总耗时:                {total_time:.1f}s ({total_time/60:.1f}min)")
    print(f"{'='*60}")

    # 详细列表
    print(f"\n单题详情:")
    print(f"  {'ID':22s}  {'Dafny':6s}  {'uDebug':6s}  {'Spec':6s}  {'Code':6s}  {'Rnds':5s}  {'Time':6s}")
    print(f"  {'-'*60}")
    for r in results:
        pid = r.get("task_id", "?")
        dv = "✅" if r.get("dafny_verified") else "❌"
        ft = r.get("functional", {})
        fp = "✅" if ft.get("test_passed") else ("⏭" if not ft.get("tested") else "❌")
        sem = "✅" if r.get("spec", {}).get("exact_match") else "❌"
        cem = "✅" if r.get("code", {}).get("exact_match") else "❌"
        rn = str(r.get("rounds", "-"))
        tm = str(r.get("time", "-"))
        print(f"  {pid:22s}  {dv:6s}  {fp:6s}  {sem:6s}  {cem:6s}  {rn:5s}  {tm:6s}s")
    print(f"{'='*60}")

    # 保存结果
    summary = {
        "total": total,
        "dafny_verified": dafny_passed,
        "dafny_verified_rate": f"{dafny_passed/total*100:.1f}%",
        "func_tested": func_tested,
        "func_passed": func_passed,
        "func_pass_rate": f"{func_passed/total*100:.1f}%",
        "spec_exact_match": spec_exact_match,
        "code_exact_match": code_exact_match,
        "avg_llm_spec_score": round(avg_llm_score, 3) if avg_llm_score else None,
        "avg_rounds": round(avg_rounds, 2),
        "total_time": round(total_time, 1),
        "results": results,
    }
    with open(config.LOG_DIR / "nl2vc_benchmark_final.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n[Log] 完整结果已保存到 logs/nl2vc_benchmark_final.json")


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="NL2VC-60 评测脚本")
    parser.add_argument("--start", type=int, default=0, help="起始问题索引")
    parser.add_argument("--limit", type=int, default=60, help="评测问题数量")
    parser.add_argument("--rounds", type=int, default=3, help="最大修复轮次")
    parser.add_argument("--list", action="store_true", help="列出所有问题")
    args = parser.parse_args()

    problems = load_nl2vc()

    if args.list:
        list_problems(problems)
        return

    # 过滤范围
    end = min(args.start + args.limit, len(problems))
    selected = problems[args.start:end]
    print(f"\n[Run] 评测 {len(selected)} 个问题 (索引 {args.start}-{end-1}), 最大修复轮次={args.rounds}\n")

    results = []
    for i, prob in enumerate(selected):
        print(f"\n--- [{i+1}/{len(selected)}] ---")
        result = evaluate_problem(prob, max_rounds=args.rounds)
        results.append(result)

        # 每轮保存中间结果
        with open(config.LOG_DIR / f"nl2vc_intermediate_{i+1}.json", "w", encoding="utf-8") as f:
            json.dump({"current": i+1, "result": result}, f, indent=2, ensure_ascii=False)

    print_summary(results)


if __name__ == "__main__":
    main()
