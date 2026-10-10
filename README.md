# 固定可信规约下的代码生成研究

## 当前入口：公开任务上的四组生成实验（2026-10-10）

`generation/public_benchmark/` 实现相同规约、历史、模型与预算下的四组对照：
A 自主循环、B 证据账本、C 结构顺序调度、D 证据调度。完整程序必须通过冻结契约检查与真实 Dafny 验证，局部证明或模型自报成功不能替代最终验收。

正式队列已冻结为 **116 个测试题族 × 4 组 × 3 次重复 = 1,392 个会话**。
截至本次同步，本机记录为 **416 个已完成、412 个通过**，这些已完成会话累计 **460 次模型调用**；队列尚未完成，不能据此报告正式组间效果。
此前开发试跑、参考解检查、语义审查和突变审计均与正式生成结果分开。

- [实验协议与执行前裁决](research/LARGE_SCALE_CODEGEN_PROTOCOL_2026_10_09.md)
- [公开数据来源与限制](research/LARGE_SCALE_DATASET_SOURCES_2026_10_09.md) · [数据复现说明](research/data/large-scale-20261009/REPRODUCTION.md)
- [运行器](generation/public_benchmark/campaign.py) · [完整矩阵只读分析](research/analyze_main_public_20261009.py)

公开数据快照及来源、许可文件随项目保留。模型调用使用本机配置；`.env`、`logs/`、工具安装、验证普查输出和编译缓存不进入 Git。完整原始实验轨迹仍保存在本机 `logs/public-codegen-20261009/`，本仓库同步不代表完整结果已经发布。

## 前一阶段：规约义务与证据状态驱动 Agent（2026-10-07）

实验问题：**同一固定规约、模型和预算下，显式证据状态与定向修复能否提高 Dafny 验证通过率？**

新入口 `generation.obligations.cli` 提供 `baseline / state / guided / independent_sampling` 四组。
四组公开相同形式契约，共用 `generation/engine.py` 的调用预算、方法体检查、Dafny 验证和最终文件重验。
证据绑定规约、候选版本与工具链；代码改变使旧证明失效，模型声明和诊断消失都不能充当证明。

从 [义务 Agent 使用说明](generation/obligations/README.md) 开始。默认 mock、无 API 调用；
历史表示实验入口继续可用，新协议结果与历史结果分开汇总。

已完成 [公共失败起点修复实验](research/COMMON_FAILURE_REPAIR_RESULTS_2026_10_06.md)：8 次运行均首次修复通过真实 Dafny，
其中 1 次提示转交偏差排除策略比较。当前支持修复闭环可运行，尚无义务引导收益证据。

