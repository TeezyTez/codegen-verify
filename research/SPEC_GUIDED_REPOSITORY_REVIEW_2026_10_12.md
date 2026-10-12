# 规约参与大规模代码生成：研究定位与近期证据

检索日期：2026-10-12。类型：单人、定向叙述性文献检索，不是穷尽性系统综述。以下数字均为论文报告，未独立复现实验。本次阅读了所列论文的 HTML 方法、结果或局限部分；会议状态只在有一手记录时标注。

## 正确的研究对象

研究规约在多模块、跨文件代码生成中的介入位置和使用机制：生成前约束、生成中检查、最终核验、反馈修复。规模应按生成的系统、模块依赖与跨模块行为衡量，不能把大量独立算法题算作大型系统生成。

区分三种规约：结构化需求/设计描述，接口与行为契约，可机器检查的逻辑规约。前者可参与规划和提示；后两者可产生检查或证明义务。也要区分从零生成仓库、在已有仓库修复局部代码，以及已有实现的证明补全。

## 直接相关证据

| 工作与一手来源 | 规约参与方式 | 已核验的进展与边界 |
|---|---|---|
| [RPG / ZeroRepo](https://arxiv.org/html/2509.16198)，2025-09 首稿，ICLR 2026；[作者仓库](https://github.com/microsoft/RPG-ZeroRepo) | 需求、文件、接口和数据流组成持久图；依赖顺序生成；单元、集成与回归测试；图辅助定位修复 | RepoCraft：6 个项目、1,052 个评测任务。表 2 的 o3-mini 配置测试通过率 69.7%，生成约 24K LOC；约 37K LOC 对应 Qwen3-Coder，不能把两者拼成一个配置。原仓库在该评测流程也仅 81.0% 通过，存在定位/测试适配测量限制。不是形式化全仓库证明。 |
| [Repo0](https://arxiv.org/html/2608.19854v1)，2026-08-20 预印本 | 需求图与组件图分别建模并对齐，先迭代调整架构，再用共同 TDD 流程生成 | 与 RPG 等使用相同下游生成、验证、修复流程。消融移除相邻需求上下文会损害通过率；移除依赖顺序在 statsmodels 上下降 30 个百分点。主表为 3 项目，另 3 项目在补充材料；仅 Python/RepoCraft。已覆盖“需求图+依赖生成”的宽泛主张。 |
| [PaperCompiler](https://arxiv.org/html/2609.02272v1)，2026-09-02 预印本 | 论文证据→需求→文件责任与依赖→局部文件契约；生成时传递上下游约束 | 90 篇论文；参考实现一致性评分 3.647→4.152。9 篇消融支持部分契约组件，但不同评分口径并不一致。作者明确：这些契约是生成指导，并非形式保证；未建立全部仓库可执行性或实验复现。 |
| [WiseSpec](https://arxiv.org/html/2609.00568v1)，2026-09-01；正文列 ASE 2026 SRC 论文标识 | 检索仓库证据，用需求 DSL 组织；由生成代码/测试的执行反馈修订需求 | 三种 SWE-bench 各抽 100 题。DeepSeek 下 Verified 子集 46%→51%，Pro 子集 24%→35%（对表中 Claude Code 框架基线）。是已有仓库 issue 修复，非从零构建；自生成测试是需求质量代理，不是完整语义保证。 |
| [Vero](https://arxiv.org/html/2608.13522v1)，2026-08-13 预印本 | 固定 API 与人工整理的 Lean 规约，联合生成多模块实现和证明 | 43 实例、743 API、2,705 规约；最强 code-and-proof 配置单规约通过 87.3%，完整通过 27/43。强调共享引理与全局不变量。原始来源仓库 LOC 不能充当实际新增实现 LOC；不是直接生成整个原语言生产仓库。 |
| [SWE-Proof](https://arxiv.org/html/2609.21190v1)，2026-09 预印本 | 为真实仓库修复构造规约与环境假设；比较自写规约、给定规约、验证等设置 | 正文 SWE-bench Verified 500 题；自写规约端到端未见稳定解题收益。提供整理过的规约后 Nagini 设置 85.0%→96.2%、81.2%→94.4%。已有定位控制仍有收益；但提供的是更强的语义信息，不是纯检查时机对照。环境公理和 Python/形式表示的一致性依赖审计，不等于全仓库形式证明。 |
| [CodeNova / VeriCodeBench](https://arxiv.org/html/2609.39568v1)，2026-09-30 预印本 | 原子需求形式化，保持生成规约，再生成代码与按验证反馈修复；同时衡量规约覆盖和代码验证 | 400 道 C/Java/Rust/Python 任务；聚合联合成功率 Direct 44.1%、CodeNova 49.1%。已有组合消融，因此“规约生成+验证修复闭环”本身不新。任务级评测，不是大型仓库生成。 |

## 辅助研究

- [SSDE](https://arxiv.org/html/2605.02455v1)，2026-05：三个 MVC 系统、五模型，比较领域模型、接口签名和 Gherkin 等输入。结构有帮助，但更结构化的行为文本并非始终更好；是先导研究。
- [DafnyComp](https://arxiv.org/abs/2509.23061)，[ICLR 2026 正文](https://openreview.net/pdf?id=y4kAMUBqLq)：300 个含 2–5 函数的组合程序，研究跨函数规约生成失败。属于组合性桥梁，尚非大仓库。
- [SpecCoder](https://arxiv.org/html/2607.04232v1)，2026-07：可执行中间断言为修复提供局部反馈；HumanExec 为竞赛程序。程序运行中的检查点与仓库逐步生成中的检查时机是两个不同概念。

## 综合判断与可检验问题

这条方向已有直接工作，也已经出现正面证据与重要反例。现有研究说明结构化要求、模块依赖和可靠行为规约可以帮助特定设置；并不说明增加规约、增加形式化程度、增加检查频率必然有益。

最接近用户目标的工程起点是 ZeroRepo / Repo0；PaperCompiler 提供需求到文件的约束传递方法；Vero 提供多模块形式保证的压力测试。不能用 SWE-bench 中的局部补丁成功率替代从零生成整仓库成功率。

候选窄问题：在相同且经过审查的跨模块行为契约下，生成阶段提前检查接口义务，是否比最终统一检查更能减少错误向下游传播？这是待研究问题，不宣称已证明新颖性。ZeroRepo 已有分阶段测试，必须把普通 TDD、契约语义、检查时机和反馈定位分别控制，不能只对比一个弱的直接生成器。

可识别实验：固定模型、需求、架构和契约信息，分阶段比较“只有契约提示”“最终契约核验后修复”“模块交接时检查同一契约”。再独立比较诊断反馈是否按依赖边定位。各组保留相同普通测试能力；预先规定工具暴露与预算；报告固定资源与达到目标质量的成本两种视角。使用独立冻结的最终验收，不以模型自己的测试作唯一裁判。

主要结果应是仓库级要求满足率、跨模块缺陷、错误被发现前影响的下游模块数、修复引入的回归，而非仅单函数证明通过率。按项目/任务族划分开发和留出集；同一仓库多个断言不能当作独立样本。

已有本地实验只覆盖编辑权限、证明补全和局部修复。PUBLIC_SCOPE 的两组均 18/18 且没有执行主体改写，既未支持额外选择器，也未检验上述大规模生成问题。其价值是验证基础设施和揭示测量风险；不足以否定或支持用户的主研究假设。

## 检索记录与局限

2026-10-12 使用网络学术检索发现记录，再访问 arXiv HTML、OpenReview 会议正文与作者仓库核对。未使用聚合摘要作为最终定量证据，未声称穷尽所有最新论文，未合并不同基准的百分比。

主要检索式（引号为原检索字符）：

```text
"specification" "repository-level" "code generation" 2026 verification
"specification-guided" "code generation" 2026 agent
"formal specifications" "agentic" "code generation" 2026
"Vero" "repository" "verification" arxiv 2026
"WiseSpec" arxiv
"specification" "incremental" "repository" "code generation" 2026
"compositional" "code generation" "contracts" LLM 2026
ZeroRepo Repository Planning Graph arxiv 2026
"specification" "code generation" "October" "2026" repository
"specification" "generation" "verification" "checkpoint" repository LLM
DafnyComp Local Success Does Not Compose arxiv
site:arxiv.org/abs/2610 "specification" "code generation"
site:arxiv.org "contract" "repository" "generation" "2026" agent specification
"specification-guided" "repository" code generation formal verification
"specification" "when to verify" "code generation"
```

审阅边界：对关键正文表格和局限进行了核对，没有下载和运行文献项目。Repo0 的六项目完整补充结果未逐项核验，最终讨论不把主文以外的数值作为独立核验结果。新的算法设计与正式实验预注册尚未完成，本文件不是完成实验的声明。
