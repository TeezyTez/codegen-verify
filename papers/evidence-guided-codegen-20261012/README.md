# 中文研究初稿交付

工作题名：**固定规约代码生成中的证据状态与目标调度：可审计框架和阶段性机制分析**。

按用户指定顺序完成：先建立主张—证据表，再制定提纲，撰写完整正文，最后核对实验数值、引用与主张范围。论文交付不意味着尚未完成的正式实验已经完成。

## 阅读顺序

1. [主张—证据表](claim_evidence.md)：允许的主张、证据定位、局限及不能推出的结论。
2. [论文提纲](outline.md)：每节问题和论证关系。
3. [完整中文正文](manuscript.md)：便于阅读的论文初稿，含方法、结果、机制解释、相关工作、限制、后续试验及参考文献。
4. [引用核验台账](literature/citation_audit.md) 与 [BibTeX](literature/references.bib)：九篇定向近邻和工具背景资料的原始元数据、选定全文定位与引用边界。
5. [实验工件核验](evidence/audit.md) 与 [独立代理审阅及修订](review/resolution.md)。

## 目前可以下的结论

正式计划为 1392 个会话，本地完成 416、成功 412；四组均为 103/104。完成的 104 个题目×重复块都含四组，但只有 4 个题族完成全部三次重复。当前结果是完成子集的描述，不能写为完整总体试验，也不证明四组等效。

研究机制的实际触发很稀少：8 个多目标机会、4 次同状态推荐分歧，D 组实际遇到其中 1 次。当前更有依据的论文贡献是可审计框架、证据语义案例和机制触发不足的诊断，而不是已经证实的性能提升或首次算法。

## 审计层

- `manuscript.audit.md` 保留逐段主张及证据标记；`claim_evidence.csv` 将文字绑定到 SHA-256。
- `source_manifest.json` 记录来源；`machine_source_checks.json` 单独记录代理读取及哈希核对。前者的人类 verification 仍为 unverified，避免把机器检查冒充人工签核。
- `consistency_manifest.json`、`validation_report.json` 和 `validation/` 保存机器一致性检查及 skills 检查器的实际输出。
- `manuscript_manifest.json`、`authorship.json`、`reporting_coverage.json` 记录草稿状态和未定声明；`submission_ready=false`。
- `evidence/evidence_audit.json` 保存逐运行来源、机会事件、分母与文件哈希；没有把原始日志已公开当作事实。

## 复现本次整理

从项目根目录依次执行；这些命令只重读本地数据和重建论文工件，不调用生成模型或 Dafny 实验。文献重建也只读取保存的公开资料响应。

```powershell
.venv/Scripts/python.exe -X utf8 papers/evidence-guided-codegen-20261012/evidence/extract_evidence.py
.venv/Scripts/python.exe -X utf8 papers/evidence-guided-codegen-20261012/build_manuscript.py
.venv/Scripts/python.exe -X utf8 papers/evidence-guided-codegen-20261012/verify_manuscript.py
.venv/Scripts/python.exe -X utf8 papers/evidence-guided-codegen-20261012/literature/verify_citations.py
```

原始数据或正文改变后需重新核对证据范围；重建登记和通过机械检查不自动批准改变后的科学主张。提取脚本依赖本地日志、冻结框架和工具链工件，仅有公开代码克隆不能保证立即复现全部历史检查。

## 保留的核验限制

旧机制探针冻结的验证适配器与当前源码哈希不同，已在正文披露；当前主矩阵的冻结源码一致性检查通过。引用中，Clover 已交叉核对正式出版信息；DafnyBench 可能的正式版升级受访问验证墙限制，因此引用已打开的 arXiv 版本。SkillForge 的接收状态仅为作者自报，未充当已核验出版记录。

引用 skill 的原检查器因当前 Python 缺少 requests 未能启动；本次使用了实际通过的本地书目一致性检查，并保存原始来源响应。科学写作 skill 的主张审核会如实报告人工复核尚未完成；这是保留的人工门槛，不是把所有主张自动标为 verified 来规避的错误。

作者、单位、投稿 venue、资助、利益冲突、贡献与数据发布权限待责任人确认。本轮完成的是可审查中文研究初稿，不是已投稿稿件。
