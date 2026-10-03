# 首次真实模型 Agent 试跑：2026-09-20

**本次不是 mock：真实 DeepSeek API 生成候选，真实 Dafny 验证。**
一个任务、一个表示、一次运行；结果用于确认在线链路，不作方法效果或论文结论。

## 配置及选择理由

仓库已有 DeepSeek 凭据，旧 CODE_MODEL 为 deepseek-chat。官方停用公告与现行接口文档表明需要改用当前模型名；
仅在本次独立配置中选择 `deepseek-flash`，没有修改用户 `.env`，没有将密钥写入工件。
模型选择、真实服务返回的模型名和指纹均记录，不将旧模型与新模型混算。

同一个 SDK 适配器增加 DeepSeek 参数分支：`max_tokens`，显式 `thinking=disabled`，
不发送该服务未声明支持的 `store` 或 seed 参数。temperature=0.2，使用自然语言表示与 iterative_repair 策略。

范围：`sequence_max`，5个自建演示任务中包含循环证明的任务。最多3次模型调用、4次在线验证、
每次2048输出 token、16000记账 token、180秒和0.05美元费用预留上限；数据准入另计。
API输入只包含公开签名、自然语言需求和统一输出协议，不包含参考实现、隐藏验收规约、其他表示或公司代码。

## 实际结果

| 指标 | 观测 |
|---|---|
| 请求模型 / 返回模型 | deepseek-flash / deepseek-flash |
| is_mock | false |
| 任务 | sequence_max：非空整数序列的最大值 |
| 候选数 / 模型调用数 | 1 / 1 |
| 首次候选 | 完整验证通过 |
| 最终工件重验 | 完整验证通过 |
| 在线正式验证调用 | 2；准入另2次 |
| 输入 / 输出 token | 251 / 162，供应商实际报告 |
| 缓存命中 / 未命中输入 | 0 / 251 |
| 模型耗时 | 约1.614秒 |
| 在线验证耗时合计 | 约1.586秒 |
| 单run总耗时 | 约3.205秒，不含准入 |
| 费用估算 | 0.0002697美元；按高峰输入未命中0.30美元/M、输出1.20美元/M计算 |

费用是保守单价估算，**不是账户实际扣款回执**；没有把低峰折扣计入。0.05美元是本地预留上限，不是消费额，
也不是供应商计费的数学保证。本次已完成的使用量远低于上限。

模型返回实现包含：初始最大值、顺序扫描循环、索引范围不变式、已扫描元素的上界不变式、
当前最大值属于已扫描元素的存在性不变式、终止度量，以及最终断言。
这些方法体内容由模型生成；requires/ensures 来自框架冻结装配。
Dafny 最终报告 `2 verified, 0 errors`，对应 Maximum 的 well-formedness 和 correctness 批次，**不是两个任务成功**。

## 工件

- [运行配置](../generation/representation/configs/deepseek-live-smoke.json)
- [无API请求的启动检查](runs/2026-09-20-deepseek-preflight.json)
- [实际发给模型的消息](runs/2026-09-20-deepseek-live-sequence-max/0000_sequence_max_iterative_repair_natural_0/round_001.messages.json)
- [实际模型响应及token](runs/2026-09-20-deepseek-live-sequence-max/0000_sequence_max_iterative_repair_natural_0/round_001.response.json)
- [最终程序](runs/2026-09-20-deepseek-live-sequence-max/0000_sequence_max_iterative_repair_natural_0/final.dfy)
- [最终结果与原始验证证据](runs/2026-09-20-deepseek-live-sequence-max/0000_sequence_max_iterative_repair_natural_0/result.json)
- [汇总](runs/2026-09-20-deepseek-live-sequence-max/summary.json) · [只读工件与输入审计](runs/2026-09-20-deepseek-live-audit.json)

## 实际运行命令

```sh
.venv/bin/python -m generation.representation.cli preflight --config generation/representation/configs/deepseek-live-smoke.json --task-id sequence_max --output research/runs/2026-09-20-deepseek-preflight.json
.venv/bin/python -m generation.representation.cli run --config generation/representation/configs/deepseek-live-smoke.json --task-id sequence_max --strategy iterative_repair --representation natural --allow-paid --output research/runs/2026-09-20-deepseek-live-sequence-max
.venv/bin/python scripts/check_representation_artifacts.py research/runs/2026-09-20-deepseek-live-sequence-max --output research/runs/2026-09-20-deepseek-live-audit.json
```

已有输出不能覆盖，复现须使用新路径并另行确认调用授权。无隐式SDK重试，没有开展批量实验。
本次相关适配/Agent测试87项通过；最终全仓库回归 **357 passed，2 subtests passed，49.44秒**。
[全仓库测试XML](runs/2026-09-20-deepseek-adapter-tests.xml)

## 能得出的结论

已经实际打通：真实模型请求 → 合法实现提取 → 冻结规约装配 → 全文件证明 → 最终持久化重验 → 成本及轨迹记录。
当前模型在这道题上不需要修复。**因此没有验证真实反馈驱动的修复能力**，也没有比较三种表示或独立采样。
不能将1/1成功解读为通用成功率100%。表示等价性仍 pending，演示任务不是独立论文测试集。

下一项有价值的检查是保持规约与提示协议不变，在更有代表性的任务上观察自然出现的失败，
再检验模型收到受控诊断后能否修复；不人为削弱提示或放松验收来制造对比。

## 官方依据（2026-09-20核对）

- [DeepSeek现行模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)
- [DeepSeek Chat Completions参数](https://api-docs.deepseek.com/api/create-chat-completion/)
- [deepseek-chat停用公告](https://api-docs.deepseek.com/news/news260424/)
- [OpenAI SDK调用与重试说明](https://developers.openai.com/api/reference/python)

部分官方页面直接抓取超时，模型/价格/参数使用可访问的官方域名索引正文核验；实际请求参数接受情况、
返回模型名与token统计又由本次API响应确认。SDK复用依照OpenAI Docs核验，不新增独立模型调用框架。
