# MDA 的 PSM → 代码：收窄补充（2026-10-06）

用户已明确：这里的“配置项”是 MDA 中 Platform-Specific Model（PSM）的内容。本文件取代泛配置/API 版本视角作为当前选题依据；不修改先前报告。使用 research 工作流核对一手来源，未实现、未运行付费实验。

## 范围纠正

PSM 不是任意 JSON、feature flags 或依赖版本列表的同义词。MDA 的典型链路为 PIM → 包含目标平台实现细节的 PSM → 代码。是否为 PSM 取决于它的元模型、平台概念、结构/行为约束与映射关系；文件恰好用 JSON/XMI 保存不是判据。[OMG MDA 概述](https://www.omg.org/mda/specs.htm)、[OMG 托管 MDA 教材章节](https://www.omg.org/mda/mda_files/Kleppe_ch01.pdf)。该旧概述中的历史版本号不作为当前软件版本依据。

因此核心问题应写成：**给定固定且可信的 PSM，LLM 生成代码在何种平台语义上偏离该模型，怎样独立检测与定位这些偏离？** 本轮确实找到 LLM 与模型到代码的直接工作，但没有核实到足以称为“固定 PSM 语义符合性标准基准”的公开数据集；不能拿泛配置或 API 版本基准补齐这个缺口。

## 必须保留的官方传统基线

**OMG MOF Model to Text Transformation Language（MOFM2T）1.0**，2008 年正式标准。定义模型到文本变换语言；它是 M2T 的标准基础，不是一个能直接解释所有平台模型语义的万能编译器。[OMG 标准页与规范](https://www.omg.org/spec/MOFM2T/1.0/About-MOFM2T)。

**Eclipse Acceleo**，官方开源实现/项目。官方页说明其实现 OMG MTL，可从 EMF 模型（UML、SysML、领域模型等）生成 Java、C 等文本代码。用于实验时仍需给出目标 PSM 元模型和可信生成模板；不能把“运行 Acceleo”本身当成语义正确证明。[Eclipse 官方项目](https://projects.eclipse.org/projects/modeling.acceleo)、[官方说明](https://wiki.eclipse.org/Acceleo/)。

合理对照是相同 PSM 下的人工审计模板、LLM 直接 M2T、模板骨架加 LLM 补全。传统模板应作为强基线或参考实现，不应为了获得模型优势而故意缺省必要映射。

## 最接近的三篇研究与距离

### 1. LLMs as Code Generators for Model-Driven Development

Yoonsik Cheon，**ICSOFT 2025**，页 386–393，DOI 10.5220/0013580300003964。出版商明确确认 venue。

- 输入：UML 类图与 OCL 约束。
- 输出：Dart/Flutter 代码。
- 证据：研究 ChatGPT 的模型驱动代码生成，报告约束实现、脚手架和结构一致性，同时承认正确性验证等局限。
- 与 PSM 距离：这是模型到代码的直接 LLM 工作；但“UML/OCL + 指定 Dart/Flutter”不自动等于独立、完整的 MDA PSM。当前已核验摘要不足以确认其 PSM 元模型和平台语义是否独立冻结。
- 复现：本轮未核验公开代码/完整数据，不推断存在形式证明。

[SCITEPRESS 正式论文条目](https://www.scitepress.org/PublishedPapers/2025/135803/)、[出版商原文](https://www.scitepress.org/Papers/2025/135803/135803.pdf)。原文 PDF 在本工具返回 403，条目和原始摘要可检索。

### 2. Development of a Model-Driven DevOps Solution Based on Context-Engineered LLM Code Generation: PROFES Doctoral Symposium

Uldis Karlovs-Karlovskis，**PROFES 2025 Doctoral Symposium**，页 153–159；2025-11-19 online，Springer 推荐引用年份为 2026。它是博士论坛论文，不应写成 PROFES 主会完整实证论文。

- 输入：软件架构模型及其 PIM/PSM 变换链。
- 输出：面向 GitLab 等 CI/CD 平台的配置代码。
- 证据：出版商摘要确认 ATL 模型变换、Acceleo 生成、LLM 上下文增强和运行验证；作者项目进一步明确 PSM 实例经 Acceleo 转成 CI/CD YAML。
- 与 PSM 距离：链路最明确，但对象是流水线配置；项目也让 LLM 生成 PSM 元模型和变换，研究面大于“固定可信 PSM → 程序”。其平台集成演示不能直接证明固定 PSM 的语义保真。
- 复现：作者公开项目进展，2026-09-11 记录部分生成/集成模块仍处开发阶段；不能据此声称整套工具已完整复现。

[Springer 正式条目](https://link.springer.com/chapter/10.1007/978-3-032-12092-2_10)、[作者项目关于 PSM→Acceleo 的记录](https://mddoai.com/latest/2026-09-11)。章节更正只补致谢，由出版商页确认。

同一研究线还有 **Towards LLM-Based Context Engineering for Model-Driven Vibe-DevOps-Engineering of Cross-Platform CI/CD Pipeline Support**，**FedCSIS 2026 / ACSIS 47，83–93**。官方摘要称其从既有 MDE 工件和平台文档合成 CI/CD 模型变换链，是概念验证。已核验发表元数据和摘要；未成功读取全文，因此不擅自声称它对固定 PSM 做了语义符合性实验。[官方原始条目](https://annals-csis.org/Volume_47/drp/5402.html)。

### 3. Formal-Method-Guided Vibe Coding: Closing the Verification Loop on AI-Generated Safety-Critical Software Through Model-Driven Engineering（Forge）

Ran Wei 等，**2026-06-21 arXiv 预印本**；本轮未核验正式 venue。

- 输入：需求与受限 Java 生成规则。
- 输出：Java 源代码；之后从源代码抽取 EMF/RoboChart 模型，再生成 Dafny、CSP、Isabelle 工件并把失败反馈给 LLM。
- 验证与代码：原文提供三类验证器、案例与开源实现，并限定可被模型抽取器识别的 Java 结构。
- 与 PSM 距离：这是生成代码后反向抽取形式模型的闭环，不是把预先固定的用户 PSM 当权威输入。仅证明所抽取模型的性质，不应表述成已证明代码符合某个独立原始 PSM。

[作者原文 §3、§5.2](https://arxiv.org/html/2606.22413v1)、[代码与案例](https://github.com/wrwei/Forge)。其验证闭环与追踪机制可借鉴；任务定义和信任边界必须分开。

SDSM 只作为邻近引用：它刻意用简单数据结构替代 DSL，本轮未确认其输入具有 MDA PSM 的元模型与平台语义，不能再将它列为严格 PSM 生成的直接代表。[原始摘要](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6818764)。

另外两项模型到代码邻近工作：

- [LLM as a code generator in Agile Model Driven Development](https://arxiv.org/abs/2410.18489)，2024 首版、2025 修订的预印本：UML 加 OCL/FIPA 语义生成面向 JADE/PADE 的 Java/Python。可参考平台语义的输入组织，但本轮摘要级核验不能证明它具有独立冻结的 PSM 符合性判定。
- [Model-Driven Quantum Code Generation Using Large Language Models and Retrieval-Augmented Generation](https://arxiv.org/html/2508.21097v1)，2025，作者标注 MODELS NIER，关联 DOI 10.1109/MODELS67397.2025.00031：UML Profile 模型实例生成 Python/Qiskit；正文 §V 用模型元素映射的 Precision/Recall/F-measure 和 CodeBLEU 评价，不能据此推断一般 PSM 行为语义已获形式证明。[作者代码](https://github.com/nazaninsiavash/QuantumCodeGeneration)。

## 可执行的窄问题：PSM 语义义务的漏实现与反馈定位

建议先选择一个平台和受限 PSM 子集，例如 Java 数据对象/操作模型：类型映射、可空性、集合顺序/唯一性、整数边界，以及明确的操作前后条件。不能只给类图却声称完整行为语义已经指定。

研究问题：**在代码能够编译时，哪些 PSM 语义义务仍被漏实现；将验证错误定位到 PSM 元素和约束，是否比只提供编译/测试错误更有效地减少偏离？** 这与现有项目的固定契约研究比较接近，但需要真实 PSM 接入，不能把现有 Dafny 任务重命名为 PSM。

最小试点：先做 10 个经过人工审计的真实 PSM 实例，冻结元模型、实例、平台映射和约束；验证器从冻结 PSM 的可信变换生成，LLM 只能修改目标代码。对比模板、LLM 直接生成、LLM 加代码层诊断、LLM 加 PSM 元素定位诊断。若语义映射无法独立说明，先报告未覆盖范围，不把编译通过当成符合性。

分开报告结构符合、约束符合、平台映射符合、编译通过及成本；每个失败应追踪到具体模型元素。加入少量手工错误变体来检查验证器会不会漏报，特别是空值、边界值、集合语义错误。试点只有揭示稳定的模型特有失效后才扩规模。

撞车风险：UML/OCL→代码、M2T、验证反馈、模型追踪都已有工作。可能贡献应限定为某类平台语义、固定独立模型的判定协议及受控失效分析；“LLM替代模板”“MDE+形式验证闭环”都不够新。检索有限，未证明此细分问题尚无人研究。

## 生成机制澄清：MDDOAI 中 LLM 究竟写什么

2025 年博士论坛论文 §3.2 描述混合路线：架构模型经 ATL 转到 PIM/PSM，Acceleo 按预定义模板生成 YAML；LLM 读取 PSM，补充模板未覆盖的复杂条件、动态任务等配置代码。此处的 LLM 产物确实是最终配置的一部分。这是论文所述方案，不能据此假定后来所有版本均如此实现。[作者上传的论文原文](https://www.researchgate.net/publication/397757426_Development_of_a_Model-Driven_DevOps_Solution_Based_on_Context-Engineered_LLM_Code_Generation_PROFES_Doctoral_Symposium)、[出版商元数据](https://link.springer.com/chapter/10.1007/978-3-032-12092-2_10)。

2026 年作者明确提出另一条路线：LLM 根据平台文档与参考工件依次生成 **Ecore 平台元模型 → ATL 变换程序 → Acceleo 生成模板**；随后执行这些工件，由模型实例产生流水线 YAML。因此这条路线的 LLM 主要在“写生成器”，最终文件由变换工具生成。每步附参考样例与约束；编译/执行错误再加入约束，重新生成相应工件。[作者关于三步输入输出的说明](https://mddoai.com/latest/2026-06-18)。

实现状态需限定时间：作者 2026-09-11 演示已生成并验证 Mock Platform 的 Ecore、ATL 和 Acceleo 工件；当时 ATL/Acceleo 的 PR 尚在审查，自动执行完整链路的最终 Generation/Test Agent 仍待完成。已有工件生成演示，不等于全自动端到端语义正确性已经证实。[作者演示记录](https://mddoai.com/latest/2026-09-11)。

## 生成机制补充：从模型到最终源码的具体分工

以下是查得工作的机制分类，不是对整个领域占比的统计，也不把所有 UML 模型自动认定为完整 MDA PSM。

1. **规则/模板执行**：Acceleo 读取模型，模板通过查询、循环和条件选择将模型元素映射为目标文本，写出代码文件。映射由生成器作者实现；可覆盖的行为取决于模型和规则，不局限于类骨架。[Acceleo 用户指南](https://wiki.eclipse.org/Acceleo/User_Guide)。
2. **模型文本直接提示 LLM**：AMDD 将 UML 用 PlantUML 表达，结合结构、行为及 OCL/FIPA 约束，由现成 GPT-4 生成面向 JADE/PADE 的 Java/Python；部署和验证由建模者完成，不能称全自动验证。[原文 §3](https://arxiv.org/html/2410.18489v2)。
3. **模板结构＋LLM 方法体**：MoProCo 的 *To Model, to Prompt, or to Code? The Choice Is Yours: A Multi-Paradigmatic Approach to Software Development*（ICSOFT 2025）以 tUML 表达类、属性、关联、操作及可选的 `desc`/`impl`。模板先生成 Java 结构；`impl` 直接成为方法体，`desc` 成为方法的 `@prompt`。Weaver 将提示与当前项目 Java 文件发给 LLM，提取返回的方法体并插入对应位置。它支持小范围行为补全，不是任意 PSM 语义的通用证明。[出版商全文 §2.2–2.3](https://www.scitepress.org/Papers/2025/135571/135571.pdf)、[正式会议条目](https://www.insticc.org/node/TechnicalProgram/icsoft/2025/presentationDetails/135571)。
4. **LLM 编写生成器**：MDDOAI 2026 路线先生成元模型、ATL 变换与 Acceleo 模板，再执行工件生成最终文件。实现状态见上一节。

RAG 属于输入增强，可和上述 LLM 路线组合。量子代码生成论文将元模型约束下的模型实例文本和检索到的 Qiskit 示例代码交给 GPT-4o，生成 Python/Qiskit。论文当前检索的是代码片段；检索元模型等属于后续方向。[原文 §IV](https://arxiv.org/html/2508.21097v1)。

需要分别说明：条件只是写进提示、条件被实现为确定性映射、条件由独立检查器验证，三者提供的保证不同。编译通过本身不证明 PSM 条件都被落实。
