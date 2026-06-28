"""
修复 pipeline.py 的 _inject_nested_loop_assert 函数
"""
import re

with open(r'D:\codegen-verify\project\pipeline.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 _inject_nested_loop_assert 函数的开始和结束
start = content.find('def _inject_nested_loop_assert')
rest = content[start:]
m = re.search(r'\n\ndef ', rest)
end = start + m.start() + 1 if m else len(content)

new_func = '''
def _inject_nested_loop_assert(code: str) -> str:
    """
    检测嵌套循环，在内层循环后注入 assert 桥接。
    直接从代码的 while 条件中提取变量名。
    """
    import re
    lines = code.split('\\n')

    # 1) 识别外层和内层循环变量
    outer_info = None  # (var, bound)
    inner_info = None  # (var, bound)

    for line in lines:
        # 匹配 while i < |something| 或 while j < |something|
        m = re.search(r'while\\s+(\\w+)\\s+<\\s+(\\S+)', line)
        if m:
            var = m.group(1)
            bound = m.group(2).rstrip('{:')
            if outer_info is None:
                outer_info = (var, bound)
            elif var != outer_info[0]:
                inner_info = (var, bound)
                break  # 找到内层就够了

    if not outer_info or not inner_info:
        return code

    outer_var, outer_bound = outer_info
    inner_var, inner_bound = inner_info

    # 2) 扫描并注入 assert
    result_lines = []
    for idx, line in enumerate(lines):
        result_lines.append(line)
        stripped = line.strip()

        if idx >= 1 and re.match(rf'{outer_var}\\s*:=\\s*{outer_var}\\s*\\+\\s*1(;?)', stripped):
            # 向上查找内层循环
            found = False
            for k in range(idx - 2, max(0, idx - 25), -1):
                lk = lines[k].strip()
                if lk.startswith(f'while {inner_var} <'):
                    found = True
                    break
                if lk.startswith(f'while {outer_var} <'):
                    break

            if found:
                # 从内层 invariant 中提取条件
                condition = None
                for k in range(idx - 2, max(0, idx - 30), -1):
                    lk = lines[k].strip()
                    if 'invariant' in lk and '!result' in lk and 'forall' in lk:
                        # 提取 !(expr) 部分 - 使用宽匹配
                        idx_expr = lk.find('!(')
                        if idx_expr >= 0:
                            end_expr = lk.find(')', idx_expr)
                            if end_expr >= 0:
                                condition = lk[idx_expr+2:end_expr]
                                break

                result_lines.append('    if !result {')
                if condition:
                    # 替换条件中的变量名（保持通用）
                    result_lines.append(f'        assert forall kk :: {outer_var} < kk < {inner_bound} ==> !({condition});')
                else:
                    result_lines.append(f'        assert forall kk :: {outer_var} < kk < {inner_bound} ==> !({outer_bound}[{outer_var}] - {outer_bound}[kk] < threshold && {outer_bound}[kk] - {outer_bound}[{outer_var}] < threshold);')
                result_lines.append('    }')

    return '\\n'.join(result_lines)

'''

content = content[:start] + new_func + content[end:]

with open(r'D:\codegen-verify\project\pipeline.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done - function replaced')
