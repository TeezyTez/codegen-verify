"""Traceability recorder connecting agent artifacts without leaking orchestration state."""

from __future__ import annotations

from artifacts import (
    AgentRequest,
    FailureDiagnosis,
    ProgramPlan,
    RequirementAnalysis,
    SpecArtifact,
    TraceLink,
    TraceNode,
    TraceabilityGraph,
    VerificationEvidence,
    stable_hash,
)


class TraceRecorder:
    """Accumulate a deduplicated graph and expose only immutable snapshots."""

    def __init__(self, request: AgentRequest, analysis: RequirementAnalysis):
        self._nodes: dict[str, TraceNode] = {}
        self._links: dict[tuple[str, str, str], TraceLink] = {}
        self._pending_patch: str | None = None
        self._node(f"TASK-{request.problem_id}", "task", request.problem_desc)
        for requirement in analysis.requirements:
            self._node(requirement.id, "requirement", requirement.description)
            self._link(f"TASK-{request.problem_id}", "contains", requirement.id)
        for case in analysis.verification_cases:
            self._node(case.id, "test", case.description, {"kind": case.kind})
            for requirement_id in case.related_requirements:
                self._link(requirement_id, "verified_by", case.id)

    def record_spec(self, spec: SpecArtifact) -> None:
        artifact_id = f"SPECART-{spec.fingerprint[:12]}"
        self._node(artifact_id, "spec_artifact", f"spec v{spec.version}", {"decision": spec.decision})
        if not spec.structured:
            return
        for clause in spec.structured.clauses:
            self._node(clause.id, "spec_clause", clause.natural_language, {"kind": clause.kind})
            self._link(artifact_id, "contains", clause.id)
            for requirement_id in clause.related_requirements:
                self._link(requirement_id, "derived_to", clause.id)
        for case in spec.structured.verification_cases:
            for requirement_id in case.related_requirements:
                for clause in spec.structured.clauses:
                    if requirement_id in clause.related_requirements:
                        self._link(clause.id, "verified_by", case.id)

    def record_plan(self, spec: SpecArtifact, plan: ProgramPlan) -> None:
        plan_id = f"PLAN-{spec.version}"
        self._node(plan_id, "plan", plan.algorithm)
        for clause_id, strategy in plan.clause_mapping.items():
            self._link(clause_id, "planned_by", plan_id)
            strategy_id = f"STRATEGY-{stable_hash([clause_id, strategy])[:10]}"
            self._node(strategy_id, "strategy", strategy)
            self._link(clause_id, "implemented_via", strategy_id)
            self._link(strategy_id, "part_of", plan_id)

    def record_candidate(self, spec: SpecArtifact, code: str, attempt: int) -> str:
        code_id = f"CODE-{attempt}-{stable_hash(code)[:10]}"
        self._node(code_id, "code", "candidate", {"attempt": attempt})
        if self._pending_patch:
            self._link(self._pending_patch, "produced", code_id)
            self._pending_patch = None
        if spec.structured:
            for clause in spec.structured.clauses:
                self._link(clause.id, "implemented_by", code_id)
        return code_id

    def record_verification(self, code_id: str, evidence: VerificationEvidence, attempt: int) -> str:
        vc_id = f"VC-{attempt:03d}"
        self._node(vc_id, "verification", evidence.stage, {"passed": evidence.passed})
        self._link(code_id, "verified_by", vc_id)
        return vc_id

    def record_failure(self, vc_id: str, diagnosis: FailureDiagnosis, attempt: int) -> str:
        failure_id = f"FAIL-{attempt:03d}"
        self._node(failure_id, "failure", diagnosis.summary, {"category": diagnosis.category})
        self._link(vc_id, "failed_with", failure_id)
        for clause_id in diagnosis.violated_spec_ids:
            self._link(clause_id, "violated_by", failure_id)
        return failure_id

    def record_repair(self, failure_id: str, attempt: int) -> None:
        patch_id = f"PATCH-{attempt:03d}"
        self._node(patch_id, "patch", "targeted repair", {"attempt": attempt})
        self._link(failure_id, "repaired_by", patch_id)
        self._pending_patch = patch_id

    def snapshot(self) -> TraceabilityGraph:
        return TraceabilityGraph(
            nodes=tuple(self._nodes.values()),
            links=tuple(self._links.values()),
        )

    def _node(self, node_id: str, kind: str, label: str = "", metadata=None) -> None:
        self._nodes[node_id] = TraceNode(node_id, kind, label, metadata or {})

    def _link(self, source: str, relation: str, target: str) -> None:
        self._links[(source, relation, target)] = TraceLink(source, relation, target)
