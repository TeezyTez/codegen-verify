import copy
import json
from pathlib import Path

import pytest

from generation.representation.task import Task
from generation.representation.verifier import Verification
from repair.task import digest

ROOT = Path(__file__).resolve().parents[1]


def test_driver_rejects_missing_frozen_tasks(tmp_path, monkeypatch):
    from generation.obligations import common_failure
    class Verifier:
        def identity(self): return {'version':'4.11.0'}
    monkeypatch.setattr(common_failure,'Dafny',lambda **kwargs:Verifier())
    monkeypatch.setattr(common_failure,'load_tasks',lambda _:[])
    with pytest.raises(ValueError,match='frozen task'):
        common_failure.execute(tmp_path/'batch',prepare_only=True)


def fixture():
    t=Task.load(ROOT/'generation/representation/tasks/absolute/task.json')
    evidence=Verification('verification_failed', executed=True, real_verifier=True,
                          stdout='public failure', obligations={'Absolute (correctness)':'failed'})
    point={'bodies':t.meta['mutants'][0]['bodies'],'evidence':evidence,
           'source_sha256':digest(t.assemble(t.meta['mutants'][0]['bodies'])),
           'task_sha256':t.file_hash,'toolchain':{'fixture':True}}
    return t, point


def test_repair_prompts_share_seed_feedback_and_instruction():
    from generation.obligations.common_failure import RepairPolicy
    t,p=fixture()
    packets={}
    for strategy in ('baseline','state','guided','independent_sampling'):
        policy=RepairPolicy(t,p['toolchain'])
        policy.observe(t.assemble(p['bodies']),p['evidence'],'initial')
        packets[strategy]=json.loads(policy.messages(t,'contract',strategy,p['bodies'])[1]['content'])
    for field in ('task','current_bodies','history','repair_instruction'):
        assert all(packets[s][field]==packets['baseline'][field] for s in packets)
    assert 'evidence_state' not in packets['baseline']
    assert packets['state']['evidence_state']==packets['guided']['evidence_state']
    assert packets['state']['target'] is None and packets['guided']['target']
    assert packets['baseline']['history'][0]['verifier_output']['stdout']=='public failure'


def test_independent_repairs_restart_from_same_failure():
    from generation.obligations.common_failure import RepairPolicy
    t,p=fixture(); policy=RepairPolicy(t,p['toolchain'])
    policy.observe(t.assemble(p['bodies']),p['evidence'],'initial')
    first=policy.messages(t,'contract','independent_sampling',p['bodies'])
    policy.observe(t.assemble(t.meta['reference']),Verification('timeout'), 'round_001')
    assert first==policy.messages(t,'contract','independent_sampling',t.meta['reference'])


def test_seed_does_not_replace_generated_final_verification(tmp_path):
    from generation.engine import run
    from generation.obligations.common_failure import RepairPolicy, configuration
    t,p=fixture(); c=configuration()
    class Model:
        kind='live'
        def identity(self): return {'kind':'live','name':'test'}
        def generate(self,*args):
            return {'text':json.dumps({'bodies':t.meta['reference']}),'error':None}
    class Verifier:
        def identity(self): return p['toolchain']
        def verify(self,*args,**kwargs): return Verification('verified',real_verifier=False)
    row=run(t,Model(),Verifier(),tmp_path/'run',config=c,strategy='baseline',representation='contract',
            policy=RepairPolicy(t,p['toolchain']),starting_point=p)
    assert not row['success'] and row['usage']['verifier_calls']==2
    assert row['usage']['model_calls']==1
    assert (tmp_path/'run/initial.verification.json').exists()
    state=json.loads((tmp_path/'run/state.json').read_text())
    assert state['observations'][0]['label']=='initial'
    bad=copy.deepcopy(p); bad['source_sha256']='wrong'
    with pytest.raises(ValueError,match='starting point'):
        run(t,Model(),Verifier(),tmp_path/'bad',config=c,strategy='baseline',representation='contract',
            policy=RepairPolicy(t,p['toolchain']),starting_point=bad)
