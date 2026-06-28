"""修复 pipeline.py 中添加缺失的 PipelineState"""
with open(r'D:\codegen-verify\project\pipeline.py', 'r', encoding='utf-8') as f:
    content = f.read()

insert = """

\n
# ==================== 状态定义 ====================

class PipelineState(TypedDict):
    \"\"\"在 Agent 之间传递的全局状态\"\"\"
    problem_id: str                        # 问题 ID
    problem_desc: str                      # 问题描述
    spec: str                              # 生成的规约
    code: str                              # 生成的代码
    verification: VerificationResult       # 验证结果
    round: int                             # 当前修复轮次
    max_rounds: int                        # 最大修复轮次
    history: list                          # 修复历史
    passed: bool                           # 是否最终通过


# ==================== Agent 节点 ====================

"""

content = content.replace('def spec_agent(state: PipelineState) -> dict:', insert + 'def spec_agent(state: PipelineState) -> dict:')

with open(r'D:\codegen-verify\project\pipeline.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed - PipelineState added back')
