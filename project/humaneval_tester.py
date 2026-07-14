"""
HumanEval 端到端测试器

从 Pipeline 拿到 Dafny 验证通过的代码后：
1. 编译 Dafny → Python
2. 用 HumanEval 原始测试用例（check()）验证
3. 返回真·通过/失败
"""
import ast
import re
import os
import sys
import json
import tempfile
import subprocess
import traceback
from contextlib import contextmanager
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
            # Generated Dafny functions use Seq operations such as ``drop``
            # and slicing. A Python tuple happens to support loop indexing but
            # fails as soon as compiled recursive code accesses ``.elems``.
            return dafny_runtime.Seq(
                [_to_dafny_single(v, inner) for v in val]
            )
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
            return dafny_runtime.Seq(
                [_to_dafny_single(v, inner) for v in val]
            )
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

    option_match = re.fullmatch(r"Option\s*<\s*(.+)\s*>", dafny_type)
    if option_match:
        class_name = type(val).__name__
        is_none = getattr(val, "is_None", False)
        if callable(is_none):
            is_none = is_none()
        if class_name.endswith("_None") or is_none:
            return None
        if class_name.endswith("_Some") or hasattr(val, "value"):
            return _from_dafny_val(getattr(val, "value"), option_match.group(1))
        raise TypeError(f"无法识别 Dafny Option 运行时值: {class_name}")

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
# HumanEval test 执行与安全诊断
# ─────────────────────────────────────────────

def _find_check_node(tree: ast.Module):
    checks = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "check"
    ]
    if len(checks) != 1 or not isinstance(checks[0], ast.FunctionDef):
        return None
    return checks[0]


def _is_candidate_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "candidate"
    )


def _diagnostic_assertions(test_code: str):
    """返回可安全逐条重放的顶层 assert，否则返回 None。

    这里故意保守：check() 只能包含可选 docstring 和顶层 assert，
    且每个 assert 必须恰好调用一次 candidate。遇到赋值、循环、
    条件、helper 封装或不含 candidate 的断言时，都不做“部分”
    诊断，以免再次出现漏跑断言的情况。
    """
    try:
        tree = ast.parse(test_code or "")
    except SyntaxError:
        return None

    check_fn_node = _find_check_node(tree)
    if check_fn_node is None:
        return None

    body = list(check_fn_node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]

    if not body or not all(isinstance(stmt, ast.Assert) for stmt in body):
        return None

    for stmt in body:
        if any(
            isinstance(
                node,
                (
                    ast.GeneratorExp,
                    ast.ListComp,
                    ast.SetComp,
                    ast.DictComp,
                    ast.Lambda,
                    ast.NamedExpr,
                    ast.Await,
                    ast.Yield,
                    ast.YieldFrom,
                ),
            )
            for node in ast.walk(stmt.test)
        ):
            return None
        candidate_calls = [
            node for node in ast.walk(stmt.test) if _is_candidate_call(node)
        ]
        if len(candidate_calls) != 1:
            return None

    return body


def _contains_node(root: ast.AST, target: ast.AST) -> bool:
    return any(node is target for node in ast.walk(root))


def _eval_ast(node: ast.AST, namespace: dict):
    expression = ast.Expression(body=node)
    ast.fix_missing_locations(expression)
    return eval(compile(expression, "<humaneval-diagnostic>", "eval"), namespace)


def _infer_expected(assertion: ast.Assert, candidate_call: ast.Call, namespace: dict):
    """尽力从常见比较式中提取期望值；提取失败不影响测试判定。"""
    test = assertion.test

    # abs(candidate(...) - expected) < tolerance
    for node in ast.walk(test):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "abs"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.BinOp)
            and isinstance(node.args[0].op, (ast.Sub, ast.Add))
        ):
            continue
        difference = node.args[0]
        left_has_candidate = _contains_node(difference.left, candidate_call)
        right_has_candidate = _contains_node(difference.right, candidate_call)
        try:
            if left_has_candidate and not right_has_candidate:
                return _eval_ast(difference.right, namespace)
            if right_has_candidate and not left_has_candidate:
                return _eval_ast(difference.left, namespace)
        except Exception:
            pass

    if isinstance(test, ast.Compare):
        operands = [test.left, *test.comparators]
        for index, operand in enumerate(operands):
            if not _contains_node(operand, candidate_call):
                continue
            other_indices = [i for i in range(len(operands)) if i != index]
            if len(other_indices) != 1:
                return None
            other = operands[other_indices[0]]
            if _contains_node(other, candidate_call):
                return None
            try:
                return _eval_ast(other, namespace)
            except Exception:
                return None

    if test is candidate_call:
        return True
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        if test.operand is candidate_call:
            return False
    return None


