"""
Specification repair utilities.

The repair agent strengthens weak generated specs before code generation. It is
designed as a conservative research mechanism: if the repaired spec is invalid,
the pipeline falls back to the original spec and records the failed attempt.
"""
import os
import re
import subprocess
import tempfile
from typing import Any

import config
from dafny_wrapper import DafnyVerifier
from spec_adequacy import check_spec_adequacy
from contract_utils import bodyless_callable_names


CRITICAL_FLAGS = {
    "no_postcondition",
    "postcondition_does_not_constrain_result",
    "postcondition_ignores_inputs",
    "trivial_or_shape_only_postcondition",
    "low_semantic_signal",
    "sequence_task_without_element_or_length_condition",
    "string_task_without_string_semantics",
    "bool_task_without_logical_condition",
    "threshold_task_without_distance_condition",
    "ordering_task_without_order_constraint",
    "mutation_verified_mutant",
    "verified_but_behavior_failed",
    "proof_friendly_reference_missing",
    "invalid_dafny_spec",
}


def should_repair_spec(adequacy: dict[str, Any]) -> bool:
    if not config.ENABLE_SPEC_REPAIR:
        return False
    level = adequacy.get("level", "")
    flags = set(adequacy.get("flags") or [])
    return level in {"inadequate", "weak", "partial"} or bool(flags & CRITICAL_FLAGS)


def repair_spec_with_llm(
    llm,
    problem_desc: str,
    spec: str,
    adequacy: dict[str, Any],
    max_retries: int | None = None,
) -> dict[str, Any]:
    max_retries = config.MAX_SPEC_REPAIR_RETRIES if max_retries is None else max_retries
    original_signature = _method_signature_line(spec)
    last_error = ""

    for attempt in range(max_retries + 1):
        raw = llm.chat(
            system=_system_prompt(),
            user=_user_prompt(problem_desc, spec, adequacy, original_signature, last_error),
        )
        candidate = _strip_method_bodies(_extract_dafny_code(raw))
        valid, error = validate_spec(candidate)
        candidate_adequacy = check_spec_adequacy(candidate, problem_desc)

        if valid and _signature_compatible(original_signature, candidate):
            return {
                "repaired": True,
                "spec": candidate,
                "adequacy": candidate_adequacy,
                "attempts": attempt + 1,
                "error": "",
            }

        last_error = error or "method signature changed or missing"

    return {
        "repaired": False,
        "spec": spec,
        "adequacy": adequacy,
        "attempts": max_retries + 1,
        "error": last_error,
    }


