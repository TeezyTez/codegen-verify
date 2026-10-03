"""Protocol, adversarial boundary, offline model, and actual Dafny tests."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from generation.analyze import summarize
from generation.cli import audit, main
from generation.models import Provider, Replay
from generation.oracle import Evidence, Oracle
from generation.runner import prompt_for, run
from generation.task import CONDITIONS, Task, body_check, load_tasks
from generation.templates import Template, RULES
from repair.runner import Limits
from repair.task import BoundaryError
from repair.verifier import Dafny, Result

ROOT = Path(__file__).resolve().parents[1]


def task(name='remaining'):
    return Task.load(ROOT/'generation'/'tasks'/name/'task.json')


class FakeOracle:
    def __init__(self,statuses=None):
        self.statuses = list(statuses or ['passed','passed'])
        self.calls = 0
    def identity(self):
        return {'kind':'unit_test_double'}
    def check(self,t,source,timeout=10,**kwargs):
        self.calls += 1
        status = self.statuses[min(self.calls-1,len(self.statuses)-1)]
        return Evidence(status,structure='passed',formal=status,behavioral='passed' if status=='passed' else 'not_run',
                        verifier_calls=1,runtime_calls=int(status=='passed'),details={'formal':{
                            'obligations':{name+' (correctness)':'passed' if status=='passed' else 'failed' for name in t.names}}})


class Responses:
    kind='scripted_replay'
    def __init__(self,actions):
        self.actions=list(actions)
    def identity(self):
        return {'kind':self.kind,'test':True}
    def generate(self,*args):
        action = self.actions.pop(0) if self.actions else {'action':'stop'}
        if isinstance(action,Exception):
            raise action
        return {'text':action if isinstance(action,str) else json.dumps(action),
                'input_tokens':None,'output_tokens':None,'cost_usd':0}


def correct(t,condition='G11'):
    return {'action':'generate','bodies':t.meta['reference']} if condition in {'G10','G11'} else {
        'action':'generate','source':t.assemble(t.meta['reference'])}


def test_twelve_diagnostics_not_three_independent_sources():
    tasks=load_tasks(ROOT/'generation'/'tasks')
    assert len(tasks)==12 and len({t.meta['family'] for t in tasks})==3
    assert len({t.meta['source_project'] for t in tasks})==1
    assert all(t.meta['split']=='dev' for t in tasks)


@pytest.mark.parametrize('body',[
    'assume false;', 'assert {:axiom} false;', 'r := *;', 'var x :| false;',
    '} method M() {} {', 'while true decreases * {}', 'print 1;',
    'var x := new int[2];', 'expect false;', 'r := 1; // comment',
    'r := 1; /*', 'import X', 'r := "secret";', 'reveal Foo();',
])
def test_generation_profile_rejects_bypasses_and_io(body):
    with pytest.raises(BoundaryError):
        body_check(body)


def test_external_contract_immutable_without_skeleton():
    t=task()
    source=t.assemble(t.meta['reference'])
    assert t.candidate({'action':'generate','source':source},'G00')==source
    for changed in (source.replace('ensures r == cap - used','ensures true'),
                    source+'method Sneak() {}\n',source.replace('requires 0 <= used <= cap','requires false')):
        with pytest.raises(BoundaryError):
            t.candidate({'action':'generate','source':changed},'G00')


def test_full_source_harmless_whitespace_is_not_a_boundary_violation():
    t=task()
    source=t.assemble(t.meta['reference']).replace('  ensures','\tensures').replace('cap - used','cap-used')
    assert t.candidate({'action':'generate','source':source},'G00')==source
    with pytest.raises(BoundaryError):
        t.extract(source.replace('requires 0','requires0'))


@pytest.mark.parametrize('condition',CONDITIONS)
def test_same_semantic_inputs_and_no_reference_leak(condition):
    t=task('reserve_twice')
    p=prompt_for(t,condition,'secret_candidate',[{'secret_feedback':True}])
    assert p['task']==t.public()
    assert 'reference' not in p['task'] and 'tests' not in p['task'] and 'mutants' not in p['task']
    assert ('skeleton' in p)==(condition in {'G10','G11'})
    assert ('current_source' in p)==(condition in {'G01','G11'})
    if condition in {'G00','G10'}:
        assert p==prompt_for(t,condition)
        assert 'secret' not in json.dumps(p)


@pytest.mark.parametrize('condition',CONDITIONS)
def test_replay_negative_paths_and_final_acceptance(tmp_path,condition):
    t=task()
    oracle=FakeOracle(['verification_failed','passed','passed'])
    result=run(t,Replay(t,condition),oracle,tmp_path/condition,condition=condition)
    assert result['success'] and result['boundary_rejections']==1
    assert result['usage']['oracle_calls']==3 and result['usage']['model_calls']==3
    assert result['usage']['runtime_calls']==2
    assert not result['research_eligible'] and not result['first_candidate_passed']
    p1=json.loads((tmp_path/condition/'prompt_001.json').read_text())
    p3=json.loads((tmp_path/condition/'prompt_003.json').read_text())
    if condition in {'G00','G10'}:
        assert p1==p3
    else:
        assert p1!=p3 and 'verification_failed' in json.dumps(p3)


def test_final_reverification_can_reject_success(tmp_path):
    t=task()
    result=run(t,Responses([correct(t)]),FakeOracle(['passed','timeout']),tmp_path/'run')
    assert not result['success'] and result['stop_reason']=='final_reverification_failed'


@pytest.mark.parametrize('limits,reason',[(Limits(total_tokens=1),'token_budget_exhausted'),
                                        (Limits(verifier_calls=1),'reserved_final_oracle_budget')])
def test_budget_before_call(tmp_path,limits,reason):
    result=run(task(),Responses([]),FakeOracle(),tmp_path/'run',limits=limits)
    assert result['usage']['model_calls']==0 and result['stop_reason']==reason


def test_failed_model_and_malformed_json_recover(tmp_path):
    t=task()
    result=run(t,Responses([ConnectionError('no secret'),'{bad',correct(t)]),FakeOracle(),tmp_path/'run')
    assert result['success'] and result['usage']['model_calls']==3
    assert result['usage']['unknown_usage_calls']==3 and result['usage']['cost_usd'] is None


def test_template_never_reads_reference_or_witnesses():
    for t in load_tasks(ROOT/'generation'/'tasks'):
        t.meta['reference']=t.meta['mutants']=t.meta['tests']=None
        model=Template(t)
        response=model.generate('',1,1)
        action=json.loads(response['text'])
        t.extract(action['source'])
        assert model.identity()['uses_reference'] is False
    assert len(RULES)==12


def test_unsupported_template_is_not_hidden(tmp_path):
    t=task()
    t.meta['rule']={'name':'unsupported','version':99}
    result=run(t,Template(t),FakeOracle(),tmp_path/'run',condition='T')
    assert not result['success'] and not result['supported']
    assert result['usage']['model_calls']==0 and result['usage']['oracle_calls']==0


def test_replay_summary_is_separate_and_tamper_is_rejected(tmp_path):
    t=task()
    run(t,Responses([correct(t)]),FakeOracle(),tmp_path/'one')
    s=summarize(tmp_path)
    assert s['live_research']==[] and s['scripted_diagnostics']
    (tmp_path/'one'/'final.dfy').write_text('tampered')
    with pytest.raises(ValueError,match='hash mismatch'):
        summarize(tmp_path)


def test_cross_source_split_guard_and_renamed_clones(tmp_path):
    meta=copy.deepcopy(task().meta)
    for i in range(2):
        p=tmp_path/str(i)
        p.mkdir()
        meta.update(id=f'task{i}',split='dev' if i==0 else 'test')
        (p/'task.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='crosses splits'):
        load_tasks(tmp_path)
    meta['source_project']='renamed_source'
    (tmp_path/'1'/'task.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='template crosses'):
        load_tasks(tmp_path)


def test_authorization_before_output_or_provider(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(['suite','--model','live','--output',str(tmp_path/'no')])
    assert exc.value.code==2 and not (tmp_path/'no').exists()


def test_failed_admission_blocks_provider(tmp_path,monkeypatch):
    import generation.cli as cli
    monkeypatch.setattr(cli,'validate',lambda *args:{'all_admitted':False})
    monkeypatch.setattr(cli,'Provider',lambda **kwargs:pytest.fail('must not call provider'))
    assert cli.main(['suite','--model','live','--allow-paid','--output',str(tmp_path/'failed')])==1


def test_provider_uses_generation_prompt_and_missing_usage_is_unknown():
    captured={}
    class Transport:
        def with_options(self,**kw):
            captured.update(kw)
            return self
        @property
        def chat(self): return self
        @property
        def completions(self): return self
        def create(self,**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(usage=None,model='unit-test',choices=[SimpleNamespace(
                message=SimpleNamespace(content='{}'),finish_reason='stop')])
    p=Provider.__new__(Provider)
    p.client=SimpleNamespace(model='unit-test',provider='openai',client=Transport())
    p.input_price=p.output_price=1
    result=p.generate('task',30,5)
    assert result['input_tokens'] is None and result['cost_usd'] is None
    assert captured['max_retries']==0 and captured['timeout']==5
    assert 'Generate implementations' in captured['messages'][0]['content']


def test_missing_formal_batch_never_accepts(monkeypatch):
    t=task()
    verifier=SimpleNamespace(verify=lambda *args,**kwargs:Result('passed',obligations={'Wrong (correctness)':'passed'}))
    oracle=Oracle(verifier)
    monkeypatch.setattr(oracle,'runtime',lambda *args:pytest.fail('must not execute after incomplete proof'))
    evidence=oracle.check(t,t.assemble(t.meta['reference']))
    assert evidence.status=='unknown' and evidence.runtime_calls==0


def test_boundary_rejected_before_verifier():
    oracle=Oracle(SimpleNamespace(verify=lambda *args,**kwargs:pytest.fail('illegal candidate reached verifier')))
    evidence=oracle.check(task(),'method Fake() {}')
    assert evidence.status=='boundary_rejected' and evidence.verifier_calls==0


def test_real_dafny_generation_oracle_and_template(tmp_path):
    verifier=Dafny()
    if not verifier.version().startswith('4.11.'):
        pytest.skip('Dafny 4.11 required for real integration')
    t=task('reserve_twice')
    oracle=Oracle(verifier)
    wrong=oracle.check(t,t.assemble(t.meta['mutants'][0]['bodies']),test_failed=True)
    assert wrong.formal=='verification_failed' and wrong.behavioral=='behavior_failed'
    result=run(t,Template(t),oracle,tmp_path/'real',condition='T')
    assert result['success'] and result['usage']['verifier_calls']==2 and result['usage']['runtime_calls']==2


def test_empty_implementation_is_not_a_repair_admission_requirement():
    t=task('snapshot')
    source=t.assemble({name:'' for name in t.names})
    assert t.extract(source)  # Model starts absent, not an injected bad algorithm.
    assert '<generate body:' in t.skeleton()


def test_runtime_timeout_kills_process_group_and_strips_api_keys(monkeypatch):
    import generation.oracle as module
    import subprocess
    captured={}
    class Process:
        pid=1234567
        def __init__(self,*args,**kwargs):
            captured.update(kwargs)
            self.count=0
        def communicate(self,timeout=None):
            self.count+=1
            if self.count==1:
                raise subprocess.TimeoutExpired('fake',1)
            return '', ''
        def kill(self): captured['killed']=True
    monkeypatch.setenv('OPENAI_API_KEY','unit-test-secret')
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    monkeypatch.setattr(module.os,'killpg',lambda pid,sig:captured.update(killed=True,pid=pid))
    t=task()
    evidence=Oracle(SimpleNamespace(path='fake')).runtime(t.assemble(t.meta['reference']),t,1)
    assert evidence['status']=='timeout' and captured['killed']
    assert 'OPENAI_API_KEY' not in captured['env']


def test_real_audit_rejects_result_identity_and_missing_jobs(tmp_path):
    t=task()
    root=tmp_path/'suite'
    run(t,Responses([correct(t)]),FakeOracle(),root/'000_G11_0')
    job={'directory':'000_G11_0','task_id':t.meta['id'],'condition':'G11','replicate':0}
    (root/'jobs.json').write_text(json.dumps([job]))
    assert audit(root,[t])['accepted']==1
    job['replicate']=1
    (root/'jobs.json').write_text(json.dumps([job]))
    with pytest.raises(ValueError,match='identity mismatch'):
        audit(root,[t])
    job['directory']='not_run'
    (root/'jobs.json').write_text(json.dumps([job,dict(job,directory='000_G11_0')]))
    assert summarize(root)['missing_planned_runs']
    with pytest.raises(ValueError,match='incomplete'):
        audit(root,[t])


def test_formal_pass_with_behavior_failure_is_not_joint_success(monkeypatch):
    t=task()
    verifier=SimpleNamespace(verify=lambda *args,**kwargs:Result('passed',
        obligations={'Remaining (correctness)':'passed'}))
    oracle=Oracle(verifier)
    monkeypatch.setattr(oracle,'runtime',lambda *args:dict(status='behavior_failed',executed=True))
    evidence=oracle.check(t,t.assemble(t.meta['reference']))
    assert evidence.formal=='passed' and evidence.status=='behavior_failed' and evidence.runtime_calls==1


def test_trace_audit_checks_actual_no_feedback_prompts(tmp_path):
    from scripts.check_generation_factorial import inspect
    t=task()
    jobs=[]
    for condition in ('G00','G10'):
        directory='000_'+condition+'_0'
        run(t,Responses([correct(t,condition)]),FakeOracle(),tmp_path/directory,condition=condition)
        jobs.append(dict(task_id=t.meta['id'],condition=condition,replicate=0,directory=directory))
    (tmp_path/'jobs.json').write_text(json.dumps(jobs))
    assert inspect(tmp_path,ROOT/'generation'/'tasks')['fresh_no_feedback_prompts']==2
    path=tmp_path/'000_G00_0'/'prompt_001.json'
    prompt=json.loads(path.read_text())
    prompt['leaked_diagnostic']='verification failed'
    path.write_text(json.dumps(prompt))
    with pytest.raises(ValueError,match='independent prompt'):
        inspect(tmp_path,ROOT/'generation'/'tasks')


def test_live_paired_estimates_exclude_missing_pairs(tmp_path):
    class FakeLive(Responses):
        kind='live_model'
    t=task()
    for condition in ('G01','G11'):
        run(t,FakeLive([correct(t,condition)]),FakeOracle(),tmp_path/condition,condition=condition)
    result=summarize(tmp_path)
    assert result['scripted_diagnostics']==[] and len(result['live_research'])==2
    pair=result['paired_live'][0]
    assert (pair['left'],pair['right'],pair['matched'])==('G11','G01',1)
    assert pair['task_run_difference']==0 and pair['source_macro_ci95'] is None
    assert result['interaction_live'] is None
