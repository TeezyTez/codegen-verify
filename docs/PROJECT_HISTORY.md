# Project History

This file records important research and engineering updates. For each future
code change, append a short entry with the motivation, implementation summary,
and validation result.

## 2026-07-14 - Repository Cleanup

### Updates

- Removed obsolete root-level status, debugging, one-off patch, inspection,
  result-printing, and smoke-test scripts that were not referenced by the
  active pipeline or test suite.
- Removed six superseded presentation-generation scripts and their unused
  `python-pptx` / `lxml` dependencies.
- Removed the stale `activate.ps1` helper, which referenced a machine-specific
  Dafny path and the retired `env/` virtual-environment layout.
- Added local pytest and Claude configuration directories to `.gitignore`.

### Validation

- `python -B -m pytest tests -q -p no:cacheprovider`: 92 passed.
- No active README, project module, test, or requirements file references any
  removed script or dependency.
- `git diff --check` completed without patch-format errors.

## 2026-07-09 - Closed-Loop Spec-Aware Coding Harness

### Motivation

The previous harness treated Dafny verification as the stopping condition. The
HumanEval-20 run exposed a more important failure mode: code can satisfy the
current Dafny spec while still failing behavioral tests. This update turns
verification, behavior testing, spec adequacy, mutation adequacy, and repair
routing into one closed loop.

### Updates

- Added `project/spec_code_alignment.py` for verified-but-behavior-failed
  repair.
- Added `project/mutation_probe.py` for reusable lightweight in-loop mutation
  adequacy probing.
- Extended `pipeline.py` state with:
  - `dafny_verified`,
  - `behavior_executed`,
  - `behavior_passed`,
  - `behavior_error`,
  - `mutation_adequacy`.
- Added a `behavior_test` node after successful Dafny verification.
- Added an `alignment_repair` node that repairs spec/code alignment when Dafny
  passes but HumanEval behavior fails.
- Added an in-loop `mutation_adequacy` node before code generation.
- Added a `spec_strengthening` node that can strengthen specs when simple
  mutants are still verified.
- Hardened `proof_repair_agent` so it rejects outputs that drop original
  `requires`/`ensures` clauses.
- Updated `run_humaneval.py` so HumanEval problems are passed into the pipeline
  as behavior tests instead of being only a post-hoc benchmark check.
- Strengthened `spec_adequacy.py` with task-type-aware checks for filter,
  membership, count, sorting, and prefix tasks.
- Updated `analyze_results.py` with repair-path metrics:
  - proof repair attempts/success,
  - alignment repair attempts/success,
  - spec strengthening attempts/success,
  - behavior loop execution count.
- Added configuration flags:
  - `ENABLE_BEHAVIOR_REPAIR_LOOP`,
  - `ENABLE_INLOOP_MUTATION_ADEQUACY`,
  - `ENABLE_MUTATION_SPEC_STRENGTHENING`.

### Validation

- `python -m compileall project test_benchmark.py`
- `USE_TEMPLATE_FALLBACK=0 python run_humaneval.py --start 0 --limit 1 --rounds 1`
  - `HumanEval/0` passed Dafny and HumanEval behavior tests.
  - Trace included `mutation_adequacy` and `behavior_test`.
- `USE_TEMPLATE_FALLBACK=0 python run_humaneval.py --start 7 --limit 1 --rounds 2`
  - `HumanEval/7` passed Dafny and HumanEval behavior tests.
  - In-loop mutation adequacy reported `0/2` verified mutants.
- Behavior-failure routing smoke check:
  - `decide_after_behavior(...)` returns `alignment_repair` when behavior fails
    before the repair budget is exhausted.
- `python mutation_adequacy.py`
- `python analyze_results.py`
  - New repair-path metrics are written to `logs/benchmark_results.csv` and
    `logs/benchmark_summary.json`.

### Next Steps

- Run a fresh 20-task experiment with this closed-loop harness and compare
  verified-but-test-failed rate against the 2026-07-07 baseline.
- Add targeted case studies for `HumanEval/7` and `HumanEval/12`.
- Improve alignment repair with structured JSON output so spec and code changes
  can be audited separately.

## 2026-07-07 - HumanEval-20 Run with Repair Policy and Proof Repair

### Motivation

