# 相关工作核验记录

核验日期：2026-09-08。证据标签：**[P] 原文陈述**；**[O] 本仓库实际观察**；**[H] 我们的假设/判断**；**[?] 待核验**。
只引用以下明确版本的原文、作者仓库或官方出版来源。不把 arXiv 上传当录用，不把最新预印本当已同行评审。
本地最初没有 research/；此前材料实际在 docs/LATEST_RESEARCH_AND_EXPERIMENT_DESIGN.md。旧文完整保留并标记为历史初稿。

## 首先分清四个维度

1. 补证明注释不是生成实现；证明修复固定实现，代码修复可以改变实现。
2. 单次成功率、独立样本 pass@k、一次包含多轮反馈的 Agent 成功率不可互换。
3. 给定目标规约不测规约生成忠实度；生成规约的任务不能直接作为冻结规约修复基线。
4. 文件有多个函数不等于仓库级维护；仓库派生任务也不等于真实提交演化。

以下每篇的节号/表号针对所链接版本。跨版本数字必须重新核对，不能拼接。

## 最近、最接近的工作

### Laurel：单缺失断言的位置与内容生成

[P] v1（2024-05-27）标题为 *Laurel: Generating Dafny Assertions Using Large Language Models*；v2（2025-03-03）改为 *Laurel: Unblocking Automated Verification with Large Language Models*。
arXiv 作者注记称 accepted at OOPSLA25；此处将其标为**作者报告录用**，不把 Dafny workshop 出现视为主会证明。[版本与状态](https://arxiv.org/abs/2405.16792)

[P] 固定程序中删除一个辅助断言；§4 根据验证错误插入占位位置，再检索相似证明供 LLM 补断言。
§5 使用三个真实来源项目（Dafny Libraries、Cedar、DafnyVMC）。§6.1 为 GPT-4o、Dafny 4.3、温度1、最多10次尝试；摘要的56.6%不能叫单次生成成功率。
正文评估集称143，Table 1 提取断言项合计145，需以发布 task ID 查清筛选差额，不擅自统一。
[H] 已覆盖“错误定位+相关证明上下文”；不足以证明跨函数调度新颖。精读 §4、§5、§6.1：分别核对定位输入、任务粒度、重试口径。[原文 v2](https://arxiv.org/html/2405.16792v2)

### DAISY：多缺失断言与混合定位

[P] *Inferring multiple helper Dafny assertions with LLMs*，arXiv v1，2025-10-31；本次未核实正式发表记录，按预印本处理。[版本](https://arxiv.org/abs/2511.00125)

[P] §3.1 混合 LLM 与验证器定位，§3.2 检索相关证明、生成候选断言集合。§4/§5.1 共506个删除变体：241单缺失、235双缺失、30全部删除；使用 GPT-4.1、定制 Dafny 4.10、Z3 4.15.2、300秒验证限制，每提示10候选。
§5.2/Table 5 的单缺失153/241（63.4%）合并不同定位策略，不能当某个单策略的 pass@1；摘要多缺失31.7%也不能与 Laurel 直接排名。
[H] “一次修多个洞”不再足以构成贡献。精读 §3、Table 5、§7：核对候选预算、合并结果及非唯一插入位置。[原文 v1](https://arxiv.org/html/2511.00125v1)

### DafnyPro：固定实现下的受约束注释补全

[P] *DafnyPro: LLM-Assisted Automated Verification for Dafny Programs*，v1，2026-01-08；未核实正式发表，不标 POPL 主会。[版本](https://arxiv.org/abs/2601.05385)

[P] §3/§4.1 Algorithm 1：diff-checker 限制改写基础逻辑，pruner 删除非归纳不变量，8条通用提示辅助修复。
§4.2 使用 Dafny 4.11、Claude 3.5/3.7 Sonnet、10次尝试；Table 1 DafnyBench 为86.18%/85.67%。作者还修订了782项中70项格式问题。
[H] 旧文“提升约16个百分点”不能脱离其模型、预处理与比较对象使用，更不能作为本仓库同预算优势。边界检查已是既有要求，不是创新。
精读 Algorithm 1、§4.2/Table 1：对齐修改权限、预处理和预算。[原文 v1](https://arxiv.org/html/2601.05385v1)

### AxDafny：完整验证生成 Agent

[P] *AxDafny: Agentic Verified Code Generation in Dafny*，v1，2026-06，按预印本处理。
§3.1 为 proposer、审查与滚动记忆；§3.2 最多20次尝试。§3.3 分开 DafnyBench 证明提示补全与250项 LCB-Pro-Dafny 代码/证明生成。
§3.4 有反绕过与独立运行测试；Table 1 的725/782（92.7%）使用 Gemini 3.1，不能与不同模型/预算的 DafnyPro 分数作受控比较。
[H] 通用 Agent + 验证 + 记忆已被覆盖，本项目不以此命名新方法。精读 §3.3–3.4 和 Table 1：核对两类任务、规格约束与历史分数来源。[原文 v1](https://arxiv.org/html/2606.32007v1)

### DafnyCOMP：多函数组合困难，但不是冻结规约修复

[P] *Local Success Does Not Compose: Benchmarking Large Language Models for Compositional Formal Verification*，arXiv v1，2025-09-27。[版本](https://arxiv.org/abs/2509.23061)
[?] 检索到 ICLR2026 的官方索引，直接打开 OpenReview 遇到浏览器验证；本记录不将最终录用/相机版内容视为已完整核验。[官方记录入口](https://openreview.net/pdf?id=y4kAMUBqLq)

[P] §3 是300个自动组合的2–5函数任务；§3.3/§4 涉及生成形式规约与证明注释，并非仅修给定固定目标。
Table 1 区分 @1/@2/@4/@8；v1 Claude 3.5 的 verified 3.67%@1、7%@8，不是多轮 Agent 修复率。
[H] 可作为组合困难的动机，不能直接给我们的多函数修复成功率设基准。精读 §3.3 和 Table 1：确认输出项与采样口径。[原文 v1](https://arxiv.org/html/2509.23061v1)

### VeriStruct：数据结构模块验证，允许规约生成/调整

[P] *VeriStruct: AI-assisted Automated Verification of Data-Structure Modules in Verus*，arXiv v1，2025-10-28；作者出版页列 TACAS2026，pp.109–128。[出版记录](https://theory.stanford.edu/~barrett/pubs/SSA%2B26-abstract.html)

[P] §§3–5 联合抽象视图、类型不变量、方法规约和证明，再迭代修复。§6/Table 2 报告10/11模块、128/129函数，基线4/11模块、52函数。
使用 o1，流程含3样本和5轮修复；基线13调用按观察到的最高调用数设置，不能称等 token 比较。
[H] 模块一致性已被研究；但其允许规格调整，和我们的冻结目标不等价。精读 §§3–5 与 §6：确认哪些制品可改、如何算模块成功。[原文 v1](https://arxiv.org/html/2510.25015v1)

### Vero：两种任务边界与仓库级评测已经出现

[P] *Vero: Can AI Agents Build Formally Verified Software Repositories?*，v1，2026-08-13，按预印本处理。[版本](https://arxiv.org/abs/2608.13522)

[P] §3.2 为43个 **Lean 4** 多模块任务，区分 proof-only 与 code-and-proof；来自多语言项目不等于在多语言验证器上评测。
使用标记编辑区、不可变部分重建、允许公理集合。§3.3 的依赖顺序用于数据翻译策划，不能据此说作者已经提出在线依赖修复调度。
§4.2/Figures 3、5：90分钟预算，最强27/43；更深辅助证明依赖与更低成功相关，不是因果结论。
[H] 我们的任务边界与反作弊不是新贡献；潜在缺口只可能是受控调度机制。精读 §3.2、§4.2：对齐验收协议与实际瓶颈。[原文 v1](https://arxiv.org/html/2608.13522v1)

### P³：联合规划与局部修复/重规划——高重叠风险

[P] *P³: Joint Program-and-Proof Planning for Verified Code Generation*，v1，2026-08-10，按预印本处理。
§3 先决定程序分解、桥接谓词、辅助引理及证明义务，再实现/证明；§3.3 区分局部失败与计划失败，分别局部修复或重规划。
§4 Lean4Commit0 为108库派生任务、511实现/519证明槽。§5.1 每任务30美元、180分钟，四后端、每配置一次，不能估计任务内方差；Table 3 比较实现单侧规划和联合规划。
[H] “失败感知路由”概念重叠很高；我们只能检验固定实现/固定目标下细粒度调度的信息价值。精读 §3.1–3.3、§5.1、附录C：防止把已有回退机制换名当创新。[原文 v1](https://arxiv.org/html/2608.09277v1)

## 公开基线复现的实际边界

[P] *DafnyBench: A Benchmark for Formal Software Verification*，arXiv v1，2024-06-12。
原文摘要报告750余程序、约53k LOC、最佳设置68%；任务是已有程序的证明提示补全，有错误反馈重试，不是自然语言规约生成。[原文与版本](https://arxiv.org/abs/2406.08467)

[P] 已读官方 `eval/fill_hints.py`：`feedback_turn` 默认10，`max_tokens=4096`，温度0.3；生成整文件、执行 Dafny、反作弊检查，失败后把错误加回对话。
[O] 新 `linear` 复用了这个可理解的反馈协议，但改为统一区域补丁、统一预算与温度；因此是**受控协议改编**，不是原方法完整复现，也没有复现68%的分数。
[O] 官方仓库浅克隆因网络超时失败；成功取得两个 ground_truth 文件。公开源只作任务派生，参考修复不进入真实模型提示。
精读代码的循环、`run_dafny` 与 `check_no_cheating`，再复现其原始设置。[官方实现](https://raw.githubusercontent.com/sun-wendy/DafnyBench/main/eval/fill_hints.py)

[?] Laurel/DAISY 的检索数据、模型与修改过的 verifier 尚未在本机复现；DAISY 公开入口是 [VeriFixer/daisy](https://github.com/VeriFixer/daisy)。无付费授权，未跑 GPT-4.1 检索/生成实验；DafnyPro 没有取得经核实可运行的完整 artifact。不得用这些论文分数填充我们缺失的 baseline。

## 验证器本身已有依赖信息

[P] Dafny 官方2023-10-27说明：4.4起支持基于求解器证明使用情况的 proof dependencies，用于冗余假设等诊断；依赖集合不保证最小。
[H] 普通调用图既不是这类证明使用依赖，也不能被包装为完整证明 DAG。本版先记录语法边与批次，是否值得接入原生证明依赖由预实验决定。[官方机制说明](https://dafny.org/blog/2023/10/27/proof-dependencies/)

## 对旧初稿的纠正和待核验清单

| 旧论断/设计 | 本次处理 |
|---|---|
| “方向是对的”“最新研究支持现有整套系统” | 改为待检验假设；相关工作只能支持问题存在，不能支持本方法有效 |
| DafnyPro +16pp、AxDafny92.7%、DafnyBench68% | 保留在各自原文设置，禁止跨模型/预算比较或混入本仓库结果 |
| DafnyCOMP 作为修复基线 | 纠正为涉及规约/注释生成的组合任务，不能直接代表固定目标修复 |
| 加 memory/critic/branch/authority 就是下一步 | 不采纳；混入多个机制无法解释依赖调度效应 |
| Laurel/DAISY/Vero/P³ 未纳入核心对比 | 本次补齐；这些近邻显著削弱泛化“新 Agent/新依赖图”主张 |
| SpecGen、FormalBench、Dafny-as-IR、Alloy test validation、NL2VC-60、VeriSpecGen、VeriAct、SpecRL、VeriEquivBench、VERINA、CLEVER、HumanEval-Dafny | 本轮未逐一核对原文全套指标/版本/发表状态，旧数字统一 **[?]**；属于其他任务或后续规格质量研究，不用来支持当前机制 |
| AutoVerus、AlphaVerus、S*、CodeMonkeys、DeepSeek-Prover-V1.5/V2、EvalPlus、LiveCodeBench、SWE-rebench、SWE-bench-Live、CriticGPT、LLMs Gaming Verifiers、CodeT、LEVER | 除上文明确核验的事实外，其旧文结论与迁移建议均 **[?]**；非本轮最接近的固定 Dafny 修复方法，不依据旧数值作新结论 |

[?] 另发现 [VeriSoftBench 官方页](https://utopia-group.github.io/VeriSoftBench/)；尚未精读预算、拆分与方法，不写性能结论。论文投稿前要再次更新检索，而不是把本清单视为穷尽证明。

## 推荐精读顺序

先读 Vero §3.2（什么算合法成功），再读 DafnyBench 官方循环（能复现的最小协议），
然后 DAISY §3/§5 与 Laurel §4（定位和上下文已做到什么），最后 P³ §3 与 VeriStruct §§3–5（更高层规划与模块一致性覆盖了什么）。
对产品经理视角，先把每篇还原成“输入—可修改对象—工具反馈—停止条件—资源账本”，再读技术细节；不要按 Agent 角色数量比较贡献。
