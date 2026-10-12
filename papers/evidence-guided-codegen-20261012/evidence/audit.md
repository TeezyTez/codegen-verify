# 本地证据审计（2026-10-12）

仅重新读取已有工件；没有模型调用或验证器实验，没有运行要求完整主矩阵的分析入口。此为自动一致性核验，不是人工复核。

主矩阵冻结 1392 会话；现有 432 个目录，其中完成 416、无终结 result 16、未建目录 960。无 result 不等于后台仍在运行。
已完成子集：412 成功，460 模型调用，75 题/75 族。共有 104 个任务×重复块，其中 104 个四组齐全，各组任务×重复名单相同（True）；因此这个层面的四组配对完整。仅 4 族具备四组各三次的完整12会话，题族重复覆盖尚不完整。此完成子集可作明确标注的配对描述，但不能冒充完整冻结矩阵 ITT 或预定主检验。

| 组 | 完成 | 首轮成功 | 修复后成功 | 最终成功 | 模型调用 |
|---|---:|---:|---:|---:|---:|
| A | 104 | 95 | 8 | 103 | 114 |
| B | 104 | 90 | 13 | 103 | 119 |
| C | 104 | 96 | 7 | 103 | 112 |
| D | 104 | 93 | 10 | 103 | 115 |

失败原因：{'model_infrastructure_failure': 4}。所有完成结果通过现有 analyze._trial 核对 result、manifest、artifact 哈希和 action 轨迹；冻结 roster、tasks、family、prelaunch、framework snapshot 另行校验。

调度审计 460/460 轮；多候选机会 8 轮，同状态建议分歧 4 轮。逐轮来源及真实 selected_target 见 JSON scheduler_events。机会来自 DT0023 四组和 DA0087 的 B 组；全部分歧来自 DT0023。D 实际遇到的分歧仅一轮，不能支持总体有效性。
D target-following：{'availability': 'partial', 'audited_targeted_rounds': 114, 'missing_targeted_rounds': 1, 'followed': 112, 'rate': 0.9824561403508771}。参考额外 helper 和实际生成 helper 使用不同定义，详见 JSON。runner closed 回退计数 0，逐轮更宽口径 closed→nonclosed 事件 0。

开发 development-v2：62/64；canary-v1：12/12。不可与主矩阵合并。最终去重族清单：{'admitted_tasks': 412, 'families': 180, 'family_split_counts': {'development': 64, 'test': 116}, 'task_split_counts': {'development': 167, 'test': 245}, 'test_representatives': 116, 'no_generation_outcomes_used_recorded': True}。

开发集题族数量按当时冻结 tasks.json 为 16；若仅为解释而套用 families-final 映射，则为 15。保留两种口径及来源，不静默替换历史分母。

旧机制诊断工件复算：66 次验证（[60, 4, 2]），记录模型请求0；{'verification_failed': 48, 'verified': 18}；初始30变体两次重复，30 变体的解析状态/义务/诊断一致。count、copy 两组反例支持诊断本身不能区分实现错误与证明缺口，并显示加提示后后置条件报错可迁移到 invariant；4 个局部通过批次在人工编写的依赖图上仍有失败依赖。这些是存在性机制例证，不是方法效果或发生率估计。

全部来源路径、文件 SHA-256、逐条核对结果、分母和局限均在 evidence_audit.json。SHA-256 只证明本地工件一致性；不能证明外部真实性或人工复核。

检查 1163 项，通过 1162；非致命历史/当前源码差异 1 项（详见 check_summary）。

复现：从项目根执行 `.venv/Scripts/python.exe -B papers/evidence-guided-codegen-20261012/evidence/extract_evidence.py`。输出仅写本证据目录。
