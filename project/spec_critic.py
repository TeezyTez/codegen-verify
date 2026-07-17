"""Independent semantic critic for generated Dafny specifications.

The critic is independent at the *role and context* level: it receives only
the task artifact and the candidate specification, never the producer's chain
of thought or conversation history.  Provider and model selection live behind
``critic_llm`` so experiments can later use a different model family without
changing the pipeline.
"""

from __future__ import annotations

import json
import re
from typing import Any

import config


VALID_DECISIONS = {"approve", "reject", "abstain"}
HIGH_SEVERITIES = {"high", "critical"}
ISSUE_CATEGORIES = {"semantic_mismatch", "input_domain", "ambiguity", "dafny_validity"}
GROUNDED_SOURCES = {"task_text", "public_example"}
CONTRADICTORY_REJECT_PHRASES = (
    "specification is correct",
    "specification is actually correct",
    "specification is fine",
    "should approve",
    "should accept",
    "i find no error",
    "i don't find errors",
    "no semantic mismatch",
    "not a semantic mismatch",
    "previous audit is wrong",
    "previous audit incorrectly",
    "only a code smell",
)
PROBE_SELF_REVISION_PATTERNS = (
    r"(?:^|[.!?]\s+)wait\s*[,;:]",
    r"\bcorrect\s+expected(?:\s+value)?\s*(?:[:=]|is\b)",
    r"\b(?:proposed|supplied)\s+(?:expected\s+)?value\b.{0,80}"
    r"\b(?:is|was)\s+(?!not\b)(?:incorrect|wrong|invalid)\b",
)
CONTRADICTORY_CONFIRM_PATTERNS = (
    r"\b(?:so|therefore|thus|should)\s+dispute\b",
    r"\b(?:proposed|supplied)\s+(?:expected\s+)?value\b.{0,80}"
    r"\b(?:is|was)\s+(?!not\b)(?:incorrect|wrong|invalid)\b",
    r"\b(?:proposed|supplied)\s+(?:expected\s+)?value\b.{0,80}\bdoes\s+not\s+match\b",
)


