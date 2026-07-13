"""
Repair policy for the spec-aware coding agent harness.

The policy layer turns verifier feedback and spec adequacy signals into an
explicit repair action. Keeping this logic outside prompt text makes the harness
easier to analyze and compare in experiments.
"""
from dataclasses import dataclass
from typing import Any

from dafny_wrapper import VerificationResult


@dataclass(frozen=True)
class RepairDecision:
    target: str
    agent: str
    confidence: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "agent": self.agent,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


def choose_repair_policy(
    verification: VerificationResult,
    attribution: dict[str, Any],
    spec_adequacy: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> RepairDecision:
    """Choose which specialized repair agent should handle the next step."""
    if verification.passed:
        return RepairDecision(
            target="none",
            agent="none",
            confidence=1.0,
            rationale="Verification passed; no repair is needed.",
        )

    history = history or []
    error_types = [error.error_type for error in verification.errors]
    error_subtypes = [getattr(error, "subtype", "") for error in verification.errors]
    category = attribution.get("category", "")
    adequacy_flags = set(spec_adequacy.get("flags") or [])

    if any(error in {"syntax", "type", "undefined", "assignment", "contract"} for error in error_types):
        return RepairDecision(
            target="code",
            agent="code_repair_agent",
            confidence=0.9,
            rationale="Verifier reported language/type/name errors that require implementation-level repair.",
        )

    if "timeout" in error_types:
        return RepairDecision(
            target="strategy_shift",
            agent="code_repair_agent",
            confidence=0.9,
            rationale="Verification timed out; roll back proof growth and choose a simpler algorithm/proof structure.",
        )

    # This check must precede invariant routing; otherwise repeated invariant
    # failures are routed to the same proof prompt forever.
    if _same_error_repeated(history):
        return RepairDecision(
            target="strategy_shift",
            agent="code_repair_agent",
            confidence=0.8,
            rationale="The same verification obligation repeated without improvement; switch implementation/proof strategy.",
        )

    if "out_of_range" in error_types or "termination" in error_subtypes:
        return RepairDecision(
            target="proof",
            agent="proof_repair_agent",
            confidence=0.85,
            rationale="The failure needs a domain bound, call-site proof, total helper, or decreases argument.",
        )

    if any(error in {"invariant", "postcondition", "precondition", "other"} for error in error_types):
        if category in {"proof_obligation_gap", "loop_proof_gap"} or "invariant" in error_types:
            return RepairDecision(
                target="proof",
                agent="proof_repair_agent",
                confidence=0.85,
                rationale="The failure is dominated by proof obligations; add invariants, assertions, lemmas, or decreases clauses.",
            )

    if category == "spec_or_code_mismatch" or adequacy_flags & {
        "verified_but_behavior_failed",
        "no_postcondition",
        "postcondition_does_not_constrain_result",
        "postcondition_ignores_inputs",
    }:
        return RepairDecision(
            target="code_or_spec",
            agent="code_repair_agent",
            confidence=0.6,
            rationale="Spec adequacy or postcondition mismatch is suspicious; current harness keeps in-loop repair on code while recording the spec risk.",
        )

    return RepairDecision(
        target="code",
        agent="code_repair_agent",
        confidence=0.45,
        rationale="No specialized policy matched; fall back to general code repair.",
    )


def _same_error_repeated(history: list[dict[str, Any]]) -> bool:
    seen: dict[tuple[str, int], int] = {}
    for item in history:
        for error in item.get("errors", []):
            key = (error.get("type", ""), int(error.get("loc", 0) or 0))
            seen[key] = seen.get(key, 0) + 1
            if seen[key] >= 2:
                return True
    return False
