# 固定规约表示 × 验证修复 Agent

2026-09-20：要先接入真实 AI 答一道题，请按 [Agent 快速接入](AGENT_QUICKSTART.md) 操作。
新增无请求 preflight 和逐轮进度，沿用本目录同一个 Agent 循环；不是另建实验系统。
同日已完成DeepSeek真实单题试跑，见 [真实运行报告](../../research/LIVE_AGENT_2026_09_20.md)。

当前协议 `fixed_spec_representation_v1`。这是单 Agent 论文预实验原型，不是论文结论、生产沙箱或 MDA/PSM 平台。
既有 `generation.cli` 的 G00–G11 与 `repair.cli` 保留不变；本入口复用其装配、边界检查、验证解析和日志工具，
但**不复用会公开完整契约的旧提示词**，也不混合历史实验结果。

## 从安装到首个样例

在仓库根目录操作。已有 `.venv` 时直接复用，不必重建。新环境：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

本次核验版本：Python 3.12.13、openai SDK 3.2.0、Dafny 4.11.0。
从 [Dafny 官方 4.11.0 发布页](https://github.com/dafny-lang/dafny/releases/tag/v4.11.0) 下载适合系统/架构的发行包并解压，
按官方发行说明安装运行依赖。将其中 `dafny` 可执行文件加入 PATH，或设置 `DAFNY_PATH` 为它的绝对路径。
也可在下面命令中加 `--dafny /absolute/path/to/dafny`。
无需 API 密钥即可完成所有 mock + 真实 Dafny 演示；缺少 Dafny 时不会假装验证通过。

最短三条命令（输出目录必须尚不存在）：

```sh
.venv/bin/python -m generation.representation.cli doctor
.venv/bin/python -m generation.representation.cli run --task-id absolute --strategy iterative_repair --representation natural --output /tmp/representation-first
.venv/bin/python -m generation.representation.cli summarize --output /tmp/representation-first
```

第二条会先真实验证参考/错误实现，再由**确定性 mock**依次提交错误体和参考体；最终候选重新验证。
它只证明工程闭环，不能说明模型能够修复。查看输出目录的 `summary.md`、`summary.csv`、`summary.json`。
用新目录重跑，避免覆盖或复用其他实验条件。

## 数据校验、矩阵与测试

```sh
# 仅检查 schema、哈希和映射覆盖；不等于人工语义审查
.venv/bin/python -m generation.representation.cli validate --schema-only

# 真实检查全部 5 个正确参考和 5 个错误实现
.venv/bin/python -m generation.representation.cli validate --output /tmp/representation-admission

# 5 任务 × 3 表示 × 3 策略 × 1 重复，默认 mock，不调用 API
.venv/bin/python -m generation.representation.cli matrix --config generation/representation/configs/demo.json --output /tmp/representation-matrix
.venv/bin/python scripts/check_representation_artifacts.py /tmp/representation-matrix

.venv/bin/python -m pytest tests/test_representation_agent.py -q
```

`--task-id` 可缩小矩阵；`--replicate` 用于配置范围内的单次 run。
CLI 命令：`doctor / preflight / validate / run / matrix / summarize`。
doctor 返回 0 表示检测到已测试的 Dafny 4.11 系列；其他版本不自动宣称兼容。
matrix 中模型失败是保留的实验结果，不等于 CLI 崩溃；准入失败退出 2 并且不创建模型客户端。
所有任务、条件的计划清单在执行前保存；未完成项会明确出现在汇总中。

## 三种输入，三种策略

| 策略 | 模型看到前次实现/诊断？ | 模型调用 | 验证 |
|---|---|---|---|
| single_shot | 否 | 最多 1 次（服务失败也不隐式重试） | 仅最终文件完整验证一次 |
| iterative_repair | 是，当前合法方法体与 `controlled_v1` 诊断 | 配置上限内 | 每个候选验证，成功候选另作最终重验 |
| independent_sampling | 否，每次发送相同的新消息 | 与 iterative 相同预算上限 | 仅编排器看到结果并选择，成功候选另作最终重验 |

每种策略支持 `natural / checklist / structured`。所有方法签名、验收条件、语言约束和反馈策略固定。
structured 是 `constraints_v1` JSON：`constraints` 数组的每条含 `requirement_id/kind/subject/relation/value`。
它是手工表示，不是 PSM，也没有自动翻译为 Dafny 的流程。
natural 也携带公开 `[R1]` 标识，避免只有结构化组能理解反馈编号。

默认每 run：3 次模型调用、4 次验证、2048 输出 token、48000 记账 token、单次验证 15 秒、
单次 SDK timeout 60 秒、任务 120 秒。single_shot 的一次性预算由定义决定，不能将其与多次修复的差异全归因于反馈。
independent_sampling 才是多调用的计算预算对照。实际消费和上限都记录，三种表示的 token 长度不强行填充到相等。
每次失败的 API 尝试占用模型调用额度，SDK 隐式重试关闭；下一轮重试另计 `model_retry_calls`。

## 输入与信息泄露边界

模型消息仅含系统输出协议与白名单：task_id、公开签名、共享定义（v1 为空）、**选定的一个表示**。
修复策略另带当前合法方法体和受控诊断。没有完整任务对象、隐藏 requires/ensures、验收模板、参考实现、
运行样例、其他表示、隐藏契约行号或剩余耗时；不复用别的任务/重复的消息。

诊断只返回稳定类别、可定位的公开 requirement_id、方法体内相对行号；不能准确归因时写 `unknown`。
原始 stdout/stderr 常含完整契约，只保存到本地工件，不回传模型。不能用错误条数估计满足约束的比例。
默认 `additional_spec_disclosure=false`；若以后要增加信息，必须升级协议并重新审计全部表示条件。

mock 适配器本身刻意读取参考体，用作测试夹具；它的身份为 `uses_reference=true`，始终单独统计。
真实适配器只接收消息，没有任务对象。即使 mock 使用真实 Dafny，也不是模型能力证据。

## 固定验收与安全范围

- 只收 `{"bodies":{"MethodName":"..."}}`，不可覆盖完整文件；可信代码复用既有冻结头部装配。
- 复用词法/边界检查，再增加受限语句解析、括号/块嵌套检查、while 必须有显式循环体。
- 可用赋值、初始化变量、if/else、while、不变式/decreases、assert、return、整数与序列表达式。
  v1 不支持任意共享声明、独立辅助引理、方法调用语句、字符串、注释、属性、导入、分配或 I/O。
- 禁止 assume/axiom、havoc、无体循环、通配 decreases、受信任声明和提前闭合区域；表达式还需真实 Dafny 解析/类型检查。
- 每次验证前后检查任务文件、内存冻结资产和配置；最终验收重新读取持久化工件并检查其哈希。
- 只运行固定参数的 `dafny verify`，不编译/执行生成代码，不运行模型提供的宿主命令；独立临时目录、最小环境、POSIX 超时杀进程组。
- 状态区分 `verified / parse_error / verification_failed / timeout / tool_error / invalid_candidate / unknown`。
  parse_error 包含解析与类型/名称解析失败。缺少预期 CSV 批次、非零退出码、假验证器均不能产生成功。

成功只表示固定规约及 Dafny/求解器可信链下完整验证通过，不等于所有现实需求已满足。
这不是完整 Dafny AST 审计器或生产级安全沙箱；没有 OS 强隔离和内存配额。
SDK timeout 是传输超时，不是可强杀的全进程 deadline；模型返回后若超出任务时间/预算会拒绝接受结果。
token 预留使用 UTF-8 长度加开销，是保守工程记账而非供应商计费的形式上界，必须监控实际账单。

## 真实模型：显式配置与授权后才运行

复用一个 OpenAI Chat Completions SDK 适配器，含OpenAI与DeepSeek请求参数分支；不猜测采样参数支持。
先复制 `configs/live.example.json` 为本地配置，填入已有权限的 `model.name`、HTTPS `base_url`、
凭据环境变量名和预算；配置文件不接受 api_key 明文。由调用者在环境中安全设置该变量。
如果该模型支持 temperature/top_p/seed，再显式配置；默认不发送这些可选参数，API 拒绝时不偷偷删除参数重试。
SDK 3.2.0 的构造器/方法签名已在本地核对；DeepSeek分支已经真实单题试跑，OpenAI端点尚未进行真实调用验证。

编辑配置、确认数据允许外发并获得费用授权后，准确运行命令为：

```sh
.venv/bin/python -m generation.representation.cli run --config /absolute/path/to/live.json --task-id absolute --strategy iterative_repair --representation natural --allow-paid --output /tmp/representation-live-first
```

未知价格、用量或费用保持 null。若启用 cost_usd 上限，必须同时填写输入/输出单价与 `price_source`；
缺少价格时拒绝启动这种费用上限配置，不编造估价。API 超时/失败的未知费用按预留值控制后续调用，实际费用仍标未知。
开发与离线测试不读取凭据内容；SDK 只在显式授权的实际请求中获取凭据，日志不保存它。

## 工件与复现

suite 保存 config、jobs、admission 和三种格式汇总。每个 run 保存 manifest、逐轮消息/哈希、响应、
提取方法体、装配文件、原始验证日志/CSV、受控诊断、events.jsonl、最终文件与结果。
manifest 含任务/规约/表示/映射/模板/配置/源码哈希、Git revision、Dafny/SDK 版本、实际请求参数和种子策略。
最终通过必须来自真实验证；接口测试替身即使返回 verified 也不会被算成功。

Ctrl-C 保留已完成轮次、调用预留和 `completed=false` 的结果。硬终止后最近检查点可能仍显示未完成，
中断的真实请求可能仍被供应商计费，因此未返回用量的请求保留 unknown，费用不写为零。
所有缺失/未完成作业都进入汇总。**不实现断点续跑**，不自动复用任何旧预算账本。
新建输出目录独立重跑，不能删除失败记录来提高成功率。
汇总按 mock/真实模型、人工审计状态、表示、策略、配置分组，同时报告独立任务数、每任务重复编号和任务平均成功比例。
不提供显著性/p 值；重复不能当新任务，缺失矩阵不能推断实验效应。

## 数据与研究边界

5 项自建 `synthetic_demo`，数据声明 CC0-1.0（仅这些新演示数据，不修改仓库其他代码/论文的许可）：
absolute、clamp、remaining、sequence_last、sequence_max。后者的参考使用循环和不变式；不强制生成器必须复制该算法。
一项来源项目、全部 dev、没有独立测试集。表示、参考、错误实现均由同一实现者准备，
`equivalence_audit.status=pending`；schema/映射覆盖和真实验证不能替代人工语义审查或证明规约非空、充分。

研究控制与威胁见 [EXPERIMENT.md](EXPERIMENT.md)。正式研究仍需外部任务、许可核查、独立表示等价性与验收充分性审查，
以及真实模型重复对照，不能把演示数据包装成论文基准。

## 官方接口依据

- [Dafny 4.11.0 Reference](https://dafny.org/v4.11.0/DafnyRef/DafnyRef)：§8.15.1–8.15.4，特别是无体循环/证明可被验证器暂时接受的边界；另核对本机 `dafny verify --help` 的 CSV、超时和固定参数。
- [OpenAI Python SDK 官方文档](https://developers.openai.com/api/reference/python)：Retries/Timeouts；显式禁用隐藏重试并配置请求超时。
- [Chat Completions 官方参数](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)：输出上限与可选采样参数；实际仅发送配置指定字段。

初版接口核验日期：2026-09-17；当时未执行真实API请求。2026-09-20后续真实DeepSeek请求与证据见顶部报告。