After adding repair-policy routing and a proof repair agent, rerun the same
20-task HumanEval slice to check whether explicit proof repair improves the
harness and whether the new behavior exposes different research risks.

### Updates

- Ran a pure LLM benchmark with template fallback disabled:
  `USE_TEMPLATE_FALLBACK=0 python run_humaneval.py --start 0 --limit 20 --rounds 3`.
- Ran mutation adequacy analysis with `python mutation_adequacy.py`.
- Ran result aggregation with `python analyze_results.py`.
- Updated result artifacts:
  - `logs/benchmark_final.json`
  - `logs/benchmark_results.csv`
  - `logs/benchmark_summary.json`
  - `logs/mutation_adequacy.json`
  - `logs/mutation_adequacy.csv`

### Validation

- Total tasks: 20.
- End-to-end passed: 7/20.
- Dafny verified: 9/20.
- HumanEval passed: 7/20.
- Verified but test failed: 2/20.
- Average repair rounds: 2.25.
- Average spec adequacy score: 87.9.
- Spec adequacy levels:
  - `strong_static`: 12.
  - `plausible`: 7.
  - `partial`: 1.
- Mutation adequacy:
  - high-risk specs: 2/20.
  - suspicious mutants: 2.
- Passed tasks:
  - `HumanEval/0` `has_close_elements`
  - `HumanEval/2` `truncate_number`
  - `HumanEval/5` `intersperse`
  - `HumanEval/6` `parse_nested_parens`
  - `HumanEval/9` `rolling_max`
  - `HumanEval/11` `string_xor`
  - `HumanEval/14` `all_prefixes`
- Verified but behavior failed:
  - `HumanEval/7` `filter_by_substring`
  - `HumanEval/12` `longest`

### Findings

- Compared with the 2026-07-03 pure LLM run, Dafny verification improved from
  8/20 to 9/20, but end-to-end correctness dropped from 8/20 to 7/20.
- The proof repair route is active and helps the verifier on some tasks, but it
  can also make the system satisfy an insufficient or misaligned specification.
- The two verified-but-test-failed cases are the clearest current evidence that
  the harness should treat formal verification as one signal in a coding-agent
  loop, not as the final stopping condition.

### Next Steps

- Add a post-verification behavior-check stage that routes HumanEval failures
  back into code/spec repair.
- Split metrics by repair path: no repair, code repair, spec repair, and proof
  repair.
- Inspect `HumanEval/7` and `HumanEval/12` as case studies for specification
  insufficiency and verified-but-wrong code.

## 2026-07-07 - Repair Policy and Proof Repair Agent

### Motivation

The project is being reframed as a formal-specification-aware coding agent
harness. The previous pipeline routed all verification failures into a generic
code repair agent, even when the failure was clearly a proof obligation gap.
Recent HumanEval-20 results showed that proof obligations were the largest
failure category, so the harness needs an explicit repair policy and a
specialized proof repair layer.

### Updates

- Added `project/repair_policy.py`.
- Added `project/proof_repair.py`.
- Added `ENABLE_PROOF_REPAIR` configuration.
- Added an explicit `repair_policy` field to pipeline state.
- `diagnose_agent` now calls `choose_repair_policy(...)` and records the
  decision in trace events.
- Added `proof_repair_agent`, which focuses on invariants, assertions, lemmas,
  helper functions, and decreases clauses while preserving the original spec.
- Updated LangGraph routing:
  - verification failure goes to `diagnose`;
  - `diagnose` routes to `proof_repair_agent` or the existing code repair agent
    based on repair policy.

### Validation

- `python -m compileall project test_benchmark.py`
- Policy unit check: an `invariant` error with `proof_obligation_gap` routes to
  `proof_repair_agent`.
- `python run_humaneval.py --start 1 --limit 1 --rounds 1` passed via template
  fallback.
- Pure LLM smoke test on `HumanEval/3` with `USE_TEMPLATE_FALLBACK=0` and
  `--rounds 2` triggered the new proof repair route. The run did not fully pass
  within 2 rounds, but verifier errors were reduced from two proof obligations
  to one assertion failure.

### Next Steps

- Improve `proof_repair_agent` prompts with reusable invariant/assertion
  templates from successful cases.
- Add proof-specific static checks, such as detecting unchanged invariants or
  repeated assertion failures.
- Report proof repair success rate separately from code repair success rate in
  `analyze_results.py`.

