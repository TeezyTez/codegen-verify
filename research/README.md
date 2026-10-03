# 研究入口：固定可信规约下的代码生成

2026-09-13 新主线：[方向与实验设计](FIXED_SPEC_GENERATION.md)；[补充相关工作](GENERATION_RELATED_WORK.md)。
给定规约/PSM条件，研究生成代码的符合性；依赖修复调度暂不继续扩充。
2026-09-14新增 [可运行生成框架](../generation/README.md) 和 [真实执行报告](GENERATION_PILOT_REPORT.md)；
当前只有受限固定Dafny规约任务，无实际PSM转换。旧运行原样保留。
以下条目为2026-09-08修复方向的审计与工程证据，不可混入新的生成结果。

审计日期：2026-09-08。当前检出版本原先没有 `research/`；既有材料在
`docs/LATEST_RESEARCH_AND_EXPERIMENT_DESIGN.md` 等文件。本目录依据原文重新整理，
未覆盖的历史索引条目保持“待核验”，不作为已确认事实。

阅读顺序：

1. [研究问题、边界与实验协议](PROTOCOL.md)：先理解什么能修改、成功意味着什么。
2. [设计审计和取舍](DESIGN_AUDIT.md)：解释旧项目哪些模块退出主流程及原因。
3. [相关工作核验](RELATED_WORK.md)：按任务、方法、预算、结果、局限阅读。
4. [差异矩阵](NOVELTY_MATRIX.md)：候选研究空白，不是新颖性证明。
5. [真实预实验报告](PILOT_REPORT.md)：工程回放与模型效果严格分开。

证据标签：`[原文]` 只指给定版本论文/官方实现；`[本地观察]` 必须关联命令、
运行目录和工具版本；`[假设]` 表示需要受控实验检验的推断；`[待核验]` 不参与论证。
录用信息区分会议主会、workshop、作者自报接受和预印本。项目不承诺任何会议录用。

命名约定：项目名仍为 Codegen Verify；新协议名 `fixed_contract_repair_v1`；
候选机制名 **dependency-guided repair scheduling**（依赖引导修复调度）。
当前图称为 **conservative reference graph**（保守引用图），禁止称为完整证明依赖图。
旧 `TaskIR/SpecIR/SpecAuthority` 属于自动规约生成轨道，不是本篇论文的必要组成。
