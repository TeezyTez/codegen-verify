# Codex batch transport verification — 2026-10-09

## Result

The installed Codex CLI successfully called **gpt-6-astra**, reasoning effort **high**, through the computer's existing Windows proxy. The isolated readiness probe returned exactly `{"ready":true}`, exited 0, and emitted `turn.completed`. This establishes a working model transport for subsequent experiments; it is **not a benchmark sample**.

No production module, Codex account setting, credential file, or system network setting was changed. The probe script did not need modification. Authentication contents were never opened or copied.

## Diagnosis and evidence

| Check | Observation | Interpretation |
|---|---|---|
| Installed CLI | `codex-cli 0.159.0-alpha.12.1` | Existing desktop-bundled CLI is available. |
| Existing login, with explicit `CODEX_HOME` | `Logged in using ChatGPT` | Existing login recognized; this alone does not verify inference. |
| Original sandbox probe | Cache/initialization permission errors | Normal cache access needs authorized execution in this environment. |
| Authorized direct probe | `thread.started`, `turn.started`, then repeated `request timed out`; harness terminated at 60 seconds | CLI initialized, but inference transport did not complete. |
| Proxy environment names | No `HTTP_PROXY`, `HTTPS_PROXY`, or `ALL_PROXY` in diagnostic shell | Child CLI does not inherit a proxy environment route. |
| Existing Windows Internet Settings | `ProxyEnable=1`, `ProxyServer=127.0.0.1:10808`, no auto-config URL | An already configured local proxy exists. |
| Unauthenticated direct HTTPS HEAD | `curl: (28) Connection timed out after 12001 milliseconds` | Direct endpoint connection fails. |
| Same HTTPS HEAD through existing proxy | HTTP 200 CONNECT, then endpoint HTTP 405 / `allow: GET`, under one second | TLS and endpoint route work; HEAD is unsupported. This is not an authentication check. |
| Same isolated inference probe with process-only `HTTPS_PROXY` | Exit 0; exact readiness response; empty stderr | Existing proxy route resolves observed inference timeout. |

The successful probe changed the process proxy route while keeping the same model, reasoning effort, login directory, prompt, and isolation options. This is strong evidence that missing proxy routing caused the prior transport timeout. It does not establish why direct networking is unavailable or guarantee future availability.

Prior evidence is preserved under `logs/codex-transport-20261009-execution/` and `logs/codex-transport-20261009-authorized/`. Successful evidence is under `logs/codex-transport-20261009-existing-proxy/`:

- `request.json`: exact executable, argument array, and prompt.
- `stdout.jsonl`: completed assistant response and usage.
- `stderr.txt`: zero bytes.

Successful run timestamps: request written **2026-10-09 07:59:49 UTC**, stdout written **08:00:03 UTC** (about 14.9 seconds end-to-end, inferred from artifact timestamps). Thread ID: `01a11fac-fc60-7e80-815a-fb1ed6e91382`.

```json
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"{\"ready\":true}"}}
{"type":"turn.completed","usage":{"input_tokens":11705,"cached_input_tokens":3968,"cache_write_input_tokens":0,"output_tokens":9,"reasoning_output_tokens":0}}
```

The reported input token count includes Codex harness context and must not be treated as the length of the tiny user prompt. Cached input tokens are part of the reported input, not additional generated tokens.

## Reproduction

Working directory: `C:/workspace/gencode/codegen-verify`. Use a **fresh output directory** because the script refuses to overwrite an existing run. The actual successful command was:

```powershell
$env:HTTPS_PROXY = 'http://127.0.0.1:10808'
.venv/Scripts/python.exe scripts/probe_codex_model.py --codex-home C:/Users/16039/.codex --output logs/codex-transport-20261009-existing-proxy --model gpt-6-astra
```

Run it in an authorized process that can use the existing Codex cache. The environment assignment is limited to that shell and its children; it does not modify Windows proxy settings. The Python script separately sets child `CODEX_HOME` to the supplied existing login directory. Do not copy authentication material into an experiment directory. The bare `python` command resolves to a Windows Store alias in the approved shell; the repository virtual environment above is the working interpreter.

