"""Synthetic archived trials and real Dafny compilation; no model or program runs."""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from generation.public_benchmark.task import PublicTask, canonical, digest


ROOT=Path(__file__).resolve().parents[1]
DAFNY=ROOT/'.tools/dafny/4.11.0/Dafny.exe'


def module():
    return importlib.import_module('generation.public_benchmark.compile_audit')


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2),encoding='utf-8')


@pytest.fixture(scope='module')
def verified_fixture(tmp_path_factory):
    from generation.public_benchmark import runner
    from generation.representation.verifier import Dafny
    from generation.public_benchmark.structure import inspect_source
    if not DAFNY.is_file(): pytest.skip('bundled Dafny integration toolchain unavailable')
    root=tmp_path_factory.mktemp('compile-audit-verified')/'trial'
    task=PublicTask({'id':'T1','source':'fixture','source-id':'1','vc-description':'Return x plus one.',
                    'vc-preamble':'','vc-helpers':'',
                    'vc-spec':'method Solve(x:int) returns(y:int) ensures y == x+1',
                    'vc-code':'','vc-postamble':''},family_id='fixture-family')
    class Model:
        def identity(self): return {'kind':'fixture','model':'synthetic-not-research'}
        def generate(self,messages,output_dir,**kwargs):
            output_dir.mkdir()
            return {'executed':True,'error':None,'input_tokens':1,'output_tokens':1,
                    'text':canonical({'implementation':'{ y := x+1; }',
                        'helpers':'method Main() { print "AUDIT_MUST_NOT_EXECUTE"; }'})}
    with patch.object(runner,'Dafny',lambda **kwargs:Dafny(path=str(DAFNY),**kwargs)):
        result=runner.run_trial(task,inspect_source(task.skeleton),['Solve'],Model(),root,'A',
                               budget={'max_model_actions':1})
    assert result['success'],result
    return root


@pytest.fixture
def archived(verified_fixture,tmp_path):
    trial=tmp_path/'trial'
    shutil.copytree(verified_fixture,trial)
    return trial


def rehash_result(root,row):
    write(root/'result.json',row)
    (root/'result.sha256').write_text(digest(canonical(row))+'\n',encoding='utf-8')


def test_real_dafny_translation_and_python_compile_never_execute_main(archived,tmp_path):
    result=module().audit_campaign(archived,tmp_path/'audit',dafny_path=DAFNY)
    assert result['primary_successes']==1
    assert result['counts']=={'translate_succeeded':1,'python_syntax_ok':1,'failed':0,'unknown':0}
    row=result['rows'][0]
    assert row['provenance_verified'] is True
    compiled=json.loads((tmp_path/'audit'/row['compile_result']).read_text(encoding='utf-8'))
    assert compiled['translation']['command'][1:3]==['translate','py']
    assert '--no-verify' in compiled['translation']['command']
    assert compiled['syntax']['command'][1:5]==['-I','-S','-m','py_compile']
    assert 'AUDIT_MUST_NOT_EXECUTE' not in compiled['translation']['stdout']+compiled['syntax']['stdout']
    assert compiled['generated_file_sha256'] and compiled['executed_generated_program'] is False
    assert result['primary_acceptance_changed'] is False


