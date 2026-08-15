# 规约引导代码生成：20 题核心消融实验报告

## 结论摘要

本轮结果暂不支持“当前的规约引导独立实现流程优于直接代码生成”这一假设：

- `signature_only` 端到端通过 11/20（55%）；
- `independent` 端到端通过 5/20（25%），比直接生成低 30 个百分点；
- `executable_reference` 端到端通过 15/20（75%），比独立实现高 50 个百分点。

因此，主要问题不是生成规约完全无用，而是当前系统不能稳定地把语义规约转换成
可独立证明的实现。可执行 Reference 是有信息量的诊断上界，但不能作为论文主方法的
正确率：它允许实现复用规约中的答案，也仍可能把错误规约验证为正确程序。

## 实验协议

实验固定以下因素，只改变规约使用方式：

- 数据：HumanEval `0..19`，共 20 题；
- 模型：Spec、Code、Repair、Critic 均使用 `deepseek-chat`；
- 温度：0.2；
- 验证器：Dafny 4.11；
- 修复：最多三轮；
- 评测：strict 留出协议，不向生成或修复阶段提供官方测试反馈；
- Critic：advisory，不因拒绝或不确定而阻止后续生成；
- 模板回退：关闭；
- mutation 自动加强：关闭；
- 数据 SHA-256：`1d49078ba3e2b196b9344535bef34a43021f038fad9561d6ee7c53450609a6a2`；
- Prompt 源 SHA-256：`ebac48421bc21214a7772c4d37b26168a072639f4aafeac96320fda94f9fc257`；
- Git 基础提交：`f6be8e5960c9fec8ce7505bfae81b7d99526c41e`；
- 三组实验工作区哈希均为：
  `23da9d8d2f7148e981bd57b3de97fd04b320b041aacd9c751b706bb4a27cbbb7`。

三组条件为：

| 条件 | 语义规约 | 实现能否执行最终 Reference | 研究角色 |
|---|---:|---:|---|
| `signature_only` | 否 | 不适用 | 直接代码生成基线 |
| `independent` | 是 | 否，包含间接调用 | 论文主方法 |
| `executable_reference` | 是 | 是 | 可执行规约复用上界 |

## 主要结果

| 条件 | 端到端正确 | 95% Wilson CI | Dafny 通过 | 验证后错误交付 | 平均轮次 | 总耗时 | LLM 调用 | 总 token |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `signature_only` | 11/20（55%） | 34.2%–74.2% | 12/20（60%） | 1/12（8.3%） | 2.25 | 8.6 分钟 | 78 | 217,745 |
| `independent` | 5/20（25%） | 11.2%–46.9% | 5/20（25%） | 0/5（0%） | 2.70 | 25.1 分钟 | 227 | 557,934 |
| `executable_reference` | 15/20（75%） | 53.1%–88.8% | 16/20（80%） | 1/16（6.3%） | 1.60 | 19.1 分钟 | 148 | 340,038 |

三组均生成了 20/20 题的候选代码。这里的“端到端正确”要求同时通过 Dafny 验证和
HumanEval 官方测试；“验证后错误交付”指 Dafny 通过、但官方测试失败。

通过题目如下：

- `signature_only`：0、2、5、9、10、12、13、14、16、17、18；
- `independent`：0、2、5、15、17；
- `executable_reference`：0、2、4、5、6、7、8、10、11、12、13、14、16、17、18。

## 配对观察

按同一题号作探索性配对比较：

| 比较 | 前者独有成功 | 后者独有成功 | 共同成功 | 双侧精确 McNemar p |
|---|---:|---:|---:|---:|
| `signature_only` vs `independent` | 7 | 1 | 4 | 0.0703 |
| `executable_reference` vs `independent` | 11 | 1 | 4 | 0.00635 |
| `executable_reference` vs `signature_only` | 5 | 1 | 10 | 0.2188 |

这些 p 值只用于定位效应，不应作为论文显著性结论。每组目前只有一次模型采样，三组
也没有复用完全相同的中间规约，既有样本量小，也有生成随机性混杂。

## 正确性与安全性

`independent` 没有出现验证后错误，但其可交付覆盖只有 5 题，因此不能仅凭 0% 错误率
断言它更可靠。`signature_only` 在 HumanEval/15 出现一次 Dafny 通过但官方测试失败；
`executable_reference` 在 HumanEval/9 出现同类错误。

HumanEval/9 尤其值得注意：Critic 曾拒绝该规约，但 advisory 策略仍允许程序直接执行
Reference，最终 Dafny 通过而官方测试失败。这说明 Critic 策略应依模式区分：

