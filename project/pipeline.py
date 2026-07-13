"""
规约引导的代码生成 + 验证反馈驱动的自修复 Pipeline
基于 LangGraph 多 Agent 架构
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from typing import TypedDict, Literal
from dataclasses import dataclass, field
import json

import config
from llm_client import spec_llm, code_llm, repair_llm
from dafny_wrapper import DafnyVerifier, VerificationResult, ErrorInfo
from templates import get_verified_template
from research_trace import (
    append_trace,
    attribute_failure,
    spec_adequacy_snapshot,
    spec_metrics,
    trace_event,
    verification_snapshot,
)
from spec_repair import repair_spec_with_llm, should_repair_spec
from repair_policy import choose_repair_policy
from proof_repair import extract_dafny_code as extract_proof_dafny_code
from proof_repair import repair_proof_with_llm
from spec_code_alignment import extract_dafny_code as extract_alignment_dafny_code
from spec_code_alignment import repair_alignment_with_llm
from mutation_probe import probe_spec_mutants
from contract_utils import contract_fidelity_issues


# ==================== 后处理函数 ====================

def _extract_dafny_code(text: str) -> str:
    """提取 LLM 输出中的 Dafny 代码块，并清理非 ASCII 噪声。"""
    import re
    code = text or ""
    if "```dafny" in code:
        code = code.split("```dafny", 1)[1].split("```", 1)[0].strip()
    elif "```" in code:
        code = code.split("```", 1)[1].split("```", 1)[0].strip()
    return re.sub(r'[^\x00-\x7F\n\r ]+', '', code).strip()


def _strip_method_bodies_from_spec(spec_code: str) -> str:
    """
    Spec Agent 偶尔会把 method body 一起输出。规约阶段只保留签名和
    requires/ensures，避免 Code Agent 把未验证的实现当作约束。
    """
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


def _static_code_issues(code: str) -> list[str]:
    """捕获 Dafny 中最常见且可静态识别的 LLM 语法错误。"""
    import re
    issues = []
    lines = code.splitlines()
    in_pure_decl = False
    decl_name = ""
    depth = 0

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        m = re.match(r'(function|predicate)\s+(\w+)', stripped)
        if m:
            in_pure_decl = True
            decl_name = m.group(2)
            depth = line.count("{") - line.count("}")
            if "{" not in line:
                depth = 0
            continue

        if in_pure_decl:
            if "{" in line or "}" in line:
                depth += line.count("{") - line.count("}")

            if re.search(r'\b(while|for)\b', stripped):
                issues.append(f"L{lineno}: function/predicate `{decl_name}` contains loop `{stripped[:80]}`")
            if re.search(r'\bvar\b\s+\w+', stripped) or ':=' in stripped:
                issues.append(f"L{lineno}: function/predicate `{decl_name}` contains command `{stripped[:80]}`")

            if depth <= 0 and "}" in line:
                in_pure_decl = False
                decl_name = ""

    if "assert !result ==>" in code and "returns (result: bool)" not in code:
        issues.append("contains boolean-result assert bridge in a method whose result is not bool")
    if "|s|[" in code or "threshold" in code and "threshold" not in code.split("{", 1)[0]:
        issues.append("contains suspicious injected placeholder expression")
    return issues


def _extract_spec_from_code(code: str) -> str:
    """Extract method-level contract from a full Dafny implementation."""
    return _strip_method_bodies_from_spec(_extract_dafny_code(code))


def _is_vacuous_spec(spec: str, adequacy: dict) -> bool:
    """放宽后的规约是否退化成不约束 result 的空规约。"""
    flags = (adequacy or {}).get("flags") or []
    if "postcondition_does_not_constrain_result" in flags:
        return True
    has_ensures = any(line.strip().startswith("ensures") for line in (spec or "").splitlines())
    return not has_ensures


def _contract_clauses(spec: str) -> list[str]:
    clauses = []
    for line in (spec or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(("requires", "ensures")):
            clauses.append(_normalize_contract_clause(stripped))
    return clauses


def _normalize_contract_clause(clause: str) -> str:
    return " ".join(clause.strip().split())


def _missing_original_contract_clauses(original_spec: str, candidate_code: str) -> list[str]:
    """Compatibility wrapper around the structured public-contract check."""
    return contract_fidelity_issues(original_spec, candidate_code)


def _candidate_code_issues(
    spec: str,
    code: str,
    entry_point: str = "",
    *,
    run_resolve: bool = False,
) -> list[str]:
    """Return deterministic issues that must be fixed before verification."""
    issues = list(_static_code_issues(code))
    issues.extend(
        f"public contract mismatch: {issue}"
        for issue in contract_fidelity_issues(spec, code, entry_point)
    )
    if run_resolve and not issues:
        resolution = DafnyVerifier().resolve(code)
        if not resolution.passed:
            for error in resolution.errors[:8]:
                subtype = getattr(error, "subtype", "") or error.error_type
                source = f" source={error.source!r}" if getattr(error, "source", "") else ""
                issues.append(
                    f"Dafny resolve [{subtype}] L{error.location_line}: {error.message}{source}"
                )
            if not resolution.errors:
                issues.append("Dafny resolve failed without a structured diagnostic")
    return issues


def _inject_nested_loop_assert(code: str) -> str:
    """
    检测嵌套循环，在内层循环后、i := i + 1 之前注入 assert 桥接。
    如果 LLM 已经加了 assert 桥接，则跳过。
    """
    import re
    # 这个后处理只对 has_close_elements 这类 bool pair-search 模式安全。
    # 旧版会把 unrelated string/list 题也注入 threshold/numbers 断言，反而制造语法错误。
    if not (
        "returns (result: bool)" in code
        and "numbers: seq<real>" in code
        and "threshold" in code
        and "while i < |numbers|" in code
    ):
        return code

    lines = code.split('\n')

    # 1) 识别外层和内层循环变量
    outer_info = None  # (var, bound)
    inner_info = None  # (var, bound)

    for line in lines:
        m = re.search(r'while\s+(\w+)\s+<\s+(\S+)', line)
        if m:
            var = m.group(1)
            bound = m.group(2).rstrip('{:')
            if outer_info is None:
                outer_info = (var, bound)
            elif var != outer_info[0]:
                inner_info = (var, bound)
                break

    if not outer_info or not inner_info:
        return code

    outer_var, outer_bound = outer_info
    inner_var, inner_bound = inner_info

    # 2) 扫描并注入 assert（在 i := i + 1 之前）
    result_lines = []
    for idx, line in enumerate(lines):
        stripped = line.strip()

        if idx >= 1 and re.match(rf'{outer_var}\s*:=\s*{outer_var}\s*\+\s*1\s*;?\s*$', stripped):
            # 检查前面几行是否已经有 assert 桥接（LLM 可能已经加过）
            has_existing_assert = False
            for k in range(idx - 1, max(0, idx - 6), -1):
                if 'assert' in lines[k] and 'forall' in lines[k]:
                    has_existing_assert = True
                    break

            # 向上查找内层循环
            has_inner_loop = False
            for k in range(idx - 2, max(0, idx - 25), -1):
                lk = lines[k].strip()
                if lk.startswith(f'while {inner_var} <'):
                    has_inner_loop = True
                    break
                if lk.startswith(f'while {outer_var} <'):
                    break

            if has_inner_loop and not has_existing_assert:
                # 从内层 invariant 中提取条件
                condition = None
                forall_var = None
                for k in range(idx - 2, max(0, idx - 30), -1):
                    lk = lines[k].strip()
                    if 'invariant' in lk and '!result' in lk and 'forall' in lk:
                        m_fv = re.search(r'forall\s+(\w+)\s+::', lk)
                        if m_fv:
                            forall_var = m_fv.group(1)
                        idx_expr = lk.find('!(')
                        if idx_expr >= 0:
                            end_expr = lk.find(')', idx_expr)
                            if end_expr >= 0:
                                condition = lk[idx_expr+2:end_expr]
                                break

                # 注入 assert 在 i := i + 1 之前
                indent = line[:len(line) - len(line.lstrip())]
                if condition and forall_var:
                    cond_fixed = condition.replace(forall_var, 'kk')
                    result_lines.append(f'{indent}// assert bridge: connect inner loop result to outer invariant')
                    result_lines.append(f'{indent}assert !result ==> forall kk :: {outer_var} < kk < {inner_bound} ==> !({cond_fixed});')

            result_lines.append(line)
        else:
            result_lines.append(line)

    return '\n'.join(result_lines)






# ==================== 状态定义 ====================

class PipelineState(TypedDict):
    """在 Agent 之间传递的全局状态"""
    problem_id: str                        # 问题 ID
    problem_desc: str                      # 问题描述
    spec: str                              # 生成的规约
    code: str                              # 生成的代码
    verification: VerificationResult       # 验证结果
    diagnosis: str                         # 当前诊断文本
    last_attribution: dict                 # 最近一次验证失败归因
    spec_adequacy: dict                    # 规约充分性检查结果
    mutation_adequacy: dict                # mutation-based 规约充分性探针
    repair_policy: dict                    # harness repair policy 决策
    entry_point: str                       # 目标入口函数名
    behavior_problem: dict                 # 可选 HumanEval 原始问题，用于行为测试
    behavior_executed: bool                # 是否执行了行为测试
    behavior_passed: bool                  # 行为测试是否通过
    behavior_error: str                    # 行为测试失败信息
    behavior_detail: dict                  # 行为测试详情
    dafny_verified: bool                   # Dafny 是否验证通过
    last_verified_code: str                # 最近一次 Dafny 验证通过的代码（用于回滚）
    last_verified_spec: str                # 最近一次 Dafny 验证通过的规约
    regression_rolled_back: bool           # alignment 修复回归后是否已回滚
    candidate_rejected: bool               # 最近候选是否被确定性门槛/单调门槛拒绝
    best_code: str                         # 当前验证质量最好的候选
    best_spec: str                         # best_code 对应的规约
    best_verification: VerificationResult  # best_code 的验证结果
    best_quality: list[int]                # 可序列化的词典序质量分
    stagnation_count: int                  # 连续未改善候选数
    verification_attempts: int             # 实际 Dafny verify 次数
    round: int                             # 当前修复轮次
    max_rounds: int                        # 最大修复轮次
    history: list                          # 修复历史
    research_trace: list                   # 研究追踪：每轮规约、验证、归因、修复动作
    passed: bool                           # 是否最终通过


# ==================== Agent 节点 ====================

def spec_agent(state: PipelineState) -> dict:
    """Agent 1: 从自然语言生成 Dafny 规约"""
    import re
    print(f"\n{'='*50}")
    print(f"[Spec Agent] 正在为 [{state['problem_id']}] 生成规约...")

    llm = spec_llm()

    system_prompt = """你是一个 Dafny 规约专家。
