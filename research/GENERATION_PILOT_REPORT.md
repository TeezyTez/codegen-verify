# 固定规约代码生成：2026-09-14 工程预实验

本报告属于 `fixed_spec_generation_v1`，与9月8日的修复实验分开。
候选来源分成两类：手写序列回放、真正执行的确定性规则生成器。
**没有调用付费模型，回放不进入模型效果统计。**

## 已实施的改变

- 新 `generation/` 独立入口：加载固定接口/契约，从无实现开始生成，不复用“坏程序先验证失败”的修复准入。
- G00/G01输出完整方法文件，G10/G11输出固定骨架中的全部方法体；无反馈组每次收到相同的新提示。
- 外置契约不可编辑；同时检查结构、全文件正式验证、编译后的运行样例，最后重新读取最终工件并全部重验。
- 模型适配器、预算、失败恢复、去重、回归记录、源码/任务哈希、原始响应和轨迹、分组汇总与审计。
- 12项人工配额业务任务，含参考实现、语义负对照、固定运行样例；另有不读取参考代码的规则生成器。
- 没有恢复规约生成、多Agent、依赖图调度、RL或多验证器架构；旧目录和结果保留。

运行器当前是受限Dafny方法profile，不是任意源文件编辑器、完整OS沙箱或实际PSM转换器。
完整说明：[generation/README.md](../generation/README.md)。

## 任务集实际覆盖

| 设计子族 | 任务 | 检查重点 |
|---|---|---|
| structural | remaining、scale、snapshot、clamp | 余量计算、整数单位换算、字段映射、上限 |
| guarded_update | reserve、release、partial、transfer | 守卫、拒绝不改状态、部分分配、转移守恒 |
| composition | refill、reserve_twice、release_twice、reserve_release | 循环/等价闭式实现、顺序状态更新、多操作效果 |

12项全部是dev，**一个人工来源项目、三个设计子族**。不是三个独立项目，不是外部PSM基准，
没有独立测试集。任务及期望值由本次实现者编写，独立人工语义复核尚未完成。
源JSON本身已完整表达规则；此事实使它们适合协议诊断，却不足以证明LLM的必要性。

每项准入独立检查：参考实现正式验证通过且运行通过；语义mutant正式验证失败且运行明确expect失败。
全部12项准入通过，12/12语义负对照同时被两种检查发现。
负对照不是编译错误或超时，包括漏容量守卫、错误字段映射、不守恒、第二次操作读取旧状态等。
[准入原始报告](runs/2026-09-14-generation-template/admission/validation.json)

## 实际执行命令与环境

```sh
.venv/bin/python -m generation.cli suite --model replay --replicates 3 --output research/runs/2026-09-14-generation-replay
.venv/bin/python -m generation.cli template --output research/runs/2026-09-14-generation-template
.venv/bin/python -m generation.cli audit --output research/runs/2026-09-14-generation-template
.venv/bin/python -m generation.cli audit --output research/runs/2026-09-14-generation-replay
.venv/bin/python scripts/check_generation_factorial.py research/runs/2026-09-14-generation-replay --output research/runs/2026-09-14-generation-factorial-audit.json
.venv/bin/python -m generation.cli estimate --output research/runs/2026-09-14-generation-estimate.json
.venv/bin/python -B -m pytest -q -p no:cacheprovider --junitxml=research/runs/2026-09-14-generation-tests-final.xml
```

Python 3.12.13，Dafny 4.11.0（完整版本、驱动与solver候选哈希在每个manifest中），本机macOS。
没有切换工具链或自研证明内核。Dafny正式证明后，运行子步骤使用Python编译后端与可信Main/expect。
运行子步骤的 `--no-verify` 仅避免重复证明，不提供形式证明证据：联合成功必须另外有完整verify通过。
两次独立suite各自重新准入，准备阶段各有24次verify和24次编译/运行，分开记录，不隐藏为免费工作。

输出目录已存在，复现需用新目录。部分suite与测试同时执行，耗时仅是本次环境观测，不用于方法延迟优劣论证。

## 真实规则基线：12/12

`Template`根据公开rule ID选择冻结的确定性代码生成规则，不读取reference、mutants或tests。
12项均通过最终完整验收，在线生成/验收共24次verify和24次编译/运行，合计31.70秒，模型调用0。
[规则基线汇总](runs/2026-09-14-generation-template/summary.json) · [工件审计](runs/2026-09-14-generation-template/audit.json)

这是真实生成结果，但只适用于手工支持的12种规则；不是通用规约综合器，规则维护的人工时间未量化，记null而不是0。
其中Refill的参考实现使用循环，规则生成器选择等价的闭式表达式；ReserveRelease只需返回原状态，
因为当前规约约束可观察的最终值，不要求特定内部调用轨迹。这些是合法实现，不按参考代码相似度评分。

