"""Synthetic records only; these tests never execute research model calls."""
from copy import deepcopy
import json

import pytest

from research import analyze_main_public_20261009 as main
from generation.public_benchmark.task import canonical, digest


def fixture(root):
    rows, jobs, tasks = [], [], {}
    for index in range(2):
        task = f'T{index}'
        tasks[task] = {'family_id': f'F{index}', 'split': 'test', 'editable_ids': ['M']}
        for rep in range(3):
            for arm in 'ABCD':
                folder = root / 'runs' / f'{task}-{rep}-{arm}'
                folder.mkdir(parents=True)
                manifest = {'task': {'id': task}, 'model': {'model': 'synthetic'}, 'arm': arm, 'replicate': rep}
                messages = [{'role': 'user', 'content': 'same C/D initial message'}]
                (folder / 'round-01').mkdir()
                (folder / 'round-01/messages.json').write_text(json.dumps(messages), encoding='utf8')
                eligible = not (index == 0 and rep == 0 and arm == 'D')
                row = {'model': 'synthetic', 'task_id': task, 'family_id': f'F{index}', 'arm': arm,
                       'replicate': rep, 'complete': True, 'research_eligible': eligible,
                       'success': eligible, 'successful_action': 1 if eligible else None,
                       'model_calls': 1, 'verifier_calls': int(eligible), 'seconds': 1,
                       'stop_reason': 'verified' if eligible else 'runner_infrastructure_failure',
                       'rounds': [{'action': 1, 'generation': {'input_tokens': 10, 'output_tokens': 5},
                                   'ledger_after': {'declarations': {'M': {'editable': True},
                                                                       'H': {'editable': True},
                                                                       'P': {'editable': False}}},
                                   'scheduler_audit': {'open_editable_targets': ['M', 'H'],
                                                       'structural_target': {'id': 'M'},
                                                       'evidence_target': {'id': 'H'},
                                                       'target_disagreement': True}}],
                       'artifact_sha256': {'round-01/messages.json': digest(json.dumps(messages))},
                       'manifest_sha256': digest(canonical(manifest))}
                save(folder / 'manifest.json', manifest)
                save(folder / 'result.json', row)
                (folder / 'result.sha256').write_text(digest(canonical(row)))
                rows.append(row)
                jobs.append({'task_id': task, 'arm': arm, 'replicate': rep, 'directory': folder.name})
    audit = {'ids': list(tasks), 'test_family_count': 2, 'no_main_outcomes_exist': True,
             'structural_strata': {'T0': {'extra_helpers': 0}, 'T1': {'extra_helpers': 2}}}
    manifest = {'phase': 'main_public', 'model': {'model': 'synthetic'}, 'expected_sessions': 24,
                'jobs_sha256': digest(canonical(jobs)), 'tasks_sha256': digest(canonical(tasks))}
    audit.update({k: manifest[k] for k in ('jobs_sha256', 'tasks_sha256')})
    manifest['prelaunch_audit_sha256'] = digest(canonical(audit))
    for name, value in [('jobs', jobs), ('tasks', tasks), ('results', rows), ('manifest', manifest), ('prelaunch-audit', audit)]:
        save(root / (name + '.json'), value)
    return rows


def save(path, value):
    path.write_text(json.dumps(value), encoding='utf8')


def test_primary_itt_preserves_failure_and_sensitivity_drops_whole_family(tmp_path):
    rows = fixture(tmp_path)
    before = deepcopy(rows)
    result = main.analyze_completed(tmp_path, bootstrap=20)
    primary = result['primary_itt']['models']['synthetic']
    assert primary['families'] == 2
    assert primary['arm_rates']['D'] == pytest.approx(5/6)
    assert result['primary_itt']['complete_matrix']
    assert result['sensitivity_complete_eligible_families']['included_families'] == ['F1']
    assert result['sensitivity_complete_eligible_families']['paired']['recorded_sessions'] == 12
    assert result['noneligible_failures'][0]['task_id'] == 'T0'
    assert result['sessions'][3]['research_eligible'] is False
    assert json.loads((tmp_path / 'results.json').read_text()) == before
    assert result['exploratory']['strata']['reference_helpers_0']['sessions'] == 12
    assert result['exploratory']['first_action_cd']['prompt_equality']['equal_pairs'] == 6
    assert len(result['exploratory']['scheduler_cases']) == 24
    assert result['task_arm_rates']['T0']['D']['failure_stop_reasons'] == {'runner_infrastructure_failure': 1}


