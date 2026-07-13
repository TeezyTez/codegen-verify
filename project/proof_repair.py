"""
Proof-oriented repair agent helpers.

Unlike general code repair, proof repair tries to preserve the algorithm and
specification while adding or strengthening Dafny proof artifacts: loop
invariants, assertions, helper lemmas/functions, and decreases clauses.
"""
import re
from typing import Any

from proof_patterns import select_proof_patterns


def repair_proof_with_llm(
    llm,
    problem_desc: str,
    spec: str,
    code: str,
    diagnosis: str,
    verification_errors: list[dict[str, Any]],
    history_text: str = "",
) -> str:
    proof_patterns = select_proof_patterns(problem_desc, spec, verification_errors)
    return llm.chat(
        system="""你是 Dafny proof repair 专家。
你的任务不是重写算法，而是让现有实现更容易被 Dafny 证明。

优先动作：
- 加强 while invariant，描述已处理前缀、累计变量、result=true/false 两种状态。
- 在循环后或关键分支后添加 assert bridge。
- 添加纯 helper function、predicate、lemma 来表达证明义务。
- 添加或修正 decreases 子句。
- 修复 postcondition proof gap 时，优先补中间断言和不变量。

硬性约束：
- 保持 method 签名和原始 requires/ensures 不变。
- 不要削弱规约。
- 不要把 function/predicate 写成命令式代码。
- helper function/predicate 优先定义为全函数；确需 requires 时，必须在每个调用点证明，且不得加强公共 method 的输入前置条件。
- 只输出完整 Dafny 代码。
""",
        user=f"""问题描述：
{problem_desc}

规约：
```dafny
{spec}
```

当前 Dafny 代码：
```dafny
{code}
```

验证错误：
{_format_errors(verification_errors)}

诊断：
{diagnosis}

历史错误：
{history_text}

与当前义务匹配的通用 proof patterns：
{proof_patterns}

请进行 proof repair：保留算法主体，补充/修复 invariant、assert、lemma、decreases，使 Dafny 能证明代码满足规约。
只输出完整 Dafny 代码。
""",
    )


def extract_dafny_code(text: str) -> str:
    code = text or ""
    if "```dafny" in code:
        code = code.split("```dafny", 1)[1].split("```", 1)[0].strip()
    elif "```" in code:
        code = code.split("```", 1)[1].split("```", 1)[0].strip()
    if code.lower().startswith("dafny\n"):
        code = code.split("\n", 1)[1]
    return re.sub(r"[^\x00-\x7F\n\r ]+", "", code).strip()


def _format_errors(errors: list[dict[str, Any]]) -> str:
    if not errors:
        return "(no structured errors)"
    lines = []
    for idx, error in enumerate(errors, start=1):
        subtype = error.get("subtype") or error.get("type")
        detail = f"{idx}. [{subtype}] L{error.get('loc', 0)}: {error.get('msg', '')}"
        if error.get("source"):
            detail += f"\n   source: {error['source']}"
        if error.get("related"):
            detail += f"\n   related: {error['related']}"
        lines.append(detail)
    return "\n".join(lines)
