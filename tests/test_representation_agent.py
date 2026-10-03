"""Offline transport tests plus actual Dafny integration; no paid calls."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from generation.representation import REPRESENTATIONS, STRATEGIES
from generation.representation.analyze import summarize, write_summary
from generation.representation.cli import main, admit
from generation.representation.config import Budget, default_config, load_config, validate_config
from generation.representation.guard import validate_body
from generation.representation.models import Mock, OpenAIModel, SYSTEM
from generation.representation.runner import messages_for, run
from generation.representation.task import Task, asset_hashes, canonical, load_tasks
from generation.representation.verifier import Dafny, Verification, feedback
from repair.task import BoundaryError, digest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'generation/representation/tasks'


def task(name='absolute'):
    return Task.load(DATA/name/'task.json')


def config():
    value = default_config()
    value['strategies'] = list(STRATEGIES)
    return value


class FakeVerifier:
    """Interface double cannot produce an accepted real-verifier result."""
    def __init__(self, statuses=('verification_failed',)):
        self.statuses, self.calls = list(statuses), 0

    def identity(self):
        return {'real_verifier':False,'kind':'test_double'}

    def verify(self, source, **kwargs):
        result = Verification(self.statuses[min(self.calls,len(self.statuses)-1)])
        self.calls += 1
        return result


class Responses:
    kind = 'mock'

    def __init__(self, values):
        self.values = iter(values)

    def identity(self):
        return {'kind':'mock','fixture':True}

    def generate(self, *args):
        value = next(self.values)
        if isinstance(value,BaseException):
            raise value
        if isinstance(value,dict) and 'text' in value:
            return value
        return {'text':value if isinstance(value,str) else json.dumps(value),
                'input_tokens':None,'output_tokens':None,'cost_usd':0}


def execute(tmp_path, *, t=None, model=None, verifier=None, strategy='iterative_repair', c=None, representation='natural'):
    t = t or task()
    return run(t,model or Mock(t),verifier or FakeVerifier(),tmp_path/'run',
               config=c or config(),strategy=strategy,representation=representation)


def actual():
    verifier = Dafny(timeout=15)
    if not (shutil.which(verifier.path) or Path(verifier.path).is_file()):
        pytest.skip('actual Dafny not installed: real verification NOT executed')
    return verifier


def test_data_and_config():
    tasks = load_tasks(DATA)
    assert len(tasks) == 5
    assert any('while' in canonical(t.meta['reference']) for t in tasks)
    assert all(t.meta['origin'] == 'synthetic_demo' and t.meta['license'] == 'CC0-1.0' for t in tasks)
    assert all(t.meta['equivalence_audit']['status'] == 'pending' for t in tasks)
    validate_config(load_config(ROOT/'generation/representation/configs/demo.json'))


@pytest.mark.parametrize('field,value', [('model_calls',0),('verifier_calls',True),('output_tokens',1.2),
                                        ('task_seconds',float('nan')),('cost_usd',-1),('total_tokens',0)])
def test_budget_rejects_bad_values(field,value):
    with pytest.raises(ValueError):
        Budget(**{field:value})


@pytest.mark.parametrize('change',[
    lambda c:c['model'].update(api_key='do-not-store'),
    lambda c:c.update(replicates=0),
    lambda c:c.update(representations=['natural','natural']),
    lambda c:c['model'].update(kind='openai',name='x',base_url='https://key:secret@example.com'),
    lambda c:c['model'].update(sampling={'unsupported':1}),
])
def test_invalid_configuration(change):
    c=config(); change(c)
    with pytest.raises(ValueError):
        validate_config(c)


@pytest.mark.parametrize('representation',REPRESENTATIONS)
@pytest.mark.parametrize('strategy',STRATEGIES)
def test_public_allowlist_and_fresh_no_feedback(representation,strategy):
    t=task()
    base=messages_for(t,representation,strategy)
    content=json.loads(base[1]['content'])
    assert set(content['task']) == {'task_id','signatures','shared_definitions','requirements'}
    assert content['task']['requirements'] == t.meta['representations'][representation]
    assert 'ensures' not in base[1]['content'] and 'reference' not in base[1]['content']
    changed=messages_for(t,representation,strategy,{'secret_body':'x'},{'secret_diagnostic':True})
    assert (base == changed) == (strategy != 'iterative_repair')
    t.meta['reference']={'secret':'NEVER_IN_PROMPT'}
    assert 'NEVER_IN_PROMPT' not in canonical(messages_for(t,representation,strategy))


@pytest.mark.parametrize('body',[
    'assume false;', 'assert {:axiom} false;', 'r := *;', 'var x :| false;',
    '} method Other() {} {', 'r := 1; // hidden', 'import X', 'r := "x";',
    'while true decreases * {}', 'while false invariant true;',
    'while true invariant false', 'forall i ensures false;',
    'var i;', 'assert true by {}', 'ghost var x := 1;', '#line 0',
    'expect false;', 'print 1;', 'r := new int[4];', 'return; }',
    'if true r := 1;', 'r := 1; /*x*/', 'r := ((1];',
])
def test_rejects_escape_and_structural_injection(body):
    with pytest.raises(BoundaryError):
        validate_body(body)


def test_frozen_assets_and_mapping_validation(tmp_path):
    t=task()
    path=tmp_path/'task.json'
    m=copy.deepcopy(t.meta)
    path.write_text(json.dumps(m))
    loaded=Task.load(path)
    loaded.meta['methods'][0]['header']='ensures true'
    with pytest.raises(BoundaryError,match='frozen'):
        loaded.check_frozen()
    m['representations']['natural'] += 'Extra hidden change'
    path.write_text(json.dumps(m))
    with pytest.raises(ValueError,match='hash'):
        Task.load(path)
    m['asset_hashes']=asset_hashes(m)
    m['requirements'][0]['acceptance']['header_line']=1
    m['asset_hashes']=asset_hashes(m)
    path.write_text(json.dumps(m))
    with pytest.raises(ValueError,match='acceptance'):
        Task.load(path)


def test_feedback_redaction_and_unknown_attribution():
    t=task(); source=t.assemble(t.meta['mutants'][0]['bodies'])
    locations,mapping=t.layout(source)
    evidence=Verification('verification_failed',stdout='PRIVATE SPEC',diagnostics=[
        {'subtype':'postcondition','message':'PRIVATE SPEC','related_spec':'SECRET',
         'location_line':next(iter(locations)),'related_location_line':2},
        {'subtype':'new_diagnostic','message':'RAW','location_line':999,'related_location_line':999}])
    result=feedback(t,source,evidence)
    assert result['diagnostics'][0]['requirement_ids']==['R1']
    assert result['diagnostics'][0]['candidate_location']['line']==1
    assert result['diagnostics'][1]['requirement_ids']=='unknown'
    assert result['property_satisfaction']=='unknown'
    assert all(x not in canonical(result) for x in ('PRIVATE','SECRET','RAW','999'))


def test_model_errors_invalid_json_and_retry_count(tmp_path):
    t=task()
    model=Responses([TimeoutError('DO_NOT_LOG_KEY'),'{bad',{'bodies':t.meta['reference']}])
    result=execute(tmp_path,t=t,model=model)
    assert not result['success'] and result['usage']['model_calls']==3
    assert result['usage']['model_retry_calls']==1
    assert result['failures']['invalid_candidate']==1
    assert 'DO_NOT_LOG_KEY' not in ''.join(p.read_text() for p in (tmp_path/'run').glob('*.json*'))


@pytest.mark.parametrize('strategy',STRATEGIES)
def test_no_fake_verifier_success(tmp_path,strategy):
    t=task()
    result=execute(tmp_path,t=t,model=Responses([{'bodies':t.meta['reference']}]),
                   verifier=FakeVerifier(['verified']),strategy=strategy)
    assert not result['success'] and not result['real_verifier_executed']


@pytest.mark.parametrize('setting,reason',[
    ({'total_tokens':1},'token_budget_exhausted'),
    ({'verifier_calls':1},'verification_budget_exhausted'),
])
def test_pre_call_budgets(tmp_path,setting,reason):
    c=config(); c['budget'].update(setting)
    result=execute(tmp_path,c=c)
    assert result['stop_reason']==reason and result['usage']['model_calls']==0


def test_cost_budget_and_unknown_prices_fail_closed(tmp_path):
    c=live_config(); c['budget']['cost_usd']=0.00001
    with pytest.raises(ValueError,match='known prices'):
        validate_config(c)
    c['model'].update(input_usd_per_million=1,output_usd_per_million=1,price_source='test-only synthetic prices')
    class Live(Responses):
        kind='live'
    result=execute(tmp_path,c=c,model=Live([]))
    assert result['stop_reason']=='cost_budget_exhausted' and result['usage']['model_calls']==0


def test_over_budget_after_model_is_not_accepted(tmp_path):
    c=config(); c['budget']['total_tokens']=10000
    t=task(); model=Responses([{'text':json.dumps({'bodies':t.meta['reference']}),
                              'input_tokens':20000,'output_tokens':5,'cost_usd':None}])
    result=execute(tmp_path,c=c,model=model)
    assert not result['success'] and result['stop_reason']=='budget_exhausted_after_call'
    assert result['usage']['verifier_calls']==0


def test_wall_budget_after_call(tmp_path,monkeypatch):
    import generation.representation.runner as runner
    clock=[0.0]
    monkeypatch.setattr(runner.time,'monotonic',lambda:clock[0])
    class Slow(Mock):
        def generate(self,*args):
            clock[0]=200
            return super().generate(*args)
    result=execute(tmp_path,model=Slow(task()))
    assert result['stop_reason']=='task_timeout' and not result['success']
    assert result['usage']['verifier_calls']==0


def test_final_reverification_failure_and_asset_mutation(tmp_path):
    t=task()
    result=execute(tmp_path/'final',t=t,model=Responses([{'bodies':t.meta['reference']}]),
                   verifier=FakeVerifier(['verified','timeout']))
    assert not result['success'] and result['status']=='timeout' and result['usage']['verifier_calls']==2
    class Mutating(FakeVerifier):
        def verify(self,*args,**kwargs):
            t.meta['shared_definitions']='tampered'
            return Verification('verified')
    result=execute(tmp_path/'mutation',t=t,verifier=Mutating())
    assert not result['success'] and result['stop_reason']=='frozen_assets_changed'


def test_condition_state_isolation_and_missing_jobs(tmp_path):
    t=task()
    for view in ('natural','structured'):
        run(t,Mock(t),FakeVerifier(),tmp_path/view,config=config(),strategy='iterative_repair',representation=view)
    for view in ('natural','structured'):
        first=json.loads((tmp_path/view/'round_001.response.json').read_text())
        assert json.loads(first['text'])['bodies']==t.meta['mutants'][0]['bodies']
    jobs=[{'directory':view,'task_id':'absolute','strategy':'iterative_repair',
           'representation':view,'replicate':0} for view in ('natural','structured','checklist')]
    (tmp_path/'jobs.json').write_text(json.dumps(jobs))
    report=summarize(tmp_path)
    assert len(report['missing_runs'])==1 and not report['complete_matrix']
    jobs[0]['task_id']='tampered'; (tmp_path/'jobs.json').write_text(json.dumps(jobs))
    with pytest.raises(ValueError,match='mismatched'):
        summarize(tmp_path)


def test_real_parse_error_and_missing_batches(monkeypatch):
    result=actual().verify('method Broken() { var x := ; }',names=['Broken'])
    assert result.status=='parse_error' and result.real_verifier
    class Process:
        returncode=0
        def __init__(self,*args,**kwargs): pass
        def communicate(self,**kwargs): return 'Dafny program verifier finished with 1 verified, 0 errors',''
    monkeypatch.setattr(subprocess,'Popen',Process)
    result=Dafny().verify('method X() {}',names=['X'])
    assert result.status=='unknown'


def test_failed_verification_and_call_budget(tmp_path):
    c=config(); c['budget']['model_calls']=2
    result=execute(tmp_path,c=c)
    assert result['stop_reason']=='model_budget_exhausted'
    assert result['usage']['model_calls']==result['usage']['verifier_calls']==2


def test_single_shot_one_check_independent_no_history(tmp_path):
    t=task()
    single=execute(tmp_path/'single',t=t,strategy='single_shot')
    independent=execute(tmp_path/'independent',t=t,strategy='independent_sampling')
    assert single['usage']['model_calls']==single['usage']['verifier_calls']==1
    assert independent['usage']['model_calls']==3
    prompts=[json.loads(p.read_text())['messages'] for p in sorted((tmp_path/'independent/run').glob('*.messages.json'))]
    assert all(p==prompts[0] for p in prompts)


def test_interrupt_preserves_charged_call_and_incomplete_result(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        execute(tmp_path,model=Responses([KeyboardInterrupt()]))
    row=json.loads((tmp_path/'run/result.json').read_text())
    assert not row['completed'] and row['stop_reason']=='interrupted' and row['usage']['model_calls']==1
    summary=write_summary(tmp_path)
    assert summary['incomplete_runs']==1 and not summary['complete_matrix']


def test_interrupted_live_request_is_unknown_not_free(tmp_path):
    class Live(Responses):
        kind='live'
        def identity(self): return {'kind':'live','fixture':True}
    with pytest.raises(KeyboardInterrupt):
        execute(tmp_path,model=Live([KeyboardInterrupt()]),c=live_config())
    row=json.loads((tmp_path/'run/result.json').read_text())
    assert row['usage']['cost_usd'] is None and row['usage']['unknown_usage_calls']==1
    assert row['usage']['model_calls']==1 and row['usage']['accounted_tokens']>0


def test_missing_dafny_and_actual_timeout():
    v=Dafny('/definitely/not/installed/dafny',timeout=1)
    r=v.verify('method X() {}',names=['X'])
    assert r.status=='tool_error' and not r.real_verifier and not r.executed
    r=actual().verify(task().assemble(task().meta['reference']),names=task().names,timeout=0.0001)
    assert r.status=='timeout' and r.executed and r.real_verifier


def test_timeout_kills_group_and_strips_env(monkeypatch):
    seen={}
    class Process:
        pid=123; returncode=-9
        def __init__(self, *args, **kwargs):
            seen.update(kwargs); self.n=0
        def communicate(self,timeout=None):
            self.n+=1
            if self.n==1: raise subprocess.TimeoutExpired('fake',timeout)
            return 'partial output','partial error'
    monkeypatch.setenv('REPRESENTATION_SECRET','NEVER_PASS')
    monkeypatch.setattr(subprocess,'Popen',Process)
    monkeypatch.setattr(os,'killpg',lambda pid,sig:seen.update(killed=pid))
    r=Dafny().verify('method X() {}',names=['X'])
    assert r.status=='timeout' and r.stdout=='partial output' and r.stderr=='partial error'
    assert 'REPRESENTATION_SECRET' not in seen['env']
    if os.name=='posix': assert seen['killed']==123


class SDK:
    def __init__(self, response=None, error=None):
        self.response,self.error=response,error
        self.chat=SimpleNamespace(completions=self)
    def with_options(self,**kwargs):
        self.options=kwargs
        return self
    def create(self,**kwargs):
        self.request=kwargs
        if self.error: raise self.error
        return self.response


def live_config():
    c=config()
    c['model'].update(kind='openai',name='configured-model',base_url='https://api.openai.com/v1')
    return c


def test_sdk_exact_messages_limits_and_no_hidden_retries():
    c=live_config(); c['model']['send_seed']=True
    sdk=SDK(SimpleNamespace(usage=SimpleNamespace(prompt_tokens=20,completion_tokens=8),
                          choices=[SimpleNamespace(message=SimpleNamespace(content='{}'),finish_reason='stop')],
                          model='returned-model'))
    adapter=OpenAIModel(c['model'],authorized=True,client=sdk)
    messages=messages_for(task(),'natural','single_shot')
    result=adapter.generate(messages,100,7,17)
    assert sdk.request['messages']==messages and sdk.request['max_completion_tokens']==100
    assert sdk.options=={'timeout':7,'max_retries':0} and sdk.request['seed']==17
    assert 'temperature' not in sdk.request and sdk.request['store'] is False
    assert result['cost_usd'] is None and result['input_tokens']==20


@pytest.mark.parametrize('mode',['empty','rate_limit','timeout'])
def test_sdk_empty_timeout_and_rate_limit(mode):
    import httpx2
    import openai
    request=httpx2.Request('POST','https://api.openai.com/v1/chat/completions')
    error=(openai.RateLimitError('SECRET',response=httpx2.Response(429,request=request),body=None) if mode=='rate_limit'
           else openai.APITimeoutError(request=request) if mode=='timeout' else None)
    sdk=SDK(SimpleNamespace(usage=None,choices=[]),error)
    adapter=OpenAIModel(live_config()['model'],authorized=True,client=sdk)
    result=adapter.generate([],100,2,1)
    assert result['error']==('empty_output' if mode=='empty' else mode)
    assert 'SECRET' not in canonical(result)


def test_explicit_live_authorization_before_output(tmp_path):
    path=tmp_path/'live.json'; path.write_text(json.dumps(live_config()))
    with pytest.raises(SystemExit):
        main(['run','--task-id','absolute','--config',str(path),'--output',str(tmp_path/'out')])
    assert not (tmp_path/'out').exists()
    with pytest.raises(ValueError,match='allow-paid'):
        OpenAIModel(live_config()['model'],client=SDK())


def test_summary_separates_mock_live_and_audit_and_keeps_task_repeats(tmp_path):
    c=config(); c['replicates']=2
    t=task()
    for rep in range(2):
        run(t,Mock(t),FakeVerifier(),tmp_path/f'mock{rep}',config=c,strategy='single_shot',representation='natural',replicate=rep)
    lc=live_config()
    class LiveFailure(Responses):
        kind='live'
        def identity(self): return {'kind':'live','fixture':True}
    run(t,LiveFailure([{'text':'','error':'timeout'}]),FakeVerifier(),tmp_path/'live',config=lc,
        strategy='single_shot',representation='natural')
    result=write_summary(tmp_path)
    assert len(result['conditions'])==2
    mock=next(s for s in result['conditions'] if s['is_mock'])
    assert mock['unique_tasks']==1 and mock['recorded_runs']==2 and mock['replicate_ids']==[0,1]
    assert mock['audit_status']=='pending' and mock['input_tokens'] is None
    assert (tmp_path/'summary.csv').exists() and (tmp_path/'summary.md').exists()


def test_actual_admission_all_five(tmp_path):
    report=admit(load_tasks(DATA),actual(),tmp_path/'admission')
    assert report['all_admitted']
    assert all(t['cases'][0]['status']=='verified' and t['cases'][1]['status']=='verification_failed' for t in report['tasks'])


@pytest.mark.parametrize('representation',REPRESENTATIONS)
def test_actual_mock_repair_and_final_artifact(tmp_path,representation):
    t=task('sequence_max')
    result=execute(tmp_path,t=t,verifier=actual(),representation=representation)
    assert result['success'] and result['is_mock'] and result['real_verifier_executed']
    assert result['usage']['model_calls']==2 and result['usage']['verifier_calls']==3
    assert not result['first_candidate_verified']
    assert result['failures']=={'verification_failed':1}
    packet=json.loads((tmp_path/'run/round_002.messages.json').read_text())
    content=json.loads(packet['messages'][1]['content'])
    assert content['diagnostic']['status']=='verification_failed'
    assert 'ensures' not in packet['messages'][1]['content']
    summary=summarize(tmp_path)
    assert summary['conditions'][0]['successes']==1
    from scripts.check_representation_artifacts import audit
    audited=audit(tmp_path)
    assert audited['runs_checked']==1 and audited['verification_events_checked']==3
    (tmp_path/'run/final.dfy').write_text('tampered')
    with pytest.raises(ValueError,match='hash'):
        summarize(tmp_path)
