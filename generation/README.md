# 固定规约代码生成：可运行的最小实验

协议：`fixed_spec_generation_v1`。本目录与旧 `repair/` 分开，不能混算结果。
输入为固定方法接口/契约与行为说明，初始不提供实现。目标是生成代码及必要不变量/断言，
最终同时通过结构检查、Dafny全文件证明与编译后的有限运行样例。

## 快速运行

在仓库根目录运行，使用现有 Python 3.12 环境和 Dafny 4.11：

```sh
# 查看任务准入与反例检出：不调用模型
.venv/bin/python -m generation.cli validate --output /tmp/gen-admission

# 4条件×12任务×3重复：手写候选、真实验证，非模型效果实验
.venv/bin/python -m generation.cli suite --model replay --output /tmp/gen-replay

# 真正的确定性规则生成器，不读取参考实现
.venv/bin/python -m generation.cli template --output /tmp/gen-template

# 分析、核对轨迹与工件、估算资源上限
.venv/bin/python -m generation.cli analyze --output /tmp/gen-replay
.venv/bin/python -m generation.cli audit --output /tmp/gen-replay
.venv/bin/python scripts/check_generation_factorial.py /tmp/gen-replay
.venv/bin/python -m generation.cli estimate --output /tmp/gen-estimate.json
.venv/bin/python -m pytest tests/test_generation.py -q
```

所有生成输出目录必须不存在。`analyze`/`audit`读取已有目录；`estimate`的output是文件路径。
用 `--task-id reserve_twice --replicates 1` 缩小smoke范围；用 `--dafny /path/to/dafny` 指定后端。
没有Dafny时真实集成测试明确skip，不能当作通过；CLI准入失败不会启动生成器。

真实模型需要配置现有 `CODE_PROVIDER`、`CODE_MODEL` 和密钥，并审查输入可外发；
`suite --model live` 必须同时有明确的 `--allow-paid` 授权。默认replay不读取API密钥给模型，也不发送请求。
价格在 `configs/pilot.json` 填入，未知保持null；禁止把未知用量当成免费。
当前live适配器已离线测试，不表示已经验证供应商在线兼容性。

## 数据的实际边界

`tasks/` 有12个本地人工任务，**只有一个来源项目**，分为结构映射、带守卫更新、操作组合三个设计子族。
不是三个独立来源，也不是公开/工业PSM或冻结测试集。任务全部dev；独立人工语义审查仍待完成。
每个task.json含：

- 固定接口、requires/ensures、公开说明与规则标识；
- 来源/设计子族/评审状态，不因分组而伪造独立性；
- 一个满足规约的参考实现；
- 一个语义错误实现、具体违反规则的解释；
- 独立显式列出的有限输入/期望输出样例，不由候选或模板输出充当期望值。

模型只得到 `Task.public()` 白名单：id/description/methods/rule/profile。
reference、mutants、运行样例都不在生成提示中。回放器有意读取它们，仅用于工程诊断。
这里的有限样例是固定开发验收，不声称是未泄漏的外部测试集；人工编写者相同仍是oracle偏差威胁。

准入要求参考正式验证与运行都通过，语义mutant在正式验证中失败且运行确实触发expect失败。
因此不会把超时/编译错误当成“发现了语义缺陷”。空实现不是注入bug，不要求其先verification_failed。

## 两个实验因素

| condition | 生成内容 | 后续提示 |
|---|---|---|
| G00 | 完整方法文件 | 固定新提示，不带历史/候选/反馈 |
| G01 | 完整方法文件 | 当前候选、完整验收反馈、近期工具轨迹 |
| G10 | 固定骨架中的全部方法体 | 固定新提示，不带历史/候选/反馈 |
| G11 | 固定骨架中的全部方法体 | 当前候选、完整验收反馈、近期工具轨迹 |
| T | 规则注册表生成代码 | 无模型 |