## 2026-07-03 - HumanEval-20 Pure LLM Run

### Motivation

After configuring `DEEPSEEK_API_KEY`, run a real pure LLM experiment without
template fallback to observe the current Spec Agent, Spec Repair Agent, Code
Agent, Dafny verifier, repair loop, HumanEval tester, and adequacy diagnostics.

### Updates

- Confirmed the project reads `DEEPSEEK_API_KEY`.
- Ran a one-task smoke test with `USE_TEMPLATE_FALLBACK=0`; `HumanEval/0`
  passed Dafny verification and HumanEval tests.
- Ran `python run_humaneval.py --start 0 --limit 20 --rounds 3` with
  `USE_TEMPLATE_FALLBACK=0`.
- Ran `python mutation_adequacy.py`.
- Ran `python analyze_results.py`.
- Updated result artifacts:
  - `logs/benchmark_final.json`
  - `logs/benchmark_results.csv`
  - `logs/benchmark_summary.json`
  - `logs/mutation_adequacy.json`
  - `logs/mutation_adequacy.csv`

### Validation

- Total tasks: 20.
- End-to-end passed: 8/20.
- Dafny verified: 8/20.
- HumanEval passed: 8/20.
- Verified but test failed: 0/20.
- Average repair rounds: 2.3.
- Average spec adequacy score: 91.4.
- Mutation adequacy:
  - high-risk specs: 1/20.
  - suspicious mutants: 2.
- Passed tasks:
  - `HumanEval/0`
  - `HumanEval/2`
  - `HumanEval/5`
  - `HumanEval/6`
  - `HumanEval/7`
  - `HumanEval/9`
  - `HumanEval/11`
  - `HumanEval/14`
- Main failure categories:
  - `proof_obligation_gap`: 6 tasks.
  - `implementation_language_error`: 3 tasks.
  - `implementation_semantics_mismatch`: 1 task.
  - `spec_or_code_mismatch`: 1 task.
  - `unclassified_verification_failure`: 1 task.

### Next Steps

- Prioritize proof repair: better invariant/assertion generation is the largest
  immediate bottleneck.
- Investigate `HumanEval/4`, the only high mutation-risk spec in this run.
- Improve spec repair output validation because some strengthened specs were
  syntactically valid but too hard to prove.
- Add targeted repair strategies for Dafny `function` purity errors and
  immutable `seq` assignment mistakes.

## 2026-07-02 - HumanEval-20 Dry Run

### Motivation

Run a small benchmark slice to observe the current end-to-end behavior after
adding research trace, spec adequacy checks, mutation adequacy, and spec repair.

### Updates

- Ran `python run_humaneval.py --start 0 --limit 20 --rounds 3`.
- Ran `python mutation_adequacy.py`.
- Ran `python analyze_results.py`.
- Generated/updated:
  - `logs/benchmark_final.json`
  - `logs/benchmark_results.csv`
  - `logs/benchmark_summary.json`
  - `logs/mutation_adequacy.json`
  - `logs/mutation_adequacy.csv`

### Validation

- Total tasks: 20.
- End-to-end passed: 3/20.
- Dafny verified: 3/20.
- HumanEval passed: 3/20.
- The three passing tasks were template fallback cases:
  - `HumanEval/1`
  - `HumanEval/3`
  - `HumanEval/4`
- The other 17 tasks did not enter the LLM pipeline because
  `DEEPSEEK_API_KEY` is not configured.
- Mutation adequacy result:
  - 3 high-risk specs.
  - 5 suspicious mutants.
  - All three template specs verified but were marked inadequate/high-risk
    because their specs are intentionally weak or missing semantic
    postconditions.

### Next Steps

- Configure `DEEPSEEK_API_KEY` and rerun with `USE_TEMPLATE_FALLBACK=0` to test
  the real LLM + spec repair pipeline.
- Strengthen template specs or exclude template fallback from main paper
  results.
- Add mutation adequacy as a primary diagnostic metric in future experiments.

## 2026-07-02 - Spec Repair Agent

### Motivation

The system can now detect weak or inadequate specifications, but detection alone
does not improve the pipeline. The next research step is to strengthen weak
specifications before generating code, so repair can target both code and spec.

### Updates

