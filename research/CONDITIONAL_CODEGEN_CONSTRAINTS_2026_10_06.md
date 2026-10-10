# 显式约束下的 LLM 代码生成：论文核验与候选小选题

核验日期：2026-10-06。仅使用原论文、会议/期刊页与作者项目；未运行模型、未安装依赖、未做付费实验。检查工作区及祖先路径，未找到适用的 AGENTS.md。本报告是定向快速检索，不能证明研究空白。

## 判断

这个方向已经形成独立文献群。多约束生成、约束依赖、全部满足率、约束数量曲线、不可行复杂度识别和约束表达格式均已有直接工作。更稳妥的切口是：在明确的程序语言子集与可信验收器下，隔离“条件数量”与“条件相互作用”，或定位多个条件共同造成的最小冲突，而不是再提出一个泛化的多约束 benchmark。

优先精读三篇：**CodeIF**（约束分类、依赖及联合满足指标）、**IFEvalCode**（功能正确与指令遵循分开验收，公开评测代码）、**IntentCoding / CodeConstraints**（2026 年最直接的数量操控与推理时改进）。若选资源约束，C3E 应替代其中一篇作为首读。

## 七篇核心文献

### 1. CodeIF: Benchmarking the Instruction-Following Capabilities of Large Language Models for Code Generation

