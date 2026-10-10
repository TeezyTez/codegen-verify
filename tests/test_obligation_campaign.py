import copy
from pathlib import Path

import pytest

from generation.obligations.config import default_config
from generation.representation.task import load_tasks

ROOT = Path(__file__).resolve().parents[1]


def test_plan_blocks_determinism_and_unknown_cost():
    from generation.obligations.campaign import plan
    tasks = load_tasks(ROOT/'generation/representation/tasks')[:2]
    c = default_config(); c['replicates'] = 3
    a = plan(tasks, c); b = plan(list(reversed(tasks)), c)
    assert a == b
    assert len(a['jobs']) == 24 and a['maximum_model_calls'] == 96
    assert a['maximum_cost_usd'] is None
    keys = {(j['task_id'], j['strategy'], j['replicate']) for j in a['jobs']}
    assert len(keys) == 24
    for offset in range(0, 24, 4):
        block = a['jobs'][offset:offset+4]
        assert len({(j['task_id'],j['replicate']) for j in block}) == 1
        assert {j['strategy'] for j in block} == set(c['strategies'])
    assert plan(tasks, c, schedule_seed=91)['jobs'] != a['jobs']
    with pytest.raises(ValueError, match='duplicate'):
        plan(tasks+tasks, c)


def summary():
    conditions = []
    for strategy in ('baseline','state','guided','independent_sampling'):
        conditions.append({'strategy': strategy, 'representation': 'contract', 'is_mock': False,
            'config_sha256': 'same', 'audit_status': 'reviewed',
            'by_task': {t:{'runs':3, 'replicate_ids':[0,1,2], 'success_fraction':float(strategy=='guided')}
                        for t in ('one','two','three')}})
    return {'complete_matrix':True, 'conditions':conditions, 'protocol':'fixed_spec_obligation_v1'}


def test_paired_effect_uses_cluster_units_not_trials():
    from generation.obligations.campaign import paired
    result = paired(summary(), clusters={'one':'shared','two':'shared','three':'different'}, draws=100)
    main = result['contrasts']['guided-baseline']
    assert main['difference'] == 1 and main['ci95'] == [1,1]
    assert result['task_count'] == 3 and result['cluster_count'] == 2
    assert result['replicates_per_task'] == 3
    assert result['confirmatory'] is False


def test_explicit_empty_cluster_mapping_is_rejected():
    from generation.obligations.campaign import paired
    with pytest.raises(ValueError, match='cluster mapping'):
        paired(summary(), clusters={}, draws=100)


def test_cli_analysis_requires_expected_jobs_manifest(tmp_path, monkeypatch):
    from generation.obligations import campaign
    monkeypatch.setattr(campaign, 'summarize', lambda _: summary())
    runs = tmp_path/'runs'
    runs.mkdir()
    with pytest.raises(ValueError, match='jobs.json'):
        campaign.main(['analyze', '--runs', str(runs), '--output', str(tmp_path/'analysis')])
    assert not (tmp_path/'analysis').exists()


@pytest.mark.parametrize('change', [
    lambda s:s.update(complete_matrix=False),
    lambda s:s['conditions'].pop(),
    lambda s:s['conditions'][0]['by_task'].pop('one'),
    lambda s:s['conditions'][0]['by_task']['one'].update(replicate_ids=[0,1]),
    lambda s:s['conditions'][0].update(config_sha256='different'),
])
def test_unbalanced_or_incomplete_summary_is_rejected(change):
    from generation.obligations.campaign import paired
    s=copy.deepcopy(summary()); change(s)
    with pytest.raises(ValueError):
        paired(s, draws=100)


def test_cli_plan_refuses_overwrite(tmp_path):
    from generation.obligations.campaign import main
    args=['plan','--tasks',str(ROOT/'generation/representation/tasks'),
          '--config',str(ROOT/'generation/obligations/configs/demo.json'),'--output',str(tmp_path/'plan')]
    assert main(args) == 0
    assert (tmp_path/'plan/campaign.json').is_file()
    with pytest.raises(FileExistsError):
        main(args)
