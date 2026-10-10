"""Reverify frozen reference text and prior review witnesses; never call a model."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path

from .admission import DATA, ROOT, structure_version
from .runner import _verification
from .structure import BUILD_MANIFEST, compare_frozen, inspect_source
from .task import PublicTask, canonical, digest
from generation.representation.verifier import Dafny


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8'))


def _bytes_hash(value):
    return hashlib.sha256(value).hexdigest()


def _identity():
    build=_read(BUILD_MANIFEST)
    verifier=Dafny(timeout=120).identity()
    sources=['generation/public_benchmark/'+name for name in
             ('final_qualification.py','structure.py','structure_bridge.cs','structure_bridge.ps1','runner.py','task.py')]
    sources+=['generation/representation/verifier.py','repair/verifier.py']
    return {'structure_version':structure_version(),'bridge_build':build,'verifier':verifier,
            'source_hashes':{name:_bytes_hash((ROOT/name).read_bytes()) for name in sources}}


def _guard_status(report):
    return 'unknown' if report.get('status')=='tool_error' else 'failed'


def _verify_stage(source,structure,primary,folder):
    evidence=_verification(Dafny(timeout=120).verify(source,names=(),timeout=120),primary)
    _write(folder/'verification.json',evidence)
    for name,key in [('stdout.txt','stdout'),('stderr.txt','stderr'),('verifier.csv','csv_log')]:
        (folder/name).write_bytes(evidence.get(key,'').encode('utf-8'))
    passed=evidence.get('status')=='verified' and evidence.get('executed') is True and evidence.get('real_verifier') is True
    status='passed' if passed else 'failed' if evidence.get('status') in {'verification_failed','parse_error'} else 'unknown'
    return {'status':status,'passed':passed,'evidence':evidence,'source_sha256':digest(source),
            'verified_input_sha256':_bytes_hash(source.encode('utf-8'))}


def _inspect(source,folder):
    folder.mkdir(parents=True,exist_ok=False)
    (folder/'source.dfy').write_bytes(source.encode('utf-8'))
    report=inspect_source(source)
    _write(folder/'ast.json',report)
    return report


def _witness(task,reference,reference_structure,editable_ids,body,folder):
    source=reference+'\nmethod AdmissionWitnessFixed()\n'+body+'\n'
    report=_inspect(source,folder)
    result={'body':body,'source_sha256':digest(source),'verified_input_sha256':digest(source),
            'status':'failed','passed':False,'reason':None,'guard_findings':[]}
    if report.get('status')!='ok' or not report.get('trusted_ast') or report.get('findings'):
        result.update(status=_guard_status(report),reason='witness_ast_rejected',guard_findings=report.get('findings',[]))
    else:
        findings=compare_frozen(reference_structure,report,[])
        original={d['id'] for d in reference_structure['declarations']}
        extra=[d for d in report['declarations'] if d['id'] not in original]
        if findings:
            result.update(reason='witness_changed_reference',guard_findings=findings)
        elif len(extra)!=1 or extra[0]['name']!='AdmissionWitnessFixed':
            result['reason']='witness_must_add_exactly_one_declaration'
        elif extra[0]['header_tokens']!=['method','AdmissionWitnessFixed','(',')']:
            result['reason']='witness_header_not_parameterless_method'
        elif {'if','while','for','match','return','break','continue','yield','forall'} & set(extra[0]['tokens']):
            result['reason']='witness_not_straight_line'
        elif not set(editable_ids) & set(extra[0]['depends_on']):
            result['reason']='witness_does_not_call_target'
        else:
            result.update(_verify_stage(source,report,extra[0],folder))
            result['reason']='verified_nonempty_input' if result['passed'] else 'witness_not_verified'
    _write(folder/'result.json',result)
    return result


def qualify_one(record,admission,semantic,reference_path,output_dir,*,toolchain=None):
    """One fresh qualification, retaining failed and unknown stages without rerolls."""
    root=Path(output_dir).resolve(); root.mkdir(parents=True,exist_ok=False)
    result={'schema_version':1,'id':record.get('id'),'status':'unknown','passed':False,
            'reason':None,'model_calls':0,'reference':None,'witnesses':[],
            'source_normalization':'universal_newlines_to_LF'}
    try:
        task=PublicTask(record,family_id=admission['family_id'])
        identity=toolchain or _identity()
        manifest={'task':task.manifest(),'admission_sha256':digest(canonical(admission)),
                  'semantic_sha256':digest(canonical(semantic)),'toolchain':identity,
                  'source_normalization':'universal_newlines_to_LF',
                  'purpose':'fresh_final_reference_and_nonempty_input_qualification_not_generation_efficacy'}
        _write(root/'manifest.json',manifest)
        result['manifest_sha256']=digest(canonical(manifest))
        if (identity['bridge_build'].get('identity',{}).get('schema')!='public_dafny_bridge_v2'
                or identity['verifier'].get('adapter')!='representation_formal_only_v3'
                or identity['verifier'].get('source_newline_translation') is not False):
            result['reason']='required_byte_preserving_toolchain_unavailable'
        elif admission.get('structure_version')!=identity['structure_version']:
            result.update(status='failed',reason='stale_structural_admission')
        elif (admission.get('id')!=task.id or admission.get('status')!='structurally_eligible'
                or admission.get('record_sha256')!=task.record_sha256
                or admission.get('task',{}).get('spec_sha256')!=task.spec_sha256
                or admission.get('task',{}).get('skeleton_sha256')!=digest(task.skeleton)):
            result.update(status='failed',reason='admission_record_or_spec_mismatch')
        elif (semantic.get('id')!=task.id or semantic.get('status')!='admitted'
                or semantic.get('record_sha256',task.record_sha256)!=task.record_sha256
                or len(semantic.get('reviews',[]))!=2
                or any(r.get('id')!=task.id or r.get('verdict')!='admit' or not isinstance(r.get('witness_body'),str)
                       for r in semantic.get('reviews',[]))):
            result.update(status='failed',reason='two_prior_admitting_reviews_required')
        else:
            raw=Path(reference_path).read_bytes()
            # The admission hash historically binds read_text universal-newline text.
            # Preserve publication bytes separately; execute exactly this documented text.
            reference=raw.decode('utf-8').replace('\r\n','\n').replace('\r','\n')
            (root/'published-reference.dfy').write_bytes(raw)
            (root/'reference-input.dfy').write_bytes(reference.encode('utf-8'))
            result.update(raw_file_sha256=_bytes_hash(raw),reference_sha256=digest(reference),
                          verified_input_sha256=digest(reference))
            if digest(reference)!=admission.get('reference_sha256'):
                result.update(status='failed',reason='reference_hash_mismatch')
            else:
                skeleton=_inspect(task.skeleton,root/'skeleton')
                answer=_inspect(reference,root/'reference')
                (root/'reference'/'published.dfy').write_bytes(raw)
                old_skeleton=admission.get('skeleton',{})
                findings=compare_frozen(old_skeleton,skeleton,[])+compare_frozen(skeleton,answer,admission['editable_ids'])
                _write(root/'reference'/'guard.json',findings)
                if skeleton.get('status')!='ok' or answer.get('status')!='ok':
                    result.update(status='unknown' if 'tool_error' in {skeleton.get('status'),answer.get('status')} else 'failed',
                                  reason='fresh_reference_or_skeleton_ast_rejected')
                elif findings or not skeleton.get('trusted_ast') or not answer.get('trusted_ast') or answer.get('findings'):
                    result.update(status='failed',reason='fresh_reference_guard_failed',guard_findings=findings)
                else:
                    primary=[d for d in answer['declarations'] if d['name']==task.target_name and d['id'] in admission['editable_ids']]
                    if len(primary)!=1:
                        result.update(status='failed',reason='ambiguous_primary_target')
                    else:
                        result['reference']=_verify_stage(reference,answer,primary[0],root/'reference')
                        _write(root/'reference'/'result.json',result['reference'])
                        if result['reference']['status']!='passed':
                            result.update(status=result['reference']['status'],reason='reference_not_verified')
                        else:
                            for index,review in enumerate(semantic['reviews']):
                                witness=_witness(task,reference,answer,admission['editable_ids'],review['witness_body'],root/f'witness-{index}')
                                result['witnesses'].append(witness)
                                if witness['passed']:
                                    result.update(status='passed',passed=True,reason='reference_and_fresh_witness_verified',witness_index=index)
                                    break
                            if not result['passed']:
                                result.update(status='unknown' if any(r['status']=='unknown' for r in result['witnesses']) else 'failed',
                                              reason='no_fresh_verified_witness')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result.update(status='unknown',passed=False,reason='qualification_infrastructure_failure',error_type=type(exc).__name__)
    result['artifact_sha256']={str(p.relative_to(root)):_bytes_hash(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
    _write(root/'result.json',result)
    (root/'result.sha256').write_bytes((digest(canonical(result))+'\n').encode('ascii'))
    return result


def run(ids,admission_root,semantic_root,output,*,workers=6):
    if not ids or len(set(ids))!=len(ids) or type(workers) is not int or workers<1:
        raise ValueError('unique IDs and positive workers required')
    records={r['id']:r for r in (json.loads(line) for line in (DATA/'vericoding/jsonl/dafny_tasks.jsonl').read_text(encoding='utf-8').splitlines())}
    prepared=[]
    for ident in ids:
        if ident not in records: raise ValueError('unknown task ID: '+ident)
        admission=_read(Path(admission_root)/'tasks'/f'{ident}.json')
        semantic=_read(Path(semantic_root)/'tasks'/f'{ident}.json')
        reference=DATA/'vericoding/vericoded'/f'{ident}_vericoded.dfy'
        if not reference.is_file(): raise ValueError('missing published reference: '+ident)
        prepared.append((records[ident],admission,semantic,reference))
    root=Path(output).resolve(); root.mkdir(parents=True,exist_ok=False)
    toolchain=_identity()
    _write(root/'manifest.json',{'ids':ids,'workers':workers,'model_calls':0,'toolchain':toolchain,
                               'admission_root':str(Path(admission_root).resolve()),'semantic_root':str(Path(semantic_root).resolve()),
                               'reference_timeout_seconds':120,'witness_timeout_seconds':120})
    rows=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(qualify_one,*entry,root/'tasks'/entry[0]['id'],toolchain=toolchain) for entry in prepared]
        for future in as_completed(futures):
            row=future.result(); rows.append(row)
            _write(root/'tasks'/f"{row['id']}.json",row)
            _write(root/'progress.json',{'completed':len(rows),'expected':len(ids),'statuses':dict(Counter(r['status'] for r in rows))})
            print(row['id'],row['status'],row['reason'],flush=True)
    rows.sort(key=lambda r:r['id'])
    _write(root/'results.json',rows)
    summary={'expected':len(ids),'completed':len(rows),'statuses':dict(Counter(r['status'] for r in rows)),
             'passed_ids':[r['id'] for r in rows if r['status']=='passed'],'model_calls':0,
             'interpretation':'Fresh formal reference/witness qualification only; previous semantic reviews remain independent evidence, not new model review.'}
    _write(root/'summary.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ids',nargs='+',required=True)
    parser.add_argument('--admission',type=Path,required=True)
    parser.add_argument('--semantic',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=6)
    args=parser.parse_args()
    print(json.dumps(run(args.ids,args.admission,args.semantic,args.output,workers=args.workers),ensure_ascii=False))
