"""
Behavior-alignment repair helpers.

This repair path is used when Dafny verifies the generated code but behavioral
tests fail. In that situation the harness should not keep adding proof hints;
it should realign the specification, implementation, and natural-language task.
"""
import re
from typing import Any


def repair_alignment_with_llm(
    llm,
    problem_desc: str,
    spec: str,
    code: str,
    behavior_error: str,
    adequacy: dict[str, Any],
    history_text: str = "",
) -> str:
    return llm.chat(
        system="""你是形式化规约感知的 coding harness 修复专家。
当前情况是：Dafny 已经证明代码满足当前规约，但真实行为测试失败。这说明问题出在
「规约与题意不对齐」或「代码语义错」之一，而不是证明义务不足。

关键判断（必须先做）：
Dafny 已验证通过 = 代码已经满足当前规约。所以如果行为测试在「合法输入」上失败，
最常见的原因是【规约本身过约束或语义错误】，而不是代码没满足规约。

从诊断信息推断哪种情况（重要）：
行为测试失败信息会给出「输入」「期望」「实际」。实际 ≠ 期望。
- 如果实际输出满足当前规约（已知事实，Dafny 已验证），但期望输出不满足当前规约
  → 那必然是 (b) 规约过约束/错误。因为期望输出是正确行为，而当前规约排斥它。
- 如果实际输出不满足当前规约，但 Dafny 通过（矛盾）→ 规约可能有逃逸路径 → 也是 (b)。
- 如果实际和期望都满足当前规约，但行为测试仍失败 → (a) 代码语义错。

两种情况：
(a) 规约正确但代码语义错：代码虽然满足了规约的字面条件，但实现逻辑与题意不符。
    → 修复代码实现，使其既满足规约又通过行为测试。
(b) 规约过约束或语义错误：代码正确实现了规约，但规约强制了一个错误的条件
    （例如强制固定长度、强制最坏情况、漏掉"最短/最长/最早"等优化语义）。
    → 修正规约：删除/放宽/替换与行为测试矛盾的 ensures，用源自自然语言题意的
      正确约束替换；然后调整代码使其满足修正后的规约。

对齐原则：
- 以自然语言题意为最终标准，让规约+代码共同对齐题意与行为测试。
- 不要只添加 proof hint，也不要一味加强规约——错误方向上加强规约只会让代码更偏。
- 行为测试失败信息会给出具体「输入/期望/实际」，据此定位是规约错还是代码错。

硬性规则：
- 保持 method 名、参数列表、returns 列表不变。
- 输出完整 Dafny 代码，包含规约和方法体。
- 可以删除或放宽与行为测试矛盾的 ensures；但新规约不能 vacuous——必须仍约束 result
  与输入的关系，不得删除全部 ensures 或用 vacuous requires 逃避测试。
- function/predicate 只能包含纯表达式，不能包含 var、:=、while、for。
- 优先让代码同时满足 Dafny verifier 和行为测试。
""",
        user=f"""自然语言题目：
{problem_desc}

当前 Dafny 规约：
```dafny
{spec}
```

当前 Dafny 代码：
```dafny
{code}
```

行为测试失败信息：
{behavior_error or "(no error detail)"}

规约充分性报告：
```json
{adequacy}
```

历史：
{history_text}

请进行 spec/code alignment repair。
只输出修复后的完整 Dafny 代码。
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
