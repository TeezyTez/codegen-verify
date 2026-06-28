# 本机环境配置

这个项目是一个「规约引导的大模型代码生成 + Dafny 验证反馈修复」实验工程。主流程在 `project/` 下：

1. `llm_client.py` 调用 DeepSeek/OpenAI 生成 Dafny 规约、实现和修复补丁。
2. `pipeline.py` 串联 Spec Agent、Code Agent、Dafny Verifier、Repair Agent。
3. `dafny_wrapper.py` 调用本机 `dafny` CLI 做 `resolve` 和 `verify`。
4. `run_humaneval.py` / `run_nl2vc.py` 批量评测数据集。

## 当前这台 Mac 的状态

已完成：

- Apple Command Line Tools: `/Library/Developer/CommandLineTools`
- Git: Apple Git 2.50.1
- 用户级 Python: `~/.local/bin/python3`，版本 3.12.13
- uv: `~/.local/bin/uv`
- Dafny: `~/.local/bin/dafny`，版本 4.11.0
- 项目虚拟环境: `.venv`
- Python 依赖: `openai`、`python-pptx`、`lxml`

待网络条件更好时补装：

- Homebrew（可选，用于后续更方便地安装系统工具）

## 1. 安装系统工具

macOS 需要先有 Python 3 和 Dafny。

```bash
# 如果还没有 Xcode Command Line Tools
xcode-select --install

# 推荐安装 Homebrew 后安装常用系统工具
brew install python git

# 可选：用 Homebrew 安装 .NET SDK
brew install --cask dotnet-sdk
```

如果 `dafny` 不在 PATH，可以运行时设置：

```bash
export DAFNY_PATH="/absolute/path/to/dafny"
```

这台机器当前使用 Dafny 官方 Apple Silicon release zip，已安装到：

```bash
~/.local/dafny/4.11.0/dafny/dafny
```

## 2. 创建 Python 虚拟环境

```bash
cd /Users/zhangfangying/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_ud91axvt7xjx22_d5e9/msg/file/2026-06/workspace/codegen-verify/codegen-verify/codegen-verify
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

这台机器已经完成上述步骤。

## 3. 配置 API Key

```bash
export DEEPSEEK_API_KEY="你的 DeepSeek API Key"
# 如需 OpenAI 再设置：
# export OPENAI_API_KEY="你的 OpenAI API Key"
```

不要把真实 Key 写进代码或提交到仓库。

## 4. 快速检查

```bash
cd project
python dafny_wrapper.py
python run_humaneval.py
```

`run_humaneval.py` 默认跑前 5 题，会调用大模型 API 并消耗额度。`run_nl2vc.py` 需要额外放入 `data/NL2VC-60.jsonl`。

`run_humaneval.py` 支持快速切片评测：

```bash
python run_humaneval.py --start 0 --limit 5 --rounds 3
python run_humaneval.py --start 20 --limit 10
```

当前 pipeline 默认启用 verified template fallback。它会先为少量已整理的 HumanEval 模式使用本地已验证模板，模板没有命中时再调用 LLM pipeline。关闭模板、运行纯 LLM 实验：

```bash
USE_TEMPLATE_FALLBACK=0 python run_humaneval.py --start 0 --limit 5
```

如果暂时没有 Dafny，可以先做 Python 侧检查：

```bash
source .venv/bin/activate
python -m compileall project test_benchmark.py
python -c "import openai, pptx, lxml; print('imports ok')"
```
