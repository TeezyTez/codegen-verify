"""Structural admission and isolated semantic review of pinned public tasks.

The compatibility stage is not final admission. No tested policy participates
in dataset review and no reference implementation is given to a code generator.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import json
from pathlib import Path

from .task import PublicTask, canonical, digest
from .structure import inspect_source, compare_frozen

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'research/data/large-scale-20261009'


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def structure_version():
    names=['structure.py','structure_bridge.ps1','structure_bridge.cs']
    paths=[Path(__file__).parent/name for name in names]
    for path in [Path(__file__).with_name('build_structure_bridge.ps1'),ROOT/'.tools/public-structure-bridge/build.json']:
        if path.exists(): paths.append(path)
    return digest(canonical({str(p.relative_to(ROOT)):digest(p.read_text(encoding='utf-8')) for p in paths}))


def compatibility_one(record, family, reference_result, directory):
    path = directory/(record['id']+'.json')
    version = structure_version()
    if path.exists():
        existing = json.loads(path.read_text(encoding='utf-8'))
        if existing['structure_version'] != version: raise ValueError('structure guard changed: new admission directory required')
        return existing
    result = {'id':record['id'],'family_id':family,'source':record['source'],
        'structure_version':version,'status':'not_qualified','semantic_review':'pending',
        'record_sha256':digest(canonical(record)), 'reasons':[]}
    try:
        task = PublicTask(record,family_id=family)
        skeleton = inspect_source(task.skeleton)
        reference = (DATA/'vericoding/vericoded'/f"{task.id}_vericoded.dfy").read_text(encoding='utf-8')
        answer = inspect_source(reference)
        editable = [d['id'] for d in skeleton['declarations'] if d['name']==task.target_name]
        result.update(task=task.manifest(),skeleton=skeleton,reference_structure=answer,
                      reference_sha256=digest(reference),reference_verification=reference_result['status'])
        if skeleton['status']!='ok': result['reasons'].append('skeleton_'+skeleton['status'])
        if answer['status']!='ok': result['reasons'].append('reference_'+answer['status'])
        if len(editable)!=1: result['reasons'].append('ambiguous_target')
        differences = compare_frozen(skeleton,answer,editable)
        result['frozen_differences'] = differences
        if differences: result['reasons'].append('reference_contract_or_definition_mismatch')
        if reference_result['status']!='all_observed_batches_verified': result['reasons'].append('reference_not_verified')
        target = next((d for d in skeleton['declarations'] if d['id'] in editable),{})
        if 'ensures' not in target.get('header_tokens',[]): result['reasons'].append('no_target_postcondition')
        if not result['reasons']:
            result['status']='structurally_eligible'
            result['editable_ids']=editable
    except (ValueError,OSError,KeyError) as error:
        result['reasons'].append(type(error).__name__+': '+str(error))
    save(path,result)
    return result


def prepare(directory, *, workers=6, ids=None):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    grouping=json.loads((DATA/'recruitment-groups.json').read_text(encoding='utf-8'))
    families={ident:g['provisional_family_id'] for g in grouping['groups'] for ident in g['ids']}
    records=[json.loads(s) for s in (DATA/'vericoding/jsonl/dafny_tasks.jsonl').read_text(encoding='utf-8').splitlines()]
    jobs=[]
    for row in records:
        if ids is not None and row['id'] not in ids: continue
        if row['source']=='dafnybench': continue
        result_path=DATA/'baf_preflight'/(row['id']+'.json')
        if result_path.exists():
            evidence=json.loads(result_path.read_text(encoding='utf-8'))
            if evidence['status']=='all_observed_batches_verified':
                jobs.append((row,families[row['id']],evidence))
    if ids is not None and set(ids)!={j[0]['id'] for j in jobs}:
        raise ValueError('requested IDs missing from reference-qualified native pool')
    save(directory/'plan.json',{'records':len(jobs),'workers':workers,
        'source_selection':'Non-DafnyBench BAF tasks with published reference passing initial 30-second verification. Other records retained in upstream challenge pool.',
        'structure_version':structure_version(),'model_calls':0,'semantic_review_required':True})
    results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(compatibility_one,*job,directory/'tasks') for job in jobs]
        for f in as_completed(futures):
            results.append(f.result())
            if len(results)%50==0 or len(results)==len(jobs):
                print(len(results),dict(Counter(r['status'] for r in results)),flush=True)
                save(directory/'progress.json',{'completed':len(results),'planned':len(jobs),
                    'statuses':dict(Counter(r['status'] for r in results)),'admitted':0})
    save(directory/'compatibility.json',sorted(results,key=lambda r:r['id']))
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--ids',nargs='+')
    args=parser.parse_args()
    prepare(args.output,workers=args.workers,ids=args.ids)
