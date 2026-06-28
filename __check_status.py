import json

print("=== benchmark_final.json ===")
d = json.load(open(r'D:\codegen-verify\logs\benchmark_final.json'))
print(f"total={d.get('total')}, passed={d.get('passed')}, failed={d.get('failed')}")
print(f"model={d.get('model')}, max_rounds={d.get('max_rounds')}")
print(f"dataset={d.get('dataset')}, timestamp={d.get('timestamp')}")
print()
results = d.get('results', [])
for r in results:
    task = r.get('task_id','?')
    status = r.get('status','?')
    rounds = r.get('repair_rounds','?')
    print(f"  {task}: {status} (repair_rounds={rounds})")
    if 'errors' in r:
        for e in r['errors']:
            print(f"    错误: {e}")

print()
print("=== benchmark_intermediate 演化 ===")
for fn in ['benchmark_intermediate_1','benchmark_intermediate_2','benchmark_intermediate_3','benchmark_intermediate_4','benchmark_intermediate_5']:
    d2 = json.load(open(rf'D:\codegen-verify\logs\{fn}.json'))
    print(f"  {fn}: total={d2.get('total')}, passed={d2.get('passed')}, failed={d2.get('failed')}")

print()
print("=== result_test_max.json ===")
try:
    rmax = json.load(open(r'D:\codegen-verify\logs\result_test_max.json'))
    print(json.dumps(rmax, indent=2, ensure_ascii=False))
except:
    print("(无法读取)")