def test_incomplete_roster_fails_before_analysis(tmp_path):
    fixture(tmp_path)
    rows = json.loads((tmp_path / 'results.json').read_text())
    save(tmp_path / 'results.json', rows[:-1])
    with pytest.raises(ValueError, match='aggregate results'):
        main.analyze_completed(tmp_path, bootstrap=20)


def test_prelaunch_tampering_rejected(tmp_path):
    fixture(tmp_path)
    p = tmp_path / 'prelaunch-audit.json'
    value = json.loads(p.read_text()); value['structural_strata']['T0']['extra_helpers'] = 7
    save(p, value)
    with pytest.raises(ValueError, match='prelaunch'):
        main.analyze_completed(tmp_path, bootstrap=20)


def test_prompt_disagreement_is_not_silently_a_noise_control(tmp_path):
    fixture(tmp_path)
    folder = tmp_path / 'runs/T0-0-D'
    path = folder / 'round-01/messages.json'
    path.write_text('[{"role":"user","content":"different"}]')
    row = json.loads((folder / 'result.json').read_text())
    row['artifact_sha256']['round-01/messages.json'] = digest(path.read_text())
    save(folder / 'result.json', row)
    (folder / 'result.sha256').write_text(digest(canonical(row)))
    rows = json.loads((tmp_path / 'results.json').read_text())
    rows[3] = row; save(tmp_path / 'results.json', rows)
    result = main.analyze_completed(tmp_path, bootstrap=20)
    control = result['exploratory']['first_action_cd']
    assert control['prompt_equality']['unequal_pairs'] == 1
    assert control['noise_control_valid'] is False


def test_output_is_external_fresh_and_source_unchanged(tmp_path):
    root = tmp_path / 'campaign'; root.mkdir(); fixture(root)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='outside'):
        main.write_analysis(root, root / 'analysis', bootstrap=20)
    output = tmp_path / 'analysis'
    main.write_analysis(root, output, bootstrap=20)
    assert 'ITT' in (output / 'report.zh.md').read_text(encoding='utf8')
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
    with pytest.raises(FileExistsError):
        main.write_analysis(root, output, bootstrap=20)


def update_row(root, index, change):
    rows = json.loads((root / 'results.json').read_text())
    row = rows[index]; change(row)
    folder = root / 'runs' / f"{row['task_id']}-{row['replicate']}-{row['arm']}"
    save(folder / 'result.json', row)
    (folder / 'result.sha256').write_text(digest(canonical(row)))
    save(root / 'results.json', rows)


def test_live_infra_can_still_be_eligible_and_timeout_stays_in_sensitivity(tmp_path):
    fixture(tmp_path)
    update_row(tmp_path, 3, lambda r: r.update(research_eligible=True))
    update_row(tmp_path, 12, lambda r: r.update(success=False, successful_action=None, stop_reason='session_timeout'))
    result = main.analyze_completed(tmp_path, bootstrap=20)
    assert result['original_eligible_filter_would_exclude'] == 0
    assert len(result['infrastructure_events']) == 1
    assert result['sensitivity_complete_eligible_families']['included_families'] == ['F0', 'F1']
    assert result['sensitivity_complete_infrastructure_free_families']['included_families'] == ['F1']


def test_generated_helpers_preserve_unknown_and_reference_distinction(tmp_path):
    fixture(tmp_path)
    update_row(tmp_path, 3, lambda r: r['rounds'][0].pop('ledger_after'))
    result = main.analyze_completed(tmp_path, bootstrap=20)
    helpers = result['exploratory']['generated_vs_reference_helpers']
    assert helpers[0]['reference_extra_helpers'] == 0
    assert helpers[0]['max_observed_generated_helpers'] == 1
    assert helpers[3]['max_observed_generated_helpers'] is None
    assert helpers[3]['unknown_rounds'] == 1


def test_two_repeats_per_family_are_not_accepted_as_full_main(tmp_path):
    fixture(tmp_path)
    original = main.stored._load
    def fewer(root):
        rows, context = original(root)
        return [r for r in rows if r['replicate'] != 2], context
    from unittest.mock import patch
    with patch.object(main.stored, '_load', side_effect=fewer):
        with pytest.raises(ValueError, match='twelve'):
            main.analyze_completed(tmp_path, bootstrap=20)
