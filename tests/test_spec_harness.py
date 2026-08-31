import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from spec_harness import build_spec_harness


def test_spec_harness_preserves_unknowns_instead_of_claiming_unmeasured_evidence():
    harness = build_spec_harness(
        decision="approve",
        mutation={"mutants_total": 4, "mutants_verified": 0},
        critic_report={
            "public_precondition_review": {"status": "passed"},
            "executable_boundary_checks": {
                "status": "passed", "checks_scheduled": 3, "checks_run": 3
            },
        },
    )

    assert harness.cells["negative_implementations"]["rejected"] == 4
    assert harness.cells["postcondition_completeness"]["mutation_kill_rate"] == 1.0
    assert "equivalence_or_uniqueness" in harness.missing_evidence
    assert harness.risk == "medium"


def test_spec_harness_marks_surviving_mutants_as_failed_evidence():
    harness = build_spec_harness(
        decision="reject",
        mutation={"mutants_total": 4, "mutants_verified": 1},
    )

    assert "negative_implementations" in harness.failed_cells
    assert harness.risk == "high"

