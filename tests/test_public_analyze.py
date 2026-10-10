"""Synthetic saved campaign records, never live research results."""
from copy import deepcopy
import json

import pytest

from generation.public_benchmark import analyze
from generation.public_benchmark.task import canonical, digest


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')


def trial(folder,arm='A',success=True,audit=True):
    manifest={'arm':arm,'replicate':0,'task':{'id':'T1','family_id':'old-family'},'model':{'model':'synthetic'}}
    rounds=[{'action':1,'generation':{'input_tokens':10000,'output_tokens':1000,'usage':{'input_tokens':10000,'output_tokens':1000,'cached_input_tokens':300}},
             'selected_target':{'id':'M'} if arm in 'CD' else None,'target_followed':True}]
    if audit:
        rounds[0]['scheduler_audit']={'open_editable_targets':['M','Helper'],
            'structural_target':{'id':'M'},'evidence_target':{'id':'Helper'},'target_disagreement':True}
    row={'model':'synthetic','task_id':'T1','family_id':'old-family','arm':arm,'replicate':0,
         'success':success,'successful_action':1 if success else None,'complete':True,'research_eligible':True,
         'model_calls':1,'verifier_calls':1,'input_tokens':10000,'output_tokens':1000,'total_tokens':11000,
         'usage_complete':True,'seconds':2,'verifier_seconds':1,'stop_reason':'verified' if success else 'model_action_budget',
         'rounds':rounds,'ledger_metrics':{'proof_regressions':2},'artifact_sha256':{},
         'manifest_sha256':digest(canonical(manifest))}
    save(folder/'manifest.json',manifest); save(folder/'result.json',row)
    (folder/'result.sha256').write_text(digest(canonical(row)))
    return row


def campaign(folder, audit=True):
    rows=[]; jobs=[]
    for arm in 'ABCD':
        jobs.append({'task_id':'T1','arm':arm,'replicate':0,'directory':arm})
        rows.append(trial(folder/'runs'/arm,arm,success=arm!='A',audit=audit))
    tasks={'T1':{'family_id':'frozen-family','split':'development'}}
    save(folder/'jobs.json',jobs); save(folder/'tasks.json',tasks); save(folder/'results.json',rows)
    save(folder/'manifest.json',{'phase':'development_fixture','model':{'model':'synthetic'},
        'expected_sessions':4,'jobs_sha256':digest(canonical(jobs)),'tasks_sha256':digest(canonical(tasks))})
    return rows


def test_exact_roster_frozen_family_and_budget_curves(tmp_path):
    campaign(tmp_path)
    summary=analyze.analyze(tmp_path,bootstrap=20)
    assert summary['exact_roster_verified'] and summary['phase']=='development_fixture'
    assert summary['family_count']==1 and summary['family_mapping_source']=='campaign.tasks.json'
    assert summary['trials'][0]['family_id']=='frozen-family'
    assert summary['arms']['A']['itt_success_rate']==0
    assert summary['arms']['D']['action_success_curve']['1']['rate']==1
    assert summary['arms']['D']['token_success_curve']['16000']['rate']==1
    assert summary['arms']['D']['usage']['reported_output_tokens']==1000
    assert summary['arms']['D']['scheduler']['opportunity_rounds']==1
    assert summary['scheduler']['opportunity_rounds']==4
    assert summary['scheduler']['counterfactual_disagreement_rounds']==4
    assert summary['d_target_following']['followed']==1
    assert summary['proof_regressions']['reported_total']==8
    assert summary['usage']['raw_fields']['cached_input_tokens']['reported_sum']==1200
    assert summary['paired']['models']['synthetic']['families']==1


def test_old_canary_missing_scheduler_is_unavailable_not_zero(tmp_path):
    campaign(tmp_path,audit=False)
    summary=analyze.analyze(tmp_path,bootstrap=20)
    assert summary['scheduler']['availability']=='unavailable'
    assert summary['scheduler']['opportunity_rounds'] is None
    assert summary['scheduler']['counterfactual_disagreement_rounds'] is None
    assert '不可用' in analyze.render_markdown(summary)


@pytest.mark.parametrize('mutation',['duplicate','missing','unexpected','mismatch'])
def test_roster_rejects_missing_duplicate_extra_or_mismatched_results(tmp_path,mutation):
    rows=campaign(tmp_path)
    if mutation=='duplicate': rows.append(rows[0])
    elif mutation=='missing': rows.pop()
    elif mutation=='unexpected': rows[0]['task_id']='OTHER'
    else: rows[0]['success']=True
    save(tmp_path/'results.json',rows)
    with pytest.raises(ValueError): analyze.analyze(tmp_path,bootstrap=20)


def test_single_trial_unknown_usage_does_not_become_free_success(tmp_path):
    row=trial(tmp_path,audit=False)
    row['rounds'][0]['generation']['input_tokens']=None
    row['usage_complete']=False
    save(tmp_path/'result.json',row); (tmp_path/'result.sha256').write_text(digest(canonical(row)))
    summary=analyze.analyze(tmp_path,bootstrap=20)
    assert summary['kind']=='single_trial'
    assert summary['arms']['A']['token_success_curve']['16000']['successes']==0
    assert summary['arms']['A']['token_success_curve']['16000']['unknown_successes']==1
    assert summary['usage']['unknown_usage_calls']==1


def test_artifact_tampering_is_rejected(tmp_path):
    row=trial(tmp_path)
    (tmp_path/'candidate.dfy').write_text('original')
    row['artifact_sha256']={'candidate.dfy':digest('original')}
    save(tmp_path/'result.json',row); (tmp_path/'result.sha256').write_text(digest(canonical(row)))
    (tmp_path/'candidate.dfy').write_text('changed')
    with pytest.raises(ValueError): analyze.analyze(tmp_path,bootstrap=20)


def test_report_writer_preserves_source_and_refuses_output_replacement(tmp_path):
    source=tmp_path/'campaign'; campaign(source)
    before={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    output=tmp_path/'analysis'
    result=analyze.write_analysis(source,output,bootstrap=20)
    assert (output/'summary.json').exists() and (output/'report.zh.md').exists()
    assert '开发' in (output/'report.zh.md').read_text(encoding='utf-8')
    assert result['study_complete_claim'] is False
    assert before=={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError): analyze.write_analysis(source,output,bootstrap=20)
