"""Campaign provenance tests use synthetic recorded evidence, never model calls."""
import json
import hashlib

import pytest

from generation.public_benchmark import campaign
from generation.public_benchmark.task import PublicTask, canonical, digest


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def transport_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


@pytest.fixture
def audited(tmp_path, monkeypatch):
    record = {'id':'T1', 'source':'fixture', 'source-id':'1', 'vc-description':'Increment x.',
              'vc-preamble':'', 'vc-helpers':'',
              'vc-spec':'method Solve(x:int) returns(y:int) ensures y == x+1',
              'vc-code':'PRIVATE_REFERENCE', 'vc-postamble':''}
    task = PublicTask(record, family_id='provisional-1')
    data, admission, semantic = (tmp_path/name for name in ('data','admission','semantic'))
    records_path = data/'vericoding/jsonl/dafny_tasks.jsonl'
    records_path.parent.mkdir(parents=True)
    records_path.write_text(json.dumps(record)+'\n', encoding='utf-8')
    structural = {'id':'T1', 'status':'structurally_eligible', 'family_id':'provisional-1',
                  'record_sha256':task.record_sha256, 'task':task.manifest(), 'editable_ids':['Solve'],
                  'skeleton':{'status':'ok', 'trusted_ast':True, 'source_sha256':digest(task.skeleton),
                              'declarations':[]}}
    write(admission/'tasks/T1.json', structural)
    reviews = [{'id':'T1', 'verdict':'admit', 'semantic_family':'Integer successor',
                'reason':f'Independent fixture review {i}', 'witness_body':'{ var y := Solve(0); }'}
               for i in range(2)]
    write(semantic/'tasks/T1.json', {'id':'T1', 'status':'admitted', 'reviews':reviews,
                                   'witnesses':[{'passed':True, 'body':reviews[0]['witness_body']}]})
    batch = semantic/'batches/batch-one'
    write(batch/'batch.json', {'ids':['T1'], 'purpose':'independent_semantic_admission_not_policy_efficacy'})
    write(batch/'result.json', {'batch':['T1'], 'status':'reviewed'})
    for i, review in enumerate(reviews):
        folder = batch/f'reviewer_{i}'
        messages = [{'role':'system', 'content':f'Independent reviewer {i}'},
                    {'role':'user', 'content':canonical({'tasks':[{**task.public(),'target':'Solve'}]})}]
        prompt = 'Complete the task in the following role-labeled message transcript. Do not call tools or inspect files. Return only the final answer requested by the transcript.\n'+transport_json(messages)
        request = {'messages':messages, 'prompt':prompt, 'command':['fixture'],
                   'identity':{'kind':'live','model':'fixture-model'}}
        request_hash = digest(transport_json(request))
        request.update(request_sha256=request_hash, command_sha256=digest(transport_json(['fixture'])))
        text = canonical({'reviews':[review]})
        write(folder/'request.json', request)
        (folder/'prompt.txt').write_text(prompt, encoding='utf-8')
        write(folder/'result.json', {'error':None, 'executed':True, 'exit_code':0,
                                     'request_sha256':request_hash, 'text':text})
        events = [{'type':'turn.started'}, {'type':'item.completed','item':{'type':'agent_message','text':text}},
                  {'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':10}}]
        (folder/'stdout.jsonl').write_text('\n'.join(json.dumps(x) for x in events), encoding='utf-8')
    class Model:
        def identity(self): return {'kind':'live','model':'fixture-model'}
    monkeypatch.setattr(campaign, 'DATA', data)
    monkeypatch.setattr(campaign, 'model', Model)
    return {'root':tmp_path, 'record':record, 'records_path':records_path, 'admission':admission,
            'semantic':semantic, 'batch':batch, 'task':task}


def prepare(audited, **kwargs):
    directory = audited['root']/'campaign'
    campaign.prepare(directory, audited['admission'], audited['semantic'], ['T1'], **kwargs)
    return directory


def test_legacy_review_is_linked_to_both_actual_prompts_before_freeze(audited):
    directory = prepare(audited)
    frozen = json.loads((directory/'tasks.json').read_text())['T1']
    linkage = frozen['audit_linkage']
    assert linkage['record_sha256'] == audited['task'].record_sha256
    assert linkage['skeleton_sha256'] == digest(audited['task'].skeleton)
    assert len(linkage['reviews']) == 2
    assert {row['reviewer'] for row in linkage['reviews']} == {0,1}
    for row in linkage['reviews']:
        assert len(row['request_sha256']) == len(row['prompt_sha256']) == 64


def test_changed_description_cannot_reuse_structural_admission(audited):
    audited['record']['vc-description'] = 'Return x minus one.'
    audited['records_path'].write_text(json.dumps(audited['record'])+'\n')
    with pytest.raises(ValueError, match='record'):
        prepare(audited)


