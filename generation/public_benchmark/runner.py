"""Frozen, auditable public-task trials; no reference implementation enters prompts."""
from copy import deepcopy
import csv
import json
import math
from pathlib import Path
import time

from .policy import EvidenceLedger, build_messages, choose_target
from .results import declaration_outcomes
from .structure import compare_frozen, inspect_source
from .task import canonical, digest
from generation.representation.verifier import CATEGORIES, Dafny
from repair.verifier import classify


DEFAULT_BUDGET = {'max_model_actions':12,'max_verifier_checks':12,'max_output_tokens':16384,
                  'max_total_tokens':240000,'model_timeout':900,'verifier_timeout':120,
                  'session_timeout':10800}


def _write(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2),encoding='utf-8')


def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError('duplicate JSON object key')
        result[key]=value
    return result


def _ledger_rows(report, editable=(), frozen_ids=None, initial=False):
    rows=[]
    for position, row in enumerate(report['declarations']):
        dependencies = row.get('depends_on',[])
        if initial and row['id'] in editable:
            dependencies = [binding.split(':member:',1)[1] for binding in row.get('contract_bindings',[])
                            if ':member:' in binding]
        rows.append({'id':row['id'],'name':row['name'],'kind':row['kind'],
                     'order':position,'depends_on':sorted(set(dependencies)),
                     'editable':row['id'] in editable or (frozen_ids is not None and row['id'] not in frozen_ids)})
    return rows


def _diagnostics(report, source, structure, primary):
    rows=[]
    for item in report.get('diagnostics',[]):
        row=deepcopy(item)
        target=primary
        line=item.get('location_line')
        if isinstance(line,int) and line>0:
            prefix=''.join(source.splitlines(keepends=True)[:line-1])
            position=len(prefix.encode('utf-16-le'))//2
            for declaration in structure.get('declarations',[]):
                lo,hi=declaration.get('source_region',[-1,-1])
                if lo<=position<hi:
                    target=declaration['id']; break
        row.update(target=target,category=CATEGORIES.get(item.get('subtype'),'unknown'))
        rows.append(row)
    if report.get('status') in {'parse_error','resolution_error'}:
        rows.append({'target':primary,'category':'parse_error' if report['status']=='parse_error' else 'type_error'})
    return rows


def _verification(raw, primary):
    """Reclassify whole-file output; names=() in the reused adapter is conservative."""
    evidence=raw.to_dict() if hasattr(raw,'to_dict') else deepcopy(raw)
    evidence['adapter_status']=evidence.get('status')
    csv_obligations={}
    try:
        for row in csv.DictReader(evidence.get('csv_log','').splitlines()):
            name=row.get('TestResult.DisplayName')
            if name:
                csv_obligations[name]='unknown' if name in csv_obligations else row.get('TestResult.Outcome','').lower()
    except (csv.Error,AttributeError):
        csv_obligations={}
    evidence['csv_matches_obligations']=bool(csv_obligations) and csv_obligations==evidence.get('obligations',{})
    if evidence.get('status') in {'timeout','tool_error'}:
        return evidence
    status=classify(evidence.get('stdout','')+evidence.get('stderr',''),
                    evidence.get('returncode'),evidence.get('obligations',{}))
    evidence['status']={'passed':'verified','compile_error':'parse_error'}.get(status,status)
    names=set(primary.get('verifier_names',[]))|{primary['id'],primary['name']}
    allowed={'correctness'} if primary['kind'] in {'method','lemma'} else {'correctness','well-formedness'}
    primary_batches=[(name,value) for name,value in evidence.get('obligations',{}).items()
                     if any(name==base+' ('+suffix+')' for base in names for suffix in allowed)]
    evidence['primary_batches']=dict(primary_batches)
    if evidence['status']=='verified' and (not evidence.get('executed') or not evidence.get('real_verifier')
            or evidence.get('returncode')!=0 or not evidence['csv_matches_obligations'] or not primary_batches
            or any(value!='passed' for _,value in primary_batches)):
        evidence['status']='unknown'
    return evidence


