"""
HumanEval 端到端测试器

从 Pipeline 拿到 Dafny 验证通过的代码后：
1. 编译 Dafny → Python
2. 用 HumanEval 原始测试用例（check()）验证
3. 返回真·通过/失败
"""
import re
import os
import sys
import json
import tempfile
import subprocess
import traceback
from pathlib import Path
from typing import Optional

import config


# ─────────────────────────────────────────────
# Dafny 方法签名解析
# ─────────────────────────────────────────────

def parse_method_signature(code: str, entry_point: str):
    """从 Dafny 代码中提取方法签名，返回 (params, returns)
    params = [(name, type), ...]
    returns = [(name, type), ...]
    """
    # 清理 markdown 标记
    code_clean = code
    if "```dafny" in code_clean:
        code_clean = code_clean.split("```dafny")[1].split("```")[0]
    elif "```" in code_clean:
        code_clean = code_clean.split("```")[1].split("```")[0]

    # 匹配 method 签名（支持多行）
    pattern = rf'method\s+{re.escape(entry_point)}\s*\(([\s\S]*?)\)\s*returns\s*\(([\s\S]*?)\)(?:\s*{{|[\r\n])'
    m = re.search(pattern, code_clean)
    if not m:
        # 尝试匹配无 returns 的 method（void）
        pattern2 = rf'method\s+{re.escape(entry_point)}\s*\(([\s\S]*?)\)\s*(?:{{|[\r\n])'
        m = re.search(pattern2, code_clean)
        if m:
            params = _parse_params(m.group(1))
            return params, []
        return None, None

    params = _parse_params(m.group(1))
    returns = _parse_params(m.group(2))
    return params, returns


def _parse_params(param_str: str):
    """解析 'x: int, y: seq<real>, z: string' 等参数列表"""
    params = []
    # 逐个解析，注意 seq<> 中的逗号
    current = ""
    depth = 0
    for ch in param_str:
        if ch in ('<', '{'):
            depth += 1
            current += ch
        elif ch in ('>', '}'):
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0:
            current = current.strip()
            if ':' in current:
                name, typ = current.split(':', 1)
                params.append((name.strip(), typ.strip()))
            current = ""
        else:
            current += ch
    # 最后一个参数
    current = current.strip()
    if current and ':' in current:
        name, typ = current.split(':', 1)
        params.append((name.strip(), typ.strip()))
    return params


# ─────────────────────────────────────────────
# 类型转换
# ─────────────────────────────────────────────

def _to_dafny_val(val, dafny_type: str):
    """Python → Dafny Python runtime 的类型转换"""
    import _dafny as dafny_runtime

    if dafny_type == 'string':
        if isinstance(val, str):
            return dafny_runtime.Seq(val)
        return val

    if dafny_type.startswith('seq<'):
        inner = dafny_type[4:-1]
        if isinstance(val, (list, tuple)):
            return tuple(_to_dafny_single(v, inner) for v in val)
        return val

    # int, real, bool, char → native
    return val


def _to_dafny_single(val, dafny_type: str):
    """单个值的类型转换"""
    import _dafny as dafny_runtime
    if dafny_type == 'string':
        if isinstance(val, str):
            return dafny_runtime.Seq(val)
        return val
    if dafny_type in ('int', 'real', 'bool', 'char'):
        return val
    # 递归 seq
    if dafny_type.startswith('seq<'):
        inner = dafny_type[4:-1]
        if isinstance(val, (list, tuple)):
            return tuple(_to_dafny_single(v, inner) for v in val)
        return val
    return val


def _from_dafny_val(val, dafny_type: str):
    """Dafny Python runtime → Python native"""
    import _dafny as dafny_runtime

    def seq_items(seq_val):
        if isinstance(seq_val, dafny_runtime.Seq):
            return list(getattr(seq_val, "Elements", getattr(seq_val, "elems", [])))
        if isinstance(seq_val, (list, tuple)):
            return list(seq_val)
        return list(seq_val)

    if dafny_type == 'string':
        if isinstance(val, str):
            return val
        if isinstance(val, dafny_runtime.Seq):
            return ''.join(str(ch) for ch in seq_items(val))
        return str(val)

    if dafny_type.startswith('seq<'):
        inner = dafny_type[4:-1]
        return [_from_dafny_val(v, inner) for v in seq_items(val)]

    return val


# ─────────────────────────────────────────────
# 编译 Dafny → Python + 运行测试
# ─────────────────────────────────────────────