后续已建立核验文件输入、原始会话响应自动收集与持久化执行器。
[96 次开发矩阵中止报告](research/FILE_REPAIR_DEVELOPMENT_INTERRUPTION_2026_10_07.md)：
8 次有效通过、3 次协议中止、85 次未启动；平台跨午夜更新被旧审计误判为额外任务。
原批次永久保留，不追认中止样本。修复采用独立 v2 协议，
[四组恢复检查](research/FILE_HANDOFF_RECOVERY_PROTOCOL_2026_10_07.md) 与原 96 次矩阵分开。
恢复检查现已 [全部结束并通过审计](research/FILE_HANDOFF_RECOVERY_RESULTS_2026_10_07.md)：
A 第 2 轮、C 第 3 轮、D 第 1 轮通过；B 用完 3 轮未通过。单题四次运行不能支持策略排序。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m generation.obligations.cli preflight --task-id absolute
.\.venv\Scripts\python.exe -X utf8 -m generation.obligations.cli matrix --task-id absolute --output logs/my-obligation-smoke
```

以下为此前的实验记录与入口。

最新真实模型挑战实验：3道题各跑3次，6/9首次通过、7/9预算内通过；出现1次第四轮修复成功、
2次连续四轮仍无法证明。见 [挑战实验与失败分析](research/LIVE_CHALLENGE_2026_09_20.md)。
这是探索性开发题结果，不是论文基准成绩；原 [首次单题报告](research/LIVE_AGENT_2026_09_20.md)保留。

**此前开发重点：让真实模型完成一个生成—验证—修复任务。**
从 [Agent 快速接入](generation/representation/AGENT_QUICKSTART.md) 开始；先做不调用 API 的 preflight，
再在明确模型与预算授权后运行单题，不默认扩大矩阵。

## 历史入口：固定规约表示与验证修复（2026-09-17）

研究原型现支持 `natural/checklist/structured` 三种输入，以及 `single_shot/iterative_repair/independent_sampling`
三种策略。共用冻结方法体装配、受限语句检查、真实 Dafny 验证、预算和完整日志；隐藏契约不进入模型提示。
默认只跑 mock，不调用付费 API。5 个自建演示任务的表示等价性仍为 **pending**，不是论文基准。

完整安装、配置、运行与防护边界见 [新 Agent README](generation/representation/README.md)，
控制变量和预算对照见 [实验设计](generation/representation/EXPERIMENT.md)。
代码复用、真实测试与诊断矩阵结果见 [本次交付报告](research/REPRESENTATION_AGENT_REPORT.md)。
新环境先按说明安装 `requirements.lock` 与 Dafny 4.11；已有 `.venv` 可直接执行：

```sh
.venv/bin/python -m generation.representation.cli doctor
.venv/bin/python -m generation.representation.cli run --task-id absolute --strategy iterative_repair --representation natural --output /tmp/representation-first
.venv/bin/python -m generation.representation.cli summarize --output /tmp/representation-first
```

旧 `generation/` G00–G11 和 `repair/` 协议、研究笔记与历史运行全部保留，不能与这个新协议混算。

## 之前的生成与修复工作

**2026-09-13 方向调整：下一阶段研究“给定固定规约或经审计的 PSM 条件，生成符合这些条件的代码”。**
修复是生成闭环中的工具，依赖调度不再是默认论文主机制；不恢复在线规约生成。

先读 [新研究方向与实验设计](research/FIXED_SPEC_GENERATION.md) 和 [生成方向相关工作](research/GENERATION_RELATED_WORK.md)。
新方向已有独立的 `generation/` 生成实验入口，使用冻结Dafny契约；PSM转换器仍未实现。
使用方法见 [生成实验说明](generation/README.md)，运行证据见 [生成预实验报告](research/GENERATION_PILOT_REPORT.md)。
**以下是已实现并保留的修复原型**，其历史回放结果不能作为新生成方向的效果证据。

```sh
.venv/bin/python -m generation.cli suite --model replay --output /tmp/generation-replay
.venv/bin/python -m generation.cli template --output /tmp/generation-template
.venv/bin/python -m generation.cli audit --output /tmp/generation-replay
```

默认不调用付费模型；脚本候选与真实Dafny验收分开标记，不把回放当模型效果。

## 已实现的上一阶段：规约约束下的 Agent 验证修复

上一阶段问题：**固定目标规约、相同资源预算下，显式依赖信息与修复调度能否提高多函数程序的验证修复成功率，并减少回归和验证成本？**
这是待检验的研究问题，不是已经证明有效或具有新颖性的方法。

当前原型使用 Dafny 4.11，区分两条任务：

- **proof**：实现与目标规约固定，只修指定不变量/断言区域。
- **implementation**：目标规约固定，只修指定实现与证明区域。

长期目标是实现、规约、证明在软件变更中的一致性维护；需求变化、规约演化和真实仓库维护暂不进入第一版。
新主流程在 `repair/`。原 `project/`、历史结果、Typed Spec IR 探索保留，见 [历史 README](README.legacy.md) 和 [设计取舍审计](research/DESIGN_AUDIT.md)。

## 先运行一条真实流程

需要 Python 3.11+、项目依赖与 Dafny 4.11。复用现有 `.venv` 即可；新环境可安装 `requirements.lock` 和 pytest。
通过 `DAFNY_PATH` 指定 Dafny 可执行文件，可选 `DAFNY_SOLVER_PATH` 指定 solver；也可传 `--dafny /absolute/path/to/dafny`。
不要把旧 Windows toolchain.lock 的哈希当成本机安装判据；每次运行会保存实际版本、可执行文件哈希和平台。

```sh
# 不需要模型密钥；确认 original 通过、故障程序失败、reference 通过
python -m repair.cli validate --output /tmp/repair-admission

