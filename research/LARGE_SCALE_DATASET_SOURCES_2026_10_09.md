# 大规模固定规格代码生成：可获取数据源核查

核查日期：2026-10-09。本文读取作者仓库、论文及本次主代理已下载并按 Git blob 校验的固定版本文件；没有执行上游代码、模型实验或参考实现验证。论文的“已验证”、仓库存在解答、当前环境重新验证通过，是三个不同状态。旧筛查笔记仅作线索。

## 结论

最快的科学验证路线是同时准备两个池：**DafnyBench 的固定版本参考实现，派生出明确命名的“删除目标实现体”任务；BAF 中非 DafnyBench 来源且有发布解答的原生代码生成任务。** 前者可快速复验参考，但必须重新检查规格强度；后者有更大直接生成规模，但不能信任文件名或历史 success 标签。AlgoVeri 留作外部算法集；Clover 留作机制/负例集。AxDafny 的 LCB-Pro-Dafny 本轮仍不能获取，不能成为启动依赖。

本轮数目均为资产/行数，**不是已准入任务数或独立问题族数**：DafnyBench JSON 有 782 程序；AlgoVeri 有 77 个 Dafny 规格；BAF 有 3,029 个 Dafny 行及 1,754 个已发布 Dafny 解答文件，其中 330 个解答来自其 DafnyBench 子集，非该子集为 1,424 个候选。没有证据把这些数直接相加作为独立大样本。

## 1. DafnyBench：最容易取得成对参考，原任务是注解补全

固定提交 `0cd28feed9cd0179b07fdb9d002f8c39063658e4`。来源版本记录与逐文件哈希在本次 `research/data/large-scale-20261009/dafnybench-snapshot.json`；以下均为该提交路径：

