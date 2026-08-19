"""Requirement analysis behind one fail-soft interface."""

from __future__ import annotations

from typing import Any, Mapping

from artifacts import AgentRequest, Requirement, RequirementAnalysis, VerificationCase
from model_output import parse_json_object, string_tuple


class RequirementAnalyzer:
    """Turn public task evidence into atomic, stable-ID requirements."""

    def __init__(self, model=None):
        self._model = model

    def analyze(self, request: AgentRequest) -> RequirementAnalysis:
        if self._model is None:
            return fallback_analysis(request)
        try:
            raw = self._model.chat(
                system=_SYSTEM_PROMPT,
                user=_user_prompt(request),
            )
            return _parse_analysis(parse_json_object(raw), request)
        except Exception as exc:
            fallback = fallback_analysis(request)
            return RequirementAnalysis(
                requirements=fallback.requirements,
                ambiguities=(*fallback.ambiguities, f"requirement analysis fallback: {type(exc).__name__}"),
                edge_cases=fallback.edge_cases,
                verification_cases=fallback.verification_cases,
                confidence=min(fallback.confidence, 0.35),
            )


def fallback_analysis(request: AgentRequest) -> RequirementAnalysis:
    requirement = Requirement(
        id="REQ-001",
        description=request.problem_desc.strip() or f"Implement {request.entry_point}.",
        kind="functional",
        ambiguity=0.5,
    )
    cases = _public_cases(request.task_ir, (requirement.id,))
    return RequirementAnalysis(
        requirements=(requirement,),
        verification_cases=cases,
        confidence=0.4,
    )


def _parse_analysis(data: Mapping[str, Any], request: AgentRequest) -> RequirementAnalysis:
    raw_requirements = data.get("requirements")
    if not isinstance(raw_requirements, list) or not raw_requirements:
        raise ValueError("requirements must be a non-empty list")
    requirements: list[Requirement] = []
    for index, item in enumerate(raw_requirements, start=1):
        if not isinstance(item, Mapping):
            raise ValueError("each requirement must be an object")
        description = str(item.get("description") or item.get("content") or "").strip()
        if not description:
            raise ValueError("requirement description is empty")
        requirements.append(Requirement(
            id=f"REQ-{index:03d}",
            description=description,
            kind=str(item.get("kind") or item.get("type") or "functional"),
            source=str(item.get("source") or "user"),
            priority=str(item.get("priority") or "must"),
            ambiguity=_probability(item.get("ambiguity"), 0.0),
        ))
    requirement_ids = tuple(item.id for item in requirements)
    public_cases = _public_cases(request.task_ir, requirement_ids)
    generated_cases: list[VerificationCase] = []
    raw_cases = data.get("verification_cases") or data.get("examples") or []
    if isinstance(raw_cases, list):
        for index, item in enumerate(raw_cases, start=len(public_cases) + 1):
            if not isinstance(item, Mapping):
                continue
            description = str(item.get("description") or "").strip()
            if not description:
                continue
            related = tuple(
                value for value in string_tuple(item.get("related_requirements"))
                if value in requirement_ids
            ) or requirement_ids
            generated_cases.append(VerificationCase(
                id=f"TEST-{index:03d}",
                kind=str(item.get("kind") or "boundary"),
                description=description,
                related_requirements=related,
                data=dict(item.get("data") or {}),
            ))
    return RequirementAnalysis(
        requirements=tuple(requirements),
        ambiguities=string_tuple(data.get("ambiguities")),
        edge_cases=string_tuple(data.get("edge_cases")),
        verification_cases=(*public_cases, *generated_cases),
        confidence=_probability(data.get("confidence"), 0.7),
    )


def _public_cases(task_ir: Mapping[str, Any], requirement_ids: tuple[str, ...]) -> tuple[VerificationCase, ...]:
    examples = task_ir.get("examples", []) if isinstance(task_ir, Mapping) else []
    cases: list[VerificationCase] = []
    if isinstance(examples, (list, tuple)):
        for index, item in enumerate(examples, start=1):
            if not isinstance(item, Mapping):
                continue
            source = str(item.get("source") or "").strip()
            expected = item.get("expected_value", item.get("expected_text"))
            cases.append(VerificationCase(
                id=f"TEST-{index:03d}",
                kind="public_example",
                description=f"{source} -> {expected!r}",
                related_requirements=requirement_ids,
                data={"source": source, "expected": expected},
            ))
    return tuple(cases)


def _probability(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _user_prompt(request: AgentRequest) -> str:
    return f"""Task ID: {request.problem_id}
Entry point: {request.entry_point}
Public requirement and examples:
{request.problem_desc}

Return JSON with: requirements, ambiguities, edge_cases, verification_cases, confidence.
Each requirement must be atomic, sourced only from the public task, and include description,
kind, priority, and ambiguity. Do not invent behavior or implementation details. Do not emit code."""


_SYSTEM_PROMPT = """You are the Requirement Agent in a specification-guided coding system.
Decompose public user intent into atomic requirements and observable edge cases. Preserve the full
legal input domain, distinguish ambiguity from facts, and return only a JSON object."""
