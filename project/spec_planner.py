"""Spec-guided program planning behind one interface."""

from __future__ import annotations

import json

from artifacts import AgentRequest, ProgramPlan, SpecArtifact
from model_output import parse_json_object, string_tuple


class SpecGuidedPlanner:
    """Map each approved clause to an implementation and verification strategy."""

    def __init__(self, model=None):
        self._model = model

    def plan(self, request: AgentRequest, spec: SpecArtifact) -> ProgramPlan:
        if self._model is None:
            return fallback_plan(spec)
        try:
            data = parse_json_object(self._model.chat(
                system=_SYSTEM_PROMPT,
                user=_user_prompt(request, spec),
            ))
            mapping = data.get("clause_mapping")
            if not isinstance(mapping, dict):
                mapping = {}
            known = {item.id for item in spec.structured.clauses} if spec.structured else set()
            clean_mapping = {
                str(key): str(value).strip()
                for key, value in mapping.items()
                if str(value).strip() and (not known or str(key) in known)
            }
            algorithm = str(data.get("algorithm") or "").strip()
            if not algorithm:
                raise ValueError("planner omitted algorithm")
            for clause_id in known:
                clean_mapping.setdefault(clause_id, "Satisfy this clause directly and verify it with Dafny.")
            return ProgramPlan(
                algorithm=algorithm,
                reasoning_constraints=string_tuple(data.get("reasoning_constraints")),
                state_variables=string_tuple(data.get("state_variables")),
                invariants=string_tuple(data.get("invariants")),
                edge_case_strategy=string_tuple(data.get("edge_case_strategy")),
                verification_strategy=string_tuple(data.get("verification_strategy")),
                clause_mapping=clean_mapping,
                confidence=_probability(data.get("confidence"), 0.7),
            )
        except Exception:
            return fallback_plan(spec)


def fallback_plan(spec: SpecArtifact) -> ProgramPlan:
    clauses = spec.structured.clauses if spec.structured else ()
    edge_cases = spec.structured.edge_cases if spec.structured else ()
    return ProgramPlan(
        algorithm="Use the simplest independent algorithm that satisfies every frozen clause.",
        reasoning_constraints=tuple(
            f"{item.id}: {item.formal_expression or item.natural_language}" for item in clauses
        ),
        edge_case_strategy=tuple(edge_cases),
        verification_strategy=("Preserve the public contract and discharge every Dafny obligation.",),
        clause_mapping={
            item.id: "Implement this obligation explicitly; do not call a reference helper as the solution."
            for item in clauses
        },
        confidence=0.35,
    )


def _probability(value, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _user_prompt(request: AgentRequest, spec: SpecArtifact) -> str:
    structured = spec.structured.to_dict() if spec.structured else {}
    return f"""Task: {request.problem_desc}
Entry point: {request.entry_point}
Structured specification:
{json.dumps(structured, ensure_ascii=False, indent=2)}

Frozen Dafny specification:
{spec.text}

Return JSON with algorithm, reasoning_constraints, state_variables, invariants,
edge_case_strategy, verification_strategy, clause_mapping, confidence. clause_mapping must
explain how every SPEC ID will be satisfied. Compare correctness, proof difficulty,
implementation risk, and complexity. Do not emit implementation code."""


_SYSTEM_PROMPT = """You are the Planning Agent. Convert an approved structured specification
into a concrete, proof-friendly program plan. Every important decision must be indexed by a SPEC
clause. Prefer simple algorithms with strong loop invariants. Return only a JSON object."""