**本地结论：这批任务已经可以由传统规则完整解决，不能据此主张使用LLM更有价值。**
若要研究LLM的额外能力，应找实际现有生成器尚未覆盖的场景，而不是删除本来可用的规则。

## 四组回放：144/144工程路径完成

实际完成12任务×4条件×3重复=144次运行；每次回放固定尝试“非法假设→语义错误→参考正确实现”。
四组均为36/36最终通过，累计144次非法修改被拒绝，432次真实verify、288次真实编译/运行，
各run耗时合计468.41秒（不含单独记录的准入）。观测回归数为0；这组固定序列不是回归机制有效性的证据。
账本中的432次model_calls是回放适配器调用，不是远程模型调用；没有真实token消费统计。
它只说明对应工程路径可以完成，不测试模型理解，不是独立随机采样，也不能估计方法优势或pass@k。

逐run的最终状态以 [回放汇总](runs/2026-09-14-generation-replay/summary.json) 为准；
全部prompt、非法响应、错误候选、验证报告和最终文件保存在同目录。
汇总把回放放入 `scripted_diagnostics`，实际 `live_research` 与 `paired_live` 均为空。
工件审计通过144个计划run与432个联合验收事件；四格协议审计通过12项任务的相同输入、
432份提示与216份无反馈新提示检查，预算版本只有1个。
这是输入/权限隔离检查，不是模型效果或统计显著性的证据。
[工件审计](runs/2026-09-14-generation-replay/audit.json) · [四格协议审计](runs/2026-09-14-generation-factorial-audit.json)

## 测试与安全负路径

最终完整测试输出：**270 passed, 2 subtests passed，32.33秒**，包括保留的225项旧测试和45项新增生成测试。
[测试XML](runs/2026-09-14-generation-tests-final.xml)

覆盖：四条件输出/反馈隔离、拒绝改弱契约、禁止假设和额外声明、允许无害空白变化、
token/调用预算、供应商错误与坏JSON恢复、最终重验推翻中间成功、缺失批次、
证明通过但运行失败、未支持模板的显式结果、来源/近重复划分、最终文件篡改、计划缺失与身份不一致。
还有实际Dafny生成与运行集成测试、在线调用授权前置检查、准入失败不创建客户端、运行超时进程组清理和密钥环境隔离。
工具异常/超时/供应商缺失用量的一部分使用测试替身，不能说已对所有真实服务故障做过实验。

## 相对设计方案的实施差异

1. **数据来源未达到预期**：12题只有一个人工来源，不足以支持跨来源泛化、显著性或工业PSM声明。
2. **还没有真实模型效果实验**：之前授权边界要求明确允许付费调用；本次没有自行消费已有密钥。
   本机未找到可直接使用的ollama/llama-cli命令，但这不代表已穷尽所有可用本地模型环境。
3. **骨架很小**：只固定头部和拼接，不提供算法骨架；无骨架组也接受相同外部契约检查。
4. **无反馈更严格**：G00/G10不返回编译或语义错误，也不传历史和剩余时间，不应描述成“仅去掉语义错误”。
5. **没有PSM转换或跨语言等价性结论**：只证明Dafny核心、另跑有限编译样例；无数据库、并发或实际平台映射。
6. **没有公开方法忠实复现**：G01是受控通用工具循环，不等同AxDafny/P³或某商业Agent产品。
7. **全量恢复尚有限**：单run可从供应商/格式错误恢复，但中断suite不支持在原预算账本上继续；缺失作业会被审计发现，不能隐藏。

## 下一步判断与资源

工程门槛已具备：输入固定、正确/错误参考能区分、完整生成与双重验收可运行、日志可审计。
研究门槛未达到：尚无模型决策证据，任务完全可模板化，缺少外部PSM来源和独立语义审查。

最值得下一步做的是取得一份可脱敏PSM或公开等价模型，明确结构与行为规则、现有模板覆盖和未覆盖行为，
策划无法单靠字段抄写完成且仍可客观验收的任务。模板已覆盖部分保留为必要控制组。
然后经明确模型/费用授权，小规模执行真实G00–G11对照；若G11不优于强基线，报告负结果而不追加复杂模块。

当前144模型run的上限：864次模型调用、1440次联合验收、6,912,000 token；
每次联合验收最多1次verify和1次编译/运行，准入与模板开销另计。
模型价格未给出，美元费用估计为null；实际已发生API费用为0。
[成本上限工件](runs/2026-09-14-generation-estimate.json)
