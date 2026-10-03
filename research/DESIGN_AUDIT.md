# 设计审计与实施记录

范围：2026-09-08 本地 `codex/typed-spec-ir-rebuild`，基础提交 `ddd6c41`。
未发现根目录或父路径 AGENTS.md。保留已有未提交的 artifacts.py 变化和
spec_ir.py、spec_compiler.py、minimal_agent.py。未切换分支、提交、推送或删除历史结果。

## 方向变化

旧任务是“自然语言 → 自动规约 → 代码”。新任务是“目标规约已给定 → 修复验证失败”。
前者的规约生成失败率不能解释后者的修复能力。此前把 Typed IR 本身预设为论文贡献过早；
现在它被保留为探索材料，不再占据新主流程。

## 所有设计的取舍

| 既有模块/设计 | 本版决策 | 理由和替代 |
|---|---|---|
| task_normalizer / TaskIR / HumanEval 类型映射 | 历史轨道 | 新任务直接提供 Dafny 文件和冻结区域，不从 Python 推断目标契约 |
| spec_ir / spec_compiler / StructuredSpecification | 暂停接入 | 研究不允许生成或演化目标规约；另造 IR 不解决调度问题 |
| RequirementAnalyzer / Requirement / 原子需求 | 退出主流程 | 目标已经形式化，额外模型理解步骤混入新的误差和成本 |
| SpecAuthority / approve-reject-abstain / 规约重生成 | 退出 | 新任务框架持有目标；Agent 无权修改契约 |
| SpecHarness / adequacy 启发式评分 | 退出在线过程 | 字符串分数不是语义真值；用原始/破坏/参考三次实际验证做任务准入 |
| SpecCritic / 盲探针 / 期望值复核 | 退出 | 新增模型角色改变机制与预算；可信任务策划替代在线裁决 |
| mutation_probe / 正负样例 | 离线任务构造概念保留 | 人工变异必须标明来源并确认确实破坏验证；不是在线规约强度代理 |
| SpecGuidedPlanner / ProgramPlan / 子目标 DAG | 退出 | 无需通用规划模型；只检验一个依赖调度规则 |
| CandidateSynthesizer / 全文件恢复契约 | 改为区域补丁 | 从原始模板重建，冻结区域逐字保持，避免正则“恢复”遗漏定义 |
| CandidatePool / 多分支搜索 / 候选排序 | 退出 | 共用线性状态和去重；独立生成作为单独基线，不与调度叠加 |
| FailureDiagnoser / 六类语义归因 | 退出模型诊断 | 用验证器原始错误、位置、状态；验证失败不直接归因实现错误 |
| DualRepair / ProofEditGuard | 替换 | 旧行首正则把 assume/花括号当证明行，不能保障不越界；任务先声明 proof/implementation 和区域语法 |
| Reference-collapse 禁止 | 不作为本题通用限制 | 固定契约的实现修复可直接实现数学定义；避免人为提高难度。参考修复文件不进入模型上下文 |
| VerificationEngine / Dafny wrapper | 复用诊断解析 | 新适配器增加六种状态、整文件 CSV 批次结果、超时、最终重新验证 |
| TraceabilityGraph / REQ→SPEC→PLAN→PATCH | 简化 | 记录 source hash、region、diagnostic、candidate、decision 即可回溯 |
| BudgetLedger / 调用和 token 限制 | 保留概念并收紧 | 失败调用计费；调用前预留 token；所有验证含最终重验计数；未知用量不视为零 |
| Holdout / strict / assisted | 历史行为评测保留 | 新成功是冻结规约下整文件验证；无测试反馈循环。未来独立功能测试单列 |
| direct_1 / direct_verify / spec_guided | 历史条件冻结 | 新建六条件协议，防止旧分数和新任务混算 |
| run_humaneval / matrix runner / 大规模作业 | 保留历史入口 | 新 `repair.cli` 从小任务开始；旧 Phase1 不解封、不续跑 |
| manifest / logs / analyze | 保留并适配 | 固定任务、源码、模型、工具和配置；回放从研究统计中剔除 |
| toolchain.lock / check_environment | 历史锁保留 | 锁是 Windows 可执行文件哈希；本机 macOS 的 pip 缺失不等于 Dafny 不可运行。新 manifest 记录实际本机版本和二进制哈希 |
| 多 Agent / RL / GNN / 训练选择器 | 不实现 | 无证据证明当前痛点需要这些组件 |
| 多后端 / 仓库演化 / 需求变更 | 后续扩展 | 保留 verify(source)→Result 接口；本版只支持单文件多 callable Dafny |

## 已执行的实施顺序

1. 完成只读结构审计和最近工作核查；补入 DAISY、VeriStruct、Vero、P3。
2. 实现区域模板、状态分类、真实 Dafny 批次报告；先跑通失败→修复→最终重验。
3. 加入同一循环内六条件、保守图、失败位置、回归记录、统一预算与回放。
4. 加入三版本任务准入、来源划分、近重复初筛、分组分析和测试；目前4个dev任务，2个公开来源派生。
5. 执行离线真实验证；保存报告。未运行付费模型、未声称方法有效。

此结构是可审计研究原型，不是完整 Dafny AST 编辑器。region 自身有受限语法，
复杂多行 calc、任意新引理声明、imports、模块、泛型别名暂不支持；明确拒绝比静默放行可靠。

复查记录：首轮完整回放暴露声明前空行导致伪自调用边的问题。已修正行匹配、保留真实递归边，
增加空行/位置/单行调用/契约引用/引理引用测试，并以新目录重跑；旧日志标记 SUPERSEDED 而不混算。
