# 规格引导 Coding Agent 核心实验预注册

状态：在任何真实模型调用和 HumanEval holdout 结果产生之前冻结。日期：2026-08-25。

## 1. 主研究问题

在相同任务、模型家族、温度、模型调用上限、总 Token 上限、Dafny 调用上限、候选上限和墙钟时间上限下，共享且经反例审计的冻结规约，是否比无规约的验证反馈修复提高最终隐藏行为正确率，并降低 `Dafny verified but behaviorally wrong`？

## 2. 条件

- `direct_1`：公开题面与固定签名直接生成一次；只进行最终 Dafny 检查，不反馈修复。
- `direct_verify`：无 Requirement IR、Spec Authority 和 Planner；使用 Dafny 反馈进行有界实现修复。
- `spec_guided`：Requirement IR、Spec Authority、Spec Harness、Planner、双修复通道与有界候选搜索全部开启。

三组使用相同 generation/repair 模型配置。Critic 仅属于 `spec_guided` 的处理成本，必须进入该组预算账本，不能免费排除。

## 3. 阶段

### Phase 0：协议冒烟

- 数据：只根据公开 prompt 中显式类型得到的原生支持子集；当前应为 29/164。
- 条件：三组。
- 重复：3 个 replicate。
- 目的：验证预算、任务配对、Holdout 隔离、失败分类和产物完整性。
- 结果不用于正式效果声明。

### Phase 1：核心确认实验

- 数据：同一冻结原生支持子集。
- 条件：三组。
- 重复：10 个 replicate。
- 主比较：`spec_guided` 对 `direct_verify`。
- 次比较：`direct_verify` 对 `direct_1`。

### Phase 2：全量实验

只有在公开题面类型表完成独立人工复核并冻结后才能开始。类型不得从 `test`、`canonical_solution` 或任何 holdout 诊断推断。全量结果必须同时报告 164 题分母和支持域内分母。

## 4. 固定预算

每题每条件：

- 模型调用上限：12；
- 观测总 Token 上限：50,000；
- Dafny 调用上限：30；
- 候选上限：8；
- Agent 墙钟时间：900 秒；
- 最大修复深度：3；
- 搜索宽度：2。

`direct_1` 按定义只使用一次生成；未使用预算不允许转移给其他条件。

## 5. 指标

主指标：

- `HiddenPass = dafny_verified ∧ humaneval_passed`；
- `VerifiedWrong = dafny_verified ∧ ¬humaneval_passed`。

次指标：Dafny 验证率、拒绝率、支持覆盖、模型调用、Token、验证器调用、候选数、墙钟时间、Spec Harness 风险格、Mutation kill rate。

任何预算耗尽、模型异常、Dafny 异常和不支持任务都保留在分母并单独分类。不得把 `verified` 命名为 `correct`。

## 6. 统计分析

- 分析单位：`task × replicate`，条件间保持配对。
- 二元主指标：报告配对差值、McNemar 检验，并进行任务级配对 bootstrap 95% CI。
- 多重比较：Holm 校正。
- 同时报告绝对差、相对差和原始计数，不只报告 p 值。
- 先分析 Phase 0 的基础设施失败；协议通过后才解封 Phase 1。

## 7. Holdout 防泄漏

官方 HumanEval 测试仅在 Agent 完全停止后运行一次。测试结果、失败输入、异常文本和通过状态均不得进入任何生成、Critic、选择或修复调用。Assisted 模式不属于主实验。

## 8. 解封条件

Phase 1 仅在以下条件全部满足时启动：

1. 单元/集成测试全绿；
2. 环境与 Dafny 版本检查通过；
3. 三组的预算字段和 manifest 完整；
4. Phase 0 无 holdout 回流；
5. API 凭据通过本地配置读取且不进入日志；
6. 工作树版本和 prompt source hash 被 manifest 固定。