@pytest.mark.parametrize('corruption',['candidate_bytes','same_text_different_bytes','fake_success','filtered_verification','ast_source','omit_required_artifact','legacy_verifier'])
def test_invalid_success_provenance_never_reaches_translation(archived,tmp_path,monkeypatch,corruption):
    audit=module()
    row=json.loads((archived/'result.json').read_text(encoding='utf-8'))
    if corruption=='candidate_bytes':
        (archived/'round-01/candidate.dfy').write_bytes(b'method Fake() {}')
    elif corruption=='same_text_different_bytes':
        path=archived/'round-01/candidate.dfy'
        original_text=path.read_text(encoding='utf-8')
        path.write_bytes(path.read_bytes().replace(b'\n',b'\r\n'))
        assert path.read_text(encoding='utf-8')==original_text
    elif corruption=='legacy_verifier':
        path=archived/'manifest.json';manifest=json.loads(path.read_text(encoding='utf-8'))
        manifest['verifier'].update(adapter='representation_formal_only_v2',source_newline_translation=True)
        write(path,manifest);row['manifest_sha256']=digest(canonical(manifest));rehash_result(archived,row)
    elif corruption in {'fake_success','filtered_verification'}:
        if corruption=='fake_success':
            row['rounds'][0]['verification']['executed']=False
        else:
            row['rounds'][0]['verification']['command']+=['--filter-symbol','Solve']
        write(archived/'round-01/verification.json',row['rounds'][0]['verification'])
        write(archived/'round-01/round.json',row['rounds'][0])
        for name in ['round-01/verification.json','round-01/round.json']:
            key=next(k for k in row['artifact_sha256'] if Path(k)==Path(name))
            row['artifact_sha256'][key]=digest((archived/name).read_text(encoding='utf-8'))
        rehash_result(archived,row)
    elif corruption=='ast_source':
        path=archived/'round-01/structure.json'
        value=json.loads(path.read_text(encoding='utf-8'));value['source_sha256']='0'*64;write(path,value)
        key=next(k for k in row['artifact_sha256'] if Path(k)==Path('round-01/structure.json'))
        row['artifact_sha256'][key]=digest(path.read_text(encoding='utf-8'));rehash_result(archived,row)
    else:
        key=next(k for k in row['artifact_sha256'] if Path(k)==Path('round-01/structure.json'))
        row['artifact_sha256'].pop(key);rehash_result(archived,row)
    def forbidden(*args,**kwargs):pytest.fail('unproven input reached translator')
    monkeypatch.setattr(audit,'_translate',forbidden)
    result=audit.audit_campaign(archived,tmp_path/'audit',dafny_path=DAFNY)
    assert result['counts']['unknown']==1 and result['counts']['translate_succeeded']==0
    assert result['rows'][0]['provenance_verified'] is False
    if corruption=='legacy_verifier':assert result['rows'][0]['reason']=='unsupported_provenance'


def test_same_source_cache_does_not_skip_per_trial_integrity(archived,tmp_path,monkeypatch):
    audit=module()
    campaign=tmp_path/'campaign';(campaign/'runs').mkdir(parents=True)
    jobs=[];rows=[]
    for arm in ['A','B']:
        destination=campaign/'runs'/arm;shutil.copytree(archived,destination)
        manifest=json.loads((destination/'manifest.json').read_text(encoding='utf-8'));manifest['arm']=arm
        write(destination/'manifest.json',manifest)
        row=json.loads((destination/'result.json').read_text(encoding='utf-8'));row['arm']=arm
        row['manifest_sha256']=digest(canonical(manifest));rehash_result(destination,row)
        jobs.append({'task_id':'T1','arm':arm,'replicate':0,'directory':arm});rows.append(row)
    tasks={'T1':{'family_id':'fixture-family'}}
    write(campaign/'jobs.json',jobs);write(campaign/'tasks.json',tasks);write(campaign/'results.json',rows)
    write(campaign/'manifest.json',{'model':{'model':'synthetic-not-research'},'phase':'development_fixture',
          'expected_sessions':2,'jobs_sha256':digest(canonical(jobs)),'tasks_sha256':digest(canonical(tasks))})
    result=audit.audit_campaign(campaign,tmp_path/'audit',dafny_path=DAFNY)
    assert result['primary_successes']==2 and result['unique_compiled_sources']==1 and result['cache_hits']==1
    assert all(row['provenance_verified'] for row in result['rows'])
    # A complete source hash cache is not permission to skip the second record's provenance.
    (campaign/'runs/B/round-01/candidate.dfy').write_bytes(b'method Tampered() {}')
    result=audit.audit_campaign(campaign,tmp_path/'audit-again',dafny_path=DAFNY)
    assert result['counts']['python_syntax_ok']==1 and result['counts']['unknown']==1
    assert result['cache_hits']==0


