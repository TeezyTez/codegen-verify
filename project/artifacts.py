"""Immutable shared intermediate representation for the coding agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any, Mapping

from dafny_wrapper import VerificationResult


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Requirement:
    """One atomic statement of user intent."""

    id: str
    description: str
    kind: str = "functional"
    source: str = "user"
    priority: str = "must"
    ambiguity: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationCase:
    """An executable or reviewable example derived from public task evidence."""

    id: str
    kind: str
    description: str
    related_requirements: tuple[str, ...] = ()
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["related_requirements"] = list(self.related_requirements)
        value["data"] = dict(self.data)
        return value


@dataclass(frozen=True)
class RequirementAnalysis:
    """Structured requirements and public evidence extracted from a task."""

    requirements: tuple[Requirement, ...]
    ambiguities: tuple[str, ...] = ()
    edge_cases: tuple[str, ...] = ()
    verification_cases: tuple[VerificationCase, ...] = ()
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirements": [item.to_dict() for item in self.requirements],
            "ambiguities": list(self.ambiguities),
            "edge_cases": list(self.edge_cases),
            "verification_cases": [item.to_dict() for item in self.verification_cases],
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SpecClause:
    """One traceable semantic or formal obligation."""

    id: str
    kind: str
    natural_language: str
    formal_expression: str = ""
    related_requirements: tuple[str, ...] = ()
    confidence: float = 0.0
    status: str = "proposed"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["related_requirements"] = list(self.related_requirements)
        return value


@dataclass(frozen=True)
class TraceNode:
    id: str
    kind: str
    label: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "label": self.label, "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class TraceLink:
    source: str
    relation: str
    target: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class TraceabilityGraph:
    """Serializable graph connecting intent, clauses, code, evidence, and repairs."""

    nodes: tuple[TraceNode, ...] = ()
    links: tuple[TraceLink, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [item.to_dict() for item in self.nodes],
            "links": [item.to_dict() for item in self.links],
        }


@dataclass(frozen=True)
class StructuredSpecification:
    """The shared semantic IR paired with the generated formal contract."""

    task_id: str
    requirements: tuple[Requirement, ...]
    clauses: tuple[SpecClause, ...]
    edge_cases: tuple[str, ...] = ()
    verification_cases: tuple[VerificationCase, ...] = ()
    confidence: float = 0.0

    def clause(self, clause_id: str) -> SpecClause | None:
        return next((item for item in self.clauses if item.id == clause_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "requirements": [item.to_dict() for item in self.requirements],
            "clauses": [item.to_dict() for item in self.clauses],
            "edge_cases": list(self.edge_cases),
            "verification_cases": [item.to_dict() for item in self.verification_cases],
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ProgramPlan:
    """A spec-indexed implementation and verification plan."""

    algorithm: str
    reasoning_constraints: tuple[str, ...] = ()
    state_variables: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    edge_case_strategy: tuple[str, ...] = ()
    verification_strategy: tuple[str, ...] = ()
    clause_mapping: Mapping[str, str] = field(default_factory=dict)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "reasoning_constraints": list(self.reasoning_constraints),
            "state_variables": list(self.state_variables),
            "invariants": list(self.invariants),
            "edge_case_strategy": list(self.edge_case_strategy),
            "verification_strategy": list(self.verification_strategy),
            "clause_mapping": dict(self.clause_mapping),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class FailureDiagnosis:
    """A localized, spec-indexed explanation of one failed verification."""

    category: str
    summary: str
    violated_spec_ids: tuple[str, ...] = ()
    related_requirement_ids: tuple[str, ...] = ()
    relevant_code: str = ""
    repair_goal: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "summary": self.summary,
            "violated_spec_ids": list(self.violated_spec_ids),
            "related_requirement_ids": list(self.related_requirement_ids),
            "relevant_code": self.relevant_code,
            "repair_goal": self.repair_goal,
            "evidence": dict(self.evidence),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SpecArtifact:
    """A versioned specification plus the evidence authorizing its use."""

    text: str
    version: int
    task_hash: str
    decision: str
    validation_attempts: int = 1
    critic_report: Mapping[str, Any] = field(default_factory=dict)
    adequacy: Mapping[str, Any] = field(default_factory=dict)
    mutation: Mapping[str, Any] = field(default_factory=dict)
    structured: StructuredSpecification | None = None
    drift_report: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[str, ...] = ()

    @property
    def approved(self) -> bool:
        return self.decision == "approve"

    @property
    def fingerprint(self) -> str:
        return stable_hash({
            "task": self.task_hash,
            "version": self.version,
            "spec": self.text,
            "structured": self.structured.to_dict() if self.structured else {},
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "version": self.version,
            "task_hash": self.task_hash,
            "fingerprint": self.fingerprint,
            "decision": self.decision,
            "validation_attempts": self.validation_attempts,
            "critic_report": dict(self.critic_report),
            "adequacy": dict(self.adequacy),
            "mutation": dict(self.mutation),
            "structured": self.structured.to_dict() if self.structured else {},
            "drift_report": dict(self.drift_report),
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class VerificationEvidence:
    """All deterministic and formal evidence for one candidate."""

    result: VerificationResult
    contract_issues: tuple[str, ...] = ()
    static_issues: tuple[str, ...] = ()
    reference_collapse: bool = False
    stage: str = "formal"
    violated_spec_ids: tuple[str, ...] = ()
    counterexample: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return (
            self.result.passed
            and not self.contract_issues
            and not self.static_issues
            and not self.reference_collapse
        )

    @property
    def quality(self) -> tuple[int, int, int]:
        if self.passed:
            return (4, self.result.verified_count, 0)
        error_types = {error.error_type for error in self.result.errors}
        if self.reference_collapse or self.contract_issues:
            return (0, self.result.verified_count, -max(1, self.result.error_count))
        if "timeout" in error_types:
            return (0, self.result.verified_count, -max(1, self.result.error_count))
        language_errors = {"syntax", "type", "undefined", "assignment", "contract", "policy"}
        if self.static_issues or error_types & language_errors:
            return (1, self.result.verified_count, -max(1, self.result.error_count))
        return (2, self.result.verified_count, -max(1, self.result.error_count))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "quality": list(self.quality),
            "contract_issues": list(self.contract_issues),
            "static_issues": list(self.static_issues),
            "reference_collapse": self.reference_collapse,
            "stage": self.stage,
            "violated_spec_ids": list(self.violated_spec_ids),
            "counterexample": dict(self.counterexample),
            "result": asdict(self.result),
        }


@dataclass(frozen=True)
class AgentRequest:
    problem_id: str
    problem_desc: str
    entry_point: str
    task_ir: Mapping[str, Any]
    development_problem: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class AgentResult:
    status: str
    code: str
    spec: SpecArtifact
    evidence: VerificationEvidence | None
    attempts: int
    trace: tuple[Mapping[str, Any], ...] = ()
    development_executed: bool = False
    development_passed: bool = False
    development_error: str = ""
    task_ir: Mapping[str, Any] = field(default_factory=dict)
    requirement_analysis: RequirementAnalysis | None = None
    plan: ProgramPlan | None = None
    diagnoses: tuple[FailureDiagnosis, ...] = ()
    traceability: TraceabilityGraph = field(default_factory=TraceabilityGraph)
    spec_history: tuple[SpecArtifact, ...] = ()
    code_history: tuple[Mapping[str, Any], ...] = ()

    @property
    def dafny_verified(self) -> bool:
        return bool(self.evidence and self.evidence.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "code": self.code,
            "spec": self.spec.text,
            "spec_artifact": self.spec.to_dict(),
            "verification": self.evidence.result if self.evidence else VerificationResult(),
            "verification_evidence": self.evidence.to_dict() if self.evidence else {},
            "dafny_verified": self.dafny_verified,
            "passed": self.dafny_verified and (
                not self.development_executed or self.development_passed
            ),
            "round": self.attempts,
            "verification_attempts": self.attempts,
            "research_trace": [dict(event) for event in self.trace],
            "spec_adequacy": dict(self.spec.adequacy),
            "mutation_adequacy": dict(self.spec.mutation),
            "spec_critic": dict(self.spec.critic_report),
            "critic_gate_status": {
                "approve": "approved",
                "reject": "rejected",
                "abstain": "abstained",
            }.get(self.spec.decision, self.spec.decision),
            "critic_repair_rounds": max(0, self.spec.validation_attempts - 1),
            "behavior_executed": self.development_executed,
            "behavior_passed": self.development_passed,
            "behavior_error": self.development_error,
            "behavior_detail": {"error": self.development_error},
            "contract_fidelity": bool(self.evidence and not self.evidence.contract_issues),
            "task_ir": dict(self.task_ir),
            "requirement_analysis": (
                self.requirement_analysis.to_dict() if self.requirement_analysis else {}
            ),
            "plan": self.plan.to_dict() if self.plan else {},
            "diagnoses": [item.to_dict() for item in self.diagnoses],
            "traceability": self.traceability.to_dict(),
            "spec_history": [item.to_dict() for item in self.spec_history],
            "code_history": [dict(item) for item in self.code_history],
        }
