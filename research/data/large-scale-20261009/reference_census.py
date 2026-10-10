"""Bulk verification of pinned DafnyBench references; not codegen task admission."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from generation.representation.verifier import Dafny
from repair.verifier import classify
from repair.task import digest

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'reference_census'


def stripped(text):
    # Conservative lexical screening only; not the future candidate acceptance parser.
    return re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"', ' ', text)


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def prepare():
    OUT.mkdir(exist_ok=True)
    assert not (OUT/'plan.json').exists()
    data=json.loads((ROOT/'dafnybench/DafnyBench/test.json').read_text(encoding='utf-8'))
    assert len(data)==782
    jobs=[]
    for row in data:
        code=row['ground_truth']
        clean=stripped(code)
        flags=[]
        for name,pattern in [('assume',r'\bassume\b'),('axiom',r'\baxiom\b'),
                             ('extern',r'\bextern\b'),('include',r'\binclude\b'),
                             ('import',r'\bimport\b'),('bodyless_or_declared_method',r'\bmethod\b[^{};]*;'),
                             ('verification_attributes',r'\{:\s*(?:verify|options|vcs|isolate_assertions|timeLimit|resource_limit)\b'),
                             ('termination_opt_out',r'\bdecreases\s*\*'),('nondeterministic_choice',r':\|')]:
            if re.search(pattern,clean): flags.append(name)
        if not re.search(r'\bensures\b',clean): flags.append('no_ensures_anywhere')
        if not re.search(r'\bmethod\b',clean): flags.append('no_method_keyword')
        jobs.append({'id':row['test_ID'],'filename':row['test_file'],'source_sha256':digest(code),
                     'chars':len(code),'lexical_flags':flags,
                     'method_keyword_count':len(re.findall(r'\bmethod\b',clean)),
                     'ensures_keyword_count':len(re.findall(r'\bensures\b',clean)),
                     'skip_external_dependency':'include' in flags})
    workers=min(8,max(1,(os.cpu_count() or 2)//2))
    save(OUT/'plan.json',{'protocol':'pinned_reference_compatibility_census_v1',
         'created_at':datetime.now(timezone.utc).isoformat(),'workers':workers,
         'toolchain':Dafny(timeout=30).identity(),'script_sha256':digest(Path(__file__).read_text(encoding='utf-8')),
         'model_calls':0,'source_count':len(data),'jobs':jobs,
         'purpose':'Observe reference compatibility and quality warning flags. No claim of specification completeness, independent tasks, or codegen admission.',
         'no_expected_target_names':'Reference-only census classifies all observed batches; cannot be used as candidate acceptance.',
         'external_includes':'Skipped to avoid resolving dependencies outside the single-file snapshot.'})
    print('Frozen',len(jobs),'reference entries; workers',workers,flush=True)


def run():
    plan=json.loads((OUT/'plan.json').read_text(encoding='utf-8'))
    assert plan['script_sha256']==digest(Path(__file__).read_text(encoding='utf-8'))
    assert plan['toolchain']==Dafny(timeout=30).identity()
    data={r['test_ID']:r for r in json.loads((ROOT/'dafnybench/DafnyBench/test.json').read_text(encoding='utf-8'))}
    def one(job):
        path=OUT/(job['id']+'.json')
        if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
        code=data[job['id']]['ground_truth']
        assert digest(code)==job['source_sha256']
        if job['skip_external_dependency']:
            result={'job':job,'reference_status':'skipped_external_dependency','evidence':None}
        else:
            v=Dafny(timeout=30).verify(code,names=())
            status=v.status
            if status=='unknown' and v.executed and v.real_verifier:
                raw=classify(v.stdout+v.stderr,v.returncode,v.obligations)
                if raw=='passed': status='all_observed_batches_verified'
            result={'job':job,'reference_status':status,'evidence':v.to_dict()}
        save(path,result)
        return result
    done=[]
    with ThreadPoolExecutor(max_workers=plan['workers']) as pool:
        futures=[pool.submit(one,j) for j in plan['jobs']]
        for future in as_completed(futures):
            row=future.result();done.append(row)
            if len(done)%40==0 or len(done)==len(futures):
                print(len(done),dict(Counter(r['reference_status'] for r in done)),flush=True)
    save(OUT/'results.json',sorted(done,key=lambda r:r['job']['id']))
    flags=Counter(f for r in done for f in r['job']['lexical_flags'])
    verified=[r for r in done if r['reference_status']=='all_observed_batches_verified']
    flagfree=[r for r in verified if not r['job']['lexical_flags']]
    summary={'sources':len(done),'actual_verifier_calls':sum(r['evidence'] is not None for r in done),
        'model_calls':0,'statuses':dict(Counter(r['reference_status'] for r in done)),
        'lexical_warning_counts':dict(flags),'verified_with_no_lexical_flags':len(flagfree),
        'flagfree_candidate_ids':[r['job']['id'] for r in flagfree],
        'interpretation':'Flag-free verification is only a screening signal, NOT validated codegen task admission.'}
    save(OUT/'summary.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='flagfree_candidate_ids'}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','run'])
    args=parser.parse_args()
    prepare() if args.mode=='prepare' else run()
