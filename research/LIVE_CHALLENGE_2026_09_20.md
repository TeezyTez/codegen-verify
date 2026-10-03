# 真实模型挑战实验：首次失败、修复与停滞

日期：2026-09-20。**真实 DeepSeek API + 真实 Dafny 4.11；没有 mock 模型成绩。**
复用已有 Agent、装配器、诊断策略及验证配置，未为了得到失败改变提示或破坏候选。

## 结论先行

三道新开发题各独立试答三次，共9次运行：6次首轮通过，1次第4轮修复成功，2次四轮全部失败。
后两次都发生在序列反转：模型收到反馈，却四轮提交完全相同的实现。
因此现在已有真实的“首次没答对”“随后修复成功”“预算内仍修不好”三种轨迹。
这里的“没答对”指未通过固定规约完整验收，不等于找到了算法语义反例。

## 预先确定的范围

见[请求前写定的任务说明与实验计划](../generation/representation/challenge_tasks/README.md)和
[实际配置](../generation/representation/configs/deepseek-challenge.json)。

- 模型：deepseek-flash，thinking=disabled，temperature=0.2，服务实际返回同名模型。
- natural + iterative_repair；三题 × 三次。每次独立消息状态，未把先前答案传给后续重复。
- 每次最多4次模型请求、5次验证（预留最终重验）、4096输出token/请求、48000记账token、
  15秒/验证、180秒/运行、$0.05本地费用预留；九次合计预留$0.45，不是已消费额。
- 所有题先通过真实准入：正确参考 verified，负对照 verification_failed。
- 所有九次运行完整保留，没有挑选最好结果或丢弃失败。中途未修改框架、任务、模型参数或预算。
- 新题为原创 CC0-1.0 synthetic_demo，单独保存在 challenge_tasks，不改动原五道演示题。
  三种表示齐备，等价性人工审计仍为 pending；均为 dev，不是独立测试集。
- binary_lower_bound 的规约只要求功能正确，不要求二分算法或对数复杂度，线性查找也可以合格。

## 全部结果

表中轮次只计模型生成后的候选检查；成功结果另有最终文件完整重验。
重复编号对应日志中的0、1、2，不是三个不同任务，也不是提供商支持的随机种子。

| 任务 | 重复编号 | 候选验证轨迹 | 最终通过 | 模型调用 |
|---|---:|---|---|---:|
| 下界查找 | 0 | verified | 是 | 1 |
| 下界查找 | 1 | verified | 是 | 1 |
| 下界查找 | 2 | verified | 是 | 1 |
| 整数平方根 | 0 | parse_error → parse_error → parse_error → verified | 是 | 4 |
| 整数平方根 | 1 | verified | 是 | 1 |
| 整数平方根 | 2 | verified | 是 | 1 |
| 序列反转 | 0 | verified | 是 | 1 |
| 序列反转 | 1 | verification_failed × 4 | 否，模型预算耗尽 | 4 |
| 序列反转 | 2 | verification_failed × 4 | 否，模型预算耗尽 | 4 |

描述统计：首次完整通过6/9（66.7%），预算内完整通过7/9（77.8%）。
三次首轮失败中仅一次随后通过；不能把这个1/3当成通用修复能力估计。
按题分组的最终通过：下界3/3、平方根3/3、反转1/3。
没有单独运行 single_shot 或 independent_sampling 对照，因此6/9与7/9的差值
**不是已识别的验证反馈因果收益**；也没有比较三种表示。

| 资源 | 真实观测 |
|---|---:|
| 模型请求 | 18，无供应商失败重试 |
| 在线验证 | 25，含7次最终重验 |
| 输入token | 6375 |
| 输出token | 2064 |
| 合计token | 8439 |
| 各run耗时合计 | 38.051秒，不含准入/测试/启动 |
| 费用估算 | $0.0043893 |
| 验证/解析失败事件 | verification_failed 8次；parse_error 3次 |

费用沿用首轮已核对的高峰、缓存未命中美元估价，忽略缓存与低峰折扣；不是实扣账单。
单独准入6次，矩阵启动时重新准入6次，均未请求模型。另有下述2次调查性验证以及测试套件调用，
均不计入在线25次；模型消耗全部计入18次，没有其他付费追加实验。

## 具体案例1：AI后来修好了，但诊断不够精确

整数平方根重复0，冻结签名是 `returns (r: int)`。模型前三轮均写了 `var r := 0;`，
这会重复声明已有返回变量。原始Dafny日志明确为 `Duplicate local-variable name: r`。
第4轮模型自己改为 `r := 0;`，随后候选和最终文件都通过。

当前框架把这类名称解析/类型错误归入 parse_error，受控诊断仅提供 category=unknown 和
方法体第1行，未将“重复局部变量”细分类别传给模型。不能说模型已经拿到了完整原始错误。
这是值得改进的诊断损失，不是数学证明失败。本轮未临时改解析器，因此九次比较使用同一政策。