给定问题描述，生成对应的 Dafny 方法签名和完整的形式化规约（requires/ensures）。
只输出规约部分，不要函数体实现。

### 规约强度策略（重要）
- HumanEval 测试只用于最终验证，不能替代规约；题目的核心行为必须出现在 ensures/helper predicate 中。
- 不要只写类型、安全、非负、长度等 shape-only 条件；必须覆盖题意中的顺序、membership、计数、重叠、first/last、最短/最长、忽略分隔符等语义。
- 公共 method 只能使用题目明确给出的输入限制。不得发明会排除公开示例、空输入或其他合法输入的 requires。
- 如果输入中提供“固定 Dafny 签名”，必须逐字保留方法名、参数名/类型和返回名/类型，不得重新推断。
- 复杂语义应拆成少量、全定义的纯 helper function/predicate，避免巨型量词和重复字符级约束。
- 每个 ensures 都应能追溯到题目文本或公开示例，同时保持证明可行。
- 绝对不要在 method 规约后输出方法体；helper function 可以有纯表达式函数体。

### Dafny 规约语法约束（极其重要！）
- `ensures`/`requires` 子句只能包含纯表达式：量词(forall/exists)、算术运算、函数调用、逻辑运算
- **绝对禁止**在 ensures/requires 中使用 `var` 声明或 `;` 分号
- **绝对禁止**在 ensures/requires 中使用 `for`/`while` 循环或命令式语句
- 类型必须匹配：`int` 和 `real` 运算前要显式转换 (`x as real`)
- **real 转 int 必须用 `.Floor` 方法，不能用 `as int`**（Dafny 不允许 real-to-int cast）
- 规约必须简洁：每个 ensures 一行，表达一个明确的后置条件
- 如果需要辅助函数（如 sum），可以定义，但函数体必须是纯表达式
- 不要写很难证明的等价式，如完整的 parser/grouping 语义；优先保证代码可被 Dafny 验证

### Dafny 类型转换速查
- int → real: `x as real`  ✅
- real → int: `x.Floor`  ✅  (不能用 `x as int` ❌)
- real 比较: `a < b`, `a == b`  ✅
- int/real 混合运算: 必须统一类型

### 类型映射
- Python int → Dafny int
- Python float → Dafny real
- Python List[X] → Dafny seq<X>
- Python str → Dafny string
- Python bool → Dafny bool

输出格式（只输出方法签名+规约，不要实现体）：
```dafny
method 方法名(参数) returns (返回值)
    requires ...
    ensures ...
```"""

    MAX_SPEC_RETRIES = 2
    user_message = state['problem_desc']
    for attempt in range(MAX_SPEC_RETRIES + 1):
        spec = llm.chat(
            system=system_prompt,
            user=user_message
        )

        spec_code = _strip_method_bodies_from_spec(_extract_dafny_code(spec))

        # 验证spec语法：先做 regex 过滤，再用 dafny resolve 检查
        spec_ok = True
        try:
            # 步骤1: regex 预过滤 — 检测 ensures/requires 中的非法语法
            # 提取 ensures/requires 部分
            spec_lines = spec_code.split('\n')
            ensures_requires_lines = [l for l in spec_lines if 'ensures' in l or 'requires' in l]
            bad_patterns = [
                (r'\bvar\b\s+\w+\s*:', 'var declaration (var x := ... or var x: ...)'),
                (r'\bfor\b\s+\w+\s*:', 'for loop'),
                (r'\bwhile\b\s+', 'while loop'),
            ]
            for pattern, desc in bad_patterns:
                for line in ensures_requires_lines:
                    if re.search(pattern, line):
                        spec_ok = False
                        print(f"[Spec Agent] 规约包含非法语法: {desc} in '{line.strip()[:100]}...'")
                        break
                if not spec_ok:
                    break

            if spec_ok:
                # 步骤2: dafny resolve 检查语法/类型
                from dafny_wrapper import DafnyVerifier
                v = DafnyVerifier()
                import subprocess, tempfile, os
                with tempfile.NamedTemporaryFile(mode='w', suffix='.dfy', delete=False, encoding='utf-8') as f:
                    f.write(spec_code)
                    tmp_path = f.name
                try:
                    result = subprocess.run(
                        [v.dafny_path, "resolve", "--allow-warnings", tmp_path],
                        capture_output=True, text=True, timeout=15
                    )
                    resolve_output = result.stdout + result.stderr
                    if result.returncode != 0 or 'error' in resolve_output.lower():
                        spec_ok = False
                        error_lines = [l.strip() for l in resolve_output.split('\n') if 'Error' in l][:3]
                        error_msg = "; ".join(error_lines) if error_lines else resolve_output[-300:]
                        print(f"[Spec Agent] resolve 错误: {error_msg[:200]}")
                finally:
                    os.unlink(tmp_path)

            if not spec_ok and attempt < MAX_SPEC_RETRIES:
                print(f"[Spec Agent] 正在重新生成规约 (attempt {attempt+1})...")
                user_message += "\n\n⚠️ 上次生成的规约包含非法Dafny语法。只输出纯方法签名+requires/ensures表达式，禁止var/for/while。"
            elif not spec_ok:
                print(f"[Spec Agent] ⚠️ 规约可能有语法问题，但已达最大重试次数")
        except Exception as e:
            print(f"[Spec Agent] 规约验证异常: {e}")

        if spec_ok or attempt >= MAX_SPEC_RETRIES:
            break

    if not spec_ok:
        print(f"[Spec Agent] ⚠️ 规约可能有语法问题，但已达最大重试次数")

    print(f"[Spec Agent] 生成结果:\n{spec_code[:300]}...")
    metrics = spec_metrics(spec_code)
    adequacy = spec_adequacy_snapshot(
        spec=spec_code,
        problem_desc=state["problem_desc"],
        entry_point=state.get("entry_point", ""),
    )
    print(
        f"[Spec Adequacy] level={adequacy['level']} "
        f"score={adequacy['score']} flags={adequacy['flags'][:3]}"
    )
    event = trace_event(
        "spec",
        state["round"],
        spec_ok=spec_ok,
        metrics=metrics,
        adequacy=adequacy,
    )
    return {
        "spec": spec_code,
        "spec_adequacy": adequacy,
        "research_trace": append_trace(state, event),
    }


def code_agent(state: PipelineState) -> dict:
    """Agent 2: 根据规约生成代码"""
    print(f"\n{'='*50}")
    print(f"[Code Agent] 正在根据规约生成代码...")

    llm = code_llm()

    # Few-shot 示例：Dafny 循环不变量最佳实践
    FEW_SHOT = """
