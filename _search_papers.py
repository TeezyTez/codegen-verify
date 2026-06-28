import os, re

txts_dir = r'C:\Users\Tez\.openclaw\workspace\开题\Pappers\texts'
keywords = ['dougherty', 'severa', 'baksys', 'erfan', 'nl2vc', 'councilman']

for f in sorted(os.listdir(txts_dir)):
    if not any(k in f.lower() for k in keywords):
        continue
    path = os.path.join(txts_dir, f)
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            content = fh.read()
    except:
        continue
    lines = content.split('\n')
    print(f"\n=== {f} ===")
    count = 0
    for i, line in enumerate(lines):
        lower = line.lower()
        if any(kw in lower for kw in ['pass', 'accura', 'verif', 'result', 'baseline', 'correct', 'solve', 'percent', 'human eval', 'dafny direct', 'direct generation', 'gpt-4', 'deepseek', 'claude', 'baseline', 'zero-shot', 'few-shot']):
            if len(line.strip()) > 10:
                print(f"  L{i}: {line[:250]}")
                count += 1
                if count > 30:
                    break
    print(f"  (matched {count} lines)")
