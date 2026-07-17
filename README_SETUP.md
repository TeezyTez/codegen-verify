# 本机环境与评测配置

这个项目是“自然语言任务 → Dafny 规约 → Dafny 实现 → 形式验证 → 定向修复 →
HumanEval 留出测试”的实验工程。主流程位于 `project/`：

1. `task_normalizer.py` 用 AST 找到准确入口函数，保留完整题面、签名、类型和示例；
2. `pipeline.py` 串联 Spec、Code、Diagnose、Proof Repair 与 Alignment Repair；
3. `dafny_wrapper.py` 调用本机 Dafny 做 `resolve` 和 `verify`；
4. `humaneval_tester.py` 在隔离子进程中翻译并执行完整 `check(candidate)`；
5. `run_humaneval.py` 实施严格/辅助协议并写入独立实验目录。

## 1. 系统依赖

建议使用 Python 3.11 或 3.12、Dafny 4.11.0，并固定版本以便复现实验。

确认命令可用：

```bash
python --version
dafny --version
```

如果 Dafny 或 Z3 不在默认搜索路径，在 `.env` 中设置绝对路径：

```dotenv
DAFNY_PATH=/absolute/path/to/dafny
DAFNY_SOLVER_PATH=/absolute/path/to/z3
```

Windows 路径同样可直接填写，例如：

```dotenv
DAFNY_PATH=D:\tools\dafny\Dafny.exe
DAFNY_SOLVER_PATH=D:\tools\dafny\z3\bin\z3.exe
```

## 2. Python 环境

在仓库根目录创建虚拟环境并安装运行依赖：

```bash
python -m venv .venv
```

macOS / Linux：

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

需要运行测试时安装开发依赖；`requirements-dev.txt` 会同时安装运行依赖：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

## 3. 模型与 pipeline 配置

复制 `.env.example` 为 `.env`，至少配置一个 API Key：

```dotenv
DEEPSEEK_API_KEY=your-key
# OPENAI_API_KEY=your-key
```

常用可复现参数：

```dotenv
SPEC_MODEL=deepseek-chat
CODE_MODEL=deepseek-chat
REPAIR_MODEL=deepseek-chat
CRITIC_PROVIDER=deepseek
CRITIC_MODEL=deepseek-chat
CRITIC_PROBE_PROVIDER=deepseek
CRITIC_PROBE_MODEL=deepseek-chat
CRITIC_TEMPERATURE=0.0
CRITIC_MAX_TOKENS=1800
CRITIC_PROBE_MAX_TOKENS=1200
MAX_CRITIC_PROBE_PARSE_RETRIES=2
MIN_CRITIC_PROBES=3
MAX_CRITIC_PROBES=6
CRITIC_REQUIRE_PRECONDITION_EVIDENCE=1
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=0
LLM_RETRIES=2
MAX_REPAIR_ROUNDS=3
EVALUATION_MODE=strict
USE_TEMPLATE_FALLBACK=0
ENABLE_SPEC_CRITIC=1
MAX_CRITIC_REPAIR_ROUNDS=1
CRITIC_REVIEW_PASSES=1
```

`LLM_MAX_TOKENS=0` 表示不显式设置上限。真实 Key 只应出现在本机 `.env` 或环境
变量中；不要写入源码、测试、结果文件或提交到仓库。

模板回退现在默认关闭。它只适合本地演示或调试，不能计入纯 LLM 实验；
`--mode strict` 会无条件关闭模板回退。

## 4. 快速检查

以下命令不调用模型 API：

```bash
python -m pytest tests -q
python project/dafny_wrapper.py
```

若只想做 Python 语法检查：

```bash
python -m compileall -q project tests
```

HumanEval 运行会调用模型 API 并消耗额度。先用单题严格烟雾测试确认端到端环境：

```bash
python project/run_humaneval.py --mode strict --start 0 --limit 1 --rounds 1
```

再运行固定切片：

