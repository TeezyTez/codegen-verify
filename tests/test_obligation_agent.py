"""Protocol contrasts, shared acceptance, and audit isolation (no paid calls)."""
import json
from pathlib import Path

import pytest

from generation.representation.models import Mock
from generation.representation.task import Task
from generation.representation.verifier import Verification

ROOT = Path(__file__).resolve().parents[1]


def task():
    return Task.load(ROOT/'generation/representation/tasks/absolute/task.json')


def test_same_public_contract_and_no_private_assets():
    from generation.obligations.policy import Policy
    t = task()
    packets = [Policy(t, {}).messages(t, 'contract', s) for s in
               ('baseline', 'state', 'guided', 'independent_sampling')]
    assert len({p[0]['content'] for p in packets}) == 1
    public = [json.loads(p[1]['content'])['task'] for p in packets]
    assert all(p == public[0] for p in public)
    assert public[0]['methods'] == t.meta['methods']
    assert set(public[0]) == {'task_id', 'methods', 'shared_definitions', 'requirements'}
    assert 'reference' not in json.dumps(public)


def test_state_and_guidance_are_the_only_prompt_contrasts():
    from generation.obligations.policy import Policy
    t = task(); policy = Policy(t, {})
    source = t.assemble(t.meta['mutants'][0]['bodies'])
    before = policy.messages(t, 'contract', 'independent_sampling')
    diag = policy.observe(source, Verification('verification_failed'), 'round_001')
    packets = {s: json.loads(policy.messages(t, 'contract', s, t.meta['mutants'][0]['bodies'], diag)[1]['content'])
               for s in ('baseline', 'state', 'guided')}
    assert packets['baseline']['history'] == packets['state']['history'] == packets['guided']['history']
    assert packets['baseline']['current_bodies'] == packets['guided']['current_bodies']
    assert 'evidence_state' not in packets['baseline']
    assert packets['state']['evidence_state'] == packets['guided']['evidence_state']
    assert 'target' not in packets['state'] and packets['guided']['target']
    assert 'repair_instruction' in packets['guided']
    assert policy.messages(t, 'contract', 'independent_sampling', {}, diag) == before


def test_config_budget_and_unknown_strategy():
    from generation.obligations.config import default_config, validate_config
    c = default_config(); b = validate_config(c)
    assert (b.model_calls, b.verifier_calls, b.output_tokens) == (4, 5, 4096)
    c['strategies'] = ['invented']
    with pytest.raises(ValueError):
        validate_config(c)


class Verifier:
    def __init__(self, statuses):
        self.statuses = iter(statuses)

    def identity(self):
        return {'real_verifier': False, 'fixture': True}

    def verify(self, source, **kwargs):
        return Verification(next(self.statuses))


@pytest.mark.parametrize('strategy', ['baseline', 'state', 'guided', 'independent_sampling'])
def test_shared_budget_and_fixture_cannot_set_success(tmp_path, strategy):
    from generation.obligations.runner import run
    from generation.obligations.config import default_config
    t = task(); c = default_config()
    row = run(t, Mock(t), Verifier(['verification_failed']*4), tmp_path/'run',
              config=c, strategy=strategy)
    assert not row['success'] and row['completed']
    assert row['usage']['model_calls'] == row['usage']['verifier_calls'] == 4
    assert row['evidence_metrics']['repeated_candidates'] == 2
    state = json.loads((tmp_path/'run/state.json').read_text())
    assert len(state['observations']) == 4
    assert row['protocol'] == 'fixed_spec_obligation_v1'


def test_final_failure_is_not_success_and_foreign_summary_rejected(tmp_path):
    from generation.obligations.runner import run
    from generation.obligations.config import default_config
    from generation.obligations.analyze import summarize
    from generation.representation.analyze import summarize as legacy_summary
    t = task(); folder = tmp_path/'run'
    row = run(t, Mock(t), Verifier(['verified', 'verification_failed']), folder,
              config=default_config(), strategy='guided')
    assert not row['success'] and row['usage']['verifier_calls'] == 2
    report = summarize(folder)
    assert report['recorded_runs'] == 1
    assert report['conditions'][0]['evidence_metrics']['repeated_candidates'] == 0
    with pytest.raises(ValueError, match='foreign protocol'):
        legacy_summary(folder)
    snapshot = json.loads((folder/'state.json').read_text())
    snapshot['observations'].clear()
    (folder/'state.json').write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match='state'):
        summarize(folder)


