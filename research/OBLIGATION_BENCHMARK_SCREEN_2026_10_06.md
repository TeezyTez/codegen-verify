# 固定规格 Dafny 实现生成：外部数据源筛查

核验日期：2026-10-06。只读作者仓库、许可证和具体源文件；未调用模型、未运行上游代码、未下载整库、未验证任何外部参考实现。旧 `CONDITIONAL_CODEGEN_SPEC_2026_10_06.md` 仅作线索，本文不继承其发表状态或数据可用性判断。

## 结论与下一步

**下一来源优先选 AlgoVeri，先做少量适配审计；目前不能宣布任何一个集合可直接整批导入。** 它的已读样本明确缺少目标实现，适合固定规格实现生成。当前七个样本均有 v1 不支持的共享定义或结构；“有公开规格”不等于“当前 runner 可用”。BAF vericoding-benchmark 是后续扩大规模的候选，但本轮未成功读取其具体题目内容。AxDafny 指定仓库及 raw README 返回 404，暂不进入实验来源清单。

建议按关卡推进，而不是立即跑模型：先完成现有本地任务的离线验收；再从 AlgoVeri 选 2–5 个候选做逐题兼容审计；只有固定来源版本、保持契约语义、参考实现通过、负例被拒绝、运行见证通过、划分冻结后，才计入外部可用题数。这里的 2–5 是建议的审计批量，不是已发现可用题数。若必须保持 v1 原样，先记录拒绝原因，继续筛查，不能静默删掉共享定义或改弱契约。

## 本地边界

依据 `generation/task.py`、`generation/representation/task.py`、`generation/representation/guard.py`：

- `pure_dafny_methods_v1` 固定方法头和契约，只生成指定方法体；representation 层要求 `shared_definitions == ''`，不支持额外函数、谓词、类或辅助声明。
- 方法头的现行检查拒绝 `{}`、注释斜杠等字符，因此源文件里的 `{:trigger ...}` 属性也不能原样放进头部。
- 语句层仅接受受限赋值、初始化、显式分支、带实体的 while、循环不变式/终止量、简单 assert/return。拒绝 ghost、calc、by、for、match、break/continue、证明块、独立方法调用；基础 guard 还拒绝 new、print 和信任绕过。
- 导入还需要参考实现、语义突变负例、运行见证、来源/许可/版本、三种需求视图及逐条映射。外部规格本身不能补齐这些证据。

这比完整 Dafny 语言窄，兼容性判断针对本项目，不代表题目本身有错。

## AlgoVeri：已读七份具体规格

