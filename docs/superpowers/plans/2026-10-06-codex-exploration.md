# Codex isolated exploration execution ledger

User authorized execution on 2026-10-06 after being offered isolated subagents.

Frozen intent: integer_sqrt and binary_lower_bound, four existing conditions, one replicate, seed 20261006. Eight runs, at most 32 visible generation requests and 40 within-run real Dafny checks. This is development exploration, not confirmation or an API-budget comparison.

Ruling: reuse the trusted engine through a file-queue model and a separate protocol `fixed_spec_obligation_codex_exploratory_v1`. Fresh `fork_turns=none` solver per request; pass only a uniform wrapper and the exact policy messages. No tools or reference access permitted by solver instructions. Platform system/environment context is inherited and tool prohibition is an instruction, not a technical sandbox. Record this limitation. Never manually improve solver output.

Ruling: allow 300 seconds per queued response and 1500 seconds per run, including controller delay; keep verifier timeout 15 seconds. Token limits and sampling seeds cannot be enforced by collaboration, so total_tokens=null and output_tokens=4096 is advisory. Account usage/cost and actual backend identity remain unknown; record inherited model selection. Do not equate this to the strict API protocol.

1. [x] Test queue response identity, raw output preservation, timeout accounting and protocol isolation; implement adapter and driver without changing shared acceptance. RED: 3 missing-module failures. GREEN: 35 exploration/obligation tests passed. Fresh read-only review found no blocking issue.
2. [x] Freeze config, jobs, task/source/toolchain identities and initial messages; independently verify reference/negative admission; execute the eight runs once, preserving all failures. All eight passed first candidate and persisted-final verification; 8 generation requests, 16 within-run checks, 4 admission checks.
3. [x] Audit raw artifacts, report all conditions and limitations; run focused regression and fresh read-only review. Artifact audit passed. Eight local solver logs showed gpt-6-astra/high, no tool calls, exact matching final responses. Local counters recovered post hoc in a separate session audit; runtime unknown usage records remain untouched.

No automatic expansion to 96 runs until this eight-run batch establishes a usable model loop. No efficacy-based stopping within this batch.

Execution notes: batch `logs/codex-exploration-20261006` frozen before requests. The initial solver-spawn attempt returned `agent thread limit reached` while review was active. Once review completed, the same pending first request was successfully dispatched within its original deadline; no replacement candidate or budget reset occurred. This failed spawn is an orchestration event, not algorithm outcomes. All solver tasks use `fork_turns=none` and inherit the parent model settings.

Result: `research/CODEX_EXPLORATION_RESULTS_2026_10_06.md`. No repair was triggered, so no evidence of repair benefit. Proceed to harder audited development tasks or a separately frozen common-failure repair substudy before enlarging the experiment. No 96-run or larger batch launched.
