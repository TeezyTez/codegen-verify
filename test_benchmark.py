"""
Quick test: Run HumanEval/0 only
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "project"))

from run_humaneval import load_humaneval, extract_description
from pipeline import run_pipeline

problems = load_humaneval()
prob = problems[0]

print(f"ID: {prob['task_id']}")
print(f"Entry: {prob['entry_point']}")
desc = extract_description(prob)
print(f"Desc: {desc[:150]}...")

result = run_pipeline(
    problem_id=prob["task_id"],
    problem_desc=desc,
    max_rounds=3
)

print(f"\n=== Result ===")
print(f"Passed: {result.get('passed')}")
print(f"Rounds: {result.get('round')}")
if result.get('passed'):
    print(f"Code:\n{result.get('code', '')[:500]}")
