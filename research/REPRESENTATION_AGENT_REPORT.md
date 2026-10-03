# 2026-09-17：固定规约表示与验证修复原型交付

协议 `fixed_spec_representation_v1`。本次默认不使用真实付费模型，不发送仓库代码到模型服务。
这是实现与工程诊断报告，**不是表示优劣、模型修复能力或论文创新性结论**。

## 仓库审查与复用决策

Git 根目录与当前项目均为 `codegen-verify`；未找到适用 AGENTS.md。已有未提交成果和研究笔记全部保留。
已有 `generation/` 支持冻结方法骨架、候选检查、Dafny + 运行检查、模型适配、G00–G11 四条件和轨迹。
但它公开完整契约、对照的是完整文件/方法体输出，不是本次三种需求表示；旧 `repair/` 还有不同任务准入与调度。
因此不重写或替换旧协议，只在 `generation/representation/` 增加这次的输入/策略协议。

直接复用：`generation.task.Task` 的冻结头部装配与提取、`generation.task.body_check`、`repair.task` 的
BoundaryError/哈希/词法检查、`repair.runner.write_json`、`repair.verifier` 的结果分类/工具链指纹和旧诊断解析器。
新增的正式验证子类只补齐独立 stdout/stderr、进程组超时、预期批次检查和本协议状态名称；不执行生成代码。
新模型适配器继续使用已安装的 OpenAI SDK；因为旧适配器写死旧 SYSTEM 和采样策略，本协议不借用其发送消息逻辑。

## 本次主要文件

- [运行与安装说明](../generation/representation/README.md)、[实验设计](../generation/representation/EXPERIMENT.md)，主 README 增加当前入口，历史说明保留。
- `generation/representation/task.py`：复用冻结任务装配，增加三表示/需求映射/版本哈希与 pending 审计。
- `guard.py`：在已有词法防护上增加语句/块结构检查，尤其拒绝无体循环、区域闭合和受信任绕过。
- `models.py`：确定性 mock 与一个可配置 SDK 适配器，禁用隐藏重试；只显式授权时使用凭据。
- `verifier.py`：正式验证、原始日志与受控诊断；unknown 归因保持 unknown。
- `runner.py/config.py`：三策略共用循环、预算、独立会话、冻结资产检查、最终重验、逐轮工件与中断检查点。
- `cli.py/analyze.py`：环境检查、准入、单任务、矩阵、JSON/CSV/Markdown 描述汇总；缺失作业不隐藏。
- `tasks/`：五个自建 synthetic_demo；`configs/demo.json` 与 `live.example.json`。
- [自动化测试](../tests/test_representation_agent.py)、[只读工件与输入审计](../scripts/check_representation_artifacts.py)。

## 实际执行与证据

**最终版本已完成：344 passed，2 subtests passed，47.80秒；45/45计划运行完成，无缺失。**
[最终测试 XML](runs/2026-09-17-representation-tests-final.xml) ·
[最终矩阵 JSON](runs/2026-09-17-representation-final/summary.json) ·
[CSV](runs/2026-09-17-representation-final/summary.csv) ·
[Markdown](runs/2026-09-17-representation-final/summary.md) ·
[最终输入与工件审计](runs/2026-09-17-representation-final-audit.json)

最终矩阵再次执行75次 mock 调用和105次真实 Dafny 验证，准入另外10次真实验证。
各策略结果与下面首轮表一致，全部45个 manifest 源码哈希与当前代码一致。
两轮分开保留，不合并为90个独立样本。测试总数为保留的270项与新增74项。

最终实际运行命令：

```sh
.venv/bin/python -m generation.representation.cli matrix --config generation/representation/configs/demo.json --output research/runs/2026-09-17-representation-final
.venv/bin/python -B -m pytest -q -p no:cacheprovider --junitxml=research/runs/2026-09-17-representation-tests-final.xml
.venv/bin/python scripts/check_representation_artifacts.py research/runs/2026-09-17-representation-final --output research/runs/2026-09-17-representation-final-audit.json
.venv/bin/python -m generation.representation.cli summarize --output research/runs/2026-09-17-representation-final
```