## Dafny 语法基础

### Dafny 类型转换速查
- int → real: `x as real`  ✅
- real → int: `x.Floor`  ✅  (不能用 `x as int` ❌，Dafny 不支持 real-to-int cast)

### ⚠️ function 只能包含表达式，不能有命令式语句！
```dafny
// ✅ 正确：function 用表达式
function sum(s: seq<int>): int {
    if |s| == 0 then 0 else s[0] + sum(s[1..])
}

// ❌ 错误：function 不能用 for/while 循环或 var/:= 赋值
function bad(s: seq<int>): int {
    var total := 0;  // 错误!
    for i := 0 to |s| { total := total + s[i]; }  // 错误!
    total
}
```

### ⚠️ predicate 和 function 一样，只能用表达式
```dafny
// ✅ 正确：predicate 用逻辑表达式
predicate Balanced(s: string) {
    |s| % 2 == 0  // 简化版...
}

// ✅ 如果需要循环，用 method + ghost 或额外的 function
```

### ⚠️ method 才能用命令式语句（var, while, for, if-else 带赋值）
```dafny
// ✅ 正确：method 里可以用循环
method compute(s: seq<int>) returns (total: int) {
    total := 0;
    var i := 0;
    while i < |s| {
        total := total + s[i];
        i := i + 1;
    }
}
```

### ⚠️ real 小数部分提取：用 .Floor 而不是循环
```dafny
// ✅ 正确：简单直接
method truncate_number(number: real) returns (decimal: real)
    requires 0.0 <= number
    ensures 0.0 <= decimal < 1.0
{
    var int_part := number.Floor;
    decimal := number - int_part as real;
}

// ❌ 错误：不要用 while 循环去找整数部分
```

## Dafny 循环不变量最佳实践

### 模式1: 单循环遍历 seq
```dafny
var i := 0;
var acc := initial_value;
while i < |s|
    invariant 0 <= i <= |s|
    invariant acc == f(s[..i])
    decreases |s| - i
{
    acc := acc + s[i];
    i := i + 1;
}
```

### 模式2: 嵌套循环（⭐ 关键模式）

**⚠️ 为什么要加 assert 桥接：**
Dafny 的 SMT solver 不能自动将「内层循环做了什么」传递到外层循环的不变量。
内层循环结束后，必须**手动用 assert 做桥接**。

```dafny
method find_pair(numbers: seq<int>) returns (result: bool)
{
    result := false;
    var i := 0;
    while i < |numbers|
        invariant 0 <= i <= |numbers|
        // 外层: 对所有"第一个元素已处理"的 pair，都不是解
        // ⚠️ j0 范围是 i0 < j0 < |numbers|（全数组），不是 j0 < i
        invariant !result ==> forall i0, j0 :: 0 <= i0 < i && i0 < j0 < |numbers| ==> !P(numbers[i0], numbers[j0])
        invariant result ==> exists i0, j0 :: 0 <= i0 < j0 < |numbers| && P(numbers[i0], numbers[j0])
        decreases |numbers| - i
    {
        var j := i + 1;
        while j < |numbers|
            invariant i < j <= |numbers|
            invariant !result ==> forall j0 :: i < j0 < j ==> !P(numbers[i], numbers[j0])
            invariant result ==> exists i0, j0 :: 0 <= i0 < j0 < |numbers| && P(numbers[i0], numbers[j0])
            decreases |numbers| - j
        {
            if P(numbers[i], numbers[j]) {
                result := true;
                return;
            }
            j := j + 1;
        }
        // ⭐ 重要：内层结束后必须加 assert 桥接！
        // 把内层循环证明的结论 explicitly 告诉外层
        assert !result ==> forall j0 :: i < j0 < |numbers| ==> !P(numbers[i], numbers[j0]);
        i := i + 1;
    }
}
```

### ⚡ 嵌套循环 invariant 设计规则
- **外层 invariant**: `forall i0, j0 :: 0 <= i0 < i && i0 < j0 < |seq| ==> !P(...)`
  含义: 对所有已处理的第一元素 i0，所有可能的第二元素 j0(>i0) 都检查过
  ⚠️ **j0 范围是 `i0 < j0 < |seq|`（全数组），不是 `j0 < i`**
- **内层 invariant**: `forall j0 :: i < j0 < j ==> !P(seq[i], seq[j0])`
  含义: 当前外层元素 i，已检查到位置 j
- **桥接 assert**: 内层循环结束、`i := i + 1` 之前，显式声明所有 j0 都不是解
- **early return**: 循环内 `return` 时，需要 invariant 保证 postcondition 成立

### ⚡ 嵌套循环代码生成检查清单
生成包含嵌套循环的代码时，**必须逐条检查**：
- [ ] 外层 invariant: `0 <= i0 < i && i0 < j0 < |seq|`（不是 `j0 < i`!）
- [ ] 内层 invariant: `i < j0 < j` 覆盖了当前 i 搜索的范围
- [ ] **内层循环后 assert 桥接，且在 i := i + 1 之前**
- [ ] decreases 子句存在
- [ ] result 两种状态（true/false）都有对应的 invariant
"""

    prompt = f"""{FEW_SHOT}

---

问题描述：
{state['problem_desc']}

形式化规约：
{state['spec']}

请根据上面的 Dafny 模式，生成满足规约的完整 Dafny 实现代码。

### ⚡ 代码生成时必须逐条检查：
1. □ 单循环 → 写 invariant 表达「已遍历范围的累计结果」
2. □ 嵌套循环 → **严格按照模式2**：内层循环后必须加 `assert` 桥接！
3. □ invariant 覆盖 result=true 和 result=false 两种情况
4. □ 所有 while 循环都有 decreases 子句
5. □ 确保代码能通过 Dafny 验证器验证
6. □ 不要修改/删除公共 method 的 requires/ensures；代码必须绑定给定规约
7. □ 对 string/seq 构造题，使用与规约 helper 对齐的循环 invariant 或递归结构，而不是把语义留给测试

只输出完整的 Dafny 代码（包含辅助函数）。"""

    code = ""
    code_prompt = prompt
    for attempt in range(3):
        raw_code = llm.chat(
            system="你是 Dafny 代码生成专家。严格遵循 Dafny 语法：function/predicate 只能包含表达式，命令式逻辑只能放在 method 中。",
            user=code_prompt
        )
        code = _inject_nested_loop_assert(_extract_dafny_code(raw_code))
        issues = _candidate_code_issues(
            state.get("spec", ""),
            code,
            state.get("entry_point", ""),
            run_resolve=True,
        )
        if not issues:
            break
        print(f"[Code Agent] 静态预检发现问题: {issues[:3]}")
        if attempt == 2:
            break
        code_prompt = f"""{prompt}

### 上一次代码被静态预检拒绝
{chr(10).join('- ' + issue for issue in issues)}

