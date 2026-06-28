"""查看 HumanEval 0 的生成代码和错误"""
import json

# 读中间结果 (第5个中间结果 = 跑完5题)
with open(r"D:\codegen-verify\logs\benchmark_final.json") as f:
    data = json.load(f)

print(f"总数: {data['total']}, 通过: {data['passed']}, 失败: {data['failed']}, 通过率: {data['pass_rate']}")
print()

for r in data["results"]:
    spec = r.get("spec", "")
    code = r.get("code", "")
    err = r.get("error", "")
    print(f"{'='*60}")
    print(f"问题: {r['task_id']} ({r.get('entry_point','')})")
    print(f"通过: {r.get('passed')}  轮次: {r.get('rounds','-')}  耗时: {r.get('time','-')}s")
    if err:
        print(f"错误: {err}")
    if spec:
        print(f"\n-- 规约 --\n{spec[:400]}")
    if code:
        print(f"\n-- 代码 ({len(code)} chars) --\n{code[:600]}")
    print()
