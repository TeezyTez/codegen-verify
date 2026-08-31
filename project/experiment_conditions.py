"""Registered no-spec baselines with the same output and budget protocol."""

from __future__ import annotations

import json
from typing import Any

from artifacts import AgentRequest, AgentResult, SpecArtifact, stable_hash
from budget import BudgetExceeded, BudgetLedger, budget_scope
from candidate_synthesizer import extract_dafny_code
from contract_utils import restore_public_contract
from dafny_wrapper import DafnyVerifier
from humaneval_tester import run_humaneval_test
from llm_client import code_llm, repair_llm
from task_normalizer import render_dafny_signature
from verification_engine import VerificationEngine


CONDITIONS = ("spec_guided", "direct_1", "direct_verify")


class DirectSynthesizer:
    """Generate from public task text only; the signature is an interface, not a spec."""

    def __init__(self, generation_model, repair_model):
        self._generation_model = generation_model
        self._repair_model = repair_model

    def generate(self, request: AgentRequest, signature: str) -> str:
        raw = self._generation_model.chat(
            system=(
                "Write a complete Dafny implementation from the public task. Do not invent input "
                "restrictions. Output only Dafny code."
            ),
            user=f"""Public task:
{request.problem_desc}

Fixed public interface:
{signature}

Return a complete implementation of {request.entry_point}.""",
        )
        return restore_public_contract(signature, extract_dafny_code(raw), request.entry_point)

    def repair(self, request: AgentRequest, signature: str, code: str, evidence, attempt: int) -> str:
        if self._repair_model is None:
            raise RuntimeError("repair model is unavailable in the single-shot condition")
        raw = self._repair_model.chat(
            system=(
                "Repair the complete Dafny program using verifier feedback. Keep the public "
                "interface unchanged and output code only."
            ),
            user=f"""Public task:
{request.problem_desc}

Fixed public interface:
{signature}

Current candidate:
{code}

Verifier feedback for repair {attempt}:
{json.dumps(evidence.to_dict(), ensure_ascii=False, default=str)}""",
        )
        return restore_public_contract(signature, extract_dafny_code(raw), request.entry_point)


class DirectAgent:
    def __init__(
        self,
        *,
        condition_id: str,
        synthesizer: DirectSynthesizer,
        verification: VerificationEngine,
        budget: BudgetLedger,
        max_repairs: int,
        development_runner=run_humaneval_test,
    ):
        self.condition_id = condition_id
        self._synthesizer = synthesizer
        self._verification = verification
        self._budget = budget
        self._max_repairs = 0 if condition_id == "direct_1" else max(0, max_repairs)
        self._development_runner = development_runner

    def run(self, request: AgentRequest) -> AgentResult:
        signature = render_dafny_signature(request.task_ir)
        artifact = SpecArtifact(
            text=signature,
            version=0,
            task_hash=stable_hash({"problem_id": request.problem_id, "task_ir": request.task_ir}),
            decision="not_applicable",
        )
        trace: list[dict[str, Any]] = []
        history: list[dict[str, Any]] = []
        best_code = ""
        best_evidence = None
        development_executed = False
        development_passed = False
        development_error = ""
        attempts = 0
        stop_reason = ""

        with budget_scope(self._budget):
            try:
                code = self._synthesizer.generate(request, signature)
                self._budget.record_candidate()
                for repair_index in range(self._max_repairs + 1):
                    attempts += 1
                    history.append({
                        "attempt": attempts,
                        "repair_kind": "generation" if repair_index == 0 else "implementation",
                        "code": code,
                    })
                    evidence = self._verification.check(artifact, code, request.entry_point)
                    trace.append({
                        "stage": "verify",
                        "attempt": attempts,
                        "passed": evidence.passed,
                        "quality": list(evidence.quality),
                        "condition_id": self.condition_id,
                    })
                    if best_evidence is None or evidence.quality > best_evidence.quality:
                        best_code, best_evidence = code, evidence
                    if evidence.passed:
                        stop_reason = "verified"
                        if request.development_problem:
                            development_executed = True
                            development_passed, detail = self._development_runner(
                                code, dict(request.development_problem)
                            )
                            development_error = detail.get("error") or ""
                            stop_reason = "verified" if development_passed else "development_failed"
                        break
                    if repair_index >= self._max_repairs:
                        stop_reason = "single_shot" if self.condition_id == "direct_1" else "repair_depth_exhausted"
                        break
                    code = self._synthesizer.repair(
                        request, signature, code, evidence, repair_index + 1
                    )
                    self._budget.record_candidate()
                    trace.append({
                        "stage": "repair",
                        "attempt": repair_index + 1,
                        "repair_kind": "implementation",
                    })
            except BudgetExceeded as exc:
                stop_reason = exc.reason

        verified = bool(best_evidence and best_evidence.passed)
        status = (
            "budget_exhausted" if self._budget.stop_reason
            else "verified" if verified and (not development_executed or development_passed)
            else "development_failed" if verified and development_executed
            else "verification_failed"
        )
        return AgentResult(
            status=status,
            code=best_code,
            spec=artifact,
            evidence=best_evidence,
            attempts=attempts,
            trace=tuple(trace),
            development_executed=development_executed,
            development_passed=development_passed,
            development_error=development_error,
            task_ir=request.task_ir,
            code_history=tuple(history),
            condition_id=self.condition_id,
            stop_reason=stop_reason,
            budget=self._budget.snapshot(),
            search={"width": 1, "max_depth": self._max_repairs},
        )


def run_direct_condition(
    condition_id: str,
    request: AgentRequest,
    *,
    max_repairs: int,
    budget: BudgetLedger,
) -> AgentResult:
    if condition_id not in {"direct_1", "direct_verify"}:
        raise ValueError(
            f"unknown experiment condition {condition_id!r}; expected one of {CONDITIONS}"
        )
    verifier = DafnyVerifier()
    return DirectAgent(
        condition_id=condition_id,
        synthesizer=DirectSynthesizer(
            code_llm(), repair_llm() if condition_id == "direct_verify" else None
        ),
        verification=VerificationEngine(verifier),
        budget=budget,
        max_repairs=max_repairs,
    ).run(request)
