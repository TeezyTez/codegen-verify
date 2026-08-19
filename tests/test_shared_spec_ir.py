import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from artifacts import (
    AgentRequest,
    Requirement,
    SpecArtifact,
    SpecClause,
    StructuredSpecification,
    VerificationEvidence,
)
import config
from agent import SpecGuidedAgent
from candidate_synthesizer import CandidateSynthesizer
from dafny_wrapper import ErrorInfo, VerificationResult
from failure_diagnoser import FailureDiagnoser
from requirement_analyzer import RequirementAnalyzer
from spec_authority import SpecAuthority
from spec_planner import SpecGuidedPlanner
from task_normalizer import normalize_humaneval_problem
from verification_engine import VerificationEngine


REQUEST = AgentRequest(
    problem_id="task",
    problem_desc="Return the first index of target or -1 without modifying input.",
    entry_point="search",
    task_ir={
        "examples": (
            {"source": "search([1, 2], 2)", "expected_value": 1},
        ),
    },
)


class FakeModel:
    def __init__(self, value):
        self.value = value

    def chat(self, **_kwargs):
        return json.dumps(self.value)


class QueueModel:
    def __init__(self, *values):
        self.values = list(values)

    def chat(self, **_kwargs):
        value = self.values.pop(0)
        return value if isinstance(value, str) else json.dumps(value)


def structured_spec():
    requirement = Requirement("REQ-001", "Return the first index.")
    clause = SpecClause(
        "SPEC-POST-001",
        "postcondition",
        "The result is the first index.",
        "result == 0",
        (requirement.id,),
        0.9,
        "validated",
    )
    structured = StructuredSpecification("task", (requirement,), (clause,))
    return SpecArtifact(
        text="method search(a: seq<int>, target: int) returns (result: int)\n    ensures result == 0",
        version=1,
        task_hash="task",
        decision="approve",
        structured=structured,
    )


def test_requirement_analyzer_creates_stable_ids_and_keeps_public_examples():
    analyzer = RequirementAnalyzer(FakeModel({
        "requirements": [
            {"description": "Return the first target index.", "type": "functional"},
            {"description": "Do not modify the input.", "type": "side_effect"},
        ],
        "edge_cases": ["empty input", "duplicates"],
        "confidence": 0.8,
    }))

    result = analyzer.analyze(REQUEST)

    assert [item.id for item in result.requirements] == ["REQ-001", "REQ-002"]
    assert result.verification_cases[0].id == "TEST-001"
    assert result.verification_cases[0].kind == "public_example"


def test_planner_fills_missing_clause_mapping():
    planner = SpecGuidedPlanner(FakeModel({
        "algorithm": "Use lower bound search.",
        "clause_mapping": {},
        "invariants": ["discarded prefix has no target"],
    }))

    plan = planner.plan(REQUEST, structured_spec())

    assert plan.algorithm == "Use lower bound search."
    assert "SPEC-POST-001" in plan.clause_mapping


def test_failure_diagnoser_maps_proof_failure_back_to_requirement():
    evidence = VerificationEvidence(
        VerificationResult(
            errors=[ErrorInfo(error_type="invariant", subtype="invariant_maintenance", location_line=3)],
            error_count=1,
        ),
        violated_spec_ids=("SPEC-POST-001",),
    )

    diagnosis = FailureDiagnoser().diagnose(
        request=REQUEST,
        spec=structured_spec(),
        plan=SpecGuidedPlanner().plan(REQUEST, structured_spec()),
        code="line1\nline2\nline3\nline4",
        evidence=evidence,
    )

    assert diagnosis.category == "PROOF_ERROR"
    assert diagnosis.related_requirement_ids == ("REQ-001",)
    assert "3: line3" in diagnosis.relevant_code


def test_model_cannot_reopen_spec_without_independent_counterexample():
    evidence = VerificationEvidence(
        VerificationResult(
            errors=[ErrorInfo(error_type="postcondition", subtype="postcondition")],
            error_count=1,
        ),
        violated_spec_ids=("SPEC-POST-001",),
    )
    diagnoser = FailureDiagnoser(FakeModel({
        "category": "SPEC_ERROR",
        "summary": "weaken the spec",
        "violated_spec_ids": ["SPEC-POST-001"],
        "repair_goal": "remove the clause",
    }))

    diagnosis = diagnoser.diagnose(
        request=REQUEST,
        spec=structured_spec(),
        plan=SpecGuidedPlanner().plan(REQUEST, structured_spec()),
        code="method search()",
        evidence=evidence,
    )

    assert diagnosis.category == "UNKNOWN"


def test_shared_ir_flows_through_the_real_orchestrator(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_MUTATION_GUARD", False)
    monkeypatch.setattr(config, "ENABLE_SPEC_CRITIC", False)
    problem = {
        "task_id": "HumanEval/identity",
        "entry_point": "identity",
        "prompt": '''def identity(x: int) -> int:
    """Return x.
    >>> identity(2)
    2
    """
''',
    }
    task_ir = normalize_humaneval_problem(problem).to_dict()
    request = AgentRequest(
        problem_id=problem["task_id"],
        problem_desc="Return x.",
        entry_point="identity",
        task_ir=task_ir,
    )
    formal = "method identity(x: int) returns (result: int)\n    ensures result == x"

    class PassingVerifier:
        def resolve(self, _code):
            return VerificationResult(passed=True)

        def verify(self, _code):
            return VerificationResult(passed=True, verified_count=1)

    verifier = PassingVerifier()
    agent = SpecGuidedAgent(
        requirement_analyzer=RequirementAnalyzer(QueueModel({
            "requirements": [{"description": "Return the input value."}],
            "verification_cases": [],
            "confidence": 0.9,
        })),
        spec_authority=SpecAuthority(
            spec_model=QueueModel({
                "clauses": [{
                    "kind": "postcondition",
                    "natural_language": "The result equals x.",
                    "formal_expression": "result == x",
                    "related_requirements": ["REQ-001"],
                    "confidence": 0.9,
                }],
                "formal_spec": formal,
            }),
            critic_model=object(),
            probe_model=object(),
            verifier=verifier,
        ),
        planner=SpecGuidedPlanner(QueueModel({
            "algorithm": "Assign x directly.",
            "clause_mapping": {"SPEC-POST-001": "Return x."},
            "confidence": 0.9,
        })),
        synthesizer=CandidateSynthesizer(
            QueueModel(formal + "\n{ result := x; }"),
            QueueModel(),
        ),
        verification=VerificationEngine(verifier),
        diagnoser=FailureDiagnoser(),
    )

    result = agent.run(request)

    assert result.status == "verified"
    assert result.spec.structured.clauses[0].related_requirements == ("REQ-001",)
    assert result.plan.clause_mapping["SPEC-POST-001"] == "Return x."
    assert result.code_history[0]["code"].endswith("{ result := x; }")
    assert any(link.relation == "implemented_by" for link in result.traceability.links)