- [第一轮模型代码](runs/2026-09-20-deepseek-challenge/0003_integer_sqrt_iterative_repair_natural_0/round_001.dfy)
- [第一轮原始报错](runs/2026-09-20-deepseek-challenge/0003_integer_sqrt_iterative_repair_natural_0/round_001.stdout.txt)
- [第四轮模型代码](runs/2026-09-20-deepseek-challenge/0003_integer_sqrt_iterative_repair_natural_0/round_004.dfy)
- [最终验收](runs/2026-09-20-deepseek-challenge/0003_integer_sqrt_iterative_repair_natural_0/final.verification.json)

## 具体案例2：算法循环没有改错，但模型没有补齐证明

序列反转重复1、2均提交从后往前读取输入、依次追加到输出的循环，已有两条不变式：

```dafny
invariant |r| == i
invariant forall k :: 0 <= k < i ==> r[k] == s[|s| - 1 - k]
```

缺少下标范围 `0 <= i <= |s|`。Dafny报告无法证明输出长度后置条件，以及量词中输入下标可能越界。
只知道循环退出时 `i >= |s|` 不足以证明长度相等，需要循环不变式保留另一方向的界。
受控反馈确实送入后续请求：postcondition/R1，以及候选第5行 bounds；没有给隐藏规约原文。
每次运行的四份方法体哈希均相同：**不是越修越接近，而是没有改变答案。** 两次重复是同一种失败模式。

- [失败代码](runs/2026-09-20-deepseek-challenge/0007_sequence_reverse_iterative_repair_natural_1/round_001.dfy)
- [原始证明错误](runs/2026-09-20-deepseek-challenge/0007_sequence_reverse_iterative_repair_natural_1/round_001.stdout.txt)
- [第二轮实际消息，含当前候选与受控反馈](runs/2026-09-20-deepseek-challenge/0007_sequence_reverse_iterative_repair_natural_1/round_002.messages.json)
- [第四轮仍失败的代码](runs/2026-09-20-deepseek-challenge/0007_sequence_reverse_iterative_repair_natural_1/round_004.dfy)

### 单独的调查性检查，不是模型成功

为了确认不是任务无解或必须改算法，实验结束后我对两份第一轮失败工件仅添加：

```dafny
invariant 0 <= i <= |s|
```

没有修改可执行语句、契约或验证选项，两份均真实验证为 verified。
该检查支持“这两个工件缺少足够的证明注释”的解释，而非存在已证实的算法反例。
**这条证明注释是研究工程师补的，不是该实验模型生成，原始两次Agent结果仍为失败。**

[调查工件1与完整验证证据](runs/2026-09-20-challenge-diagnostic/case_1/evidence.json) ·
[调查工件2与完整验证证据](runs/2026-09-20-challenge-diagnostic/case_2/evidence.json)

## 可信度与局限

- 工件审计检查了9次运行、18份实际提示和25个验证事件；完整矩阵，无缺失记录。
  [审计](runs/2026-09-20-challenge-audit.json) · [JSON汇总](runs/2026-09-20-deepseek-challenge/summary.json)
- 固定资产哈希、禁止绕过、完整最终重验沿用原框架；未公开参考答案、隐藏验收原文或其他表示。
- 这是一组为寻找痛点选定的三道自建题，不能推广到真实仓库或正式基准。失败比例有选择偏差。
- 提供商不发送seed，重复只是独立请求，不保证输出多样性；相同失败不能当作独立机制的证据。
- 15秒验证上限本轮未触发超时；这不能保证更复杂任务都能在此预算证明。
- 支持的语法范围不等于所有Dafny：当前提示未穷举序列构造操作，能力与提示设计仍可能混杂。
- 不能用错误条数估算已满足多少约束，也不能用有限测试替代证明。

## 下一项最值得做的实验

固定这组开发题与预算，比较原始 Agent 和仅改“修复提示/诊断”的版本：
明确要求根据诊断修改当前实现，检测连续相同候选，安全细化重复变量等公开代码诊断。
再加相同调用/验证预算的 independent_sampling，检验修复是否优于重新独立作答。
不要直接把本次发现的缺失不变式硬编码给模型；不要同时换模型、温度、任务和表示。
本次没有实施该改进或追加付费对照，避免把探索后调整的成绩混进原始九次结果。

## 复现

```sh
.venv/bin/python -m generation.representation.cli matrix --tasks generation/representation/challenge_tasks --config generation/representation/configs/deepseek-challenge.json --allow-paid --output /tmp/challenge-new-run
.venv/bin/python scripts/check_representation_artifacts.py /tmp/challenge-new-run
.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_challenge_tasks.py
```

第一条会调用真实付费API，仅在获准预算内执行；输出必须是新目录。
任务新增测试4项全部通过（含三题真实正/负对照验证）；全仓库回归 **361 passed、2 subtests passed，54.16秒**。
完整回归结果记录于
[测试XML](runs/2026-09-20-challenge-full-tests.xml)。

语言依据：[Dafny 4.11 §5.5.3、§8.15](https://dafny.org/v4.11.0/DafnyRef/DafnyRef)。
价格依据：[DeepSeek官方价格](https://api-docs.deepseek.com/quick_start/pricing/)，沿用当天首轮美元估价；
本轮另核对[可访问的官方中文价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/?article_id=article_1779470751466_8)。