```bash
python project/run_humaneval.py --mode strict --start 0 --limit 20 --rounds 3
python project/run_humaneval.py --mode strict --start 20 --limit 10 --rounds 3
```

仅重放已有 run 中的冻结规约与 Independent Critic（不重新生成规约/代码）：

```powershell
python project/replay_spec_critic.py `
  --input logs/runs/<run>/benchmark_final.json `
  --task-ids HumanEval/2 HumanEval/4 HumanEval/16 `
  --with-official-oracle
```

官方 oracle 只在 Critic 决策写定后执行，不会进入审查或修复上下文。

`run_nl2vc.py` 需要另行放置 `data/NL2VC-60.jsonl`。

## 5. 严格与辅助协议

### strict（默认）

严格模式不向任何生成或修复 Agent 提供官方 HumanEval 测试。仅当 pipeline 已停止
且 Dafny 验证通过时，官方 `check(candidate)` 才作为一次性留出测试运行。留出失败
不会再触发修复。因此严格结果可用于比较泛化能力。

```bash
python project/run_humaneval.py --mode strict --start 0 --limit 5
```

### assisted

辅助模式允许把独立开发测试放入行为修复循环，但必须显式指定文件：

```bash
python project/run_humaneval.py \
  --mode assisted \
  --repair-tests data/humaneval_dev_tests.jsonl \
  --start 0 --limit 5
```

支持的 JSONL 示例：

```json
{"task_id":"HumanEval/0","test":"def check(candidate):\n    assert candidate([...]) == [...]"}
```

也可使用以下 JSON 映射形式：

```json
{
  "HumanEval/0": {
    "test": "def check(candidate):\n    assert candidate([...]) == [...]"
  }
}
```

开发测试必须独立整理，不能由官方 `test` 字段复制或变形得到。无论哪种模式，
官方测试都不会作为修复反馈。

## 6. 实验目录与 manifest

默认情况下，每次 CLI 运行创建：

```text
logs/runs/<timestamp>_humaneval_<mode>_<start>_<count>/
├── manifest.json
├── benchmark_intermediate_*.json
└── benchmark_final.json
```

`manifest.json` 在运行前记录：

- Git SHA、dirty 状态和工作区哈希；
- 数据 SHA-256、提示源码组合哈希和任务 ID；
- 模型、温度、token 上限、重试及 pipeline 开关；
- Python、平台、Dafny 路径/版本和关键依赖版本。

运行完成后还会写入 LLM 请求次数、token、延迟、错误事件和不含逐题大对象的结果
摘要。可使用 `RUNS_DIR` 改写根目录，或使用 `--output-dir` 指定一个明确的本次
目录。为了保持实验隔离，不要复用已有 run 目录。

比较实验时至少固定：数据哈希、任务 ID、模型版本、温度、修复轮次、Dafny 版本
和评测模式。模板辅助结果、辅助模式结果与严格模式结果应分别报告。

Critic 默认与 Spec Agent 使用相同模型，但拥有独立 client、prompt 和无共享历史的
调用上下文。跨模型实验只需修改 `CRITIC_PROVIDER` 与 `CRITIC_MODEL`；manifest 会
分别记录 Critic 与 spec-blind probe generator 的 provider、model、temperature、
token/解析重试上限和修复预算。确认失败 probe 时不会向确认模型展示原期望值；
公开示例、独立 probe 与 Critic 自写反例在日志中保留不同 provenance，模型生成的
probe 不能声明为 public example。全部 public/spec-blind 证据会按
`MAX_EXECUTED_CRITIC_PROBES` 分批执行，不会因截断后仍被视为通过。audit 协议失败
不会触发 probe-only 批准；初始 reject 被执行推翻后还需要 fresh reconciliation
audit，其批准边界必须复用已经执行且同 expected 的证据。非平凡 public `requires`
默认还需要明确、参数绑定且非输出语境的定义域/数学可定义性证据，可用
`CRITIC_REQUIRE_PRECONDITION_EVIDENCE=0` 做消融但不建议用于高保证主结果。
