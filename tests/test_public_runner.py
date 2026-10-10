"""Runner control-flow fixtures, explicitly not research model results."""
import copy
import json

import pytest

from generation.public_benchmark.task import PublicTask
from generation.public_benchmark import runner


def task():
    return PublicTask({'id':'T1','source':'fixture','source-id':'1','vc-description':'Increment x.',
        'vc-preamble':'','vc-helpers':'','vc-spec':'method Solve(x:int) returns(y:int) ensures y == x+1',
        'vc-code':'PRIVATE_REFERENCE_SENTINEL','vc-postamble':''},family_id='F1')


def structure(source=''):
    return {'status':'ok','trusted_ast':True,'declarations':[{'id':'Solve','name':'Solve','kind':'method',
        'header_tokens':['method','changed' if 'BAD_CONTRACT' in source else 'fixed'],
        'tokens':[source],'contract_bindings':[], 'depends_on':[], 'body':source,
        'source_region':[0,len(source)], 'verifier_names':['Solve']}], 'findings':[]}


class Model:
    kind='mock'
    def __init__(self, results): self.results=iter(results); self.messages=[]
    def identity(self): return {'kind':'mock','model':'synthetic','effort':'high'}
    def generate(self,messages,output_dir,**kwargs):
        self.messages.append(copy.deepcopy(messages))
        output_dir.mkdir()
        return next(self.results)


def answer(body='{ y := x+1; }', **kwargs):
    return {'text':json.dumps({'implementation':body,'helpers':''}),'error':None,
        'input_tokens':100,'output_tokens':10,'usage_source':'synthetic_fixture',
        'executed':True,'output_cap_enforced':False, **kwargs}


class Verifier:
    calls=0
    outcomes=[]
    def __init__(self,**kwargs): pass
    def identity(self): return {'real_verifier':False,'version':'synthetic'}
    def verify(self, source, **kwargs):
        type(self).calls += 1
        return copy.deepcopy(type(self).outcomes.pop(0))


def evidence(passed=True):
    return {'status':'unknown' if passed else 'verification_failed','stdout':
        'Dafny program verifier finished with 1 verified, 0 errors' if passed else
        'Dafny program verifier finished with 0 verified, 1 error',
        'stderr':'','returncode':0 if passed else 4,'executed':True,'real_verifier':True,
        'obligations':{'Solve (correctness)':'passed' if passed else 'failed'},
        'csv_log':'TestResult.DisplayName,TestResult.Outcome\nSolve (correctness),'+('Passed' if passed else 'Failed')+'\n',
        'diagnostics':[],'seconds':.1,'command':['synthetic']}


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    Verifier.calls=0; Verifier.outcomes=[]
    monkeypatch.setattr(runner,'Dafny',Verifier)
    monkeypatch.setattr(runner,'inspect_source',structure)


def test_success_requires_primary_batch_and_marks_mock_ineligible(tmp_path):
    Verifier.outcomes=[evidence()]
    result=runner.run_trial(task(),structure(),['Solve'],Model([answer()]),tmp_path/'trial','D')
    assert result['success'] and result['complete']
    assert result['research_eligible'] is False
    assert result['model_calls']==result['verifier_calls']==1
    assert result['rounds'][0]['changed_declarations']==['Solve']


def test_contract_mutation_never_reaches_verifier(tmp_path):
    result=runner.run_trial(task(),structure(),['Solve'],Model([answer('{ BAD_CONTRACT }')]),tmp_path/'trial','A',budget={'max_model_actions':1})
    assert not result['success'] and Verifier.calls==0
    assert result['rounds'][0]['guard_findings'][0]['code']=='contract_changed'


def test_output_overshoot_counts_usage_but_never_accepts(tmp_path):
    result=runner.run_trial(task(),structure(),['Solve'],Model([answer(output_tokens=16385)]),tmp_path/'trial','A')
    assert not result['success'] and Verifier.calls==0
    assert result['output_tokens']==16385
    assert result['stop_reason']=='output_token_budget'


def test_transport_failure_is_terminal_with_no_free_reroll(tmp_path):
    model=Model([answer(text='',error='process_timeout',input_tokens=None,output_tokens=None)])
    result=runner.run_trial(task(),structure(),['Solve'],model,tmp_path/'trial','B')
    assert result['stop_reason']=='model_infrastructure_failure'
    assert Verifier.calls==0 and len(model.messages)==1
    assert result['usage_complete'] is False and result['research_eligible'] is False


