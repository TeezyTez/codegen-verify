import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

import pipeline


def _base_state(**updates):
    state = {
        "problem_id": "test",
        "problem_desc": "Return x.",
        "spec": "old spec",
        "code": "old code",
        "entry_point": "f",
        "round": 1,
        "max_rounds": 3,
        "history": [],
        "research_trace": [],
        "spec_adequacy": {},
        "mutation_adequacy": {"mutants_verified": 0},
        "semantic_probe_suite": {},
        "resume_verified_alignment_code": False,
        "spec_critic": {"decision": "approve"},
        "critic_gate_status": "approved",
        "critic_repair_rounds": 0,
        "behavior_error": "wrong result",
        "behavior_detail": {},
        "last_verified_code": "old code",
        "last_verified_spec": "old spec",
    }
    state.update(updates)
    return state


def test_unavailable_probe_suite_is_not_reused_or_cached():
    unavailable = {"status": "unavailable", "error": "temporary", "probes": []}
    captured = {}

    def fake_review(*_args, **kwargs):
        captured["probe_suite"] = kwargs.get("probe_suite")
        return {
            "decision": "abstain",
            "confidence": 0.0,
            "summary": "probe generation unavailable",
            "issues": [],
            "counterexamples": [],
            "probe_generation": {"status": "unavailable", "error": "temporary"},
            "generated_probes": [],
        }

    with patch.object(pipeline.config, "ENABLE_SPEC_CRITIC", True), patch.object(
        pipeline, "critic_llm", return_value=object()
    ), patch.object(
        pipeline, "semantic_probe_llm", return_value=object()
    ), patch.object(
        pipeline, "review_spec_with_llm", side_effect=fake_review
    ):
        result = pipeline.spec_critic_agent(
            _base_state(semantic_probe_suite=unavailable)
        )

    assert captured["probe_suite"] is None
    assert result["semantic_probe_suite"] == {}
    assert result["critic_gate_status"] == "abstained"


def test_alignment_spec_change_invalidates_old_critic_and_rechecks_spec():
    with patch.object(pipeline, "repair_llm", return_value=object()), patch.object(
        pipeline, "repair_alignment_with_llm", return_value="new code"
    ), patch.object(
        pipeline, "extract_alignment_dafny_code", return_value="new code"
    ), patch.object(
        pipeline, "_extract_spec_from_code", return_value="new spec"
    ), patch.object(
        pipeline, "_is_vacuous_spec", return_value=False
    ), patch.object(
        pipeline, "spec_adequacy_snapshot", return_value={"level": "adequate"}
    ), patch.object(
        pipeline.DafnyVerifier,
        "verify",
        return_value=SimpleNamespace(passed=True, errors=[]),
    ):
        result = pipeline.alignment_repair_agent(_base_state())

    assert result["spec"] == "new spec"
    assert result["spec_critic"] == {}
    assert result["critic_gate_status"] == "pending"
    assert result["mutation_adequacy"] == {}
    assert result["resume_verified_alignment_code"] is True
    assert pipeline.decide_after_alignment({**_base_state(), **result}) == "recheck_spec"
    with patch.object(pipeline.config, "ENABLE_SPEC_CRITIC", True):
        assert pipeline.decide_after_critic(
            {**_base_state(), **result, "spec_critic": {"decision": "approve"}}
        ) == "verify"


def test_alignment_without_spec_change_keeps_existing_approval_and_verifies():
    state = _base_state()
    with patch.object(pipeline, "repair_llm", return_value=object()), patch.object(
        pipeline, "repair_alignment_with_llm", return_value="new code"
    ), patch.object(
        pipeline, "extract_alignment_dafny_code", return_value="new code"
    ), patch.object(
        pipeline, "_extract_spec_from_code", return_value=state["spec"]
    ), patch.object(
        pipeline, "_is_vacuous_spec", return_value=False
    ), patch.object(
        pipeline, "spec_adequacy_snapshot", return_value={"level": "adequate"}
    ), patch.object(
        pipeline.DafnyVerifier,
        "verify",
        return_value=SimpleNamespace(passed=True, errors=[]),
    ):
        result = pipeline.alignment_repair_agent(state)

    assert "spec_critic" not in result
    assert "critic_gate_status" not in result
    assert result["resume_verified_alignment_code"] is False
    assert pipeline.decide_after_alignment({**state, **result}) == "verify"


def test_spec_strengthening_that_changes_spec_discards_alignment_resume():
    state = _base_state(
        resume_verified_alignment_code=True,
        mutation_adequacy={"mutants_verified": 1},
    )
    with patch.object(
        pipeline.config, "ENABLE_MUTATION_SPEC_STRENGTHENING", True
    ), patch.object(pipeline, "spec_llm", return_value=object()), patch.object(
        pipeline,
        "repair_spec_with_llm",
        return_value={
            "repaired": True,
            "spec": "strengthened spec",
            "adequacy": {},
            "attempts": 1,
            "error": "",
        },
    ):
        result = pipeline.spec_strengthening_agent(state)

    assert result["spec"] == "strengthened spec"
    assert result["resume_verified_alignment_code"] is False


def test_critic_repair_that_changes_spec_discards_alignment_resume():
    state = _base_state(
        resume_verified_alignment_code=True,
        spec_critic={"decision": "reject", "summary": "wrong spec"},
    )
    with patch.object(pipeline, "spec_llm", return_value=object()), patch.object(
        pipeline,
        "repair_spec_with_llm",
        return_value={
            "repaired": True,
            "spec": "critic repaired spec",
            "adequacy": {},
            "attempts": 1,
            "error": "",
        },
    ):
        result = pipeline.critic_spec_repair_agent(state)

    assert result["spec"] == "critic repaired spec"
    assert result["resume_verified_alignment_code"] is False