请重新生成完整 Dafny 代码。不要在 function/predicate 中使用 var、:=、while、for；需要循环时改成 method 内部局部逻辑，或用纯递归 function。"""
        code_prompt += "\nhelper 的 requires 必须是必要且可由所有调用点证明的；优先把 helper 定义成全函数。不要发明与题意无关的复杂语义 helper。"

    print(f"[Code Agent] 生成代码:\n{code[:300]}...")
    final_issues = _candidate_code_issues(
        state.get("spec", ""),
        code,
        state.get("entry_point", ""),
    )
    event = trace_event(
        "code",
        state["round"],
        static_issue_count=len(_static_code_issues(code)),
        contract_issue_count=sum(
            issue.startswith("public contract mismatch:") for issue in final_issues
        ),
        code_line_count=len([line for line in code.splitlines() if line.strip()]),
    )
    return {"code": code, "research_trace": append_trace(state, event)}


def spec_repair_agent(state: PipelineState) -> dict:
    """Agent 1.5: 根据规约充分性报告加强规约。"""
    print(f"\n{'='*50}")
    print("[Spec Repair Agent] 检查是否需要加强规约...")

    adequacy = state.get("spec_adequacy", {})
    if not should_repair_spec(adequacy):
        print("[Spec Repair Agent] 跳过：当前规约充分性风险未达到修复阈值，或开关未启用")
        event = trace_event(
            "spec_repair",
            state["round"],
            action="skipped",
            adequacy=adequacy,
        )
        return {"research_trace": append_trace(state, event)}

    print(
        f"[Spec Repair Agent] 触发：level={adequacy.get('level')} "
        f"score={adequacy.get('score')} flags={(adequacy.get('flags') or [])[:3]}"
    )
    llm = spec_llm()
    result = repair_spec_with_llm(
        llm=llm,
        problem_desc=state["problem_desc"],
        spec=state["spec"],
        adequacy=adequacy,
    )

    action = "repaired" if result["repaired"] else "fallback_original"
    if result["repaired"]:
        print(f"[Spec Repair Agent] 修复成功，新规约:\n{result['spec'][:300]}...")
    else:
        print(f"[Spec Repair Agent] 修复失败，沿用原规约: {result.get('error', '')[:200]}")

    event = trace_event(
        "spec_repair",
        state["round"],
        action=action,
        attempts=result.get("attempts", 0),
        error=result.get("error", ""),
        before_adequacy=adequacy,
        after_adequacy=result.get("adequacy", adequacy),
    )
    return {
        "spec": result["spec"],
        "spec_adequacy": result.get("adequacy", adequacy),
        "research_trace": append_trace(state, event),
    }


def mutation_adequacy_node(state: PipelineState) -> dict:
    """Lightweight in-loop mutation adequacy probe for the current spec."""
    print(f"\n{'='*50}")
    print("[Mutation Adequacy] 正在探测规约是否能排除简单错误实现...")

    if not config.ENABLE_INLOOP_MUTATION_ADEQUACY:
        print("[Mutation Adequacy] 已禁用")
        event = trace_event("mutation_adequacy", state["round"], action="skipped")
        return {"research_trace": append_trace(state, event)}

    try:
        report = probe_spec_mutants(state.get("spec", ""))
    except Exception as exc:
        print(f"[Mutation Adequacy] 探测失败: {exc}")
        event = trace_event("mutation_adequacy", state["round"], action="error", error=str(exc))
        return {"mutation_adequacy": {"error": str(exc)}, "research_trace": append_trace(state, event)}

    risk = report.get("mutation_adequacy_risk", "not_applicable")
    verified = report.get("mutants_verified", 0)
    total = report.get("mutants_total", 0)
    print(f"[Mutation Adequacy] risk={risk} verified_mutants={verified}/{total}")

    adequacy = dict(state.get("spec_adequacy", {}))
    flags = set(adequacy.get("flags") or [])
    missing = list(adequacy.get("missing_obligations") or [])
    if verified:
        flags.add("mutation_verified_mutant")
        missing.append("Strengthen the spec so simple default/parameter-return mutants cannot verify.")
        adequacy["score"] = max(0, int(adequacy.get("score", 100)) - 15)
        adequacy["level"] = "partial" if adequacy.get("level") == "strong_static" else adequacy.get("level", "partial")
    adequacy["flags"] = sorted(flags)
    adequacy["missing_obligations"] = missing

    event = trace_event(
        "mutation_adequacy",
        state["round"],
        action="probed",
        report={k: v for k, v in report.items() if k != "mutants"},
        verified_mutant_names=[m["name"] for m in report.get("mutants", []) if m.get("dafny_verified")],
    )
    return {
        "mutation_adequacy": report,
        "spec_adequacy": adequacy,
        "research_trace": append_trace(state, event),
    }


def spec_strengthening_agent(state: PipelineState) -> dict:
    """Strengthen specs when mutation probing finds verified wrong-looking mutants."""
    print(f"\n{'='*50}")
    print("[Spec Strengthening Agent] mutation 信号触发，尝试加强规约...")

    if not config.ENABLE_MUTATION_SPEC_STRENGTHENING:
        print("[Spec Strengthening Agent] 已禁用")
        event = trace_event("spec_strengthening", state["round"], action="skipped")
        return {"research_trace": append_trace(state, event)}

    adequacy = state.get("spec_adequacy", {})
    llm = spec_llm()
    result = repair_spec_with_llm(
        llm=llm,
        problem_desc=state["problem_desc"],
        spec=state["spec"],
        adequacy=adequacy,
    )

    action = "strengthened" if result.get("repaired") else "fallback_original"
    if result.get("repaired"):
        print(f"[Spec Strengthening Agent] 加强成功:\n{result['spec'][:300]}...")
    else:
        print(f"[Spec Strengthening Agent] 加强失败，沿用原规约: {result.get('error', '')[:200]}")

    event = trace_event(
        "spec_strengthening",
        state["round"],
        action=action,
        before_mutation_adequacy=state.get("mutation_adequacy", {}),
        before_adequacy=adequacy,
        after_adequacy=result.get("adequacy", adequacy),
        attempts=result.get("attempts", 0),
        error=result.get("error", ""),
    )
    return {
        "spec": result.get("spec", state.get("spec", "")),
        "spec_adequacy": result.get("adequacy", adequacy),
        "research_trace": append_trace(state, event),
    }


def _verification_quality(result: VerificationResult) -> tuple[int, int, int]:
    """Lexicographic quality used to prevent repair regressions."""
    if result.passed:
        return (4, result.verified_count, 0)
    error_types = {error.error_type for error in result.errors}
    if "timeout" in error_types:
        return (0, result.verified_count, -max(1, result.error_count))
    language_errors = {"syntax", "type", "undefined", "assignment"}
    if error_types & language_errors:
        return (1, result.verified_count, -max(1, result.error_count))
    return (2, result.verified_count, -max(1, result.error_count))


def _verification_fingerprint(result: VerificationResult) -> str:
    return "|".join(
        f"{error.error_type}:{error.location_line}:{getattr(error, 'subtype', '')}"
        for error in result.errors
    )


def verify_node(state: PipelineState) -> dict:
    """Node: Dafny 验证器"""
    print(f"\n{'='*50}")
    print(f"[Verify] Round {state['round']}: 正在验证...")

    candidate_code = state['code']
    candidate_spec = state.get('spec', '')
    contract_issues = contract_fidelity_issues(
        candidate_spec,
        candidate_code,
        state.get("entry_point", ""),
    )
    if contract_issues:
        result = VerificationResult(
            passed=False,
            errors=[
                ErrorInfo(
                    error_type="contract",
                    subtype="contract_mismatch",
                    message=issue,
                )
                for issue in contract_issues
            ],
            error_count=len(contract_issues),
            raw_output="\n".join(contract_issues),
        )
        print(f"[Verify] 公共契约门槛拒绝候选: {contract_issues[:3]}")
    else:
        verifier = DafnyVerifier()
        result = verifier.verify(candidate_code)

    print(f"[Verify] 通过={result.passed}  verified={result.verified_count}  errors={result.error_count}")
    if not result.passed:
        for e in result.errors[:3]:
            print(f"  -> [{e.error_type}] L{e.location_line}: {e.message[:100]}")

    candidate_attribution = attribute_failure(result, candidate_spec, candidate_code)
    quality = _verification_quality(result)
    best_quality = tuple(state.get("best_quality") or [])
    has_best = bool(state.get("best_code")) and bool(best_quality)
    rejected = False

    # Never let a failed repair replace a strictly better finite candidate.
    # Verified candidates remain eligible because behavior alignment may improve
    # semantics while keeping the same verifier score.
    if has_best and not result.passed and quality <= best_quality:
        rejected = True
        chosen_result = state.get("best_verification", result)
        chosen_code = state.get("best_code", candidate_code)
        chosen_spec = state.get("best_spec", candidate_spec)
        attribution = attribute_failure(chosen_result, chosen_spec, chosen_code)
        stagnation_count = state.get("stagnation_count", 0) + 1
        print(
            f"[Verify] 候选未改善 quality={quality} best={best_quality}，"
            "回滚到 best-so-far"
        )
    else:
        chosen_result = result
        chosen_code = candidate_code
        chosen_spec = candidate_spec
        attribution = candidate_attribution
        stagnation_count = 0

    print(f"[Verify] 归因={attribution['category']}  修复目标={attribution['repair_target']}")
    event = trace_event(
        "verify",
        state["round"],
        verification=verification_snapshot(chosen_result),
        attribution=attribution,
        candidate_verification=verification_snapshot(result),
        candidate_quality=list(quality),
        candidate_rejected=rejected,
        rollback_reason="non_monotonic_verification" if rejected else "",
    )
    update = {
        "code": chosen_code,
        "spec": chosen_spec,
        "verification": chosen_result,
        "dafny_verified": chosen_result.passed,
        "passed": chosen_result.passed and not bool(state.get("behavior_problem")),
        "last_attribution": attribution,
        "candidate_rejected": rejected,
        "stagnation_count": stagnation_count,
        "verification_attempts": state.get("verification_attempts", 0) + 1,
        "research_trace": append_trace(state, event),
    }
    if not rejected:
        update.update({
            "best_code": candidate_code,
            "best_spec": candidate_spec,
            "best_verification": result,
            "best_quality": list(quality),
        })
    # Dafny 验证通过时快照当前代码/规约，供 alignment_repair 回归时回滚
    if chosen_result.passed:
        update["last_verified_code"] = chosen_code
        update["last_verified_spec"] = chosen_spec
    return update


def behavior_test_node(state: PipelineState) -> dict:
    """Run behavioral tests after Dafny verification succeeds."""
    print(f"\n{'='*50}")
    print("[Behavior Test] Dafny 已通过，正在运行行为测试...")

    problem = state.get("behavior_problem") or {}
    if not problem or not config.ENABLE_BEHAVIOR_REPAIR_LOOP:
        print("[Behavior Test] 无可用行为测试，按 Dafny 验证结果结束")
        event = trace_event(
            "behavior_test",
            state["round"],
            action="skipped",
            reason="no_behavior_problem_or_disabled",
        )
        return {
            "behavior_executed": False,
            "behavior_passed": False,
            "passed": state.get("verification", VerificationResult()).passed,
            "research_trace": append_trace(state, event),
        }

    try:
        from humaneval_tester import run_humaneval_test

        behavior_passed, detail = run_humaneval_test(state.get("code", ""), problem)
    except Exception as exc:
        behavior_passed = False
        detail = {"error": f"测试执行异常: {type(exc).__name__}: {exc}"}

    error = detail.get("error") or ""
    spec_adequacy = spec_adequacy_snapshot(
        spec=state.get("spec", ""),
        problem_desc=state.get("problem_desc", ""),
        entry_point=state.get("entry_point", ""),
        dafny_verified=True,
        humaneval_passed=behavior_passed,
    )

    if behavior_passed:
        print("[Behavior Test] PASS")
        attribution = {
            "category": "verified_and_behavior_passed",
            "repair_target": "none",
            "confidence": 1.0,
            "rationale": "Dafny verification and behavioral tests both passed.",
        }
    else:
        print(f"[Behavior Test] FAIL: {error[:180]}")
        attribution = {
            "category": "verified_but_behavior_failed",
            "repair_target": "spec_or_code_alignment",
            "confidence": 0.9,
            "rationale": "The implementation satisfies the current spec but fails behavioral tests.",
        }

    event = trace_event(
        "behavior_test",
        state["round"],
        action="tested",
        behavior_passed=behavior_passed,
        error=error,
        adequacy=spec_adequacy,
        attribution=attribution,
    )
    return {
        "behavior_executed": True,
        "behavior_passed": behavior_passed,
        "behavior_error": error,
        "behavior_detail": detail,
        "passed": bool(behavior_passed),
        "spec_adequacy": spec_adequacy,
        "last_attribution": attribution,
        "research_trace": append_trace(state, event),
    }


def diagnose_agent(state: PipelineState) -> dict:
    """Agent 3: 诊断验证错误，生成结构化修复指导"""
    print(f"\n{'='*50}")
    print(f"[Diagnose Agent] 正在分析错误...")

    result = state['verification']

    # 构建结构化错误摘要（按类型分组）
    invariant_errors = []
    syntax_errors = []
    type_errors = []
    other_errors = []
    for e in result.errors:
        if e.error_type == "invariant":
            invariant_errors.append(e)
        elif e.error_type == "syntax":
            syntax_errors.append(e)
        elif e.error_type == "type":
            type_errors.append(e)
        else:
            other_errors.append(e)

    error_summary = ""
    for i, e in enumerate(result.errors):
        subtype = getattr(e, "subtype", "") or e.error_type
        error_summary += f"\n错误 {i+1}: [{subtype}] 第{e.location_line}行\n"
        error_summary += f"  信息: {e.message}\n"
        if getattr(e, "source", ""):
            error_summary += f"  源码: {e.source}\n"
        if e.related_spec:
            error_summary += f"  关联规约: {e.related_spec}\n"

    # 专项诊断指引
    invariant_guide = ""
    syntax_guide = ""
    type_guide = ""

    if invariant_errors:
        invariant_guide = """
