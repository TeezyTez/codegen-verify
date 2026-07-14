# Codegen Verify

规约引导的大模型代码生成与 Dafny 验证修复实验项目。系统把 HumanEval
题目规范化为结构化任务，依次生成 Dafny 规约和实现，运行解析/验证，按错误类型
修复，最后才在官方 HumanEval 留出测试上做一次端到端判定。

## 评测原则

- `strict` 是默认且推荐的研究口径。官方 HumanEval 测试不会进入生成或修复循环，
  只在 pipeline 停止且 Dafny 验证通过后运行一次。
- `assisted` 允许使用单独整理的开发测试辅助修复，但仍不会向 Agent 泄露官方测试。
- verified template fallback 默认关闭；严格模式会强制关闭它，即使环境变量另有设置。
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

2026-07-09 的旧纯 LLM 20 题基线为 Dafny `8/20`（40%）、端到端 `6/20`
（30%）。旧数字来自协议硬化之前，仅作为历史对照；不能与模板辅助的旧 `5/5`
烟雾结果混用。由于 LLM 输出有方差，正式研究报告仍应补充多 seed 重复运行。

## Notes

- `.env`、虚拟环境、缓存、工具包和 `logs/` 不会提交到 Git。
- Dafny 需要预先安装并在 `PATH` 中，或通过 `DAFNY_PATH` / `DAFNY_SOLVER_PATH`
  指定。
- 可用 `RUNS_DIR` 改写独立实验目录的位置；也可用 CLI `--output-dir` 指定本次目录。
- 完整本机环境与协议说明见 `README_SETUP.md`。
