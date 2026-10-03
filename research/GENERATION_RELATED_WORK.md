# 固定规约/PSM代码生成：补充核查

2026-09-13。这是为方向决策做的一手来源核查，不是穷尽综述或原方法复现。
论文内容、我们的判断、待核验分别标记；不沿用旧修复方向的差异矩阵作为新颖性结论。

| 来源与核查范围 | 已确认的任务/方法 | 对新方向的约束 |
|---|---|---|
| [OMG MDA说明](https://www.omg.org/mda/specs.htm)，MDA Overview/MOF | PIM→PSM→代码的变换链；模型是主要开发制品 | PSM到代码并非新问题；结构模型不能替代未声明的行为语义 |
| [MOFM2T 1.0](https://www.omg.org/spec/MOFM2T/1.0/About-MOFM2T)，官方规范元数据 | 已有模型到文本变换标准 | 必須纳入模板/规则生成器，不能只比LLM提示方法；未在本地部署该标准实现 |
| [VERINA v3](https://arxiv.org/abs/2505.23135v3)，2026-03-16版本，摘要 | 189个Lean任务，区分code/spec/proof及组合评测 | 只取给定规格的任务定义作参考；不把规约生成或纯证明成绩移植为生成效果 |
| [AxDafny v1](https://arxiv.org/abs/2606.32007v1)，2026-06-30，摘要 | Dafny实现和证明生成，验证反馈修正；250项LCB-Pro-Dafny | 直接的形式生成邻近工作；竞赛题不等同PSM业务模块，本次未重现结果 |
| [P³ v1](https://arxiv.org/html/2608.09277v1)，§2–§4，2026-08-10 | 给定规约，联合程序分解与证明规划；库派生多API任务 | 不能把“同时生成代码和证明”“先规划后验证”叫新机制；新方案不默认加入联合规划 |

以上生成论文除链接页明确说明外，本轮不新增录用判断，不用历史数字做同预算比较。

## Forge：本轮新增的高重叠工作

【原文】*Formal-Method-Guided Vibe Coding: Closing the Verification Loop on AI-Generated Safety-Critical Software Through Model-Driven Engineering*，
arXiv v1，2026-06-21。§3生成Java并经MDE提取模型，使用Dafny、FDR4和Isabelle反馈修正。
§4为三个案例的可行性研究；Table 6耗时排除了LLM编写时间。
§5.5明确模型转换的语义保持/工具资格仍需后续论证，不能把可复现等同语义可信。
页面虽有TOSEM字样，但DOI为占位符；本次只确认为预印本，不将其视为录用证据。
[原文 §3、§4/Table 6、§5.5](https://arxiv.org/html/2606.22413v1)

【判断】“MDE＋主流代码生成＋形式验证反馈”已经存在；新项目不应以拼接这三者作为贡献。
我们的候选区别是固定输入模型、传统生成器对照和约束落实的受控消融，但这些是待证明的研究价值，
不是已建立的新颖性。尤其不复制其多验证器组合，先用单一可验证子集完成因果清楚的小实验。

## SDSM：模板对照不能省略

【摘要级确认】*Large Language Model as a Code Generator in Simplified Domain-Specific Modelling*，
SSRN页面标2026-05-23，作者Adam Bochenek、Jarosław Protasiewicz、Witold Pedrycz。
摘要描述以简单数据结构表达模型，并比较LLM、模板及程序化生成。
[作者预印本入口](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6818764)

【待核验】本次直接打开全文失败，具体设置、预算、评判、结论及发表状态待核验，不引用数值或声称已完整精读。
其存在已经足以要求投稿前认真排查“结构配置＋LLM替代模板”的重叠。

## 阅读优先级

先确认自己的输入究竟是什么：实际PSM示例/语义文档 → OMG变换链 → SDSM完整对照设置。
再确认验证链的可信范围：Forge §3、§5.5。最后看生成强基线：AxDafny生成赛道、P³ §2–§3、VERINA固定规格子任务。
旧Laurel/DAISY/DafnyPro只作内部证明补全过程参考，不能充当端到端代码生成的唯一强基线。