### 循环不变量常见修复策略
- entry failure：当前 invariant 在循环开始前为假，应修正初始化或删除/弱化错误 invariant；增加更多合取条件不会修好 entry failure
- maintenance failure：定位哪条赋值破坏了 invariant，再补充描述已处理前缀/未变化状态的关系或桥接 assert
- 常见解法：在invariant中加入循环体实际做了什么 = 这轮改变了什么 + 什么没变
- 例：如果循环累加 `acc := acc + s[i]`，invariant 必须包含 `acc == Sum(s[..i])`
- 例：嵌套循环中，外层 invariant 的 j0 范围必须是 `i0 < j0 < |seq|`（全数组），不是 `j0 < i`
- 也可以添加 `assert` 语句来帮助 Dafny 理解中间状态
"""
    if syntax_errors:
        syntax_guide = """
### 语法错误修复策略
- Dafny 的 predicate 必须是纯函数式的，不能使用 `:=` 赋值或循环
- 检查是否有 `forall` 内的赋值语句，应改用函数式表达
- 检查括号配对、分号、花括号是否匹配
- 检查 `SeqToString`、`as string` 等类型转换语法是否正确
"""
    if type_errors:
        type_guide = """
### 类型错误修复策略
        - Dafny 是强类型语言，`int` 和 `real` 不能混用；int→real 用 `as real`，real→int 不能用 `as int`，需要按题意使用 `.Floor`
- `seq<string>` 和 `string` 是不同的类型——string 可以当 seq<char> 用，但不能当 seq<string>
- 注意 `Floor` 是 `real` 的方法，返回 `int`
"""

    llm = code_llm()
    diagnosis = llm.chat(
        system=f"""你是 Dafny 代码的调试专家。
分析验证错误，给出具体的修复指引：
1. 错误发生在哪里（定位）
2. 错误的原因是什么
3. 用什么策略修复
{invariant_guide}
{syntax_guide}
{type_guide}

输出格式：
```
定位: ...
原因: ...
修复策略: ...
```""",
        user=f"""代码:
{state['code']}

验证错误:
{error_summary}

