# 给定规约、配置和约束的代码生成：文献与选题路线

检索日期：2026-10-06。用途：从代表文献倒推可执行研究问题。本文是定向检索，不是系统综述；候选题目的新颖性尚未证明。未运行模型实验。出版状态以会议论文集或出版社为优先依据，只有 arXiv/SSRN 证据的条目标为预印本。

**用户后续澄清：这里的“配置项条件”特指 MDA 中 PSM（Platform-Specific Model）的配置项。** 因此，下文的 API 版本、一般业务开关和通用指令遵循只保留为外围比较，不能再作为用户配置含义。当前优先研究主线改为 **PSM→目标实现的模型符合性、约束保持与可追溯验证**；Dafny 仅为可能的验证实现选择，不能因已有原型而默认替代实际 PSM/目标平台。参见[收窄后的 PSM 文献与研究边界](PSM_CODEGEN_FOCUS_2026_10_06.md)。PSM 的具体元模型、格式、目标平台与实际配置样例尚待用户说明。

## 1. 先明确“条件”是哪一种

| 条件 | 例子 | 对应研究线 | 合适的验收 |
|---|---|---|---|
| 行为规约 | 前后置条件、状态不变量、允许副作用 | Specification-guided / verified program synthesis / vericoding | 相对于冻结规约的形式验证；必要时补执行测试 |
| 产品或业务配置 | 功能开关、分配策略、接口/字段模型、互斥选项 | Model-driven code generation、software product lines、configuration-conditioned generation | 配置映射检查、功能测试、配置组合及变化关系 |
| 环境条件 | 指定库版本、平台、允许使用的 API | Version-conditioned / environment-aware code generation | 固定环境下实际编译和执行 |
| 实现限制 | 禁止递归、禁止某 API、类型规则、资源上界 | Constrained code generation / code instruction following | 静态分析、类型检查、测试或与资源语义对应的检查 |

这里的分类是研究设计用的综合整理。它们可以组合，但不能把各自验收标准混为一谈。给条件生成实现、让模型生成条件、生成配置文件是三个不同任务。JSON 是一种表示格式，其是否构成规约取决于明确语义。

