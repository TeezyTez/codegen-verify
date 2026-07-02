# Project History

This file records important research and engineering updates. For each future
code change, append a short entry with the motivation, implementation summary,
and validation result.

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
