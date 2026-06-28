import re

with open(r'D:\codegen-verify\gen_ppt_defense_v4.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: swap list and DARK in comps[2]
old = '''("Dafny 验证器", "\\u2705", DARK, ['''
new = '''("Dafny 验证器", "\\u2705", ['''
content = content.replace(old, new)
# Add DARK at the end of the entry
old2 = '''        ], DARK),
    ]'''
new2 = '''        ], DARK),
    ]'''
# Actually it's already DARK at the right position. Let me check...

# Fix 2: update the for loop
old_loop = '''for i, (t, icon, d, cl) in enumerate(comps):
    x = Inches(0.8 + i * 4.1)'''
new_loop = '''comps_data = [("测试执行", "\\u274c", ["只告诉你\\u300c没过\\u300d", "覆盖不到的地方就是盲区"], GRAY),
    ("LLM 自审", "\\u274c", ["漏检 31.7% 的 bug", "还会把对的当成错的"], GRAY),
    ("Dafny 验证器", "\\u2705", ["\\u2713 精确到行号和列", "\\u2713 告诉你违反了什么规约", "\\u2713 数学级别的正确性保证"], DARK)]
for i, (t, icon, items, cl) in enumerate(comps_data):
    x = Inches(0.8 + i * 4.1)'''

# Hmm, this is getting complicated. Let me just replace the whole block.
# Search for "comps = [" and replace the entire thing
import re
comps_block = re.search(r'comps = \[.*?\]', content, re.DOTALL)
if comps_block:
    print("Found comps block at:", comps_block.start())
    print("Content:", comps_block.group()[:100])
    
with open(r'D:\codegen-verify\gen_ppt_defense_v4.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find comps = [ line
for i, line in enumerate(lines):
    if 'comps = [' in line:
        print(f"Line {i+1}: {line.rstrip()}")
        # Print next few lines
        for j in range(i, min(i+15, len(lines))):
            print(f"  {j+1}: {lines[j].rstrip()}")
        break
