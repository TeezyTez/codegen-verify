"""Final qualification fixtures; real Dafny, no model calls or public task batch."""
import json

import pytest

from generation.public_benchmark import final_qualification as qualification
from generation.public_benchmark.admission import structure_version
from generation.public_benchmark.structure import inspect_source
from generation.public_benchmark.task import PublicTask, digest


@pytest.fixture
def case(tmp_path):
    record={'id':'Fixture1','source':'fixture','source-id':'1','vc-description':'Return successor for nonnegative x.',
            'vc-preamble':'// 中文 😀','vc-helpers':'',
            'vc-spec':'method Solve(x:int) returns(y:int) requires x >= 0 ensures y == x+1',
            'vc-code':'not forwarded','vc-postamble':''}
    task=PublicTask(record,family_id='fixture-family')
    reference=task.assemble({'implementation':'{ y := x+1; }','helpers':''})
    path=tmp_path/'reference.dfy'; path.write_bytes(reference.encode('utf-8'))
    admission={'id':task.id,'status':'structurally_eligible','family_id':task.family_id,
               'record_sha256':task.record_sha256,'task':task.manifest(),'structure_version':structure_version(),
               'reference_sha256':digest(reference),'editable_ids':['Solve'],'skeleton':inspect_source(task.skeleton)}
    semantic={'id':task.id,'status':'admitted','reviews':[{'id':task.id,'verdict':'admit',
        'witness_body':'{ var y := Solve(0); }'} for _ in range(2)],'witnesses':[{'passed':True}]}
    return record,admission,semantic,path,tmp_path/'qualification'


def test_reference_and_fresh_witness_pass_with_saved_byte_exact_evidence(case):
    result=qualification.qualify_one(*case)
    assert result['status']=='passed' and result['passed'] is True
    assert result['reference']['evidence']['status']=='verified'
    assert result['witnesses'][0]['evidence']['primary_batches']['AdmissionWitnessFixed (correctness)']=='passed'
    assert len(result['witnesses'])==1
    assert (case[-1]/'reference/source.dfy').read_bytes()==case[-2].read_bytes()
    assert (case[-1]/'reference/verifier.csv').is_file()
    assert (case[-1]/'witness-0/ast.json').is_file()
    assert json.loads((case[-1]/'result.json').read_text())['model_calls']==0


@pytest.mark.parametrize('body',[
    '{ if false { var y := Solve(0); } }',
    '{ assume false; var y := Solve(0); }',
    '{ var y := Solve(-1); }',
])
def test_unreachable_assumed_or_invalid_input_witness_never_passes(case,body):
    for review in case[2]['reviews']: review['witness_body']=body
    result=qualification.qualify_one(*case)
    assert result['reference']['status']=='passed'
    assert result['status']=='failed' and result['passed'] is False
    assert len(result['witnesses'])==2 and all(not row['passed'] for row in result['witnesses'])


def test_second_independent_witness_is_tried_after_first_guard_failure(case):
    case[2]['reviews'][0]['witness_body']='{ if false { var y := Solve(0); } }'
    result=qualification.qualify_one(*case)
    assert result['status']=='passed' and len(result['witnesses'])==2
    assert result['witnesses'][0]['passed'] is False and result['witnesses'][1]['passed'] is True


def test_unknown_real_verification_is_not_passed(case,monkeypatch):
    actual=qualification.Dafny
    class Unknown:
        def __init__(self,**kwargs): pass
        def identity(self): return actual(timeout=120).identity()
        def verify(self,*args,**kwargs):
            return {'status':'unknown','executed':True,'real_verifier':True,'returncode':0,
                    'stdout':'inconclusive','stderr':'','csv_log':'','obligations':{}}
    monkeypatch.setattr(qualification,'Dafny',Unknown)
    result=qualification.qualify_one(*case)
    assert result['status']=='unknown' and result['passed'] is False
    assert result['witnesses']==[]


def test_crlf_publication_is_traced_and_exact_normalized_input_is_verified(case):
    case[-2].write_bytes(case[-2].read_bytes().replace(b'\n',b'\r\n'))
    result=qualification.qualify_one(*case)
    assert result['status']=='passed'
    assert result['raw_file_sha256']!=result['verified_input_sha256']
    assert result['source_normalization']=='universal_newlines_to_LF'
    assert (case[-1]/'reference/published.dfy').read_bytes()==case[-2].read_bytes()
    verified=(case[-1]/'reference/source.dfy').read_bytes()
    assert b'\r' not in verified
    assert digest(verified.decode('utf-8'))==result['verified_input_sha256']==case[1]['reference_sha256']


def test_changed_reference_text_does_not_match_frozen_hash(case):
    case[-2].write_bytes(case[-2].read_bytes().replace(b'x+1',b'x+2'))
    result=qualification.qualify_one(*case)
    assert result['status']=='failed' and result['reason']=='reference_hash_mismatch'
    assert (case[-1]/'published-reference.dfy').read_bytes()==case[-2].read_bytes()
    assert (case[-1]/'reference-input.dfy').is_file()


def test_stale_structure_admission_is_not_silently_reused(case):
    case[1]['structure_version']='old-bridge-v1'
    result=qualification.qualify_one(*case)
    assert result['status']=='failed' and result['reason']=='stale_structural_admission'
