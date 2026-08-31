"""Candidate generation and repair against an immutable specification."""

from __future__ import annotations

import re
import json
from typing import Any, Mapping

from artifacts import FailureDiagnosis, ProgramPlan, SpecArtifact, VerificationEvidence
from contract_utils import restore_public_contract
from proof_edit_guard import proof_edit_issues


def extract_dafny_code(text: str) -> str:
    code = text or ""
    if "```dafny" in code:
        code = code.split("```dafny", 1)[1].split("```", 1)[0]
    elif "```" in code:
        code = code.split("```", 1)[1].split("```", 1)[0]
    return re.sub(r"[^\x00-\x7F\n\r\t ]+", "", code).strip()


class CandidateSynthesizer:
    """Generate and repair code without authority to modify the frozen spec."""

    def __init__(self, generation_model, repair_model, *, enforce_proof_guard: bool = True):
        self._generation_model = generation_model
        self._repair_model = repair_model
        self._enforce_proof_guard = enforce_proof_guard
        self.last_guard_issues: tuple[str, ...] = ()

    def generate(
        self,
        *,
        problem_desc: str,
        spec: SpecArtifact | str,
        entry_point: str,
        task_ir: Mapping[str, Any],
        plan: ProgramPlan | None = None,
    ) -> str:
        spec_text = spec.text if isinstance(spec, SpecArtifact) else spec
        structured = spec.structured.to_dict() if isinstance(spec, SpecArtifact) and spec.structured else {}
        plan_data = plan.to_dict() if plan else {}
        raw = self._generation_model.chat(
            system=_generation_system_prompt(),
            user=f"""Public task:
{problem_desc}

Structured specification with stable clause IDs:
{json.dumps(structured, ensure_ascii=False, indent=2)}

Frozen Dafny specification:
{spec_text}

Spec-guided program plan:
{json.dumps(plan_data, ensure_ascii=False, indent=2)}

Entry point: {entry_point}

Implement the complete Dafny method. Follow the plan and explicitly satisfy every SPEC clause.
The public signature, requires, and ensures are frozen. Pure specification helpers may support
proofs but must not be called as the returned implementation. Output only complete Dafny code.""",
        )
        return restore_public_contract(spec_text, extract_dafny_code(raw), entry_point)

    def repair(
        self,
        *,
        problem_desc: str,
        spec: SpecArtifact | str,
        entry_point: str,
        code: str,
        evidence: VerificationEvidence,
        attempt: int,
        plan: ProgramPlan | None = None,
        diagnosis: FailureDiagnosis | None = None,
        repair_kind: str = "implementation",
        search_memory: tuple[str, ...] = (),
    ) -> str:
        spec_text = spec.text if isinstance(spec, SpecArtifact) else spec
        diagnostics = _format_evidence(evidence)
        diagnosis_data = diagnosis.to_dict() if diagnosis else {}
        plan_data = plan.to_dict() if plan else {}
        repair_kind = repair_kind if repair_kind in {"implementation", "proof"} else "implementation"
        scope = (
            "Change only proof annotations, assertions, ghost code, or lemmas; executable logic "
            "and assignments must remain textually unchanged."
            if repair_kind == "proof"
            else "Repair executable logic as needed while preserving the frozen contract."
        )
        raw = self._repair_model.chat(
            system=_scoped_repair_system_prompt(repair_kind),
            user=f"""Public task:
{problem_desc}

Frozen specification (must not be modified):
{spec_text}

Spec-guided plan:
{json.dumps(plan_data, ensure_ascii=False, indent=2)}

Failure diagnosis and localized repair scope:
{json.dumps(diagnosis_data, ensure_ascii=False, indent=2)}

Current complete Dafny candidate:
{code}

Verification evidence for repair {attempt}:
{diagnostics}

Bounded search memory (do not repeat these failed strategies):
{json.dumps(list(search_memory), ensure_ascii=False)}

Repair channel: {repair_kind}. {scope}
Repair only the diagnosed code/proof concern, preserve already satisfied clauses, and do not
weaken or delete any contract. Do not use a Reference/Helper as the returned implementation.
Output only the complete repaired Dafny program.""",
        )
        repaired = restore_public_contract(spec_text, extract_dafny_code(raw), entry_point)
        self.last_guard_issues = (
            proof_edit_issues(code, repaired)
            if repair_kind == "proof" and self._enforce_proof_guard else ()
        )
        return code if self.last_guard_issues else repaired


def _format_evidence(evidence: VerificationEvidence) -> str:
    rows = [*evidence.contract_issues, *evidence.static_issues]
    rows.extend(
        f"[{error.subtype or error.error_type}] line {error.location_line}: {error.message}"
        for error in evidence.result.errors
    )
    return "\n".join(f"- {row}" for row in rows) or "- verifier returned no structured detail"


def _generation_system_prompt() -> str:
    return """你是 Dafny 实现专家。规约已经由独立模块冻结，你只能实现它。
优先使用简单循环、明确 decreases、足够的不变量和局部 assert。function/predicate
保持纯表达式；method 才能使用赋值和循环。不得增加前置条件、删除后置条件或把
可执行规约 helper 直接当作实现。"""


def _scoped_repair_system_prompt(repair_kind: str) -> str:
    channel = (
        "Use the proof-only channel: never alter executable control flow, assignments, or returns."
        if repair_kind == "proof"
        else "Use the implementation channel: correct behavior without weakening the contract."
    )
    return (
        "You are a Dafny repair expert. Use structured verifier evidence, but never modify the "
        "frozen contract or bypass it through a reference implementation. " + channel
    )


def _repair_system_prompt() -> str:
    return """你是 Dafny 修复专家。根据结构化验证证据修改实现或证明提示，但绝不
修改冻结规约。若候选因契约漂移或 Reference 坍缩被拒绝，必须重新实现算法，而不是
绕过门控。重复错误时必须改变实现策略。"""
