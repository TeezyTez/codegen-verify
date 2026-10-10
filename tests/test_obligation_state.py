"""Evidence must not outlive its exact candidate or gain truth from a model claim."""
import copy
from pathlib import Path

from generation.representation.task import Task
from generation.representation.verifier import Verification

ROOT = Path(__file__).resolve().parents[1]


def task():
    return Task.load(ROOT/'generation/representation/tasks/absolute/task.json')


def test_changed_candidate_invalidates_proof_and_preserves_original_observation():
    from generation.obligations.state import EvidenceState
    t = task()
    state = EvidenceState(t, {'version': '4.11.0'})
    correct = t.assemble(t.meta['reference'])
    state.observe(correct, Verification('verified', executed=True, real_verifier=True,
                  obligations={'Absolute (correctness)': 'passed'}), 'round_001')
    before = copy.deepcopy(state.snapshot())
    assert before['obligations']['R1']['status'] == 'DISCHARGED'
    state.begin_candidate(t.assemble(t.meta['mutants'][0]['bodies']))
    assert state.snapshot()['obligations']['R1']['status'] == 'STALE'
    assert state.snapshot()['observations'][0] == before['observations'][0]


def test_disappearing_error_does_not_discharge_requirement():
    from generation.obligations.state import EvidenceState
    t = task()
    state = EvidenceState(t, {})
    source = t.assemble(t.meta['mutants'][0]['bodies'])
    state.observe(source, Verification('verification_failed', executed=True, real_verifier=True,
                  diagnostics=[{'subtype': 'postcondition', 'location_line': 2}]), 'round_001')
    assert state.snapshot()['obligations']['R1']['status'] == 'UNPROVED'
    state.observe(source, Verification('verification_failed', executed=True, real_verifier=True), 'round_002')
    assert state.snapshot()['obligations']['R1']['status'] != 'DISCHARGED'
    assert state.snapshot()['obligations']['R2']['status'] != 'DISCHARGED'


def test_verified_candidate_has_no_historical_diagnostic_target():
    from generation.obligations.state import EvidenceState
    t = task(); state = EvidenceState(t, {})
    state.observe(t.assemble(t.meta['mutants'][0]['bodies']), Verification('verification_failed',
                  real_verifier=True, executed=True,
                  diagnostics=[{'subtype':'postcondition','location_line':2}]), 'round_001')
    state.observe(t.assemble(t.meta['reference']), Verification('verified',
                  real_verifier=True, executed=True,
                  obligations={'Absolute (correctness)':'passed'}), 'round_002')
    assert state.select_target() is None
    assert state.observations[0]['diagnostic']['diagnostics']


def test_fixture_verified_is_not_proof_and_timeout_is_unknown():
    from generation.obligations.state import EvidenceState
    t = task()
    state = EvidenceState(t, {})
    source = t.assemble(t.meta['reference'])
    state.observe(source, Verification('verified'), 'round_001')
    assert state.snapshot()['obligations']['R1']['status'] == 'UNKNOWN'
    state.observe(source, Verification('timeout', executed=True, real_verifier=True), 'round_002')
    assert state.snapshot()['obligations']['R1']['status'] == 'UNKNOWN'


def test_repeat_counts_submissions_but_not_final_reverification():
    from generation.obligations.state import EvidenceState
    t = task()
    state = EvidenceState(t, {})
    source = t.assemble(t.meta['reference'])
    for label in ('round_001', 'round_002', 'final'):
        state.observe(source, Verification('verification_failed'), label)
    assert state.snapshot()['metrics']['candidate_submissions'] == 2
    assert state.snapshot()['metrics']['repeated_candidates'] == 1


def test_targets_prioritize_parse_errors_and_return_detached_snapshots():
    from generation.obligations.state import EvidenceState
    t = task()
    state = EvidenceState(t, {})
    state.observe(t.assemble(t.meta['reference']), Verification('parse_error',
                  diagnostics=[{'subtype': 'undefined', 'location_line': 5}]), 'round_001')
    target = state.select_target()
    assert target['kind'] == 'diagnostic'
    assert target['category'] == 'undefined_name'
    snapshot = state.snapshot()
    snapshot['obligations'].clear()
    assert state.snapshot()['obligations']


def test_toolchain_identity_changes_evidence_identity():
    from generation.obligations.state import EvidenceState
    t = task()
    source = t.assemble(t.meta['reference'])
    identities = []
    for version in ('4.11.0', 'different'):
        state = EvidenceState(t, {'version': version})
        state.observe(source, Verification('timeout'), 'round_001')
        identities.append(state.snapshot()['identity'])
    assert identities[0]['candidate_sha256'] == identities[1]['candidate_sha256']
    assert identities[0]['toolchain_sha256'] != identities[1]['toolchain_sha256']


def test_observed_method_batch_regression_is_distinct_from_lost_observability():
    from generation.obligations.state import EvidenceState
    t = task(); state = EvidenceState(t, {})
    state.observe(t.assemble(t.meta['reference']), Verification('verification_failed',
                  real_verifier=True, executed=True, obligations={'Absolute (correctness)': 'passed'}), 'round_001')
    assert state.snapshot()['obligations']['M:Absolute']['status'] == 'DISCHARGED'
    assert state.snapshot()['obligations']['R1']['status'] != 'DISCHARGED'
    state.observe(t.assemble(t.meta['mutants'][0]['bodies']), Verification('verification_failed',
                  real_verifier=True, executed=True, obligations={'Absolute (correctness)': 'failed'}), 'round_002')
    assert state.snapshot()['metrics']['proof_regressions'] == 1
    assert state.snapshot()['metrics']['lost_observability'] == 0


def test_precondition_remains_assumption_after_whole_program_success():
    from generation.obligations.state import EvidenceState
    t = Task.load(ROOT/'generation/representation/tasks/clamp/task.json')
    state = EvidenceState(t, {})
    state.observe(t.assemble(t.meta['reference']), Verification('verified', real_verifier=True,
                  executed=True, obligations={n+' (correctness)': 'passed' for n in t.names}), 'round_001')
    assumptions = [v for v in state.snapshot()['obligations'].values() if v['kind'] == 'assumption']
    assert assumptions and all(v['status'] == 'UNOBSERVED' for v in assumptions)


def test_mapped_timeout_diagnostic_is_unknown_not_a_proof_regression():
    from generation.obligations.state import EvidenceState
    t = task(); state = EvidenceState(t, {})
    state.observe(t.assemble(t.meta['reference']), Verification('verified', executed=True,
                  real_verifier=True, obligations={'Absolute (correctness)': 'passed'}), 'round_001')
    state.observe(t.assemble(t.meta['mutants'][0]['bodies']), Verification('timeout', executed=True,
                  real_verifier=True, diagnostics=[{'subtype': 'timeout', 'location_line': 2}]), 'round_002')
    snapshot = state.snapshot()
    assert snapshot['obligations']['R1']['status'] == 'UNKNOWN'
    assert all(v['status'] == 'UNKNOWN' for v in snapshot['obligations'].values() if v['kind'] == 'diagnostic')
    assert snapshot['metrics']['proof_regressions'] == 0
    assert snapshot['metrics']['lost_observability'] == 3
