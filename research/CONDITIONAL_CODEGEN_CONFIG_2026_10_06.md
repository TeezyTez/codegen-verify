# 配置与运行环境条件驱动代码生成：定向证据核查（2026-10-06）

范围：区分配置作为生成输入、运行环境作为约束、配置文件作为生成输出。优先核查原始论文、出版商和作者项目；不是系统综述，也不声称以下小问题无人研究。未运行模型或付费实验。检查了工作区和上级目录，未发现适用于本目录的 AGENTS.md；沿用 research 目录的证据/建议分离约定。

## 判断

**“给配置生成代码”已有成熟传统路线，也已有直接 LLM 对标。** 若配置的语义和映射规则已完整给定，模板或程序式生成器必须作为强基线。比较值得测试的是：改变配置或组合已知特征时，生成器是否同时满足新条件、保留不受影响的行为，以及验证反馈能否定位交互错误。这里的研究价值需要实证证明，不能用“配置比自然语言更结构化”代替。

| 类别 | 条件输入 → 输出 | 关键区别 |
|---|---|---|
| A. 产品/业务配置生成 | feature model、特征选择、领域模型或简单数据结构 → 程序变体 | 配置决定业务功能；SDSM、PRICES、FeatureC++ 属于这条线 |
| B. 环境约束下生成 | 业务需求 + 依赖库版本、平台等 → 在目标环境正确执行的代码 | API 版本是运行条件；LibEvolutionEval、GitChameleon 2.0 属于这条线 |
| C. 配置文件生成 | 自然语言意图 + 可选已有 YAML → YAML/IaC | 配置本身是输出；CloudEval-YAML 不能作为“读取业务配置生成程序”的直接证据 |

硬件、内存、时延和部署条件也属于 B，但和 API 版本需要不同的可执行验证器。本次重点核对业务配置与版本条件，未把 GPU kernel 优化成绩外推为任意部署约束满足能力。

## 六项最相关一手证据

### 1. SDSM：最直接的近期 LLM 对标

**Large Language Model as a Code Generator in Simplified Domain-Specific Modelling**，Adam Bochenek、Jarosław Protasiewicz、Witold Pedrycz，2026。**SSRN 预印本**，2026-05-23 发布；未核验到正式 venue。

- 条件输入：简单数据结构与明确实现步骤；方法主张不必设计 DSL。
- 输出：业务应用的源代码，把 LLM 当作流程中的代码生成器。
- 验证：摘要确认两项真实场景实验，比较 LLM、模板生成和程序式生成，考察代码质量与生产率。
- 代码/数据：本轮未核验到公开复现包；没有据摘要虚构测试规模、正确率或形式保证。
- 撞车含义：仅提出“JSON/配置交给 LLM 替代模板”已非常接近。摘要不足以确认其是否覆盖未见配置组合、反事实配置变更或形式验证。

[SSRN 原始摘要与元数据](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6818764)。直接打开失败，但 exact-title 搜索返回完整原始摘要；上述方法和基线信息均在摘要中。

### 2. PRICES：配置选择到可执行业务系统的强传统基线

**End-to-end development of product lines for web systems**，2025，**International Journal on Software Tools for Technology Transfer 27:201–219**，2025-04-08 正式发表。

- 条件输入：feature model、UML-DOP/IFML 模型、特征选择，以及核心/增量模块的实现。
- 输出：按特征生成 Java 后端、JavaScript 前端和相应数据库结构；配置知识决定增量模块的应用。
- 验证：AISCO 真实案例、自动生成比例和用户可用性评价；这不等于穷尽验证所有配置组合。
- 边界：领域开发阶段仍须手工补充 ABS 桩中的业务实现，之后才按选择派生产品；不能写成“任意配置零人工生成完整系统”。
- 代码/数据：论文明确公开工具、源码、模型和可用性评价原始资料。