def review_spec_with_llm(
    llm,
    *,
    problem_desc: str,
    spec: str,
    entry_point: str = "",
    max_parse_retries: int | None = None,
    review_passes: int | None = None,
    execute_boundary_checks: bool = True,
    probe_llm=None,
    task_ir: dict[str, Any] | None = None,
    probe_suite: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask a fresh critic context to audit NL-to-spec semantic fidelity.

    Invalid or ambiguous critic output is converted to ``abstain`` rather than
    silently approving a specification.  This makes the critic suitable for a
    high-assurance acceptance gate.
    """
    retries = (
        config.MAX_CRITIC_PARSE_RETRIES
        if max_parse_retries is None
        else max(0, max_parse_retries)
    )
    passes = max(
        1,
        config.CRITIC_REVIEW_PASSES if review_passes is None else review_passes,
    )
    signature_issues = _task_signature_issues(
        spec=spec,
        entry_point=entry_point,
        task_ir=task_ir or {},
    )
    if signature_issues:
        return {
            "schema_version": 1,
            "decision": "reject",
            "audit_decision": "reject",
            "confidence": 1.0,
            "summary": "Candidate public signature does not match the deterministic TaskIR signature.",
            "issues": [{
                "category": "semantic_mismatch",
                "severity": "critical",
                "material": True,
                "requirement": "Preserve the deterministic TaskIR public signature exactly.",
                "spec_location": entry_point or "public method",
                "explanation": issue,
            } for issue in signature_issues],
            "counterexamples": [],
            "boundary_checks": [],
            "signature_gate": {
                "status": "failed",
                "issues": signature_issues,
            },
            "critic_provider": getattr(llm, "provider", config.CRITIC_PROVIDER),
            "critic_model": getattr(llm, "model", config.CRITIC_MODEL),
            "review_passes": 0,
            "parse_attempts": 0,
            "parse_error": "",
        }
    report, attempts, error, raw = _request_report(
        llm,
        system=_system_prompt(),
        user_factory=lambda last_error: _user_prompt(
                problem_desc=problem_desc,
                spec=spec,
                entry_point=entry_point,
                last_error=last_error,
        ),
        retries=retries,
        report_validator=lambda candidate: _validate_report_task_values(
            candidate, task_ir or {}
        ),
    )
    audit_protocol_failure = report is None
    if audit_protocol_failure:
        report = _abstain_on_invalid_output(
            llm, attempts, error, raw, stage="initial audit"
        )

    total_attempts = attempts
    for pass_index in range(2, passes + 1) if not audit_protocol_failure else ():
        prior_report = report
        report, attempts, error, raw = _request_report(
            llm,
            system=_review_system_prompt(),
            user_factory=lambda last_error, prior=prior_report: _review_user_prompt(
                problem_desc=problem_desc,
                spec=spec,
                entry_point=entry_point,
                prior_report=prior,
                last_error=last_error,
            ),
            retries=retries,
            report_validator=lambda candidate: _validate_report_task_values(
                candidate, task_ir or {}
            ),
        )
        total_attempts += attempts
        if report is None:
            return _abstain_on_invalid_output(
                llm,
                total_attempts,
                error,
                raw,
                stage=f"audit validation pass {pass_index}",
            )

    report.update({
        "critic_provider": getattr(llm, "provider", config.CRITIC_PROVIDER),
        "critic_model": getattr(llm, "model", config.CRITIC_MODEL),
        "review_passes": passes,
        "parse_attempts": total_attempts,
        "parse_error": "",
    })
    report["audit_decision"] = report.get("decision", "abstain")
    if audit_protocol_failure:
        report["audit_protocol_failure"] = True
        report["parse_error"] = error or "invalid critic response"
    if execute_boundary_checks:
        probe_suite = _revalidate_cached_probe_suite(
            probe_suite,
            problem_desc=problem_desc,
            task_ir=task_ir or {},
        ) or generate_task_probes_with_llm(
            probe_llm or llm,
            problem_desc=problem_desc,
            entry_point=entry_point,
            task_ir=task_ir,
        )
        report["probe_generation"] = {
            key: value for key, value in probe_suite.items() if key != "probes"
        }
        report["generated_probes"] = probe_suite.get("probes", [])
        public_probes = public_example_probes(task_ir or {}, entry_point=entry_point)
        report["public_example_probes"] = public_probes
        if audit_protocol_failure:
            # A finite probe suite is testing evidence, not a substitute for an
            # independent semantic audit over the whole specification.
            report["decision"] = "abstain"
            report["confidence"] = 0.0
            report["summary"] = (
                "Semantic audit protocol failed; executable probes are recorded "
                "for diagnosis but cannot establish whole-specification approval."
            )
        elif report.get("decision") == "approve" and probe_suite.get("status") != "generated":
            report["decision"] = "abstain"
            report["confidence"] = 0.0
            report["summary"] = "Independent semantic probe generation was unavailable."
        remaining_checks = _probes_as_boundary_checks([
            *public_probes,
            *probe_suite.get("probes", []),
        ]) + _counterexamples_as_boundary_checks(report.get("counterexamples", []))
        confirmations = []
        for _confirmation_round in range(3):
            report = execute_approved_boundary_checks(
                report,
                spec=spec,
                entry_point=entry_point,
                additional_checks=remaining_checks,
            )
            pending_conflict = report.get("pending_probe_conflict")
            if not pending_conflict:
                break
            if _confirmation_round == 2:
                report["decision"] = "abstain"
                report["confidence"] = 0.0
                report["summary"] = "Too many disputed probe conflicts remained after rechecking."
                break
            confirmation = confirm_probe_expectation_with_llm(
                probe_llm or llm,
                problem_desc=problem_desc,
                entry_point=entry_point,
                arguments=pending_conflict.get("arguments", []),
                expected_value=pending_conflict.get("expected"),
                task_ir=task_ir,
            )
            confirmations.append({
                **confirmation,
                "conflict": pending_conflict,
            })
            if confirmation.get("decision") == "confirm":
                report["decision"] = "reject"
                report["confidence"] = min(
                    0.95, float(confirmation.get("confidence", 0.0))
                )
                report["summary"] = (
                    "An independently confirmed NL-derived executable probe "
                    "disproved the candidate specification."
                )
                _append_confirmed_probe_mismatch(
                    report,
                    pending_conflict=pending_conflict,
                    confirmation=confirmation,
                )
                break
            if confirmation.get("decision") == "dispute":
                conflict_key = json.dumps(
                    [pending_conflict.get("arguments"), pending_conflict.get("expected")],
                    ensure_ascii=False,
                    sort_keys=True,
                )
                remaining_checks = [
                    check for check in remaining_checks
                    if json.dumps(
                        [check.get("arguments"), check.get("expected_value")],
                        ensure_ascii=False,
                        sort_keys=True,
                    ) != conflict_key
                ]
                report["boundary_checks"] = [
                    check for check in report.get("boundary_checks", [])
                    if json.dumps(
                        [check.get("arguments"), check.get("expected_value")],
                        ensure_ascii=False,
                        sort_keys=True,
                    ) != conflict_key
                ]
                report["counterexamples"] = [
                    item for item in report.get("counterexamples", [])
                    if _probe_evidence_key(
                        item.get("arguments"), item.get("expected_value")
                    ) != _probe_evidence_key(
                        pending_conflict.get("arguments"),
                        pending_conflict.get("expected"),
                    )
                ]
                report.pop("pending_probe_conflict", None)
                report["decision"] = "approve"
                report["confidence"] = 0.7
                report["summary"] = (
                    "A disputed LLM-authored probe was removed; rechecking the "
                    "remaining public and independent suite."
                )
                report["discarded_probe_conflicts"] = [
                    *report.get("discarded_probe_conflicts", []),
                    pending_conflict,
                ]
                continue
            report["decision"] = "abstain"
            report["confidence"] = 0.0
            report["summary"] = (
                "An executable probe conflict could not be independently confirmed."
            )
            break
        if confirmations:
            report["probe_conflict_confirmations"] = confirmations
            report["probe_conflict_confirmation"] = confirmations[-1]
        if report.get("needs_reconciliation_audit"):
            passed_reconciliation_evidence = [
                {
                    "arguments": check.get("arguments", []),
                    "expected_value": check.get("expected_value"),
                }
                for check in remaining_checks
                if check.get("probe_origin")
                in {"public_example", "nl_generated"}
            ]
            disproved_evidence = {
                "counterexamples": report.get("counterexamples", []),
                "discarded_probe_conflicts": report.get("discarded_probe_conflicts", []),
                "deterministic_dafny_fact": (
                    "The harness constructed the direct Reference method and Dafny "
                    "resolved and verified that program before executing probes."
                ),
                "passed_public_examples": [
                    {
                        "arguments": probe.get("arguments", []),
                        "expected_value": probe.get("expected_value"),
                    }
                    for probe in public_probes
                ],
                "passed_spec_blind_probes": [
                    {
                        "arguments": probe.get("arguments", []),
                        "expected_value": probe.get("expected_value"),
                    }
                    for probe in probe_suite.get("probes", [])
                ],
            }
            reconciliation, rec_attempts, rec_error, rec_raw = _request_report(
                llm,
                # Reconciliation is a fresh whole-spec audit. Use the complete
                # initial protocol (including the exact JSON schema) rather than
                # a stateful-sounding review prompt that the API call cannot see.
                system=_system_prompt(),
                user_factory=lambda last_error: _reconciliation_user_prompt(
                    problem_desc=problem_desc,
                    spec=spec,
                    entry_point=entry_point,
                    disproved_evidence=disproved_evidence,
                    last_error=last_error,
                ),
                retries=retries,
                report_validator=lambda candidate: _validate_reconciliation_report(
                    candidate,
                    task_ir or {},
                    passed_evidence=passed_reconciliation_evidence,
                ),
            )
            total_attempts += rec_attempts
            report["parse_attempts"] = total_attempts
            report["reconciliation_parse_error"] = rec_error or ""
            report["reconciliation_raw_preview"] = rec_raw[:500] if rec_error else ""
            report["reconciliation_audit"] = reconciliation or {
                "decision": "abstain",
                "summary": "Fresh reconciliation audit did not return valid evidence.",
            }
            report.pop("needs_reconciliation_audit", None)
            if reconciliation and reconciliation.get("decision") == "approve":
                report["decision"] = "approve"
                report["confidence"] = min(
                    0.8, float(reconciliation.get("confidence", 0.0))
                )
                report["summary"] = (
                    "All mandatory executable probes passed and a fresh whole-spec "
                    "reconciliation audit independently approved the contract."
                )
                # Do not leave the disproved rejection narrative in the final
                # actionable findings. It remains available in the nested trace.
                report["issues"] = reconciliation.get("issues", [])
                report["counterexamples"] = reconciliation.get("counterexamples", [])
                report["boundary_checks"] = reconciliation.get("boundary_checks", [])
                report["audit_rejection_overturned"] = True
            else:
                report["decision"] = "abstain"
                report["confidence"] = 0.0
                report["summary"] = (
                    "Prior rejection evidence was disproved, but no fresh positive "
                    "whole-spec audit certified the contract."
                )
    if config.CRITIC_REQUIRE_PRECONDITION_EVIDENCE:
        precondition_review = _review_public_preconditions(
            spec=spec,
            entry_point=entry_point,
            problem_desc=problem_desc,
            task_ir=task_ir or {},
        )
        report["public_precondition_review"] = precondition_review
        unresolved = precondition_review.get("unresolved_clauses", [])
        if report.get("decision") == "approve" and unresolved:
            report["decision"] = "abstain"
            report["confidence"] = 0.0
            report["unreviewed_public_requires"] = unresolved
            report["summary"] = (
                "Public preconditions lack explicit task-domain or recognized "
                "mathematical-definedness evidence; approval is withheld."
            )
    return report


def _request_report(
    llm,
    *,
    system: str,
    user_factory,
    retries: int,
    report_validator=None,
):
    last_error = ""
    raw = ""
    for attempt in range(retries + 1):
        raw = llm.chat(
            system=system,
            user=user_factory(last_error),
            temperature=config.CRITIC_TEMPERATURE,
            max_tokens=config.CRITIC_MAX_TOKENS,
        )
        try:
            report = normalize_critic_report(parse_critic_response(raw))
            if report_validator is not None:
                report_validator(report)
            return (
                report,
                attempt + 1,
                "",
                raw,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
    return None, retries + 1, last_error, raw


def _abstain_on_invalid_output(llm, attempts: int, error: str, raw: str, *, stage: str):
    return {
        "schema_version": 1,
        "decision": "abstain",
        "confidence": 0.0,
        "summary": f"Critic output could not be parsed safely during {stage}.",
        "issues": [],
        "counterexamples": [],
        "boundary_checks": [],
        "critic_provider": getattr(llm, "provider", config.CRITIC_PROVIDER),
        "critic_model": getattr(llm, "model", config.CRITIC_MODEL),
        "review_passes": 0,
        "parse_attempts": attempts,
        "parse_error": error or "invalid critic response",
        "raw_response_preview": raw[:500],
    }


def parse_critic_response(text: str) -> dict[str, Any]:
    """Extract one JSON object from plain or fenced model output."""
    candidate = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", candidate, re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end < start:
            raise ValueError("critic response does not contain a JSON object")
        candidate = candidate[start:end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # Some OpenAI-compatible providers occasionally place literal control
        # characters inside an otherwise valid JSON string. ``strict=False``
        # accepts those characters without weakening structural validation.
        parsed = json.loads(candidate, strict=False)
    if not isinstance(parsed, dict):
        raise TypeError("critic response must be a JSON object")
    return parsed


def normalize_critic_report(report: dict[str, Any]) -> dict[str, Any]:
    """Validate the public critic schema and enforce conservative decisions."""
    decision = str(report.get("decision", "")).strip().lower()
    if decision not in VALID_DECISIONS:
        raise ValueError(f"invalid critic decision: {decision!r}")

    issues = _object_list(report.get("issues", []), "issues")
    counterexamples = _object_list(report.get("counterexamples", []), "counterexamples")
    boundary_checks = _object_list(report.get("boundary_checks", []), "boundary_checks")
    for issue in issues:
        _validate_issue(issue)
    for counterexample in counterexamples:
        _validate_counterexample(counterexample)
    for boundary in boundary_checks:
        _validate_boundary(boundary)

    confidence_raw = report.get("confidence", 0.0)
    if isinstance(confidence_raw, bool) or not isinstance(confidence_raw, (int, float)):
        raise TypeError("critic confidence must be numeric")
    confidence = max(0.0, min(1.0, float(confidence_raw)))

    # An approval carrying a concrete counterexample or a high-severity issue
    # is internally inconsistent.  Fail closed instead of trusting the label.
    has_material_semantic_issue = any(_material_semantic_issue(issue) for issue in issues)
    has_grounded_counterexample = any(
        _grounded_counterexample(counterexample) for counterexample in counterexamples
    )
    grounded_boundary_checks = [
        boundary for boundary in boundary_checks
        if boundary.get("within_task_domain") is True
        and str(boundary.get("expected_source", "")).strip().lower() in GROUNDED_SOURCES
    ]
    mismatching_grounded_boundary = any(
        boundary.get("matches") is False for boundary in grounded_boundary_checks
    )
    grounded_reject = has_material_semantic_issue and has_grounded_counterexample
    partial_reject_evidence = any((
        has_material_semantic_issue,
        has_grounded_counterexample,
    )) and not grounded_reject
    if decision != "abstain" and partial_reject_evidence:
        raise ValueError(
            "critic evidence is incomplete or misaligned; semantic issue, "
            "issue and counterexample must agree"
        )
    if decision == "approve" and grounded_reject:
        decision = "reject"
    elif decision == "approve" and mismatching_grounded_boundary:
        raise ValueError(
            "critic approval contains a grounded boundary check marked as mismatching"
        )

    summary = str(report.get("summary", "")).strip()
    if not summary:
        raise ValueError("critic summary must be non-empty")
    evidence_text = " ".join([
        summary,
        *(str(issue.get("explanation", "")) for issue in issues),
        *(str(item.get("rationale", "")) for item in counterexamples),
    ]).lower()
    if decision == "reject" and any(
        phrase in evidence_text for phrase in CONTRADICTORY_REJECT_PHRASES
    ):
        raise ValueError(
            "critic reject is self-contradictory: narrative says the specification is correct"
        )
    if decision == "reject" and not grounded_reject:
        raise ValueError(
            "critic reject lacks a material semantic issue plus a task-grounded, "
            "in-domain counterexample"
        )
    # An unsubstantiated approval is unsafe. Require two concrete, grounded
    # checks and retry malformed evidence instead of silently trusting it.
    if decision == "approve" and not grounded_boundary_checks:
        raise ValueError("critic approval needs at least one task-grounded boundary check")

    return {
        "schema_version": 1,
        "decision": decision,
        "confidence": confidence,
        "summary": summary,
        "issues": issues,
        "counterexamples": counterexamples,
        "boundary_checks": boundary_checks,
    }


def critic_feedback_obligations(report: dict[str, Any]) -> list[str]:
    """Render structured critic findings as focused spec-repair obligations."""
    obligations: list[str] = []
    for issue in report.get("issues", []):
        requirement = str(issue.get("requirement", "")).strip()
        explanation = str(issue.get("explanation", "")).strip()
        location = str(issue.get("spec_location", "")).strip()
        parts = [part for part in (requirement, explanation) if part]
        if parts:
            suffix = f" (spec: {location})" if location else ""
            obligations.append("Independent critic: " + " — ".join(parts) + suffix)
    for counterexample in report.get("counterexamples", []):
        obligations.append(
            "Independent critic counterexample: "
            + json.dumps(counterexample, ensure_ascii=False, sort_keys=True)
        )
    if not obligations and report.get("summary"):
        obligations.append("Independent critic: " + str(report["summary"]))
    return obligations


def _object_list(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise TypeError(f"critic {field} must be a list of objects")
    return value


def _validate_issue(issue: dict[str, Any]) -> None:
    category = str(issue.get("category", "")).strip().lower()
    if category not in ISSUE_CATEGORIES:
        raise ValueError(f"invalid critic issue category: {category!r}")
    if not isinstance(issue.get("material"), bool):
        raise TypeError("critic issue material must be boolean")
    severity = str(issue.get("severity", "")).strip().lower()
    if severity not in {"low", "medium", "high", "critical"}:
        raise ValueError(f"invalid critic issue severity: {severity!r}")


def _validate_counterexample(counterexample: dict[str, Any]) -> None:
    if not isinstance(counterexample.get("within_task_domain"), bool):
        raise TypeError("critic counterexample within_task_domain must be boolean")
    if not isinstance(counterexample.get("matches_spec"), bool):
        raise TypeError("critic counterexample matches_spec must be boolean")
    source = str(counterexample.get("expected_source", "")).strip().lower()
    if source not in {*GROUNDED_SOURCES, "inferred", "ambiguous"}:
        raise ValueError(f"invalid critic counterexample expected_source: {source!r}")
    if not isinstance(counterexample.get("arguments"), list):
        raise TypeError("critic counterexample arguments must be a JSON list")
    if "expected_value" not in counterexample:
        raise ValueError("critic counterexample expected_value is required")


def _validate_boundary(boundary: dict[str, Any]) -> None:
    if not isinstance(boundary.get("within_task_domain"), bool):
        raise TypeError("critic boundary within_task_domain must be boolean")
    if not isinstance(boundary.get("matches"), bool):
        raise TypeError("critic boundary matches must be boolean")
    source = str(boundary.get("expected_source", "")).strip().lower()
    if source not in {*GROUNDED_SOURCES, "inferred", "ambiguous"}:
        raise ValueError(f"invalid critic boundary expected_source: {source!r}")
    if not isinstance(boundary.get("arguments"), list):
        raise TypeError("critic boundary arguments must be a JSON list")
    if "expected_value" not in boundary:
        raise ValueError("critic boundary expected_value is required")


def _validate_report_task_values(
    report: dict[str, Any],
    task_ir: dict[str, Any],
) -> None:
    """Reject Critic evidence that contradicts deterministic TaskIR structure."""
    if not task_ir or "parameters" not in task_ir:
        return
    return_type = task_ir.get("return_type") or {}
    for field in ("counterexamples", "boundary_checks"):
        for item in report.get(field, []):
            if item.get("within_task_domain") is not True:
                continue
            arguments = item.get("arguments")
            _validate_probe_arguments(arguments, task_ir)
            if _contains_unjustified_empty_argument(arguments, task_ir):
                raise ValueError(
                    f"critic {field} claims an unspecified empty argument is in-domain"
                )
            domain_error = _explicit_task_domain_error(arguments, task_ir)
            if domain_error:
                raise ValueError(f"critic {field} violates explicit task domain: {domain_error}")
            if return_type and not _value_matches_type(
                item.get("expected_value"), return_type
            ):
                raise TypeError(
                    f"critic {field} expected_value does not match the TaskIR return type"
                )


def _validate_reconciliation_report(
    report: dict[str, Any],
    task_ir: dict[str, Any],
    *,
    passed_evidence: list[dict[str, Any]] | None = None,
) -> None:
    _validate_report_task_values(report, task_ir)
    if report.get("decision") == "approve" and passed_evidence is not None:
        passed_keys = {
            _probe_evidence_key(item.get("arguments"), item.get("expected_value"))
            for item in passed_evidence
        }
        expected_by_arguments = {
            json.dumps(
                item.get("arguments"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ): item.get("expected_value")
            for item in passed_evidence
        }
        for boundary in report.get("boundary_checks", []):
            if (
                boundary.get("within_task_domain") is not True
                or str(boundary.get("expected_source", "")).strip().lower()
                not in GROUNDED_SOURCES
            ):
                continue
            key = _probe_evidence_key(
                boundary.get("arguments"), boundary.get("expected_value")
            )
            if key in passed_keys:
                continue
            argument_key = json.dumps(
                boundary.get("arguments"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if argument_key in expected_by_arguments:
                raise ValueError(
                    "reconciliation boundary contradicts already executed evidence: "
                    f"arguments={boundary.get('arguments')!r}, executed expected="
                    f"{expected_by_arguments[argument_key]!r}"
                )
            raise ValueError(
                "reconciliation approval boundary was not executed; copy an exact "
                "arguments/expected_value pair from passed_public_examples or "
                "passed_spec_blind_probes"
            )
    if report.get("decision") != "reject":
        return
    material_issues = [
        issue for issue in report.get("issues", []) if issue.get("material") is True
    ]
    validity_markers = (
        "not valid dafny",
        "not a valid dafny",
        "invalid dafny",
        "does not compile",
        "cannot compile",
        "unexecutable",
        "not executable",
        "syntax error",
        "type error",
        "not a built-in",
        "no built-in",
        "cannot be resolved",
        "dafny expression",
    )

    def validity_only(issue: dict[str, Any]) -> bool:
        if str(issue.get("category", "")).lower() == "dafny_validity":
            return True
        text = " ".join(
            str(issue.get(field, "")).lower()
            for field in ("requirement", "explanation", "spec_location")
        )
        return any(marker in text for marker in validity_markers)

    if material_issues and all(validity_only(issue) for issue in material_issues):
        raise ValueError(
            "the direct Reference program already resolved and verified in Dafny; "
            "do not reject for syntax, typing, .Floor validity, or executability. "
            "Re-audit only task-level input/output semantics"
        )


def _explicit_task_domain_error(
    arguments: list[Any],
    task_ir: dict[str, Any],
) -> str:
    """Recognize only simple, explicit numeric domain constraints from prose."""
    examples = task_ir.get("examples") or []
    entry_point = str(task_ir.get("entry_point") or "").strip()
    if any(
        example.get("arguments_are_literal")
        and (
            not entry_point
            or str(example.get("call_name") or "").strip() in {"", entry_point}
        )
        and list(example.get("positional_args") or []) == arguments
        for example in examples
    ):
        return ""
    task_text = str(
        task_ir.get("raw_docstring") or task_ir.get("docstring") or ""
    ).lower()
    parameters = task_ir.get("parameters") or []
    for index, (argument, parameter) in enumerate(zip(arguments, parameters)):
        if isinstance(argument, bool) or not isinstance(argument, (int, float)):
            continue
        name = str(parameter.get("name") or "").rstrip("_").lower()
        for kind, pattern in (
            (
                "nonnegative",
                r"\b(?:non[- ]?negative|not\s+negative|zero\s+or\s+positive|"
                r"greater\s+than\s+or\s+equal\s+to\s+zero)\b",
            ),
            (
                "positive",
                r"\bpositive(?:\s+(?:floating[ -]point|integer|number|value))?\b",
            ),
        ):
            for match in re.finditer(pattern, task_text, flags=re.IGNORECASE):
                segment_start = max(
                    task_text.rfind(delimiter, 0, match.start())
                    for delimiter in (".", ";", "\n")
                ) + 1
                following = [
                    position
                    for position in (
                        task_text.find(delimiter, match.end())
                        for delimiter in (".", ";", "\n")
                    )
                    if position >= 0
                ]
                segment_end = min(following) if following else len(task_text)
                segment = task_text[segment_start:segment_end]
                if _match_has_output_subject(
                    segment, match.start() - segment_start
                ):
                    continue
                bound = len(parameters) == 1 or bool(
                    name and re.search(r"\b" + re.escape(name) + r"\b", segment)
                )
                if not bound:
                    continue
                if kind == "positive" and re.search(
                    r"\b(?:non[- ]?negative|not\s+negative|zero\s+or\s+positive|"
                    r"greater\s+than\s+or\s+equal\s+to\s+zero)\b",
                    segment,
                ):
                    continue
                if kind == "positive" and argument <= 0:
                    return f"parameter {name or index} is explicitly positive"
                if kind == "nonnegative" and argument < 0:
                    return f"parameter {name or index} is explicitly nonnegative"
                break
    return ""


def _material_semantic_issue(issue: dict[str, Any]) -> bool:
    return (
        issue.get("material") is True
        and str(issue.get("category", "")).strip().lower() == "semantic_mismatch"
        and str(issue.get("severity", "")).strip().lower() in HIGH_SEVERITIES
    )


def _grounded_counterexample(counterexample: dict[str, Any]) -> bool:
    return (
        counterexample.get("within_task_domain") is True
        and counterexample.get("matches_spec") is False
        and str(counterexample.get("expected_source", "")).strip().lower()
        in GROUNDED_SOURCES
    )


def generate_task_probes_with_llm(
    llm,
    *,
    problem_desc: str,
    entry_point: str,
    max_parse_retries: int | None = None,
    task_ir: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate NL-only executable probes in a fresh, spec-blind context."""
    retries = (
        config.MAX_CRITIC_PROBE_PARSE_RETRIES
        if max_parse_retries is None
        else max(0, max_parse_retries)
    )
    last_error = ""
    raw = ""
    semantic_problem_desc = _semantic_task_description(problem_desc, task_ir or {})
    required_tags = _required_probe_tags(semantic_problem_desc, task_ir or {})
    for attempt in range(retries + 1):
        raw = llm.chat(
            system=_probe_system_prompt(),
            user=_probe_user_prompt(
                problem_desc=semantic_problem_desc,
                entry_point=entry_point,
                last_error=last_error,
                required_tags=required_tags,
            ),
            temperature=config.CRITIC_TEMPERATURE,
            max_tokens=config.CRITIC_PROBE_MAX_TOKENS,
        )
        try:
            parsed = parse_critic_response(raw)
            probes = _validate_probe_suite(
                parsed,
                required_tags=required_tags,
                task_ir=task_ir or {},
            )
            return {
                "status": "generated",
                "attempts": attempt + 1,
                "error": "",
                "probe_model": getattr(llm, "model", config.CRITIC_MODEL),
                "probes": probes,
            }
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
    return {
        "status": "unavailable",
        "attempts": retries + 1,
        "error": last_error or "invalid semantic probe response",
        "probe_model": getattr(llm, "model", config.CRITIC_MODEL),
        "raw_response_preview": raw[:500],
        "probes": [],
    }


def _revalidate_cached_probe_suite(
    probe_suite: dict[str, Any] | None,
    *,
    problem_desc: str,
    task_ir: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(probe_suite, dict) or probe_suite.get("status") != "generated":
        return None
    semantic_problem_desc = _semantic_task_description(problem_desc, task_ir)
    try:
        probes = _validate_probe_suite(
            {"probes": probe_suite.get("probes", [])},
            required_tags=_required_probe_tags(semantic_problem_desc, task_ir),
            task_ir=task_ir,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return {**probe_suite, "probes": probes}


def _validate_probe_suite(
    payload: dict[str, Any],
    *,
    required_tags: set[str],
    task_ir: dict[str, Any],
) -> list[dict[str, Any]]:
    probes = _object_list(payload.get("probes", []), "probes")
    if len(probes) < config.MIN_CRITIC_PROBES:
        raise ValueError(
            f"semantic probe generator must return at least {config.MIN_CRITIC_PROBES} probes"
        )
    if len(probes) > config.MAX_CRITIC_PROBES:
        probes = probes[:config.MAX_CRITIC_PROBES]
    normalized = []
    seen = set()
    for probe in probes:
        arguments = probe.get("arguments")
        if not isinstance(arguments, list):
            raise TypeError("semantic probe arguments must be a JSON list")
        _validate_probe_arguments(arguments, task_ir)
        if _contains_unjustified_empty_argument(arguments, task_ir):
            # One speculative empty case must not poison an otherwise complete
            # suite. Drop it locally; the suite-level cardinality and coverage
            # checks below still force a retry when it carried necessary evidence.
            continue
        domain_error = _explicit_task_domain_error(arguments, task_ir)
        if domain_error:
            raise ValueError(
                "semantic probe violates an explicit task-domain constraint: "
                + domain_error
            )
        if "expected_value" not in probe:
            raise ValueError("semantic probe expected_value is required")
        return_type = task_ir.get("return_type") or {}
        if return_type and not _value_matches_type(probe.get("expected_value"), return_type):
            raise TypeError("semantic probe expected_value does not match task return type")
        if probe.get("within_task_domain") is not True:
            raise ValueError("semantic probes must be within the explicit task domain")
        source = str(probe.get("expected_source", "")).strip().lower()
        if source != "task_text":
            raise ValueError(
                "LLM-generated semantic probes must use expected_source=task_text; "
                "public_example is reserved for deterministic TaskIR extraction"
            )
        requirement = str(probe.get("requirement", "")).strip()
        case = str(probe.get("case", "")).strip()
        if not requirement or not case:
            raise ValueError("semantic probes need concise requirement and case fields")
        rationale = str(probe.get("rationale", "")).strip()
        explanatory_text = " ".join((case, requirement, rationale)).lower()
        self_revision = next(
            (
                pattern for pattern in PROBE_SELF_REVISION_PATTERNS
                if re.search(pattern, explanatory_text, flags=re.DOTALL)
            ),
            "",
        )
        if self_revision:
            raise ValueError(
                "semantic probe explanation contains an unresolved self-revision: "
                + self_revision
            )
        tags = probe.get("coverage_tags")
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise TypeError("semantic probe coverage_tags must be a list of strings")
        tags = sorted(set(tag.strip().lower() for tag in tags if tag.strip()))
        key = json.dumps(
            [arguments, probe.get("expected_value")],
            ensure_ascii=False,
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "case": case,
            "requirement": requirement,
            "arguments": arguments,
            "expected_value": probe.get("expected_value"),
            "within_task_domain": True,
            "expected_source": source,
            "rationale": rationale,
            "coverage_tags": [],
            "declared_coverage_tags": tags,
            "contrast_group": str(probe.get("contrast_group", "")).strip(),
        })
    if len(normalized) < config.MIN_CRITIC_PROBES:
        raise ValueError("semantic probe suite contains too few distinct probes")
    _augment_structural_probe_tags(normalized, task_ir, required_tags=required_tags)
    covered = {tag for probe in normalized for tag in probe["coverage_tags"]}
    missing_tags = sorted(required_tags - covered)
    if missing_tags:
        raise ValueError("semantic probe suite misses required coverage tags: " + ", ".join(missing_tags))
    if "decisive_last" in required_tags and not _has_decisive_last_contrast(
        normalized, task_ir
    ):
        raise ValueError(
            "decisive_last coverage requires adjacent probes in one contrast_group "
            "with different expected values"
        )
    return normalized


def _augment_structural_probe_tags(
    probes: list[dict[str, Any]],
    task_ir: dict[str, Any],
    *,
    required_tags: set[str],
) -> None:
    """Compute objective coverage tags instead of trusting model bookkeeping."""
    if not probes:
        return
    sizes = [_probe_input_size(probe.get("arguments", [])) for probe in probes]
    minimum_size = min(sizes)
    parameters = task_ir.get("parameters") or []
    task_text = str(
        task_ir.get("raw_docstring") or task_ir.get("docstring") or ""
    ).lower()
    for probe, size in zip(probes, sizes):
        tags = set()
        arguments = probe.get("arguments", [])
        container_minimal = True
        has_container = False
        for index, (argument, parameter) in enumerate(zip(arguments, parameters)):
            kind = (parameter.get("dafny_type") or {}).get("kind")
            if kind in {"sequence", "string", "variadic_tuple"}:
                has_container = True
                target_size = 0 if _empty_argument_is_explicit(index, task_ir) else 1
                try:
                    if _container_argument_size(argument, task_text) != target_size:
                        container_minimal = False
                except TypeError:
                    container_minimal = False
        scalar_minimal = (
            not has_container
            and (
                _probe_has_canonical_scalar_boundary(arguments, parameters)
                if parameters
                else size == minimum_size
            )
        )
        if (has_container and container_minimal) or scalar_minimal:
            tags.add("minimal_valid")
        sequence_positions = [
            index
            for index, parameter in enumerate(parameters)
            if (parameter.get("dafny_type") or {}).get("kind")
            in {"sequence", "variadic_tuple"}
        ]
        string_positions = [
            index
            for index, parameter in enumerate(parameters)
            if (parameter.get("dafny_type") or {}).get("kind") == "string"
        ]
        singleton_positions = sequence_positions or string_positions
        if singleton_positions and all(
            _container_argument_size(arguments[index], task_text) == 1
            for index in singleton_positions
        ):
            tags.add("singleton")
        if "multiplicity" in required_tags and _probe_has_multiplicity(
            arguments, task_ir, task_text
        ):
            tags.add("multiplicity")
        if "tie" in required_tags and _probe_has_structural_tie(arguments):
            tags.add("tie")
        if "representation" in required_tags and _probe_has_representation(
            arguments, probe.get("expected_value"), task_ir
        ):
            tags.add("representation")
        if "endpoint" in required_tags and _probe_has_threshold_endpoint(
            arguments, task_ir
        ):
            tags.add("endpoint")
        if "ordering" in required_tags and _probe_has_ordering(
            arguments, probe.get("expected_value"), task_text
        ):
            tags.add("ordering")
        probe["coverage_tags"] = sorted(tags)
    for index, left in enumerate(probes):
        for right in probes[index + 1:]:
            if left.get("expected_value") == right.get("expected_value"):
                continue
            left_group = str(left.get("contrast_group", "")).strip()
            right_group = str(right.get("contrast_group", "")).strip()
            if not left_group or left_group != right_group:
                continue
            if _arguments_are_decisively_adjacent(
                left.get("arguments", []), right.get("arguments", []), task_ir
            ):
                pair_tags = ["decisive_last"]
                if "endpoint" in required_tags:
                    pair_tags.append("endpoint")
                left["coverage_tags"] = sorted(set(
                    left.get("coverage_tags", []) + pair_tags
                ))
                right["coverage_tags"] = sorted(set(
                    right.get("coverage_tags", []) + pair_tags
                ))


def _container_argument_size(value: Any, task_text: str) -> int:
    if not isinstance(value, str):
        return len(value)
    if any(token in task_text for token in (
        "space-delimited", "space delimited", "separated by spaces",
    )):
        return len(value.split())
    if "group" in task_text and any(token in task_text for token in (
        "parentheses", "parenthesis", "paren",
    )):
        depth = 0
        groups = 0
        for char in value:
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
                if depth == 0:
                    groups += 1
        return groups
    return len(value)


def _probe_input_size(arguments: list[Any]) -> int:
    size = 0
    for argument in arguments:
        if isinstance(argument, (str, list, tuple, dict)):
            size += len(argument)
        else:
            size += 1
    return size


def _probe_has_canonical_scalar_boundary(
    arguments: list[Any],
    parameters: list[dict[str, Any]],
) -> bool:
    saw_scalar = False
    for argument, parameter in zip(arguments, parameters):
        kind = (parameter.get("dafny_type") or {}).get("kind")
        if kind in {"integer", "real"}:
            saw_scalar = True
            if isinstance(argument, bool) or not isinstance(argument, (int, float)):
                return False
            if not (-1 <= float(argument) <= 1):
                return False
        elif kind == "boolean":
            saw_scalar = True
        elif kind not in {"unit", "optional"}:
            return False
    return saw_scalar


def _probe_has_multiplicity(
    arguments: list[Any],
    task_ir: dict[str, Any],
    task_text: str,
) -> bool:
    if "overlap" in task_text and len(arguments) >= 2:
        haystack, needle = arguments[0], arguments[1]
        if isinstance(haystack, str) and isinstance(needle, str) and needle:
            starts = [
                index
                for index in range(max(0, len(haystack) - len(needle) + 1))
                if haystack[index:index + len(needle)] == needle
            ]
            if any(
                right - left < len(needle)
                for left, right in zip(starts, starts[1:])
            ):
                return True
        return False

    if any(token in task_text for token in ("occurrence", "occur", "how many times")):
        if len(arguments) >= 2:
            container, target = arguments[0], arguments[1]
            if isinstance(container, str) and isinstance(target, str) and target:
                return sum(
                    container[index:index + len(target)] == target
                    for index in range(max(0, len(container) - len(target) + 1))
                ) >= 2
            if isinstance(container, list):
                return sum(item == target for item in container) >= 2

    case_insensitive = any(token in task_text for token in (
        "regardless of case", "case-insensitive", "case insensitive",
    ))

    def repeated(value: Any) -> bool:
        if isinstance(value, str):
            normalized = value.lower() if case_insensitive else value
            return len(normalized) > 1 and len(set(normalized)) < len(normalized)
        if isinstance(value, list):
            keys = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
            return (
                (len(keys) > 1 and len(set(keys)) < len(keys))
                or any(repeated(item) for item in value)
            )
        return False
    return any(repeated(argument) for argument in arguments)


def _probe_has_structural_tie(arguments: list[Any]) -> bool:
    def tied(value: Any) -> bool:
        if not isinstance(value, list) or len(value) < 2:
            return False
        sized_items = [
            (json.dumps(item, ensure_ascii=False, sort_keys=True), len(item))
            for item in value
            if isinstance(item, (str, list, tuple))
        ]
        return any(
            left_key != right_key and left_size == right_size
            for index, (left_key, left_size) in enumerate(sized_items)
            for right_key, right_size in sized_items[index + 1:]
        )
    return any(tied(argument) for argument in arguments)


def _probe_has_ordering(
    arguments: list[Any],
    expected_value: Any,
    task_text: str,
) -> bool:
    sorting_task = any(token in task_text for token in (
        "sorted", "ascending", "descending", "smallest to largest",
        "largest to smallest",
    ))
    descending = any(token in task_text for token in (
        "descending", "largest to smallest",
    ))
    if sorting_task:
        for argument in arguments:
            if isinstance(argument, list) and isinstance(expected_value, list):
                if len(argument) < 2 or argument == expected_value:
                    continue
                try:
                    if expected_value == sorted(argument, reverse=descending):
                        return True
                except TypeError:
                    input_keys = sorted(
                        json.dumps(item, ensure_ascii=False, sort_keys=True)
                        for item in argument
                    )
                    output_keys = sorted(
                        json.dumps(item, ensure_ascii=False, sort_keys=True)
                        for item in expected_value
                    )
                    if input_keys == output_keys:
                        return True
            if isinstance(argument, str) and isinstance(expected_value, str):
                input_tokens = argument.split()
                output_tokens = expected_value.split()
                if (
                    len(input_tokens) >= 2
                    and input_tokens != output_tokens
                    and sorted(input_tokens) == sorted(output_tokens)
                ):
                    numeral_order = {
                        word: index for index, word in enumerate(
                            "zero one two three four five six seven eight nine".split()
                        )
                    }
                    if all(token in numeral_order for token in input_tokens):
                        correct = sorted(
                            input_tokens,
                            key=numeral_order.__getitem__,
                            reverse=descending,
                        )
                        if output_tokens == correct:
                            return True
                    elif output_tokens == sorted(input_tokens, reverse=descending):
                        return True
        return False

    candidates = [expected_value, *arguments]
    for value in candidates:
        if isinstance(value, list) and len(value) >= 2:
            keys = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
            if len(set(keys)) >= 2:
                return True
        if isinstance(value, str) and any(token in task_text for token in (
            "space-delimited", "space delimited", "separated by spaces",
        )):
            tokens = value.split()
            if len(tokens) >= 2 and len(set(tokens)) >= 2:
                return True
    return False


def _probe_has_representation(
    arguments: list[Any],
    expected_value: Any,
    task_ir: dict[str, Any],
) -> bool:
    input_kinds = {
        (parameter.get("dafny_type") or {}).get("kind")
        for parameter in task_ir.get("parameters") or []
    }
    output_kind = (task_ir.get("return_type") or {}).get("kind")
    numeric = {"integer", "real"}
    if input_kinds & numeric and output_kind == "string":
        if not isinstance(expected_value, str) or not expected_value:
            return False
        for argument, parameter in zip(arguments, task_ir.get("parameters") or []):
            kind = (parameter.get("dafny_type") or {}).get("kind")
            if kind not in numeric or isinstance(argument, bool):
                continue
            if isinstance(argument, int) and (abs(argument) >= 10 or argument < 0):
                if str(argument) in expected_value:
                    return True
            if isinstance(argument, float) and abs(argument) >= 10:
                if str(argument) in expected_value:
                    return True
        return False
    if "string" in input_kinds and output_kind in numeric:
        return (
            isinstance(expected_value, (int, float))
            and not isinstance(expected_value, bool)
            and any(
                isinstance(argument, str)
                and len(re.findall(r"\d", argument)) >= 2
                for argument in arguments
            )
        )

    def concrete_text(value: Any) -> bool:
        if isinstance(value, str):
            return any(char.isdigit() or char.isspace() or not char.isalnum() for char in value)
        if isinstance(value, list):
            return any(concrete_text(item) for item in value)
        if isinstance(value, int) and not isinstance(value, bool):
            return abs(value) >= 10
        return False
    return any(concrete_text(value) for value in [*arguments, expected_value])


def _probe_has_threshold_endpoint(
    arguments: list[Any],
    task_ir: dict[str, Any],
) -> bool:
    parameters = task_ir.get("parameters") or []
    thresholds = [
        argument
        for argument, parameter in zip(arguments, parameters)
        if "threshold" in str(parameter.get("name") or "").lower()
        and isinstance(argument, (int, float))
        and not isinstance(argument, bool)
    ]
    numeric_sequences = [
        argument
        for argument, parameter in zip(arguments, parameters)
        if (parameter.get("dafny_type") or {}).get("kind") == "sequence"
        and isinstance(argument, list)
        and all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in argument
        )
    ]
    return any(
        abs(float(left) - float(right)) == float(threshold)
        for threshold in thresholds
        for sequence in numeric_sequences
        for index, left in enumerate(sequence)
        for right in sequence[index + 1:]
    )


def _has_decisive_last_contrast(
    probes: list[dict[str, Any]],
    task_ir: dict[str, Any],
) -> bool:
    for index, left in enumerate(probes):
        for right in probes[index + 1:]:
            if left.get("expected_value") == right.get("expected_value"):
                continue
            left_group = str(left.get("contrast_group", "")).strip()
            right_group = str(right.get("contrast_group", "")).strip()
            if not left_group or left_group != right_group:
                continue
            if _arguments_are_decisively_adjacent(
                left.get("arguments", []), right.get("arguments", []), task_ir
            ):
                return True
    return False


def _arguments_are_decisively_adjacent(
    left: list[Any],
    right: list[Any],
    task_ir: dict[str, Any],
) -> bool:
    if len(left) != len(right):
        return False
    parameters = task_ir.get("parameters") or []
    container_positions = {
        index
        for index, parameter in enumerate(parameters)
        if (parameter.get("dafny_type") or {}).get("kind")
        in {"sequence", "string", "variadic_tuple"}
    }
    changed_positions = [
        index for index, (a, b) in enumerate(zip(left, right)) if a != b
    ]
    if len(changed_positions) != 1:
        return False
    changed = changed_positions[0]
    # For tasks with container inputs, a scalar threshold tweak does not test a
    # last-position bug. Require an actual one-element suffix extension.
    if container_positions and changed not in container_positions:
        return False
    return _arguments_are_adjacent(left, right)


def _arguments_are_adjacent(left: list[Any], right: list[Any]) -> bool:
    if len(left) != len(right):
        return False
    changed = 0
    for a, b in zip(left, right):
        if a == b:
            continue
        if isinstance(a, list) and isinstance(b, list):
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            adjacent = len(longer) == len(shorter) + 1 and longer[:-1] == shorter
        elif isinstance(a, str) and isinstance(b, str):
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            adjacent = len(longer) == len(shorter) + 1 and longer[:-1] == shorter
        elif (
            isinstance(a, (int, float)) and not isinstance(a, bool)
            and isinstance(b, (int, float)) and not isinstance(b, bool)
        ):
            adjacent = abs(float(a) - float(b)) == 1.0
        else:
            adjacent = False
        if not adjacent:
            return False
        changed += 1
    return changed == 1


def _required_probe_tags(
    problem_desc: str,
    task_ir: dict[str, Any] | None = None,
) -> set[str]:
    text = (problem_desc or "").lower()
    tags = {"minimal_valid"}
    parameter_kinds = {
        (parameter.get("dafny_type") or {}).get("kind")
        for parameter in (task_ir or {}).get("parameters") or []
    }
    if task_ir is not None and "parameters" in task_ir:
        has_container_input = bool(
            parameter_kinds & {"sequence", "string", "variadic_tuple"}
        )
    else:
        # Compatibility fallback for callers without normalized TaskIR. This
        # cannot distinguish input from output prose, so production always
        # supplies TaskIR and uses the structural branch above.
        has_container_input = any(
            token in text for token in ("list", "sequence", "string", "seq<")
        )
    if has_container_input:
        tags.add("singleton")
    endpoint_language = any(token in text for token in (
        "at any point", "last operation", "only at the end", "final position",
        "inclusive", "upto", "up to", "first or last",
    ))
    prefix_or_suffix = bool(re.search(r"\b(?:prefix|suffix|postfix)(?:es)?\b", text))
    enumerates_all_prefixes = bool(re.search(r"\ball\s+(?:non[- ]empty\s+)?prefixes\b", text))
    if endpoint_language or (prefix_or_suffix and not enumerates_all_prefixes):
        tags.add("decisive_last")
    if any(token in text for token in (
        "inclusive", "upto", "up to", "only at the end", "final position",
        "first or last",
    )) or (
        "threshold" in text
        and any(token in text for token in ("closer than", "less than", "greater than"))
    ):
        tags.add("endpoint")
    if any(token in text for token in (
        "duplicate", "occur", "occurrence", "overlap", "how many times",
        "multiplicity", "distinct", "unique",
    )):
        tags.add("multiplicity")
    if (
        re.search(r"\btie(?:s|d)?\b", text)
        or any(token in text for token in (
            "same length", "equal length", "if multiple", "first occurrence",
            "lexicographic", "lexicographical",
        ))
    ):
        tags.add("tie")
    if any(token in text for token in (
        "space-delimited", "space delimited", "character code", "ascii code",
        "digits of", "digit appears", "numeric string", "string representation",
    )) or bool(re.search(
        r"\b(?:convert|conversion|represent)\b.{0,50}\b(?:string|integer|number)\b|"
        r"\b(?:integer|number)\s+to\s+(?:a\s+)?string\b",
        text,
    )):
        tags.add("representation")
    if any(token in text for token in (
        "preserve order", "keep order", "same order", "sorted", "ascending",
        "descending", "shortest to longest", "longest to shortest",
    )):
        tags.add("ordering")
    return tags


def public_example_probes(
    task_ir: dict[str, Any],
    *,
    entry_point: str,
) -> list[dict[str, Any]]:
    """Convert literal TaskIR doctests into trusted, deterministic probes."""
    probes = []
    for index, example in enumerate(task_ir.get("examples") or []):
        if not example.get("arguments_are_literal") or not example.get("expected_is_literal"):
            continue
        if example.get("call_name") not in {None, "", entry_point}:
            continue
        if example.get("keyword_args"):
            # Keyword/default binding can be added when the Dafny adapter gains
            # keyword invocation support; never guess positional order here.
            continue
        arguments = _json_native(example.get("positional_args", []))
        expected = _json_native(example.get("expected_value"))
        if arguments is _UNSUPPORTED_JSON or expected is _UNSUPPORTED_JSON:
            continue
        probes.append({
            "case": f"public_example_{index + 1}",
            "requirement": "Exact public doctest behavior",
            "arguments": arguments,
            "expected_value": expected,
            "within_task_domain": True,
            "expected_source": "public_example",
            "rationale": "Deterministically extracted from TaskIR, not generated by an LLM.",
            "coverage_tags": ["public_example"],
        })
    return probes


_UNSUPPORTED_JSON = object()


def _json_native(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        converted = [_json_native(item) for item in value]
        return _UNSUPPORTED_JSON if _UNSUPPORTED_JSON in converted else converted
    return _UNSUPPORTED_JSON


def _validate_probe_arguments(arguments: list[Any], task_ir: dict[str, Any]) -> None:
    params = task_ir.get("parameters") or []
    if not params:
        return
    if len(arguments) != len(params):
        raise ValueError(
            f"semantic probe arity mismatch: expected {len(params)}, got {len(arguments)}"
        )
    for value, parameter in zip(arguments, params):
        if not _value_matches_type(value, parameter.get("dafny_type") or {}):
            raise TypeError(
                f"semantic probe value for {parameter.get('name', '?')} does not match task type"
            )


def _value_matches_type(value: Any, type_ir: dict[str, Any]) -> bool:
    import math
    kind = type_ir.get("kind")
    children = type_ir.get("arguments") or []
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "real":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str)
    if kind in {"sequence", "variadic_tuple"}:
        return isinstance(value, list) and bool(children) and all(
            _value_matches_type(item, children[0]) for item in value
        )
    if kind == "tuple":
        return isinstance(value, list) and len(value) == len(children) and all(
            _value_matches_type(item, child) for item, child in zip(value, children)
        )
    if kind == "optional":
        return value is None or (bool(children) and _value_matches_type(value, children[0]))
    if kind == "unit":
        return value is None
    return True


def _probes_as_boundary_checks(probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "case": probe["case"],
            "input": repr(probe["arguments"]),
            "arguments": probe["arguments"],
            "expected": repr(probe["expected_value"]),
            "expected_value": probe["expected_value"],
            "spec_behavior": "computed_by_harness",
            "matches": True,
            "within_task_domain": True,
            "expected_source": probe["expected_source"],
            "probe_origin": (
                "public_example"
                if probe["expected_source"] == "public_example"
                else "nl_generated"
            ),
        }
        for probe in probes
    ]


