"""
Research-oriented tracing and lightweight attribution utilities.

This module keeps the pipeline observable without changing its core strategy.
The trace is deliberately JSON-friendly so benchmark runs can be analyzed
offline for paper experiments and ablations.
"""
import re
from collections import Counter
from typing import Any

from dafny_wrapper import VerificationResult
from spec_adequacy import check_spec_adequacy


def spec_metrics(spec: str) -> dict[str, Any]:
    """Return simple static features that approximate specification strength."""
    lines = [line.strip() for line in (spec or "").splitlines() if line.strip()]
    ensures = [line for line in lines if line.startswith("ensures")]
    requires = [line for line in lines if line.startswith("requires")]
    helpers = [
        line for line in lines
        if re.match(r"^(function|predicate|lemma)\b", line)
    ]

    body_markers = 0
    for line in lines:
        if line == "{" or re.search(r"\bmethod\b.*\{", line):
            body_markers += 1

    semantic_terms = [
        "forall", "exists", "==>", "&&", "||", "result", "old(",
        "|", "[", "]", "<=", ">=", "=="
    ]
    semantic_hits = {term: spec.count(term) for term in semantic_terms if term in spec}

    return {
        "line_count": len(lines),
        "requires_count": len(requires),
        "ensures_count": len(ensures),
        "helper_count": len(helpers),
        "quantifier_count": spec.count("forall") + spec.count("exists"),
        "mentions_result": "result" in spec,
        "body_marker_count": body_markers,
        "semantic_hits": semantic_hits,
        "weak_spec_flags": _weak_spec_flags(ensures),
    }


def spec_adequacy_snapshot(
    spec: str,
    problem_desc: str = "",
    entry_point: str = "",
    dafny_verified: bool | None = None,
    humaneval_passed: bool | None = None,
) -> dict[str, Any]:
    return check_spec_adequacy(
        spec=spec,
        problem_desc=problem_desc,
        entry_point=entry_point,
        dafny_verified=dafny_verified,
        humaneval_passed=humaneval_passed,
    )


def _weak_spec_flags(ensures: list[str]) -> list[str]:
    flags = []
    if not ensures:
        flags.append("no_ensures")
    if ensures and not any("result" in line for line in ensures):
        flags.append("ensures_without_result")
    trivial_patterns = [
        r"ensures\s+true\b",
        r"ensures\s+result\s*==\s*result\b",
        r"ensures\s+0\s*<=\s*\|?result",
    ]
    for line in ensures:
        if any(re.search(pattern, line) for pattern in trivial_patterns):
            flags.append("possibly_trivial_ensures")
            break
    if len(ensures) <= 1:
        flags.append("low_ensures_count")
    return sorted(set(flags))


def verification_snapshot(result: VerificationResult) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "verified_count": result.verified_count,
        "error_count": result.error_count,
        "errors": [
            {
                "type": error.error_type,
                "line": error.location_line,
                "col": error.location_col,
                "message": error.message,
                "related_spec": error.related_spec,
            }
            for error in result.errors
        ],
    }


def attribute_failure(result: VerificationResult, spec: str, code: str) -> dict[str, Any]:
    """Map verifier feedback to a repair target for later analysis."""
    if result.passed:
        return {
            "category": "verified",
            "repair_target": "none",
            "confidence": 1.0,
            "rationale": "Dafny verification passed.",
        }

    error_types = Counter(error.error_type for error in result.errors)
    spec_info = spec_metrics(spec)
    code_lower = (code or "").lower()

    if error_types["syntax"] or error_types["type"] or error_types["undefined"]:
        return {
            "category": "implementation_language_error",
            "repair_target": "code",
            "confidence": 0.85,
            "rationale": "Verifier reported syntax/type/name errors, usually caused by invalid Dafny code.",
            "error_type_counts": dict(error_types),
        }

    if error_types["invariant"]:
        return {
            "category": "proof_obligation_gap",
            "repair_target": "invariant_or_assertion",
            "confidence": 0.8,
            "rationale": "Loop invariant errors usually need stronger invariants, bridge assertions, or proof hints.",
            "error_type_counts": dict(error_types),
        }

    if error_types["postcondition"]:
        target = "code"
        category = "implementation_semantics_mismatch"
        rationale = "Postcondition failure indicates the implementation does not establish the current spec."
        if spec_info["weak_spec_flags"]:
            category = "spec_or_code_mismatch"
            target = "code_or_spec"
            rationale = "Postcondition failure plus weak-spec flags suggests checking both implementation and spec adequacy."
        return {
            "category": category,
            "repair_target": target,
            "confidence": 0.65,
            "rationale": rationale,
            "error_type_counts": dict(error_types),
            "weak_spec_flags": spec_info["weak_spec_flags"],
        }

    if "requires" in spec and "precondition" in error_types:
        return {
            "category": "spec_precondition_too_strong_or_unproven",
            "repair_target": "spec_or_callsite",
            "confidence": 0.7,
            "rationale": "Precondition errors can mean an over-strong helper spec or a missing caller proof.",
            "error_type_counts": dict(error_types),
        }

    if "while" in code_lower and result.error_count > 0:
        return {
            "category": "loop_proof_gap",
            "repair_target": "invariant_or_assertion",
            "confidence": 0.55,
            "rationale": "The failing code contains loops and unresolved verification errors.",
            "error_type_counts": dict(error_types),
        }

    return {
        "category": "unclassified_verification_failure",
        "repair_target": "inspect",
        "confidence": 0.35,
        "rationale": "The current parser could not confidently map the verifier feedback.",
        "error_type_counts": dict(error_types),
    }


def trace_event(stage: str, round_id: int, **payload: Any) -> dict[str, Any]:
    return {
        "stage": stage,
        "round": round_id,
        **payload,
    }


def append_trace(state: dict[str, Any], event: dict[str, Any]) -> list[dict[str, Any]]:
    trace = list(state.get("research_trace", []))
    trace.append(event)
    return trace
