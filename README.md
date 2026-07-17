# Codegen Verify

规约引导的大模型代码生成与 Dafny 验证修复实验项目。系统把 HumanEval
题目规范化为结构化任务，依次生成 Dafny 规约和实现，运行解析/验证，按错误类型
修复，最后才在官方 HumanEval 留出测试上做一次端到端判定。

代码生成前还有一个 fail-closed 的 Independent Spec Critic：它在全新的模型上下文中
只审查自然语言、公开示例与候选规约的语义一致性，并输出结构化问题和反例。默认
暂时与 Spec Agent 同用 `deepseek-chat`，但通过 `CRITIC_PROVIDER` / `CRITIC_MODEL`
独立配置，便于后续做跨模型实验。Critic 拒绝会触发有限次规约修复；拒绝、弃权或
调用失败在预算耗尽后都会停止在规约阶段，不会静默进入代码生成。
默认采用一次独立语义审计，再由 spec-blind probe generator、确定性 Reference 执行
和按需冲突确认提供交叉证据；可用 `CRITIC_REVIEW_PASSES` 做多审查者消融。
Probe generator 只接收 Python 签名、函数说明和公开示例，不接收 Dafny 规约或生成
指令；公开 doctest 由 harness 确定性提取，LLM probe 不能冒充公开样例。结构标签由
harness 按 TaskIR、参数角色和任务语义重算：覆盖最小/单例、末位、阈值端点、重数、
排序、tie-breaking 和表示转换，模型自报标签不参与门控。未经题目支持的空输入 probe
会被局部删除。所有公开样例和未被独立重算推翻的 spec-blind probe 都是批准前必跑
证据；超过单批上限时分批执行而不是截断。probe 失败时，确认模型看不到原期望值，
必须独立重算；只有公开示例或独立 probe 的可执行证据才能否决正向 audit。
任何 audit 协议失败都会 fail closed 为 `abstain`；有限 probe 只保留为诊断证据，
不能替代全规约审查。公开方法的每条非平凡 `requires` 还必须绑定到题目明示的定义域
或受支持的数学可定义性理由，否则同样弃权。若初始拒绝的反例被执行推翻，结果也只
是 provisional overturn；必须再做一次 fresh whole-spec reconciliation audit，并且其
批准边界必须与已经执行的证据逐项一致，才能最终批准。

## 评测原则

- `strict` 是默认且推荐的研究口径。官方 HumanEval 测试不会进入生成或修复循环，
  只在 pipeline 停止且 Dafny 验证通过后运行一次。
- `assisted` 允许使用单独整理的开发测试辅助修复，但仍不会向 Agent 泄露官方测试。
- verified template fallback 默认关闭；严格模式会强制关闭它，即使环境变量另有设置。
- Independent Critic 默认开启；其模型、决策和修复次数写入实验结果与 manifest。
- 每次 CLI 运行写入独立目录，并保存代码版本、工作区状态、数据/提示哈希、模型参数、
  Dafny/Python 版本、LLM token/延迟/错误统计和最终结果。

## Quick Start

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

需要运行测试时再安装开发依赖：

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

复制配置模板，至少填写一个模型 API Key，并确认 Dafny 可用：

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 或 OPENAI_API_KEY
dafny --version
```

## 运行 HumanEval

从仓库根目录运行严格评测：

```bash
python project/run_humaneval.py --mode strict --start 0 --limit 5 --rounds 3
```

结果默认写入 `logs/runs/<timestamp>_humaneval_strict_.../`：

- `manifest.json`：可复现配置与 LLM 使用统计；
- `benchmark_intermediate_*.json`：逐题增量快照；
- `benchmark_final.json`：最终汇总和每题研究轨迹。

需要隔离评估 Critic 改动时，可对已有 run 中的冻结规约重放，而不重新调用 Spec/
Code Agent：

```bash
python project/replay_spec_critic.py \
  --input logs/runs/<run>/benchmark_final.json \
  --task-ids HumanEval/2 HumanEval/4 HumanEval/16 \
  --with-official-oracle
```

`--with-official-oracle` 严格在 Critic 决策冻结之后运行官方测试，只用于 post-hoc
标签和 precision/recall 分析，结果不会反馈给 Critic。

辅助模式必须显式提供与官方 HumanEval 测试独立的 JSON/JSONL 开发测试：

```bash
python project/run_humaneval.py \
  --mode assisted \
  --repair-tests data/humaneval_dev_tests.jsonl \
  --start 0 --limit 5 --rounds 3
