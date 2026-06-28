# Codegen Verify

规约引导的大模型代码生成与 Dafny 验证修复实验项目。

项目流程：

1. Spec Agent 根据自然语言题目生成 Dafny 规约。
2. Code Agent 根据规约生成 Dafny 实现。
3. Dafny Verifier 执行 `resolve` / `verify`。
4. Diagnose / Repair Agent 根据验证错误迭代修复。
5. 对 HumanEval 题目，Dafny 通过后再编译到 Python 运行原始测试。

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

配置 API Key：

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

运行快速评测：

```bash
cd project
python run_humaneval.py --start 0 --limit 5 --rounds 3
```

纯 LLM 实验可关闭本地 verified template fallback：

```bash
USE_TEMPLATE_FALLBACK=0 python run_humaneval.py --start 0 --limit 5
```

## Current Result

在默认配置下，前 5 个 HumanEval 样例当前结果：

- Dafny verified: 5/5
- HumanEval passed: 5/5
- End-to-end passed: 5/5

## Notes

- `.env`、虚拟环境、缓存和日志不会提交到 Git。
- Dafny 需要预先安装并确保 `dafny` 在 `PATH` 中。
- 更详细的本机环境配置见 `README_SETUP.md`。