The script calls `codex exec --ignore-user-config --strict-config --ephemeral --skip-git-repo-check --sandbox read-only --json --model gpt-6-astra`, uses the run directory as working root, sets `project_doc_max_bytes=0`, redirects local logs/state into the run directory, disables web search, and disables shell, unified exec, multi-agent, apps, plugins, memories, and hooks features. See `request.json` for every exact argument. No benchmark source, reference implementation, or hidden test was supplied in this readiness prompt.

## Experiment constraints

- Preserve the requested existing Codex model route; no DeepSeek or alternative model was substituted.
- The probe proves one completed request, not batch throughput, stability, or statistical quality. Benchmark generation still needs separate saved prompts, responses, verification, and accounting.
- Keep the process proxy setting explicit in the batch invocation so future failures are reproducible. The existing proxy must remain available.
- Do not include this readiness output in benchmark denominators or claim these tokens as benchmark usage.
- Keep sandbox and tool isolation in the actual generation transport; approved host execution permits normal authentication/cache/network operations and does not authorize generated code to execute outside the experiment verifier.

## Official documentation consulted

- [Authentication](https://learn.chatgpt.com/docs/auth): Codex reuses cached login; credential storage belongs to `CODEX_HOME` or the OS credential store. Credential files are secret.
- [Build iterative repair loops with Codex](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex): official example of non-interactive CLI subprocess calls and explicit model/reasoning/output arguments.
- Installed `codex exec --help` confirmed that `--ignore-user-config` skips user configuration while authentication still uses `CODEX_HOME`, and that `--ephemeral` avoids persisted session files. Local cache/state artifacts may still be created, as observed here.

## Batch adapter follow-up

`generation/public_benchmark/model.py` now exposes `CodexModel(model='gpt-6-astra', effort='high', codex_home=..., proxy=...)`, `identity()`, and `generate(messages, output_dir, timeout=900, max_output_tokens=16384)`. Each fresh output directory retains request, prompt, stdout, stderr, result, and command/request SHA-256 hashes. Messages are explicitly serialized as a role-labeled JSON transcript inside one CLI user prompt; this is not native API message-role injection. Generation uses an empty `work/` directory and disables project-document loading and the same tools/features as the readiness probe.

The [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) documents provider request and stream retry controls. The installed CLI forbids overriding reserved built-in provider ID `openai`: the first adapter smoke failed at configuration load before network execution, preserved in `logs/codex-adapter-20261009-smoke/`. The adapter therefore explicitly selects provider configuration alias `openai_batch`, with `requires_openai_auth=true`, Responses protocol, no base URL override, and request/stream retries both set to zero. This uses the existing OpenAI login and its default endpoint, not an alternative model provider or copied credential.

The corrected adapter smoke succeeded in **20.032 seconds**, with exact `{"ready":true}`, exit 0, input tokens **11760**, output tokens **9**, and no transport error. Evidence: `logs/codex-adapter-20261009-no-retry-smoke/`. Request SHA-256: `3e68fe2590e6a22193ea77f3ba7c22bc995aaae45bf691347c93ce1c0695be8e`. Command SHA-256: `44044551a817cd4dc4a869f5bdcdeae87c8fcec010e1bd80357f32f8c279b583`. This smoke is excluded from benchmark counts.

No documented `max_output_tokens` generation cap was found in the installed CLI help or official config reference. The adapter records `output_cap_enforced=false`, saves the requested cap, and reports whether provider-reported output usage exceeds it; the experiment controller must decide eligibility and stop further actions using actual usage. It does not truncate responses or claim generation-budget enforcement. The observed JSONL does not report response model or effort, so those response fields remain null; requested CLI model/effort are recorded, and any emitted identity fields are checked for mismatch.

Verification: **17 synthetic-fixture tests passed** with `.venv/Scripts/python.exe -m pytest tests/test_public_model.py -q`. They exercise actual parser behavior, malformed/unfinished logs, tool events, duplicate finals, identity mismatch, usage validation, event ordering, timeout preservation, launch failures, process crashes, immutable output directories, and recorded isolation arguments. These unit-test fixtures are not research generations. No production benchmark call was made by this adapter implementation task.