- Added `project/spec_repair.py`.
- Added `ENABLE_SPEC_REPAIR` and `MAX_SPEC_REPAIR_RETRIES` configuration knobs.
- Implemented `should_repair_spec(...)` to trigger repair for inadequate, weak,
  partial, or critically flagged specs.
- Implemented `repair_spec_with_llm(...)`, which asks the spec LLM to preserve
  the original method signature while adding stronger `requires`/`ensures` or
  pure helper predicates/functions.
- Added Dafny `resolve` validation for repaired specs; invalid repaired specs
  fall back to the original spec.
- Connected a new `spec_repair` node into the LangGraph pipeline between
  `spec_agent` and `code_agent`.
- Added trace events for skipped, successful, and failed spec repair attempts.

### Validation

- `python -m compileall project test_benchmark.py`
- Fake-LLM unit check: weak spec `method f(x: int) returns (result: int)` was
  strengthened to `ensures result == x` and classified as `strong_static`.
- `python run_humaneval.py --start 1 --limit 1 --rounds 1`

### Next Steps

- Run pure LLM experiments with `USE_TEMPLATE_FALLBACK=0` to observe real spec
  repair behavior.
- Add post-test spec repair for cases where Dafny verification passes but
  mutation adequacy or HumanEval behavior reveals weak specs.

## 2026-07-02 - Establish Project History

### Motivation

The project is evolving from an initial prototype into a research system for
specification-guided code verification and repair. To keep the research path
auditable, each meaningful update should record both the idea and the concrete
code changes.

### Updates

- Added this `docs/PROJECT_HISTORY.md` file as the canonical project history.
- Defined the entry format: motivation, updates, validation, and next steps.

### Validation

- Documentation-only change.

### Next Steps

- Append a new entry whenever code, experiments, tooling, or research direction
  changes.

## 2026-07-02 - Result Analysis and Mutation-Based Adequacy Probe

### Motivation

The project needs paper-oriented evidence, not only pass/fail outputs. The next
research question is whether a generated specification is strong enough to rule
out obviously wrong implementations.

### Updates

- Added `project/analyze_results.py` to flatten `benchmark_final.json` into CSV
  and summarize pass rates, adequacy levels, attribution categories, repair
  targets, spec flags, and mutation risks.
- Added `project/mutation_adequacy.py` to generate simple mutants such as
  default returns and direct parameter returns.
- The mutation probe verifies each mutant with Dafny and, when possible, runs
  HumanEval tests against the translated mutant.
- Integrated mutation adequacy reports into `analyze_results.py`, so
  `benchmark_results.csv` includes columns such as `mutants_verified`,
  `suspicious_mutants`, and `mutation_adequacy_risk`.

### Validation

- `python -m compileall project test_benchmark.py`
- `python mutation_adequacy.py`
- `python analyze_results.py`
- Current sample result: `HumanEval/1` has `mutation_adequacy_risk=high`,
  showing that a weak spec can verify an obviously wrong implementation.

### Next Steps

- Add more mutation operators for common HumanEval categories.
- Use mutation risk to trigger spec strengthening or a future spec repair agent.

## 2026-07-02 - Static Specification Adequacy Checker

### Motivation

Dafny verification proves that code satisfies a specification, but it does not
prove that the specification captures the natural-language task. The system
therefore needs an explicit adequacy signal.

### Updates

- Added `project/spec_adequacy.py`.
- Implemented a lightweight static checker that reports:
  - adequacy score and level,
  - missing postconditions,
  - trivial or shape-only postconditions,
  - whether `result` is constrained,
  - whether postconditions relate outputs to inputs,
  - task-feature risks for list/string/bool/order/threshold/sum problems.
- Connected adequacy reports into `pipeline.py`, `research_trace.py`, and
  `run_humaneval.py`.
- Added post-test adequacy checks so the report can distinguish static risks
  from behavior-observed risks such as verified-but-test-failed.

### Validation

- `python -m compileall project test_benchmark.py`
- `python run_humaneval.py --start 1 --limit 1 --rounds 1`
- Confirmed `logs/benchmark_final.json` contains `spec_adequacy` and
  `spec_adequacy_after_tests` trace events.

### Next Steps

- Combine static adequacy with mutation-based adequacy.
- Use adequacy flags to decide whether to repair code, repair spec, or add proof
  hints.

## 2026-07-02 - Research Trace and Failure Attribution

### Motivation