def _format_failing_input(args: tuple, kwargs: dict):
    if not kwargs:
        return list(args)
    return {"args": list(args), "kwargs": dict(kwargs)}


def _run_asserts_with_diagnostics(
    test_code: str,
    candidate,
    base_namespace: Optional[dict] = None,
):
    """
    在确认能完整覆盖 check() 后逐条重放 assert，捕获首个反例。

    注意：这个函数只用于“完整 check() 已失败”之后的附加诊断；
    它的返回值不能代替完整 check() 的测试结果。

    返回:
        (passed, detail) —— 可完整诊断时
        None —— 不能证明逐条模式与 check() 完全等价
    """
    assertions = _diagnostic_assertions(test_code)
    if assertions is None:
        return None

    namespace = dict(base_namespace or {})
    namespace.setdefault("__builtins__", __builtins__)
    total = len(assertions)

    for idx, assertion in enumerate(assertions, start=1):
        candidate_call = next(
            node for node in ast.walk(assertion.test) if _is_candidate_call(node)
        )
        invocation = {}

        def traced_candidate(*args, **kwargs):
            invocation["args"] = args
            invocation["kwargs"] = kwargs
            try:
                actual = candidate(*args, **kwargs)
            except Exception as exc:
                invocation["exception"] = exc
                raise
            invocation["actual"] = actual
            return actual

        assertion_namespace = dict(namespace)
        assertion_namespace["candidate"] = traced_candidate
        try:
            statement = ast.Module(body=[assertion], type_ignores=[])
            ast.fix_missing_locations(statement)
            exec(
                compile(statement, "<humaneval-diagnostic>", "exec"),
                assertion_namespace,
                assertion_namespace,
            )
        except AssertionError:
            if not invocation:
                return None
            args = invocation.get("args", ())
            kwargs = invocation.get("kwargs", {})
            actual = invocation.get("actual")
            expected_namespace = dict(assertion_namespace)
            expected_namespace.pop("candidate", None)
            expected = _infer_expected(
                assertion, candidate_call, expected_namespace
            )
            if "exception" in invocation:
                call_error = invocation["exception"]
                error = (
                    f"输入={_format_failing_input(args, kwargs)!r} 调用异常: "
                    f"{type(call_error).__name__}: {call_error}"
                )
            else:
                error = (
                    f"输入={_format_failing_input(args, kwargs)!r} "
                    f"期望={expected!r} 实际={actual!r}"
                )
            return False, {
                "test_passed": False,
                "error": error,
                "failing_input": _format_failing_input(args, kwargs),
                "expected": expected,
                "actual": actual,
                "assertions_total": total,
                "assertions_passed": idx - 1,
            }
        except Exception as exc:
            args = invocation.get("args", ())
            kwargs = invocation.get("kwargs", {})
            if not invocation:
                return None
            expected_namespace = dict(assertion_namespace)
            expected_namespace.pop("candidate", None)
            expected = _infer_expected(
                assertion, candidate_call, expected_namespace
            )
            return False, {
                "test_passed": False,
                "error": (
                    f"输入={_format_failing_input(args, kwargs)!r} 调用异常: "
                    f"{type(exc).__name__}: {exc}"
                ),
                "failing_input": _format_failing_input(args, kwargs),
                "expected": expected,
                "actual": invocation.get("actual"),
                "assertions_total": total,
                "assertions_passed": idx - 1,
            }

    return True, {
        "test_passed": True,
        "error": None,
        "assertions_total": total,
        "assertions_passed": total,
    }


def _blackbox_detail(error: str):
    return {
        "test_passed": False,
        "error": error,
        "assertions_total": "N/A",
        "assertions_passed": "N/A",
    }