请分析错误原因并给出修复建议。如果是不变量问题，请给出具体的「缺失条件」。"""
    )

    # 把诊断信息附加到历史
    history = state.get('history', [])
    history.append({
        "round": state['round'],
        "code": state['code'],
        "errors": [{
            "type": e.error_type,
            "subtype": getattr(e, "subtype", ""),
            "loc": e.location_line,
            "msg": e.message,
            "source": getattr(e, "source", ""),
            "related": e.related_spec,
        } for e in result.errors],
        "attribution": state.get("last_attribution", {}),
        "diagnosis": diagnosis
    })

    print(f"[Diagnose Agent] 诊断:\n{diagnosis[:200]}...")
    decision = choose_repair_policy(
        verification=result,
        attribution=state.get("last_attribution", {}),
        spec_adequacy=state.get("spec_adequacy", {}),
        history=history,
    ).to_dict()
    print(f"[Repair Policy] agent={decision['agent']} target={decision['target']} confidence={decision['confidence']}")
    event = trace_event(
        "diagnose",
        state["round"],
        attribution=state.get("last_attribution", {}),
        diagnosis_preview=diagnosis[:500],
        repair_policy=decision,
    )
    return {
        "diagnosis": diagnosis,
        "history": history,
        "repair_policy": decision,
        "research_trace": append_trace(state, event),
    }


def proof_repair_agent(state: PipelineState) -> dict:
    """Agent 4a: 专门修复 Dafny 证明义务，不主动削弱规约。"""
    print(f"\n{'='*50}")
    print(f"[Proof Repair Agent] Round {state['round']}: 正在修复 proof obligations...")

    if not config.ENABLE_PROOF_REPAIR:
        print("[Proof Repair Agent] 已禁用，回退到通用代码修复")
        return repair_agent(state)

    history = state.get("history", [])
    history_text = ""
    for h in history[-3:]:
        history_text += f"\n--- 第{h.get('round')}轮 ---\n"
        for e in h.get("errors", []):
            history_text += f"  [{e.get('type')}] L{e.get('loc', 0)}: {e.get('msg', '')}\n"

    verification_errors = history[-1].get("errors", []) if history else []
    llm = repair_llm()
    raw_code = repair_proof_with_llm(
        llm=llm,
        problem_desc=state["problem_desc"],
        spec=state["spec"],
        code=state["code"],
        diagnosis=state.get("diagnosis", ""),
        verification_errors=verification_errors,
        history_text=history_text,
    )

    new_code = _inject_nested_loop_assert(extract_proof_dafny_code(raw_code))
    missing_contract = _missing_original_contract_clauses(state.get("spec", ""), new_code)
    if missing_contract:
        print(f"[Proof Repair Agent] 检测到公共契约漂移，回退到受契约保护的通用修复: {missing_contract[:2]}")
        event = trace_event(
            "proof_repair",
            state["round"],
            action="contract_preservation_failed",
            missing_contract_clauses=missing_contract[:5],
            repair_policy=state.get("repair_policy", {}),
        )
        intermediate_state = dict(state)
        intermediate_state["research_trace"] = append_trace(state, event)
        return repair_agent(intermediate_state)

    issues = _candidate_code_issues(
        state.get("spec", ""),
        new_code,
        state.get("entry_point", ""),
        run_resolve=True,
    )
    if issues:
        print(f"[Proof Repair Agent] 静态预检发现问题，回退到通用代码修复: {issues[:3]}")
        event = trace_event(
            "proof_repair",
            state["round"],
            action="fallback_to_code_repair",
            static_issues=issues[:5],
            repair_policy=state.get("repair_policy", {}),
        )
        intermediate_state = dict(state)
        intermediate_state["research_trace"] = append_trace(state, event)
        return repair_agent(intermediate_state)

    print(f"[Proof Repair Agent] 修复后代码:\n{new_code[:300]}...")
    event = trace_event(
        "proof_repair",
        state["round"],
        action="proof_repaired",
        repair_policy=state.get("repair_policy", {}),
        new_code_line_count=len([line for line in new_code.splitlines() if line.strip()]),
        static_issue_count=len(issues),
    )
    return {
        "code": new_code,
        "candidate_rejected": False,
        "round": state["round"] + 1,
        "research_trace": append_trace(state, event),
    }


def alignment_repair_agent(state: PipelineState) -> dict:
    """Repair verified-but-behavior-failed cases by aligning spec and code."""
    print(f"\n{'='*50}")
    print(f"[Alignment Repair Agent] Round {state['round']}: 正在对齐规约、代码和行为测试...")

    history = state.get("history", [])
    history.append({
        "round": state["round"],
        "code": state.get("code", ""),
        "errors": [{
            "type": "behavior",
            "loc": 0,
            "msg": state.get("behavior_error", ""),
        }],
        "attribution": state.get("last_attribution", {}),
        "diagnosis": "Dafny verified the code, but behavioral tests failed.",
    })

    history_text = ""
    for h in history[-3:]:
        history_text += f"\n--- 第{h.get('round')}轮 ---\n"
        for e in h.get("errors", []):
            history_text += f"  [{e.get('type')}] {e.get('msg', '')}\n"

    # 把结构化失败诊断拼进 behavior_error，让 LLM 看到具体输入/期望/实际而非空 AssertionError
    detail = state.get("behavior_detail") or {}
    diag_text = state.get("behavior_error", "")
    fi = detail.get("failing_input")
    if fi is not None:
        diag_text = (diag_text + "\n" if diag_text else "") + (
            f"首个失败用例: 输入={fi!r} 期望={detail.get('expected')!r} 实际={detail.get('actual')!r}"
        )

    llm = repair_llm()
    raw_code = repair_alignment_with_llm(
        llm=llm,
        problem_desc=state["problem_desc"],
        spec=state.get("spec", ""),
        code=state.get("code", ""),
        behavior_error=diag_text,
        adequacy=state.get("spec_adequacy", {}),
        history_text=history_text,
    )
    new_code = _inject_nested_loop_assert(extract_alignment_dafny_code(raw_code))
    issues = _static_code_issues(new_code)

    new_spec = _extract_spec_from_code(new_code)
    new_adequacy = spec_adequacy_snapshot(
        spec=new_spec,
        problem_desc=state.get("problem_desc", ""),
        entry_point=state.get("entry_point", ""),
    )

    # 守卫1：放宽规约不能退化成不约束 result 的 vacuous 规约
    rolled_back = False
    rollback_reason = ""
    if new_spec and _is_vacuous_spec(new_spec, new_adequacy):
        rolled_back = True
        rollback_reason = "vacuous_spec"
        print("[Alignment Repair Agent] 修复后规约 vacuous（不约束 result），回滚到上一版已验证规约")

    # 守卫2：alignment 修复后的代码必须仍能通过 Dafny，否则回滚（避免改坏已验证代码，命中 /12 类回归）
    if not rolled_back:
        verifier = DafnyVerifier()
        precheck = verifier.verify(new_code)
        if not precheck.passed:
            rolled_back = True
            rollback_reason = "verification_regression"
            err_preview = "; ".join(
                f"[{e.error_type}] L{e.location_line}: {e.message[:60]}"
                for e in precheck.errors[:3]
            )
            print(f"[Alignment Repair Agent] 修复后代码 Dafny 验证失败，回滚到上一版已验证代码: {err_preview[:160]}")

    if rolled_back:
        restored_code = state.get("last_verified_code") or state.get("code", "")
        restored_spec = state.get("last_verified_spec") or state.get("spec", "")
        event = trace_event(
            "alignment_repair",
            state["round"],
            action="regression_rolled_back",
            rollback_reason=rollback_reason,
            previous_behavior_error=state.get("behavior_error", ""),
            rejected_code_line_count=len([l for l in new_code.splitlines() if l.strip()]),
        )
        return {
            "code": restored_code,
            "spec": restored_spec,
            "spec_adequacy": state.get("spec_adequacy", {}),
            "history": history,
            "regression_rolled_back": True,
            "candidate_rejected": True,
            "behavior_passed": False,
            "behavior_error": state.get("behavior_error", ""),
            "passed": False,
            "round": state["round"] + 1,
            "research_trace": append_trace(state, event),
        }

    print(f"[Alignment Repair Agent] 修复后代码:\n{new_code[:300]}...")
    event = trace_event(
        "alignment_repair",
        state["round"],
        action="spec_code_alignment",
        previous_behavior_error=state.get("behavior_error", ""),
        previous_adequacy=state.get("spec_adequacy", {}),
        new_adequacy=new_adequacy,
        spec_changed=new_spec != state.get("spec", ""),
        static_issue_count=len(issues),
        new_code_line_count=len([line for line in new_code.splitlines() if line.strip()]),
    )
    return {
        "code": new_code,
        "spec": new_spec or state.get("spec", ""),
        "spec_adequacy": new_adequacy if new_spec else state.get("spec_adequacy", {}),
        "history": history,
        "candidate_rejected": False,
        "behavior_passed": False,
        "behavior_error": "",
        "passed": False,
        "round": state["round"] + 1,
        "research_trace": append_trace(state, event),
    }


def repair_agent(state: PipelineState) -> dict:
    """Agent 4: 根据诊断修复代码"""
    print(f"\n{'='*50}")
    print(f"[Repair Agent] Round {state['round']}: 正在修复...")

    history = state.get('history', [])
    history_text = ""
    for h in history:
        history_text += f"\n--- 第{h['round']}轮 ---\n"
        for e in h.get('errors', []):
            history_text += f"  [{e['type']}] L{e.get('loc',0)}: {e.get('msg','')}\n"

    # 检查上一轮的问题类型，标记本轮修复重点
    last_errors = history[-1]["errors"] if history else []
    has_invariant_issue = any(e["type"] == "invariant" for e in last_errors)
    has_syntax_issue = any(e["type"] == "syntax" for e in last_errors)
    has_type_issue = any(e["type"] == "type" for e in last_errors)

    tips = []
    if has_invariant_issue:
        tips.append("""
