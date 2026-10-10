# Execute the authorized large-scale experiment

User instruction: finish the experiment and analyze results. Binding design: `research/LARGE_SCALE_CODEGEN_PROTOCOL_2026_10_09.md`. Execution is authorized; no additional planning approval is requested. Preserve existing uncommitted work and old frozen experiments. New implementation belongs in `generation/public_benchmark/`.

## Interfaces and tasks

1. Model transport: establish a real isolated Codex invocation with recorded backend identity, full prompt/output, usage and transport status. Reuse the user's existing login without reading/copying secrets. Do not substitute another provider silently. A failed transport probe is not a benchmark sample. CLI ordinary sandbox probe failed cache initialization; escalated probe reached a thread but timed out. Diagnose before retrying. Write transport findings to `research/CODEX_BATCH_TRANSPORT_2026_10_09.md`.
2. Trusted Dafny adapter: create `generation/public_benchmark/structure.py` and meaningful negative tests `tests/test_public_structure.py`. `inspect_source(source: str) -> dict` must use the actual Dafny parser/AST or fail closed; return declaration signatures/contracts, bodies, calls, forbidden trust constructs and verifier target coverage. Source-controlled implementation holes are assembled externally; no model authority over fixed contracts. Preserve support for shared functions, predicates and lemmas. Review compiler tool limitations rather than weaken the acceptance guard.
3. Dataset admission: preserve all source IDs/hashes, check reference fixed contracts and absence of bypass, deduplicate original families. Separate compatibility from contract semantic adequacy. Keep a documented challenge pool for unsolved/unaudited tasks. Freeze selected native public tasks and 64 disjoint development families before comparing arms.
4. Controllers: `generation/public_benchmark/policy.py` exposes an evidence ledger and A/B/C/D prompt builders with the design's fixed vs adaptive target selector. Tests must demonstrate candidate revision invalidation, conditional caller passes, dependency closure, stable ordering and cooldown; targets never change acceptance.
5. Runner and analysis: immutable manifests; isolated model contexts; exact prompts/raw logs; equal action/token/verifier limits; randomized paired blocks; durable resume without replacing samples; transparent transport errors. Start with the required 64 development sessions, then the frozen matrix, then paired family-level analysis. Never label partial matrices complete or offline/replay data as generation trials.

## Execution ledger

- Existing public snapshots and offline preflights are reused as data only.
- Ruling: develop in the existing workspace in new modules, preserving older frozen source files and all prior uncommitted work. A new worktree would omit the uncommitted experimental assets required here; no reset/commit/push.
- Independent transport diagnosis and Dafny AST integration may run concurrently under the dispatching-parallel-agents skill; separate file ownership. Root owns policy, dataset admission, runner and analysis.
- If model access is externally blocked, complete independent implementation and tests, preserve the precise failure evidence, and explicitly report the blocked experiment. Never invent model outputs or quietly switch a requested model.
- Policy task: new `generation/public_benchmark/policy.py` implements declaration evidence, SCC closure, fixed and adaptive scheduling. Tests first failed due to missing module; all 8 policy behavior tests now pass. Final integration/review still pending; no efficacy claim.