矩阵与测试曾并行运行，耗时只记录本机观察，不据此比较策略延迟。复现请使用新的输出路径。

先验证一个正确 arithmetic 候选，再跑 mock 错误→修复→最终重验；带循环的 Maximum 参考也独立验证通过。
五题准入全部通过：5 个正确参考 `verified`，5 个错误体 `verification_failed`。后者不被泛化解释为求解器已提供反例。
三表示均为 pending，准入不改变人工审计状态。

首轮完整工程矩阵：[运行汇总](runs/2026-09-17-representation-mock/summary.json)、
[输入/工件审计](runs/2026-09-17-representation-mock-audit.json)。
5题×3表示×3策略×1重复，共45次运行，mock 调用75次、真实 Dafny 验证105次；准入额外10次验证单列。
审计核对了45条运行、75份实际提示与105次验证事件，全部计划完成。没有真实 API 调用。

| 策略（合并三表示） | 运行数 | 首次完整通过 | 预算内完整成功 |
|---|---:|---:|---:|
| single_shot | 15 | 0/15 | 0/15 |
| iterative_repair | 15 | 0/15 | 15/15 |
| independent_sampling | 15 | 0/15 | 15/15 |

**这些数字由 mock 的“第1次错误、第2次参考”序列决定。** mock 不理解表示，也不根据反馈推理；
single_shot 的失败不是对真实模型能力的测量，两种多调用策略的成功也不能证明反馈有效。
三表示每格5题，只有1个自建来源，全部 dev，无独立测试集，不做显著性结论。

首轮全仓库测试：343 passed，2 subtests passed，48.22秒。
[首轮测试 XML](runs/2026-09-17-representation-tests.xml)
最终记账审查又补了一个测试，确保在途真实请求被中断后用量/费用为 unknown 而非零；
首轮工件保留，被后续修订的 runner/analyze 源码副本在其 `source_snapshot/` 下，可核对原始哈希。
最终版本测试与矩阵复跑另存独立目录，不把两轮当作额外独立样本。

## 真实与模拟的边界

- 真实：Dafny 4.11.0 正式验证、CSV 批次、stdout/stderr、进程超时、小型候选接受/拒绝、最终重验。
- 模拟：所有模型候选都来自有参考访问权的 mock；SDK 的正常/空输出/限流/超时路径用离线替身测试。
- 未执行：任何真实模型 API 请求、在线供应商参数兼容性检查、付费批量实验；API 费用为0。
- 版本环境：[环境检测记录](runs/2026-09-17-representation-environment.json)，Python 3.12.13，SDK 3.2.0。
- 官方接口核验和来源见运行 README；Dafny §8.15.4 对无体证明结构的说明直接促使本次加强结构检查。

测试覆盖输入泄露、防绕过/闭合注入、配置/任务哈希、真实正确/错误准入、真实修复、
首次/最终验收、未知批次、解析错误、超时杀进程组、最小环境、token/费用/调用预算、
不同条件状态隔离、缺失运行、工件篡改、mock/真实身份分离和中断保留。

## 已知限制与下一步

没有环境阻碍本地工作；Dafny 与 Python SDK 已可用。真正模型实验仍需用户选择模型、配置环境凭据并明确费用授权。
没有任意共享声明/辅助引理支持、完整 AST/OS 沙箱、内存配额、自动断点续跑、PSM 转换或公开方法忠实复现。
SDK timeout 不是整个进程可强制中断的总 deadline；超预算返回会拒绝成功，未知成本保留未知。
实现检查是受限 profile；拓宽语法/工具权限前须重新审查，不声称可处理任意不可信代码。

距离正式论文实验仍缺：独立人工三表示等价性及验收充分性审计、公开多来源与许可核查、dev/test 来源划分与近重复检查、
任务难度和传统生成器覆盖分析、实际模型参数/计费 smoke，以及相同预算下修复对独立采样的重复测量。
最值得下一步做的是**先独立审计这五题，再引入一个可公开的固定规约来源**；不应直接放大当前 mock 数字或宣称结构化表示更好。