⚠️ 上一轮有不变量问题！以下策略优先：
1. 检查 invariant 是否足够强——必须精确描述循环体在每个迭代做了什么
2. 加 assert: 内层循环结束后，加 `assert` 显式声明内层执行的结果（这是关键！Dafny solver 需要这个桥接）
3. 不要只改 invariant 本身，检查是否需要增加中间变量来帮助 Dafny 理解
4. 嵌套循环中，外层 invariant 中 j0 的范围必须是 `i0 < j0 < |seq|` 而不是 `j0 < i`
5. 如果可能，简化循环逻辑（单循环比嵌套循环更容易证明）
""")
    if has_syntax_issue:
        tips.append("""
⚠️ 上一轮有语法错误！修复时注意：
1. Dafny predicate/function 必须是纯函数式的，不能用 `:=` 赋值
2. 不能用 `while` 循环，只能用递归或 `forall`
3. `forall` body 中不能有命令式语句，只能用逻辑表达式
4. 检查 Dafny 语法：分号只在方法体中需要，predicate/function 不需要
""")
    if has_type_issue:
        tips.append("""
⚠️ 上一轮有类型错误！修复时注意：
        1. `int` 和 `real` 运算前需要显式转换；int→real 用 `x as real`，real→int 禁止 `x as int`，需要按题意使用 `x.Floor`
2. `string` 可以用切片 `s[i..j]` 得到 `string`，不是 `seq<char>`
3. Dafny 没有隐式类型转换，所有类型必须匹配
""")
    tip_text = "\n".join(tips)

    # 检测重复错误：相同错误类型+位置出现 2+ 次，强制换策略
    repeated_errors = []
    if len(history) >= 2:
        for round_idx in range(len(history)):
            for e in history[round_idx].get("errors", []):
                ekey = (e["type"], e.get("loc", 0))
                count = sum(1 for h in history for he in h.get("errors", []) if (he["type"], he.get("loc", 0)) == ekey)
                if count >= 2 and ekey not in repeated_errors:
                    repeated_errors.append(ekey)
    if repeated_errors:
        repeated_text = "\n".join(f"  - [{t}] at line {loc}" for t, loc in repeated_errors)
        tip_text += f"""
🔄 以下错误已重复出现 2+ 次，必须换策略！
{repeated_text}
请考虑完全不同的实现方式：
- 如果是 function 里有 for/while 错误 → 改用 method 实现
- 如果是 invariant 维持不住 → 尝试完全不同的循环结构或分解问题
- 如果是类型错误 → 检查是否可以用不同的数据类型方案
- **绝对不要输出与上一轮基本相同的代码！**"""

    llm = repair_llm()
    prompt = f"""问题描述：
{state['problem_desc']}

规约：
{state['spec']}

当前代码：
{state['code']}

验证错误诊断：
{state.get('diagnosis', '')}

历史修复尝试（避免重复错误）：
{history_text}{tip_text}

请基于以上信息，给出修复后的完整 Dafny 代码。
只输出最终的 Dafny 代码。"""

    new_code = llm.chat(
        system=f"""你是 Dafny 代码修复专家。
根据验证器的反馈，精确定位并修复代码中的错误。{tip_text}

注意：
- 不要改动已经正确的部分
- 确保修复后仍然满足原始规约
- 如果上一轮是相同错误，这轮必须尝试不同的修复策略
- 语法/类型错误优先使用简单直接的修复，不要过度设计
- 只输出完整的 Dafny 代码""",
        user=prompt
    )

    new_code = _inject_nested_loop_assert(_extract_dafny_code(new_code))
    issues = _candidate_code_issues(
        state.get("spec", ""),
        new_code,
        state.get("entry_point", ""),
        run_resolve=True,
    )
    if issues:
        print(f"[Repair Agent] 确定性预检发现问题，要求重写: {issues[:3]}")
        retry_prompt = f"""{prompt}

### 你刚才输出的修复代码仍有静态错误
{chr(10).join('- ' + issue for issue in issues)}

