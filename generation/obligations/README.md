# 规约义务与证据状态驱动生成

研究问题：在固定规约与相同资源上限下，显式证据状态、定向修复是否提高完整验证通过率？
协议为 `fixed_spec_obligation_v1`。本次交付是实验框架，不是算法效果结论。

分阶段规模、进入条件、题集划分与统计方法见 [实验推进路线](../../research/OBLIGATION_EXPERIMENT_ROADMAP_2026_10_06.md)。

## 四组控制变量

| strategy | 每轮输入 |
|---|---|
| `baseline` | 公共形式契约、当前方法体、按时间排列的验证观察与拒绝记录 |
| `state` | baseline 的全部信息，加上整理后的义务状态与重复候选统计 |
| `guided` | state 的全部信息，加上确定性目标及具体修复指令 |
| `independent_sampling` | 每轮相同的形式契约提示，不输入历史、当前候选或状态 |

所有组使用相同模型、system prompt、方法体 JSON 输出格式、受限语法、Dafny 参数与预算上限。
baseline/state/guided 的原始证据相同，后两组只增加显式组织与调度信息；提示长度不同，真实 token 成本会记录。
独立采样使用不同轮次 seed（仅模型配置支持时发送），不要求生成相同候选；首次完整通过后停止。
所有失败尝试和重复候选都消耗预算，不赠送重试。没有额外规划模型或跨任务记忆。

新协议公开固定 `requires/ensures`；历史 representation 协议仍隐藏这些形式契约。
参考实现、mutants、测试见证只用于本地准入/明确标记的 mock，不进入任何组的模型提示。

## 核心流程与模块

`固定任务 → 策略提示 → 方法体生成 → 边界检查 → 版本失效 → Dafny 全文件验证 → 证据更新 → 下一轮修复 → 落盘文件重验`

| 模块 | 职责 |
|---|---|
| `generation/engine.py` | 新旧协议共用执行、预算、输出持久化及最终验收；策略不能设置成功 |
| `state.py` | 规约/候选/工具链指纹、不可变历史快照、状态转移、重复与回退计数 |
| `policy.py` | 四组提示差异、确定性目标；无验收权 |
| `runner.py` | 新协议适配共享引擎，记录完整源码指纹 |
| `cli.py` / `config.py` | 预检、准入、单题/矩阵、付费调用门槛、预算 |
| `analyze.py` | 核查状态与原始工件对应关系，拒绝混合协议和损坏工件 |

沿用 Hermes 的设计思想：固定 TaskSpec、按作用域保存证据、版本失效、检查点与预算门控。
这里只抽取这些机制，未复制 Hermes 的会话/记忆系统，也不声称恢复完整逻辑依赖图。

## 状态的准确含义

- `R*`：契约条款。`requires` 是假设；`ensures` 是待证性质。
- `M:方法名`：Dafny CSV 中实际观察到的方法正确性批次；不是每个底层 VC。
- `D:指纹`：已观察到的诊断目标；位置使用方法体相对行号，可能无法映射到条款。
- 状态：`UNOBSERVED` 未观察、`UNPROVED` 本轮未证成、`DISCHARGED` 有当前证明、`UNKNOWN` 信息不足、`STALE` 属于旧候选。

只有真实执行的 Dafny 证据可证明义务。完整成功才能将映射后置条件标为 DISCHARGED；
全文件未通过时，CSV 中明确通过的方法批次仍可被单独记录，不能据此推断其他条款通过。
前置条件始终是调用假设。诊断消失不等于证明成功，超时/未知不等于语义错误。
候选改变后先失效旧证据，再调用验证器；中断也不会保留错误的当前证明。
第一版每轮完整重验，不复用旧证明。每条观察记录实际命令/证据哈希，可追溯验证参数与轮次。

调度优先级：格式拒绝/解析诊断 → 当前未证成诊断或义务 → 过期/未观察 → 未知；同级稳定排序。
修复提示要求针对目标修改实现或不变量并返回所有完整方法体，禁止改变固定契约。

## 运行

复用项目 `.venv` 与 Dafny 4.11，无新增依赖。在仓库根目录执行：

```powershell
# 离线：查看工具链与单题第一轮真实提示，不发 API 请求
.\.venv\Scripts\python.exe -X utf8 -m generation.obligations.cli doctor
.\.venv\Scripts\python.exe -X utf8 -m generation.obligations.cli preflight --task-id absolute

# 四组 smoke；默认模型是“错误实现 → 参考实现”的明确标记 fixture
.\.venv\Scripts\python.exe -X utf8 -m generation.obligations.cli matrix --task-id absolute --output logs/my-obligation-smoke
.\.venv\Scripts\python.exe -X utf8 -m generation.obligations.cli summarize --output logs/my-obligation-smoke

# 单组；省略 --task-id 的 matrix 会运行默认 5 个开发任务的四组
.\.venv\Scripts\python.exe -X utf8 -m generation.obligations.cli run --task-id sequence_max --strategy guided --output logs/my-guided-smoke
```

输出目录必须不存在。Linux 使用 `.venv/bin/python`。
默认配置在 `configs/demo.json`：4 次模型调用、5 次验证（包含最终重验）、每次最多 4096 输出 token、
累计 48000 记账 token、每次验证 15 秒、每题 180 秒。token 预留并非计费保证。
预算不足以预留最终重验时停止；任务准入在运行前单独计数，不占候选生成预算。