def _execute_test_code(
    test_code: str,
    candidate,
    support_code: str = "",
    entry_point: str = "",
):
    """完整执行 check(candidate)，并且只用诊断重放补充反例。"""
    namespace = {"__builtins__": __builtins__}
    try:
        # 少数 HumanEval check() 会调用 prompt 中先于目标函数
        # 定义的 helper（例如 poly/encode_shift）。在同一隔离
        # namespace 中先加载 prompt，才符合 HumanEval 原始 harness 语义。
        if support_code:
            exec(support_code, namespace, namespace)
        if entry_point:
            # 官方 harness 中 completion 就是 prompt 里的同名函数。
            # 部分 check() 不仅使用参数 candidate，还会直接
            # 引用该全局名，因此需要用 Dafny wrapper 覆盖 placeholder。
            namespace[entry_point] = candidate
        # globals/locals 使用同一 namespace，保证顶层 import/helper 对
        # check() 可见，与普通 Python 模块语义一致。
        exec(test_code or "", namespace, namespace)
    except Exception as exc:
        return False, _blackbox_detail(
            f"HumanEval test 加载异常: {type(exc).__name__}: {exc}"
        )

    check_fn = namespace.get("check")
    if not callable(check_fn):
        return False, {
            "test_passed": False,
            "error": "HumanEval test 中未找到 check() 函数",
            "assertions_total": 0,
            "assertions_passed": 0,
        }

    try:
        check_fn(candidate)
    except AssertionError as exc:
        diagnostic = _run_asserts_with_diagnostics(test_code, candidate, namespace)
        if diagnostic is not None and diagnostic[0] is False:
            return diagnostic
        suffix = f": {exc}" if str(exc) else ""
        return False, _blackbox_detail(f"测试断言失败{suffix}")
    except Exception as exc:
        diagnostic = _run_asserts_with_diagnostics(test_code, candidate, namespace)
        if diagnostic is not None and diagnostic[0] is False:
            return diagnostic
        return False, _blackbox_detail(
            f"测试执行异常: {type(exc).__name__}: {exc}"
        )

    return True, {
        "test_passed": True,
        "error": None,
        "assertions_total": "N/A",
        "assertions_passed": "N/A",
    }


_WORKER_FLAG = "--humaneval-worker"
_DEFAULT_TEST_TIMEOUT_SECONDS = 10.0


def _test_timeout_seconds() -> float:
    raw = os.getenv("HUMANEVAL_TEST_TIMEOUT", str(_DEFAULT_TEST_TIMEOUT_SECONDS))
    try:
        return max(0.1, float(raw))
    except (TypeError, ValueError):
        return _DEFAULT_TEST_TIMEOUT_SECONDS


def _module_is_under(module, directory: Path) -> bool:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return False
    try:
        Path(module_file).resolve().relative_to(directory.resolve())
        return True
    except (OSError, ValueError):
        return False


@contextmanager
def _loaded_generated_candidate(
    py_dir: str,
    method_name: str,
    params,
    returns,
):
    """
    在可恢复的 sys.path/模块环境中加载 Dafny 产生的 candidate。

    实际测试还会在独立子进程中运行；这里显式恢复状态，
    避免 worker 内的生成模块或 _dafny 缓存串扰后续操作。
    """
    generated_dir = Path(py_dir).resolve()
    original_path = list(sys.path)
    original_modules = dict(sys.modules)
    cache_sensitive_names = {"HumanevalModule", "_dafny"}

    try:
        sys.path.insert(0, str(generated_dir))
        for name in cache_sensitive_names:
            sys.modules.pop(name, None)

        mod = __import__("HumanevalModule")
        dafny_fn = getattr(mod.default__, method_name)

        def candidate(*args, **kwargs):
            if kwargs:
                raise TypeError("Dafny candidate 不支持关键字参数")
            if len(args) != len(params):
                raise TypeError(
                    f"candidate 需要 {len(params)} 个参数，实际收到 {len(args)} 个"
                )

            dafny_args = [
                _to_dafny_single(value, param_type)
                for value, (_, param_type) in zip(args, params)
            ]
            result = dafny_fn(*dafny_args)

            if not returns:
                return result
            if len(returns) == 1:
                return _from_dafny_val(result, returns[0][1])

            if not isinstance(result, tuple):
                raise TypeError("Dafny 多返回值未翻译为 tuple")
            return tuple(
                _from_dafny_val(result[index], return_type)
                for index, (_, return_type) in enumerate(returns)
            )

        yield candidate
    finally:
        sys.path[:] = original_path

        # 先移除本次从生成目录加载的所有模块，再恢复
        # worker 原有的同名模块。
        for name, module in list(sys.modules.items()):
            if name not in original_modules and _module_is_under(module, generated_dir):
                sys.modules.pop(name, None)
        for name in cache_sensitive_names:
            if name in original_modules:
                sys.modules[name] = original_modules[name]
            else:
                sys.modules.pop(name, None)


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return repr(value)


