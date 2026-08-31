# 最新研究综述与可执行实验设计

> 研究主题：以规约、形式验证和独立审查提高 Coding Agent 的行为正确性  
> 检索截止：2026-08-24  
> 来源边界：仅采用论文原文、作者项目页、官方代码仓库和官方基准页面。2025–2026 年尚未正式发表的工作在文中标为预印本，其数字不应与同行评审结果等同。

## 1. 结论先行

本项目当前的方向是对的：先建立共享规约，再生成代码，用 Dafny 反馈有界修复，并把官方 HumanEval 测试隔离成最终盲测。最新研究支持“形式验证器是强反馈源”，但也共同指出一个更重要的限制：

> 验证器只能证明实现满足给定规约，不能证明规约忠实表达了用户意图；增加搜索或推理预算甚至可能放大对弱验证器的利用。

因此，下一阶段不应继续堆叠更多串行 LLM 模块，而应把系统升级为以下四个相互隔离的层次：

1. **规约验证层**：同时检查一致性、完整性、非空洞性、正反例和语义变换稳定性。
2. **有界候选搜索层**：从当前单路径修复升级为多候选、分支式验证器引导搜索。
3. **独立选择与拒绝层**：生成器、Critic、行为探针和最终隐藏评测分权；输出校准后的风险而不是无条件批准。
4. **实验可信层**：真实 Direct 基线、统一预算账本、时间隔离数据、任务级配对统计和完整失败分类。

最值得主张的研究贡献不是“Dafny 验证率更高”，而是：

> 在相同推理预算下，共享且经过反例验证的规约能否提高隐藏行为正确率，并显著降低 `Dafny verified but behaviorally wrong` 的风险。

## 2. 与项目最相关的一手研究

### 2.1 规约生成、规约验证与 Dafny 中间表示