def run_humaneval_test(
    dafny_code: str,
    humeaneval_problem: dict,
    dafny_path: Optional[str] = None,
) -> tuple:
    """
    对单个 HumanEval 问题运行端到端测试。

    参数:
        dafny_code: Pipeline 生成的 Dafny 代码（已验证通过）
        humeaneval_problem: HumanEval 原始数据 dict，含 task_id, entry_point, test 等

    返回:
        (passed: bool, detail: dict)
        detail = {
            "test_passed": bool,
            "error": str | None,
            "assertions_total": int,
            "assertions_passed": int,
        }
    """
    entry_point = humeaneval_problem["entry_point"]
    dafny_path = dafny_path or config.DAFNY_PATH
    solver_path = getattr(config, "DAFNY_SOLVER_PATH", "")
    test_code = humeaneval_problem.get("test", "")
    task_id = humeaneval_problem.get("task_id", "unknown")

    # 清理代码中的 markdown
    clean_code = dafny_code
    if "```dafny" in clean_code:
        clean_code = clean_code.split("```dafny")[1].split("```")[0].strip()
    elif "```" in clean_code:
        clean_code = clean_code.split("```")[1].split("```")[0].strip()

    # 解析方法签名
    params, returns = parse_method_signature(clean_code, entry_point)
    if params is None:
        return False, {
            "test_passed": False,
            "error": f"无法解析方法签名: {entry_point}",
            "assertions_total": 0,
            "assertions_passed": 0,
        }

    # 构建模块名和方法名的 Dafny → Python 映射
    # Dafny method: has_close_elements → Python: has__close__elements
    dafny_method_py = entry_point.replace("_", "__")

    # 构造 Dafny 代码（包装在 module 中）
    # 原始代码末尾有 } 关闭方法体，加 module 包装后需要再加一个 }
    # 所以不用做任何裁剪，直接包进去
    module_code = f"module HumanevalModule {{\n{clean_code}\n}}"

    # 写临时文件
    tmp_dfy = tempfile.NamedTemporaryFile(mode='w', suffix='.dfy', delete=False)
    tmp_dfy.write(module_code)
    tmp_dfy.close()

    outdir = tempfile.mkdtemp()

    try:
        # 编译 Dafny → Python（允许 warnings，Dafny 4.11+ 默认把 warnings 当作错误）
        cmd = [dafny_path, 'translate', 'py']
        if solver_path:
            cmd.extend(['--solver-path', solver_path])
        cmd.extend([
             tmp_dfy.name,
             '--allow-warnings',
             '--output', os.path.join(outdir, 'out'),
             '--include-runtime',
        ])
        r = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=60
        )
        if r.returncode != 0:
            return False, {
                "test_passed": False,
                "error": f"Dafny 编译失败 (rc={r.returncode}): {(r.stderr or r.stdout)[:300]}",
                "assertions_total": 0,
                "assertions_passed": 0,
            }

        # 导入生成的 Python 模块
        py_dir = os.path.join(outdir, 'out-py')
        if py_dir not in sys.path:
            sys.path.insert(0, py_dir)

        import _dafny as dafny_runtime

        # 动态导入模块（清除缓存，防止不同测试间的污染）
        if 'HumanevalModule' in sys.modules:
            del sys.modules['HumanevalModule']
        mod = __import__('HumanevalModule')
        dafny_fn = getattr(mod.default__, dafny_method_py)

        # 构建 wrapper candidate
        def candidate(*args):
            """包装：Python types → Dafny types → 调用 → Dafny types → Python types"""
            # 转换参数
            dafny_args = []
            for i, (pname, ptype) in enumerate(params):
                if i < len(args):
                    dafny_args.append(_to_dafny_single(args[i], ptype))
                else:
                    dafny_args.append(None)

            # 调用
            result = dafny_fn(*dafny_args)

            # 转换返回值
            if returns and len(returns) > 0:
                rname, rtype = returns[0]
                if len(returns) > 1:
                    # 多返回值 → tuple
                    return tuple(
                        _from_dafny_val(result[i] if isinstance(result, tuple) else result, returns[i][1])
                        for i in range(len(returns))
                    )
                return _from_dafny_val(result, rtype)
            return result

        # 执行 HumanEval 测试
        # test_code 包含 check(candidate) 的定义
        # 提取 check 函数并执行

        local_vars = {}
        exec(test_code, {"__builtins__": __builtins__}, local_vars)

        if 'check' not in local_vars:
            return False, {
                "test_passed": False,
                "error": "HumanEval test 中未找到 check() 函数",
                "assertions_total": 0,
                "assertions_passed": 0,
            }

        # 替换 candidate 为标准输出打印（避免 HumanEval 的 METADATA 变量干扰）
        # 直接调用 check()
        check_fn = local_vars['check']

        try:
            check_fn(candidate)
            # 所有 assert 通过
            detail = {
                "test_passed": True,
                "error": None,
                "assertions_total": "N/A",
                "assertions_passed": "N/A",
            }
            return True, detail
        except AssertionError as e:
            detail = {
                "test_passed": False,
                "error": f"测试断言失败: {e}",
                "assertions_total": "N/A",
                "assertions_passed": "N/A",
            }
            return False, detail
        except Exception as e:
            detail = {
                "test_passed": False,
                "error": f"测试执行异常: {type(e).__name__}: {e}",
                "assertions_total": "N/A",
                "assertions_passed": "N/A",
            }
            return False, detail

    except Exception as e:
        return False, {
            "test_passed": False,
            "error": f"测试执行异常: {type(e).__name__}: {e}\n{traceback.format_exc()[:200]}",
            "assertions_total": 0,
            "assertions_passed": 0,
        }
    finally:
        # 清理临时文件
        try:
            os.unlink(tmp_dfy.name)
        except:
            pass