def test_new_cli_preflight_and_paid_gate(tmp_path, capsys):
    from generation.obligations.cli import main
    from generation.obligations.config import default_config
    assert main(['validate', '--schema-only']) == 0
    preview = tmp_path/'preview.json'
    code = main(['preflight', '--task-id', 'absolute', '--output', str(preview)])
    report = json.loads(preview.read_text())
    assert code in (0, 2) and report['protocol'] == 'fixed_spec_obligation_v1'
    assert not report['api_called']
    assert 'ensures' in report['initial_messages'][1]['content']
    c = default_config()
    c['model'].update(kind='openai', name='offline-only', base_url='https://offline.invalid/v1')
    config = tmp_path/'config.json'; config.write_text(json.dumps(c))
    with pytest.raises(SystemExit) as exc:
        main(['run', '--task-id', 'absolute', '--config', str(config), '--output', str(tmp_path/'live')])
    assert exc.value.code == 2
    assert '--allow-paid' in capsys.readouterr().err
    assert not (tmp_path/'live').exists()


def test_independent_sampling_prompts_identical_across_attempts(tmp_path):
    from generation.obligations.runner import run
    from generation.obligations.config import default_config
    t = task(); folder = tmp_path/'sampling'
    run(t, Mock(t), Verifier(['verification_failed']*4), folder,
        config=default_config(), strategy='independent_sampling')
    prompts = [json.loads(p.read_text())['messages'] for p in sorted(folder.glob('round_*.messages.json'))]
    assert len(prompts) == 4 and all(p == prompts[0] for p in prompts)


def test_interrupt_invalidates_previous_candidate_before_verifier_returns(tmp_path):
    from generation.obligations.runner import run
    from generation.obligations.config import default_config
    from repair.task import digest
    class InterruptVerifier(Verifier):
        def verify(self, source, **kwargs):
            if 'r := -x' in source:
                raise KeyboardInterrupt()
            return Verification('verification_failed')
    t = task(); folder = tmp_path/'interrupted'
    with pytest.raises(KeyboardInterrupt):
        run(t, Mock(t), InterruptVerifier([]), folder, config=default_config(), strategy='guided')
    state = json.loads((folder/'state.json').read_text())
    assert state['identity']['candidate_sha256'] == digest(t.assemble(t.meta['reference']))
    assert state['metrics']['candidate_submissions'] == 2
    row = json.loads((folder/'result.json').read_text())
    assert not row['completed'] and not row['success']


@pytest.mark.parametrize('difference', ['toolchain', 'task'])
def test_summary_rejects_mixed_experimental_identities(tmp_path, difference):
    from generation.obligations.runner import run
    from generation.obligations.config import default_config
    from generation.obligations.analyze import summarize
    from generation.representation.task import asset_hashes
    t = task(); other = t
    if difference == 'task':
        meta = json.loads(t.path.read_text())
        meta['methods'][0]['header'] = meta['methods'][0]['header'].replace('r >= 0', 'r >= -1')
        meta['template'] = meta['template'].replace('r >= 0', 'r >= -1')
        meta['asset_hashes'] = asset_hashes(meta)
        path = tmp_path/'changed-task.json'; path.write_text(json.dumps(meta))
        other = Task.load(path)
    class VersionedVerifier(Verifier):
        def __init__(self, version):
            super().__init__(['verification_failed'])
            self.version = version
        def identity(self):
            return {**super().identity(), 'version': self.version}
    c = default_config(); c['replicates'] = 2; c['budget']['model_calls'] = 1
    folder = tmp_path/'suite'
    for replicate, selected in enumerate((t, other)):
        v = VersionedVerifier(str(replicate) if difference == 'toolchain' else 'same')
        run(selected, Mock(selected), v, folder/str(replicate), config=c, strategy='guided', replicate=replicate)
    with pytest.raises(ValueError, match='mixed '+difference):
        summarize(folder)
