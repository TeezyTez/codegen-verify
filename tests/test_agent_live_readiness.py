"""Real SDK serialization through an in-memory HTTP transport, never a network call."""
import copy
import json
import os
from pathlib import Path
import shutil

import httpx2
from openai import OpenAI
import pytest

from generation.representation.cli import main
from generation.representation.config import default_config
from generation.representation.config import validate_config
from generation.representation.models import OpenAIModel
from generation.representation.preflight import inspect_run
from generation.representation.runner import run, messages_for
from generation.representation.task import Task, canonical
from generation.representation.verifier import Dafny

ROOT = Path(__file__).resolve().parents[1]


def task():
    return Task.load(ROOT/'generation/representation/tasks/absolute/task.json')


def live_config():
    config = default_config()
    config['model'].update(kind='openai',name='configured-model',base_url='https://api.openai.com/v1',
                           api_key_env='AGENT_TEST_API_KEY')
    return config


class Environment:
    def identity(self):
        return {'version':'4.11.0','kind':'test_double'}


def test_preflight_never_constructs_model_or_discloses_key(monkeypatch):
    monkeypatch.setenv('AGENT_TEST_API_KEY','SENSITIVE_DO_NOT_PRINT')
    monkeypatch.setattr(OpenAIModel,'__init__',lambda *a,**k:pytest.fail('must not create a client'))
    report = inspect_run(task(),live_config(),Environment(),strategy='iterative_repair',representation='natural')
    assert report['ready_for_authorized_attempt'] and not report['api_called']
    assert report['credential_present'] is True and 'SENSITIVE_DO_NOT_PRINT' not in canonical(report)
    assert report['initial_messages'] == messages_for(task(),'natural','iterative_repair')
    assert report['budget']['model_calls_max'] == 3
    assert 'ensures' not in canonical(report['initial_messages'])


def test_missing_settings_and_impossible_budget(monkeypatch):
    monkeypatch.delenv('AGENT_TEST_API_KEY',raising=False)
    config = live_config(); config['model']['name']='SET_YOUR_MODEL'
    config['budget']['total_tokens']=1
    report=inspect_run(task(),config,Environment(),strategy='iterative_repair',representation='natural')
    assert not report['ready_for_authorized_attempt'] and len(report['blockers'])==3


def test_preflight_cli_does_not_require_paid_authorization(tmp_path,monkeypatch):
    monkeypatch.delenv('AGENT_TEST_API_KEY',raising=False)
    path=tmp_path/'config.json'; path.write_text(json.dumps(live_config()))
    output=tmp_path/'check.json'
    assert main(['preflight','--config',str(path),'--task-id','absolute','--output',str(output)])==2
    report=json.loads(output.read_text())
    assert not report['api_called'] and not report['credential_present']


def test_authorized_command_still_rejects_missing_setup_before_output(tmp_path,monkeypatch):
    monkeypatch.delenv('AGENT_TEST_API_KEY',raising=False)
    path=tmp_path/'config.json'; path.write_text(json.dumps(live_config()))
    with pytest.raises(SystemExit):
        main(['run','--config',str(path),'--task-id','absolute','--allow-paid','--output',str(tmp_path/'run')])
    assert not (tmp_path/'run').exists()


def response(text, *, finish='stop'):
    return {'id':'offline-fixture','object':'chat.completion','created':0,'model':'configured-model',
            'choices':[{'index':0,'message':{'role':'assistant','content':text},'finish_reason':finish}],
            'usage':{'prompt_tokens':100,'completion_tokens':30,'total_tokens':130}}


def client(handler):
    return OpenAI(api_key='offline-dummy-not-a-real-key',base_url='https://offline.invalid/v1',
                  max_retries=0,http_client=httpx2.Client(transport=httpx2.MockTransport(handler),trust_env=False))


