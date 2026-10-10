# 给定形式规约的代码生成：文献核验与小选题边界

核验日期：2026-10-06。范围：formal specification、contract、verified code generation、CEGIS；只用作者论文、作者项目和出版方作为事实来源。本轮阅读摘要及与任务、方法、验收相关章节，未复现实验、未调用付费模型。工作区及目标目录父级未发现 AGENTS.md。旧 `GENERATION_RELATED_WORK.md` 仅作检索线索。

## 先固定任务定义

这里最直接的任务是：**输入固定的接口与前/后置条件，生成原先缺失的可执行实现及证明材料；规格不能被候选答案改弱。** 必须分别报告：代码生成（没有原实现）、证明补全（已有实现）、规约生成（从自然语言或已有代码生成契约）。这些任务的成功率不能互相替代。VERINA 将这些任务及组合明确拆开，是很好的定义依据。[VERINA §4](https://arxiv.org/html/2505.23135v3#S4)

## 六篇最贴近工作

### 1. AlgoVeri: An Aligned Benchmark for Verified Code Generation on Classical Algorithms

- **年份/venue：** 2026，ICML 2026，PMLR 306，已由正式论文集核验。
- **条件输入 → 输出：** 同一组经典算法的固定功能契约、接口及环境 → Dafny/Verus/Lean 实现与所需证明材料；属于真正代码生成。
- **验收：** 相应形式验证器接受；论文比较不同语言、模型及迭代修正轨迹。
- **作者已做：** 77 个经典算法在三种验证体系下对齐功能契约，研究跨语言性能、测试时计算量与错误类型。不能再把“三种语言上的规约生成比较”或“一般验证反馈迭代”作为独立新机制。
- **公开资产：** 官方论文集直接链接 [作者仓库](https://github.com/haoyuzhao123/algoveri)，含 `algoveri_data`、验证环境与运行脚本；本轮已读 README，未运行。
- **来源：** [ICML 正式论文页](https://proceedings.mlr.press/v306/zhao26bm.html)、[论文全文](https://arxiv.org/html/2602.09464v1)。

### 2. VERINA: Benchmarking Verifiable Code Generation

- **年份/venue：** 首版 2025；正式为 **ICLR 2026**，不是仅预印本。旧笔记中的预印本状态已过时。
- **条件输入 → 输出：** 其 specification-guided 子任务输入自然语言、签名与参考规格，输出代码与证明；另有 CodeGen、SpecGen、ProofGen 和其他组合，必须明确选用哪一轨。
- **验收：** CodeGen 用测试；ProofGen 用 Lean 检查且拒绝证明占位符；端到端轨还要求对参考规格证明，避免生成的代码和规格相互迁就。
- **作者已做：** 189 项人工整理 Lean 任务，分离评估代码、规格、证明及其组合；“同时看规格质量与代码正确性”已被覆盖。摘要的 4.9% 是单次 ProofGen 成绩，不能标成固定规格代码生成整体成功率。
- **公开资产：** [作者仓库](https://github.com/sunblaze-ucb/verina)、[作者数据集](https://huggingface.co/datasets/sunblaze-ucb/verina)，含任务、参考材料和测试。
- **来源：** [ICLR 正式论文页](https://proceedings.iclr.cc/paper_files/paper/2026/hash/41b8c80f9113b9f8e2e129447221682a-Abstract-Conference.html)、[v3 全文 §4–5](https://arxiv.org/html/2505.23135v3)。

### 3. A benchmark for vericoding: formally verified program synthesis

- **年份/venue：** 2025，arXiv:2509.22908；本轮未核到正式录用，作者仓库仍写 undergoing review，按预印本引用。
- **条件输入 → 输出：** 固定形式规格与上下文、实现占位区域 → Dafny/Verus/Lean 实现及辅助证明；主任务属于真正代码生成，另有纯验证比较。
- **验收：** 编译/验证反馈驱动多轮生成修正，最终排除 `sorry`、`assume` 等绕过；形式成功仅相对于给定规格。
- **作者已做：** 汇集 12,504 个规格，跨三个体系，评估现成模型与自然语言描述的附加作用；不是提出第一个“LLM＋验证器”循环。
- **数据注意：** 发布集合保留不完整、不一致或不可编译规格供规约修复研究，实验采用清理后的适用子集；12,504 不能直接当成全部可靠测试题数。论文还讨论重复和占位默认值。
- **公开资产：** [作者仓库](https://github.com/Beneficial-AI-Foundation/vericoding-benchmark)，含规格、JSONL、质量元数据和结果 CSV。
- **来源：** [摘要](https://arxiv.org/abs/2509.22908)、[全文 §3 与质量分析](https://arxiv.org/html/2509.22908v1)。

### 4. AxDafny: Agentic Verified Code Generation in Dafny

- **年份/venue：** 2026-06-30，arXiv:2606.32007；本轮只确认为预印本。
- **条件输入 → 输出：** 自然语言题目、Dafny 方法签名及固定规格 → 实现、循环不变式、断言、终止性材料。LCB-Pro-Dafny 是代码＋证明生成；DafnyBench 结果是已有代码的证明补全，不能混用。
- **验收：** Dafny 验证为主，禁止改弱固定定义/规格及证明绕过；再编译成 Python 跑原 LiveCodeBench-Pro 测试和时间限制。
- **作者已做：** 验证器引导的修正框架及 250 题 LCB-Pro-Dafny；已分析“验证成功但运行资源不达标”的差别，已经做过规格审查与部分平凡实现突变检查。
- **公开资产：** 论文声明公开 [Axiomatic-AI/ax-dafny](https://github.com/Axiomatic-AI/ax-dafny)，含代码、规格及双重验收 harness；本轮 GitHub 打开失败，公开资产为论文声明，未独立检查内容。
- **来源：** [摘要](https://arxiv.org/abs/2606.32007)、[全文 §Software and Data、Appendix A](https://arxiv.org/html/2606.32007v1)。

### 5. P³: Joint Program-and-Proof Planning for Verified Code Generation

- **年份/venue：** 2026-08-10，arXiv:2608.09277；本轮只确认为预印本。
- **条件输入 → 输出：** 只读形式规格、函数接口及算法要求 → 联合程序/证明计划、Lean 实现与证明。属于真正代码生成。
- **验收：** Lean 检查通过且满足算法指令；不允许通过替换算法或非计算见证逃避要求。
- **作者已做：** 先共同规划程序结构和证明结构，再实现并证明；在 VERINA、AlgoVeri、Lean4Commit0 上比较普通 agent、先程序后证明、仅程序规划等。Lean4Commit0 已包含库级核心 API 束和跨 API 关系规格，不能说现有工作只有单函数。
- **实验边界：** 论文采用相同预算和环境；每个任务×模型×方法只跑一次，未估计任务内随机方差。其成本分析针对困难子集，不能直接当全体平均节省。
- **公开资产：** 全文给出 [Figshare 快照](https://figshare.com/s/2ab7020cacaffcf0d258)，称含提示、环境、harness、数据和运行元数据；本轮链接打开失败，未独立检查包内容。
- **来源：** [摘要](https://arxiv.org/abs/2608.09277)、[全文 §3–5、Appendix E](https://arxiv.org/html/2608.09277v1)。

### 6. Guiding Enumerative Program Synthesis with Large Language Models

- **年份/venue：** 2024，CAV 2024，LNCS 14682:280–301，已由 Springer 正式章节核验。
- **条件输入 → 输出：** SyGuS 逻辑约束及语法限制 → 满足规格的函数表达式/程序；部分实验涉及不变式合成，后者属于证明材料生成，不能与可执行函数生成混计。
- **验收：** CEGIS 中由 SMT 检查候选，失败则回传反例；以求解成功与时间等评估。
- **作者已做：** 从 LLM 错误候选建立概率语法，引导枚举；进一步在搜索中请求 LLM helper functions，动态更新搜索引导；与均匀枚举及 cvc5 比较。这直接否定“加入反例迭代/LLM＋传统合成”本身的新颖性。
- **公开资产：** 使用公开 SyGuS 竞赛问题；本轮未从论文/出版方核到作者实现下载入口，不等于没有公开代码。实施此路线前需补查 artifact 并确认可运行。
- **来源：** [出版方全文与 venue](https://link.springer.com/chapter/10.1007/978-3-031-65630-9_15)、[作者预印本全文](https://arxiv.org/html/2403.03997v2)。

## 两个可检验的小题候选

以下是基于本轮六篇的研究假设，**不是已确认无人做过的空白，也不保证可发表**。先补关键词检索，再用小规模预实验判断效应与成本。

### 候选 A：等价契约表示对固定规格代码生成的影响

**问题：** 同一语义的规格，拆分/合并 `ensures`、定义辅助谓词、等价量词表达，会否改变生成成功率和验证成本？可否用可证明等价的规范化减少这种波动？

**小范围设计：** 选 30–50 个清理后的 Dafny 任务，每题构造少量契约变体，并先机器检查等价；保持接口、问题语义、模型、token/反馈次数一致。对比原规约、随机等价变体、确定性规范化，分开记录运行测试正确率、形式通过率、验证耗时与生成成本；进行配对比较和多次重复。

**需要避免的混淆：** 等价表达可能改变 SMT 求解难度。应对固定参考实现也跑同样变体，分别分析“模型生成改变”和“验证器更容易”两个来源；不能把后者全归功于生成方法。

**与已有工作的边界：** AlgoVeri 已控制跨语言功能契约；VERINA 已比较规格输入价值；本候选拟专门控制同语言、同语义、仅表示变化的因果效应。本轮未系统检索 specification paraphrasing、metamorphic testing、verification-condition normalization 文献，尚不能认定新颖。[AlgoVeri](https://proceedings.mlr.press/v306/zhao26bm.html)、[VERINA §4](https://arxiv.org/html/2505.23135v3#S4)

### 候选 B：固定预算内，失败证据怎样决定改代码还是改证明

**问题：** 在固定且经过审查的契约下，先把失败归成编译错误、有可执行反例的功能错误、尚无反例的证明未闭合，再限制本轮可编辑区域，是否比每轮同时重写代码和证明更省预算？

**小范围设计：** 仅使用一个语言和 30–50 个带参考实现/测试的任务；比较无分类联合修正、确定性规则分流、模型分类分流。每次失败保留当前实现，通过具体反例执行检查辅助功能错误判断；没有反例时标为“未确定”，不能武断认定代码正确。统一总 token、验证器时间和最多修正轮数，分类调用也计入成本。

**指标：** 固定预算内正式通过率、对已正确实现的破坏率、无效重写次数、代码与证明各自的编辑量、重复试验方差。

**撞车风险很高：** AxDafny 已做验证器修正，P³ 已分析先程序后证明的低效并做联合规划；若只是换一个诊断 prompt，不足以支撑贡献。需要证据显示可复用的失败分类、可验证的编辑约束及受控消融带来独立效应，并继续排查 error localization、repair routing、proof-aware synthesis。若预实验无稳定收益，应及时放弃。[AxDafny](https://arxiv.org/html/2606.32007v1)、[P³](https://arxiv.org/html/2608.09277v1)

## 最新邻近线索与投稿前检查

Vero（arXiv:2608.13522）作者项目已经公开**仓库级**代码＋证明模式以及纯证明模式、固定接口/规格、独立重建和规格缺陷审计；因此“把契约生成搬到真实仓库”不能直接视作空白。只做项目/摘要级核验，未纳入本轮六篇精读范围；作者主页有 NeurIPS 2026 标注，但本轮未独立核验会议录用页，引用时保守按预印本并注明来源。[作者项目](https://vero.verina.io/)、[作者论文](https://arxiv.org/abs/2608.13522)、[Berkeley 官方说明](https://rdi.berkeley.edu/blog/vero/)

建议最先细读 **AlgoVeri（对照任务）→ AxDafny（Dafny 方法强基线）→ P³（最近的方法撞车）**；用 VERINA 校正任务分类，若走受限 DSL/逻辑合成则必须加入 CAV 2024 与 cvc5/传统枚举基线。不得以纯 ProofGen 的提升代替条件代码生成贡献。
