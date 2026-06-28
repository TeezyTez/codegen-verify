"""
直接替换 pipeline.py 中的 _inject_nested_loop_assert 函数
"""
import re

with open(r'D:\codegen-verify\project\pipeline.py', 'r', encoding='utf-8') as f:
    content = f.read()

start = content.find('def _inject_nested_loop_assert')
if start < 0:
    print('ERROR: _inject_nested_loop_assert not found')
    exit(1)

# 找到函数结束位置
rest = content[start:]
# 函数结束在下一个 def 或文件末尾
m = re.search(r'\n\ndef ', rest)
if m:
    end = start + m.start() + 1
else:
    end = len(content)

old_func = content[start:end]

new_func = """def _inject_nested_loop_assert(code: str) -> str:
    \"\"\"
    检测嵌套循环，在内层循环后注入 assert 桥接。
    从代码中自动提取变量名。
    \"\"\"
    import re

    lines = code.split('\\n')
    # 扫描提取 outer/inner 变量和 bound
    outer_var, outer_seq, inner_var, inner_bound = None, None, None, None
    for line in lines:
        m = re.search(r'while\\s+(\\w+)\\s+<\\s+\\|(\\w+)\\|', line)
        if m:
            v, s = m.group(1), m.group(2)
            if outer_var is None:
                outer_var, outer_seq = v, s
            elif v != outer_var and inner_var is None:
                inner_var = v
        m2 = re.search(r'while\\s+(\\w+)\\s+<\\s+(\\S+[^:])\\s*', line)
        if m2 and m2.group(1) != outer_var and inner_var is None:
            inner_var = m2.group(1)
            inner_bound = m2.group(2).split('\\n')[0].rstrip()

    if not inner_var or not outer_var:
        return code

    # 第二次扫描：注入 assert
    result = []
    for idx, line in enumerate(lines):
        result.append(line)
        stripped = line.strip()

        if idx >= 1 and stripped.startswith(f'{outer_var} := {outer_var} + 1'):
            # 向上找最近的内层 while
            found_inner = False
            for k in range(idx - 2, max(0, idx - 30), -1):
                lk = lines[k].strip()
                if lk.startswith(f'while {inner_var} <'):
                    found_inner = True
                    break
                if lk.startswith(f'while {outer_var} <'):
                    break

            if found_inner:
                # 查找内层循环的 invariant 来提取条件
                cond = None
                for k in range(idx - 2, max(0, idx - 30), -1):
                    lk = lines[k].strip()
                    if 'invariant' in lk and '!result' in lk:
                        # 提取 !(expr) 部分
                        m_inv = re.search(r'!result ==> forall\\s+\\w+\\s+::\\s+.+==>\\s+!\\((.*)\\)', lk)
                        if m_inv:
                            cond = m_inv.group(1)
                            break

                result.append('    if !result {')
                if cond:
                    result.append(f'        assert forall j_test :: {outer_var} < j_test < {inner_bound} ==> !({cond});')
                else:
                    inner_seq = inner_bound.replace('|', '') if '|' in str(inner_bound) else outer_seq
                    result.append(f'        assert forall j_test :: {outer_var} < j_test < {inner_bound} ==> !({outer_seq}[{outer_var}] - {outer_seq}[j_test] < threshold && {outer_seq}[j_test] - {outer_seq}[{outer_var}] < threshold);')
                result.append('    }')

    return '\\n'.join(result)


"""

content = content[:start] + new_func + content[end:]

with open(r'D:\codegen-verify\project\pipeline.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done')