- 对 `independent`，Critic 可以继续 advisory，因为后续独立实现与证明仍有纠错机会；
- 对 `executable_reference`，若程序执行 Reference，则应要求更严格的规约审核或独立
  行为校验，否则规约错误会直接变成已验证程序错误。

## 失败归因

`independent` 的 15 个失败中，最终自动归因主要为：

| 归因 | 数量 |
|---|---:|
| proof obligation gap | 10 |
| implementation semantics mismatch | 2 |
| loop proof gap | 1 |
| spec/code mismatch | 1 |
| public contract drift | 1 |

该条件共触发 56 次验证尝试、12 次 proof repair、2 次 verification-guided spec repair，
仍只通过 5 题。日志中反复出现的模式是：Reference 使用递归、序列切片或拼接描述语义，
实现采用迭代循环，但缺少能够连接两者的前缀/后缀分解引理、fold 引理和循环不变式。
多轮修复往往增加辅助声明，却没有建立最终等价关系。

Critic 不是这轮低通过率的直接门槛：`independent` 中 8 个规约获批、7 个被拒、5 个
不确定，而 12 个风险案例都因 advisory 模式继续进入代码生成与修复。当前更值得投入的
位置是 proof transfer，而不是继续调低 Critic 拒绝率。

## 对研究假设的解释

本轮数据给出三个不同层面的信号：

1. 当前主流程没有实现预期收益。`independent` 比直接生成低 30 个百分点，且调用量约为
   2.9 倍、token 约为 2.6 倍。
2. 规约语义并非普遍错误。允许执行 Reference 后达到 75%，说明许多 Reference 能表达
   正确行为，至少可以充当语义 oracle 或诊断上界。
3. 规约目前更像“另一个实现”，还不是适合证明独立程序的接口。独立条件与可执行条件
   相差 50 个百分点，核心缺口是从递归语义到迭代实现的证明桥梁。

因此，项目没有偏离“规约引导生成更正确代码”的研究目标，但当前实现重心偏向了
规约审核和通用反复修复，尚未形成最关键的、可复用的证明结构生成能力。

## 下一阶段实验设计

### 阶段一：冻结中间产物，定位 proof transfer

先保存一套固定的 TaskIR、规约和 Reference，使各方法使用完全相同的语义输入，再比较：

1. 当前 `independent`；
2. `independent + proof skeleton`：规约阶段同时生成实现方向、循环状态和关键不变式；
3. `independent + lemma library`：注入序列拼接、切片、map/filter/fold、sum/product 等
   已验证通用引理；
4. `independent + proof skeleton + lemma library`；
5. `executable_reference`，仅作为上界。

主指标仍为全体任务端到端正确率；另外报告“Dafny 通过但官方失败”、验证尝试数和 token。
若第 2–4 组不能显著缩小与上界的差距，就要重新设计规约表示，而不是继续增加修复轮数。

### 阶段二：验证每个组件的净贡献

对阶段一最优独立实现配置做以下消融：

- 无语义规约；
- 有规约、无 Critic；
- Critic advisory 与 strict；
- 无 verification-guided spec repair；
- 无 proof repair；
- 一轮与三轮修复。

这样可以把“规约生成”“审核”“证明修复”和“额外采样预算”的贡献分开，避免指标过多
但无法回答研究问题。

### 阶段三：扩大样本并报告统计不确定性

先在 20 题上对关键条件做至少 5 个独立随机种子；确认趋势后，再运行完整 HumanEval
支持集。论文主表建议只保留：

- 端到端正确率；
- Dafny 通过率；
- 验证后错误交付率；
- 生成覆盖率；
- 每个成功任务的调用/token/耗时。

Critic 接受率、修复类型、mutation 指标适合作为诊断或附录指标，不应与端到端正确率
并列为核心目标。

## 本轮产物

- 实验设计：`docs/EXPERIMENT_PLAN_20260731.md`；
- 主方法：`logs/runs/20260731_core_ablation_independent_s1_retry2`；
- 直接生成基线：`logs/runs/20260731_core_ablation_signature_only_s1`；
- 可执行 Reference 上界：`logs/runs/20260731_core_ablation_executable_reference_s1`。

另有两个中止目录，不纳入任何统计：

- `20260731_core_ablation_independent_s1`：网络 DNS 失败；
- `20260731_core_ablation_independent_s1_retry1`：静态 guard 将 invariant/assert 中的 ghost
  Reference 引用误判为运行时调用。修复 guard 并通过测试后，三组有效实验才在同一代码
  快照上依次执行。