def validate_spec(spec: str) -> tuple[bool, str]:
    if not spec.strip():
        return False, "empty spec"

    bodyless = bodyless_callable_names(spec)
    direct_references = set(re.findall(
        r"ensures\s+\w+\s*(?:==|<==>)\s*([A-Za-z_]\w*)\s*\(",
        spec,
    ))
    missing_runtime_bodies = sorted(bodyless & direct_references)
    if missing_runtime_bodies:
        return False, (
            "non-executable result reference helper(s) missing a body: "
            + ", ".join(missing_runtime_bodies)
        )

    bad_patterns = [
        (r"\bvar\b\s+\w+\s*:", "var declaration in spec"),
        (r"\bfor\b\s+\w+\s*:", "for loop in spec"),
        (r"\bwhile\b\s+", "while loop in spec"),
        (r"\breturn\b", "return statement in spec"),
    ]
    clause_lines = [
        line.strip()
        for line in spec.splitlines()
        if line.strip().startswith(("requires", "ensures"))
    ]
    for pattern, description in bad_patterns:
        for line in clause_lines:
            if re.search(pattern, line):
                return False, f"{description}: {line[:120]}"

    verifier = DafnyVerifier()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".dfy", delete=False, encoding="utf-8") as f:
        f.write(spec)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [verifier.dafny_path, "resolve", "--allow-warnings", tmp_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0 or "error" in output.lower():
            lines = [line.strip() for line in output.splitlines() if "Error" in line]
            return False, "; ".join(lines[:3]) if lines else output[-300:]
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "spec resolve timeout"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _system_prompt() -> str:
    return """你是 Dafny 规约修复专家。
任务：在保持方法签名和合法输入域不变的前提下，修正 Dafny 规约，使其准确表达自然语言题意。

硬性规则：
- 只输出 Dafny 规约，不输出方法体实现。
- 必须保留原 method 名、参数列表、returns 列表。
- 不得新增会排除公开示例、空输入或题目其他合法输入的公共 method requires。
- 可以添加 requires/ensures，也可以添加纯 function/predicate helper。
- `ensures result == Reference(...)` 直接调用的 reference helper 必须有 `{ ... }` 可执行函数体；仅用于 ghost 规约的抽象 helper 可以无 body，但不能被运行时 reference function 调用。
- 对纯输入→输出任务，优先添加全定义、可执行的递归 reference function，并用 `ensures result == Reference(inputs)` 表达完整语义，便于实现直接复用和验证。
- 当 flags 包含 `proof_friendly_reference_missing` 时，把核心语义移入 reference function 的可执行函数体，并用 `ensures result == Reference(inputs)` 作为主后置条件；删除与其重复、需要大量额外引理的量词后置条件，但不得丢失题意。
- ensures/requires 中只能使用纯表达式，禁止 var、:=、return、while、for。
- 字符转换：int→char 写 `(x as char)`，单字符 string 写 `[(x as char)]`；Dafny 没有 `char(x)` 构造器，也不能把 int 直接 `as string`。
- 核心语义不能留给测试；同时避免与题意无关、重复或极难证明的巨型量词。
- 每个 ensures 独立成行。
"""


def _user_prompt(
    problem_desc: str,
    spec: str,
    adequacy: dict[str, Any],
    original_signature: str,
    last_error: str,
) -> str:
    retry_hint = ""
    if last_error:
        retry_hint = f"\n\n上一次修复后的规约无效，错误如下：\n{last_error}\n请修正语法并保持签名不变。"

    reference_hint = _reference_pattern_hint(problem_desc, adequacy)

    return f"""自然语言题目：
{problem_desc}

原始方法签名（必须保持不变）：
{original_signature}

当前 Dafny 规约：
```dafny
{spec}
```

规约充分性检查结果：
```json
{adequacy}
```

请输出加强后的 Dafny 规约。
重点补齐 missing_obligations 和 flags 暴露的问题，例如：
- 没有 ensures 时，添加至少一个约束 result 的 ensures；
- result 没有关联输入时，添加 result 与输入参数的关系；
- list/string 任务可添加长度、元素、membership、字符或连接相关约束；
- bool 任务尽量同时描述 true/false 条件；
- threshold/order/sum 任务添加相应比较、距离或累计约束。
{reference_hint}
{retry_hint}
"""


def _reference_pattern_hint(problem_desc: str, adequacy: dict[str, Any]) -> str:
    flags = set(adequacy.get("flags") or [])
    if "proof_friendly_reference_missing" not in flags:
        return ""
    text = (problem_desc or "").lower()
    if any(token in text for token in ("paren", "parenthes")) and "group" in text:
        return """- 字符串括号分组任务：定义有完整 `{ ... }` 函数体的 total recursive scanner。helper 参数应线程化携带 remaining/input index、current group、depth、completed groups；每次消费一个字符并按剩余长度 decreases。空格跳过，'(' 增加深度，')' 使深度回到 0 时把 current group 追加到 completed groups。再用一个一参数 reference wrapper 从空状态调用 scanner。不要只声明无 body 的抽象函数。"""
    if any(token in text for token in ("prefix", "balance", "below zero", "below_zero")):
        return """- 前缀/余额任务：定义 total recursive helper，参数携带剩余输入和 accumulator；每步先更新 accumulator，再判断当前前缀条件，最后递归处理尾部。reference wrapper 从初始 accumulator 调用它，并必须有完整函数体。"""
    return """- 返回序列任务：优先定义消费输入头部、递归处理尾部并用 `+` 构造结果的 total reference function。若需要解析状态，把状态作为 helper 参数线程化传递；所有 helper 必须有完整函数体和显然递减的剩余输入。"""


def _extract_dafny_code(text: str) -> str:
    code = text or ""
    if "```dafny" in code:
        code = code.split("```dafny", 1)[1].split("```", 1)[0].strip()
    elif "```" in code:
        code = code.split("```", 1)[1].split("```", 1)[0].strip()
    if code.lower().startswith("dafny\n"):
        code = code.split("\n", 1)[1]
    return re.sub(r"[^\x00-\x7F\n\r ]+", "", code).strip()


def _strip_method_bodies(spec_code: str) -> str:
    lines = spec_code.splitlines()
    result = []
    in_method_body = False
    depth = 0

    for line in lines:
        stripped = line.strip()
        if in_method_body:
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                in_method_body = False
            continue

        if stripped == "{" and any(l.lstrip().startswith("method ") for l in result[-6:]):
            in_method_body = True
            depth = 1
            continue

        if stripped.startswith("method ") and "{" in line:
            result.append(line.split("{", 1)[0].rstrip())
            in_method_body = True
            depth = line.count("{") - line.count("}")
            if depth <= 0:
                in_method_body = False
            continue

        result.append(line)

    return "\n".join(result).strip()


def _method_signature_line(spec: str) -> str:
    match = re.search(
        r"method\s+\w+\s*\([\s\S]*?\)\s*(?:returns\s*\([\s\S]*?\))?",
        spec,
        flags=re.DOTALL,
    )
    return match.group(0).strip() if match else ""


def _signature_compatible(original_signature: str, candidate: str) -> bool:
    if not original_signature:
        return True
    return _normalize_signature(original_signature) == _normalize_signature(_method_signature_line(candidate))


def _normalize_signature(signature: str) -> str:
    return re.sub(r"\s+", "", signature)
