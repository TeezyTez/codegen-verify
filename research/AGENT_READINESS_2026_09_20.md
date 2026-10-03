# 单 Agent 真实模型接入准备：2026-09-20

目标从扩大矩阵转为让一个真实模型完成一道生成—验证—修复任务。
沿用既有 `generation/representation/runner.py`，不新建第二套 Agent，不新增多 Agent 或额外研究机制。

## 本轮增量

- `preflight.py` / CLI `preflight`：无 API 请求的本地检查，预览真实首轮消息、预算和任务/配置哈希；凭据只检查变量是否存在。
- `cli.py` / `runner.py`：逐轮请求、验证、重试等待与停止进度。显示回调与模型消息分离，`--quiet` 不影响实验条件。
- `models.py` / `runner.py`：SDK 隐式重试保持0；显式处理 Retry-After、有界退避、非重试性错误和输出截断。等待计入任务时间。
- `configs/agent.example.json`：只启用 natural + iterative_repair + 一次重复的首题配置，占位模型必须由用户指定。
- [接入说明](../generation/representation/AGENT_QUICKSTART.md)：本地配置 → preflight → 明确授权后单题运行。

官方 Python SDK 与错误处理文档核对链接已列在接入说明中；这次未选定真实模型，也未填写虚构价格。

## 执行证据

1. 新接入测试加既有 Agent 测试：86 passed，20.65秒。
2. 最终全仓库回归：**356 passed，2 subtests passed，52.30秒**。
   [测试 XML](runs/2026-09-20-agent-tests.xml)
3. 真实 OpenAI SDK + `httpx2.MockTransport` + 真实 Dafny 的端到端接口测试通过。
   HTTP 响应是人工夹具，网络未访问；该测试适配器标记 `kind=mock`、`uses_reference=true`，不计入真实模型结果。
   测试确认第二轮实际 SDK 请求包含前次方法体和受控失败诊断，没有隐藏契约。
4. 单题 CLI 回归通过：错误候选 → 验证失败 → 正确候选 → 验证成功 → 最终文件重验。
   2次 mock 调用、3次真实验证；准入另2次真实验证。
   [单题汇总](runs/2026-09-20-agent-offline-smoke/summary.json) ·
   [输入/工件审计](runs/2026-09-20-agent-offline-audit.json)
5. 无请求检查工件：[离线 preflight](runs/2026-09-20-agent-preflight-offline.json)。
   它使用 mock 配置，不能作为真实凭据或服务可用性证明。

执行命令：

```sh
.venv/bin/python -B -m pytest -q -p no:cacheprovider --junitxml=research/runs/2026-09-20-agent-tests.xml
.venv/bin/python -m generation.representation.cli preflight --task-id absolute --output research/runs/2026-09-20-agent-preflight-offline.json
.venv/bin/python -m generation.representation.cli run --task-id absolute --strategy iterative_repair --representation natural --output research/runs/2026-09-20-agent-offline-smoke
.venv/bin/python scripts/check_representation_artifacts.py research/runs/2026-09-20-agent-offline-smoke --output research/runs/2026-09-20-agent-offline-audit.json
```

## 接下来的唯一外部决策

用户确认提供商、实际模型和首次试答费用上限，在本机配置凭据后，执行一个任务。
当前适配器核对对象为 OpenAI Chat Completions；不能把其他“兼容 API”默认当成已测试服务。
还没有真实模型推理、在线服务权限/参数兼容性或费用证据。API费用为0。
现有 pending 表示审计不妨碍工程 smoke，但不能据此进入正式论文效果结论。

这不是完整自主通用 Agent：编排器固定验证与预算流程，模型在受限范围内生成/修复实现。
保持这一边界是当前研究原型的设计，不通过增加任意 shell 或规划工具来扩大权限。