# 真实 Dafny + 明确标记的脚本候选；完整闭环与六组条件 smoke test
python -m repair.cli suite --model replay --replicates 3 --output /tmp/repair-replay

# 分组汇总：脚本回放永远不进入 research 结果
python -m repair.cli analyze --output /tmp/repair-replay
python scripts/check_repair_artifacts.py /tmp/repair-replay
python -m repair.cli estimate --output /tmp/repair-cost.json
python -m pytest -q
```

输出目录必须不存在，避免覆盖既有结果。缺少 Dafny 时真实集成测试明确 skip，不能将其视为验证通过。
`estimate` 只计算预算上限，不发起调用；未知价格输出 null。

真实模型适配器已连接旧项目的 provider 配置，但本次**没有调用付费模型**。
后续必须先审查输入仅含可外发的公开任务、配置同一 `CODE_PROVIDER` / `CODE_MODEL`、填写价格，
并明确授权后才使用 `--model live --allow-paid`。live 运行会先重新执行任务准入。
失败重试计入预算；模型没有 shell、读参考答案或修改验证器选项的工具。

## 原型如何工作

`任务与冻结区域 → 模型 JSON 动作 → 边界检查 → 全文件验证 → 回归检查/回退 → 最终工件重验 → 日志与汇总`

| 文件 | 职责 |
|---|---|
| `repair/task.py` | 任务模板、合法区域、反绕过检查、来源项目划分 |
| `repair/models.py` | 离线回放 / 显式授权的模型调用 |
| `repair/verifier.py` | Dafny CLI、完整验证、六种状态、CSV 批次和错误解析 |
| `repair/dependencies.py` | 保守语法引用图、失败映射、单一调度规则、回归比较 |
| `repair/runner.py` | 共用工具循环、预算、失败恢复、最终验收 |
| `repair/cli.py` / `analyze.py` | 准入、运行矩阵、成本上限、来源分组和配对估计 |
| `repair/configs/pilot.json` | independent / linear / generic_agent / dependency / 两个消融 |
| `repair/tasks/` | 4 个 dev 样例，含 2 个公开来源的人工派生任务 |

验证状态为 passed、verification_failed、timeout、unknown、compile_error、tool_error。
**验证失败不自动等于实现错误；没有反例不等于证明成功。** 只有合法的最终工件重新完整验证通过才能成功。
目标契约、可信假设、声明与编辑区域外字节由框架固定；禁止新增 assume、额外公理、跳过验证属性等。
这是受限区域编辑协议，不是完整 Dafny AST 安全编辑器，也不支持任意新引理、多文件、模块、自由 shell。

依赖图明确标记为保守词法近似，只含顶层调用/契约引用/已声明引理引用。
验证器报告目前是 callable 批次，**不是完整 VC 逻辑依赖图**；已证实逻辑边集合为空。
不加入多 Agent、RL、GNN 或在线规约生成。

## 研究与结果入口

- [研究问题、实验协议与威胁](research/PROTOCOL.md)
- [核验后的论文阅读与旧论断纠正](research/RELATED_WORK.md)
- [差异与新颖性风险矩阵](research/NOVELTY_MATRIX.md)
- [真实执行报告与继续/调整标准](research/PILOT_REPORT.md)
- [第三方任务来源与许可](research/THIRD_PARTY.md)

每次运行保存 manifest、源码哈希、完整 prompts/responses、逐步工件、验证报告、最终 diff 和 result.json；
suite 保存计划清单，汇总会列出缺失运行。日志不能当作最终验证的替代品。
当前只完成工程可行性与协议诊断，不用回放成功率、历史论文分数或少数成功案例论证方法有效。