def test_process_timeout_uses_tree_kill_and_bounded_drain(tmp_path,monkeypatch):
    audit=module();drains=[];kills=[]
    class Process:
        pid=919191;returncode=None
        def communicate(self,timeout=None):
            drains.append(timeout)
            raise subprocess.TimeoutExpired('fixture',timeout,output=b'partial')
        def kill(self):kills.append('parent')
    monkeypatch.setattr(audit.subprocess,'Popen',lambda *args,**kwargs:Process())
    monkeypatch.setattr(audit.subprocess,'run',lambda args,**kwargs:(kills.append(args) or SimpleNamespace(returncode=0)))
    if audit.os.name=='posix':monkeypatch.setattr(audit.os,'killpg',lambda *args:kills.append('group'))
    result=audit._run_process(['fixture'],tmp_path,timeout=0.1)
    assert result['status']=='timeout' and result['stdout']=='partial'
    assert drains==[0.1,5] and kills


def test_audit_refuses_to_write_inside_original_campaign(archived):
    with pytest.raises(ValueError,match='outside|read.only'):
        module().audit_campaign(archived,archived/'compile-audit',dafny_path=DAFNY)


def test_parallel_compilation_matches_serial_and_checks_all_provenance_first(tmp_path,monkeypatch):
    audit=module()
    sources=[b'A',b'B',b'A',b'invalid',b'C',b'D',b'C']
    roster=[(tmp_path/str(i),{'model':'fixture','task_id':str(i),'replicate':0,
                            'arm':'A','success':True,'complete':True}) for i in range(len(sources))]
    monkeypatch.setattr(audit,'_roster',lambda root:(roster,'development_fixture'))
    results=[]
    for workers in [1,4]:
        checked=[];calls=[];lock=threading.Lock();barrier=threading.Barrier(4)
        def verify(path,saved):
            i=int(path.name);checked.append(i)
            if sources[i]==b'invalid':raise ValueError('invalid fixture provenance')
            return sources[i],{'candidate_byte_sha256':audit._sha(sources[i])}
        def compiler(*args):
            assert checked==list(range(len(sources)))
            return {'usable':True}
        def translate(source,directory,dafny,timeout):
            assert checked==list(range(len(sources)))
            with lock:calls.append(source)
            if workers>1:barrier.wait(timeout=10)
            if source==b'C':raise OSError('fixture compiler unavailable')
            directory.mkdir(parents=True)
            compiled={'translate_succeeded':True,'python_syntax_ok':True,'status':'python_syntax_ok'}
            audit._write(directory/'result.json',compiled)
            return compiled
        monkeypatch.setattr(audit,'_verified_source',verify)
        monkeypatch.setattr(audit,'_compiler_identity',compiler)
        monkeypatch.setattr(audit,'_translate',translate)
        result=audit.audit_campaign(tmp_path/'input',tmp_path/f'audit-{workers}',workers=workers)
        assert sorted(calls)==[b'A',b'B',b'C',b'D']
        assert [row['identity'][1] for row in result['rows']]==list(map(str,range(len(sources))))
        assert result['counts']=={'translate_succeeded':4,'python_syntax_ok':4,'failed':0,'unknown':3}
        assert result['cache_hits']==2
        results.append(result)
    assert results[0]['rows']==results[1]['rows']
    assert results[0]['counts']==results[1]['counts']


@pytest.mark.parametrize('workers',[0,9,True,1.5])
def test_worker_count_is_bounded_integer(tmp_path,workers):
    with pytest.raises(ValueError,match='workers'):
        module().audit_campaign(tmp_path/'input',tmp_path/'output',workers=workers)
