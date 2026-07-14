"""Small reusable proof-pattern retrieval for Dafny repair prompts.

These are generic proof obligations, not task-id templates.  They give the LLM
the missing bridge shape while leaving the algorithm and concrete predicate to
the candidate program.
"""

from __future__ import annotations

from typing import Any


def select_proof_patterns(
    problem_desc: str,
    spec: str,
    verification_errors: list[dict[str, Any]],
) -> str:
    text = f"{problem_desc}\n{spec}".lower()
    types = {str(error.get("type", "")) for error in verification_errors}
    subtypes = {str(error.get("subtype", "")) for error in verification_errors}
    patterns: list[str] = []

    if types & {"invariant", "postcondition"} and any(
        token in text for token in ("sum", "product", "average", "mean", "fold", "prefix")
    ):
        patterns.append(
            """Fold/prefix bridge:
- Before updating an accumulator at index i, establish the slice identity
  `xs[..i+1] == xs[..i] + [xs[i]]`.
- Use/prove a generic append lemma such as the following concrete shape:
  `lemma FoldAppend(xs: seq<int>, x: int)`
  `  ensures Fold(xs + [x]) == Fold(xs) + x`
  `  decreases |xs|`
  `{ if |xs| > 0 { FoldAppend(xs[1..], x); } }`
- The loop invariant should be exactly `acc == F(xs[..i])`; invoke the lemma
  before assigning acc and incrementing i.
- If an early return witnesses an existential prefix property, assert the
  updated accumulator/prefix equality first, then use the current index as the
  witness before returning."""
        )

    if "out_of_range" in types:
        patterns.append(
            """Index-domain repair:
- Every helper access `s[i]` needs a fact `0 <= i < |s|`.
- Either make the helper total by handling invalid/empty cases, or add the
  minimal helper `requires` and prove it at every call site.
- A helper precondition is allowed when all calls establish it; do not hide the
  problem by strengthening the public method precondition."""
        )

    if "invariant_entry" in subtypes:
        patterns.append(
            """Invariant-entry repair:
- An invariant that is false before the first iteration must be weakened or
  replaced; adding more conjuncts cannot fix an entry failure.
- Describe the property of the processed prefix/current partial output, not the
  final postcondition if that property only becomes true after the loop."""
        )

    if "invariant_maintenance" in subtypes or "invariant" in types:
        patterns.append(
            """Invariant-maintenance repair:
- Identify the single assignment that invalidates the invariant.
- Add a bridge assertion immediately before that assignment and preserve facts
  about unchanged state explicitly.
- Distinguish initialization, maintenance, and loop-exit obligations."""
        )

    if types & {"invariant", "postcondition", "out_of_range"} and any(
        token in text for token in ("seq<", "sequence", "list", "result[")
    ):
        patterns.append(
            """Processed-prefix sequence construction:
- Prefer growing `result` with concatenation over allocating a fixed sequence
  and updating `result[index := value]`; append construction avoids index
  bounds and gives a direct length invariant.
- Maintain exact shape for the processed prefix: result length plus quantified
  even/odd (or source/emitted) positions for all indices `< i`.
- Immediately before incrementing i, assert the newly appended positions and
  the new length. At loop exit, instantiate the invariant into each ensures.
- Do not strengthen the public precondition to avoid empty/singleton inputs;
  handle those branches explicitly."""
        )

    if any(token in text for token in ("maximum", "rolling_max", "longest", "minimum")):
        patterns.append(
            """Extremum scan:
- Maintain that the current candidate is drawn from the processed prefix.
- Maintain a quantified bound over every processed element.
- When a recursive reference helper indexes the sequence, give it a proven
  non-empty/index domain or define an empty base case."""
        )

    if any(token in text for token in ("filter", "substring", "distinct", "count")):
        patterns.append(
            """Filter/count correspondence:
- Track both directions: every emitted/seen element comes from the processed
  prefix, and every qualifying processed element is represented.
- For an inner membership search, bridge its exit invariant before updating the
  outer accumulator."""
        )

    if not patterns:
        return "(no specialized pattern matched; use the exact verifier obligation)"
    return "\n\n".join(patterns)
