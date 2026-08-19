"""The spec-guided coding agent and its bounded state machine."""

from __future__ import annotations

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
)
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
    """Turn one task into the best verified candidate within a fixed budget."""

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
        self._development_runner = development_runner

    def run(self, request: AgentRequest) -> AgentResult:
        trace: list[Mapping[str, Any]] = []
        diagnoses: list[FailureDiagnosis] = []
        spec_history: list[SpecArtifact] = []
        code_history: list[Mapping[str, Any]] = []
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
            })
            if not current_spec.approved:
                return finish(
                    "abstained" if current_spec.decision == "abstain" else "spec_rejected",
                    code="",
                    spec=current_spec,
                    evidence=None,
                )

            current_plan = self._planner.plan(request, current_spec)
            recorder.record_plan(current_spec, current_plan)
            trace.append({
                "stage": "planning",
                "algorithm": current_plan.algorithm,
                "mapped_clauses": sorted(current_plan.clause_mapping),
                "confidence": current_plan.confidence,
            })
            code = self._synthesizer.generate(
                problem_desc=request.problem_desc,
                spec=current_spec,
                entry_point=request.entry_point,
                task_ir=request.task_ir,
                plan=current_plan,
            )
            trace.append({
                "stage": "candidate",
                "action": "generated",
                "spec_fingerprint": current_spec.fingerprint,
            })
            best_code = ""
            best_evidence: VerificationEvidence | None = None

            for repair_index in range(self._max_repairs + 1):
                total_attempts += 1
                code_history.append({
                    "attempt": total_attempts,
                    "spec_version": current_spec.version,
                    "code": code,
                })
                code_id = recorder.record_candidate(current_spec, code, total_attempts)
                evidence = self._verification.check(current_spec, code, request.entry_point)
                vc_id = recorder.record_verification(code_id, evidence, total_attempts)
                trace.append({
                    "stage": "verify",
                    "attempt": total_attempts,
                    "passed": evidence.passed,
                    "verification_stage": evidence.stage,
                    "violated_spec_ids": list(evidence.violated_spec_ids),
                    "quality": list(evidence.quality),
                    "reference_collapse": evidence.reference_collapse,
                    "error_types": [error.error_type for error in evidence.result.errors],
                })
                if best_evidence is None or evidence.quality > best_evidence.quality:
                    best_code, best_evidence = code, evidence

                if evidence.passed:
                    last_code, last_evidence = code, evidence
                    if not request.development_problem:
                        return finish("verified", code=code, spec=current_spec, evidence=evidence)

                    development_executed = True
                    development_passed, detail = self._development_runner(
                        code, dict(request.development_problem)
                    )
                    development_error = detail.get("error") or ""
                    trace.append({
                        "stage": "development_evidence",
                        "passed": development_passed,
                        "error": development_error,
                    })
                    if development_passed:
                        return finish(
                            "verified",
                            code=code,
                            spec=current_spec,
                            evidence=evidence,
                            development_passed=True,
                        )
                    diagnosis = spec_failure_diagnosis(current_spec, development_error)
                    diagnoses.append(diagnosis)
                    recorder.record_failure(vc_id, diagnosis, total_attempts)
                    trace.append({"stage": "diagnosis", **diagnosis.to_dict()})
                    spec_feedback = (
                        diagnosis.summary + " Evidence: " + development_error
                    )
                    revision_evidence = diagnosis.to_dict()
                    previous_spec = current_spec
                    break

                diagnosis = self._diagnoser.diagnose(
                    request=request,
                    spec=current_spec,
                    plan=current_plan,
                    code=code,
                    evidence=evidence,
                )
                diagnoses.append(diagnosis)
                failure_id = recorder.record_failure(vc_id, diagnosis, total_attempts)
                trace.append({"stage": "diagnosis", **diagnosis.to_dict()})

                if repair_index >= self._max_repairs:
                    return finish(
                        "verification_failed",
                        code=best_code,
                        spec=current_spec,
                        evidence=best_evidence,
                    )

                code = self._synthesizer.repair(
                    problem_desc=request.problem_desc,
                    spec=current_spec,
                    entry_point=request.entry_point,
                    code=code,
                    evidence=evidence,
                    attempt=repair_index + 1,
                    plan=current_plan,
                    diagnosis=diagnosis,
                )
                recorder.record_repair(failure_id, repair_index + 1)
                trace.append({
                    "stage": "repair",
                    "attempt": repair_index + 1,
                    "failure_type": diagnosis.category,
                    "violated_spec_ids": list(diagnosis.violated_spec_ids),
                    "spec_fingerprint": current_spec.fingerprint,
                })

        assert current_spec is not None
        return finish(
            "development_failed",
            code=last_code,
            spec=current_spec,
            evidence=last_evidence,
        )


def build_default_agent(*, max_repairs: int | None = None) -> SpecGuidedAgent:
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
        synthesizer=CandidateSynthesizer(code_llm(), repair_llm()),
        verification=VerificationEngine(
            verifier,
            allow_reference_implementation=config.ALLOW_REFERENCE_IMPLEMENTATION,
        ),
        diagnoser=FailureDiagnoser(
            diagnosis_llm() if config.ENABLE_FAILURE_DIAGNOSIS else None
        ),
        max_repairs=config.MAX_REPAIR_ROUNDS if max_repairs is None else max_repairs,
        max_spec_revisions=config.MAX_SPEC_REVISIONS,
    )


def run_agent(
    problem_id: str,
    problem_desc: str,
    max_rounds: int = 3,
    behavior_problem: dict | None = None,
    entry_point: str = "",
    task_ir: dict | None = None,
) -> dict[str, Any]:
    """Convenience entry point used by the benchmark runner."""
    request = AgentRequest(
        problem_id=problem_id,
        problem_desc=problem_desc,
        entry_point=entry_point,
        task_ir=task_ir or {},
        development_problem=behavior_problem,
    )
    return build_default_agent(max_repairs=max_rounds).run(request).to_dict()