作者 README 声明 77 个经典算法、三种验证语言，Dafny 环境为 4.11；数据目录按算法存放 `dafny_spec.dfy` 和 `dafny_nl.txt` 等六份文件。77 是作者集合规模，本文未逐题清点，不能作为当前可用数。[README](https://github.com/haoyuzhao123/algoveri)、[数据目录说明](https://github.com/haoyuzhao123/algoveri/tree/main/algoveri_data)

下表均来自 `algoveri_data/<目录>/dafny_spec.dfy`，已直接阅读完整文件。`<code>` 中缺的是可执行实现，不能将这些任务描述成仅填循环不变式的证明补全。

| 目录与直接证据 | 已见规格特征 | 对 v1 的判断 |
|---|---|---|
| [linear_search](https://raw.githubusercontent.com/haoyuzhao123/algoveri/main/algoveri_data/linear_search/dafny_spec.dfy) | 序列下界查询；共享 `is_sorted` 谓词；量词 trigger | 原样不兼容；可作为最小适配审计候选 |
| [binary_search](https://raw.githubusercontent.com/haoyuzhao123/algoveri/main/algoveri_data/binary_search/dafny_spec.dfy) | 同样的序列下界契约；共享谓词和 trigger | 原样不兼容；与上项应按同一规格族管理 |
| [trial_division_naive](https://raw.githubusercontent.com/haoyuzhao123/algoveri/main/algoveri_data/trial_division_naive/dafny_spec.dfy) | `divides`、`is_prime` 谓词，目标返回 bool | 原样不兼容；需审计谓词内联及本地见证类型支持 |
| [integer_exponential](https://raw.githubusercontent.com/haoyuzhao123/algoveri/main/algoveri_data/integer_exponential/dafny_spec.dfy) | 递归 `spec_pow`，输出与其相等，另有结果上界 | 原样不兼容；不能简单删除递归规格函数 |
| [gcd](https://raw.githubusercontent.com/haoyuzhao123/algoveri/main/algoveri_data/gcd/dafny_spec.dfy) | ghost 谓词、ghost `spec_gcd`，存在量词和选择表达式 | 原样不兼容；不适合作为首批低成本适配 |
| [bubble_sort](https://raw.githubusercontent.com/haoyuzhao123/algoveri/main/algoveri_data/bubble_sort/dafny_spec.dfy) | 排序与置换由多个 ghost 谓词定义 | 原样不兼容；证明支持与规格展开均需单独审计 |
| [stack_pop](https://raw.githubusercontent.com/haoyuzhao123/algoveri/main/algoveri_data/stack_pop/dafny_spec.dfy) | 泛型类、字段、构造器、读取集、`modifies this`、旧状态 | 超出现行纯方法配置，应排除首批 |

线性搜索与二分搜索的前后置条件除目标方法名外相同。**推论：** 当前只按这些功能契约验收时，不能保证生成的是指定算法，也不能保证二分复杂度；同样不能把两者随机分到 dev/test 后视为独立泛化。需要按规范化契约、算法/源题族分组；算法名称不是复杂度验收器。依据即上表两份原始规格。

许可：仓库声明 Apache-2.0，已读取实际 LICENSE。导入时保存许可与原始归属，记录修改；具体遵循上游许可证，不把许可标记误当成质量认证。[LICENSE](https://raw.githubusercontent.com/haoyuzhao123/algoveri/main/LICENSE)

版本：本轮执行只读 `git -c http.sslBackend=openssl ls-remote ... refs/heads/main` 得到 `8e313b0e8110a781009d4b67ca93b3771b5dc9db`；[提交列表](https://github.com/haoyuzhao123/algoveri/commits/main) 也显示 `8e313b0`。网页源样本从 `main` 缓存读取，尚未重新读取同 SHA 下的字节，因此**未完成数据快照固定**。正式导入须从这个或另一个明确 SHA 重取原始文件，并保存每文件 SHA-256，不能仅把此 SHA 写入当前缓存内容的 manifest。

## BAF vericoding-benchmark：扩大量候选，尚未完成样本审计

README 说明集合共 12,504 项，混合 Dafny/Lean/Verus；规格分为 preamble/spec/code/postamble，包含 `assume false` 或其他占位内容，也刻意保留无法编译的题目。`jsonl/dafny_tasks.jsonl`、`jsonl/dafny_issues.jsonl` 和总 CSV 是筛选入口；CSV 有源题 ID 和质量元数据。这里的总数不是 Dafny 数量，更不是本项目可用数量。[README](https://github.com/Beneficial-AI-Foundation/vericoding-benchmark)、[JSONL 目录](https://github.com/Beneficial-AI-Foundation/vericoding-benchmark/tree/main/jsonl)、[质量 CSV](https://github.com/Beneficial-AI-Foundation/vericoding-benchmark/blob/main/vericoding_benchmark_v1.csv)

`specs/DA0000_specs.dfy`、`DA0001_specs.dfy` 等目录项可见，但本轮 GitHub 文件页和 raw 内容返回 cache miss，API 不可访问；不能根据文件名猜测类型或宣称符合 v1。[规格目录](https://github.com/Beneficial-AI-Foundation/vericoding-benchmark/tree/main/specs)、[待重读 DA0000](https://raw.githubusercontent.com/Beneficial-AI-Foundation/vericoding-benchmark/main/specs/DA0000_specs.dfy)

README 明列 DafnyBench、APPS、HumanEval 等原始来源。**推论：** 必须保留来源/源题 ID，按源题族去重；若与已有 DafnyBench/HumanEval 数据混用，不能只按重命名后的 vericoding ID 划分。还要逐题确认目标 code 区域确实移除了实现，不能把某来源原来的证明补全成绩当作实现生成成绩。[原始来源说明](https://github.com/Beneficial-AI-Foundation/vericoding-benchmark#original-sources)

仓库 LICENSE 为 MIT（2025 Beneficial AI Foundation）；导入聚合数据仍应保留原始来源许可和归属证据。[LICENSE](https://raw.githubusercontent.com/Beneficial-AI-Foundation/vericoding-benchmark/main/LICENSE)

版本未固定：网页提交历史可见 `349ee510deeb6e15e1eb0d98174914e7093252fd`，但页面是较旧缓存，不能称为当前 HEAD；实时 `ls-remote` 因连接重置失败。正式导入须重新确认指定快照。[提交历史](https://github.com/Beneficial-AI-Foundation/vericoding-benchmark/commits/main/)

## AxDafny：本轮无法核验公开资产

[指定仓库](https://github.com/Axiomatic-AI/ax-dafny) 与 [raw README](https://raw.githubusercontent.com/Axiomatic-AI/ax-dafny/main/README.md) 均返回 404。该结果只表示本轮无法访问，不证明项目从未存在或论文声明虚假。未核验样本、许可、版本、拆分，故不报可用题数，不沿用旧笔记对其发布状态的判断，也不作为眼下导入依赖。

## 正式导入最小记录

每题记录：仓库 URL、完整 commit SHA、原文件路径与 SHA-256、原题 ID、许可、目标方法/代码区域、共享依赖、接受/拒绝原因、适配 diff 与等价性审核、参考验证日志、突变/运行见证、族 ID 和固定 split。去重在划分之前完成。题目原始实现和官方/模型解答仅用于离线审核与参考验证，不能混入生成提示。

统计至少分开：发现数、成功获取数、语法兼容数、语义/负例审计通过数、最终独立题族数。本次七份 AlgoVeri 规格是定向抽样，不是随机抽样；七份原样不兼容不能外推整库比例，也不能推断经适配后仍无可用题。
