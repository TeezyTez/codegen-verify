# Obligation evidence guided generation

The approved experiment asks whether explicit obligation/evidence state and targeted repair improve full Dafny verification under the same fixed specification, model and budget. The user authorized implementation on 2026-10-06. This is a new protocol, `fixed_spec_obligation_v1`; previous generation, repair and representation experiments remain separately usable.

## Scope

- Single agent, Dafny 4.11, existing restricted method-body and proof-annotation syntax.
- All four conditions see the same public frozen formal contract. References, mutants and test witnesses stay private. Existing hidden-contract representation experiments retain their original disclosure policy.
- Conditions: `baseline` (current body plus chronological diagnostic history), `state` (same evidence plus structured state), `guided` (state plus a deterministic target), `independent_sampling` (fresh identical prompts without candidate/feedback). One system instruction and body-only response schema for every condition. Guided instructions ask for an actual targeted edit; no additional model calls.
- Reuse one execution engine for budget accounting, model calls, candidate assembly, verifier execution, final persisted-file recheck and artifacts. Protocol adapters own prompts and experimental state, never acceptance.
- State distinguishes fixed requirement clauses, method verification batches, and observed diagnostic targets. Preconditions are assumptions, not claims proved for every input. A disappearing diagnostic is not a proof. Current obligation evidence is `UNOBSERVED`, `UNPROVED`, `DISCHARGED`, `UNKNOWN` or `STALE`.
- Evidence binds specification hash, exact assembled candidate hash and toolchain/options identity. Each changed candidate invalidates previous state before new verification. Explicit passed method batches can be recorded during a failing whole-file check; only whole-file real success discharges mapped postconditions. Individual diagnostic targets never become proved from disappearance. Scope is conservative, not a recovered VC graph.
- Model hypotheses do not set evidence state. Immutable snapshots preserve past observations. Repeated candidates are recorded and surfaced, not given free verifier calls or extra model calls.
- Target order: invalid candidate/parse diagnostic first, current unproved diagnostics or obligations, stale/unobserved items, then unknown. Ties use stable IDs. Unknown solver outcomes do not prove implementation defects.
- Defaults: 4 model calls, 5 verifier calls, 4096 output tokens, 48000 accounted tokens, 15 seconds per verification, 180 seconds per run. Existing token reservation remains engineering accounting, not a provider billing guarantee.
- Offline fixtures are labeled mock/reference-using. Live requests require explicit CLI authorization. No paid experiments in this refactor.
- New summaries reject foreign protocols and corrupted artifacts, retain incomplete jobs, and group repeats by task. Include repetition, repair success, token/call counts, verification outcomes and observable regression metrics; no claims of statistical efficacy.

## Implementation limits

The first version has no cross-task memory, multi-agent execution, learned ranking, incremental proof reuse, resume support, or automatically generated target specification. A full semantic proof dependency graph is not claimed. Existing development tasks are protocol diagnostics, not an independent research benchmark.

## Acceptance

Tests must catch stale evidence reuse, model-claimed success, unmapped diagnostics, identical independent prompts, unequal disclosure, budget bypass, final recheck failure, mixed-protocol summaries and loss of prior representation behavior. Run actual local Dafny smoke cases with labeled fixtures after unit/regression checks. Preserve the six pre-existing untracked research files.