def _resume(root, manifest):
    required=[root/'manifest.json',root/'result.json',root/'result.sha256']
    if not all(path.is_file() for path in required):
        raise FileExistsError('unfinished trial directory exists; refusing replacement')
    existing=json.loads(required[0].read_text(encoding='utf-8'))
    if existing!=manifest:
        raise ValueError('existing trial manifest differs')
    result=json.loads(required[1].read_text(encoding='utf-8'))
    if not result.get('complete') or digest(canonical(result))!=required[2].read_text().strip():
        raise ValueError('completed trial result integrity check failed')
    if result.get('manifest_sha256')!=digest(canonical(manifest)):
        raise ValueError('result manifest identity differs')
    for relative, expected in result.get('artifact_sha256',{}).items():
        path=(root/relative).resolve()
        if root not in path.parents or not path.is_file() or digest(path.read_text(encoding='utf-8'))!=expected:
            raise ValueError('saved trial artifact integrity check failed')
    return result


def run_trial(task, frozen_structure, editable_ids, model, output_dir, arm, replicate=0, budget=None):
    if arm not in 'ABCD' or len(arm)!=1:
        raise ValueError('arm must be A, B, C, or D')
    if type(replicate) is not int or replicate<0:
        raise ValueError('nonnegative replicate required')
    limits={**DEFAULT_BUDGET,**(budget or {})}
    if set(limits)!=set(DEFAULT_BUDGET) or any(type(v) not in {int,float} or not math.isfinite(v) or v<=0 or v>DEFAULT_BUDGET[k] for k,v in limits.items()):
        raise ValueError('invalid or above-protocol budget')
    if any(type(limits[k]) is not int for k in ('max_model_actions','max_verifier_checks','max_output_tokens','max_total_tokens')):
        raise ValueError('action and token limits must be integers')
    if frozen_structure.get('status')!='ok' or not frozen_structure.get('trusted_ast'):
        raise ValueError('trusted frozen structure required')
    declarations={row['id']:row for row in frozen_structure['declarations']}
    if not set(editable_ids)<=declarations.keys() or not editable_ids:
        raise ValueError('editable declarations must be frozen AST identities')
    primary=next((row for row in declarations.values() if row['name']==task.target_name),None)
    if primary is None or primary['id'] not in editable_ids:
        raise ValueError('primary target missing from editable declarations')
    root=Path(output_dir).resolve()
    verifier=Dafny(timeout=limits['verifier_timeout'])
    model_identity=model.identity()
    verifier_identity=verifier.identity()
    manifest={'schema_version':1,'task':task.manifest(),'frozen_structure_sha256':digest(canonical(frozen_structure)),
              'editable_ids':sorted(editable_ids),'model':model_identity,'verifier':verifier_identity,
              'arm':arm,'replicate':replicate,'budget':limits,
              'runner_sha256':digest(Path(__file__).read_text(encoding='utf-8')),
              'protocol_deviations':{'generation_output_cap_enforced':False,'external_model_retries':0,
                                     'unknown_usage':'terminal infrastructure failure; no zero imputation'}}
    if root.exists():
        return _resume(root,manifest)
    root.mkdir(parents=True)
    _write(root/'manifest.json',manifest)
    started=time.monotonic()
    ledger=EvidenceLedger(_ledger_rows(frozen_structure,editable_ids,declarations,initial=True))
    current=task.skeleton
    current_structure=frozen_structure
    ledger.begin(digest(current))
    result={'schema_version':1,'task_id':task.id,'family_id':task.family_id,'arm':arm,'replicate':replicate,
            'model':model_identity.get('model',model_identity.get('name','unknown')),'model_identity':model_identity,
            'research_eligible':model_identity.get('kind')=='live' and verifier_identity.get('real_verifier') is True,
            'complete':False,'success':False,'stop_reason':None,'model_calls':0,'verifier_calls':0,
            'verifier_requests':0,'real_verifier_calls':0,'input_tokens':0,'output_tokens':0,'total_tokens':0,
            'usage_complete':True,'seconds':0,'verifier_seconds':0,'rounds':[],
            'manifest_sha256':digest(canonical(manifest))}
    history=[]
    cache={}
    artifacts=[]

    def save_round(folder,row):
        _write(folder/'round.json',row)
        artifacts.append(folder/'round.json')
        _write(root/'progress.json',result)

    try:
        while result['model_calls']<limits['max_model_actions']:
            remaining=limits['session_timeout']-(time.monotonic()-started)
            if remaining<=0:
                result['stop_reason']='session_timeout'; break
            if result['total_tokens']>=limits['max_total_tokens']:
                result['stop_reason']='session_token_budget'; break
            if result['verifier_calls']>=limits['max_verifier_checks']:
                result['stop_reason']='verifier_budget'; break
            number=result['model_calls']+1
            folder=root/f'round-{number:02d}'; folder.mkdir()
            target=choose_target(ledger,arm)
            structural_target=choose_target(ledger,'C')
            evidence_target=choose_target(ledger,'D')
            open_editable=[k for k,v in ledger.rows.items() if v.get('editable',True) and v['status']!='closed']
            messages=build_messages(task.public(),current,history,ledger,arm)
            payload=json.loads(messages[-1]['content'])
            payload['parsed_declarations']=_ledger_rows(current_structure,editable_ids,declarations)
            messages[-1]['content']=json.dumps(payload,ensure_ascii=False,sort_keys=True)
            ledger.record_action(target['id'] if target else None)
            _write(folder/'messages.json',messages); artifacts.append(folder/'messages.json')
            row={'action':number,'selected_target':target,'source_before_sha256':digest(current),
                 'scheduler_audit':{'open_editable_targets':open_editable,
                     'structural_target':structural_target,'evidence_target':evidence_target,
                     'target_disagreement':(structural_target or {}).get('id')!=(evidence_target or {}).get('id')},
                 'changed_declarations':[],'guard_findings':[],'verification':None}
            result['rounds'].append(row)
            result['model_calls']+=1
            generation=model.generate(messages,folder/'model',timeout=min(limits['model_timeout'],remaining),
                                      max_output_tokens=limits['max_output_tokens'])
            row['generation']=generation
            _write(folder/'generation.json',generation); artifacts.append(folder/'generation.json')
            for name in ('request.json','prompt.txt','stdout.jsonl','stderr.txt','result.json'):
                path=folder/'model'/name
                if path.exists(): artifacts.append(path)
            known=all(type(generation.get(key)) is int and generation[key]>=0 for key in ('input_tokens','output_tokens'))
            if known:
                result['input_tokens']+=generation['input_tokens']; result['output_tokens']+=generation['output_tokens']
                result['total_tokens']=result['input_tokens']+result['output_tokens']
            else:
                result['usage_complete']=False
            if generation.get('error') or not generation.get('executed'):
                result['stop_reason']='model_infrastructure_failure'; save_round(folder,row); break
            if not known:
                result['stop_reason']='unknown_model_usage'; save_round(folder,row); break
            if generation['output_tokens']>limits['max_output_tokens']:
                result['stop_reason']='output_token_budget'; save_round(folder,row); break
            if result['total_tokens']>limits['max_total_tokens']:
                result['stop_reason']='session_token_budget'; save_round(folder,row); break
            try:
                candidate=json.loads(generation.get('text',''),object_pairs_hook=_unique_object)
                source=task.assemble(candidate)
            except (ValueError,TypeError):
                row['guard_findings']=[{'code':'invalid_candidate_json','message':'Exact implementation/helpers JSON required.'}]
                history.append({'action':number,'model_output':generation.get('text',''),'feedback':row['guard_findings']})
                ledger.diagnostics=[{'category':'parse_error','target':primary['id']}]
                save_round(folder,row); continue
            candidate_hash=digest(source)
            row['candidate_sha256']=candidate_hash
            (folder/'candidate.dfy').write_bytes(source.encode('utf-8')); artifacts.append(folder/'candidate.dfy')
            inspection=inspect_source(source)
            _write(folder/'structure.json',inspection); artifacts.append(folder/'structure.json')
            findings=compare_frozen(frozen_structure,inspection,editable_ids)
            row['guard_findings']=findings+inspection.get('findings',[])
            before={d['id']:d.get('tokens') for d in current_structure['declarations']}
            row['changed_declarations']=[d['id'] for d in inspection.get('declarations',[]) if before.get(d['id'])!=d.get('tokens')]
            row['target_followed']=target is None or target['id'] in row['changed_declarations']
            current=source
            ledger.begin(candidate_hash)
            if inspection.get('status')=='tool_error':
                result['stop_reason']='structure_infrastructure_failure'; save_round(folder,row); break
            if findings or inspection.get('status')!='ok' or not inspection.get('trusted_ast') or inspection.get('findings'):
                ledger.diagnostics=_diagnostics(inspection,source,current_structure,primary['id']) or [{'category':'parse_error','target':primary['id']}]
                history.append({'action':number,'model_output':generation.get('text',''),'source':source,
                                'structure':inspection,'guard_findings':row['guard_findings']})
                save_round(folder,row); continue
            current_structure=inspection
            ledger.update_structure(_ledger_rows(inspection,editable_ids,declarations))
            remaining=limits['session_timeout']-(time.monotonic()-started)
            if remaining<=0:
                result['stop_reason']='session_timeout'; save_round(folder,row); break
            result['verifier_requests']+=1
            row['verification_cache_hit']=candidate_hash in cache
            if candidate_hash in cache:
                verification=deepcopy(cache[candidate_hash])
            else:
                result['verifier_calls']+=1
                verification=_verification(verifier.verify(source,names=(),timeout=min(limits['verifier_timeout'],remaining)),primary)
                result['verifier_seconds']+=verification.get('seconds',0)
                result['real_verifier_calls']+=int(bool(verification.get('executed') and verification.get('real_verifier')))
                cache[candidate_hash]=deepcopy(verification)
            row['verification']=verification
            _write(folder/'verification.json',verification); artifacts.append(folder/'verification.json')
            for name,key in [('verifier.stdout.txt','stdout'),('verifier.stderr.txt','stderr'),('verifier.csv','csv_log')]:
                path=folder/name; path.write_text(verification.get(key,''),encoding='utf-8'); artifacts.append(path)
            diagnostics=_diagnostics(verification,source,inspection,primary['id'])
            ledger.observe(candidate_hash,declaration_outcomes(inspection,verification),diagnostics)
            row['ledger_after']=ledger.snapshot()
            history.append({'action':number,'model_output':generation.get('text',''),'source':source,
                            'structure':inspection,'guard_findings':[],'verification':verification})
            if time.monotonic()-started>limits['session_timeout']:
                result['stop_reason']='session_timeout'; save_round(folder,row); break
            if verification.get('status')=='verified':
                result.update(success=True,stop_reason='verified',successful_action=number,
                              accepted_candidate_sha256=candidate_hash)
                save_round(folder,row); break
            if not verification.get('executed') or not verification.get('real_verifier') or verification.get('status')=='tool_error':
                result['stop_reason']='verifier_infrastructure_failure'; save_round(folder,row); break
            save_round(folder,row)
        if result['stop_reason'] is None:
            result['stop_reason']='model_action_budget'
    except Exception as exc:
        result.update(stop_reason='runner_infrastructure_failure',infrastructure_exception_type=type(exc).__name__)
    result.update(complete=True,seconds=time.monotonic()-started,ledger_metrics=ledger.metrics,
                  output_cap_enforced=False,artifact_sha256={str(path.relative_to(root)):digest(path.read_text(encoding='utf-8')) for path in artifacts})
    _write(root/'result.json',result)
    (root/'result.sha256').write_text(digest(canonical(result))+'\n',encoding='utf-8')
    return result