For a research paper, the system must explain why verification failed and what
repair action was chosen. Final pass/fail rates alone are not enough.

### Updates

- Added `project/research_trace.py`.
- Added JSON-friendly trace events for specification generation, code
  generation, verification, diagnosis, repair, and template fallback.
- Added lightweight failure attribution categories such as:
  - `implementation_language_error`,
  - `proof_obligation_gap`,
  - `implementation_semantics_mismatch`,
  - `spec_or_code_mismatch`.
- Added `research_trace` and `final_attribution` fields to benchmark results.

### Validation

- `python -m compileall project test_benchmark.py`
- `python dafny_wrapper.py`
- `python run_humaneval.py --start 1 --limit 1 --rounds 1`

### Next Steps

- Evaluate attribution quality over a larger benchmark slice.
- Use attribution to route repair actions more explicitly.

## 2026-06-30 - Dafny and Z3 Configuration

### Motivation

The project requires Dafny and an SMT solver to run formal verification. The
local environment had Python dependencies but no usable Dafny command.

### Updates

- Installed Dafny 4.11.0 as a local .NET tool under `.tools/dotnet-tools`.
- Reused Z3 4.14.1 from the Dafny release package.
- Added `DAFNY_PATH` and `DAFNY_SOLVER_PATH` to `.env`.
- Updated `project/config.py` to read `DAFNY_SOLVER_PATH`.
- Updated `project/dafny_wrapper.py` to pass `--solver-path` during `verify`.
- Updated `project/humaneval_tester.py` to pass `--solver-path` during
  `dafny translate py`.
- Ignored `.tools/` in `.gitignore`.

### Validation

- `.tools\dotnet-tools\dafny.exe --version`
- `.tools\dafny-4.11.0\dafny\z3\bin\z3-4.14.1.exe --version`
- `python dafny_wrapper.py`
- `python run_humaneval.py --start 1 --limit 1 --rounds 1`

### Next Steps

- Keep Dafny/Z3 versions fixed for reproducible experiments.
- Add an environment checker script later.

## 2026-07-09 - Closed-Loop Regression Fixes: Rollback Guard, Test Diagnostics, Spec Relaxation

### Motivation

The 2026-07-09 closed-loop harness run (5/20 end-to-end, 6/20 Dafny verified) regressed
relative to the 2026-07-07 baseline (7/20, 9/20). Root-cause analysis of the 20-task
`benchmark_final.json` traces identified three systematic issues:

1. **No rollback after repair regression (RC1 — hit HumanEval/12)**:
   `HumanEval/12` r1 Dafny pass → behavior fail → alignment_repair → r2 Dafny fail →
   diagnose → proof_repair → r3 Dafny fail. The alignment_repair broke a passing
   verification and the remaining budget was wasted re-fixing already-correct code.
   The task ended as a Dafny-FAIL rather than the honest verified-but-behavior-failed.

2. **Over-constrained spec not relaxable (RC2 — hit HumanEval/10)**:
   `HumanEval/10 make_palindrome`: spec forced `|result| == 2*|s| - 1` (worst-case full
   length), but the natural-language task demands the *shortest* palindrome. Code
   correctly implemented the wrong spec → Dafny pass, test fail. alignment_repair was
   instructed to "only strengthen" and could not fix the root cause.

3. **Empty test-failure diagnostics (RC3 — all behavior-fail cases)**:
   HumanEval `check()` uses bare `assert candidate(x)==y` with no message. The
   caught `AssertionError` was empty → behavior_error="测试断言失败: " — alignment_repair
   was repairing blind.

### Implementation

Three interdependent improvements deployed in one round:

**Imp-1 — alignment_repair verification guard + rollback** (`project/pipeline.py`):
- Added `last_verified_code`, `last_verified_spec`, `regression_rolled_back` to `PipelineState`.
- `verify_node` snapshots code+spec on every Dafny pass.
- `alignment_repair_agent` pre-verifies its output with `DafnyVerifier`; if verification
  fails, rolls back to `last_verified_code` and sets `regression_rolled_back=True`.
- `decide_after_behavior` ends the loop instead of retrying alignment when rolled back.

**Imp-2 — capture failing-test input/expected/actual** (`project/humaneval_tester.py`):
- Added `_run_asserts_with_diagnostics()`: parses `def check(candidate):` body via
  `ast.parse`, extracts individual `assert candidate(ARGS) == EXPECTED` statements,
  runs them one-by-one, and on first failure returns the failing input, expected, and
  actual value.
