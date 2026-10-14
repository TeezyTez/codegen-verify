# 官方来源与证据边界

核查日期：2026-10-14。以下页面在本次讨论中已打开核对。产品文档可能继续更新；链接与核查日期用于定位信息来源，不是页面内容的不可变快照。

| 来源 | 支持的内容 | 使用边界 |
| --- | --- | --- |
| [OpenAI Conversation state](https://developers.openai.com/api/docs/guides/conversation-state) | 通过消息和会话状态维持多轮交互 | 不据此推断当前桌面会话的每次实际输入 |
| [OpenAI Compaction](https://developers.openai.com/api/docs/guides/compaction) | 减少上下文大小并携带后续所需状态；压缩项可不具备可读文字形式 | 不提供每条约束始终无损保留的保证 |
| [Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) | 指令文件发现、目录范围、合并顺序和大小限制 | 具体加载规则适用于该工具，不能自动推广到其他产品 |
| [Claude Code Memory](https://code.claude.com/docs/en/memory) | 指令文件、自动记忆、上下文与强制配置的区别 | 自动记忆不等于所有历史需求都被保存和执行 |
| [Cursor Rules](https://cursor.com/docs/rules) | 持久规则与不同触发方式 | 不同触发方式有不同加载条件 |
| [GitHub Copilot Repository instructions](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions) | 仓库级、路径级与代理指令 | 支持范围随产品功能和客户端而异 |
| [GitHub Spec Kit Quickstart](https://github.github.io/spec-kit/quickstart.html) | 规格、计划、任务及一致性和完成度检查流程 | 工具流程不构成相对效果或新颖性证据 |
| [Anthropic Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 即时检索、压缩、结构化笔记与子代理上下文管理 | 工程实践和分析，不是本项目的实验结果 |
| [Anthropic Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | 功能清单、进度记录、增量工作和端到端验证案例 | 示例任务及其观察不代表所有编码任务上的保证 |
| [Claude Code Hooks](https://code.claude.com/docs/en/hooks-guide) | 在生命周期事件执行命令，也支持模型参与判断的 hooks | 命令触发机制与检查逻辑是否完备是两回事 |

## 论断类型

- **产品事实**：正文在描述具体工具行为处链接相应官方文档。
- **机制解释**：四环节和失效分类用于组织问题，不作为已测量的频率或因果结论。
- **工程建议**：最小组合、需求追踪和诊断记录为本专题的综合建议。
- **候选研究问题**：需进一步文献核验和受控实验，不能表述为已证明的新方法或研究贡献。

“主流方案”在本次讨论中指多个主流产品及官方案例所采用的方案类别，不涉及市场份额或采用率排名。
