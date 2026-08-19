"""Deterministic contract and Dafny verification behind one small interface."""

from __future__ import annotations

import re

from artifacts import SpecArtifact, VerificationEvidence
from contract_utils import contract_fidelity_issues, reference_implementation_calls
from dafny_wrapper import ErrorInfo, VerificationResult


class VerificationEngine:
    """Check one frozen specification/candidate pair."""

    def __init__(self, verifier, *, allow_reference_implementation: bool = False):
        self._verifier = verifier
        self._allow_reference_implementation = allow_reference_implementation

    def check(self, spec: SpecArtifact | str, code: str, entry_point: str) -> VerificationEvidence:
        spec_text = spec.text if isinstance(spec, SpecArtifact) else spec
        contract_issues = tuple(contract_fidelity_issues(spec_text, code, entry_point))
        collapsed_calls = reference_implementation_calls(spec_text, code, entry_point)
        reference_collapse = bool(
            collapsed_calls and not self._allow_reference_implementation
        )

        policy_issues = tuple(
            f"reference implementation collapse is disabled: {call}"
            for call in collapsed_calls
        ) if reference_collapse else ()

        if contract_issues or policy_issues:
            messages = [*contract_issues, *policy_issues]
            result = VerificationResult(
                passed=False,
                errors=[
                    ErrorInfo(
                        error_type="contract" if index < len(contract_issues) else "policy",
                        subtype="contract_mismatch" if index < len(contract_issues) else "reference_collapse",
                        message=message,
                    )
                    for index, message in enumerate(messages)
                ],
                error_count=len(messages),
                raw_output="\n".join(messages),
            )
        else:
            result = self._verifier.verify(code)

        stage = "contract" if contract_issues else ("policy" if policy_issues else "formal")
        violated = _violated_spec_ids(spec, result, stage)

        return VerificationEvidence(
            result=result,
            contract_issues=contract_issues,
            static_issues=policy_issues,
            reference_collapse=reference_collapse,
            stage=stage,
            violated_spec_ids=violated,
        )


def _violated_spec_ids(
    spec: SpecArtifact | str,
    result: VerificationResult,
    stage: str,
) -> tuple[str, ...]:
    if not isinstance(spec, SpecArtifact) or not spec.structured:
        return ()
    clauses = spec.structured.clauses
    if stage in {"contract", "policy"}:
        return tuple(item.id for item in clauses)
    diagnostics = "\n".join(
        part
        for error in result.errors
        for part in (error.message, error.source, error.related_source, error.related_spec)
        if part
    )
    normalized_diagnostics = _normalize(diagnostics)
    matched = tuple(
        item.id
        for item in clauses
        if _normalize(item.formal_expression) in normalized_diagnostics
    )
    if matched:
        return matched
    if any((error.subtype or error.error_type) == "postcondition" for error in result.errors):
        return tuple(item.id for item in clauses if item.kind == "postcondition")
    if any((error.subtype or error.error_type) == "precondition" for error in result.errors):
        return tuple(item.id for item in clauses if item.kind == "precondition")
    return ()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
