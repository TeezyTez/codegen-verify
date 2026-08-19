import csv
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from analyze_results import result_row, summarize, write_csv


def test_result_row_uses_current_artifacts_and_evidence():
    row = result_row({
        "task_id": "t",
        "status": "verified",
        "passed": True,
        "dafny_verified": True,
        "humaneval_passed": True,
        "verification_attempts": 2,
        "spec_artifact": {
            "decision": "approve",
            "version": 2,
            "mutation": {"mutants_total": 4, "mutants_verified": 0},
            "structured": {"clauses": [{"id": "SPEC-POST-001"}]},
        },
        "requirement_analysis": {"requirements": [{"id": "REQ-001"}]},
        "plan": {"clause_mapping": {"SPEC-POST-001": "implement"}},
        "diagnoses": [{"category": "CODE_ERROR"}],
        "traceability": {"nodes": [{"id": "REQ-001"}], "links": []},
        "verification_evidence": {"reference_collapse": False},
        "research_trace": [{"stage": "repair"}],
    })

    assert row["spec_decision"] == "approve"
    assert row["spec_version"] == 2
    assert row["repair_events"] == 1
    assert row["mutants_total"] == 4
    assert row["spec_strength"] == 1.0
    assert row["plan_clause_coverage"] == 1.0
    assert row["last_failure_type"] == "CODE_ERROR"


def test_summary_keeps_abstention_and_collapse_visible():
    rows = [
        result_row({"status": "verified", "passed": True, "dafny_verified": True}),
        result_row({
            "status": "abstained",
            "spec_artifact": {"decision": "abstain"},
            "verification_evidence": {"reference_collapse": True},
        }),
    ]

    summary = summarize(rows)

    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["spec_abstained"] == 1
    assert summary["reference_collapses"] == 1


def test_csv_uses_the_stable_current_schema(tmp_path):
    path = tmp_path / "results.csv"
    rows = [result_row({"task_id": "t"})]

    write_csv(rows, path)

    with path.open(encoding="utf-8-sig") as handle:
        header = next(csv.reader(handle))
    assert "spec_decision" in header
    assert "reference_collapse" in header
