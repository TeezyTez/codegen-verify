# 真实执行报告：工程闭环，不是方法效果实验

日期：2026-09-08。结论：最小实验框架已真实运行；**依赖调度的新颖性和效果均未得到验证**。
候选由手写脚本回放产生，验证由真实 Dafny 完成。没有付费模型调用，没有上传代码或发布仓库。

## 可追溯的执行记录

使用本机 `.venv/bin/python`、Python 3.12.13、Dafny `4.11.0+fcb2042d6d043a2634f0854338c08feeaaaf4ae2`。
每次运行的 manifest 记录平台、Dafny executable/driver 哈希、捆绑 Z3 候选哈希及框架源码哈希。
未显式指定 solver，实际由 Dafny 默认选择；**不声称已独立确认所选 Z3 版本**。

实际命令（均已执行）：

```sh
.venv/bin/python -m repair.cli validate --output research/runs/2026-09-08-validation-r2
.venv/bin/python -m repair.cli suite --model replay --replicates 3 --output research/runs/2026-09-08-replay-r2
.venv/bin/python scripts/check_repair_artifacts.py research/runs/2026-09-08-replay-r2
.venv/bin/python -m repair.cli estimate --output research/runs/cost-estimate.json
.venv/bin/python -B -m pytest -q -p no:cacheprovider --junitxml=research/runs/tests-final.xml
```

目录已存在，重跑时必须换新的输出目录。检查脚本只审计日志/工件的一致性，不能代替 Dafny 重验。

## 任务准入结果

| task_id | 来源/故障 | 模式 | original | broken | reference |
|---|---|---|---|---|---|
| arithmetic-implementation | 人工四函数；两个运算错误 | implementation | passed | verification_failed | passed |
| clover-array-proof | DafnyBench/Clover；删除不变量、添加人工调用者 | proof | passed | verification_failed | passed |
| clover-double-mutated | DafnyBench/Clover；运算变异、添加人工调用者 | implementation | passed | verification_failed | passed |
| counter-proof | 人工三函数；删除不变量 | proof | passed | verification_failed | passed |

四项全为 dev，两个来源组：Clover、codegen-verify-synthetic。没有真实历史 bug、版本演化数据或独立测试集。
原程序、故障程序和参考修复工件各有哈希；准入单独执行12次完整验证，不混入某条件的在线修复预算。
[准入原始报告](runs/2026-09-08-validation-r2/validation.json)

## 六条件回放结果

independent、linear、generic_agent、dependency、no_dependencies、no_schedule，
每条件4任务×3重复，即每组12次、总72次；**每组都是12/12合法最终通过，仅说明脚本路径可达**。

| 项目 | 实际记录 |
|---|---:|
| 完成 / 计划 / 接受 | 72 / 72 / 72 |
| 真实 Dafny 调用，含初始与最终重验 | 252 |
| 脚本候选/动作响应（不是模型 API） | 126 |
| 被拒绝的边界/绕过候选 | 18 |
| 已通过批次变为失败的回归 | 18 |
| 批次可观察性丢失 | 0 |
| 各次运行耗时合计 | 215.38秒 |
| 付费模型调用 / API费用 | 0 / 0美元 |
| 纳入研究效果统计的运行 | 0 |

同一手写动作序列在六组重放，没有读取模型决策效果；重复回放也不是独立随机样本。
因此不计算方法优势、pass@k 或置信区间。实际 token 不适用；日志中的 accounted_tokens 是预算门禁的预留账本，不是供应商消耗。
耗时包含启动/环境开销，部分执行期间还运行了测试，不能据此比较策略延迟。
[分组汇总](runs/2026-09-08-replay-r2/summary.json) 的 `research=[]`、`paired_research=[]`，且没有缺失计划运行。

最终修改规模按添加+删除行计：counter 1行、clover-array 1行、clover-double 2行、arithmetic 4行；
这是参考型脚本修复的规模，不是模型补丁质量证据。

## 负路径与最终验收