def confirm_probe_expectation_with_llm(
    llm,
    *,
    problem_desc: str,
    entry_point: str,
    arguments: list[Any],
    expected_value: Any,
    task_ir: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute a failed probe's NL-side expectation without anchoring.

    The model never sees the proposed value. The harness compares its fresh
    answer locally, so a copied ``confirm`` label cannot substitute for an
    independent computation.
    """
    semantic_problem_desc = _semantic_task_description(problem_desc, task_ir or {})
    raw = llm.chat(
        system="""You independently compute one expected result from a programming
task. You do not see the candidate specification, its output, or any proposed
answer. Use only explicit task text/public examples. Return JSON only:
{"decision":"computed|abstain","expected_value":<JSON value>,
 "confidence":0.0,"rationale":"concise task-grounded computation"}.
Use computed only when the task determines an exact result. Use abstain when
the case is unspecified. Ensure expected_value and rationale agree exactly.""",
        user=(
            f"Entry point: {entry_point}\n\nTask:\n{semantic_problem_desc}\n\n"
            f"Arguments: {json.dumps(arguments, ensure_ascii=False)}\n"
            "Independently compute the task's expected return value."
        ),
        temperature=config.CRITIC_TEMPERATURE,
        max_tokens=min(600, config.CRITIC_PROBE_MAX_TOKENS),
    )
    try:
        payload = parse_critic_response(raw)
        decision = str(payload.get("decision", "")).strip().lower()
        confidence_raw = payload.get("confidence")
        if (
            isinstance(confidence_raw, bool)
            or not isinstance(confidence_raw, (int, float))
        ):
            raise TypeError("confirmation confidence must be numeric")
        confidence = float(confidence_raw)
        if "expected_value" not in payload:
            raise ValueError("confirmation expected_value is required")
        confirmed_value = payload.get("expected_value")
        rationale = str(payload.get("rationale", "")).strip()
        if not rationale:
            raise ValueError("confirmation rationale is required")
        return_type = (task_ir or {}).get("return_type") or {}
        if (
            decision == "computed"
            and return_type
            and not _value_matches_type(confirmed_value, return_type)
        ):
            raise TypeError("confirmation value does not match the task return type")
        if decision == "computed" and _confirm_rationale_disputes_value(rationale):
            return {
                "decision": "abstain",
                "confidence": 0.0,
                "expected_value": confirmed_value,
                "rationale": "Confirmation rationale contradicts the computed protocol.",
            }
        if decision == "computed":
            return {
                "decision": (
                    "confirm"
                    if _json_values_equivalent(confirmed_value, expected_value)
                    else "dispute"
                ),
                "confidence": max(0.0, min(1.0, confidence)),
                "expected_value": confirmed_value,
                "rationale": rationale,
            }
        if decision == "abstain":
            return {
                "decision": "abstain",
                "confidence": max(0.0, min(1.0, confidence)),
                "expected_value": confirmed_value,
                "rationale": rationale,
            }
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return {
        "decision": "abstain",
        "confidence": 0.0,
        "rationale": "Probe expectation confirmation was not parseable.",
    }


def _confirm_rationale_disputes_value(rationale: str) -> bool:
    """Reject a confirm label whose own explanation explicitly disputes it."""
    text = (rationale or "").lower()
    return any(re.search(pattern, text, flags=re.DOTALL) for pattern in CONTRADICTORY_CONFIRM_PATTERNS)


def _append_confirmed_probe_mismatch(
    report: dict[str, Any],
    *,
    pending_conflict: dict[str, Any],
    confirmation: dict[str, Any],
) -> None:
    """Promote an independently recomputed mismatch into repair evidence."""
    arguments = pending_conflict.get("arguments", [])
    expected = pending_conflict.get("expected")
    actual = pending_conflict.get("actual")
    report["issues"] = [
        *report.get("issues", []),
        {
            "category": "semantic_mismatch",
            "severity": "critical",
            "material": True,
            "requirement": "Independently recomputed task behavior",
            "spec_location": "executable Reference/helper",
            "explanation": (
                f"For arguments {arguments!r}, the task result is {expected!r}, "
                f"but the executable specification returned {actual!r}."
            ),
        },
    ]
    report["counterexamples"] = [
        *report.get("counterexamples", []),
        {
            "input": repr(arguments),
            "arguments": arguments if isinstance(arguments, list) else [arguments],
            "expected": repr(expected),
            "expected_value": expected,
            "spec_behavior": repr(actual),
            "rationale": (
                "Observed by executing the candidate specification and confirmed "
                "by an independent task-only recomputation: "
                + str(confirmation.get("rationale", "")).strip()
            ),
            "within_task_domain": True,
            "expected_source": "task_text",
            "matches_spec": False,
        },
    ]


def _probe_evidence_key(arguments: Any, expected_value: Any) -> str:
    """Identify semantic evidence independently of which source supplied it."""
    return json.dumps(
        [arguments, expected_value],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_values_equivalent(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= 1e-9 * max(1.0, abs(float(right)))
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_values_equivalent(a, b) for a, b in zip(left, right)
        )
    return left == right


def _review_public_preconditions(
    *,
    spec: str,
    entry_point: str,
    problem_desc: str,
    task_ir: dict[str, Any],
) -> dict[str, Any]:
    """Bind every public requires clause to explicit/definedness evidence."""
    from contract_utils import parse_method_contract

    contract = parse_method_contract(spec, entry_point)
    if contract is None:
        return {
            "status": "unresolved",
            "assessments": [],
            "unresolved_clauses": ["<unparseable public contract>"],
        }
    clauses = [
        clause
        for clause in contract.requires
        if re.sub(r"[\s()]", "", clause).lower() != "true"
    ]
    if not clauses:
        return {
            "status": "not_applicable",
            "assessments": [],
            "unresolved_clauses": [],
        }
    task_text = str(
        task_ir.get("raw_docstring")
        or task_ir.get("docstring")
        or problem_desc
    ).lower()
    parameter_kinds = {
        actual.name: ((expected.get("dafny_type") or {}).get("kind"))
        for actual, expected in zip(contract.params, task_ir.get("parameters") or [])
    }
    assessments = []
    unresolved = []
    for clause in clauses:
        atoms = _split_top_level_conjuncts(clause)
        atom_assessments = []
        for atom in atoms:
            evidence = _precondition_task_evidence(
                atom,
                parameter_names=[item.name for item in contract.params],
                parameter_kinds=parameter_kinds,
                task_text=task_text,
            )
            atom_assessments.append({
                "atom": atom,
                "status": "justified" if evidence else "unresolved",
                "evidence": evidence or {},
            })
        clause_justified = bool(atom_assessments) and all(
            item["status"] == "justified" for item in atom_assessments
        )
        assessments.append({
            "clause": clause,
            "status": "justified" if clause_justified else "unresolved",
            "atoms": atom_assessments,
        })
        if not clause_justified:
            unresolved.append(clause)
    return {
        "status": "passed" if not unresolved else "unresolved",
        "assessments": assessments,
        "unresolved_clauses": unresolved,
    }


def _match_has_output_subject(segment: str, match_start: int) -> bool:
    before = segment[:max(0, match_start)]
    return bool(re.search(
        r"\b(?:return|returns|returning|produce|produces)\s+"
        r"(?:(?:an?|the)\s+)?$|"
        r"\b(?:result|output)\b.{0,25}\b(?:is|will\s+be|should\s+be)\s+"
        r"(?:always\s+)?$",
        before,
        flags=re.IGNORECASE,
    ))


def _precondition_task_evidence(
    atom: str,
    *,
    parameter_names: list[str],
    parameter_kinds: dict[str, str | None],
    task_text: str,
) -> dict[str, str] | None:
    normalized = re.sub(r"\s+", "", atom.lower())
    normalized = re.sub(r"(?<=\d)\.0\b", "", normalized)
    normalized = _strip_balanced_outer_parentheses(normalized)

    def text_match(
        pattern: str,
        kind: str,
        *,
        parameter: str = "",
        allow_generic: bool = False,
        reject_output_context: bool = False,
    ) -> dict[str, str] | None:
        matches = list(re.finditer(pattern, task_text, flags=re.IGNORECASE | re.DOTALL))
        match = None
        for candidate in matches:
            segment_start = max(
                task_text.rfind(delimiter, 0, candidate.start())
                for delimiter in (".", ";", "\n")
            ) + 1
            following = [
                position for position in (
                    task_text.find(delimiter, candidate.end())
                    for delimiter in (".", ";", "\n")
                )
                if position >= 0
            ]
            segment_end = min(following) if following else len(task_text)
            segment = task_text[segment_start:segment_end]
            if reject_output_context and _match_has_output_subject(
                segment, candidate.start() - segment_start
            ):
                continue
            if allow_generic or not parameter:
                match = candidate
                break
            if re.search(
                r"\b" + re.escape(parameter.rstrip("_")) + r"\b",
                segment,
                flags=re.IGNORECASE,
            ):
                match = candidate
                break
        if match is None:
            return None
        return {
            "kind": kind,
            "parameter": parameter,
            "text": match.group(0).strip(),
        }

    for name in parameter_names:
        token = name.lower()
        base_name = token.rstrip("_")
        positive = normalized in {f"{token}>0", f"0<{token}"}
        nonnegative = normalized in {f"{token}>=0", f"0<={token}"}
        nonempty = normalized in {f"|{token}|>0", f"0<|{token}|"}

        if positive:
            evidence = text_match(
                r"(?<!zero or )(?<!or )(?<!non-)(?<!non )"
                r"\bpositive(?:\s+(?:floating[ -]point|integer|number|value))?\b",
                "explicit_task_constraint",
                parameter=base_name,
                allow_generic=len(parameter_names) == 1,
                reject_output_context=True,
            )
            if evidence:
                return evidence
        if nonnegative:
            evidence = text_match(
                r"\b(?:non[- ]?negative|not\s+negative|zero\s+or\s+positive|"
                r"greater\s+than\s+or\s+equal\s+to\s+zero)\b",
                "explicit_task_constraint",
                parameter=base_name,
                allow_generic=len(parameter_names) == 1,
                reject_output_context=True,
            )
            if evidence:
                return evidence
            sequence_pattern = (
                r"starting\s+from\s+0.{0,100}(?:up\s*to|upto)\s+"
                + re.escape(base_name)
                + r"\b"
            )
            evidence = text_match(
                sequence_pattern,
                "range_definedness",
                parameter=base_name,
                allow_generic=True,
            )
            if evidence:
                return evidence
        if nonempty:
            evidence = text_match(
                r"\b(?:non[- ]?empty|not\s+empty|at\s+least\s+one|one\s+or\s+more)\b",
                "explicit_task_constraint",
                parameter=base_name,
                allow_generic=len(parameter_names) == 1,
                reject_output_context=True,
            )
            if evidence:
                return evidence
            if parameter_kinds.get(name) in {"sequence", "variadic_tuple"}:
                evidence = text_match(
                    r"\b(?:mean\s+absolute\s+deviation|mean|average)\b",
                    "mathematical_definedness",
                    parameter=base_name,
                    allow_generic=(
                        sum(
                            kind in {"sequence", "variadic_tuple"}
                            for kind in parameter_kinds.values()
                        ) == 1
                    ),
                )
                if evidence:
                    return evidence

    lowered_parameter_names = [name.lower() for name in parameter_names]
    length_pair = next((
        (left, right)
        for left in lowered_parameter_names
        for right in lowered_parameter_names
        if left != right and normalized == f"|{left}|==|{right}|"
    ), None)
    if length_pair:
        left, right = (name.rstrip("_") for name in length_pair)
        for candidate in re.finditer(
            r"\b(?:same|equal)\s+length\b",
            task_text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            segment_start = max(
                task_text.rfind(delimiter, 0, candidate.start())
                for delimiter in (".", ";", "\n")
            ) + 1
            following = [
                position
                for position in (
                    task_text.find(delimiter, candidate.end())
                    for delimiter in (".", ";", "\n")
                )
                if position >= 0
            ]
            segment_end = min(following) if following else len(task_text)
            segment = task_text[segment_start:segment_end]
            if all(
                re.search(r"\b" + re.escape(name) + r"\b", segment)
                for name in (left, right)
            ):
                return {
                    "kind": "explicit_task_constraint",
                    "parameter": f"{left},{right}",
                    "text": candidate.group(0).strip(),
                }
    return None


def _strip_balanced_outer_parentheses(expression: str) -> str:
    value = expression
    while len(value) >= 2 and value[0] == "(" and value[-1] == ")":
        depth = 0
        closes_at_end = False
        for index, char in enumerate(value):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    closes_at_end = index == len(value) - 1
                    break
        if not closes_at_end:
            break
        value = value[1:-1]
    return value


def _split_top_level_conjuncts(clause: str) -> list[str]:
    clause = _strip_balanced_outer_parentheses(clause.strip())
    parts = []
    start = 0
    depth = 0
    index = 0
    while index < len(clause):
        char = clause[index]
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth > 0:
            depth -= 1
        elif depth == 0 and clause[index:index + 2] == "&&":
            part = clause[start:index].strip()
            if part:
                parts.append(part)
            index += 2
            start = index
            continue
        index += 1
    tail = clause[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _task_signature_issues(
    *,
    spec: str,
    entry_point: str,
    task_ir: dict[str, Any],
) -> list[str]:
    """Compare the candidate method to the deterministic TaskIR signature."""
    if not task_ir or not task_ir.get("supported", True):
        return []
    if "parameters" not in task_ir or not task_ir.get("return_type"):
        return []
    from contract_utils import parse_method_contract
    from task_normalizer import render_dafny_signature

    expected_source = render_dafny_signature(task_ir)
    expected = parse_method_contract(expected_source, entry_point)
    actual = parse_method_contract(spec, entry_point)
    if expected is None:
        return ["Harness could not render/parse the expected TaskIR signature."]
    if actual is None:
        return [f"Candidate is missing public method `{entry_point}` or its signature is unparseable."]

    issues = []
    if actual.name != expected.name:
        issues.append(f"method name differs: expected {expected.name}, got {actual.name}")
    if actual.signature_types != expected.signature_types:
        issues.append(
            "parameter/return types differ: "
            f"expected {expected.signature_types!r}, got {actual.signature_types!r}"
        )
    expected_param_names = tuple(item.name for item in expected.params)
    actual_param_names = tuple(item.name for item in actual.params)
    if actual_param_names != expected_param_names:
        issues.append(
            f"parameter names/order differ: expected {expected_param_names!r}, "
            f"got {actual_param_names!r}"
        )
    expected_return_names = tuple(item.name for item in expected.returns)
    actual_return_names = tuple(item.name for item in actual.returns)
    if actual_return_names != expected_return_names:
        issues.append(
            f"return names/order differ: expected {expected_return_names!r}, "
            f"got {actual_return_names!r}"
        )
    return issues


def _semantic_task_description(
    problem_desc: str,
    task_ir: dict[str, Any],
) -> str:
    """Project a generation prompt down to task semantics for blind probes."""
    docstring = str(
        task_ir.get("raw_docstring") or task_ir.get("docstring") or ""
    ).strip()
    if not docstring:
        return problem_desc
    signature = str(task_ir.get("signature") or "").strip()
    parts = []
    if signature:
        parts.append("Python signature:\n" + signature)
    parts.append("Function description and public examples:\n" + docstring)
    return "\n\n".join(parts)


def _contains_unjustified_empty_argument(
    arguments: list[Any],
    task_ir: dict[str, Any],
) -> bool:
    """Reject invented empty-container behavior from otherwise valid probes."""
    parameters = task_ir.get("parameters") or []
    if not parameters:
        return False
    for index, (argument, parameter) in enumerate(zip(arguments, parameters)):
        kind = (parameter.get("dafny_type") or {}).get("kind")
        if kind not in {"sequence", "string", "variadic_tuple"}:
            continue
        if argument not in ([], ""):
            continue
        if not _empty_argument_is_explicit(index, task_ir):
            return True
    return False


def _empty_argument_is_explicit(index: int, task_ir: dict[str, Any]) -> bool:
    """Return whether an empty value is explicitly in one parameter's public domain.

    A mention of an internal empty value (or a statement that something must be
    non-empty) must not silently authorize an empty public input. Public examples
    are bound positionally; prose evidence is bound to the parameter whenever a
    task has more than one container argument.
    """
    examples = task_ir.get("examples") or []
    entry_point = str(task_ir.get("entry_point") or "").strip()
    if any(
        example.get("arguments_are_literal")
        and (
            not entry_point
            or str(example.get("call_name") or "").strip() in {"", entry_point}
        )
        and len(example.get("positional_args") or []) > index
        and (example.get("positional_args") or [])[index] in ([], "", ())
        for example in examples
    ):
        return True

    parameters = task_ir.get("parameters") or []
    if index >= len(parameters):
        return False
    container_parameters = [
        parameter
        for parameter in parameters
        if (parameter.get("dafny_type") or {}).get("kind")
        in {"sequence", "string", "variadic_tuple"}
    ]
    parameter_name = str(parameters[index].get("name") or "").rstrip("_").lower()
    task_text = str(
        task_ir.get("raw_docstring") or task_ir.get("docstring") or ""
    ).lower()
    empty_pattern = re.compile(
        r"\bempty\b|\bzero[- ]length\b|\blength\s+(?:is|=|of)\s*0\b"
    )
    for match in empty_pattern.finditer(task_text):
        segment_start = max(
            task_text.rfind(delimiter, 0, match.start())
            for delimiter in (".", ";", "\n")
        ) + 1
        following = [
            position
            for position in (
                task_text.find(delimiter, match.end())
                for delimiter in (".", ";", "\n")
            )
            if position >= 0
        ]
        segment_end = min(following) if following else len(task_text)
        segment = task_text[segment_start:segment_end]
        relative_start = match.start() - segment_start
        before_match = segment[:relative_start]
        # Exclusions and invalid-domain statements describe non-membership, not
        # behavior for an empty public argument.
        if re.search(
            r"\bnon[- ]empty\b|\b(?:not|never|cannot|can't)\s+(?:be\s+)?empty\b|"
            r"\bempty\b.{0,40}\b(?:invalid|undefined|disallowed|not allowed|error)\b|"
            r"\b(?:invalid|undefined|disallowed)\b.{0,40}\bempty\b",
            segment,
        ):
            continue
        # Do not confuse an empty output with permission to call the function
        # on an empty input ("return an empty list if nothing matches").
        if re.search(
            r"\b(?:return|returns|returning|result|output|produce|produces)"
            r"(?:\s+(?:is|will\s+be|should\s+be))?\s+(?:an?\s+)?$",
            before_match,
        ):
            continue
        parameter_bound = bool(
            parameter_name
            and re.search(
                r"(?:\b" + re.escape(parameter_name)
                + r"\b\s+(?:is|may\s+be|can\s+be|might\s+be)\s+empty\b)|"
                r"(?:\bempty\s+" + re.escape(parameter_name) + r"\b)",
                segment,
            )
        )
        generic_input_bound = bool(re.search(
            r"\b(?:input|argument)(?:\s+(?:list|string|sequence|array))?\b.{0,30}\bempty\b|"
            r"\bempty\s+(?:input|argument)\b|"
            r"\b(?:list|string|sequence|array)\s+(?:may|can|might)\s+be\s+empty\b|"
            r"\b(?:if|when|for|given)\s+(?:an?\s+)?empty\s+"
            r"(?:list|string|sequence|array)\b",
            segment,
        ))
        if parameter_bound or (len(container_parameters) == 1 and generic_input_bound):
            return True
    return False


def _counterexamples_as_boundary_checks(
    counterexamples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "case": "critic_counterexample",
            "input": item.get("input", repr(item.get("arguments"))),
            "arguments": item["arguments"],
            "expected": item.get("expected", repr(item.get("expected_value"))),
            "expected_value": item["expected_value"],
            "spec_behavior": item.get("spec_behavior", "computed_by_harness"),
            "matches": False,
            "within_task_domain": item.get("within_task_domain") is True,
            "expected_source": item.get("expected_source", "inferred"),
            "probe_origin": "critic_counterexample",
        }
        for item in counterexamples
        if isinstance(item.get("arguments"), list) and "expected_value" in item
    ]


def execute_approved_boundary_checks(
    report: dict[str, Any],
    *,
    spec: str,
    entry_point: str,
    additional_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute NL-derived probes against an executable Reference specification.

    The LLM proposes expected behaviors from the task, but the harness—not the
    LLM—computes what the Dafny specification actually returns.  This catches
    hallucinated symbolic traces such as using an out-of-domain quantifier
    witness while preserving the official holdout as a final-only oracle.
    """
    original_decision = report.get("decision")
    if original_decision not in {"approve", "reject"} or not entry_point:
        return report
    rejection_replay = (
        original_decision == "reject"
        or report.get("audit_decision") == "reject"
    )
    # An approving audit's symbolic traces are not independent evidence and
    # can contain serialization mistakes (for example, quote characters folded
    # into a string argument). Only replay Critic-authored checks when auditing
    # an actual rejection; approval is tested by public/spec-blind probes.
    critic_boundaries = (
        [
            {**check, "probe_origin": "critic_boundary"}
            for check in report.get("boundary_checks", [])
        ]
        if rejection_replay
        else []
    )
    candidate_checks = [*(additional_checks or []), *critic_boundaries]
    checks = [
        check for check in candidate_checks
        if check.get("within_task_domain") is True
        and str(check.get("expected_source", "")).strip().lower() in GROUNDED_SOURCES
    ]
    # A rejection's grounded evidence is mandatory and therefore ordered first.
    # Every public/spec-blind probe is also mandatory for *approval*: a probe
    # that happened to fall after a configured slice must never be described as
    # having passed. Deduplication still lets a trusted public example displace
    # an equivalent LLM-authored case.
    priority = {
        "public_example": 0,
        "nl_generated": 1,
        "critic_counterexample": 2,
        "critic_boundary": 3,
    }
    required_reject_keys = set()
    if rejection_replay:
        required_reject_keys.update(
            _probe_evidence_key(item.get("arguments"), item.get("expected_value"))
            for item in report.get("counterexamples", [])
            if _grounded_counterexample(item)
        )
        required_reject_keys.update(
            _probe_evidence_key(item.get("arguments"), item.get("expected_value"))
            for item in report.get("boundary_checks", [])
            if item.get("within_task_domain") is True
            and item.get("matches") is False
            and str(item.get("expected_source", "")).strip().lower()
            in GROUNDED_SOURCES
        )
    required_approval_keys = {
        _probe_evidence_key(item.get("arguments"), item.get("expected_value"))
        for item in checks
        if item.get("probe_origin") not in {"critic_counterexample", "critic_boundary"}
    }
    required_execution_keys = required_reject_keys | required_approval_keys
    checks.sort(key=lambda item: (
        0
        if _probe_evidence_key(item.get("arguments"), item.get("expected_value"))
        in required_reject_keys
        else (
            1
            if _probe_evidence_key(item.get("arguments"), item.get("expected_value"))
            in required_approval_keys
            else 2
        ),
        priority.get(item.get("probe_origin", ""), 3),
    ))
    deduped = []
    seen = set()
    for check in checks:
        key = _probe_evidence_key(
            check.get("arguments"), check.get("expected_value")
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(check)
    total_checks = len(deduped)
    checks = [
        check
        for check in deduped
        if _probe_evidence_key(check.get("arguments"), check.get("expected_value"))
        in required_execution_keys
    ]
    if not checks:
        return report

    from contract_utils import build_direct_reference_program
    from dafny_wrapper import DafnyVerifier
    from humaneval_tester import run_humaneval_test

    code = build_direct_reference_program(spec, entry_point)
    if not code:
        report["executable_boundary_checks"] = {
            "status": "not_applicable",
            "reason": "no_direct_executable_reference",
        }
        report["decision"] = "abstain"
        report["confidence"] = 0.0
        report["summary"] = "Candidate specification has no directly executable reference for probe validation."
        return report
    verification = DafnyVerifier().verify(code)
    if not verification.passed:
        diagnostics = [
            {
                "error_type": str(getattr(error, "error_type", "")),
                "subtype": str(getattr(error, "subtype", "")),
                "message": str(getattr(error, "message", ""))[:500],
                "line": int(getattr(error, "location_line", 0) or 0),
            }
            for error in (getattr(verification, "errors", None) or [])
        ]
        timed_out = any(
            item["error_type"] == "timeout" or item["subtype"] == "timeout"
            for item in diagnostics
        )
        report["executable_boundary_checks"] = {
            "status": "execution_error" if timed_out else "not_executable",
            "dafny_error_count": verification.error_count,
            "dafny_errors": diagnostics,
        }
        if timed_out:
            report["decision"] = "abstain"
            report["confidence"] = 0.0
            report["summary"] = (
                "Dafny timed out while preparing the executable specification; "
                "semantic approval is withheld without blaming the contract."
            )
            return report

        # Once a direct Reference implementation has been constructed, a
        # deterministic Dafny resolution/verification failure is actionable
        # contract evidence rather than missing semantic evidence. Route it to
        # bounded spec repair instead of ending the pipeline as an abstention.
        detail = "; ".join(
            item["message"] or item["subtype"] or item["error_type"]
            for item in diagnostics[:3]
        ) or f"Dafny reported {verification.error_count} error(s)."
        report["decision"] = "reject"
        report["confidence"] = 1.0
        report["summary"] = (
            "The candidate contract's direct Reference implementation does not "
            "resolve or verify and must be repaired before semantic certification."
        )
        report["issues"] = [
            *report.get("issues", []),
            {
                "category": "dafny_validity",
                "severity": "high",
                "material": True,
                "requirement": (
                    "The executable Reference/helper and public contract must "
                    "resolve and verify in Dafny."
                ),
                "spec_location": "executable Reference/helper",
                "explanation": detail,
            },
        ]
        return report

    comparator = '''def _critic_equal(actual, expected):
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual == expected
    if expected is None:
        return actual is None
    if isinstance(expected, str):
        return isinstance(actual, str) and actual == expected
    if isinstance(expected, float):
        if isinstance(actual, bool):
            return False
        try:
            return abs(float(actual) - expected) <= 1e-9 * max(1.0, abs(expected))
        except (TypeError, ValueError, OverflowError):
            return False
    if isinstance(expected, int):
        if isinstance(actual, bool):
            return False
        if actual == expected:
            return True
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError, OverflowError):
            return False
    if isinstance(expected, list):
        try:
            actual_items = list(actual)
        except (TypeError, ValueError):
            return False
        return len(actual_items) == len(expected) and all(
            _critic_equal(a, e) for a, e in zip(actual_items, expected)
        )
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(
            _critic_equal(actual[key], expected[key]) for key in expected
        )
    return actual == expected
'''
    # MAX_EXECUTED_CRITIC_PROBES is a per-process batch limit, not an evidence
    # truncation limit. Execute all mandatory evidence in deterministic batches.
    batch_size = max(1, int(config.MAX_EXECUTED_CRITIC_PROBES))
    passed = True
    detail: dict[str, Any] = {"error": None}
    failed_index = -1
    completed_or_failed_checks = 0
    batch_results = []
    for offset in range(0, len(checks), batch_size):
        batch = checks[offset:offset + batch_size]
        assertions = []
        for check in batch:
            args = ", ".join(repr(value) for value in check["arguments"])
            assertions.append(
                f"    assert _critic_equal(candidate({args}), {check['expected_value']!r})"
            )
        test_code = comparator + "\ndef check(candidate):\n" + "\n".join(assertions) + "\n"
        batch_passed, batch_detail = run_humaneval_test(
            code,
            {
                "task_id": "critic-boundary-probe",
                "entry_point": entry_point,
                "test": test_code,
            },
        )
        batch_results.append({
            "offset": offset,
            "scheduled": len(batch),
            "passed": bool(batch_passed),
            "error": batch_detail.get("error"),
        })
        if batch_passed:
            completed_or_failed_checks = offset + len(batch)
            continue
        passed = False
        detail = batch_detail
        try:
            local_failed_index = int(batch_detail.get("assertions_passed", 0) or 0)
        except (TypeError, ValueError):
            local_failed_index = 0
        local_failed_index = max(0, min(local_failed_index, len(batch) - 1))
        failed_index = offset + local_failed_index
        completed_or_failed_checks = failed_index + 1
        break

    executed_check_keys = {
        _probe_evidence_key(check.get("arguments"), check.get("expected_value"))
        for check in checks[:completed_or_failed_checks]
    }
    missing_required_reject_keys = required_reject_keys - executed_check_keys
    missing_required_approval_keys = required_approval_keys - executed_check_keys
    infrastructure_failure = not passed and (
        "failing_input" not in detail or detail.get("failing_input") is None
    )
    status = "passed" if passed else ("execution_error" if infrastructure_failure else "failed")
    report["executable_boundary_checks"] = {
        "status": status,
        "checks_run": completed_or_failed_checks,
        "checks_scheduled": len(checks),
        "checks_total": total_checks,
        "checks_truncated": max(0, total_checks - len(checks)),
        "batches_run": len(batch_results),
        "batch_results": batch_results,
        "required_reject_evidence_missing": len(missing_required_reject_keys),
        "required_approval_evidence_missing": len(missing_required_approval_keys),
        "error": detail.get("error"),
        "failing_input": detail.get("failing_input"),
        "expected": detail.get("expected"),
        "actual": detail.get("actual"),
    }
    if passed:
        if rejection_replay:
            grounded_claim_keys = {
                _probe_evidence_key(item.get("arguments"), item.get("expected_value"))
                for item in report.get("counterexamples", [])
                if _grounded_counterexample(item)
            }
            rejection_was_concretely_tested = bool(
                grounded_claim_keys or report.get("discarded_probe_conflicts")
            )
            all_reject_evidence_replayed = (
                rejection_was_concretely_tested
                and required_reject_keys <= executed_check_keys
            )
            all_approval_evidence_replayed = (
                bool(required_approval_keys)
                and required_approval_keys <= executed_check_keys
            )
            if (
                report.get("probe_generation", {}).get("status") == "generated"
                and all_reject_evidence_replayed
                and all_approval_evidence_replayed
            ):
                report["decision"] = "abstain"
                report["confidence"] = 0.0
                report["summary"] = (
                    "Executable replay disproved the Critic's claimed evidence and all "
                    "independent/public probes passed; a fresh whole-spec audit is still "
                    "required before approval."
                )
                report["provisional_audit_rejection_overturned"] = True
                report["needs_reconciliation_audit"] = True
            else:
                report["decision"] = "abstain"
                report["confidence"] = 0.0
                report["summary"] = "Critic rejection could not be replayed conclusively."
        return report
    if infrastructure_failure:
        report["decision"] = "abstain"
        report["confidence"] = 0.0
        report["summary"] = (
            "Executable Critic probes could not run reliably; semantic approval is withheld."
        )
        return report

    failing_input = detail.get("failing_input")
    failed_check = checks[failed_index] if 0 <= failed_index < len(checks) else {}
    expected = (
        checks[failed_index].get("expected_value")
        if 0 <= failed_index < len(checks)
        else detail.get("expected")
    )
    actual = detail.get("actual")
    if failed_check.get("probe_origin") in {"critic_counterexample", "critic_boundary"}:
        report["decision"] = "abstain"
        report["confidence"] = 0.0
        report["summary"] = (
            "Critic-authored counterexample mismatched the specification but lacks "
            "independent executable confirmation."
        )
        report["pending_probe_conflict"] = {
            "arguments": failed_check.get("arguments", []),
            "expected": expected,
            "actual": actual,
            "case": failed_check.get("case", ""),
            "origin": failed_check.get("probe_origin"),
        }
        return report
    if failed_check.get("probe_origin") == "nl_generated":
        report["decision"] = "abstain"
        report["confidence"] = 0.0
        report["summary"] = "NL-derived executable probe mismatch awaits independent confirmation."
        report["pending_probe_conflict"] = {
            "arguments": failed_check.get("arguments", []),
            "expected": expected,
            "actual": actual,
            "case": failed_check.get("case", ""),
            "origin": "nl_generated",
        }
        return report
    report["decision"] = "reject"
    report["confidence"] = 1.0
    report["summary"] = (
        "Executable task-grounded Critic probe disproved the candidate specification."
    )
    report["issues"] = [
        *report.get("issues", []),
        {
            "category": "semantic_mismatch",
            "severity": "critical",
            "material": True,
            "requirement": "Task-grounded executable boundary behavior",
            "spec_location": "executable Reference/helper",
            "explanation": (
                f"For input {failing_input!r}, task-derived expected value is "
                f"{expected!r}, but executing the specification produced {actual!r}."
            ),
        },
    ]
    report["counterexamples"] = [
        *report.get("counterexamples", []),
        {
            "input": repr(failing_input),
            "arguments": failing_input if isinstance(failing_input, list) else [failing_input],
            "expected": repr(expected),
            "expected_value": expected,
            "spec_behavior": repr(actual),
            "rationale": "Observed by executing the candidate Dafny specification.",
            "within_task_domain": True,
            "expected_source": "task_text",
            "matches_spec": False,
        },
    ]
    return report


def _system_prompt() -> str:
    return """You are an independent semantic auditor for Dafny specifications.
Your task is to decide whether the candidate specification faithfully captures
the supplied natural-language task. You are not the specification author and
must not rewrite the specification.

Audit rules:
- Inspect the bodies of every Reference/helper function, not only method ensures.
- Trace public examples manually against the helper definitions.
- Audit semantic fidelity only. Syntax, type checking, termination annotations,
  proof difficulty and Dafny resolvability are handled by deterministic gates.
  You may record them as category=dafny_validity with material=false, but they
  can never justify REJECT.
- Use only requirements explicitly stated in the task text or public examples.
  Do not invent behavior for malformed inputs, unequal lengths, empty values,
  padding, or other cases the task leaves unspecified. Mark such reasoning as
  expected_source=inferred or ambiguous; it can never justify REJECT.
- Treat the source signature types as the default input domain. A public
  requires clause needs an explicit task restriction or a recognized
  mathematical-definedness reason. If neither exists, ABSTAIN for unresolved
  domain narrowing; REJECT only when an explicitly valid input is excluded and
  you can provide a grounded counterexample.
- Search for concrete counterexamples and boundary errors: inclusive/exclusive
  indices, empty/singleton inputs, first/last and shortest/longest choices,
  ordering, multiplicity, tie-breaking, numeric conversion and character codes.
- Do not trust a helper's name or comments. Expand its base and recursive cases
  to determine the function it actually computes.
- Mandatory adversarial audit: test at least two concrete valid boundary cases.
  For sequence/string tasks, include a singleton and a case where the decisive
  event or required element occurs only at the final position. For indexed
  prefix helpers, explicitly determine whether the endpoint is included. For
  choice tasks, test ties and shortest/longest direction. For numeric-to-char
  conversion, check concrete code points such as 0, 1, 9 and 10.
- Check every public requires clause against the task's input domain.
- Dafny resolvability or a strong-looking contract is not evidence of semantic fidelity.
- Do not use or request hidden benchmark tests.
- APPROVE when no task-grounded material semantic mismatch exists. It is valid
  and expected to approve a correct specification. Do not invent a defect or
  keep searching merely to justify rejection.
- REJECT only with two aligned forms of evidence: a high/critical material
  semantic_mismatch issue and a concrete within-domain counterexample whose
  expected behavior comes from task_text/public_example and differs from the spec.
- ABSTAIN only when ambiguity blocks the core task interpretation or a material
  helper cannot be assessed.
- Keep the report concise: at most 3 issues, 3 counterexamples and 4 boundary
  checks. Never include internal deliberation or self-correction in strings.
- Return JSON only. Do not include markdown or a repaired specification.

Required JSON schema:
{
  "decision": "approve|reject|abstain",
  "confidence": 0.0,
  "summary": "concise audit conclusion",
  "issues": [
    {
      "category": "semantic_mismatch|input_domain|ambiguity|dafny_validity",
      "severity": "low|medium|high|critical",
      "material": true,
      "requirement": "requirement from the task",
      "spec_location": "clause or helper",
      "explanation": "precise semantic mismatch"
    }
  ],
  "counterexamples": [
    {
      "input": "concrete input",
      "arguments": ["JSON-native positional argument values"],
      "expected": "behavior required by task",
      "expected_value": "JSON-native expected return value",
      "spec_behavior": "behavior defined by spec",
      "rationale": "why they differ",
      "within_task_domain": true,
      "expected_source": "task_text|public_example|inferred|ambiguous",
      "matches_spec": false
    }
  ],
  "boundary_checks": [
    {
      "case": "what semantic boundary is tested",
      "input": "concrete valid input",
      "arguments": ["JSON-native positional argument values"],
      "expected": "behavior required by task",
      "expected_value": "JSON-native expected return value",
      "spec_behavior": "behavior obtained by expanding the spec helpers",
      "matches": true,
      "within_task_domain": true,
      "expected_source": "task_text|public_example|inferred|ambiguous"
    }
  ]
}"""


def _review_system_prompt() -> str:
    return """You are the final neutral judge for a semantic specification audit.
The previous audit is untrusted evidence, not a conclusion. Independently
recompute its boundary cases and return a concise corrected report. Approval is
a valid outcome; do not feel obligated to find a defect.

Mandatory checks:
- Respect every quantifier domain, slice endpoint, function precondition and
  recursion base case. A proposed witness is invalid unless it satisfies the
  written bound. Enumerate eligible indices for singleton and short inputs.
- For every quantified prefix computation, explicitly test a singleton where
  the first/last element alone is decisive and a longer input where only the
  final element changes the answer. Enumerate the legal quantified indices
  before evaluating the helper; never use i=|xs| when the bound is i<|xs|.
- Never infer behavior from a helper name. Expand the actual helper body.
- Reject only for behavior contradicted by explicit task text or a public
  example on an input within the stated task domain. Never invent semantics for
  unspecified malformed/empty/unequal-length inputs.
- Do not reject for Dafny syntax, typing, decreases/termination, proof effort or
  implementation difficulty; deterministic gates handle those separately.
- If the prior report says or implies that the specification is correct, its
  final decision must not be reject. Remove superseded issues and deliberation.
- Every reject must contain a material semantic_mismatch issue and an aligned
  task-grounded counterexample. Otherwise approve when no
  material mismatch remains, or abstain only for core ambiguity.
- Recheck decisive-last-position, empty/singleton, endpoint inclusivity,
  shortest/longest, ties, ordering/multiplicity and representation conversions
  whenever relevant.
- Return a complete replacement audit using exactly the same JSON schema as the
  initial critic. Use at most 3 issues, 3 counterexamples and 4 boundary checks.
  Return JSON only, with no internal monologue and no repaired Dafny code."""


def _probe_system_prompt() -> str:
    return """You generate executable semantic probes from a programming task.
You are independent of both the specification author and semantic auditor. You
will NOT see the candidate specification. Derive expected results only from the
task text and public examples.

Rules:
- Return 4 to 6 distinct, concrete probes using JSON-native positional arguments
  and JSON-native expected return values.
- Include public examples when literal, then add high-discrimination boundary
  probes not already shown publicly.
- For sequence/string tasks, include a singleton or shortest valid input and a
  case where the decisive event/value occurs only at the final position.
- When relevant, cover inclusive endpoints, duplicates/multiplicity, ordering,
  ties/first occurrence, overlapping matches, already-satisfied inputs, and
  concrete representation conversions.
- Do not invent behavior for malformed inputs or cases the task leaves
  unspecified. Omit such probes entirely.
- Every probe must be within the explicit task domain. expected_source must be
  task_text. Public examples are injected deterministically by the harness.
- coverage_tags must describe what the probe actually covers, chosen from:
  minimal_valid, singleton, decisive_last, tie, multiplicity, representation,
  endpoint, ordering.
- When decisive_last is required, emit two probes with the same non-empty
  contrast_group: a baseline and an input formed by appending exactly one final
  element (or incrementing one numeric endpoint by one). Their expected values
  must differ, and at least the extended probe must carry decisive_last.
- Compute each expected value before writing the JSON. The expected_value and
  rationale must agree exactly. Do not include recalculations, corrections,
  uncertainty, or a superseded value in the rationale; such a suite is invalid.
- Keep rationale and requirement concise. Return JSON only, no markdown.

Schema:
{
  "probes": [
    {
      "case": "short boundary name",
      "requirement": "explicit task behavior being exercised",
      "arguments": ["JSON-native positional arguments"],
      "expected_value": "JSON-native expected return value",
      "within_task_domain": true,
      "expected_source": "task_text",
      "rationale": "why this probe discriminates likely semantic errors",
      "coverage_tags": ["minimal_valid", "singleton"],
      "contrast_group": "shared id for adjacent decisive_last probe pairs, else empty"
    }
  ]
}"""


def _probe_user_prompt(
    *,
    problem_desc: str,
    entry_point: str,
    last_error: str,
    required_tags: set[str],
) -> str:
    retry = ""
    if last_error:
        retry = (
            "\n\nThe previous probe suite was invalid: "
            + last_error
            + "\nReturn one corrected JSON object only."
        )
    return f"""Target entry point: {entry_point or "(not supplied)"}

Natural-language task and public examples:
---
{problem_desc}
---

Required coverage tags for this task: {", ".join(sorted(required_tags))}

Generate a compact executable semantic probe suite. Every required tag must
appear on at least one probe and must accurately describe that probe.{retry}"""


def _review_user_prompt(
    *,
    problem_desc: str,
    spec: str,
    entry_point: str,
    prior_report: dict[str, Any],
    last_error: str,
) -> str:
    retry = ""
    if last_error:
        retry = (
            "\n\nYour previous validation response was invalid: "
            + last_error
            + "\nReturn exactly one complete JSON audit object."
        )
    return f"""Target entry point: {entry_point or "(not supplied)"}

Natural-language task and public examples:
---
{problem_desc}
---

Candidate Dafny specification:
```dafny
{spec}
```

Untrusted previous audit:
{json.dumps(prior_report, ensure_ascii=False, indent=2)}

    Independently validate and replace the audit.{retry}"""


def _reconciliation_user_prompt(
    *,
    problem_desc: str,
    spec: str,
    entry_point: str,
    disproved_evidence: dict[str, Any],
    last_error: str,
) -> str:
    retry = ""
    if last_error:
        retry = (
            "\n\nYour previous reconciliation response was invalid: "
            + last_error
            + "\nReturn exactly one complete JSON audit object."
        )
    return f"""Target entry point: {entry_point or "(not supplied)"}

Natural-language task and public examples:
---
{problem_desc}
---

Candidate Dafny specification:
```dafny
{spec}
```

A previous audit rejected this specification, but direct execution disproved
the concrete evidence below. Discard only those claims; do not assume the
specification is correct. Perform a fresh whole-spec semantic audit from the
task and helper bodies. Search for any *other* material mismatch. Approve only
if none remains; abstain for genuine task ambiguity.

The deterministic Dafny verification fact and passed public examples below are
authoritative: do not repeat claims that the Reference is syntactically/
semantically undefined or that it fails those exact public cases. Spec-blind
generated probes are supporting evidence, not a replacement for task semantics;
you may challenge their expected values if the task contradicts them.
If you APPROVE, every grounded boundary_check must copy an exact
arguments/expected_value pair from passed_public_examples or
passed_spec_blind_probes below. Do not introduce an unexecuted approval trace.

Disproved evidence:
{json.dumps(disproved_evidence, ensure_ascii=False, indent=2)}

Return a complete replacement audit using the required schema.{retry}"""


def _user_prompt(
    *,
    problem_desc: str,
    spec: str,
    entry_point: str,
    last_error: str,
) -> str:
    retry = ""
    if last_error:
        retry = (
            "\n\nYour previous response was invalid: "
            + last_error
            + "\nReturn exactly one JSON object matching the schema."
        )
    return f"""Target entry point: {entry_point or "(not supplied)"}

Natural-language task and public examples:
---
{problem_desc}
---

Candidate Dafny specification:
```dafny
{spec}
```

Audit semantic fidelity. Do not produce replacement Dafny code.{retry}"""


__all__ = [
    "critic_feedback_obligations",
    "execute_approved_boundary_checks",
    "generate_task_probes_with_llm",
    "public_example_probes",
    "normalize_critic_report",
    "parse_critic_response",
    "review_spec_with_llm",
]