理论起点：[Syntax-Guided Synthesis，FMCAD 2013](https://people.eecs.berkeley.edu/~sseshia/pubs/b2hd-alur-fmcad13.html) 已将逻辑正确性条件与限制实现空间的语法共同作为程序合成输入。因此“给定条件生成程序”本身不是新任务。

## 2. 直接对标的论文

| 文献与已核验状态 | 已经研究什么 | 对本项目的意义 |
|---|---|---|
| [A benchmark for vericoding: formally verified program synthesis](https://arxiv.org/abs/2509.22908)，2025 预印本 | 给形式规格生成实现及所需证明，覆盖 Dafny、Verus/Rust、Lean；有[官方数据与实现](https://github.com/Beneficial-AI-Foundation/vericoding-benchmark) | 固定规约到实现的直接任务基线；不能把完整公开任务数等同于本地可直接接入的可靠题数 |
| [AlgoVeri](https://proceedings.mlr.press/v306/zhao26bm.html)，ICML 2026 | 77 个经典算法在 Dafny、Verus、Lean 下对齐功能契约，研究跨工具的验证代码生成 | 适合学习契约对齐和可比实验；跨语言生成不是空白 |
| [AxDafny: Agentic Verified Code Generation in Dafny](https://arxiv.org/abs/2606.32007)，2026 预印本 | 固定规格下生成实现及证明材料，验证反馈后修正，并补充执行测试和资源检查 | 与现有 Dafny 原型高度贴近，应该纳入强基线与机制对照的核查 |
| [P³: Joint Program-and-Proof Planning for Verified Code Generation](https://arxiv.org/abs/2608.09277)，2026 预印本 | 联合规划程序结构和证明结构，包含跨 API 关系规格任务 | 单纯增加规划阶段或同时生成代码与证明，已有直接方法对标 |
| [VERINA](https://proceedings.iclr.cc/paper_files/paper/2026/hash/41b8c80f9113b9f8e2e129447221682a-Abstract-Conference.html)，ICLR 2026 | 将实现、规约、证明及其组合区分评测 | 使用时只能取符合自己任务定义的子任务，不能混合不同任务的成功率 |
| [Large Language Model as a Code Generator in Simplified Domain-Specific Modelling](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6818764)，2026 SSRN 预印本 | 用简单数据结构表达领域模型，研究 LLM 代码生成并与模板和程序化方法比较 | 最贴近“结构化配置到业务代码”；全文未成功直接打开，本轮依据原始 SSRN 搜索返回摘要，不引用具体结果数字 |
| [End-to-end development of product lines for web systems](https://link.springer.com/article/10.1007/s10009-025-00784-3)，STTT 2025，PRICES | 模型与产品线驱动的 Web 系统开发和产品派生，公开[工具及模型](https://gitlab.com/RSE-Lab-Fasilkom-UI/prices-2) | 配置到代码路线的重要传统对照；不是 LLM 方法 |
| [LibEvolutionEval](https://aclanthology.org/2025.naacl-long.348/)，NAACL 2025 | 多库、多版本条件下的代码补全，考察版本文档上下文；有[作者实现](https://github.com/amazon-science/LibEvolutionEval) | 如果配置指依赖版本，这比泛泛的模型驱动生成更直接 |
| [GitChameleon 2.0](https://aclanthology.org/2026.acl-long.2170/)，ACL 2026 | 328 个带指定 Python 库版本和可执行测试的补全任务；[项目页](https://gitchameleon-2-0.github.io/) | 可用于研究“代码在指定环境里是否真正可运行” |
| [CodeIF](https://aclanthology.org/2025.acl-industry.89/)，ACL 2025 Industry Track | 面向代码任务的细粒度指令遵循，包括合成、调试、重构等 | 约束符合性已有直接基准；主实验须只选与代码生成任务一致的子集 |
| [IntentCoding: Amplifying User Intent in Code Generation](https://aclanthology.org/2026.findings-acl.1662/)，Findings of ACL 2026 | 研究多约束用户意图及约束数量增多时的性能衰减，并提出解码策略 | “约束增多导致失败”已被研究，需要更窄的机制或失败类型 |
| [Type-Constrained Code Generation with Language Models](https://doi.org/10.1145/3729274)，PLDI 2025 | 用类型信息限制生成；在形式核心语言及 TypeScript 子集实现，提供[复现包](https://github.com/eth-sri/type-constrained-code-generation) | 生成时强制类型约束已有深入工作；类型正确仍不等于满足全部业务行为 |
| [Complexity-Constraint Code Evaluation (C3E)](https://jcst.ict.ac.cn/article/doi/10.1007/s11390-025-5518-5)，JCST 2026 | 显式时间复杂度要求下的代码生成，含可行和理论不可行要求 | 资源约束应另选专门验收；“识别不可能复杂度”已经有直接研究 |
| [Compact Constraint Encoding for LLM Code Generation](https://arxiv.org/abs/2604.07192)，2026 预印本 | 比较自然语言与紧凑结构化约束表示；在其设置下主要收益是节省 tokens，未检出符合率的显著差异 | 不应预设“换成 JSON/清单就提高正确性”；其结果也不能泛化为所有领域均无差异 |

## 3. 三个可继续收窄的选题

下列是基于文献和本地工程现状的建议，不是已发现的空白，也没有正向实验结果。

### A. 固定规约下，验证反馈的信息粒度如何影响代码生成？

- 一句话问题：冻结相同契约、初始候选和预算时，完整诊断、压缩诊断和仅失败状态，对修复成功及失败类型有什么影响？
- 对标：Vericoding benchmark、AlgoVeri；不能把生成—验证—修复循环当新方法。
- 工程起点：本地已有 Dafny 方法体生成、验证、迭代和轨迹记录，见[项目说明](../README.md)。本轮仅阅读说明，未重跑或验证旧实验结果。
- 最小比较：独立重新采样；旧候选加失败状态；旧候选加现有压缩诊断；旧候选加完整诊断。若后续研究定位后的反馈，应另设控制，分开判断“增加信息”和“改变表示”的作用。
- 主要指标：预算内验证成功率及成本；按语法/名称/类型、证明义务、超时和工具错误分层；区分仅证明注释变化与可执行逻辑变化。
- 潜在贡献：同预算的受控经验结果及可复用的失败分析。需要继续核对验证诊断压缩、Dafny 反馈研究，不能只依靠本次广泛检索宣布新颖性。

### B. 给定业务配置，生成代码在未见配置组合上是否仍保持正确行为？

- 一句话问题：同一业务任务更换策略或组合配置后，生成代码能否同时满足选中行为和始终有效的共同不变量？
- 对标：SDSM 与 PRICES；它们要求我们认真比较传统模板/规则生成器。
- 可操作例子：资源分配函数。配置明确规定处理顺序、是否允许部分分配、失败语义；共同要求是不超额、不接受非法请求、拒绝操作不改变状态。每个选项的语义必须事先明确。
- 最小比较：相同输入信息下的模板/规则方法（适用部分完整保留）、直接提示、固定骨架加生成、生成加验收反馈。避免同时更换全部模块，先检验一种机制。
- 主要指标：完整配置符合率、未见组合的功能正确率、配置变化关系满足率、代价。按基础任务或来源划分数据，不能把同一模板的组合变体当独立问题。
- 核心难点：配置语义和独立验收器需要可信来源。若配置已经完整决定实现且规则生成器可覆盖所有需求，LLM 的收益必须另有证据。

### C. 功能正确与实现限制的联合满足：失败发生在哪里？

- 一句话问题：在可满足的功能规格、固定接口和 API/副作用限制同时存在时，生成或修复会以什么方式满足一项却破坏另一项？
- 对标：CodeIF、IntentCoding、Type-Constrained Code Generation；仅统计约束数量或增加一个反馈循环不够。
- 最小起点：选一种语言和两类可自动判断的限制，例如接口/依赖白名单与输入不变性，给每类限制独立检查；同一个功能任务配匹配的约束条件。
- 主要指标：功能测试通过率、每条约束满足率、所有约束联合满足率、功能与全部约束联合通过率。不同指标必须分别命名，不能都叫 CSR。
- 指标纠偏：CodeIF 的 CSR 是题级全部约束满足率，Compact Constraint Encoding 的 CSR 是条件平均满足率，不能直接比较两个同名分数；详见分线报告原文核验。
- 后续机制：只有发现稳定的具体失败原因后，再设计局部反馈或生成边界；修复时保持既有约束也有邻近工作，不能预设创新。

## 4. 不宜作为唯一贡献的点

1. 形式规格加 LLM，再把验证错误返回模型：已有直接 vericoding 工作。
2. 用 JSON/清单代替自然语言：已有 Compact Constraint Encoding 等表示研究。
3. 约束越多越难：IntentCoding 已直接分析。
4. 限制生成语法或类型：SyGuS、类型约束解码已有成熟方向。
5. 配置到代码首次使用 LLM：SDSM 已有直接对标；模板也必须纳入比较。
6. 加入回归检查以保留已满足约束：[CIT-CAD](https://arxiv.org/abs/2609.07434) 的 CAD 场景及 [COVER](https://journals.sagepub.com/doi/10.3233/FAIA260737) 的约束建模场景已有相近研究。它们任务不同，但足以说明不能仅以组合这些部件宣称新颖性。

## 5. 最短准备与发表路线

建议优先级依据现有工程条件：A 最容易复用本地框架；B 最贴近“配置项到代码”的业务问题，但数据与语义建设更重；C 可从普通语言切入，但文献密集，必须细化失败机制。

执行顺序（建议）：

1. 选一条任务定义，精读三篇直接对标的 task/method/evaluation/limitations。
2. 建立“已有工作—拟增加的证据—如何检验”差异表，并继续定向检索最近邻。
3. 先审计公共数据是否可用，选少量开发题估计难度、成本和检查器可信度；不把 pilot 题数当统计充分性依据。
4. 根据 pilot 冻结主比较、测试集、预算及样本量策略；同任务配对、按来源隔离，报告不确定性与成本。
5. 先写实验图表和方法，再写引言；明确贡献是经验发现、评测资源还是新机制。

渠道定位只表示主题匹配，不表示录用预测或当前可投稿窗口：

- 测试、分析、验证反馈、生成可靠性，可先对标 [ISSTA 的研究范围与研究/经验/复现类别](https://conf.researchr.org/track/issta-2026/issta-2026-research-papers)。
- 模型/配置到代码、模型变换及其质量保证，可对标 [MODELS](https://conf.researchr.org/track/models-2026/models-2026-research-papers)。
- 产品线、复用和配置研究，可进一步查看 [VARIABILITY](https://conf.researchr.org/track/variability-2026/variability-2026-papers)。
- 本次引用的 2026 征稿页用于理解范围；下一轮具体期限和轨道需另核验。

## 6. 分线检索记录

- [规约/可验证代码生成](CONDITIONAL_CODEGEN_SPEC_2026_10_06.md)
- [配置与环境条件](CONDITIONAL_CODEGEN_CONFIG_2026_10_06.md)
- [实现约束与指令遵循](CONDITIONAL_CODEGEN_CONSTRAINTS_2026_10_06.md)

与既有材料关系：保留原有实验设计和历史结果，本文件用于文献定位，不改变实验协议或宣称任何旧结果已复验。