```

JSONL 每行至少包含 `task_id` 和测试代码字段 `test`，例如：

```json
{"task_id":"HumanEval/0","test":"def check(candidate):\n    assert candidate([...]) == [...]"}
```

不要把官方 `HumanEval.jsonl` 的 `test` 字段复制成开发测试；这样会造成测试泄漏，
结果不能作为严格泛化能力指标。

## 结果口径

最终 `passed` 同时要求：

1. 生成的 Dafny 代码通过验证；
2. 规约与实现的公开方法契约保持一致；
3. 编译后的实现通过官方 HumanEval 留出测试。

固定版本改造后的 2026-07-14 严格模式 20 题运行结果为：Dafny `14/20`
（70%），官方留出测试暨端到端 `11/20`（55%）；首轮端到端 `10/20`。
运行目录为 `logs/runs/20260714_094215_191679_humaneval_strict_0_20/`，其中
manifest 明确记录 `strict`、模板关闭、模型/token 和 dirty working-tree hash。

Independent Critic 的 2026-07-16 三轮同一 20 题迭代结果如下；“正确批准”表示获批
候选同时通过官方留出测试：

| Critic 版本 | 批准覆盖 | 正确批准 | 错误批准 | 总耗时 |
|---|---:|---:|---:|---:|
| 初始结构化 Critic | 5/20 (25%) | 5/5 | 0 | 21.8 min |
| 加入可执行独立 probe | 7/20 (35%) | 7/7 | 0 | 19.0 min |
| 证据分层完整运行 | 10/20 (50%) | 10/10 | 0 | 15.4 min |

当前完整运行位于
`logs/runs/20260716_180313_794440_humaneval_strict_0_20/`。该 run 之后对 `/14`
做的冻结回放又从 `abstain` 恢复为 `approve` 且官方 oracle 通过；这项定点结果尚未
计入上表的完整 20 题数字。此后还进一步关闭了 audit-protocol-failure 的 probe-only
放行、probe 截断批准、未经 fresh audit 推翻拒绝、伪造 public provenance、未绑定
前置条件和非判别性排序 coverage 等路径，因此上表不是最终代码的重新整轮测量。
历史 verified-wrong 控制 `/3`、`/10`、`/15` 在最新在线反向控制中为 2 个拒绝、1 个
弃权、0 误批准。单次 20 题样本仍不足以给出
稳定置信区间，正式论文应补同一冻结候选池上的多 seed、不同 Critic 模型和选择性
风险—覆盖曲线。

最终 fail-closed 代码的定点冻结回放保存在同一 run 目录：

- `critic_replay_postfix_hardened.json` 及后续 reconciliation v3/v4 回放：合并结果为
  `/2、/4、/14、/17` 批准且 oracle 通过；`/16` 因 audit 协议失败弃权；`/18` 因
  协议/定义域风险弃权；
- `critic_replay_postfix_verified_wrong.json`：三个精选 verified-wrong 控制 0 误批准；
- `critic_replay_final_domain_control.json`：官方测试可通过、但含无依据
  `requires threshold >= 0` 的旧 `/0` 从批准改为弃权。

这些是定点安全/效用控制，不是新一轮完整 20 题，也不能替代多 seed 统计。最后加入
的 reconciliation 证据逐项对账和输出/输入定义域绑定已通过 168 个本地回归测试；因
模型 API 用量上限，尚未再次在线重放，所以论文数据应在额度恢复后重新跑冻结候选池。

2026-07-09 的旧纯 LLM 20 题基线为 Dafny `8/20`（40%）、端到端 `6/20`
（30%）。旧数字来自协议硬化之前，仅作为历史对照；不能与模板辅助的旧 `5/5`
烟雾结果混用。由于 LLM 输出有方差，正式研究报告仍应补充多 seed 重复运行。

## Notes

- `.env`、虚拟环境、缓存、工具包和 `logs/` 不会提交到 Git。
- Dafny 需要预先安装并在 `PATH` 中，或通过 `DAFNY_PATH` / `DAFNY_SOLVER_PATH`
  指定。
- 可用 `RUNS_DIR` 改写独立实验目录的位置；也可用 CLI `--output-dir` 指定本次目录。
- 完整本机环境与协议说明见 `README_SETUP.md`。
