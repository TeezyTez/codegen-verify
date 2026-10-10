# 固定数据与离线预检

仓库同步说明（2026-10-10）：以下保留最初数据抓取与预检阶段的操作记录。公开数据与固定版本清单已入库；`baf_preflight/`、`reference_census/` 是本机生成的验证输出，已由 `.gitignore` 排除。新克隆需要先运行相应脚本的 `prepare`，再执行下面的 `run`；不要把“本机已 prepare”当作新克隆也已有日志。正式代码生成队列的当前状态见根目录 README；本目录早期 `campaign-design.json` 不代表后来正式队列的状态。

所有命令在 `C:\workspace\gencode\codegen-verify` 执行。上游仓库中的 Python/脚本没有执行；仅把 `.dfy` 数据交给本项目现有 Dafny 验证适配器，没有运行生成程序。三个 snapshot 清单记录固定提交、逐文件 Git blob SHA1 与 SHA256。

- `algoveri/`：77 个原生 Dafny 规格及配套文字、其它语言规格、README/许可。
- `dafnybench/`：原始 782 条 JSON 及参考/移除提示资产。不是 782 个已准入生成任务。
- `vericoding/`：BAF Dafny tasks/issues JSONL、全语言质量 CSV、检查报告、1,754 个 Dafny 发布参考、README/许可。
- `baf_preflight/inventory.json`：3,029 行逐条字段与哈希；`plan.json` 固定 1,754 个参考验证任务。
- `recruitment-groups.json`：1,891 个非 DafnyBench tasks 按已知重复信息合并，仍待语义去重。不是最终 split。
- `campaign-design.json`：大规模实验设计，`run_enabled=false`。控制器 v1、最终任务/模型身份尚未冻结，没有伪造正式模型 jobs。

抓取脚本 `fetch_snapshots.py` 通过 GitHub codeload ZIP 下载固定版本，对选定成员逐一校验 Git tree blob 和文件长度。首次 BAF raw.githubusercontent 请求失败，随后同一固定提交通过 codeload 完成；前两套成功快照没有重写。不要在现有已完成快照上重复运行抓取命令。树文件保存读取到的仓库和 commit。

参考预检已 prepare；恢复时只运行 run，保留已有逐题结果，不在另一个进程仍在处理该队列时启动重复 run：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m research.data.large-scale-20261009.reference_census run
.\.venv\Scripts\python.exe -X utf8 -m research.data.large-scale-20261009.baf_inventory run
```

两个 run 检查固定脚本哈希和工具链身份，一题一 JSON；完成后写 `results.json`、`summary.json`。DafnyBench 为六 worker、BAF 为四 worker，每次30秒参考筛查。120秒正式准入标准另在主协议定义，不能用此轮超时直接排除候选。

预检为参考兼容性观察，不设已知目标集合，因此将实际完成的全部观测批次通过标为 `all_observed_batches_verified`。这不是候选验收：正式模型程序必须核对外部契约、预期目标和新增辅助声明的覆盖，不能直接复制此分类器。

重建非运行性实验设计与原始错误说明：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m research.data.large-scale-20261009.build_campaign_plan
```

`reference_census/tool-error-annotations.json` 解释原始日志，不修改旧结果、不将警告错误改为成功。已完成的782次中236个 tool_error 都有严格警告策略拒绝信息，须区分旧语法与信任绕过等实质警告。

所有这些脚本的模型调用数均为0。机器生成的大量验证记录不能充当“大规模 agent 有效性实验”。