def test_iteration_forwards_full_actual_feedback_and_never_reference(tmp_path):
    Verifier.outcomes=[evidence(False),evidence(True)]
    model=Model([answer('{ y := x; }'),answer()])
    frozen=structure('PRIVATE_REFERENCE_SENTINEL')
    result=runner.run_trial(task(),frozen,['Solve'],model,tmp_path/'trial','C')
    assert result['success'] and result['model_calls']==2
    second=json.loads(model.messages[1][1]['content'])
    assert '0 verified, 1 error' in json.dumps(second['history'])
    assert 'PRIVATE_REFERENCE_SENTINEL' not in json.dumps(model.messages)
    assert second['current_source'].find('y := x;')>=0


def test_completed_resume_validates_hashes_and_refuses_different_identity(tmp_path):
    Verifier.outcomes=[evidence()]
    first=runner.run_trial(task(),structure(),['Solve'],Model([answer()]),tmp_path/'trial','A')
    resumed=runner.run_trial(task(),structure(),['Solve'],Model([]),tmp_path/'trial','A')
    assert first==resumed
    with pytest.raises(ValueError):
        runner.run_trial(task(),structure(),['Solve'],Model([]),tmp_path/'trial','B')
    (tmp_path/'trial'/'result.json').write_text('{}')
    with pytest.raises(ValueError):
        runner.run_trial(task(),structure(),['Solve'],Model([]),tmp_path/'trial','A')


def test_incomplete_output_directory_refuses_overwrite(tmp_path):
    folder=tmp_path/'trial'; folder.mkdir()
    with pytest.raises(FileExistsError):
        runner.run_trial(task(),structure(),['Solve'],Model([]),folder,'A')


def test_no_primary_batch_is_not_success(tmp_path):
    row=evidence(); row['obligations']={'Helper (correctness)':'passed'}
    Verifier.outcomes=[row]
    result=runner.run_trial(task(),structure(),['Solve'],Model([answer()]),tmp_path/'trial','A',budget={'max_model_actions':1})
    assert not result['success']
    assert result['rounds'][0]['verification']['status']=='unknown'


def test_obligation_claim_without_matching_csv_is_not_success(tmp_path):
    row=evidence(); row['csv_log']='TestResult.DisplayName,TestResult.Outcome\nOther (correctness),Passed\n'
    Verifier.outcomes=[row]
    result=runner.run_trial(task(),structure(),['Solve'],Model([answer()]),tmp_path/'trial','A',budget={'max_model_actions':1})
    assert not result['success']


def test_real_dafny_assembly_integration_is_not_model_efficacy(tmp_path,monkeypatch):
    monkeypatch.undo()
    public=task()
    frozen=runner.inspect_source(public.skeleton)
    assert frozen['status']=='ok',frozen
    result=runner.run_trial(public,frozen,['Solve'],Model([answer()]),tmp_path/'real-verifier-fixture','D')
    assert result['success'],result
    assert result['real_verifier_calls']==1
    assert result['research_eligible'] is False
    assert result['rounds'][0]['verification']['primary_batches']=={'Solve (correctness)':'passed'}


def test_duplicate_json_regions_are_rejected_without_verification(tmp_path):
    model=Model([answer(text='{"implementation":"{}","implementation":"{ y := x+1; }","helpers":""}')])
    result=runner.run_trial(task(),structure(),['Solve'],model,tmp_path/'trial','A',budget={'max_model_actions':1})
    assert not result['success'] and result['verifier_calls']==0
    assert result['rounds'][0]['guard_findings'][0]['code']=='invalid_candidate_json'


def test_nonfinite_budget_cannot_disable_deadline(tmp_path):
    with pytest.raises(ValueError):
        runner.run_trial(task(),structure(),['Solve'],Model([]),tmp_path/'trial','A',budget={'session_timeout':float('nan')})


def test_fixed_public_function_is_dependency_not_generation_target(tmp_path,monkeypatch):
    public=task(); public.record['vc-preamble']='function Inc(x:int):int { x+1 }'
    public=PublicTask(public.record,family_id='F1')
    def report(source=''):
        result=structure(source)
        inc=copy.deepcopy(result['declarations'][0])
        inc.update(id='Inc',name='Inc',kind='function',tokens=['frozen Inc'],body='{ x+1 }',verifier_names=['Inc'])
        result['declarations'][0]['depends_on']=['Inc']
        result['declarations'][0]['contract_bindings']=['Ens:member:Inc']
        result['declarations'].insert(0,inc)
        return result
    monkeypatch.setattr(runner,'inspect_source',report)
    Verifier.outcomes=[evidence()]
    model=Model([answer()])
    result=runner.run_trial(public,report(),['Solve'],model,tmp_path/'trial','C')
    payload=json.loads(model.messages[0][-1]['content'])
    assert payload['target']['id']=='Solve'
    assert payload['parsed_declarations'][0]['editable'] is False
    assert payload['parsed_declarations'][1]['editable'] is True
    assert result['success']
