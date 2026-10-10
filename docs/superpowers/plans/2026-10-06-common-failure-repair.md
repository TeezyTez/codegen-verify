# Common-failure repair exploration

User approved continuing with common failing code/diagnostics on 2026-10-06. Execute inline using the existing experimental loop; preserve all previous artifacts. This is a bounded extension of the previous authorized design, not a new approval gate.

Question: can the real model repair fixed failing implementations under actual Dafny feedback, and is there any observed difference between raw feedback, explicit state, deterministic target guidance and independent repair sampling?

Freeze before generation: two existing development contracts (binary_lower_bound, integer_sqrt), one authored multi-defect failing body per contract, four conditions, one replicate, schedule seed 20261007. 8 runs, maximum 24 generation requests and 32 within-run checks. Common failing candidates are verified once per task and the exact resulting evidence is replayed identically for all four conditions; those initial checks and reference checks are outside repair budgets and separately counted. Each run allows 3 model requests, 4 full-file checks including final acceptance, 15 seconds per check, 300 seconds per queued response, 1200 seconds per run. Token/dollar caps remain unenforced; use a distinct Codex exploration protocol.

All groups receive the same seed and full public Dafny diagnostic text (temporary paths normalized), and the same repair instruction. A uses current candidate and chronological feedback; B additionally sees the current ledger; C additionally sees the selected target. D always sees the original seed and feedback, independently sampling repairs without later feedback. D is therefore independent repair sampling, not the prior from-scratch sampler. No prompt-length placebo or random-target ablation in this small batch; no causal claim about selector optimality.

Ruling: repair is unrestricted within the existing allowed body grammar. Replacing the whole implementation is allowed; count such cases explicitly and do not equate them with targeted local repair. Seeds deliberately contain errors and are exploratory fixtures, not naturally sampled model failures. Neither task is a holdout.

Tasks:
1. [x] Reproduce and fix stale diagnostic scheduling after successful verification; keep historical observations intact.
2. [x] Add an optional frozen failing start to the shared executor, plus repair policy and queue driver; preserve the existing final acceptance. Test initial evidence identity/acceptance, equal first-round public input, D restart semantics and B/C instruction equivalence.
3. [x] Validate/freeze seeds, prompts, config, toolchain, source and schedule. Review code, then execute all 8 planned runs with fresh no-history/no-tools solvers.
4. [x] Audit every response and final verification; report complete outcomes, repairs/replacements, usage limitations and next-stage decision. Do not expand on p-values.

Review focus: seed evidence cannot certify generated output; initial failure must be real and source-bound; old diagnostics cannot remain active after fresh verification; all groups get identical initial source/diagnostics and instruction; sampling never gets later feedback; no silent dropped jobs or free retries.

Validation: full suite 400 passed + 2 subtests (120.15 seconds). Reviewer identified missing frozen-task-set validation; reproduced a failing test, fixed the guard, then 40 focused tests passed. Preflight verified both references and both authored failing seeds with real Dafny, and checked first-round common fields match across all groups. No production code changes after live batch freeze. Live batch: `logs/common-failure-repair-20261006`.

Completed: all 8 first repairs and final rechecks verified. A disclosed manual dispatch omission in `006_binary_lower_bound_state` invalidates that run for controlled comparison; no replacement or hidden retry. 7 comparison-eligible runs, 1 complete four-arm task block. Artifact audit preserves this distinction; session audit found matching raw finals, inherited gpt-6-astra/high and zero tool calls. Task payload encryption prevents independent plaintext dispatch attestation. 8 model requests, 16 within-run verifier calls, 4 admission checks, 4 separate preflight checks; 251,721 reported session tokens, dollar cost unknown. Report: `research/COMMON_FAILURE_REPAIR_RESULTS_2026_10_06.md`. Next gate: eliminate manual transcription and validate actual dispatch before expanding the development set. This batch establishes repair feasibility, not efficacy or a completed large-scale experiment.