def test_stale_skeleton_hash_is_rejected(audited):
    path = audited['admission']/'tasks/T1.json'
    value = json.loads(path.read_text()); value['skeleton']['source_sha256'] = '0'*64
    write(path, value)
    with pytest.raises(ValueError, match='skeleton'):
        prepare(audited)


@pytest.mark.parametrize('reviewer', [0,1])
def test_each_review_requires_its_actual_prompt_evidence(audited, reviewer):
    (audited['batch']/f'reviewer_{reviewer}'/'request.json').unlink()
    with pytest.raises(ValueError, match='semantic|review'):
        prepare(audited)


def test_current_admission_cannot_reuse_old_description_reviews(audited):
    audited['record']['vc-description'] = 'Compute the successor.'
    audited['records_path'].write_text(json.dumps(audited['record'])+'\n')
    new_task = PublicTask(audited['record'], family_id='provisional-1')
    path = audited['admission']/'tasks/T1.json'
    value = json.loads(path.read_text()); value.update(record_sha256=new_task.record_sha256, task=new_task.manifest())
    write(path, value)
    with pytest.raises(ValueError, match='semantic|review'):
        prepare(audited)


def test_review_result_must_match_the_saved_admission_verdict(audited):
    path = audited['semantic']/'tasks/T1.json'
    value = json.loads(path.read_text()); value['reviews'][1]['reason'] = 'Different response'
    write(path, value)
    with pytest.raises(ValueError, match='semantic|review'):
        prepare(audited)


def test_prompt_file_must_match_recorded_transport_request(audited):
    (audited['batch']/'reviewer_1/prompt.txt').write_text('Another task')
    with pytest.raises(ValueError, match='semantic|review'):
        prepare(audited)


def test_main_phase_rejects_provisional_family_without_manifest(audited):
    with pytest.raises(ValueError, match='family'):
        prepare(audited, phase='main_model1')


def test_main_freezes_finalized_family_mapping_and_test_split(audited):
    path = audited['root']/'families.json'
    write(path, {'tasks':{'T1':{'family_id':'final-family-1','split':'test'}}})
    directory = prepare(audited, phase='main_model1', family_manifest=path)
    tasks = json.loads((directory/'tasks.json').read_text())
    assert tasks['T1']['family_id'] == tasks['T1']['task']['family_id'] == 'final-family-1'
    assert tasks['T1']['split'] == 'test'
    manifest = json.loads((directory/'manifest.json').read_text())
    assert manifest['family_manifest_sha256'] == digest(canonical(json.loads(path.read_text())))
    assert json.loads((directory/'family_manifest.json').read_text()) == json.loads(path.read_text())


@pytest.mark.parametrize('mapping', [
    {'T1':{'family_id':'provisional-1','split':'test'}},
    {'T1':{'family_id':'final-1','split':'development'}},
    {'T1':{'family_id':'final-1','split':'test'},'T2':{'family_id':'final-1','split':'development'}},
])
def test_main_rejects_provisional_or_cross_split_family_assignments(audited, mapping):
    path = audited['root']/'families.json'; write(path, {'tasks':mapping})
    with pytest.raises(ValueError, match='family|split'):
        prepare(audited, phase='main_model1', family_manifest=path)


def test_run_uses_exact_frozen_roster_not_only_expected_count(audited, monkeypatch):
    directory = prepare(audited)
    def trial(task, frozen, editable, model, output, *, arm, replicate, budget):
        return {'task_id':'UNROSTERED','family_id':task.family_id,'arm':arm,
                'replicate':replicate,'model':'fixture-model',
                'complete':True,'research_eligible':True,'success':True,'stop_reason':'fixture',
                'model_calls':1,'verifier_calls':1,'total_tokens':20}
    monkeypatch.setattr(campaign, 'run_trial', trial)
    assert campaign.run(directory, workers=1)['complete_matrix'] is False


def fixture_trial(task, frozen, editable, model, output, *, arm, replicate, budget):
    return {'task_id':task.id,'family_id':task.family_id,'arm':arm,'replicate':replicate,
            'model':'fixture-model','complete':True,'research_eligible':True,'success':True,
            'stop_reason':'fixture','model_calls':1,'verifier_calls':1,'total_tokens':20}


def test_prepare_preserves_actual_source_bytes_and_binds_snapshot_manifest(audited):
    directory=prepare(audited)
    manifest=json.loads((directory/'manifest.json').read_text())
    snapshot=json.loads((directory/'snapshot_manifest.json').read_text())
    assert digest(canonical(snapshot))==manifest['framework_snapshot_sha256']
    assert snapshot['source_hashes']==manifest['source_hashes']
    for name,expected in manifest['source_hashes'].items():
        copied=directory/'framework_snapshot'/name
        assert copied.read_bytes()==(campaign.ROOT/name).read_bytes()
        assert digest(copied.read_text(encoding='utf-8'))==expected