- Falls back to black-box `check(candidate)` execution for non-standard test formats.
- Replaces empty `"测试断言失败: "` error with e.g. `"输入=['xyx'] 期望='xyx' 实际='xyxyx'"`.

**Imp-3 — alignment_repair prompt for spec relaxation** (`project/spec_code_alignment.py`):
- Replaced the blanket "never delete ensures, only strengthen" rule with explicit
  two-case reasoning: (a) code semantics wrong → fix code; (b) spec over-constrained
  or wrong → correct the spec (delete/relax/replace the offending ensures).
- Added diagnostic-based inference rules to help the LLM distinguish cases.
- Added a vacuous-spec guard in `pipeline.py` that rejects alignment outputs whose
  spec does not constrain `result`.

### Validation

- `python -m compileall project test_benchmark.py`
- HumanEval/10 smoke test: behavior_error changed from `"测试断言失败: "` to
  `"输入=['xyx'] 期望='xyx' 实际='xyxyx'"` — diagnostic capture works.
- HumanEval/10 standalone run: alignment_repair relaxed `|result|==2|s|-1` to
  `|result|>=|s|`, and the task passed end-to-end.
- HumanEval/12 standalone run: alignment_repair regressed verification; the rollback
  guard preserved the verified state and ended as verified-but-behavior-failed instead
  of Dafny-fail.
- `USE_TEMPLATE_FALLBACK=0 python run_humaneval.py --start 0 --limit 20 --rounds 3`
- `python mutation_adequacy.py`
- `python analyze_results.py`

### Results Comparison

| Metric | 7/7 Baseline | Before (7/9) | After (7/9) | Δ |
|--------|--------------|-------------|-------------|-----|
| End-to-end passed | 7/20 (35%) | 5/20 (25%) | **6/20 (30%)** | +1 |
| Dafny verified | 9/20 (45%) | 6/20 (30%) | **8/20 (40%)** | +2 |
| HumanEval passed | 7/20 (35%) | 5/20 (25%) | **6/20 (30%)** | +1 |
| Verified-but-test-failed | 2/20 | 1/20 | 2/20 | +1 |
| Avg repair rounds | 2.25 | 2.53 | 2.50 | - |
| Avg spec adequacy score | 87.9 | 92.0 | 85.8 | - |
| Mutation high-risk / suspicious | 2 / 2 | 0 / 0 | 0 / 0 | - |

Notable per-task changes:
- `HumanEval/7 filter_by_substring`: recovered from FAIL to PASS.
- `HumanEval/12 longest`: improved from Dafny-FAIL to verified-but-behavior-failed
  (rollback guard preserved honest state instead of regressing).
- `HumanEval/17`: improved from FAIL to Dafny-verified (behavior-failed later).
- `HumanEval/10`: showed LLM variance — passed in standalone but failed in full run
  (prompt-driven spec relaxation is non-deterministic).

### Findings

- The three improvements are interdependent and work as designed: Imp-2 feeds
  diagnostics → Imp-3 reasons about spec vs code → Imp-1 guards regression.
- Dafny verification recovered from 6→8 (matching 7/7 baseline closely), confirming
  that proof_obligation_gap repair was not the bottleneck — the regression was partly
  noise and partly alignment_repair damaging verified code (fixed by Imp-1).
- HumanEval/10's performance variance across runs (standalone PASS vs full-run FAIL)
  confirms that the spec-relaxation prompt is a soft lever: the LLM does not
  consistently recognize over-constrained specs. A more structured approach
  (e.g., symbolic detection of over-constraints) may be needed.
- proof_repair remains the largest unsolved category: 8/14 failures remain
  proof_obligation_gap. Imp-4 (prompt hardening with invariant templates) is the
  natural next step.
- Average spec adequacy score dropped from 92.0 to 85.8 — caused by alignment_repair
  relaxing over-constrained specs (intended effect: correctness over static score).

### Next Steps

