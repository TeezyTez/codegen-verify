# Phase 0 observed results

Date: 2026-08-25  
Model: DeepSeek V4 Pro, thinking disabled  
Dataset: 29-task native-supported HumanEval-to-Dafny subset  
Unit of analysis: task × replicate

## Outcome

Phase 0 is only partially complete. `direct_1` and `direct_verify` completed all
three replicates (87 task runs each). The original `spec_guided` condition failed
its five-task pilot at the specification gate and was stopped before scaling.
That pilot is protocol-diagnostic evidence, not an estimate of method quality.

| Condition | Runs | Hidden pass | Dafny verified | Verified-wrong | LLM calls | Tokens/task | Seconds/task |
|---|---:|---:|---:|---:|---:|---:|---:|
| `direct_1` | 87 | 22 (25.3%) | 22 | 0 | 87 | 795.2 | 8.55 |
| `direct_verify` | 87 | 24 (27.6%) | 25 | 1 | 284 | 5,011.7 | 30.98 |
| `spec_guided` pilot | 5 | 0 | 0 | 0 | 15 | 9,001.6 | 38.56 |

## Paired Direct-1 versus Direct+Verify result

- Both passed: 17
- Direct-1 only: 5
- Direct+Verify only: 7
- Both failed: 58
- Net gain: 2/87 task-runs, or 2.3 percentage points
- Exact paired McNemar p-value: 0.774414
- Token ratio: 6.302×
- Wall-time ratio: 3.623×
- Ten Direct+Verify passes occurred after round 1, but five paired Direct-1
  successes were also lost; repair success counts alone therefore overstate net benefit.

The observed +2 net passes are not reliable evidence of improvement at this
sample size. The current blind verifier-feedback loop is substantially more
expensive and produced one Dafny-verified implementation that failed the hidden
behavior test.

## Spec-Guided protocol failure

The frozen five-task pilot rejected every task before implementation. Diagnosis
identified four distinct infrastructure/protocol defects:

1. Signature, naming, and example requirements were incorrectly required to map
   to formal Dafny clauses.
2. Missing traceability metadata was treated as a semantic/structural failure.
3. Critic retries did not explain that real/integer JSON values must be unquoted.
4. The specification gate did not require a directly executable result
   definition even though downstream semantic probes require one.

These defects were repaired with regression tests. A subsequent real-task replay
progressed farther, but raw LLM Dafny generation still produced unstable type
casts and an illegal method call inside an `ensures` clause. The corrected
`spec_guided` implementation is therefore a new protocol version; mixing its
future results with the frozen pilot would invalidate the comparison.

## Decision

Phase 1 remains locked. Before rerunning Phase 0, the project should replace raw
LLM-to-Dafny contract generation with a typed specification IR plus deterministic
Dafny rendering/reference construction, or demonstrate an equivalent reliable
compiler boundary. Admission criteria for a new frozen run are:

1. All 29 public tasks produce a Dafny-resolving, directly executable reference
   specification in an offline/replay gate.
2. No task exits through audit protocol failure in a one-replicate smoke run.
3. Traceability incompleteness remains visible as risk evidence but cannot be
   confused with semantic invalidity.
4. The protocol is frozen at a clean commit with prompt/config hashes before any
   new holdout outcome is observed.

Machine-readable aggregates are in `phase0_observed_results.json` and per-run
rows are in `phase0_observed_results.csv`. Recreate them with:

```powershell
.venv\Scripts\python.exe project\analyze_experiment_matrix.py `
  logs\experiments\phase0_native_v2 `
  --json experiments\phase0_observed_results.json `
  --csv experiments\phase0_observed_results.csv
```
