"""The spec-guided coding agent and its bounded candidate-search state machine."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

import config
from artifacts import (
    AgentRequest,
    AgentResult,
    FailureDiagnosis,
    ProgramPlan,
    RequirementAnalysis,
    SpecArtifact,
    VerificationEvidence,
    stable_hash,
)
from budget import BudgetExceeded, BudgetLedger, BudgetLimits, budget_scope
from candidate_pool import CandidatePool, CandidateState
from candidate_synthesizer import CandidateSynthesizer
from dafny_wrapper import DafnyVerifier
from failure_diagnoser import FailureDiagnoser, spec_failure_diagnosis
from humaneval_tester import run_humaneval_test
from llm_client import (
    code_llm,
    critic_llm,
    diagnosis_llm,
    planner_llm,
    repair_llm,
    requirement_llm,
    semantic_probe_llm,
    spec_llm,
)
from requirement_analyzer import RequirementAnalyzer
from spec_authority import SpecAuthority
from spec_planner import SpecGuidedPlanner
from traceability import TraceRecorder
from verification_engine import VerificationEngine


class SpecGuidedAgent:
    """Turn one task into the best verified candidate within one explicit budget."""

    def __init__(
        self,
        *,
        spec_authority: SpecAuthority,
        synthesizer: CandidateSynthesizer,
        verification: VerificationEngine,
        requirement_analyzer: RequirementAnalyzer | None = None,
        planner: SpecGuidedPlanner | None = None,
        diagnoser: FailureDiagnoser | None = None,
        max_repairs: int = 3,
        max_spec_revisions: int = 1,
        search_width: int = 1,
        max_candidates: int = 0,
        dual_repair: bool = True,
        budget: BudgetLedger | None = None,
        development_runner=run_humaneval_test,
    ):
        self._requirement_analyzer = requirement_analyzer or RequirementAnalyzer()
        self._spec_authority = spec_authority
        self._planner = planner or SpecGuidedPlanner()
        self._synthesizer = synthesizer
        self._verification = verification
        self._diagnoser = diagnoser or FailureDiagnoser()
        self._max_repairs = max(0, max_repairs)
        self._max_spec_revisions = max(0, max_spec_revisions)
        self._search_width = max(1, search_width)
        self._max_candidates = max(0, max_candidates)
        self._dual_repair = dual_repair
        self._budget = budget or BudgetLedger()
        self._development_runner = development_runner

    def run(self, request: AgentRequest) -> AgentResult:
        with budget_scope(self._budget):
            try:
                result = self._run(request)
            except BudgetExceeded as exc:
                result = _budget_failure(request, exc.reason)
        return replace(
            result,
            budget=self._budget.snapshot(),
            stop_reason=result.stop_reason or self._budget.stop_reason,
        )

    def _run(self, request: AgentRequest) -> AgentResult:
        trace: list[Mapping[str, Any]] = []
        diagnoses: list[FailureDiagnosis] = []
        spec_history: list[SpecArtifact] = []
        code_history: list[Mapping[str, Any]] = []
        search_history: list[Mapping[str, Any]] = []
        analysis = self._requirement_analyzer.analyze(request)
        recorder = TraceRecorder(request, analysis)
        trace.append({
            "stage": "requirement_analysis",
            "requirement_ids": [item.id for item in analysis.requirements],
            "ambiguities": list(analysis.ambiguities),
            "edge_cases": list(analysis.edge_cases),
            "confidence": analysis.confidence,
        })

        previous_spec: SpecArtifact | None = None
        current_spec: SpecArtifact | None = None
        current_plan: ProgramPlan | None = None
        current_pool: CandidatePool | None = None
        spec_feedback = ""
        revision_evidence: Mapping[str, Any] = {}
        total_attempts = 0
        last_code = ""
        last_evidence: VerificationEvidence | None = None
        development_executed = False
        development_error = ""

        def finish(
            status: str,
            *,
            code: str,
            spec: SpecArtifact,
            evidence: VerificationEvidence | None,
            development_passed: bool = False,
            stop_reason: str = "",
        ) -> AgentResult:
            return AgentResult(
                status=status,
                code=code,
                spec=spec,
                evidence=evidence,
                attempts=total_attempts,
                trace=tuple(trace),
                development_executed=development_executed,
                development_passed=development_passed,
                development_error=development_error,
                task_ir=request.task_ir,
                requirement_analysis=analysis,
                plan=current_plan,
                diagnoses=tuple(diagnoses),
                traceability=recorder.snapshot(),
                spec_history=tuple(spec_history),
                code_history=tuple(code_history),
                condition_id="spec_guided",
                stop_reason=stop_reason,
                budget=self._budget.snapshot(),
                search={
                    "width": self._search_width,
                    "max_depth": self._max_repairs,
                    "candidates": search_history,
                    "current_pool": current_pool.snapshot() if current_pool else [],
                },
            )

        for revision in range(self._max_spec_revisions + 1):
            current_spec = self._spec_authority.assess(
                problem_id=request.problem_id,
                problem_desc=request.problem_desc,
                entry_point=request.entry_point,
                task_ir=request.task_ir,
                analysis=analysis,
                feedback=spec_feedback,
                revision_evidence=revision_evidence,
                previous=previous_spec,
            )
            recorder.record_spec(current_spec)
            spec_history.append(current_spec)
            trace.append({
                "stage": "spec_authority",
                "revision": revision,
                "decision": current_spec.decision,
                "spec_fingerprint": current_spec.fingerprint,
                "clause_ids": [
                    item.id for item in current_spec.structured.clauses
                ] if current_spec.structured else [],
                "issues": list(current_spec.issues),
                "drift": dict(current_spec.drift_report),
                "harness": current_spec.harness.to_dict() if current_spec.harness else {},
            })
            if not current_spec.approved:
                return finish(
                    "abstained" if current_spec.decision == "abstain" else "spec_rejected",
                    code="",
                    spec=current_spec,
                    evidence=None,
                    stop_reason="spec_gate",
                )

            current_plan = self._planner.plan(request, current_spec)
            recorder.record_plan(current_spec, current_plan)
            trace.append({
                "stage": "planning",
                "algorithm": current_plan.algorithm,
                "mapped_clauses": sorted(current_plan.clause_mapping),
                "confidence": current_plan.confidence,
            })
            generated = self._synthesizer.generate(
                problem_desc=request.problem_desc,
                spec=current_spec,
                entry_point=request.entry_point,
                task_ir=request.task_ir,
                plan=current_plan,
            )
            current_pool = CandidatePool(max_candidates=self._max_candidates)
            initial = current_pool.offer(generated, depth=0)
            if initial is None:
                return finish(
                    "verification_failed", code="", spec=current_spec, evidence=None,
                    stop_reason="candidate_pool_empty",
                )
            self._budget.record_candidate()
            trace.append({
                "stage": "candidate",
                "action": "generated",
                "candidate_id": initial.id,
                "spec_fingerprint": current_spec.fingerprint,
            })

            frontier = [initial]
            reopen_spec = False
            for depth in range(self._max_repairs + 1):
                next_frontier: list[CandidateState] = []
                for candidate in frontier[: self._search_width]:
                    total_attempts += 1
                    code_history.append({
                        "attempt": total_attempts,
                        "candidate_id": candidate.id,
                        "parent_id": candidate.parent_id,
                        "repair_kind": candidate.repair_kind,
                        "spec_version": current_spec.version,
                        "code": candidate.code,
                    })
                    code_id = recorder.record_candidate(current_spec, candidate.code, total_attempts)
                    evidence = self._verification.check(
                        current_spec, candidate.code, request.entry_point
                    )
                    current_pool.record(candidate.id, evidence)
                    vc_id = recorder.record_verification(code_id, evidence, total_attempts)
                    event = {
                        "stage": "verify",
                        "attempt": total_attempts,
                        "candidate_id": candidate.id,
                        "parent_id": candidate.parent_id,
                        "repair_kind": candidate.repair_kind,
                        "depth": depth,
                        "passed": evidence.passed,
                        "verification_stage": evidence.stage,
                        "violated_spec_ids": list(evidence.violated_spec_ids),
                        "quality": list(evidence.quality),
                        "reference_collapse": evidence.reference_collapse,
                        "error_types": [error.error_type for error in evidence.result.errors],
                    }
                    trace.append(event)
                    search_history.append(event)

                    if evidence.passed:
                        last_code, last_evidence = candidate.code, evidence
                        if not request.development_problem:
                            return finish(
                                "verified", code=candidate.code, spec=current_spec,
                                evidence=evidence, stop_reason="verified",
                            )

                        development_executed = True
                        development_passed, detail = self._development_runner(
                            candidate.code, dict(request.development_problem)
                        )
                        development_error = detail.get("error") or ""
                        trace.append({
                            "stage": "development_evidence",
                            "passed": development_passed,
                            "error": development_error,
                        })
                        if development_passed:
                            return finish(
                                "verified", code=candidate.code, spec=current_spec,
                                evidence=evidence, development_passed=True,
                                stop_reason="verified",
                            )
                        diagnosis = spec_failure_diagnosis(current_spec, development_error)
                        diagnoses.append(diagnosis)
                        recorder.record_failure(vc_id, diagnosis, total_attempts)
                        trace.append({"stage": "diagnosis", **diagnosis.to_dict()})
                        spec_feedback = diagnosis.summary + " Evidence: " + development_error
                        revision_evidence = diagnosis.to_dict()
                        previous_spec = current_spec
                        reopen_spec = True
                        break

                    diagnosis = self._diagnoser.diagnose(
                        request=request,
                        spec=current_spec,
                        plan=current_plan,
                        code=candidate.code,
                        evidence=evidence,
                    )
                    diagnoses.append(diagnosis)
                    failure_id = recorder.record_failure(vc_id, diagnosis, total_attempts)
                    trace.append({"stage": "diagnosis", **diagnosis.to_dict()})
                    if depth >= self._max_repairs:
                        continue

                    repair_kinds = _repair_kinds(
                        diagnosis.category,
                        dual_repair=self._dual_repair,
                        search_width=self._search_width,
                    )
                    for repair_kind in repair_kinds:
                        if len(next_frontier) >= self._search_width:
                            break
                        repaired = self._synthesizer.repair(
                            problem_desc=request.problem_desc,
                            spec=current_spec,
                            entry_point=request.entry_point,
                            code=candidate.code,
                            evidence=evidence,
                            attempt=depth + 1,
                            plan=current_plan,
                            diagnosis=diagnosis,
                            repair_kind=repair_kind,
                            search_memory=tuple(
                                f"{item.category}: {item.summary[:180]}" for item in diagnoses[-6:]
                            ),
                        )
                        guard_issues = tuple(
                            getattr(self._synthesizer, "last_guard_issues", ()) or ()
                        )
                        child = current_pool.offer(
                            repaired,
                            depth=depth + 1,
                            parent_id=candidate.id,
                            repair_kind=repair_kind,
                        )
                        trace.append({
                            "stage": "repair",
                            "attempt": depth + 1,
                            "parent_id": candidate.id,
                            "candidate_id": child.id if child else "",
                            "repair_kind": repair_kind,
                            "failure_type": diagnosis.category,
                            "violated_spec_ids": list(diagnosis.violated_spec_ids),
                            "guard_issues": list(guard_issues),
                            "accepted": child is not None,
                            "spec_fingerprint": current_spec.fingerprint,
                        })
                        if child:
                            self._budget.record_candidate()
                            recorder.record_repair(failure_id, depth + 1)
                            next_frontier.append(child)
                if reopen_spec:
                    break
                if depth >= self._max_repairs or not next_frontier:
                    break
                frontier = next_frontier

            if reopen_spec:
                continue
            best = current_pool.best()
            return finish(
                "verification_failed",
                code=best.code if best else "",
                spec=current_spec,
                evidence=best.evidence if best else None,
                stop_reason="repair_depth_exhausted" if best else "candidate_pool_empty",
            )

        assert current_spec is not None
        return finish(
            "development_failed",
            code=last_code,
            spec=current_spec,
            evidence=last_evidence,
            stop_reason="spec_revision_exhausted",
        )


def _repair_kinds(category: str, *, dual_repair: bool, search_width: int) -> tuple[str, ...]:
    if not dual_repair:
        return ("implementation",)
    if category == "PROOF_ERROR":
        return ("proof",)
    if category == "UNKNOWN" and search_width > 1:
        return ("implementation", "proof")
    return ("implementation",)


def configured_budget() -> BudgetLedger:
    return BudgetLedger(BudgetLimits(
        max_model_calls=config.MAX_MODEL_CALLS,
        max_total_tokens=config.MAX_TOTAL_TOKENS,
        max_verifier_calls=config.MAX_VERIFIER_CALLS,
        max_wall_seconds=config.MAX_WALL_SECONDS,
        max_candidates=config.MAX_CANDIDATES,
    ))


def _budget_failure(request: AgentRequest, reason: str) -> AgentResult:
    spec = SpecArtifact(
        text="",
        version=0,
        task_hash=stable_hash({"problem_id": request.problem_id, "task_ir": request.task_ir}),
        decision="abstain",
        issues=(f"experiment budget exhausted: {reason}",),
    )
    return AgentResult(
        status="budget_exhausted",
        code="",
        spec=spec,
        evidence=None,
        attempts=0,
        task_ir=request.task_ir,
        condition_id="spec_guided",
        stop_reason=reason,
    )


def build_default_agent(
    *,
    max_repairs: int | None = None,
    budget: BudgetLedger | None = None,
) -> SpecGuidedAgent:
    verifier = DafnyVerifier()
    authority = SpecAuthority(
        spec_model=spec_llm(),
        critic_model=critic_llm(),
        probe_model=semantic_probe_llm(),
        verifier=verifier,
        max_repairs=config.MAX_SPEC_REPAIR_ROUNDS,
    )
    return SpecGuidedAgent(
        requirement_analyzer=RequirementAnalyzer(
            requirement_llm() if config.ENABLE_STRUCTURED_REQUIREMENTS else None
        ),
        spec_authority=authority,
        planner=SpecGuidedPlanner(planner_llm() if config.ENABLE_SPEC_PLANNING else None),
        synthesizer=CandidateSynthesizer(
            code_llm(), repair_llm(),
            enforce_proof_guard=config.ENABLE_PROOF_EDIT_GUARD,
        ),
        verification=VerificationEngine(
            verifier,
            allow_reference_implementation=config.ALLOW_REFERENCE_IMPLEMENTATION,
        ),
        diagnoser=FailureDiagnoser(
            diagnosis_llm() if config.ENABLE_FAILURE_DIAGNOSIS else None
        ),
        max_repairs=config.MAX_REPAIR_ROUNDS if max_repairs is None else max_repairs,
        max_spec_revisions=config.MAX_SPEC_REVISIONS,
        search_width=config.SEARCH_WIDTH,
        max_candidates=config.MAX_CANDIDATES,
        dual_repair=config.ENABLE_DUAL_REPAIR,
        budget=budget or configured_budget(),
    )


def run_agent(
    problem_id: str,
    problem_desc: str,
    max_rounds: int = 3,
    behavior_problem: dict | None = None,
    entry_point: str = "",
    task_ir: dict | None = None,
    condition_id: str | None = None,
) -> dict[str, Any]:
    """Run one registered experiment condition behind a common result schema."""
    request = AgentRequest(
        problem_id=problem_id,
        problem_desc=problem_desc,
        entry_point=entry_point,
        task_ir=task_ir or {},
        development_problem=behavior_problem,
    )
    condition = (condition_id or config.EXPERIMENT_CONDITION).strip().lower()
    if condition != "spec_guided":
        from experiment_conditions import run_direct_condition

        return run_direct_condition(
            condition,
            request,
            max_repairs=max_rounds,
            budget=configured_budget(),
        ).to_dict()
    return build_default_agent(
        max_repairs=max_rounds,
        budget=configured_budget(),
    ).run(request).to_dict()