def test_actual_sdk_transport_and_dafny_loop(tmp_path):
    t=task(); v=Dafny(timeout=15)
    if not (shutil.which(v.path) or Path(v.path).is_file()):
        pytest.skip('Dafny not installed; real verification not executed')
    requests=[]
    bodies=[t.meta['mutants'][0]['bodies'],t.meta['reference']]
    def handler(request):
        data=json.loads(request.content)
        assert request.url.host=='offline.invalid'
        requests.append(data)
        assert len(requests)<=2, 'hidden SDK retries or extra calls'
        return httpx2.Response(200,json=response(json.dumps({'bodies':bodies[len(requests)-1]})))
    sdk=client(handler)
    class OfflineTransport(OpenAIModel):
        kind='mock'
        def identity(self):
            return {**super().identity(),'kind':'mock','uses_reference':True,
                    'test_transport':'httpx2.MockTransport','api_called':False}
        def generate(self,*args,**kwargs):
            packet=super().generate(*args,**kwargs)
            packet.update(usage_source='synthetic_transport_fixture',cost_usd=0.0)
            return packet
    model=OfflineTransport(live_config()['model'],authorized=True,client=sdk)
    progress=[]
    try:
        row=run(t,model,v,tmp_path/'run',config=default_config(),strategy='iterative_repair',
                representation='natural',progress=progress.append)
    finally:
        sdk.close()
    assert row['success'] and row['is_mock'] and row['real_verifier_executed']
    assert row['usage']['model_calls']==2 and row['usage']['verifier_calls']==3
    second=json.loads(requests[1]['messages'][1]['content'])
    assert second['current_bodies']==bodies[0] and second['diagnostic']['status']=='verification_failed'
    assert 'ensures' not in canonical(requests[1]['messages'])
    assert [p['stage'] for p in progress].count('model_call_started')==2
    assert progress[-1]['stage']=='run_finished'
    assert 'offline-dummy-not-a-real-key' not in ''.join(p.read_text() for p in (tmp_path/'run').glob('*.json*'))


@pytest.mark.parametrize('status,category,retryable',[(429,'rate_limit',True),(503,'server_error',True),
                                                   (400,'invalid_request',False),(401,'authentication',False)])
def test_sdk_error_transport_no_hidden_retries(status,category,retryable):
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx2.Response(status,headers={'retry-after':'3'},json={'error':{
            'message':'SENSITIVE_SERVER_DETAIL','type':'test_error','code':'test','param':None}})
    with client(handler) as sdk:
        model=OpenAIModel(live_config()['model'],authorized=True,client=sdk)
        packet=model.generate(messages_for(task(),'natural','iterative_repair'),50,2,1)
    assert len(requests)==1 and packet['error']==category and packet['retryable'] is retryable
    assert packet['retry_after_seconds']==3 and 'SENSITIVE_SERVER_DETAIL' not in canonical(packet)


def test_sdk_truncated_output_is_not_accepted_as_complete_json():
    with client(lambda request:httpx2.Response(200,json=response('{"bodies":{}}',finish='length'))) as sdk:
        model=OpenAIModel(live_config()['model'],authorized=True,client=sdk)
        packet=model.generate([],50,2,1)
    assert packet['error']=='output_truncated' and packet['output_tokens']==30


def test_retry_delay_cannot_exceed_budget(tmp_path):
    class Limited:
        kind='live'
        def identity(self): return {'kind':'live','test_double':True}
        def generate(self,*args):
            return {'text':'','error':'rate_limit','retryable':True,'retry_after_seconds':1000,
                    'input_tokens':None,'output_tokens':None,'cost_usd':None}
    row=run(task(),Limited(),Environment(),tmp_path/'run',config=live_config(),
            strategy='iterative_repair',representation='natural')
    assert row['stop_reason']=='provider_retry_delay_exceeds_budget'
    assert row['usage']['model_calls']==1 and row['usage']['cost_usd'] is None


def test_fatal_provider_error_is_not_retried(tmp_path):
    class Fatal:
        kind='live'
        def identity(self): return {'kind':'live','test_double':True}
        def generate(self,*args):
            return {'text':'','error':'invalid_request','retryable':False}
    row=run(task(),Fatal(),Environment(),tmp_path/'run',config=live_config(),
            strategy='iterative_repair',representation='natural')
    assert row['stop_reason']=='invalid_request' and row['usage']['model_calls']==1


def test_deepseek_wire_parameters_and_provider_identity():
    config=live_config()
    config['model'].update(kind='deepseek',name='deepseek-flash',base_url='https://api.deepseek.com',
                           api_key_env='DEEPSEEK_API_KEY',thinking='disabled',output_token_parameter='max_tokens')
    validate_config(config)
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200,json=response('{"bodies":{}}'))
    with client(handler) as sdk:
        model=OpenAIModel(config['model'],authorized=True,client=sdk)
        result=model.generate([],100,2,1)
        assert model.identity()['provider']=='deepseek'
    assert requests[0]['thinking']=={'type':'disabled'} and requests[0]['max_tokens']==100
    assert 'store' not in requests[0] and 'seed' not in requests[0]
    assert result['error'] is None
    config['model']['send_seed']=True
    with pytest.raises(ValueError,match='seed'):
        validate_config(config)