arithmetic 回放首先尝试 `assume false`，在调用验证器前被拒绝；
第二次修复两个故障，却把原本通过的 Stable 改错，检测到回归并回退；第三次修复通过，随后重新读取 final.dfy、检查边界并再次完整验证。
counter 的第一条错误不变量导致验证失败，第二条才成功。错误候选、拒绝理由与回归记录全部保留。
[示例完整轨迹](runs/2026-09-08-replay-r2/000_dependency_0/events.jsonl) · [最终工件](runs/2026-09-08-replay-r2/000_dependency_0/final.dfy)

工件审计检查了72项计划、252条验证事件、单一框架源码版本、最终哈希、边界、最终重验事件及预算；全部一致。
测试实际输出为 **225 passed, 2 subtests passed，29.06秒**，涵盖旧轨道回归与新协议。
新测试包括反绕过、不可变契约、六状态解析、真实四任务验证、预算耗尽、最终重验推翻中间成功、
JSON/供应商错误恢复、回放隔离、来源泄漏、图解析及 live 授权/准入门禁。
超时、未知和供应商故障部分采用明确的测试替身，不伪称所有状态均由真实外部服务触发。
[测试 XML](runs/tests-final.xml)

## 假设目前得到什么证据

**[O] 已支持工程可行性：** 冻结目标、限制区域、真实验证、回归回退、最终验收和可追溯记录可以串成闭环。
这不是论文机制有效性的证据。

**[O] 存在反例的朴素假设：** “被调用函数验证失败，就会沿调用图使调用者失败”。
counter 初始状态明确为 Count failed、Twice passed、Client passed。
固定契约下的模块化验证允许这种情况；调用边不能被当作失败因果边。
[真实批次报告](runs/2026-09-08-replay-r2/003_dependency_0/result.json)

**[H] 未支持也未反驳：** 依赖信息是否改善真实模型的位置/动作选择、成功率、成本；
共享引理是否比普通调用关系更有帮助；机制是否超越最近的 DAISY/P³ 等工作。
现有三个任务只有一个可编辑区域，另一个是简单独立算术错误，几乎不能检验调度痛点。
不据此扩充图算法，也不把所有条件通过解释为它们等效。

## 复查中发现的问题与保留记录

首轮工程测试发现一项汇总测试把两个同身份的测试运行一起汇总，触发重复身份保护；已改为独立目录断言。
随后日志复查发现词法图将声明前空行误作自调用来源；已修正，并新增精确行号、单行调用、真实递归和边类型测试。
旧完整回放保存在 [已替代说明](runs/2026-09-08-replay/SUPERSEDED.md)，不与 r2 合并。
主报告只用修正后的 r2；未删除失败/缺陷发现记录来制造“首次即正确”的印象。

## 尚未完成的研究部分与下一项实验

1. 真实模型效果：没有调用授权，本轮止于离线接线、配置与真实验证；供应商在线行为仍待授权后小测。
2. 公开方法忠实复现：已核对 DafnyBench 官方反馈循环并做受控改编；没复现原参数/整文件生成或论文分数。
   GitHub 浅克隆超时，raw 部分下载成功；DAISY 检索数据、定制环境和在线模型尚未跑通。
3. 数据集：当前只有4个小dev样例、2来源组；没有多来源复杂共享引理任务、时间隔离测试集或充分的近重复审计。
4. 工具范围：词法图不是 SMT 证明依赖；任意辅助引理、calc、多文件、自由 shell 和真实仓库维护未实现。

**下一项最值得做的实验：** 先策划10–20个至少3来源的公开开发任务，
对比“只有调用关联”与“共享证明辅助项”两层，每题至少2个合法修复位置。
完成原始/故障/参考验证和人工定位标签后，再经授权以相同模型、六条件、3重复跑小试。
比较 dependency 对 generic_agent、no_dependencies、no_schedule 的位置选择、合法成功与全部成本；
如果图只增加成本、无图调度已等效或收益仅在人工构造题出现，就收窄/调整机制，不追加复杂模块。
完整决策步骤见 [协议与后续路线](PROTOCOL.md)。

当前72任务运行矩阵的预算上限为432模型调用、720验证调用、3,456,000 token。
价格未知，费用估计留 null；可用上限 token × 输入/输出中较高的每百万价格作粗略最坏估计，
实际应分别核算输入/输出及供应商额外收费。扩大到新任务数时重新运行 estimate，不能沿用本数字。
[预算估算工件](runs/cost-estimate.json)