| 工作 | 年份 | 核心方法与原文结果 | 对本项目的启示 | 可复现实验建议 | 一手来源 |
|---|---:|---|---|---|---|
| SpecGen | 2024（2025 修订） | 两阶段生成 JML 规约；首次对话生成失败后，对规约应用四类变异并按可验证性选择。报告在 385 个程序中生成 279 个可验证规约。 | 规约本身也应成为搜索对象；但“可验证”不能替代语义正确。 | 对同一任务固定实现，比较单次规约、规约线性修复、规约变异搜索；分别报告可解析率、可验证率和隐藏语义正确率。 | [论文](https://arxiv.org/abs/2401.08807) |
| FormalBench | 2025，ACL | 将规约质量拆为 **consistency**（语法与形式语义一致）和 **completeness**（覆盖完整程序行为）；模型在复杂控制流、尤其循环上明显退化，对语义保持变换也不稳；自修复提示提高成功率 25%。 | 当前 `SpecAuthority` 不能只用 resolve、Dafny 通过和条款数量判断充分性；必须显式评估完整性与变换鲁棒性。 | 建立循环/分支/集合/嵌套结构分层；对变量重命名、等价条件改写、输入排列进行成对稳定性测试。 | [ACL 论文页](https://aclanthology.org/2025.acl-long.1068/) · [官方代码](https://github.com/thanhlecongg/FormalBench/) |
| Dafny as Verification-Aware Intermediate Language | 2025 | 先生成可自动验证的 Dafny 中间表示，再编译到目标语言；用户只通过自然语言交互。论文在 HumanEval 上报告原型。 | 证明型 IR 与最终执行语言应分离；长期不应把“最终产物必须是 Dafny”写死在 Agent 接口中。 | 同一候选分别运行 `Dafny-only` 与 `Dafny IR → Python → hidden tests`；单独记录证明成功和编译后语义保持。 | [论文](https://arxiv.org/abs/2501.06283) |
| Validating Formal Specifications with LLM-generated Test Cases | 2025，预印本 | 从自然语言需求生成正例与反例，用于发现人写 Alloy 规约中的错误；强调 verification 与 validation 的区别。 | 现有 Critic probe 应从“辅助文字审查”升级为可执行的正反例验证协议。 | 对每份冻结规约生成正例、边界例、反例各一组；以人工注入的弱/错/过强规约测量缺陷检出率和误报率。 | [论文](https://arxiv.org/abs/2510.23350) |
| NL2VC-60 | 2026，预印本 | 发布 60 个自然语言到 Dafny 验证代码任务；在抽取的 11 题、7 个开放模型上比较无上下文、签名锚定和验证器自修复；使用 uDebug 防止空洞验证。 | 当前类型覆盖问题不能靠隐式猜测解决；冻结签名是有效结构锚点。形式通过之外必须保留独立功能验证。 | 完整复现论文三种提示条件，再加入本项目 Full Agent；不能只复现论文的 11 题，应报告全部 60 题的支持率和端到端结果。 | [论文](https://arxiv.org/abs/2604.22601) |

以下 2025–2026 工作与本项目的下一步尤其接近，建议优先复现而不是继续发明新的 Agent 角色：

| 工作 | 年份 | 关键结论 | 对本项目的直接动作 | 一手来源 |
|---|---:|---|---|---|
| VeriSpecGen | 2026，预印本 | 将原子需求映射到每条需求的 positive、negative-input、negative-output 测试，并只修复失败条款；还加入 adversarial tests。 | 将当前整份规约重写改为条款级局部修复，并强制保存 `requirement → tests → clause` 显式映射。 | [论文](https://arxiv.org/abs/2604.10392) |
| VeriAct | 2026，预印本 | 用 Spec-Harness 分别测前置/后置条件的 correctness 与 completeness；显示 verifier 接受的规约仍可能过强或过弱。 | 将 `spec_adequacy` 扩成 pre/post × correctness/completeness 四象限，而不是一个总分。 | [论文](https://arxiv.org/abs/2604.00280) · [官方代码](https://github.com/Mondego/vACT) |
| SpecRL | 2026，预印本 | 指出 verifier-only 反馈不能区分强规约与弱规约；生成程序不可能产生的负输入—输出对，并以候选规约拒绝这些负例的比例作为 completeness 信号。 | 将当前固定代码 mutant 扩展为输入—输出级 negative tests；先作为推理时门禁和评测指标，积累可靠轨迹后再考虑 RL。 | [论文](https://arxiv.org/abs/2604.05820) |
| VeriEquivBench | 2026，ICLR | 以双向蕴含和输出唯一性评估无 ground-truth 的形式代码等价；论文显示多个既有验证数据集只有部分样例具有可建立的 equivalence。 | 给 Dafny Spec 增加 uniqueness/equivalence probe；只有 verifier pass 的题不能直接进入“正确”分子。 | [OpenReview 论文](https://openreview.net/pdf?id=tRRHVUwP2B) |
| VERINA | 2026，ICLR | 189 个人工任务，将 code、spec、proof 及其组合分开评估；形式证明仍是明显瓶颈。 | 把实验拆为 SpecGen、Gold-Spec→Code、ProofRepair、End-to-End 四条模块赛道，先定位瓶颈再解释端到端结果。 | [论文](https://arxiv.org/abs/2505.23135) · [官方项目](https://verina.io/) |
| CLEVER | 2025，NeurIPS Datasets & Benchmarks | 161 个人工策划任务，使用 held-out ground-truth spec，避免测试监督、实现逻辑泄漏和空洞解；分别要求规约匹配与可证明实现。 | 主实验需要一条带人工 gold spec 的独立规约质量轨道；HumanEval 隐藏测试只能判断行为，不足以精确定位 SpecGen 失败。 | [论文](https://proceedings.neurips.cc/paper_files/paper/2025/hash/a7f67788f7b4d77fa7cd6887de3dcbe7-Abstract-Datasets_and_Benchmarks_Track.html) · [官方代码](https://github.com/trishullab/clever) |
| HumanEval-Dafny / Mainstream Verification Study | 2025，预印本 | 人工整理 132 个 Dafny、106 个 Nagini 和 55 个 Verus 验证程序，并分析多轮验证失败。 | 优先使用人工整理的 132 题解决当前 Dafny 类型/签名覆盖问题；若使用其 gold spec 或实现，必须放在 Gold-Spec 或 ProofRepair 轨道，不能伪装成 NL→Spec。 | [论文](https://arxiv.org/abs/2503.14183) · [官方数据](https://github.com/JetBrains-Research/HumanEval-Dafny/) |

### 2.2 形式验证反馈、搜索与测试时扩展

| 工作 | 年份 | 核心方法与原文结果 | 对本项目的启示 | 可复现实验建议 | 一手来源 |
|---|---:|---|---|---|---|
| DafnyBench | 2024 | 750 余个程序、约 5.3 万行 Dafny；任务是补全证明提示。最佳模型/提示约 68%，错误反馈重试能提高成功率，代码与所需提示增加会降低成功率。 | 当前三轮线性修复是合理起点，但缺少难度分层和证明工作量度量。 | 增加 DafnyBench proof-completion 轨道；按 LOC、缺失提示数、循环数、错误类别报告，而不是只报告总成功率。 | [论文](https://arxiv.org/abs/2406.08467) |
| DafnyPro | 2026，预印本 | 以 diff-checker 防止为通过验证而改写基础程序逻辑，以 pruner 删除无用不变量，并检索通用证明提示；在 DafnyBench 上相对基础模型提升约 16 个百分点。 | 当前整文件 repair 应拆为“实现修复”和“证明注解修复”；后者默认禁止修改可执行逻辑，并在成功后做 proof-hint pruning。 | 在相同预算下比较 whole-file repair、annotation-only repair、带通用 hint retrieval 的 annotation repair，并记录逻辑漂移与证明复杂度。 | [论文](https://arxiv.org/abs/2601.05385) |
| AxDafny | 2026，预印本 | 以 proposer、review system 和跨轮 memory 迭代生成实现、不变量、断言及终止论证；报告 DafnyBench 92.7%，并在 LCB-Pro-Dafny 上同时区分验证成功与编译后运行时测试。 | 给当前有界循环增加压缩记忆、反作弊 reviewer、可选 counterexample 和实现/证明双通道；最终指标必须同时保留 formal 与 runtime。 | 复现其 Direct、iterative-agent 和 runtime-test 条件；再加入本项目 Spec Authority，主比较采用相同 attempt/Token/验证器预算。 | [论文](https://arxiv.org/abs/2606.32007) |
| AutoVerus | 2024 预印本 / OOPSLA 2025 | 多 Agent 模拟专家的三阶段证明：初始证明、通用技巧细化、验证错误驱动调试；在 150 个非平凡 Verus 证明任务上报告超过 90% 成功。 | 诊断应区分通用证明策略与错误定向修复，且每一步应有明确阶段语义。 | 将当前 repair 拆成 `generic proof enrichment` 与 `diagnostic repair` 两个条件，保持总调用预算一致。 | [论文](https://arxiv.org/abs/2409.13082) |
| AlphaVerus | 2024 预印本 / ICLR 2025 | 探索候选翻译、Treefinement 验证器反馈树搜索，并过滤规约—程序错配以避免 reward hacking。 | 当前单路径“生成→修复”容易陷入局部失败；应保留多条互异候选和诊断分支。 | 比较相同 Token/Dafny 调用预算下的线性修复与分支搜索；分别报告 oracle coverage 与 selector accuracy。 | [论文](https://arxiv.org/abs/2412.06176) · [作者项目](https://alphaverus.github.io/) |
| S* | 2025，Findings of EMNLP | 结合并行采样和串行调试；生成区分性输入，利用执行信息对候选进行两两选择；在多模型和 LiveCodeBench/CodeContests 上验证测试时扩展。 | “生成更多候选”和“能选对候选”是两个问题。当前项目应把候选覆盖率与选择准确率分开。 | 固定候选池后离线比较：Dafny 状态选择、Critic 选择、生成测试选择、组合选择；禁止用隐藏测试选答案。 | [论文](https://arxiv.org/abs/2502.14382) · [官方代码](https://github.com/NovaSky-AI/SkyThought) |
| CodeMonkeys | 2025，预印本 | 在 SWE-bench 上同时扩展单轨迹迭代和多轨迹采样；用模型生成测试投票加最终选择轨迹选补丁。 | 大规模搜索需要可复用的上下文、候选去重、独立选择阶段和明确成本核算。 | 对 `K={1,4,8}`、深度 `D={1,3}` 做预算匹配实验；报告最好候选是否存在、是否被选中以及额外正确答案的边际成本。 | [论文](https://arxiv.org/abs/2501.14723) · [官方代码](https://github.com/ScalingIntelligence/codemonkeys) |
| DeepSeek-Prover-V1.5 | 2024 / ICLR 2025 | 使用 proof-assistant feedback 做 RL，并用 RMaxTS 生成多样化证明路径；报告 miniF2F 63.5%、ProofNet 25.3%。 | 形式验证环境适合过程搜索，但搜索奖励不应只有最终二元通过。 | 用错误类别、未解决义务数量、回归数和候选新颖性构造分阶段搜索信号；与单一 `verified` 奖励比较。 | [论文](https://arxiv.org/abs/2408.08152) |
| DeepSeek-Prover-V2 | 2025 | 用强模型将复杂定理递归分解为子目标，再结合形式证明形成训练数据并做 RL。 | Planner 应生成可验证子目标及其依赖图，而不只是自然语言步骤列表。 | 增加 `subgoal DAG` 条件；测量每个子目标的证明率、失败传播位置和组合成功率。 | [论文](https://arxiv.org/abs/2504.21801) |
| Vericoding benchmark | 2025，预印本 | 12,504 个“从形式规约生成验证代码”任务，其中 Dafny 3,029、Verus 2,334、Lean 7,141，并包含 6,174 个新问题。 | 可以将“理解自然语言”与“满足既定形式规约”分开测量，避免所有失败混为 Agent 失败。 | 把 Dafny 子集作为 Formal-Spec→Code 轨道；与 NL→Spec→Code 轨道分开报告，不合并总分。 | [论文](https://arxiv.org/abs/2509.22908) · [官方基准](https://github.com/Beneficial-AI-Foundation/vericoding-benchmark) |
| DafnyCOMP | 2025，预印本 | 300 个多函数 Dafny 程序；论文报告模型在单函数成功后，组合任务仍明显下降，常见问题包括脆弱规约、实现—证明错配和推理不稳定。 | HumanEval 单函数成功不能说明 Agent 能处理真实模块；规约作用域和跨函数依赖必须进入 IR。 | 增加组合轨道；按调用图深度、函数数、共享状态和跨函数不变量分层，报告 local-pass/global-fail。 | [论文](https://arxiv.org/abs/2509.23061) |

### 2.3 规约缺陷、验证器投机、独立 Critic 与可信评测

| 工作 | 年份 | 核心方法与原文结果 | 对本项目的启示 | 可复现实验建议 | 一手来源 |
|---|---:|---|---|---|---|
| EvalPlus / HumanEval+ | 2023 | 自动输入生成结合 LLM 与变异策略，将 HumanEval 测试扩充约 80 倍；论文报告可发现大量原测试漏掉的错误代码，并改变部分模型排序。 | 原始 HumanEval 通过不能作为充分的行为正确标签；已有候选可直接用更强测试做事后重评估。 | 同一冻结候选同时跑 HumanEval 和 HumanEval+；核心指标使用 HumanEval+，两者差值作为测试不足敏感度。 | [论文](https://arxiv.org/abs/2305.01210) · [官方代码](https://github.com/evalplus/evalplus) |
| LiveCodeBench | 2024 | 持续从竞赛平台收集新题，覆盖生成、自修复、执行和测试输出预测，以时间新鲜度降低污染。 | HumanEval 适合回归测试，不足以支撑当前模型的泛化主结论。 | 使用晚于模型知识/训练截止时间的冻结时间窗；记录题目发布时间与模型快照日期。 | [论文](https://arxiv.org/abs/2403.07974) · [官方代码](https://github.com/LiveCodeBench/LiveCodeBench) |
| SWE-rebench | 2025，预印本 | 自动抽取超过 2.1 万个可执行 SWE 任务，并建立持续更新评测；论文强调固定 scaffold、五次重复、时间标记和防止将 pass@N 当 pass@1。 | Agent 结果高度依赖脚手架和重试协议；必须冻结整个 scaffold，而不只是模型名。 | 所有条件共享统一运行器；每题五次；同时报告单次平均成功率与 pass@5，且明确两者不可互换。 | [论文](https://arxiv.org/abs/2505.20411) |
| SWE-bench-Live | 2025，预印本 | 初版 1,319 个 2024 年以来的真实 GitHub 任务、93 个仓库，每题独立 Docker 环境；论文报告相对静态基准存在明显性能差距。 | 后续 repo-level 扩展应优先使用带时间戳、可重建环境的新鲜任务，而不是只做旧 SWE-bench。 | 先在纯函数层验证机制，再用固定的小型 fresh repo 子集检验外部有效性；不要把两类任务合并成一个分数。 | [论文](https://arxiv.org/abs/2505.23419) |
| LLM Critics Help Catch LLM Bugs / CriticGPT | 2024 | 专门训练的 Critic 在真实代码错误上能帮助发现更多问题；论文同时报告 Critic 会幻觉不存在的错误，人机组合能降低幻觉。 | Critic 不能只有 approve/reject 准确率，还要测“拒绝正确规约”和虚假缺陷；独立模型也不是事实 oracle。 | 构造已知缺陷与已知正确规约的平衡集；比较无 Critic、同模型 Critic、独立模型 Critic；画风险—覆盖曲线。 | [论文](https://arxiv.org/abs/2407.00215) · [作者说明](https://openai.com/index/finding-gpt4s-mistakes-with-gpt-4/) |
| LLMs Gaming Verifiers | 2026，预印本 | 提出 Isomorphic Perturbation Testing；论文观察到部分 RLVR 模型产生能通过原验证器但不保持同构变换的捷径，而且捷径随任务复杂度和推理预算增加。作者明确限制是实验域为逻辑归纳任务。 | 不能假设更多测试时计算天然更安全；在引入 RL 或大搜索前，必须先建立同构/变形一致性门禁。 | 对任务做变量、常量、顺序和表示的语义保持变换；原任务通过而变换任务失败记为 `verifier-shortcut`。 | [论文](https://arxiv.org/abs/2604.15149) |

### 2.4 奠基性执行验证基线

下面两项不是最新论文，但应成为实验设计的概念基线：

- [CodeT：Code Generation with Generated Tests](https://arxiv.org/abs/2207.10397)（ICLR 2023）使用模型生成测试和候选间执行一致性选程序。它说明候选选择必须与候选生成分开评估。
- [LEVER：Learning to Verify Language-to-Code Generation with Execution](https://proceedings.mlr.press/v202/ni23b.html)（ICML 2023）联合自然语言、程序和执行结果训练 verifier，并对候选重排。它说明二元编译/验证状态之外的执行信息可用于独立选择。

## 3. 对当前架构的具体改进

### 3.1 P0：把“验证通过”升级为正确性证据格

当前系统已经有 requirement、spec、mutation、critic、contract fidelity、Dafny 和 final holdout。下一步应把它们统一成不可跳级的证据格，而不是散落的布尔字段：

```text
E0 parsed
E1 signature-preserving
E2 spec-resolved
E3 spec-non-vacuous
E4 positive/negative witnesses passed
E5 implementation preserves frozen contract
E6 Dafny verified
E7 metamorphic/isomorphic stable
E8 independent functional holdout passed
```

规则：

- `E6` 只能命名为 **formally verified against generated spec**，不能命名为 correct。
- 正式正确率必须要求 `E6 ∧ E8`。
- `E6 ∧ ¬E8` 单独记为 `verified_wrong`，这是最重要的风险指标。
- 任一验证基础设施异常必须进入 `abstain`，不能降级为 approve。

### 3.2 P0：增强 Spec Authority，而不是增加另一个写规约的 Agent

每份规约至少通过四类相互独立的挑战：

1. **可满足性/非空洞性**：寻找至少一个满足前置条件和后置条件的具体 witness。
2. **正例完整性**：需求和公开样例允许的行为不能被规约拒绝。
3. **反例强度**：常量返回、边界错误、符号错误、顺序错误、空集合错误等错误实现应被杀死。
4. **语义变换稳定性**：变量重命名、输入置换、等价表示和尺度变化后结论应按关系变换。

建议把当前 mutation score 分解成按错误族统计的向量，不能只用一个总分掩盖关键错误族全漏检。

### 3.3 P0：从线性修复升级为有界分支搜索

实现 `CandidatePool`，但不要引入庞大通用 Agent 框架。最小搜索协议：

```text
初始并行候选 K=4
每轮保留 B=2 个互异候选
最大深度 D=3
每个父节点按不同失败假设生成修复子节点
按规范化 AST + 诊断签名去重
```

硬门禁优先于排序分数：

```text
contract fidelity
→ no reference collapse
→ spec-strength gate
→ Dafny/diagnostic progress
→ independent behavior probes
→ selector
```

搜索必须输出两个互不混淆的指标：

- `oracle_coverage@K`：候选池是否包含正确答案；
- `selection_accuracy@K`：隐藏测试不可见时，选择器是否选中了正确答案。

### 3.4 P0：建立真实 Direct 基线和全局预算账本

关闭现有 feature flags 仍会保留确定性 fallback，因此不能声称是 Direct。需要真实实现：

- `Direct-1`：题目和签名直接生成一次代码；
- `Direct+Verify`：无规约 IR/Planner，但拥有相同 Dafny 反馈和修复预算；
- `Spec Prompt`：同一次上下文里先写规约再写代码，不冻结共享 IR。

全局预算至少强制：总输入/输出 Token、模型调用、Dafny 调用、墙钟时间、搜索节点、修复轮数。主要对比必须同时给出“相同 Token 上限”和“相同 verifier 调用上限”的结果。

### 3.5 P1：把 Planner 改为可验证子目标 DAG

计划条目应包含：

```text
subgoal_id
depends_on
requirement_ids
spec_clause_ids
candidate_invariant
discharge_strategy
verification_status
```

单个子目标通过不等于组合成功。需要显式记录 `local_verified/global_failed`，并用 DafnyCOMP 检查跨函数组合。

### 3.6 P1：让 Critic 输出可校准风险，而非单一裁决

保留 `approve/reject/abstain`，同时增加：

- 缺陷类别和具体 witness；
- `p_spec_wrong`；
- 证据来源（静态、执行、模型判断）；
- 与 generator 是否同模型/同提供商；
- 反事实：删除哪条证据会改变决策。

正式实验中至少比较无 Critic、同模型 Critic、跨模型 Critic。阈值只能在开发集确定，然后冻结；最终报告风险—覆盖曲线、AURC、误拒正确规约率和接受错误规约率。

### 3.7 P2：在可信奖励建立前不要进行 RL 自改进

AlphaVerus、DeepSeek-Prover 和 AlphaProof 类工作说明形式环境适合训练与搜索；2026 年 verifier gaming 结果同时说明弱 verifier 会成为捷径目标。因此本项目的顺序应是：

```text
先建立多源验证 + 同构稳定性 + 私有行为 oracle
→ 再收集冻结轨迹
→ 再做离线选择器/诊断器训练
→ 最后才考虑 verifier-reward RL
```

## 4. 正式实验设计

### 4.1 研究问题与预注册假设

| ID | 研究问题 | 可证伪假设 |
|---|---|---|
| H1 | 共享冻结规约是否有效？ | 等预算下，Full Agent 的 `E6 ∧ E8` 通过率高于 Direct+Verify。 |
| H2 | 规约安全门是否有效？ | Mutation + 独立 Critic 降低 `P(¬E8 | E6)`，且正确规约误拒增幅受控。 |
| H3 | 分支搜索是否优于线性修复？ | 相同 Token 和 Dafny 调用下，分支搜索提高 pass@1；若只提高 coverage@K 而不提高 pass@1，则选择器无效。 |
| H4 | 独立 Critic 是否优于自审？ | 跨模型 Critic 比同模型 Critic 有更低 accepted-wrong，且不是仅靠提高拒绝率。 |
| H5 | 形式成功是否可组合？ | 单函数结果不能外推到多函数；Full Agent 应缩小但不能消除 local/global gap。 |
| H6 | 更多推理是否更安全？ | 如果搜索预算增加导致 verified-wrong 或同构不稳定上升，则否定“计算量单调改善安全性”。 |

唯一主假设建议预注册为 H1；其余为次要或机制假设。

### 4.2 核心条件矩阵

| 条件 | 需求/规约 | 规划 | Dafny 反馈修复 | 规约防护 | 候选搜索 | 用途 |
|---|---|---|---|---|---|---|
| C0 Direct-1 | 无 | 无 | 无 | 无 | 单次 | 现实基础线 |
| C1 Direct+Verify | 无 | 无 | 有，等预算 | 无 | 线性 | **主对照**，排除“只是多验证/多修复” |
| C2 Spec Prompt | 同上下文非结构化 | 无 | 无 | 无 | 单次 | 排除“只是让模型多想一步” |
| C3 Shared Spec+Plan | 冻结结构化 IR | 有 | 无 | 基本结构检查 | 单次 | 测共享 IR 与计划 |
| C4 Spec+Linear Verify | 冻结结构化 IR | 有 | 有 | 无 Mutation/Critic | 线性 | 测形式反馈 |
| C5 Current Full | 冻结结构化 IR | 有 | 有 | Mutation + Critic | 线性 | 当前系统 |
| C6 Full+Branch | 同 C5 | 子目标 DAG | 有 | 同 C5 | `K=4,B=2,D=3` | 测 Treefinement 类搜索 |
| C7 Full+Branch+Differential | 同 C6 | 同 C6 | 有 | 正反例 + 同构/变形 + 独立选择 | 同 C6 | 建议最终系统 |

主要比较：`C5 vs C1`。搜索贡献：`C6 vs C5`。新增规约验证贡献：`C7 vs C6`。

### 4.3 数据轨道必须分开报告

| 轨道 | 建议数据 | 测量对象 | 不能声称什么 |
|---|---|---|---|
| A：NL→Spec→Code | HumanEval+/MBPP+、NL2VC-60 | 需求理解、规约生成、实现和证明的端到端能力 | 不能把不支持任务静默排除后称为全数据结果 |
| B：Formal Spec→Code | Vericoding Dafny 子集 | 在规约给定时的实现/证明能力 | 不测自然语言规约忠实度 |
| C：Proof Completion | DafnyBench | 为已有程序补充证明提示 | 不测代码功能生成 |
| D：Compositional | DafnyCOMP | 多函数规约与组合证明 | 不能由 HumanEval 单函数结果替代 |
| E：Fresh Behavioral | 时间隔离的 LiveCodeBench 子集 | 抗污染的算法泛化 | 在没有可靠 Dafny 适配前不能与 A 合并排名 |
| F：Repo-level Future | SWE-rebench / SWE-bench-Live 小型冻结子集 | 真实仓库中的定位、修改和测试 | 当前纯函数 Agent 尚不具备完整 repo-level 能力 |

当前项目只有约 29/164 HumanEval 任务能直接通过类型归一化。正式实验前必须冻结一个只根据公开题面恢复的类型表，并报告：原生支持率、恢复后支持率、全任务端到端成功率、支持域内成功率。所有条件共享同一份类型表。

### 4.4 分阶段运行规模

#### Phase 0：基础设施与协议验证

- 29 个当前原生支持任务；
- C0–C5 六组；
- 每题每组 3 次；
- `29 × 6 × 3 = 522` 次任务运行。

这批结果只用于发现泄漏、预算和恢复问题，不进入正式效果结论。

#### Phase 1：核心确认实验

- 类型冻结后的全部 164 个 HumanEval/HumanEval+ 任务；
- C0–C5；
- 每题每组 5 次独立运行；
- `164 × 6 × 5 = 4,920` 次任务运行。

同一批最终候选先冻结，再分别跑 HumanEval 与 HumanEval+，避免额外生成成本和反馈泄漏。

#### Phase 2：搜索与选择实验

- 从全任务中预先按任务类型和难度分层抽取 80 题；
- `K={1,4,8}`，`D={1,3}`，共 6 个搜索配置；
- 每配置 3 次；
- `80 × 6 × 3 = 1,440` 次。

记录 coverage@K 与 selection accuracy@K。隐藏测试只在选择冻结后运行。

#### Phase 3：规约鲁棒性实验

为每题构造至少四类受控规约缺陷：

1. 弱化/删除关键后置条件；
2. 错误边界或符号；
3. 过强、拒绝合法行为；
4. 空洞或 reference-collapse 规约。

对每个缺陷记录 Mutation、同模型 Critic、跨模型 Critic、正反例和同构门禁的检出情况。该阶段使用冻结 artifacts，可离线反复评估，不应重新生成代码。

#### Phase 4：外部有效性

- NL2VC-60 全集；
- DafnyBench 全集或官方固定子集；
- Vericoding Dafny 官方未见/测试划分；
- DafnyCOMP 300 题；
- 一个晚于所测模型训练截止时间的 LiveCodeBench 时间窗。

各轨道独立给表，禁止把不同任务定义的 success 做宏平均形成一个“总正确率”。

### 4.5 预算公平和随机化

每个 task-condition-replicate 强制记录和限制：

```text
input_tokens
output_tokens
model_calls
dafny_calls
search_nodes
wall_clock_seconds
provider_retries
stop_reason
```

实验规则：

- 主比较使用同一模型快照、同一任务签名、同一总 Token 和 Dafny 调用上限。
- Provider 网络重试和 Agent 语义重试分开计数。
- 条件按任务交错运行，避免服务时间漂移；每个 replicate 随机任务顺序。
- 温度为 0 也运行五次，因为远程推理不保证完全确定。
- 每个请求记录实际模型名、请求 ID、UTC 时间和参数。
- 不能把五次中最好结果报告为 pass@1；平均单次成功率与 pass@5 分列。

### 4.6 指标

#### 主要指标

```text
behaviorally_correct_verified = Dafny verified AND HumanEval+/private holdout passed
```

#### 必须报告的风险指标

```text
verified_wrong_rate = P(hidden fail | Dafny verified)
accepted_wrong_spec = P(Critic approve | injected/independently-labeled wrong spec)
rejected_correct_spec = P(Critic reject | independently-labeled correct spec)
shortcut_rate = P(original passes AND isomorphic variant fails)
local_global_gap = P(global fail | every local component verified)
```

#### 搜索指标

- pass@1；
- oracle coverage@K；
- selection accuracy@K；
- success by repair depth；
- unique candidates per Token；
- additional correct tasks per million Tokens/Dafny calls。

#### 规约指标

- resolve rate；
- 正例接受率、反例拒绝率；
- mutation score，按错误族分解；
- requirement/spec clause coverage；
- semantic-transform consistency；
- 规约修订次数和漂移率。

#### 系统指标

- 原生/恢复/总体支持率；
- API、解析、Dafny 超时等基础设施失败率；
- Token、调用数、延迟和估算成本；
- 风险—覆盖曲线与 AURC；
- 正确率—成本 Pareto 前沿。

### 4.7 统计协议

- 独立统计单位是任务，而不是同一任务的多次运行。
- 主分析使用任务级配对差值，并按任务做 10,000 次 cluster bootstrap，报告绝对百分点差和 95% CI。
- 主比较 `C5 vs C1` 只做一个预注册检验；其他多重比较采用 Holm 校正。
- 五次重复用于估计随机性；不能把 164×5 当成 820 个独立样本。
- 二元敏感性分析可用配对 McNemar；完整分析可用以 condition 为固定效应、task 为随机截距的混合效应逻辑回归。
- 支持率、基础设施失败和 abstain 必须进入分母或单独列出，不能事后删除失败任务。
- 先用 Phase 0 的任务间差异和 discordant pair 比例做功效模拟，再冻结正式样本量。

## 5. 最关键的消融

不要做完整 `2^N` 因子组合。以 C5/C7 为锚点，一次移除一项：

| 消融 | 研究问题 |
|---|---|
| 无结构化 Requirement IR | 收益来自需求结构还是仅增加调用？ |
| 无 Planner / 无 subgoal DAG | 计划和形式子目标是否真正贡献？ |
| 无诊断模型，仅返回原始错误 | Failure Diagnoser 是否优于简单 verifier feedback？ |
| 无 Mutation Guard | Mutation 是否降低 verified-wrong？ |
| 无 Critic | Critic 的净收益与误拒成本是多少？ |
| 同模型 Critic 替代跨模型 Critic | 模型独立性是否有价值？ |
| 无正反例验证 | 可执行 spec validation 是否有增益？ |
| 无同构/变形门禁 | 该门禁是否只增加拒绝，还是发现真实捷径？ |
| 线性搜索替代分支搜索，预算相同 | 收益来自搜索结构还是更多计算？ |
| Dafny 状态选择替代独立 selector | 行为选择器是否解决了“池中有正确答案却选错”的问题？ |

## 6. 失败分类必须冻结

建议在运行前冻结以下互斥主标签，并允许附加次标签：

```text
unsupported_signature
requirement_misread
spec_parse_or_resolve
spec_weak
spec_overstrong
spec_semantic_misalignment
contract_drift
reference_collapse
implementation_compile
proof_failure
proof_timeout
selector_failure
verified_wrong
critic_false_reject
budget_exhausted
provider_failure
infrastructure_failure
```

这样最终才能回答“规约驱动到底改善了哪一种错误”，而不是只得到一个总通过率。

## 7. 推荐的实施顺序

1. 实现真实 `Direct-1`、`Direct+Verify`、`Spec Prompt`。
2. 增加全局预算账本、运行 ID、停止原因和原子恢复。
3. 接入 HumanEval+，保持最终测试单次、只读、无反馈。
4. 冻结 HumanEval 类型恢复表，将支持覆盖提升到可发表规模。
5. 将 Spec 检查扩展为正例、反例、变异族和语义变换稳定性。
6. 运行 Phase 0 的 522 次协议验证。
7. 冻结 commit、prompt、模型快照、数据、预算和统计脚本。
8. 运行 Phase 1 的 4,920 次核心确认实验。
9. 核心结果成立后实现 `CandidatePool`、分支搜索和独立 selector。
10. 再运行搜索、Critic、组合性与外部数据轨道。
11. 只有多源验证器已证明抗捷径后，才收集训练数据或引入 RL。

## 8. 最终论文可以形成的清晰论证链

```text
Direct+Verify 控制额外验证和修复预算
    ↓
共享冻结 Spec IR 是否提高隐藏正确率
    ↓
Mutation / 正反例 / Critic 是否降低 verified-wrong
    ↓
分支搜索是否提高候选覆盖，独立 selector 是否把覆盖转化为 pass@1
    ↓
同构与语义变换是否证明系统没有只学会利用验证器
    ↓
结果是否跨 HumanEval+、NL2VC-60、DafnyBench、Vericoding 和 DafnyCOMP 保持
```

如果 H1 未成立，项目仍能产出有价值结论：定位规约生成、规约强度、实现证明和候选选择中哪一层造成损失。如果 H1 成立但 verified-wrong 不下降，则只能声称“更容易生成可证明程序”，不能声称“更正确”。只有隐藏行为正确率上升、verified-wrong 下降、等预算和新鲜数据结果同时成立，才能支持“规约驱动提高 Coding Agent 正确性”的核心主张。
