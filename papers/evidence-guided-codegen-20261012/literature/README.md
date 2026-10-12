# 文献核验交付说明

- `references.bib`：9 篇引用。7 个 arXiv BibTeX 导出端点返回元数据；Clover 改用已交叉核对的正式出版作者 BibTeX；P³ 与 SkillForge 的导出端点失败，程序从已打开的原始 arXiv 元数据字段生成。作者/题名/DOI 均不来自模型记忆。
- `citation_audit.json` / `citation_audit.md`：E101–E109 稳定映射、作者、年份、出版状态、版本、全文定位、支持范围、不能推出的结论、访问程度与限制。
- `raw/`：工具返回的原始网页/搜索文本以及错误。它们是 web 工具处理后的响应，不是原始 HTTP 字节，也不意味着已逐字审阅整篇论文。搜索结果仅作发现线索。
- `raw_manifest.json`：保存响应的 SHA-256。
- `build_citations.py`：从保存的响应程序化再生 BibTeX 与台账，不联网。
- `verify_citations.py` / `validation_report.json`：本地结构、字段与台账一致性检查。技能自带验证器因缺少 requests 无法启动，该限制明确记录，未伪称其通过。

本次是定向叙述性核验，不是系统综述。所有记录机器检查了书目元数据与选定全文段落，人类核验统一为 pending，未填写具名复核人。访问日期固定为 2026-10-12；未把本地未发表文本或日志发往外部。

已按实际使用技能的引用要求收录 Scientific Agent Skills，作为流程/软件引用；该论文不能证明本研究结果可靠或技能提高科研效能。

关键边界：AxDafny 为直接近邻；固定规格、记忆与验证循环均不能单独作为本项目新颖性主张。论文结果不用于跨基准数值排名；现有文献不能证明当前 A/B/C/D 部分矩阵中的效能优势或首次性。

访问限制：arXiv API 的本地请求发生 SSL 错误；web API 与 Crossref API 不可访问；两个 arXiv BibTeX 端点 cache miss；Clover HTML/一个作者 PDF 访问失败而公开 arXiv PDF 可读。DafnyBench 的 TMLR 2025 线索遇到 OpenReview 浏览器验证墙，其正式版升级仍未核验，没有绕过。SkillForge 的 EMNLP 接收状态仅为 arXiv 作者自报，未伪造 ACL 出版元数据。

