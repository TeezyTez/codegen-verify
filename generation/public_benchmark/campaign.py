"""Freeze and execute actual paired public-task code generation trials."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import random
import re

from .admission import DATA, ROOT, save
from .model import CodexModel, parse_codex_events
from .runner import run_trial, DEFAULT_BUDGET
from .task import PublicTask, canonical, digest
from .results import paired_summary


def hashes():
    names=['generation/public_benchmark/'+n for n in ['runner.py','policy.py','task.py',
        'model.py','structure.py','structure_bridge.cs','structure_bridge.ps1','results.py','campaign.py']]
    names += ['generation/representation/verifier.py','repair/verifier.py']
    builder='generation/public_benchmark/build_structure_bridge.ps1'
    if (ROOT/builder).is_file(): names.append(builder)
    return {n:digest((ROOT/n).read_text(encoding='utf-8')) for n in names}


def model():
    return CodexModel(model='gpt-6-astra',effort='high',codex_home='C:/Users/16039/.codex',proxy='http://127.0.0.1:10808')


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _raw_digest(value):
    return hashlib.sha256(value).hexdigest()


def _source_digest(value):
    # Match the existing source_hashes contract: UTF-8 text with universal newlines.
    return digest(value.decode('utf-8').replace('\r\n','\n').replace('\r','\n'))


def _contained(root, relative):
    if not isinstance(relative,str) or Path(relative).is_absolute():
        raise ValueError('invalid framework snapshot relative path')
    root=root.resolve()
    path=(root/relative).resolve()
    if root not in path.parents:
        raise ValueError('framework snapshot path escapes its directory')
    return path


def artifact_hashes():
    """Freeze build receipts and their DLLs as bytes; never decode a DLL as text."""
    relative='.tools/public-structure-bridge/build.json'
    receipt_path=ROOT/relative
    if not receipt_path.exists(): return {}
    try:
        receipt_bytes=receipt_path.read_bytes()
        receipt=json.loads(receipt_bytes.decode('utf-8-sig'))
        key=receipt['key']
        if (receipt.get('schema_version')!=1 or not isinstance(key,str)
                or not re.fullmatch('[0-9a-f]{64}',key)
                or not isinstance(receipt.get('identity'),dict)
                or receipt['identity'].get('schema')!='public_dafny_bridge_v2'
                or not isinstance(receipt.get('dll_sha256'),str)
                or not re.fullmatch('[0-9a-f]{64}',receipt['dll_sha256'])):
            raise ValueError('invalid bridge build receipt schema')
        dll_relative='.tools/public-structure-bridge/cache/'+key+'/bridge.dll'
        dll_path=_contained(ROOT,dll_relative)
        declared=Path(receipt['dll_path'])
        if not declared.is_absolute() or declared.resolve()!=dll_path:
            raise ValueError('bridge receipt DLL path differs from its content key')
        dll_hash=_raw_digest(dll_path.read_bytes())
        if dll_hash!=receipt['dll_sha256']:
            raise ValueError('bridge receipt DLL digest differs')
        return {relative:_raw_digest(receipt_bytes),dll_relative:dll_hash}
    except (OSError,UnicodeError,ValueError,TypeError,KeyError) as error:
        raise ValueError('invalid bridge binary artifact receipt or DLL: '+str(error)) from error


def _create_framework_snapshot(directory, source_hashes, binary_hashes):
    """Capture only bytes that still match the proposed frozen identities."""
    if set(source_hashes)&set(binary_hashes):
        raise ValueError('framework snapshot source and artifact inventories overlap')
    blobs={}
    for name,expected in {**source_hashes,**binary_hashes}.items():
        blob=_contained(ROOT,name).read_bytes()
        actual=_source_digest(blob) if name in source_hashes else _raw_digest(blob)
        if actual!=expected:
            raise ValueError('framework changed while creating snapshot: '+name)
        blobs[name]=blob
    snapshot=directory/'framework_snapshot'
    snapshot.mkdir(exist_ok=False)
    for name,blob in blobs.items():
        target=_contained(snapshot,name)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(blob)
    receipt={'schema_version':1,'snapshot_directory':'framework_snapshot',
             'source_hashes':source_hashes,'artifact_hashes':binary_hashes,
             'source_byte_sha256':{name:_raw_digest(blobs[name]) for name in source_hashes},
             'source_hash_algorithm':'SHA256 of UTF-8 text with universal newlines; snapshot preserves original bytes'}
    save(directory/'snapshot_manifest.json',receipt)
    return digest(canonical(receipt))


def _verify_framework_snapshot(directory, manifest):
    expected=manifest.get('framework_snapshot_sha256')
    if not expected:
        raise ValueError('legacy campaign without a bound framework snapshot is analysis-only; cannot run or resume')
    try:
        receipt=_read(directory/'snapshot_manifest.json')
        if (digest(canonical(receipt))!=expected or receipt.get('schema_version')!=1
                or receipt.get('snapshot_directory')!='framework_snapshot'
                or receipt.get('source_hashes')!=manifest['source_hashes']
                or receipt.get('artifact_hashes')!=manifest.get('artifact_hashes',{})
                or set(receipt.get('source_byte_sha256',{}))!=set(manifest['source_hashes'])):
            raise ValueError('framework snapshot manifest differs from frozen inventory')
        snapshot=directory/'framework_snapshot'
        for name,source_hash in manifest['source_hashes'].items():
            blob=_contained(snapshot,name).read_bytes()
            if (_source_digest(blob)!=source_hash
                    or _raw_digest(blob)!=receipt['source_byte_sha256'][name]):
                raise ValueError('framework snapshot source changed: '+name)
        for name,expected_hash in manifest.get('artifact_hashes',{}).items():
            if _raw_digest(_contained(snapshot,name).read_bytes())!=expected_hash:
                raise ValueError('framework snapshot binary artifact changed: '+name)
    except (OSError,UnicodeError,ValueError,TypeError,KeyError) as error:
        raise ValueError('framework snapshot validation failed: '+str(error)) from error


def _transport_json(value):
    # CodexModel hashes the request before adding its two digest fields.
    return json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)


def _review_linkage(task, semantic, semantic_root, batches):
    """Recover legacy review provenance from actual transport inputs and outputs."""
    if semantic.get('id')!=task.id or semantic.get('record_sha256',task.record_sha256)!=task.record_sha256:
        raise ValueError('semantic review record differs: '+task.id)
    pair=semantic.get('reviews',[])
    if len(pair)!=2 or any(row.get('id')!=task.id or row.get('verdict')!='admit' for row in pair):
        raise ValueError('two admitting semantic reviews required: '+task.id)
    if not any(row.get('passed') is True for row in semantic.get('witnesses',[])):
        raise ValueError('semantic review lacks a verified witness: '+task.id)
    expected={**task.public(),'target':task.target_name}
    matches=[]
    for batch in batches:
        try:
            if _read(batch/'result.json').get('status')!='reviewed':
                continue
            reviews=[]
            for reviewer in range(2):
                folder=batch/f'reviewer_{reviewer}'
                request=_read(folder/'request.json')
                response=_read(folder/'result.json')
                prompt=(folder/'prompt.txt').read_text(encoding='utf-8')
                unsigned={k:v for k,v in request.items() if k not in {'request_sha256','command_sha256'}}
                request_hash=digest(_transport_json(unsigned))
                if request.get('request_sha256')!=request_hash or response.get('request_sha256')!=request_hash:
                    raise ValueError('review request hash differs')
                if request.get('command_sha256')!=digest(_transport_json(request['command'])):
                    raise ValueError('review command hash differs')
                if prompt!=request['prompt'] or json.loads(prompt.split('\n',1)[1])!=request['messages']:
                    raise ValueError('actual review prompt differs from recorded messages')
                user_messages=[m for m in request['messages'] if m.get('role')=='user']
                if len(user_messages)!=1:
                    raise ValueError('ambiguous review task message')
                public=json.loads(user_messages[0]['content'])['tasks']
                if [row for row in public if row.get('id')==task.id]!=[expected]:
                    raise ValueError('semantic review did not see current public task')
                identity=request['identity']
                if (identity.get('kind')!='live' or response.get('executed') is not True
                        or response.get('error') is not None or response.get('exit_code')!=0):
                    raise ValueError('semantic review was not a completed live request')
                stdout=(folder/'stdout.jsonl').read_text(encoding='utf-8')
                parsed=parse_codex_events(stdout,model=identity['model'],effort=identity.get('effort','unknown'))
                if parsed['error'] or parsed['text']!=response['text']:
                    raise ValueError('semantic review response differs from actual events')
                output=json.loads(response['text'])['reviews']
                if [row for row in output if row.get('id')==task.id]!=[pair[reviewer]]:
                    raise ValueError('semantic review verdict differs from recorded response')
                reviews.append({'reviewer':reviewer,'batch':str(batch.relative_to(semantic_root)),
                    'request_sha256':request_hash,'prompt_sha256':digest(prompt),
                    'artifact_sha256':{name:digest((folder/name).read_text(encoding='utf-8'))
                        for name in ('request.json','prompt.txt','result.json','stdout.jsonl')}})
            if reviews[0]['request_sha256']==reviews[1]['request_sha256']:
                raise ValueError('semantic reviews reuse one request')
            matches.append(reviews)
        except (OSError,ValueError,KeyError,TypeError,IndexError):
            continue
    if len(matches)!=1:
        raise ValueError('current task requires one unambiguous pair of linked semantic review requests: '+task.id)
    return {'record_sha256':task.record_sha256,'skeleton_sha256':digest(task.skeleton),
            'public_task_sha256':digest(canonical(expected)),
            'semantic_root':str(semantic_root.resolve()),'reviews':matches[0]}


def _family_assignments(family_manifest, phase):
    development=phase.startswith('development_')
    if family_manifest is None:
        if not development:
            raise ValueError('a finalized family manifest is required outside development phases')
        return None
    value=_read(Path(family_manifest))
    mapping=value.get('tasks')
    if not isinstance(mapping,dict) or not mapping:
        raise ValueError('family manifest requires task assignments')
    splits={}
    for row in mapping.values():
        if (not isinstance(row,dict) or not isinstance(row.get('family_id'),str) or not row['family_id'].strip()
                or row.get('split') not in {'development','test'}):
            raise ValueError('invalid family or split assignment')
        family=row['family_id']
        if family in splits and splits[family]!=row['split']:
            raise ValueError('one family cannot cross development/test splits')
        splits[family]=row['split']
    return value


def prepare(directory, admission_root, semantic_root, ids, *, replicates=1,
            phase='development_canary', family_manifest=None):
    directory=Path(directory)
    if directory.exists(): raise FileExistsError('campaign directory already exists')
    if not ids or len(set(ids))!=len(ids) or type(replicates) is not int or replicates<1:
        raise ValueError('unique task IDs and positive integer replicates required')
    family_data=_family_assignments(family_manifest,phase)
    semantic_root=Path(semantic_root)
    batch_index={}
    for path in sorted((semantic_root/'batches').glob('*/batch.json')):
        for ident in _read(path).get('ids',[]): batch_index.setdefault(ident,[]).append(path.parent)
    records={r['id']:r for r in [json.loads(s) for s in (DATA/'vericoding/jsonl/dafny_tasks.jsonl').read_text(encoding='utf-8').splitlines()]}
    tasks={}
    for ident in ids:
        admission=json.loads((Path(admission_root)/'tasks'/f'{ident}.json').read_text(encoding='utf-8'))
        semantic=json.loads((Path(semantic_root)/'tasks'/f'{ident}.json').read_text(encoding='utf-8'))
        if admission['status']!='structurally_eligible' or semantic['status']!='admitted':
            raise ValueError('task has not passed admission: '+ident)
        task=PublicTask(records[ident],family_id=admission['family_id'])
        audited=admission.get('task',{})
        if admission.get('id')!=ident or admission.get('record_sha256')!=task.record_sha256 or audited.get('record_sha256')!=task.record_sha256:
            raise ValueError('current record differs from structural admission: '+ident)
        if (admission['skeleton'].get('source_sha256')!=digest(task.skeleton)
                or audited.get('skeleton_sha256')!=digest(task.skeleton)
                or audited.get('spec_sha256')!=task.spec_sha256):
            raise ValueError('current skeleton differs from structural admission: '+ident)
        linkage=_review_linkage(task,semantic,semantic_root,batch_index.get(ident,[]))
        split='development'
        if family_data is not None:
            assignment=family_data['tasks'].get(ident)
            if assignment is None: raise ValueError('task missing from family manifest: '+ident)
            split=assignment['split']
            expected_split='development' if phase.startswith('development_') else 'test'
            if split!=expected_split: raise ValueError('task split does not match campaign phase: '+ident)
            if assignment['family_id']==admission['family_id']:
                raise ValueError('family manifest must replace provisional recruitment IDs: '+ident)
            task=PublicTask(records[ident],family_id=assignment['family_id'])
        tasks[ident]={'record':records[ident],'family_id':task.family_id,'split':split,
            'frozen_structure':admission['skeleton'],'editable_ids':admission['editable_ids'],
            'admission_sha256':digest(canonical(admission)),'semantic_review_sha256':digest(canonical(semantic)),
            'audit_linkage':linkage,'task':task.manifest()}
    rng=random.Random(20261009)
    blocks=[(ident,r) for ident in sorted(ids) for r in range(replicates)]
    rng.shuffle(blocks);jobs=[]
    for ident,replicate in blocks:
        arms=list('ABCD');rng.shuffle(arms)
        for arm in arms:
            jobs.append({'task_id':ident,'arm':arm,'replicate':replicate,
                         'directory':f'{len(jobs):05d}_{ident}_{arm}_{replicate}'})
    source_hashes=hashes()
    binary_hashes=artifact_hashes()
    directory.mkdir(parents=True,exist_ok=False)
    snapshot_sha256=_create_framework_snapshot(directory,source_hashes,binary_hashes)
    save(directory/'tasks.json',tasks);save(directory/'jobs.json',jobs)
    if family_data is not None: save(directory/'family_manifest.json',family_data)
    manifest={'phase':phase,'model':model().identity(),'source_hashes':source_hashes,
        'artifact_hashes':binary_hashes,'framework_snapshot_sha256':snapshot_sha256,
        'jobs_sha256':digest(canonical(jobs)),'tasks_sha256':digest(canonical(tasks)),
        'family_manifest_sha256':digest(canonical(family_data)) if family_data is not None else None,
        'expected_sessions':len(jobs),'budget':DEFAULT_BUDGET,'seed':20261009,
        'reference_in_generator_input':False,
        'interpretation':'Real code generation. Development canary is not the large confirmatory matrix. No outcome-dependent task additions within this frozen cohort.'}
    _verify_framework_snapshot(directory,manifest)
    save(directory/'manifest.json',manifest)
    print('Frozen',len(jobs),'real generation sessions',flush=True)


def run(directory, *, workers=4):
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    tasks=json.loads((directory/'tasks.json').read_text(encoding='utf-8'))
    jobs=json.loads((directory/'jobs.json').read_text(encoding='utf-8'))
    _verify_framework_snapshot(directory,manifest)
    if manifest['source_hashes']!=hashes(): raise ValueError('frozen framework changed')
    if manifest.get('artifact_hashes',{})!=artifact_hashes(): raise ValueError('frozen framework binary artifacts changed')
    if manifest['jobs_sha256']!=digest(canonical(jobs)) or manifest['tasks_sha256']!=digest(canonical(tasks)):
        raise ValueError('frozen campaign changed')
    if manifest.get('family_manifest_sha256') is not None:
        if digest(canonical(_read(directory/'family_manifest.json')))!=manifest['family_manifest_sha256']:
            raise ValueError('frozen family manifest changed')
    if model().identity()!=manifest['model']: raise ValueError('model changed')

    def one(job):
        _verify_framework_snapshot(directory,manifest)
        if manifest['source_hashes']!=hashes(): raise ValueError('framework changed during campaign')
        if manifest.get('artifact_hashes',{})!=artifact_hashes(): raise ValueError('framework binary artifacts changed during campaign')
        info=tasks[job['task_id']]
        task=PublicTask(info['record'],family_id=info['family_id'])
        return run_trial(task,info['frozen_structure'],info['editable_ids'],model(),directory/'runs'/job['directory'],
                         arm=job['arm'],replicate=job['replicate'],budget=manifest['budget'])

    results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(one,j) for j in jobs]
        for f in as_completed(futures):
            row=f.result();results.append(row)
            print(row['task_id'],row['arm'],row['replicate'],row['success'],row['stop_reason'],row['model_calls'],flush=True)
            save(directory/'progress.json',{'complete':len(results),'expected':len(jobs),
                'successes':sum(r['success'] for r in results),'model_calls':sum(r['model_calls'] for r in results)})
    model_name=manifest['model'].get('model',manifest['model'].get('name','unknown'))
    expected=[(model_name,job['task_id'],job['replicate'],job['arm']) for job in jobs]
    summary=paired_summary(results,expected_sessions=len(jobs),expected_identities=expected)
    summary['phase']=manifest['phase']
    summary['total_model_calls']=sum(r['model_calls'] for r in results)
    summary['total_verifier_calls']=sum(r['verifier_calls'] for r in results)
    summary['total_reported_tokens']=sum(r['total_tokens'] for r in results)
    save(directory/'results.json',results);save(directory/'summary.json',summary)
    print('Complete matrix:',summary['complete_matrix'],flush=True)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run'])
    p.add_argument('--output',type=Path,required=True);p.add_argument('--admission',type=Path)
    p.add_argument('--semantic',type=Path);p.add_argument('--ids',nargs='+')
    p.add_argument('--workers',type=int,default=4);p.add_argument('--replicates',type=int,default=1)
    p.add_argument('--phase',default='development_canary')
    p.add_argument('--family-manifest',type=Path)
    a=p.parse_args()
    if a.command=='prepare':prepare(a.output,a.admission,a.semantic,a.ids,replicates=a.replicates,phase=a.phase,family_manifest=a.family_manifest)
    else:run(a.output,workers=a.workers)
