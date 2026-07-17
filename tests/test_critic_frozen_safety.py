"""Frozen safety controls for historically verified-but-wrong specifications.

These tests deliberately use only versioned public examples and task-derived
probes.  No network access, model call, or benchmark log is involved.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "project"))

import config
from spec_critic import execute_approved_boundary_checks, public_example_probes


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "critic_verified_wrong.json"
FROZEN_CASES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]


def _dafny_available() -> bool:
    configured = Path(config.DAFNY_PATH)
    return configured.is_file() or shutil.which(str(config.DAFNY_PATH)) is not None


def _as_boundary_check(probe: dict, *, origin: str) -> dict:
    return {
        "case": probe["case"],
        "input": repr(probe["arguments"]),
        "arguments": probe["arguments"],
        "expected": repr(probe["expected_value"]),
        "expected_value": probe["expected_value"],
        "spec_behavior": "computed_by_harness",
        "matches": True,
        "within_task_domain": probe["within_task_domain"],
        "expected_source": probe["expected_source"],
        "probe_origin": origin,
    }


@pytest.mark.skipif(not _dafny_available(), reason="Dafny CLI is unavailable")
@pytest.mark.parametrize("case", FROZEN_CASES, ids=lambda item: item["task_id"])
def test_frozen_verified_wrong_spec_is_never_approved(case: dict) -> None:
    public_probes = public_example_probes(
        case["task_ir"], entry_point=case["entry_point"]
    )
    checks = [
        *(_as_boundary_check(probe, origin="public_example") for probe in public_probes),
        *(
            _as_boundary_check(probe, origin="task_probe")
            for probe in case["task_probes"]
        ),
    ]
    report = execute_approved_boundary_checks(
        {
            "decision": "approve",
            "confidence": 1.0,
            "summary": "Candidate awaits deterministic safety controls.",
            "issues": [],
            "counterexamples": [],
            "boundary_checks": [],
        },
        spec=case["spec"],
        entry_point=case["entry_point"],
        additional_checks=checks,
    )

    assert public_probes, "Every frozen task must retain its public examples."
    assert case["task_probes"], "Every frozen task must retain a task-derived probe."
    assert report["decision"] != "approve", (
        f"Safety regression: {case['task_id']} was historically verified but wrong "
        "and must not pass the Critic gate."
    )