- [直接 JSON 下载](https://raw.githubusercontent.com/sun-wendy/DafnyBench/0cd28feed9cd0179b07fdb9d002f8c39063658e4/DafnyBench/test.json)：782 条；字段 `test_ID`, `test_file`, `ground_truth`, `hints_removed`。
- [参考目录](https://github.com/sun-wendy/DafnyBench/tree/0cd28feed9cd0179b07fdb9d002f8c39063658e4/DafnyBench/dataset/ground_truth)：每个 `.dfy` 是完整文件参考；相邻 `hints_removed` 为注解去除版。
- [仓库 LICENSE](https://raw.githubusercontent.com/sun-wendy/DafnyBench/0cd28feed9cd0179b07fdb9d002f8c39063658e4/LICENSE)：Apache-2.0；聚合来源的原始归属仍须保留，不能以此推断每个 GitHub 原作者的独立许可已逐题核实。

作者正式版 §3 描述 556 个 GitHub 文件、62 个 Clover 文件、164 个 dafny-synthesis/MBPP 文件，并称以 Dafny 4.3.0 验证源文件。原评测给出实现、删除 assert/invariant，再恢复证明。已有 proof-hint 成绩不能作为整段实现生成基线；同一文件多个目标也不是独立源题。[作者论文](https://namin.seas.harvard.edu/pubs/dafnybench.pdf)

**实际读取暴露的准入问题：** `test_ID=000` 的 BinarySearch 只约束“返回范围内则元素相等”和“返回 -1 则不存在”；缺少 `index == -1 || 0 <= index < a.Length`。逻辑上返回 `-2` 能使两个前件均为假。这是对原契约的静态推论，本轮未运行该突变。`001` DPGD 无 `ensures`，且出现 assume 与非确定赋值；`002` gaussian 也无 `ensures`。因此，即使参考通过，不能直接称所有 782 条都是可信功能生成任务。[精确原始资产](https://raw.githubusercontent.com/sun-wendy/DafnyBench/0cd28feed9cd0179b07fdb9d002f8c39063658e4/DafnyBench/test.json)

建议保留完整只读共享定义，按 AST 指定可编辑实现体及允许新增证明区域。参考、辅助可执行函数、其他方法体是否向生成器公开必须固定，否则会泄漏答案。若需修正弱契约，建立单独的修订版本并公开 diff，不把它混称原始固定规格。准入至少区分参考验证、反平凡解检查、规格语义检查以及 body-removal 后的任务可定义性。

## 2. BAF vericoding-benchmark：最大直接代码生成候选池，参考需要重新验收

固定提交 `387cd69996792d452ead7b0460f36ee4c5cdd148`。作者仓库发布可编译占位规格，也刻意保留无法编译的翻译规格；`vericoded` 是 AI 解答，`handcoded` 是预留目录。原始来源包含 DafnyBench、APPS、HumanEval、Verina、NumPy 和 VerifiedCogen。[README](https://github.com/Beneficial-AI-Foundation/vericoding-benchmark/tree/387cd69996792d452ead7b0460f36ee4c5cdd148)

可获取资产：

- [Dafny 任务 JSONL](https://raw.githubusercontent.com/Beneficial-AI-Foundation/vericoding-benchmark/387cd69996792d452ead7b0460f36ee4c5cdd148/jsonl/dafny_tasks.jsonl)，树记录 4,078,298 bytes。
- [Dafny 问题 JSONL](https://raw.githubusercontent.com/Beneficial-AI-Foundation/vericoding-benchmark/387cd69996792d452ead7b0460f36ee4c5cdd148/jsonl/dafny_issues.jsonl)，树记录 2,200,058 bytes。本次固定快照实读 `tasks` 2,334 行、`issues` 695 行，ID 交集为零，总计 3,029。两者统一 schema：CSV 字段另加 `vc-description`, `vc-preamble`, `vc-helpers`, `vc-spec`, `vc-code`, `vc-postamble`。QA 计数字段为 int、`qa-score` 为 float，其余相关字段为 string。1,754 个发布解答 ID 全在 tasks 文件内；issue 集没有对应发布解答。
- [总质量/来源 CSV](https://raw.githubusercontent.com/Beneficial-AI-Foundation/vericoding-benchmark/387cd69996792d452ead7b0460f36ee4c5cdd148/vericoding_benchmark_v1.csv)，本轮通过作者 Git blob API 实读：字段包括 `id`, `language`, `source`, `source-id`, `source-notes`, `qa-issue`, `qa-issue-type`, `qa-functions-with-default-values`, `qa-methods-with-bodies`, `qa-specs-with-default-values`, `qa-execs-with-bodies`, `qa-execs-with-ghost-types`, `qa-definitions-with-sorry`, `qa-near-duplicate-group`, `qa-score`。
- [完整树 API](https://api.github.com/repos/Beneficial-AI-Foundation/vericoding-benchmark/git/trees/387cd69996792d452ead7b0460f36ee4c5cdd148?recursive=1) 列出 `specs/<ID>_specs.dfy` 和 `vericoded/<ID>_vericoded.dfy`；本轮 `handcoded` 只有 `.gitignore`，不能声称存在人工参考集。
- [LICENSE](https://raw.githubusercontent.com/Beneficial-AI-Foundation/vericoding-benchmark/387cd69996792d452ead7b0460f36ee4c5cdd148/LICENSE)：MIT，2025 Beneficial AI Foundation。原题源许可/归属需逐来源保留；本文没有完成八类源题的独立许可清单。

CSV 与固定版本树联合统计：

| 前缀 | source | Dafny 规格行 | 发布 `.dfy` 解答文件 |
|---|---|---:|---:|
| DA | apps | 883 | 563 |
| DB | bignum | 62 | 29 |
| DD | dafnybench | 929 | 330 |
| DH | humaneval | 164 | 151 |
| DJ | verified_cogen | 172 | 165 |
| DS | numpy_simple | 59 | 44 |
| DT | numpy_triple | 603 | 335 |
| DV | verina | 157 | 137 |
| 总计 | — | 3,029 | 1,754 |

DD 的 929 行高于原始 782 文件，不能解释为 929 新题。其 `source-id` 含源文件和方法名，例如 `630-dafny_tmp_tmpz2kokaiq_Solution_BinarySearch`。这给出了与 DafnyBench 的直接连接，应按原始文件/源题归并，而不是按 BAF ID 随机划分。[CSV](https://raw.githubusercontent.com/Beneficial-AI-Foundation/vericoding-benchmark/387cd69996792d452ead7b0460f36ee4c5cdd148/vericoding_benchmark_v1.csv)

**已实读的成对样例 DA0000：** [规格](https://raw.githubusercontent.com/Beneficial-AI-Foundation/vericoding-benchmark/387cd69996792d452ead7b0460f36ee4c5cdd148/specs/DA0000_specs.dfy) 分 `vc-preamble/vc-helpers/vc-spec/vc-code` 区域，目标 solve 的实现是 `assume {:axiom} false` 占位；要求在 1..x 内找最大数位和并取并列最大值。[解答](https://raw.githubusercontent.com/Beneficial-AI-Foundation/vericoding-benchmark/387cd69996792d452ead7b0460f36ee4c5cdd148/vericoded/DA0000_vericoded.dfy) 有循环实现和辅助引理，确为实现+证明生成，而非仅补注解。此处只确认存在真实代码，没有确认当前 Dafny 通过或最坏情况运行效率。

作者人工检查 120 个成功输出（各语言/来源单元抽五个），Dafny 40 个中仅 33 个未发现规格问题，另含弱规格、泄漏和误翻译；实现检查也发现绕过和缺陷。明确列出 DS0024 的 assume axiom、DH0123 的 assume false 和 DT0202 的常量 stub。不能把小样本比例外推成全库真实质量率，也不能把未标 issue 当作人工审计通过。[作者检查报告](https://github.com/Beneficial-AI-Foundation/vericoding-benchmark/blob/main/inspection/ANALYSIS.md)

推荐先筛 `DA/DH/DB`，再扩 `DJ/DV`；`DS/DT` 的翻译语义与同一 NumPy 操作的重复变体要额外审计；DD 不作独立外部验证。tasks 的 2,108 行评分为 1.0；164 行带非空 near-duplicate-group，覆盖 38 个组。`qa-score=1` 仅作优先队列信号，不作准入证明；QA 中存在 `-1`，其上游缺省/不适用语义尚未逐字段核实，不能当零缺陷。空重复组也不能证明无语义重复。所有 AI 参考均需冻结原契约、检查 bypass、重新验证；主结果不应只报“上游曾经被某模型解出的集合”而省略选择偏差。

## 3. AlgoVeri：最合适的原生外部算法集，缺全量参考资产

固定提交 `8e313b0e8110a781009d4b67ca93b3771b5dc9db`；77 算法目录，每个提供 Dafny/Verus/Lean 的规格和自然语言描述。环境为 Dafny 4.11，Apache-2.0。[README](https://raw.githubusercontent.com/haoyuzhao123/algoveri/8e313b0e8110a781009d4b67ca93b3771b5dc9db/README.md)、[LICENSE](https://raw.githubusercontent.com/haoyuzhao123/algoveri/8e313b0e8110a781009d4b67ca93b3771b5dc9db/LICENSE)

每题路径为 `algoveri_data/<algorithm>/dafny_spec.dfy` 与 `dafny_nl.txt`。例如 [binary_search 规格](https://raw.githubusercontent.com/haoyuzhao123/algoveri/8e313b0e8110a781009d4b67ca93b3771b5dc9db/algoveri_data/binary_search/dafny_spec.dfy) 和 [自然语言](https://raw.githubusercontent.com/haoyuzhao123/algoveri/8e313b0e8110a781009d4b67ca93b3771b5dc9db/algoveri_data/binary_search/dafny_nl.txt)。`preamble/helpers/proofs/spec/code` 标签明确分区，code 是空目标实现；不是规格生成任务。本轮固定版本树和下载目录未发现逐题完整参考实现或全量已验证解答发布资产，不能把模型实验报告当参考存在证据。[固定版本树](https://api.github.com/repos/haoyuzhao123/algoveri/git/trees/8e313b0e8110a781009d4b67ca93b3771b5dc9db?recursive=1)

作者强调人工写、对齐、复查规格，并在验证通过后另用语义评审检查是否实现指定算法。[论文 §2–3](https://arxiv.org/html/2602.09464v1)。本轮实读 linear_search 与 binary_search，二者 lower-bound 契约除方法名相同；固定功能契约不会强制二分算法或复杂度。所有排序方法也不能先验当互相独立。三种语言不是 231 个独立算法样本。

建议作为冻结后的外部评测集；当前 runner 不支持的共享谓词、ghost、类、引理不能删除来凑兼容数。缺乏参考的题可单独报告为开放挑战，不把未解题自动解释为方法失败或规格可满足性已证。若补参考，应在实验前用独立流程完成并冻结，不根据被测方法表现筛题。

## 4. Clover：小而实用的机制和负例套件，与 DafnyBench 重叠

GitHub API 核实提交 `02144bec1bbf8d38951ef2df6f0c2870965a214e`，提交日期 2025-05-12。MIT（Copyright 2023 LiviaSun）。[提交](https://github.com/ChuyueSun/Clover/commit/02144bec1bbf8d38951ef2df6f0c2870965a214e)、[LICENSE](https://raw.githubusercontent.com/ChuyueSun/Clover/02144bec1bbf8d38951ef2df6f0c2870965a214e/LICENSE)

实查固定树：`dataset/CloverBench/textbook_algo` 有 62 个题目录、每题 `_strong.dfy` 和 `_spec.txt`（另有 README/.DS_Store）；`textbook_algo_anno` 有 62 个契约等价检查模板；`textbook_algo_unit_tests` 有 62 个题文件加 README；`adversarial_incorrect` 有 1,033 个资产文件，**不是 1,033 个独立生成题**。[树 API](https://api.github.com/repos/ChuyueSun/Clover/git/trees/02144bec1bbf8d38951ef2df6f0c2870965a214e?recursive=1)

可直接读取 [abs 完整参考](https://raw.githubusercontent.com/ChuyueSun/Clover/02144bec1bbf8d38951ef2df6f0c2870965a214e/dataset/CloverBench/textbook_algo/abs/abs_strong.dfy)、[abs 描述](https://raw.githubusercontent.com/ChuyueSun/Clover/02144bec1bbf8d38951ef2df6f0c2870965a214e/dataset/CloverBench/textbook_algo/abs/abs_spec.txt)、[等价模板](https://raw.githubusercontent.com/ChuyueSun/Clover/02144bec1bbf8d38951ef2df6f0c2870965a214e/dataset/CloverBench/textbook_algo_anno/abs/abs_anno_check_template.dfy)、[运行样例](https://raw.githubusercontent.com/ChuyueSun/Clover/02144bec1bbf8d38951ef2df6f0c2870965a214e/dataset/CloverBench/textbook_algo_unit_tests/abs/abs_tests.dfy)。运行文件打印五组结果，期望值写在注释中，不是现成逐值断言 oracle；须由 harness 比较。

原 Clover 是代码、描述、规格间一致性检验，包含生成规格的研究方向；使用它做固定规格整段代码生成同样是派生切片。用其干净参考、契约等价模板、对抗错误构造机制检验很合适，但不能当与 DafnyBench 独立的外部泛化集。[作者仓库说明](https://github.com/ChuyueSun/Clover)

## 5. AxDafny / LCB-Pro-Dafny：论文可核实，下载不可用

论文 v1 声称公开 250 个题（100 easy/100 medium/50 hard），给自然语言、固定 Dafny 规格和实现目标；规格经模型辅助、人工审查与反平凡解检查，Dafny 4.11。论文明确指出验证通过与原竞赛时间/内存限制是不同指标。[论文及 Software and Data](https://arxiv.org/html/2606.32007v1)

本轮网页和实时 GitHub API 对作者给出的 [Axiomatic-AI/ax-dafny](https://github.com/Axiomatic-AI/ax-dafny) 都返回 404。因此未核实可下载文件、commit、数据许可、schema、完整参考解答与拆分。论文“发布”声明不能代替可获取资产；论文许可也不自动是数据许可。保留候选，眼下不报可用数。

## 建议划分与最快验证顺序

以下是研究设计建议，不是上游官方 split。两个主池的执行先后应由当前 Dafny 版本的离线准入产率决定；若 DafnyBench 旧语法/工具错误多，优先 BAF-native，不必为保留原始 782 数量而投入大量迁移。工具错误与真实验证失败分开，迁移版另外固定。

1. **主评测第一批：BAF-native fixed-spec synthesis。** 主代理的本轮预检支持先走原生生成题。从 1,424 个非 DD 发布解答候选优先准入；另有 467 个非 DD tasks 没有发布参考，独立补可满足性证据后才纳入。对 `source-id`、`qa-near-duplicate-group` 和规范化 AST/契约一起聚类，跨来源审查重叠。单独报告源题分层结果，避免 NumPy 变体数压倒其它领域。
2. **补充派生集：DafnyBench-derived body synthesis。** 全量 782 只作待筛池。复验完整参考、排除信任绕过/无有效功能契约/平凡解，保留每题具体排除原因。以原始仓库+原始文件+规范化契约/算法族的连通分量划分；不要拆同文件目标、Clover/MBPP 衍生或重命名版本。经过筛选的题数和独立族数才是实际 N；不并入原生生成主分数。
3. **外部评测：AlgoVeri 77 题池。** 在开发结束前冻结可执行的兼容/审计策略，不使用其失败样本继续调策略后又称外部测试。无参考或复杂共享结构的题单列；算法身份/复杂度若需测量，增加独立指标。
4. **机制集：Clover 与受控变体。** 同一根题产生的实现 bug、缺/错不变量、冗余证明、义务次序等变体全部绑在同一 split。变体可增加受控观测数，不能增加独立根题 N；统计按根题配对/聚类。先在这里证明策略确实使用状态并选择不同动作，再以主集验证外推。

不要为扩大样本把模型自动生成的规格直接称可信规格。若公共准入池仍不足，可生成题但应先独立建立冻结规格和参考、做非空前置见证及反平凡解/突变检查；生成模型与被测方法分离，且报告生成来源和选择规则。重复 prompt、随机种子、近义改写和参数替换不是新独立问题。

**仍未知：** 最终兼容且可信的 N、所有参考的当前 Dafny 验证结果、每个聚合源的逐题许可链、跨来源语义重复的准确数量、AlgoVeri 全量可满足性证据、AxDafny 资产何时可访问。上述未知不阻止现在开展全量离线普查，但阻止提前宣称已经拥有数千个独立可信生成任务。
