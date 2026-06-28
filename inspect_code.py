"""检查改进后的 has_close_elements 代码"""
import sys
sys.path.insert(0, r"D:\codegen-verify\project")
from dafny_wrapper import DafnyVerifier

# 用同样的prompt重新生成代码做精确诊断
from llm_client import code_llm

llm = code_llm()
FEW_SHOT = """
## Dafny 循环不变量常见模式

### 模式1: 单循环遍历 seq（最常用）
```dafny
var i := 0;
var acc := initial_value;
while i < |s|
    invariant 0 <= i <= |s|
    invariant acc == f(s[..i])        // 表达已遍历部分的计算结果
    decreases |s| - i
{
    acc := acc + s[i];
    i := i + 1;
}
```

### 模式2: 双循环遍历 seq（嵌套循环）
当内层循环结束时，外层的循环不变量需要「知道」内层做了什么。
关键是：内层循环的 invariant 必须明确写出「已检查过哪些 pair」：
```dafny
method find_pair(numbers: seq<int>) returns (result: bool)
{
    result := false;
    var i := 0;
    while i < |numbers|
        // 外层不变量: 对索引< i 的所有 pair 已检查过
        invariant 0 <= i <= |numbers|
        invariant !result ==> forall i0, j0 :: 0 <= i0 < j0 < i ==> !P(numbers[i0], numbers[j0])
        invariant result ==> exists i0, j0 :: 0 <= i0 < j0 < i && P(numbers[i0], numbers[j0])
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
        i := i + 1;
    }
}
```

### 关键原则
1. invariant 必须足够强——Dafny 不会帮你「推断」逻辑，你写多少它就知道多少
2. nested loop 的内层 invariant 必须「链接」到外层
3. 如果有 `result` 变量，invariant 要同时覆盖 `result=true` 和 `result=false`
"""

spec = """method has_close_elements(numbers: seq<real>, threshold: real) returns (result: bool)
    requires threshold > 0.0
    ensures result == (exists i, j :: 0 <= i < j < |numbers| && numbers[i] - numbers[j] < threshold && numbers[j] - numbers[i] < threshold)
"""

code = llm.chat(
    system="你是 Dafny 代码生成专家。严格遵循 loop invariant 最佳实践，确保写出的 invariant 足够强。",
    user=f"""{FEW_SHOT}

---

问题描述：
请用 Dafny 语言实现以下函数。

函数说明：Check if in given list of numbers, are any two numbers closer to each other than given threshold.

形式化规约：
{spec}

请根据上面的 Dafny 模式，生成满足规约的完整 Dafny 实现代码。
注意：
1. 如果问题涉及循环，一定要写足够强的 invariant（参考上面的示例）
2. Dafny 需要显式的 invariant 来证明正确性，不要漏写
3. 嵌套循环时，内层 invariant 要表达清楚「当前外层索引 i 的处理状态」
4. 确保代码能通过 Dafny 验证器验证

只输出完整的 Dafny 代码。"""
)

# 提取代码
if "```dafny" in code:
    code = code.split("```dafny")[1].split("```")[0].strip()
elif "```" in code:
    code = code.split("```")[1].split("```")[0].strip()

print("="*60)
print("GENERATED CODE:")
print("="*60)
print(code)
print()

# 验证
v = DafnyVerifier()
result = v.verify(code)
print(f"passed={result.passed} verified={result.verified_count} errors={result.error_count}")
for e in result.errors[:5]:
    print(f"  [{e.error_type}] L{e.location_line}: {e.message[:120]}")