- 年份/状态：2025，ACL Industry Track；[会议正式页](https://aclanthology.org/2025.acl-industry.89/)。方法细节核验自[预印本正文](https://arxiv.org/html/2502.19166v1)。
- 输入条件：任务说明加原子约束及依赖，覆盖全局、结构、变量、接口、函数、类、文件、组合八类；数据涉及四种语言。
- 输出：符合这些说明的代码，也包含调试、重构、解释等任务场景。
- 验收：把原子约束判成满足/不满足；CSR 统计一题全部满足，SSR 统计平均满足比例，RSR 纳入先决约束。正文讨论 LLM 自动评价及人工一致性，**不能把它描述成全部由 AST/执行测试确定的形式验证**。
- 公开资产：[作者仓库](https://github.com/lin-rany/codeIF)含数据与评测流程。
- 对选题的限制：“研究依赖关系”或“提出联合满足率”本身已经有直接先例。

### 2. IFEvalCode: Controlled Code Generation

- 年份/状态：2025，当前核验到 arXiv 预印本；[论文](https://arxiv.org/abs/2507.22462)、[正文](https://arxiv.org/html/2507.22462v2)。未据此认定会议录用。
- 输入条件：自然语言编程问题加风格、结构、命名等可检查条件，中英双语。
- 输出：代码；提出前向/后向条件生成与训练流程。
- 验收：代码正确性 Corr. 与指令遵循 Instr. 使用不同检查函数，在沙箱执行。这比只看是否跑通更接近用户问题，但检查通过仍只证明给定检查范围。
- 公开资产：[官方代码及数据](https://github.com/CSJianYang/IFEvalCode)。正文表 1 为 810 个问题各有中英文，共 1,620 条语言版本；列出八种编程语言（含 PHP）。摘要、正文不同位置的语言数/样本表述有不一致，引用数字时应以表格及发布数据为准。
- 边界：作者明确说明缺少更复杂及仓库级的受控生成评测。

### 3. IntentCoding: Amplifying User Intent in Code Generation（正文写作 Intent↑Coding）

- 年份/状态：2026，Findings of ACL；[正式页](https://aclanthology.org/2026.findings-acl.1662/)、[正式 PDF](https://aclanthology.org/2026.findings-acl.1662.pdf)。
- 输入条件：CodeConstraints 操控数据类型、返回集合类型、长度、值域四类条件及数量。
- 输出：实现这些要求的程序。方法通过移除意图的对照预测及不同强度集成，在解码时放大意图影响；不是语法硬屏蔽。
- 验收：CodeConstraints 以全部条件满足算正确，并另在 IFEvalCode、HumanEval、LiveCodeBench 测试。已直接研究二至四条件的性能变化。
- 公开资产：论文和构造规则公开；本轮未核验到作者代码/数据发布链接，不等于未发布。
- 对选题的限制：“多放几个条件看性能下降”已高度重合。扩展到工程限制、控制难度混杂和分析交互，才值得进一步核查差异。

### 4. Type-Constrained Code Generation with Language Models

- 年份/状态：2025，PLDI；[官方会议页](https://pldi25.sigplan.org/details/pldi-2025-papers/25/Type-Constrained-Code-Generation-with-Language-Models)、[论文](https://arxiv.org/abs/2504.09246)。
- 输入条件：代码生成上下文与类型系统约束；理论在简单类型语言上展开，工程扩展到 TypeScript。
- 输出：受类型约束的代码；增量解析器与 prefix automata 判断部分程序是否还能补成类型合法程序，并用于限制采样。
- 验收：类型/编译错误，以及 HumanEval、MBPP 的功能表现；涉及合成、翻译、修复。
- 公开资产：[复现仓库](https://github.com/eth-sri/type-constrained-code-generation)含实现与实验。
- 边界：类型保证限于其形式化/实现覆盖范围；类型合法并不蕴含排序正确、不泄露秘密、满足时间复杂度或全部自然语言要求。

### 5. Complexity-Constraint Code Evaluation: A Benchmark for Time Complexity Compliance in LLM-Generated Code（C3E）

- 年份/状态：**2026 正式发表**，Journal of Computer Science and Technology 41(3):910–923；[期刊页](https://jcst.ict.ac.cn/article/doi/10.1007/s11390-025-5518-5)。DOI 中的 025 不能当作发表年份。
- 输入条件：编程问题及显式时间复杂度要求，包含可行要求和理论不可行要求。
- 输出：程序；不可行情形还检查模型是否识别不可能性。
- 验收：功能正确性及复杂度合规，提出 CAS；复杂度部分基于理论分析而非直接把运行时间当作渐近复杂度。LLM/专家分析不应描述成通用自动复杂度证明。
- 公开资产：[作者代码和数据](https://github.com/wahaha12321/C3E)。
- 对选题的限制：“让模型识别不可能复杂度”已存在；多个工程条件共同冲突、最小冲突集定位是否未被覆盖，需要进一步查验。

### 6. Compact Constraint Encoding for LLM Code Generation: An Empirical Study of Token Economics and Constraint Compliance

- 年份/状态：2026，arXiv 预印本，4 月 v2；[摘要](https://arxiv.org/abs/2604.07192)、[正文](https://arxiv.org/pdf/2604.07192)。
- 输入条件：技术栈、依赖限制、架构模式，以自然语言或紧凑结构头表达；也比较约束在多阶段流程中的传递方式。
- 输出：代码；检查正常约束与违背模型常见习惯的约束。
- 验收：规则式源码检查；文中 CSR 为六个条件的**平均**满足比例。实验未检测到编码方式带来的显著合规提升，主要收益是省 token；这是受测条件下的零结果，不是所有格式等价的证明。
- 公开资产：[作者补充材料](https://github.com/EricT-Creator/CodePrompt-DSL)含提示、规则、结果和生成样本。
- 对选题的限制：仅比较自然语言、JSON/紧凑头等表示形式已明显重合。

### 7. Benchmarking Complex Instruction-Following with Multiple Constraints Composition（ComplexBench）

- 年份/状态：2024，NeurIPS Datasets and Benchmarks；[官方页](https://proceedings.neurips.cc/paper_files/paper/2024/hash/f8c24b08b96a08ec7a7a975feea7777e-Abstract-Datasets_and_Benchmarks_Track.html)。
- 输入条件：四类约束、十九个维度、四类组合方式组成的复杂自然语言指令。
- 输出：通用文本响应；**不是专门的代码正确性 benchmark**。
- 验收：规则增强的 LLM 评审，按组合对应的依赖结构聚合。
- 公开资产：[官方仓库](https://github.com/thu-coai/ComplexBench)含数据、评价代码与模型结果。
- 对选题的意义：约束组合与依赖结构的评估思想已成熟，代码研究应说明执行语义与可验证性带来的实质区别。

## 必须补查、避免混名的邻近工作

- **CodeAlignBench: Assessing Code Generation Models on Developer-Preferred Code Adjustments**（2025 预印本）：真实开发者偏好形成指令目录，既研究初始提示约束，也研究生成后追加修改；Python/Java/JavaScript；规则加 LLM 评审、结合原任务功能测试。涵盖性能、结构和可读性要求。[论文正文](https://arxiv.org/html/2510.27565v1)。本轮未确认最终会议录用或作者公开仓库，不能把“under review at ICLR 2026”写成 ICLR 录用。
- **CodeIF-Bench** 与 **CodeIF** 是两篇不同论文。前者研究交互式代码生成及静态/动态对话场景，检查跨轮指令遵循；[2025 预印本](https://arxiv.org/abs/2503.22688)、[代码和数据](https://github.com/zhu-zhu-ding/CodeIF-Bench)。跨轮遗忘也不能直接称为新问题。
- **Monitor-Guided Decoding of Code LMs with Static Analysis of Repository Context**（NeurIPS 2023）使用静态分析引导解码，覆盖类型一致的对象成员访问，并探索参数数量和有状态 API 协议。输入仓库上下文、输出方法补全，主要评价编译与参考匹配等；[正式页](https://proceedings.neurips.cc/paper_files/paper/2023/hash/662b1774ba8845fc1fa3d1fc0177ceeb-Abstract-Conference.html)、[官方代码及 PragmaticCode 数据](https://github.com/microsoft/monitors4codegen)。它说明“语义约束引导解码”早于本轮最新论文。
- **ComplexCodeEval** 的“复杂”主要指真实代码上下文和任务复杂度。它覆盖生成、补全、API 推荐、测试生成，不能据名字把它当成“多显式约束 benchmark”。[2024 预印本](https://arxiv.org/abs/2409.10280)、[作者数据仓库](https://github.com/ComplexCodeEval/ComplexCodeEval)。
- **CodeConqueror**：对准确名称及代码/LLM 组合检索后，本轮未找到可核验的原论文；不据此宣布该论文不存在，也不编造标题、venue 或功能。

## 语法、类型、语义不能混为一谈

| 层次 | 可以验收什么 | 不能直接推出什么 |
|---|---|---|
| 文法/格式约束 | 可解析、AST 形态、输出 schema | 类型正确、算法正确、无漏洞 |
| 类型/名称/API 约束 | 在覆盖的类型系统中合法、成员存在、协议允许的调用序列 | 实现任务含义、资源界限、任意安全性质 |
| 可执行行为约束 | 给定测试集、性质测试或限定模型中的规格 | 未覆盖输入上的完整正确性 |
| 非功能约束 | 禁止库/构造、复杂度、预算、特定安全性质 | 一种验收器能统一证明所有要求 |

这是根据上述类型约束、monitor、IFEvalCode 和 C3E 的验收边界所作的方法性区分。尤其不要把字符串未出现 `sort` 当成禁止排序 API 的完整验证；别名、间接调用及跨函数行为会改变检查需求。禁止递归可先限定到无反射、无动态分派的语言子集，再定义调用图上的检查。资源限制还应区分实测耗时/内存预算与渐近复杂度。安全条件应具体化，例如禁止特定危险 API 或限定数据流属性，不能只用“代码安全”作标签。

## 两个可以缩小后开展的选题

### A. 相同条件数下，工程约束的相互作用是否额外损害联合满足率？

候选任务：只做 Python 函数级，在 30–50 个小问题中选择可判定的限制，例如不能调用指定 API、不能递归、输入不能修改、输出保持某种次序。为每题设计 1/2/3 条条件，以及相同数量但不同交互强度的条件组合；每个可行组合提供已验收的参考实现。保持问题、条件长度和模型预算尽量可比，随机条件顺序。

核心比较：直接生成、显式清单、外部检查后有限次数修复；若有条件再加入 IntentCoding。先测每个条件的边际通过率，再测全通过率；不能仅凭全通过率随条件增加下降，就宣称出现组合推理缺陷，因为即使独立错误也会造成下降。用同题配对比较、分层 bootstrap，分析相对“独立边际成功率乘积”的偏差，但不能把该乘积基线误当作已证实的因果模型。

候选贡献在于可执行工程限制的交互隔离、验收器误差审计，以及功能正确和约束全通过的联合结果。**这只是待验证的差异点**：CodeIF 已有依赖，ComplexBench 已有组合，IntentCoding 已有数量操控；正式开题前必须逐项对比。

### B. 多条件共同不可行时，模型能否输出最小冲突集，并在最小修订后生成正确代码？

先用有限、可判定的小规格空间；例如有限值域、集合类型、精确长度、元素唯一性等，构造每个条件单独可行、组合不可行的实例。冲突必须由枚举或约束求解给出证据，不能由模型自称不可行。增加若干已知可行但不符合模型默认习惯的对照，防止模型一看到困难条件就拒绝。

输出协议：可行则生成代码；不可行则返回冲突条件编号和最小修订。验收包括可行性分类、误拒率、冲突集有效性及包含意义下的最小性、修订后功能及全部条件满足率；时间和 token 用量单列。仅将“不可行”回答评分为正确不够。

候选贡献是“多条件共同冲突 + 可核验最小核心 + 修订后代码”这一完整链条。**不是新颖性证明**：C3E 已测试不可行复杂度，CodeConstraints 已覆盖类型/长度/值域，必须继续检索 unsatisfiable specifications、inconsistent requirements、minimal unsatisfiable core 与 LLM synthesis 文献；若撞车，可转向验收器稳健性和误拒控制。

## 推荐统一记录的指标

设功能测试通过为 F、各显式约束检查为 C1…Ck：分别报告功能通过率 E[F]、逐条件平均通过率 E[mean(Cj)]、全条件满足率 E[prod(Cj)]、**功能且全部条件通过率 E[F·prod(Cj)]**。另记录语法/类型失败、生成中断、执行器故障与无法判定，避免把基础设施错误都归入模型错误。

CodeIF 的 CSR 指全部约束同时满足；Compact Constraint Encoding 的 CSR 指条件平均满足。这两个分数不能直接横向比较。解码方法还需说明是否能访问 logits、是否支持闭源 API，以及额外推理/修复开销。

最值得先做的是小规模数据与验收器审计，而不是立即扩展模型排行榜。本报告没有运行这些候选实验。