@pytest.mark.parametrize('completed', [False,True])
def test_tampered_snapshot_stops_new_run_and_completed_resume(audited, monkeypatch, completed):
    directory=prepare(audited)
    monkeypatch.setattr(campaign,'run_trial',fixture_trial)
    if completed:
        assert campaign.run(directory,workers=1)['complete_matrix'] is True
    copied=directory/'framework_snapshot/generation/public_benchmark/policy.py'
    copied.parent.mkdir(parents=True,exist_ok=True)
    copied.write_bytes(b'TAMPERED SOURCE')
    with pytest.raises(ValueError,match='snapshot'):
        campaign.run(directory,workers=1)


def test_snapshot_inventory_cannot_omit_a_frozen_source(audited, monkeypatch):
    directory=prepare(audited)
    path=directory/'snapshot_manifest.json'
    snapshot=json.loads(path.read_text())
    snapshot['source_hashes'].pop('generation/public_benchmark/policy.py')
    write(path,snapshot)
    manifest_path=directory/'manifest.json'
    manifest=json.loads(manifest_path.read_text())
    manifest['framework_snapshot_sha256']=digest(canonical(snapshot))
    write(manifest_path,manifest)
    monkeypatch.setattr(campaign,'run_trial',fixture_trial)
    with pytest.raises(ValueError,match='snapshot'):
        campaign.run(directory,workers=1)


def test_legacy_manifest_without_bound_snapshot_is_analysis_only(audited, monkeypatch):
    directory=prepare(audited)
    path=directory/'manifest.json'
    manifest=json.loads(path.read_text());manifest.pop('framework_snapshot_sha256',None)
    write(path,manifest)
    monkeypatch.setattr(campaign,'run_trial',fixture_trial)
    with pytest.raises(ValueError,match='analysis.only|snapshot'):
        campaign.run(directory,workers=1)


def framework_repository(audited,monkeypatch):
    repository=audited['root']/'isolated-framework'
    for name in campaign.hashes():
        target=repository/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((campaign.ROOT/name).read_bytes())
    monkeypatch.setattr(campaign,'ROOT',repository)
    return repository


def test_optional_builder_and_binary_receipt_are_frozen_as_real_bytes(audited,monkeypatch):
    repository=framework_repository(audited,monkeypatch)
    builder='generation/public_benchmark/build_structure_bridge.ps1'
    (repository/builder).write_bytes(b'# synthetic builder\r\n')
    dll_relative='.tools/public-structure-bridge/cache/'+'a'*64+'/bridge.dll'
    dll=repository/dll_relative;dll.parent.mkdir(parents=True);dll.write_bytes(b'\x00\xffDLL\x80')
    receipt_relative='.tools/public-structure-bridge/build.json'
    write(repository/receipt_relative,{'schema_version':1,'key':'a'*64,
                                     'identity':{'schema':'public_dafny_bridge_v2'},'dll_path':str(dll.resolve()),
                                     'dll_sha256':hashlib.sha256(dll.read_bytes()).hexdigest()})
    directory=prepare(audited)
    manifest=json.loads((directory/'manifest.json').read_text())
    assert builder in manifest['source_hashes']
    for name in [receipt_relative,dll_relative]:
        assert manifest['artifact_hashes'][name]==hashlib.sha256((repository/name).read_bytes()).hexdigest()
        assert (directory/'framework_snapshot'/name).read_bytes()==(repository/name).read_bytes()
    monkeypatch.setattr(campaign,'run_trial',fixture_trial)
    (directory/'framework_snapshot'/dll_relative).write_bytes(b'\x00CHANGED')
    with pytest.raises(ValueError,match='snapshot'):
        campaign.run(directory,workers=1)


@pytest.mark.parametrize('failure',['missing_dll','wrong_digest','invalid_receipt'])
def test_invalid_existing_binary_receipt_fails_closed(audited,monkeypatch,failure):
    repository=framework_repository(audited,monkeypatch)
    dll=repository/('.tools/public-structure-bridge/cache/'+'a'*64+'/bridge.dll')
    dll.parent.mkdir(parents=True);dll.write_bytes(b'\xfffixture')
    receipt=repository/'.tools/public-structure-bridge/build.json'
    value={'schema_version':1,'key':'a'*64,'identity':{'schema':'public_dafny_bridge_v2'},
           'dll_path':str(dll.resolve()),'dll_sha256':hashlib.sha256(dll.read_bytes()).hexdigest()}
    if failure=='missing_dll':dll.unlink()
    if failure=='wrong_digest':value['dll_sha256']='0'*64
    if failure=='invalid_receipt':value={}
    write(receipt,value)
    with pytest.raises(ValueError,match='artifact|receipt|DLL'):
        prepare(audited)
