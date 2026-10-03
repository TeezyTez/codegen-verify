# Exploratory challenge set, 2026-09-20

Three original CC0-1.0 synthetic_demo **development** tasks. They are deliberately separate
from the five original demos and are not a held-out benchmark. All three representation
equivalence audits are pending; mechanical clause coverage is not semantic review.

| Task | Requirement | Intended stress |
|---|---|---|
| binary_lower_bound | Partition sorted sequence around a key | Quantified loop invariants, empty input, duplicate keys |
| integer_sqrt | Nonnegative floor square root | Nonlinear arithmetic, termination |
| sequence_reverse | Same length, reversed element positions | Sequence construction and quantified invariants |

The name binary_lower_bound does not impose a binary-search or complexity requirement:
any terminating implementation satisfying the frozen functional contract is accepted.
References and negative controls use the unchanged pure body syntax profile; no extra
declarations, axioms or verifier flags are needed. They are never sent to the model.
Finite witnesses are metadata, not substitutes for formal verification and not executed
by this formal-only protocol. Sequence displays/concatenation are admitted by the current
expression grammar; the unchanged common prompt mentions sequence indexing/length but
does not exhaustively enumerate every supported expression (a prompt-clarity limitation).

## Plan fixed before the first challenge API request

- Model: deepseek-flash, thinking disabled, temperature 0.2; same public input/feedback protocol.
- Primary batch: 3 tasks × 3 fresh runs, natural + iterative_repair only.
- Each run: at most 4 model calls, 5 verifier calls (including final recheck), 4096 output
  tokens/request, 48000 accounted tokens, 15 seconds/check, 180 seconds/run, $0.05 cost reservation.
- Batch upper bounds: 36 API calls, 45 online verifier calls, $0.45 local cost reservations.
  Admission is local and separately accounted. Prices are estimates, not billing receipts.
- Keep all nine runs even if early results are easy or disappointing. No answer corruption,
  reference leakage, hidden extra requirements, post-result contract edits or retry-until-success selection.
- If all nine first candidates pass, record that result before creating a separately labeled
  harder exploratory batch. Do not silently replace the first batch.
- Observe first failures, exact feedback, repairs and persistent failures. No causal claim
  about feedback without an equal-budget independent-sampling comparison. Repeats are not nine tasks.
- Provider does not accept seed in this profile: run indices do not make generation deterministic.

## Run (requires explicit authorization for paid calls)

```sh
.venv/bin/python -m generation.representation.cli validate --tasks generation/representation/challenge_tasks --output /tmp/challenge-admission
.venv/bin/python -m generation.representation.cli matrix --tasks generation/representation/challenge_tasks --config generation/representation/configs/deepseek-challenge.json --allow-paid --output /tmp/challenge-live
.venv/bin/python scripts/check_representation_artifacts.py /tmp/challenge-live
```

Use fresh output paths. Existing runs must not be overwritten. Official language reference:
[Dafny 4.11, §5.5.3 sequences and §8.15 loop specifications](https://dafny.org/v4.11.0/DafnyRef/DafnyRef).
