# 第三方代码与任务来源

`repair/tasks/clover_double/original.dfy` 和 `repair/tasks/clover_array/original.dfy`
来自 [DafnyBench 官方仓库](https://github.com/sun-wendy/DafnyBench)，2026-09-08 获取。
仓库级许可为 Apache-2.0，完整文本保存在 [LICENSE.DafnyBench](LICENSE.DafnyBench)。
保留上游文件原样；作者与来源归属不因本地派生而改变。原文件没有另附版权头。

| 本地任务 | 上游路径（main） | 本地修改 |
|---|---|---|
| clover_double | `DafnyBench/dataset/ground_truth/Clover_double_quadruple.dfy` | `2*x` 改为 `2+x`，加入冻结 Consumer 与区域标记 |
| clover_array | `DafnyBench/dataset/ground_truth/Clover_array_sum.dfy` | 删除一条循环不变量，加入冻结 ArrayClient 与区域标记 |

每个 task.json 有直接来源 URL。此次网络条件未取得可靠 commit ID，因此不捏造版本；
`source_revision` 如实写 main，已取得的 original 字节与 SHA256 在 validation.json 中固定。
正式测试集发布前仍需补齐上游提交、所有来源项目许可审查和近重复审计。

本地变异/缺失注释不是上游真实 bug，也不宣称与官方 hints_removed 切分完全相同。
新增调用者是人工组合，只测模块化验证的工程行为。`counter` 和 `arithmetic` 是本仓库人工编写的诊断任务。
reference.json 和 replay.json 是公开可见的工程测试材料；真实模型只收到 program.dfy 和可编辑区元数据，不会读取这些文件。
