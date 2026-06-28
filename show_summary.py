"""
HumanEval 基准评测结果分析 (5 problems)
"""
import json

with open(r"D:\codegen-verify\logs\benchmark_final.json") as f:
    data = json.load(f)

print("=" * 70)
print("HumanEval 基准评测结果: 5 problems / 1 passed (20%)")
print("=" * 70)
print()

for r in data["results"]:
    pid = r["task_id"]
    entry = r["entry_point"]
    passed = r.get("passed", False)
    rounds = r.get("rounds", "-")
    time_s = r.get("time", "-")

    # 判断失败原因
    if passed:
        reason = "✅ 通过"
    else:
        code = r.get("code", "")
        spec = r.get("spec", "")
        if "invariant" in code and ("cannot" in code or "Error" in code):
            reason = "❌ 循环不变量不足"
        elif "seq<" in code and ("string" in code or "char" in code):
            reason = "❌ Dafny 字符串处理复杂"
        elif "requires" in spec and "forall" in spec:
            reason = "❌ 规约语法错误"
        else:
            reason = "❌ 其他"

    print(f"  {pid:20s} ({entry:25s})  {reason:30s}  轮次={rounds}  耗时={time_s}s")