def _worker_main(payload_path: str, result_path: str) -> int:
    try:
        payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
        with _loaded_generated_candidate(
            payload["py_dir"],
            payload["method_name"],
            payload["params"],
            payload["returns"],
        ) as candidate:
            passed, detail = _execute_test_code(
                payload["test_code"],
                candidate,
                payload.get("support_code", ""),
                payload.get("entry_point", ""),
            )
    except BaseException as exc:
        passed = False
        detail = _blackbox_detail(
            f"隔离测试进程异常: {type(exc).__name__}: {exc}"
        )

    result = {"passed": bool(passed), "detail": _json_safe(detail)}
    try:
        Path(result_path).write_text(
            json.dumps(result, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        return 2
    return 0


def _run_test_in_subprocess(
    py_dir: str,
    method_name: str,
    params,
    returns,
    test_code: str,
    timeout_seconds: Optional[float] = None,
    support_code: str = "",
    entry_point: str = "",
):
    """在独立 Python 进程中执行不可信的 check/candidate 组合。"""
    timeout = _test_timeout_seconds() if timeout_seconds is None else timeout_seconds
    timeout = max(0.1, float(timeout))

    with tempfile.TemporaryDirectory(prefix="humaneval-runner-") as ipc_dir:
        ipc_root = Path(ipc_dir)
        payload_path = ipc_root / "payload.json"
        result_path = ipc_root / "result.json"
        payload_path.write_text(
            json.dumps(
                {
                    "py_dir": str(Path(py_dir).resolve()),
                    "method_name": method_name,
                    "params": list(params),
                    "returns": list(returns),
                    "test_code": test_code or "",
                    "support_code": support_code or "",
                    "entry_point": entry_point or "",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            _WORKER_FLAG,
            str(payload_path),
            str(result_path),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(ipc_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, _blackbox_detail(
                f"HumanEval 测试超时（>{timeout:g}s）"
            )

        if not result_path.exists():
            process_output = (completed.stderr or completed.stdout or "").strip()
            suffix = f": {process_output[:300]}" if process_output else ""
            return False, _blackbox_detail(
                f"HumanEval 隔离测试进程失败 (rc={completed.returncode}){suffix}"
            )

        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            passed = bool(result["passed"])
            detail = result["detail"]
            if not isinstance(detail, dict):
                raise TypeError("detail 不是 dict")
            return passed, detail
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return False, _blackbox_detail(
                f"HumanEval 隔离测试结果无效: {type(exc).__name__}: {exc}"
            )


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

    try:
        # Dafny 源文件、翻译输出和 runtime 都局限在一个自动清理的
        # 临时目录中，避免 benchmark 长跑时持续泄漏 out-py 目录。
        with tempfile.TemporaryDirectory(prefix="humaneval-dafny-") as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "candidate.dfy"
            output_base = temp_root / "out"
            source_path.write_text(module_code, encoding="utf-8")

            # 编译 Dafny → Python（允许 warnings，Dafny 4.11+ 默认把
            # warnings 当作错误）。
            cmd = [dafny_path, "translate", "py"]
            if solver_path:
                cmd.extend(["--solver-path", solver_path])
            cmd.extend([
                str(source_path),
                "--allow-warnings",
                "--output", str(output_base),
                "--include-runtime",
            ])
            try:
                compiled = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                return False, {
                    "test_passed": False,
                    "error": "Dafny 编译超时（>60s）",
                    "assertions_total": 0,
                    "assertions_passed": 0,
                }

            if compiled.returncode != 0:
                compiler_output = compiled.stderr or compiled.stdout or ""
                return False, {
                    "test_passed": False,
                    "error": (
                        f"Dafny 编译失败 (rc={compiled.returncode}): "
                        f"{compiler_output[:300]}"
                    ),
                    "assertions_total": 0,
                    "assertions_passed": 0,
                }

            py_dir = temp_root / "out-py"
            if not py_dir.is_dir():
                return False, {
                    "test_passed": False,
                    "error": f"Dafny 编译未生成 Python 目录: {py_dir.name}",
                    "assertions_total": 0,
                    "assertions_passed": 0,
                }

            # 完整 check() 与 candidate 在可超时终止的独立进程中运行。
            return _run_test_in_subprocess(
                str(py_dir),
                dafny_method_py,
                params,
                returns,
                test_code,
                support_code=humeaneval_problem.get("prompt", ""),
                entry_point=entry_point,
            )

    except Exception as e:
        return False, {
            "test_passed": False,
            "error": f"测试执行异常: {type(e).__name__}: {e}\n{traceback.format_exc()[:200]}",
            "assertions_total": 0,
            "assertions_passed": 0,
        }


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == _WORKER_FLAG:
    raise SystemExit(_worker_main(sys.argv[2], sys.argv[3]))