所有条件的目标契约相同且不可编辑；G00/G01也会拒绝改弱契约，不能通过改题获取优势。
完整文件模式允许空白格式变化，但要求同一头部token与方法顺序；这是受限协议，不是通用AST工具。
四组都能read/generate/verify/stop；无反馈条件不返回检查结果、不通过剩余耗时泄漏失败状态，
失败后从相同提示重新生成。生成器看不到先前尝试，验收器可在首次成功时停止，所有验收仍计费。
本版无反馈组也不返回编译错误，比“仅屏蔽语义错误”更严格，必须在论文里如实说明。

骨架只含接口/契约，不提供算法、循环骨架、参考不变量或隐藏答案。
这种最小骨架可能只节省样板和格式错误；不能提前宣称它改善复杂行为推理。

## 可信边界与最终验收

1. `task.py`白名单检查完整声明、方法体边界；禁止修改契约、额外声明、假设、公理、属性、导入、I/O与分配等。
2. `repair.verifier.Dafny`对实际候选全文件验证；保留passed/verification_failed/timeout/unknown/compile_error/tool_error。
3. 所有预期method correctness批次必须存在。缺失报告不能通过。
4. `oracle.py`用Dafny现成Python后端编译同一源码，加可信Main调用公开方法并检查固定运行样例。
5. 持久化final.dfy，重新读取，再执行1–4；只接受预算内联合通过的最终工件。

运行检查使用 `dafny run --no-verify --target py`，因为正式证明已经由独立verify完成。
此处“did not attempt verification”只描述运行子步骤，**不能作为形式成功的证据**。
负对照准入允许在明确verification_failed后执行样例以独立确认语义错误，这也不会被接受。
有限运行不证明所有输入；证明只相对于固定规约与Dafny/solver/compiler可信链。

生成代码在临时目录执行，传递最小环境变量，不带模型密钥；POSIX运行超时杀死进程组。
目前依赖严格语言profile，不是面向任意不可信程序的完整OS沙箱，也没有内存强配额。
不能直接放宽到任意Java/Python、外部库或网络代码；新增能力必须重做安全与语义边界审计。

## 预算、恢复与可追溯性

每run默认：6次模型调用、10次联合验收、48k token、单次输出2048、180秒。
联合验收内的Dafny verify和编译/运行子调用分别记数；最后一次验收预留给最终工件。
准入在每个suite开始时单独运行，不充入某个模型条件的在线预算；其日志与成本仍保留。
模板没有模型调用，其代码生成和验收时间计入；规则开发时间未知，记null而不是0。

供应商异常消耗一次调用与保守token预留，后续可恢复；坏JSON、边界违规、重复候选不会被接受。
反馈组记录先前已通过批次的回归并回退；无反馈组不假装在做有状态修复。
调用前UTF-8字节预留不是供应商tokenizer形式上界；超额记失败，不承诺供应商计费绝不越界。
SDK禁用隐藏重试，模型名/模式/价格/源码哈希等保存在manifest中，不记录密钥。

每run包含manifest、初始输入、完整prompt/response、候选、events.jsonl、final.dfy与result.json。
suite另有config、jobs、admission、summary、audit。汇总明确分开live_research、scripted_diagnostics和deterministic_baseline。
缺失run保留并阻止audit通过；重复身份、混合框架版本、最终哈希不匹配都拒绝。
目前不支持断点续跑同一预算账本；中断后先保留/分析缺失作业，再新建独立输出运行，不能静默丢失失败。

## 当前真正可检验的结论

这批任务的规则注册表覆盖全部12种操作。它基于公开规则独立编写，不读取reference，
但本身是针对该诊断profile的人工工程，不是已支持任意规约的综合器。
例如Refill可用闭式表达式替代参考循环、ReserveRelease可直接返回原状态；规约允许时这些都是合法实现，不能当作弊。
没有理由在这批完全可生成任务上宣称LLM必要。后续应取得真实模型输入和传统生成器的覆盖边界，
而不是为了制造优势删除可用规则。

研究方案：[FIXED_SPEC_GENERATION.md](../research/FIXED_SPEC_GENERATION.md)。
本次真实运行报告：[GENERATION_PILOT_REPORT.md](../research/GENERATION_PILOT_REPORT.md)。
