import json

with open("D:/codegen-verify/data/HumanEval.jsonl") as f:
    for i, line in enumerate(f):
        if i >= 3:
            break
        d = json.loads(line)
        print(f"--- {d['task_id']} ---")
        print(f"entry_point: {d['entry_point']}")
        # 提取函数签名作为自然语言描述的基础
        prompt = d["prompt"]
        print(f"prompt[:300]:")
        print(prompt[:300])
        print()
