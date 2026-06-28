import json

d = json.load(open(r'D:\codegen-verify\logs\benchmark_final.json'))
print("Total: %d, Passed: %d, Failed: %d" % (d["total"], d["passed"], d["failed"]))
print("Pass rate: %s, Avg rounds: %s, Total time: %ds" % (d["pass_rate"], d["avg_rounds"], d["total_time"]))
print()

for r in d["results"]:
    task = r["task_id"]
    passed = r["passed"]
    rnds = r.get("rounds")
    tm = r.get("time", 0)
    print("%s: passed=%s, rounds=%s, time=%.1fs" % (task, passed, rnds, tm))
