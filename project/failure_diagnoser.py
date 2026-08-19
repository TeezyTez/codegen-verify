"""Failure attribution and localization for targeted repair."""

from __future__ import annotations

import json

from artifacts import AgentRequest, FailureDiagnosis, ProgramPlan, SpecArtifact, VerificationEvidence
from model_output import parse_json_object, string_tuple


FAILURE_TYPES = {"SPEC_ERROR", "CODE_ERROR", "PROOF_ERROR", "TEST_ERROR", "ENV_ERROR", "UNKNOWN"}


class FailureDiagnoser:
    """Classify one failure and reduce repair context to related clauses and code."""

    def __init__(self, model=None):
        self._model = model

    def diagnose(
        self,
        *,
        request: AgentRequest,
        spec: SpecArtifact,
        plan: ProgramPlan,
        code: str,
        evidence: VerificationEvidence,
    ) -> FailureDiagnosis:
        fallback = _deterministic_diagnosis(spec, code, evidence)
        if self._model is None or fallback.category in {"CODE_ERROR", "ENV_ERROR"}:
            return fallback
        try:
            data = parse_json_object(self._model.chat(
                system=_SYSTEM_PROMPT,
                user=_user_prompt(request, spec, plan, fallback, evidence),
            ))
            category = str(data.get("category") or "UNKNOWN").upper()
            if category not in FAILURE_TYPES:
                category = "UNKNOWN"
            # A verifier failure proves only that code/proof does not satisfy
            # the current spec. Reopening the spec requires independent
            # behavioral evidence, never a model label alone.
            if category == "SPEC_ERROR" and not evidence.counterexample:
                category = "UNKNOWN"
            known_clauses = {item.id for item in spec.structured.clauses} if spec.structured else set()
            violated = tuple(item for item in string_tuple(data.get("violated_spec_ids")) if item in known_clauses)
            if not violated:
                violated = fallback.violated_spec_ids
            related = _related_requirements(spec, violated)
            return FailureDiagnosis(
                category=category,
                summary=str(data.get("summary") or fallback.summary),
                violated_spec_ids=violated,
                related_requirement_ids=related,
                relevant_code=fallback.relevant_code,
                repair_goal=str(data.get("repair_goal") or fallback.repair_goal),
                evidence=fallback.evidence,
                confidence=_probability(data.get("confidence"), 0.65),
            )
        except Exception:
            return fallback


def spec_failure_diagnosis(spec: SpecArtifact, detail: str) -> FailureDiagnosis:
    clause_ids = tuple(item.id for item in spec.structured.clauses) if spec.structured else ()
    return FailureDiagnosis(
        category="SPEC_ERROR",
        summary="Independent development evidence disproved the approved spec/candidate.",
        violated_spec_ids=clause_ids,
        related_requirement_ids=_related_requirements(spec, clause_ids),
        repair_goal="Correct the specification with explicit evidence, then rerun every spec validation gate.",
        evidence={"development_error": detail},
        confidence=0.8,
    )


def _deterministic_diagnosis(
    spec: SpecArtifact,
    code: str,
    evidence: VerificationEvidence,
) -> FailureDiagnosis:
    error_types = {
        (error.subtype or error.error_type or "other") for error in evidence.result.errors
    }
    if evidence.contract_issues or evidence.reference_collapse:
        category = "CODE_ERROR"
        goal = "Restore the frozen contract and implement the algorithm without reference collapse."
    elif error_types & {"syntax", "type", "undefined", "assignment", "out_of_range"}:
        category = "CODE_ERROR"
        goal = "Correct the localized implementation error while preserving every frozen clause."
    elif error_types & {"timeout", "process_error"}:
        category = "ENV_ERROR"
        goal = "Resolve verifier availability or resource limits before changing the specification."
    elif error_types & {"invariant", "invariant_entry", "invariant_maintenance", "termination", "precondition"}:
        category = "PROOF_ERROR"
        goal = "Strengthen invariants, decreases clauses, assertions, or lemmas without weakening behavior."
    elif "postcondition" in error_types:
        category = "UNKNOWN"
        goal = "Determine whether the algorithm or proof is responsible, then repair only that scope."
    else:
        category = "UNKNOWN"
        goal = "Use the structured evidence to localize the failure before editing code or specification."
    violated = evidence.violated_spec_ids
    if not violated and spec.structured and category != "ENV_ERROR":
        violated = tuple(item.id for item in spec.structured.clauses)
    location = next((error.location_line for error in evidence.result.errors if error.location_line), 0)
    relevant_code = _code_window(code, location)
    return FailureDiagnosis(
        category=category,
        summary="; ".join(
            error.message or error.subtype or error.error_type for error in evidence.result.errors
        ) or "Verification failed without structured diagnostics.",
        violated_spec_ids=violated,
        related_requirement_ids=_related_requirements(spec, violated),
        relevant_code=relevant_code,
        repair_goal=goal,
        evidence={"stage": evidence.stage, "error_types": sorted(error_types)},
        confidence=0.75 if category != "UNKNOWN" else 0.4,
    )


def _related_requirements(spec: SpecArtifact, clause_ids: tuple[str, ...]) -> tuple[str, ...]:
    if not spec.structured:
        return ()
    values = {
        requirement_id
        for clause in spec.structured.clauses
        if clause.id in clause_ids
        for requirement_id in clause.related_requirements
    }
    return tuple(sorted(values))


def _code_window(code: str, line: int, radius: int = 4) -> str:
    lines = (code or "").splitlines()
    if not lines:
        return ""
    if line <= 0:
        return "\n".join(f"{index + 1}: {value}" for index, value in enumerate(lines[:12]))
    start, end = max(0, line - radius - 1), min(len(lines), line + radius)
    return "\n".join(f"{index + 1}: {lines[index]}" for index in range(start, end))


def _probability(value, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _user_prompt(
    request: AgentRequest,
    spec: SpecArtifact,
    plan: ProgramPlan,
    fallback: FailureDiagnosis,
    evidence: VerificationEvidence,
) -> str:
    return f"""Task: {request.problem_desc}
Frozen clauses: {json.dumps(spec.structured.to_dict() if spec.structured else {}, ensure_ascii=False)}
Plan: {json.dumps(plan.to_dict(), ensure_ascii=False)}
Verifier evidence: {json.dumps(evidence.to_dict(), ensure_ascii=False, default=str)}
Localized code:
{fallback.relevant_code}

Return JSON with category, summary, violated_spec_ids, repair_goal, confidence.
category must be SPEC_ERROR, CODE_ERROR, PROOF_ERROR, TEST_ERROR, ENV_ERROR, or UNKNOWN.
Choose SPEC_ERROR only when the supplied independent counterexample contradicts the formal spec;
a Dafny failure by itself is not evidence that the specification is wrong.
Do not recommend weakening or deleting a clause merely to satisfy the verifier."""


_SYSTEM_PROMPT = """You are the Failure Diagnoser in a specification-guided coding agent.
Attribute failures using only the supplied requirements, clauses, plan, localized code, and
structured evidence. Separate semantic code errors from proof-hint errors and infrastructure
errors. Return only a JSON object."""