请换一种实现方式，输出完整 Dafny 代码。function/predicate 中绝对不能出现 var、:=、while、for。"""
        retry_prompt += "\nhelper 的 requires 只有在确有必要且所有调用点都能证明时才保留；也可以把 helper 改写为对全部输入有定义的全函数。"
        new_code = llm.chat(
            system="你是 Dafny 代码修复专家。优先修复语法层面的非法命令式 function/predicate。",
            user=retry_prompt
        )
        new_code = _inject_nested_loop_assert(_extract_dafny_code(new_code))

    issues = _candidate_code_issues(
        state.get("spec", ""),
        new_code,
        state.get("entry_point", ""),
        run_resolve=True,
    )
    if issues:
        print(f"[Repair Agent] 候选仍不满足代码/契约门槛，保留上一版: {issues[:3]}")
        event = trace_event(
            "repair",
            state["round"],
            action="candidate_rejected",
            deterministic_issues=issues[:8],
            previous_attribution=state.get("last_attribution", {}),
        )
        return {
            "code": state.get("code", ""),
            "candidate_rejected": True,
            "round": state["round"] + 1,
            "research_trace": append_trace(state, event),
        }

    print(f"[Repair Agent] 修复后代码:\n{new_code[:300]}...")
    event = trace_event(
        "repair",
        state["round"],
        action="candidate_accepted_for_verification",
        previous_attribution=state.get("last_attribution", {}),
        new_code_line_count=len([line for line in new_code.splitlines() if line.strip()]),
        static_issue_count=len(_static_code_issues(new_code)),
    )
    return {
        "code": new_code,
        "candidate_rejected": False,
        "round": state["round"] + 1,
        "research_trace": append_trace(state, event),
    }


# ==================== 条件路由 ====================

def decide_after_mutation(state: PipelineState) -> Literal["strengthen_spec", "code"]:
    """Route specs with verified mutants to a strengthening pass."""
    report = state.get("mutation_adequacy", {})
    if (
        config.ENABLE_MUTATION_SPEC_STRENGTHENING
        and report.get("mutants_verified", 0) > 0
    ):
        print("[Router] mutation 探测发现 verified mutant，路由到 Spec Strengthening")
        return "strengthen_spec"
    return "code"


def decide_after_verify(state: PipelineState) -> Literal["behavior_test", "end", "repair"]:
    """Route after Dafny verification."""
    verification = state.get("verification", VerificationResult())
    if verification.passed and state.get("behavior_problem") and config.ENABLE_BEHAVIOR_REPAIR_LOOP:
        print("[Router] Dafny 验证通过，继续行为测试")
        return "behavior_test"
    if verification.passed:
        print(f"[Router] 验证通过! ✅")
        return "end"
    if state['round'] >= state['max_rounds']:
        print(f"[Router] 达到最大轮次 {state['max_rounds']}，停止")
        return "end"
    print(f"[Router] 继续修复 (round {state['round']}/{state['max_rounds']})")
    return "repair"


def decide_after_behavior(state: PipelineState) -> Literal["end", "alignment_repair"]:
    """Route behavior-test failures into spec/code alignment repair."""
    if state.get("regression_rolled_back"):
        print("[Router] alignment 修复回归已回滚，保留已验证状态结束")
        return "end"
    if state.get("behavior_passed"):
        print("[Router] 行为测试通过，结束")
        return "end"
    if state["round"] >= state["max_rounds"]:
        print(f"[Router] 行为测试失败但已达到最大轮次 {state['max_rounds']}，停止")
        return "end"
    print("[Router] Dafny 通过但行为失败，路由到 Alignment Repair Agent")
    return "alignment_repair"


def decide_repair_route(state: PipelineState) -> Literal["proof_repair", "code_repair"]:
    """Route repair to the specialized agent chosen by Repair Policy."""
    decision = state.get("repair_policy", {})
    if decision.get("agent") == "proof_repair_agent":
        print("[Router] 路由到 Proof Repair Agent")
        return "proof_repair"
    print("[Router] 路由到 Code Repair Agent")
    return "code_repair"


# ==================== Graph 构建 ====================

def build_pipeline():
    """构建 LangGraph Pipeline"""
    from langgraph.graph import StateGraph, END

    builder = StateGraph(PipelineState)

    # 添加节点
    builder.add_node("spec_agent", spec_agent)
    builder.add_node("spec_repair", spec_repair_agent)
    builder.add_node("mutation_adequacy", mutation_adequacy_node)
    builder.add_node("spec_strengthening", spec_strengthening_agent)
    builder.add_node("code_agent", code_agent)
    builder.add_node("verify", verify_node)
    builder.add_node("behavior_test", behavior_test_node)
    builder.add_node("diagnose", diagnose_agent)
    builder.add_node("alignment_repair", alignment_repair_agent)
    builder.add_node("proof_repair", proof_repair_agent)
    builder.add_node("repair", repair_agent)

    # 添加边
    builder.set_entry_point("spec_agent")
    builder.add_edge("spec_agent", "spec_repair")
    builder.add_edge("spec_repair", "mutation_adequacy")
    builder.add_conditional_edges(
        "mutation_adequacy",
        decide_after_mutation,
        {
            "strengthen_spec": "spec_strengthening",
            "code": "code_agent",
        }
    )
    builder.add_edge("spec_strengthening", "code_agent")
    builder.add_edge("code_agent", "verify")

    # 验证后条件路由
    builder.add_conditional_edges(
        "verify",
        decide_after_verify,
        {
            "end": END,
            "repair": "diagnose",
            "behavior_test": "behavior_test",
        }
    )

    builder.add_conditional_edges(
        "behavior_test",
        decide_after_behavior,
        {
            "end": END,
            "alignment_repair": "alignment_repair",
        }
    )

    builder.add_conditional_edges(
        "diagnose",
        decide_repair_route,
        {
            "proof_repair": "proof_repair",
            "code_repair": "repair",
        }
    )
    builder.add_edge("proof_repair", "verify")
    builder.add_edge("repair", "verify")
    builder.add_edge("alignment_repair", "verify")

    return builder.compile()


# ==================== 运行入口 ====================

def run_pipeline(
    problem_id: str,
    problem_desc: str,
    max_rounds: int = 3,
    behavior_problem: dict | None = None,
    entry_point: str = "",
):
    """运行完整 Pipeline"""
    if config.USE_TEMPLATE_FALLBACK:
        template = get_verified_template(problem_id)
        if template:
            print(f"\n{'='*50}")
            print(f"[Template] 命中 verified fallback: {problem_id}")
            verifier = DafnyVerifier()
            verification = verifier.verify(template.code)
            if verification.passed:
                print(f"[Template] Dafny 验证通过，跳过 LLM pipeline")
                return {
                    "problem_id": problem_id,
                    "problem_desc": problem_desc,
                    "spec": template.spec,
                    "code": template.code,
                    "verification": verification,
                    "round": 0,
                    "max_rounds": max_rounds,
                    "history": [{"round": 0, "source": "verified_template"}],
                    "research_trace": [
                        trace_event(
                            "template",
                            0,
                            source="verified_template",
                            verification=verification_snapshot(verification),
                            metrics=spec_metrics(template.spec),
                            adequacy=spec_adequacy_snapshot(
                                spec=template.spec,
                                problem_desc=problem_desc,
                                dafny_verified=verification.passed,
                            ),
                        )
                    ],
                    "spec_adequacy": spec_adequacy_snapshot(
                        spec=template.spec,
                        problem_desc=problem_desc,
                        entry_point=entry_point,
                        dafny_verified=verification.passed,
                    ),
                    "mutation_adequacy": {},
                    "entry_point": entry_point,
                    "behavior_problem": behavior_problem or {},
                    "behavior_executed": False,
                    "behavior_passed": False,
                    "behavior_error": "",
                    "behavior_detail": {},
                    "dafny_verified": verification.passed,
                    "last_verified_code": template.code,
                    "last_verified_spec": template.spec,
                    "regression_rolled_back": False,
                    "candidate_rejected": False,
                    "best_code": template.code,
                    "best_spec": template.spec,
                    "best_verification": verification,
                    "best_quality": list(_verification_quality(verification)),
                    "stagnation_count": 0,
                    "verification_attempts": 1,
                    "passed": True,
                }
            print(f"[Template] 模板验证失败，回退到 LLM pipeline")

    app = build_pipeline()

    initial_state: PipelineState = {
        "problem_id": problem_id,
        "problem_desc": problem_desc,
        "spec": "",
        "code": "",
        "verification": VerificationResult(),
        "diagnosis": "",
        "last_attribution": {},
        "spec_adequacy": {},
        "mutation_adequacy": {},
        "repair_policy": {},
        "entry_point": entry_point,
        "behavior_problem": behavior_problem or {},
        "behavior_executed": False,
        "behavior_passed": False,
        "behavior_error": "",
        "behavior_detail": {},
        "dafny_verified": False,
        "last_verified_code": "",
        "last_verified_spec": "",
        "regression_rolled_back": False,
        "candidate_rejected": False,
        "best_code": "",
        "best_spec": "",
        "best_verification": VerificationResult(),
        "best_quality": [],
        "stagnation_count": 0,
        "verification_attempts": 0,
        "round": 1,
        "max_rounds": max_rounds,
        "history": [],
        "research_trace": [],
        "passed": False,
    }

    final_state = app.invoke(initial_state)

    print(f"\n{'='*50}")
    print(f"[Result] {problem_id}")
    print(f"[Result] 通过: {'是 ✅' if final_state.get('passed') else '否 ❌'}")
    print(f"[Result] 总轮次: {final_state.get('round', 0)}")
    return final_state


# ==================== 测试 ====================

if __name__ == "__main__":
    # 简单测试用例
    result = run_pipeline(
        problem_id="test_max",
        problem_desc="""实现一个 Max 函数，输入两个整数 x 和 y，返回较大的那个数。
要求：返回值必须不小于 x 和 y，且返回值等于 x 或 y 中的一个。""",
        max_rounds=2
    )

    # 保存结果
    out = {
        "id": result.get("problem_id"),
        "passed": result.get("passed"),
        "rounds": result.get("round"),
        "code": result.get("code"),
        "spec": result.get("spec"),
    }
    with open(config.LOG_DIR / "result_test_max.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[Log] 结果已保存到 logs/result_test_max.json")