- Add Imp-4: proof_repair prompt enrichment with concrete invariant templates and
  few-shot loop-invariant examples (similar to code_agent's nested-loop section).
- Investigate structured detection of over-constrained specs (e.g., check if the spec
  forces a fixed-length equality on a task that needs `min`/`max` semantics).
- Add Imp-5: connection-error resilience in llm_client.py for transient API failures.
- Add a plausible-wrong mutant operator to mutation_probe to catch the "shapes-correct-
  but-semantics-wrong" blind spot identified in the research findings.

## 2026-07-13 - Trustworthy Evaluation Protocol and Monotonic Repair Hardening

### Motivation

The latest 20-task pure-LLM run reached 8/20 Dafny verification and 6/20
end-to-end success, but an audit showed that the score was not yet a reliable
measure of model generalization:

- task descriptions were truncated and could select a helper signature instead
  of the declared HumanEval entry point;
- the diagnostic runner executed only a subset of some official assertions;
- official HumanEval tests could enter the behavior-repair loop and then be
  reused for the final score;
- generic code/repair paths could drift from the generated public contract;
- a failed repair could replace a better earlier candidate;
- runs reused output files and did not fully record model usage or source/data
  identity.

This round prioritizes measurement validity and repair safety before attempting
to improve the raw pass rate.

### Implementation

**Structured task normalization** (`project/task_normalizer.py`):

- parses the exact `entry_point` with Python AST instead of choosing the first
  `def` in a prompt;
- preserves the complete prompt/docstring and extracts structured parameters,
  return types and examples without the previous 200-character truncation;
- renders a fixed Dafny signature and reports unsupported annotations explicitly
  rather than silently guessing.

**Isolated and complete behavior testing** (`project/humaneval_tester.py`):

- always runs the complete official `check(candidate)` as the decisive result;
- uses extracted flat assertions only to enrich failure diagnostics;
- runs translated code in a timeout-controlled subprocess and cleans temporary
  modules/paths;
- loads prompt-defined helpers and converts translated Dafny option values back
  to Python `None` / values.

**Strict/assisted protocol split** (`project/run_humaneval.py`):

- added `--mode strict` (default), where official tests run exactly once after
  search and never feed a repair Agent;
- added `--mode assisted --repair-tests <JSON/JSONL>` for separately curated
  development tests while keeping official tests as a holdout;
- records official and development test outcomes separately, including type
  coverage and contract-fidelity status;
- forces template fallback off in strict mode.

**Contract and repair safety** (`project/contract_utils.py`, `project/pipeline.py`):

- compares public `requires` / `ensures` structurally with parameter alpha-renaming
  across initial code generation, proof repair and generic repair;
- applies deterministic static checks and a Dafny resolve gate before accepting
  generated candidates;
- tracks the best verification state and rolls back non-improving failed repairs;
- preserves failure subtype/source metadata in research traces.

**Better proof diagnosis and repair** (`project/dafny_wrapper.py`,
`project/proof_patterns.py`, `project/proof_repair.py`, `project/repair_policy.py`):

- parses Dafny 4.11 diagnostic blocks using process return codes and captures
  primary/related locations;
- distinguishes invariant entry from invariant maintenance and routes repeated,
  bounds, termination, timeout and contract failures more deliberately;
- retrieves targeted prefix/fold, bounds, extremum and filter/count proof patterns;
- allows helper preconditions when call sites prove them, while forbidding new
  public preconditions that exclude valid task inputs.

**Reproducible runs** (`project/experiment_manifest.py`, `project/llm_client.py`,
`project/config.py`):

- creates a unique `logs/runs/<timestamp>_...` directory for every CLI run;
- stores Git SHA/dirty state, working-tree/data/prompt hashes, task selection,
  model parameters, pipeline flags, Dafny/Python/dependency versions and results;
- records per-request token usage, latency and errors, then aggregates them into
  the completed manifest;
- makes `strict`, deterministic-ish temperature settings and disabled template
  fallback the defaults.

**Tests and documentation**:

- added focused regression suites for task normalization, full HumanEval testing,
  Dafny diagnostics, public-contract fidelity, run manifests and protocol leakage;
- added `requirements-dev.txt` with pytest and rewrote setup/run documentation to
  keep strict, assisted and template-aided results distinct.

### Validation

- `python -m pytest tests -q`
- `python -m compileall -q project tests`
- offline canonical HumanEval translation/execution checks
- Dafny positive/negative wrapper smoke checks, including structured invariant
  diagnostics

A fresh model-backed strict benchmark is intentionally required before reporting
post-change pass rates. The 8/20 Dafny and 6/20 end-to-end figures remain the old
protocol baseline, not a result of this update.

### Next Steps

- run a one-task API smoke test followed by the fixed 20-task strict slice;
- compare first-pass language-error rate, direct repair success, repair regression,
  Dafny verification and end-to-end holdout success against the old baseline;
- use manifests and repeated seeds/runs when estimating LLM variance;
- continue improving proof templates and mutation adequacy only when the strict
  traces identify a measurable bottleneck.

## 2026-07-14 - Strict 20-Task Result: 55% End-to-End

### Outcome

Ran one fixed-working-tree HumanEval/0--19 experiment with:

- `--mode strict --start 0 --limit 20 --rounds 3`;
- official tests withheld until the search stopped;
- template fallback disabled;
- one unique run manifest at
  `logs/runs/20260714_094215_191679_humaneval_strict_0_20/`.

| Metric | 2026-07-09 baseline | 2026-07-14 strict | Change |
|---|---:|---:|---:|
| End-to-end | 6/20 (30%) | **11/20 (55%)** | +5 / +25 pp |
| Dafny verified | 8/20 (40%) | **14/20 (70%)** | +6 / +30 pp |
| First-round end-to-end | 4/20 (20%) | **10/20 (50%)** | +6 / +30 pp |
| First-round Dafny | 4/20 (20%) | **13/20 (65%)** | +9 / +45 pp |
| Average rounds | 2.50 | **1.70** | -0.80 |
| Total wall time | 1052.9 s | **838.0 s** | -214.9 s (-20.4%) |
| Contract-drift repair events | 7 | **0** | -7 |

The run covered 20/20 normalized tasks. It made 75 successful LLM calls with
120,438 prompt tokens, 37,834 completion tokens and 158,272 total tokens. LLM
latency summed to 349.613 seconds. Mutation adequacy classified 13 tasks `low`
risk and 7 `insufficient`; insufficient samples are no longer mislabeled low.

### Additional implementation fixes discovered by model-backed smoke tests

- Dafny 4.11 warning-only exits are now accepted with `--allow-warnings`; the
  previous wrapper mislabeled them as process failures.
- quantified contract variables are compared modulo alpha-renaming, while
  public contract semantic changes remain rejected.
- a frozen executable reference helper can directly construct the public method
  implementation, including multiple returns, avoiding duplicate loop proofs.
- valid pure function let-bindings (`var x := expr; body`) are no longer rejected
  by an unsound regex checker.
- bodyless runtime reference helpers are rejected, while ghost-only abstract
  helpers remain allowed.
- Python lists are converted to the Dafny Python runtime `Seq`, fixing recursive
  translated functions that need slicing/drop operations.
- Python parameter names that are Dafny keywords (for example `string`) are
  deterministically escaped in the fixed Dafny signature.
- invalid final specs are explicitly routed to spec repair even when their
  heuristic semantic score was high.
- executable reference specifications suppress redundant shape-only spec
  strengthening, which had changed correct prefix behavior.
- int/char conversion prompts now use resolver-confirmed `(x as char)` and
  `[(x as char)]` syntax.

### Repair audit and remaining failures

The fixed analyzer associates each repair only with its immediately following
verification. In the strict run, proof repair directly succeeded 0/3 times and
code repair 1/11 times. Across 14 evaluated repair calls there were 4 regressions
and 3 non-improvements; monotonic rollback prevented those candidates from
replacing better states. Repair remains substantially weaker than first-round
reference-helper generation.

Three programs verified but failed the official holdout (`HumanEval/3`, `/10`,
`/15`), exposing reference-helper semantic errors. Six more failed Dafny
verification (`/1`, `/6`, `/9`, `/13`, `/18`, `/19`), dominated by parser,
termination, precondition and complex recursive-proof obligations. These are
the next research targets; they were not hidden by weakening public contracts.

### Validation

- `python -B -m pytest tests -q -p no:cacheprovider`: 91 passed;
- `python -B -m compileall -q project tests`: passed;
- `git diff --check`: passed;
- strict manifest recorded 0 final public-contract fidelity failures.

The run manifest records `git.sha = c5ea15c...` with `dirty = true` and a
working-tree hash, because these changes were intentionally not committed by the
assistant. A publication artifact should commit the exact tree and repeat the
strict run across multiple seeds.
