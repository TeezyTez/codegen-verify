# 先让一个真实模型完成一道题

后续已完成9次真实挑战运行，含首次失败后修复以及连续失败；见
[挑战实验与Agent停滞分析](../../research/LIVE_CHALLENGE_2026_09_20.md)。以下保留首次接入流程。

2026-09-20已完成首个真实 DeepSeek `deepseek-flash` 请求和 Dafny 最终验收，见
[真实运行报告](../../research/LIVE_AGENT_2026_09_20.md)。该任务首次成功，未触发真实修复。
同一 SDK 适配器现也接受 `kind=deepseek`；其配置需显式提供 thinking 模式、使用 max_tokens 且不发送 seed。
可参考 `configs/deepseek-live-smoke.json`，其中单价是保守估算，复跑前需核对。

当前重点是可用的单 Agent，不是扩大实验矩阵。沿用现有 `runner.py`，不引入第二套 Agent 框架。

它的职责：读取允许公开的需求 → 模型生成方法体 → 冻结装配 → Dafny 验证 → 返回受控反馈 → 模型再提交实现。
这属于工具驱动的受限生成修复 Agent；编排器控制验证、预算与停止，模型负责实现与证明注释，不能自由运行 shell。
成功后保存并重验 final.dfy，失败则保留每轮记录及停止原因。模型不保证一定能解出任务。

## 1. 配置一个模型，不先跑矩阵

复制 `configs/agent.example.json` 为自己的配置（例如 `/tmp/my-agent.json`），填写：

- `model.name`：你实际拥有权限的模型标识；不是让程序自行猜选模型。
- `model.base_url`：服务端点；当前适配器支持 OpenAI Chat Completions及已实际试跑的DeepSeek分支，其他兼容服务尚未核验。
- `model.api_key_env`：凭据环境变量名称。只在本机安全设置变量，不把密钥写入 JSON 或发到聊天中。
- `budget`：首次调试默认最多3次模型调用、4次验证、120秒。调整输出上限需同时评估总预算。
- 若要求美元费用上限：填写 `budget.cost_usd`、输入/输出每百万 token 单价和 `price_source`。价格未知时不要填虚构数值。

配置只启用 natural + iterative_repair + 一次重复。后续可以在原有配置中切换表示和策略，不需要改 Agent 代码。
本轮开发不加载或检查凭据内容，不作真实付费请求。已有密钥也不代表授权批量调用。

## 2. 先检查，不发请求

```sh
.venv/bin/python -m generation.representation.cli preflight --config /tmp/my-agent.json --task-id absolute --output /tmp/agent-preflight.json
```

preflight 检查工具版本、配置占位符、凭据变量是否存在、首个请求预算是否容纳得下，并给出**实际首轮消息预览**。
不会创建模型客户端或验证 API 权限；`ready_for_authorized_attempt=true` 只是本地启动条件满足。
费用未知、审计 pending 等仍会列为警告。消息预览没有隐藏契约、其他表示或参考答案。
没有配好时返回2，并明确列出 blocker。不会消费模型调用来“试探密钥是否可用”。

## 3. 获得调用授权后，运行一个任务

```sh
.venv/bin/python -m generation.representation.cli run --config /tmp/my-agent.json --task-id absolute --allow-paid --output /tmp/agent-first-live
```

框架先在本地验证正确/错误参考，再开始模型请求。现在终端会逐轮显示：

```text
round 1: requesting model
round 1: response received
round_001: verification_failed
round 2: requesting model
round 2: response received
round_002: verified
final: verified
stopped: verified; model calls=2, verify calls=3
```

以上只是**输出格式示意，不是真实模型运行结果**；模型也可能首次成功、生成非法格式或耗尽预算。
`--quiet` 只关闭进度显示，不改变提示、验证或预算。

如需查看结果：

```sh
.venv/bin/python -m generation.representation.cli summarize --output /tmp/agent-first-live
```

结果目录含每轮实际请求、原始响应、候选、原始验证日志、受控诊断、final.dfy 和总结。
无成功工件时先根据停止原因定位：provider 错误、输出格式错误、形式证明失败或预算耗尽；不要把它们混成模型不会写代码。

## 服务失败时的行为

- SDK 自动重试为0，每一次请求均经过 Agent 的预算记账。
- 限流/服务错误读取安全的 Retry-After 延迟，缺失则使用有界退避；等待计入总时限。
- 服务器要求等待超过任务剩余时间或60秒时，停止并记录原因，不忽略服务器要求继续请求。
- 鉴权、权限、请求参数错误停止，不重复消耗额度。
- 输出被截断记 `output_truncated`，即使看起来像完整 JSON 也不当完整候选接受。
- 错误日志不包含原始 HTTP 头、供应商错误正文或凭据。

行为依据：[官方 Python SDK 文档](https://developers.openai.com/api/reference/python)及
[官方错误处理说明](https://developers.openai.com/api/docs/guides/error-codes)，2026-09-20核对。
依旧不是硬实时或生产安全沙箱：传输 timeout 不是可强杀的总进程时限，费用预留不是供应商账单的数学上界。

## 已测与未测

已测试：真实 SDK 对请求/响应的序列化、内存 HTTP transport 中的429/503/400/401处理、截断识别，
以及 SDK → 真 Dafny → 反馈 → SDK → 最终重验的端到端接口。传输层返回人工数据，始终标为 mock。
首轮接入准备阶段未测试真实API；后续DeepSeek单任务的权限、参数兼容性与生成验收现已实际验证，见顶部报告。
其余模型、真实反馈修复能力和账户实际扣款仍未核验。

下一步只需选定提供商、模型与首次试答费用上限，配置凭据后跑一道题；不需要再建多 Agent、规划器或数据库。
