"""Structured specification synthesis and approval behind a fail-closed interface."""

from __future__ import annotations

from dataclasses import replace
import json
import re
from typing import Any, Mapping

import config
from artifacts import (
    AgentRequest,
    RequirementAnalysis,
    SpecArtifact,
    SpecClause,
    StructuredSpecification,
    stable_hash,
)
from contract_utils import bodyless_callable_names
from model_output import parse_json_object
from mutation_probe import probe_spec_mutants
from requirement_analyzer import fallback_analysis
from spec_adequacy import check_spec_adequacy
from spec_critic import critic_feedback_obligations, review_spec_with_llm
from task_normalizer import render_dafny_signature


class SpecAuthority:
    """Produce a versioned structured/formal spec only when all evidence approves it."""

    def __init__(
        self,
        *,
        spec_model,
        critic_model,
        probe_model,
        verifier,
        max_repairs: int = 1,
        critic=review_spec_with_llm,
        mutation_probe=probe_spec_mutants,
    ):
        self._spec_model = spec_model
        self._critic_model = critic_model
        self._probe_model = probe_model
        self._verifier = verifier
        self._max_repairs = max(0, max_repairs)
        self._critic = critic
        self._mutation_probe = mutation_probe

    def assess(
        self,
        *,
        problem_id: str,
        problem_desc: str,
        entry_point: str,
        task_ir: Mapping[str, Any],
        analysis: RequirementAnalysis | None = None,
        feedback: str = "",
        revision_evidence: Mapping[str, Any] | None = None,
        previous: SpecArtifact | None = None,
    ) -> SpecArtifact:
        if analysis is None:
            analysis = fallback_analysis(AgentRequest(
                problem_id=problem_id,
                problem_desc=problem_desc,
                entry_point=entry_point,
                task_ir=task_ir,
            ))
        task_hash = stable_hash({
            "problem_id": problem_id,
            "description": problem_desc,
            "task_ir": task_ir,
            "requirements": analysis.to_dict(),
        })
        version = (previous.version + 1) if previous else 1
        prior_text = previous.text if previous else ""
        last_issues = [feedback] if feedback else []

        for attempt in range(self._max_repairs + 1):
            candidate, proposed_clauses = self._generate(
                problem_desc=problem_desc,
                task_ir=task_ir,
                analysis=analysis,
                previous_spec=prior_text,
                issues=last_issues,
            )
            structured = _build_structured_spec(
                problem_id, analysis, candidate, proposed_clauses
            )
            drift = _spec_drift(previous, structured, feedback, revision_evidence)
            structural_issues = list(self._validate(candidate, entry_point))
            structural_issues.extend(_cross_level_issues(candidate, structured))
            if drift.get("unjustified"):
                structural_issues.append("approved spec changed without revision evidence")
            adequacy = check_spec_adequacy(candidate, problem_desc, entry_point=entry_point)

            def artifact(
                decision: str,
                *,
                issues: tuple[str, ...] = (),
                mutation: Mapping[str, Any] | None = None,
                critic_report: Mapping[str, Any] | None = None,
            ) -> SpecArtifact:
                final_structured = _with_clause_status(
                    structured, "validated" if decision == "approve" else "rejected"
                )
                return SpecArtifact(
                    text=candidate,
                    version=version,
                    task_hash=task_hash,
                    decision=decision,
                    validation_attempts=attempt + 1,
                    critic_report=critic_report or {},
                    adequacy=adequacy,
                    mutation=mutation or {},
                    structured=final_structured,
                    drift_report=drift,
                    issues=issues,
                )

            if structural_issues:
                if attempt < self._max_repairs:
                    prior_text, last_issues = candidate, structural_issues
                    continue
                return artifact("reject", issues=tuple(structural_issues))

            mutation: dict[str, Any] = {}
            if config.ENABLE_MUTATION_GUARD:
                try:
                    mutation = self._mutation_probe(candidate, verifier=self._verifier)
                except Exception as exc:
                    return artifact(
                        "abstain",
                        mutation={"error": f"{type(exc).__name__}: {exc}"},
                        issues=("mutation evidence unavailable",),
                    )
                if int(mutation.get("mutants_verified", 0)) > 0:
                    issue = "spec permits generated wrong implementations"
                    if attempt < self._max_repairs:
                        prior_text, last_issues = candidate, [issue]
                        continue
                    return artifact("reject", mutation=mutation, issues=(issue,))

            if not config.ENABLE_SPEC_CRITIC:
                return artifact("approve", mutation=mutation)

            try:
                report = self._critic(
                    self._critic_model,
                    problem_desc=_critic_problem(problem_desc, analysis),
                    spec=candidate,
                    entry_point=entry_point,
                    probe_llm=self._probe_model,
                    task_ir=dict(task_ir),
                )
            except Exception as exc:
                report = {
                    "decision": "abstain",
                    "summary": "spec audit infrastructure failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }

            decision = report.get("decision", "abstain")
            if decision == "approve":
                return artifact("approve", mutation=mutation, critic_report=report)
            if decision == "reject" and attempt < self._max_repairs:
                prior_text = candidate
                last_issues = critic_feedback_obligations(report) or [
                    report.get("summary", "critic rejected the specification")
                ]
                continue
            final_decision = decision if decision in {"reject", "abstain"} else "abstain"
            return artifact(
                final_decision,
                mutation=mutation,
                critic_report=report,
                issues=tuple(critic_feedback_obligations(report)),
            )

        raise AssertionError("unreachable specification loop")

    def _generate(
        self,
        *,
        problem_desc: str,
        task_ir: Mapping[str, Any],
        analysis: RequirementAnalysis,
        previous_spec: str,
        issues: list[str],
    ) -> tuple[str, list[Mapping[str, Any]]]:
        fixed_signature = render_dafny_signature(task_ir)
        revision = ""
        if previous_spec:
            revision = f"""\nPrevious formal specification:\n{previous_spec}

Evidence-backed issues that must be corrected:
""" + "\n".join(f"- {issue}" for issue in issues if issue)
        raw = self._spec_model.chat(
            system=_spec_system_prompt(),
            user=f"""Public task:
{problem_desc}

Structured requirements:
{json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2)}

Fixed public method:
{fixed_signature}
{revision}

Return a JSON object with `clauses` and `formal_spec`. Each clause must contain kind,
natural_language, formal_expression, related_requirements, and confidence. formal_spec must be
complete Dafny declarations and a bodyless public method. Do not emit a public implementation.""",
        )
        try:
            bundle = parse_json_object(raw)
            formal = str(bundle.get("formal_spec") or "")
            clauses = bundle.get("clauses")
            if not formal or not isinstance(clauses, list):
                raise ValueError("spec bundle is incomplete")
            return _strip_method_bodies(_extract_dafny_code(formal)), [
                item for item in clauses if isinstance(item, Mapping)
            ]
        except Exception:
            return _strip_method_bodies(_extract_dafny_code(raw)), []

    def _validate(self, spec: str, entry_point: str) -> tuple[str, ...]:
        issues: list[str] = []
        if not spec.strip():
            return ("empty specification",)
        if not re.search(rf"\bmethod\s+{re.escape(entry_point)}\s*\(", spec):
            issues.append("fixed public method is missing")
        if not any(line.strip().startswith("ensures") for line in spec.splitlines()):
            issues.append("public method has no postcondition")

        bodyless = bodyless_callable_names(spec)
        direct_references = set(re.findall(
            r"ensures\s+\w+\s*(?:==|<==>)\s*([A-Za-z_]\w*)\s*\(", spec
        ))
        for helper in sorted(bodyless & direct_references):
            issues.append(f"result reference helper has no body: {helper}")

        if issues:
            return tuple(issues)
        resolved = self._verifier.resolve(spec)
        if not resolved.passed:
            for error in resolved.errors[:6]:
                issues.append(
                    f"Dafny resolve [{error.subtype or error.error_type}] "
                    f"line {error.location_line}: {error.message}"
                )
            if not resolved.errors:
                issues.append("Dafny resolve failed without structured diagnostics")
        return tuple(issues)


def _build_structured_spec(
    task_id: str,
    analysis: RequirementAnalysis,
    formal_spec: str,
    proposed: list[Mapping[str, Any]],
) -> StructuredSpecification:
    requirement_ids = tuple(item.id for item in analysis.requirements)
    proposed_by_expression = {
        _normalize_expression(str(item.get("formal_expression") or "")): item
        for item in proposed
        if str(item.get("formal_expression") or "").strip()
    }
    counts = {"precondition": 0, "postcondition": 0, "invariant": 0}
    prefixes = {"precondition": "PRE", "postcondition": "POST", "invariant": "INV"}
    clauses: list[SpecClause] = []
    for kind, expression in _formal_clauses(formal_spec):
        counts[kind] += 1
        item = proposed_by_expression.get(_normalize_expression(expression), {})
        related = tuple(
            value for value in item.get("related_requirements", [])
            if value in requirement_ids
        ) if isinstance(item.get("related_requirements"), list) else ()
        clauses.append(SpecClause(
            id=f"SPEC-{prefixes[kind]}-{counts[kind]:03d}",
            kind=kind,
            natural_language=str(item.get("natural_language") or expression).strip(),
            formal_expression=expression,
            # Raw-Dafny output remains supported for replay/tests. New JSON
            # output must provide explicit traceability instead of claiming
            # that every clause covers every requirement.
            related_requirements=related if proposed else requirement_ids,
            confidence=_probability(item.get("confidence"), analysis.confidence),
        ))
    confidence_values = [analysis.confidence, *(item.confidence for item in clauses)]
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    return StructuredSpecification(
        task_id=task_id,
        requirements=analysis.requirements,
        clauses=tuple(clauses),
        edge_cases=analysis.edge_cases,
        verification_cases=analysis.verification_cases,
        confidence=round(confidence, 3),
    )


def _formal_clauses(spec: str) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    mapping = {"requires": "precondition", "ensures": "postcondition", "invariant": "invariant"}
    for line in spec.splitlines():
        stripped = line.strip()
        for keyword, kind in mapping.items():
            if stripped.startswith(keyword + " "):
                values.append((kind, stripped[len(keyword):].strip()))
                break
    return values


def _cross_level_issues(spec: str, structured: StructuredSpecification) -> tuple[str, ...]:
    formal = {_normalize_expression(expression) for _, expression in _formal_clauses(spec)}
    mapped = {_normalize_expression(item.formal_expression) for item in structured.clauses}
    issues: list[str] = []
    if not structured.requirements:
        issues.append("structured specification has no requirements")
    if not structured.clauses:
        issues.append("structured specification has no formal clauses")
    if formal != mapped:
        issues.append("structured clauses and formal specification diverged")
    requirement_ids = {item.id for item in structured.requirements}
    covered = {
        value for clause in structured.clauses for value in clause.related_requirements
    }
    missing = sorted(requirement_ids - covered)
    if missing:
        issues.append("requirements without formal clauses: " + ", ".join(missing))
    return tuple(issues)


def _spec_drift(
    previous: SpecArtifact | None,
    current: StructuredSpecification,
    reason: str,
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not previous or not previous.structured:
        return {"changed": False, "reason": "initial specification"}
    before = {item.id: item.formal_expression for item in previous.structured.clauses}
    after = {item.id: item.formal_expression for item in current.clauses}
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
    affected = sorted({
        requirement_id
        for clause in (*previous.structured.clauses, *current.clauses)
        if clause.id in {*removed, *added, *changed}
        for requirement_id in clause.related_requirements
    })
    has_change = bool(removed or added or changed)
    return {
        "changed": has_change,
        "removed_clause_ids": removed,
        "added_clause_ids": added,
        "changed_clause_ids": changed,
        "affected_requirements": affected,
        "reason": reason,
        "evidence": dict(evidence or {}),
        "unjustified": bool(has_change and not reason.strip()),
        "revalidation_required": has_change,
    }


def _with_clause_status(spec: StructuredSpecification, status: str) -> StructuredSpecification:
    return replace(spec, clauses=tuple(replace(item, status=status) for item in spec.clauses))


def _normalize_expression(value: str) -> str:
    text = re.sub(r"^\s*(?:requires|ensures|invariant)\s+", "", value.strip())
    return re.sub(r"\s+", " ", text)


def _probability(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _critic_problem(problem_desc: str, analysis: RequirementAnalysis) -> str:
    requirements = "\n".join(
        f"- {item.id} [{item.priority}/{item.kind}]: {item.description}"
        for item in analysis.requirements
    )
    edges = "\n".join(f"- {item}" for item in analysis.edge_cases) or "- none identified"
    return f"""{problem_desc}

Atomic public requirements:
{requirements}

Public edge cases to audit:
{edges}"""


def _extract_dafny_code(text: str) -> str:
    code = text or ""
    if "```dafny" in code:
        code = code.split("```dafny", 1)[1].split("```", 1)[0]
    elif "```" in code:
        code = code.split("```", 1)[1].split("```", 1)[0]
    return re.sub(r"[^\x00-\x7F\n\r\t ]+", "", code).strip()


def _strip_method_bodies(spec: str) -> str:
    lines = spec.splitlines()
    result: list[str] = []
    in_body = False
    depth = 0
    for line in lines:
        stripped = line.strip()
        if in_body:
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                in_body = False
            continue
        if stripped == "{" and any(
            previous.lstrip().startswith("method ") for previous in result[-8:]
        ):
            in_body, depth = True, 1
            continue
        if stripped.startswith("method ") and "{" in line:
            result.append(line.split("{", 1)[0].rstrip())
            depth = line.count("{") - line.count("}")
            in_body = depth > 0
            continue
        result.append(line)
    return "\n".join(result).strip()


def _spec_system_prompt() -> str:
    return """You are the Specification Agent and authority for a spec-guided Dafny coding agent.
Create atomic structured clauses mapped to REQ IDs and an equivalent formal Dafny contract. Keep
the fixed public method and full legal input domain. Do not invent preconditions, omit requirements,
or emit a public method body. Pure helpers are allowed only when total. Return only JSON. The result
will face independent semantic review, public-example probes, mutation testing, and Dafny resolution."""