[出版商论文及数据声明](https://link.springer.com/article/10.1007/s10009-025-00784-3)；[原文 §3.2、§4、§6](https://link.springer.com/content/pdf/10.1007/s10009-025-00784-3.pdf)；[作者工具与模型](https://gitlab.com/RSE-Lab-Fasilkom-UI/prices-2)。

### 3. FeatureC++：特征交互不是 LLM 时代才出现的问题

**Code Generation to Support Static and Dynamic Composition of Software Product Lines**，2008，**GPCE 2008**，页 3–12。

- 条件输入：特征模型、特征选择、模块化实现，以及静态/动态组合方式。
- 输出：从同一代码库生成/组合 C++ 产品，支持部署时选择组合方式。
- 验证：检查配置合法性，并自动应用预先实现的特征交互代码；论文还比较性能与内存开销。
- 代码/数据：原文指向 FeatureC++ 实现，但本轮未验证旧下载站仍可运行，也未确认现代可复现实验包。
- 边界：自动选择交互代码不等于自动发现交互语义，更不等于生成器能处理任意新特征。

[作者托管原文](https://www.se.cs.uni-saarland.de/publications/docs/GPCE2008dynamic.pdf)；[作者发表清单](https://www.se.cs.uni-saarland.de/apel/pubs-complete.php)。它是“配置组合/feature interactions”必须承认的旧工作。

### 4. LibEvolutionEval：依赖版本条件的已发表基线

**LibEvolutionEval: A Benchmark and Study for Version-Specific Code Generation**，2025，**NAACL 2025 主会长文**，页 6826–6840。

- 条件输入：代码上下文、目标库版本，以及可选的版本对应 API 文档；覆盖八个库。
- 输出：行内代码/API 表达式补全。
- 验证：论文主指标为提取出的 API 表达式 F1，文档检索为 MRR；不能称为完整执行正确率。官方实现也有 exact match/edit similarity 等计分功能。
- 代码/数据：官方仓库公开数据、检索器、生成与评分流程。
- 撞车含义：版本提示、按版本检索文档与代码补全的比较已做过；仅将版本号加入 prompt 不构成充分新意。

[ACL 正式论文](https://aclanthology.org/2025.naacl-long.348/)；[原文 §2–3](https://aclanthology.org/2025.naacl-long.348.pdf)；[官方代码与数据](https://github.com/amazon-science/LibEvolutionEval)。

### 5. GitChameleon 2.0：最适合直接复用的可执行版本条件任务

**GitChameleon 2.0: Evaluating AI Code Generation Against Python Library Version Incompatibilities**，2025 年预印本，**ACL 2026 主会长文**；本轮已用 ACL Anthology 核验正式状态。

- 条件输入：功能题目、代码上下文和指定 Python 库版本。
- 输出：在指定版本下完成任务的 Python 代码。
- 验证：328 道任务；作者原文描述 26 个库，提供可见测试用于反馈、隐藏测试用于评分，执行检查功能正确性。
- 代码/数据：官方仓库公开任务和评测 harness。
- 撞车含义：版本条件生成、RAG、自调试、Agent 和代码助手均已比较。新实验需要明确不同的干预或失效机制，不能重新做一遍排行榜。

[ACL 2026 正式条目](https://aclanthology.org/2026.acl-long.2170/)；[作者预印本 §2](https://arxiv.org/html/2507.12367v2)；[官方代码与任务](https://github.com/mrcabbage972/GitChameleonBenchmark)。

### 6. CloudEval-YAML：用于划清“生成配置”的边界

**CloudEval-YAML: A Practical Benchmark for Cloud Configuration Generation**，2024，**MLSys 2024**。

- 条件输入：自然语言需求和可选 YAML 上下文。
- 输出：新建或修改后的云配置 YAML。
- 验证：1011 道人工编写任务，每题带单元测试；也研究精简、缩写及双语需求表述。
- 代码/数据：官方仓库和作者数据集可访问。
- 边界：它研究的是配置输出。其测试方法可借鉴，但不能用它证明 feature-model-to-program 或业务配置到程序的效果。

[MLSys 原始论文条目](https://proceedings.mlsys.org/paper_files/paper/2024/hash/554e056fe2b6d9fd27ffcd3367ae1267-Abstract-Conference.html)；[官方代码](https://github.com/alibaba/CloudEval-YAML)；[作者数据集](https://huggingface.co/datasets/ai4cloud/CloudEval-YAML)。

## 两个可执行的小选题（研究建议，尚未实验）

### A. 配置变更时的符合性与回归：优先推荐的业务配置方向

问题：只修改一项合法配置时，LLM 是否修好受影响行为，同时破坏未变化行为？把“配置生成是否成功”细化成“变更关系是否正确”。

最小设计：选择两个易建立独立 oracle 的内存数据处理领域，例如记录归一化/去重、分组/稳定排序。各建 8–12 个任务家族，每家族 4–8 个有效配置；配置覆盖缺失值策略、键比较、重复处理、排序等交互。明确非法组合，并按任务家族划分开发与测试，另外留出特征组合。先人工审计 10 个变更对，确认测试能分别捕获应变/不应变行为，再扩大。

比较：确定性模板/程序式生成器作为语义 oracle；LLM 从头生成；基于旧代码的配置变更；变更时加公开契约和有针对性的验证反馈。测试或契约应由可信规则确定，不能让被测模型同时自由修改规范。若接现有 Dafny 框架，所有组必须看到相同固定契约。

指标：新配置执行/验证成功率、变更对同时正确率、未受影响行为回归率、非法配置拒绝率、tokens 与验证成本；按家族聚类统计。模板预期达到高正确率，其作用是揭示 LLM 引入了什么成本和失效，不应人为削弱模板以获得胜率。

撞车风险：SDSM 已做 LLM 与模板比较，SPL 已长期研究交互；这里最多先定位为受控经验分析。还需继续查 configuration-aware regression、metamorphic testing、LLM feature interaction，确认是否已有同样的配置变更协议。风险为中高；不能把换成 JSON 或加反馈单独写成创新。若所有错误只是一般代码错误而非配置交互，应承认配置没有带来独立机制。

### B. 版本条件冲突下，模型是否悄悄修改环境而非满足条件

问题：在目标依赖已冻结时，模型是否通过升级版本、修改依赖声明或转用不允许的 API 来“通过”可见测试？这与只测 API 名称命中不同。

最小设计：从 GitChameleon 2.0 选 20–30 个可稳定构建的任务，冻结环境并保留隐藏测试。比较只给版本号、给对应版本文档、给有版本标记但不适配的文档三种条件；后者必须明确作为受控冲突，不冒充官方推荐上下文。先用现成候选或少量本地模型做环境可复现检查。Agent 组记录每一次依赖改动，但最终在独立的冻结环境重跑。

指标：冻结环境功能成功率、版本/API 违约率、错误文档服从率、尝试修改环境的比例及成本。既有单库版本数据即可起步；多库兼容矩阵另作后续，避免依赖冲突使评测本身成为主工作。

撞车风险：GitChameleon 已含 Agent、自调试、RAG，LibEvolutionEval 已含版本文档；2026 年版本兼容评测持续增加，重复普通版本检索实验风险高。可取差异是独立冻结环境判定与环境修改轨迹分析，但是否新颖仍待更完整相关工作核查。

## 推荐顺序与未核验事项

若用户重点是业务配置，优先 A：以 SDSM 为最近直接对标，以 PRICES/FeatureC++ 说明传统强基线，以“配置变更引发的行为回归”收紧问题。若优先尽快做可复现实证，B 的数据与执行框架更现成，但其新颖性风险也更高。

最强三项分别是 **SDSM（直接 LLM 配置/模型生成对标）**、**PRICES（实际配置派生与传统实现）**、**GitChameleon 2.0（可执行的环境条件评测）**。它们代表不同问题，不能合并计算效果。

限制：没有完整复现任何工具；SDSM 仅核验原始摘要；公开仓库可访问不代表旧环境可重建；本轮未证明不存在其他更接近的配置变更研究。以上实验规模是建议预算，不是已获数据或已验证可运行数量。
