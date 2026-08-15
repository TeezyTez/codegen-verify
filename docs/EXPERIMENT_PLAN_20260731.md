# 规约引导代码生成：核心三条件实验

## 研究问题

1. 生成语义规约后再生成代码，是否比只给方法签名更能提高端到端正确率？
2. 规约带来的收益是否来自真正的引导与证明，而不是直接执行 Reference？
3. 独立实现条件下，验证、规约修复和代码修复分别贡献了多少成功案例与成本？

## 本轮实验条件

固定 HumanEval `0..19`、DeepSeek Chat、温度 `0.2`、最多三轮修复、Dafny 4.11、
strict 留出协议、advisory Critic、关闭模板回退和 mutation 自动加强。只改变
`SPEC_GUIDANCE_MODE`：

| 条件 | 语义规约 | 允许实现调用最终 Reference | 用途 |
|---|---|---|---|
| `signature_only` | 否 | 不适用 | 直接代码生成基线 |
| `independent` | 是 | 否（含间接调用） | 论文主方法 |
| `executable_reference` | 是 | 是 | 可执行规约复用上界/泄漏消融 |

## 指标与判定

主指标是全部任务上的端到端通过率。同步报告 Dafny 通过率、验证后错误交付率、
代码生成覆盖率、平均修复轮次、调用数、token 和耗时。

本轮 20 题单次运行属于流程验证和效应量探索，不用于显著性结论。进入论文主表前，
至少扩展到完整支持集并做多次独立重复。建议的阶段性判断标准：

- `independent` 相比 `signature_only` 有正向端到端增益；
- `independent` 与 `executable_reference` 的差距不超过 10 个百分点；
- 已验证代码的错误交付率不高于 5%；
- 失败主要能归因到规约、独立实现或证明修复，而不是 Critic 提前拒绝。

若第二条差距很大，说明当前规约更像可执行答案，而不是对独立实现有效的指导，下一步
应优先改进 proof-friendly specification、invariant synthesis 和验证反馈路由。

## 执行命令

```bash
python project/run_humaneval.py --mode strict --critic-gate-mode advisory \
  --spec-guidance-mode signature_only --start 0 --limit 20 --rounds 3
python project/run_humaneval.py --mode strict --critic-gate-mode advisory \
  --spec-guidance-mode independent --start 0 --limit 20 --rounds 3
python project/run_humaneval.py --mode strict --critic-gate-mode advisory \
  --spec-guidance-mode executable_reference --start 0 --limit 20 --rounds 3
```