真实模型沿用 [模型配置说明](../representation/README.md)：复制本目录 demo，保留新四组和 `contract`，
只修改模型/价格/预算配置；先 preflight，获授权后显式加 `--allow-paid`。
不要直接传旧 representation 配置，其实验条件不属于新协议。凭据只用环境变量引用，不写入 JSON。

## 工件、指标与边界

已完成的 [Codex 独立子代理探索](../../research/CODEX_EXPLORATION_RESULTS_2026_10_06.md) 使用单独协议。`exploration.py` 是父控制器逐次交接响应的队列接口，不是自动模型客户端；单独启动它不会自行创建子代理。该批次不强制 token 上限，不能与严格 API 实验合并。

后续 [公共失败起点修复批次](../../research/COMMON_FAILURE_REPAIR_RESULTS_2026_10_06.md) 使用 `common_failure.py` 和独立协议 `common_failure_codex_repair_v1`。
四组共享预先验证的失败代码、完整公开错误和通用修复指令；D 每轮只修复原始起点，不接收后续反馈。
该入口仍需父控制器交接响应。8 次工件验证通过，1 次实际转交提示偏差已排除比较；原始执行汇总须与偏差记录及审计合读。
扩大批次前应消除手工转抄并核对实际发送文本；计划提示哈希不等于实际模型输入证明。

`handoff.py` 现提供单次文件加载与原会话响应收集，`file_campaign.py` 负责冻结清单、输入审计和永久停止门控。
父控制器仍需派发每个全新子代理；单独启动队列不会创建模型。单次加载以外的工具调用被协议禁止且事后审计，
不是 OS 隔离。每个 solver 请求包含工具选择和读入后回答，累计 token 包含平台上下文；没有硬 token/费用上限。

[文件交接开发矩阵](../../research/FILE_REPAIR_DEVELOPMENT_INTERRUPTION_2026_10_07.md) 在 8 次有效运行后因跨午夜环境更新误停，
原 v1 批次保留为不完整。当前 v2 严格识别平台环境 metadata，只允许日期同日/次日以及原环境字段的重复；
额外任务、普通用户消息、文本夹带和权限变化仍拒绝。收集和消费两端重新审计，旧 response 不自动升级为新协议样本。
[恢复检查方案](../../research/FILE_HANDOFF_RECOVERY_PROTOCOL_2026_10_07.md) 仅四次新运行，不代表 96 次矩阵完成。
[恢复检查结果](../../research/FILE_HANDOFF_RECOVERY_RESULTS_2026_10_07.md)：4 次均有合规终态，9 次响应审计通过；
3 次最终成功、1 次用完预算未通过，出现了真实多轮修复。结果仅作链路检查和轨迹描述。

离线准备 block 随机化调度清单与配对分析：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m generation.obligations.campaign plan --tasks generation/representation --config generation/obligations/configs/development-plan.mock.json --output logs/my-development-plan
.\.venv\Scripts\python.exe -X utf8 -m generation.obligations.campaign analyze --runs logs/my-obligation-smoke --output logs/my-paired-analysis
```

`plan` 仅产生冻结清单，**不会执行模型**；现有 `matrix` 尚不读取此清单。
文件交接探索现由 `file_campaign` 与各批次冻结控制器执行；它不等同于严格 API 预算的通用批量执行器。
`analyze` 要求保留预定作业清单 `jobs.json`，先审计原始工件和完成数量，再对题目做配对和簇 bootstrap；同题重复不当作独立样本。
近重复题需通过 `--clusters` 提供完整的 task ID → 基础算法簇 JSON 映射；省略时假设每题独立，该假设须由数据审计支撑。
它输出描述性区间，不执行确认性假设检验；mock 结果保留明确标记。

每题保存 `manifest.json`、每轮提示/响应/候选/原始验证、`state.json`、事件日志及 `result.json`。
成功必须来自 `final.dfy` 落盘后重新读取并全文件验证的真实证据。
汇总核对候选、规约、工具链、证据和状态指纹；新旧协议不能混合，同一条件重复题目按 task 分组。
同一汇总必须使用同一工具链，同一 task ID 的冻结任务资产必须一致，否则拒绝合并。

`summary.json` 含首次候选通过率、预算内通过率、按题平均通过率、调用/token/时间、
重复候选数、首轮失败后的最终成功率，以及观察到的证明回退与失去可观测性次数。
首轮失败包括模型/格式失败；采样组的该比率代表后续抽样成功，不代表修复效果。
`proof_regressions` 统计已通过义务在改动后被明确报告未证成；`lost_observability` 统计改动后变为 UNKNOWN。
两者均为验证证据变化，不是行为回归的证明。中断、未运行和缺失作业单独保留。

现有题目是开发演示题，mock 知道参考答案，结果仅证明管线可运行。正式实验需冻结独立题集与模型，
每题多次重复，在相同预算下比较四组；不能用本地 fixture 的通过率声称方法有效。
Windows 沿用验证器的父进程终止机制，尚无 POSIX 式整组终止保证；manifest 明确记录该平台差异。
