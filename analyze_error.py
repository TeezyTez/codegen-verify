"""分析 has_close_elements 的完整代码和所有错误"""
import sys
sys.path.insert(0, r"D:\codegen-verify\project")
from dafny_wrapper import DafnyVerifier

# 从中间结果中提取最终代码
import json
with open(r"D:\codegen-verify\logs\benchmark_final.json") as f:
    data = json.load(f)

# 找出问题0
for r in data["results"]:
    if r["task_id"] == "HumanEval/0":
        code = r["code"]
        spec = r["spec"]
        break

print("=" * 60)
print("生成的规约:")
print(spec)
print()
print("=" * 60)
print("生成的代码:")
print(code)
print()

# 用Dafny验证并展示详细错误
v = DafnyVerifier()
result = v.verify(code)
print("=" * 60)
print(f"验证结果: passed={result.passed}")
print(f"verified={result.verified_count} errors={result.error_count}")
print()
for i, e in enumerate(result.errors):
    print(f"--- 错误 {i+1} ---")
    print(f"  类型: {e.error_type}")
    print(f"  位置: L{e.location_line}:{e.location_col}")
    print(f"  信息: {e.message}")
    if e.related_spec:
        print(f"  关联: {e.related_spec}")
    print()
