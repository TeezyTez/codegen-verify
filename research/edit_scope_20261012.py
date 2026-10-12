"""Exploratory same-state edit-scope experiment; independent of main-v3.

Reference proofs are used only in preflight, never in model prompts.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from generation.public_benchmark.structure import inspect_source,compare_frozen,_tokens
from generation.public_benchmark.model import CodexModel
from generation.public_benchmark.runner import _unique_object
from generation.representation.verifier import Dafny

CODE=('init','condition','step','finish')
LISTS=('invariants','before_loop','after_loop')
KEYS=set(CODE+LISTS+('decreases',))
BUDGET={'actions':3,'verifier_checks':3,'model_timeout':300,'verifier_timeout':30,
        'max_output_tokens':8192,'max_total_tokens':90000}


def sha(s):return hashlib.sha256(s.encode('utf-8')).hexdigest()
def save(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def tok(s):return list(_tokens(s))


def model_feedback(evaluation):
    """Only task-relevant feedback crosses the model boundary; raw logs stay local."""
    verification=evaluation.get('verification')
    return {'findings':evaluation.get('findings',[]),
            'verification':None if verification is None else
            {k:verification[k] for k in ('status','diagnostics','obligations') if k in verification}}


def infrastructure_failure(evaluation):
    return any((evaluation.get(k) or {}).get('status') in {'tool_error','unknown'}
               for k in ('structure','verification'))


def candidate(init,condition,step,invariants,decreases,finish=''):
    return dict(init=init,condition=condition,step=step,finish=finish,invariants=invariants,
                decreases=decreases,before_loop=[],after_loop=[])


def make_tasks():
    tasks=[]
    def add(ident,desc,header,ref,initial_invariants):
        initial=deepcopy(ref);initial['invariants']=initial_invariants
        tasks.append(dict(id=ident,family='power_sums' if ident in {'S01','S02','S03'} else ident,description=desc,header=header,initial=initial,
                          reference=ref,cohort='correct_body',witness=None))
    add('S01','Return the sum of integers from 1 to n.',
        'method Solve(n:int) returns (s:int)\nrequires n >= 0\nensures 2*s == n*(n+1)',
        candidate('var i := 0; s := 0;','i < n','i := i + 1; s := s + i;',
                  ['0 <= i <= n','2*s == i*(i+1)'],'n-i'),['0 <= i <= n'])
    add('S02','Return the sum of squares of integers from 1 to n.',
        'method Solve(n:int) returns (s:int)\nrequires n >= 0\nensures 6*s == n*(n+1)*(2*n+1)',
        candidate('var i := 0; s := 0;','i < n','i := i + 1; s := s + i*i;',
                  ['0 <= i <= n','6*s == i*(i+1)*(2*i+1)'],'n-i'),['0 <= i <= n'])
    add('S03','Return the sum of cubes of integers from 1 to n.',
        'method Solve(n:int) returns (s:int)\nrequires n >= 0\nensures 4*s == n*n*(n+1)*(n+1)',
        candidate('var i := 0; s := 0;','i < n','i := i + 1; s := s + i*i*i;',
                  ['0 <= i <= n','4*s == i*i*(i+1)*(i+1)'],'n-i'),['0 <= i <= n'])
    add('S04','Compute quotient and remainder of nonnegative a by positive b.',
        'method Solve(a:int,b:int) returns (q:int,r:int)\nrequires a >= 0 && b > 0\nensures a == q*b+r && q >= 0 && 0 <= r < b',
        candidate('q := 0; r := a;','r >= b','r := r-b; q := q+1;',
                  ['a == q*b+r','q >= 0','r >= 0'],'r'),['r >= 0'])
    add('S05','Create a fresh array containing the input elements in reverse order.',
        'method Solve(a:array<int>) returns (b:array<int>)\nensures b.Length == a.Length\nensures forall k :: 0 <= k < a.Length ==> b[k] == a[a.Length-1-k]',
        candidate('b := new int[a.Length]; var i := 0;','i < a.Length','b[i] := a[a.Length-1-i]; i := i+1;',
                  ['0 <= i <= a.Length','b.Length == a.Length','forall k :: 0 <= k < i ==> b[k] == a[a.Length-1-k]'],'a.Length-i'),
        ['0 <= i <= a.Length','b.Length == a.Length'])
    add('S06','Return a maximum element of a nonempty integer array.',
        'method Solve(a:array<int>) returns (m:int)\nrequires a.Length > 0\nensures forall k :: 0 <= k < a.Length ==> a[k] <= m\nensures exists k :: 0 <= k < a.Length && a[k] == m',
        candidate('m := a[0]; var i := 1;','i < a.Length','if a[i] > m { m := a[i]; } i := i+1;',
                  ['1 <= i <= a.Length','forall k :: 0 <= k < i ==> a[k] <= m','exists k :: 0 <= k < i && a[k] == m'],'a.Length-i'),['1 <= i <= a.Length'])
    add('S07','Find an occurrence of x, or return -1 if x is absent.',
        'method Solve(a:array<int>,x:int) returns (p:int)\nensures -1 <= p < a.Length\nensures p >= 0 ==> a[p] == x\nensures p == -1 ==> forall k :: 0 <= k < a.Length ==> a[k] != x',
        candidate('var i := 0; p := -1;','i < a.Length && p == -1','if a[i] == x { p := i; } i := i+1;',
                  ['0 <= i <= a.Length','-1 <= p < i','p >= 0 ==> a[p] == x',
                   'p == -1 ==> forall k :: 0 <= k < i ==> a[k] != x'],'a.Length-i'),['0 <= i <= a.Length','-1 <= p < i'])
    add('S08','Return the floor of the square root of nonnegative n.',
        'method Solve(n:int) returns (r:int)\nrequires n >= 0\nensures r >= 0 && r*r <= n < (r+1)*(r+1)',
        candidate('r := 0;','(r+1)*(r+1) <= n','r := r+1;',
                  ['r >= 0','r*r <= n'],'n-r*r'),['r >= 0'])
    for i,field,value,header,proof in [
        (0,'step','i := i+1; s := s+i+1;',
         'method Solve(n:int) returns (s:int)\nrequires n == 2\nensures s == 5',
         ['0 <= i <= n','2*s == i*(i+3)']),
        (3,'init','q := 1; r := a;',
         'method Solve(a:int,b:int) returns (q:int,r:int)\nrequires a == 5 && b == 2\nensures q == 3 && r == 1',
         ['a == (q-1)*b+r','q >= 1','r >= 0']),
        (4,'step','b[i] := a[i]; i := i+1;',
         'method Solve(a:array<int>) returns (b:array<int>)\nrequires a.Length == 2 && a[0] == 1 && a[1] == 2\nensures b.Length == 2 && b[0] == 1 && b[1] == 2',
         ['0 <= i <= a.Length','b.Length == a.Length','forall k :: 0 <= k < i ==> b[k] == a[k]']),
        (5,'step','if a[i] < m { m := a[i]; } i := i+1;',
         'method Solve(a:array<int>) returns (m:int)\nrequires a.Length == 2 && a[0] == 1 && a[1] == 3\nensures m == 1',
         ['1 <= i <= a.Length','forall k :: 0 <= k < i ==> m <= a[k]','exists k :: 0 <= k < i && a[k] == m']),
    ]:
        wrong=deepcopy(tasks[i]);wrong['id']+='X';wrong['cohort']='bug_calibration';wrong['initial'][field]=value
        witness=deepcopy(wrong['initial']);witness['invariants']=proof
        wrong['witness']={'header':header,'candidate':witness,'meaning':'Concrete output violates original contract; this separate diagnostic contract is never a candidate solution.'}
        tasks.append(wrong)
    return tasks


def validate_candidate(task,c,arm):
    if not isinstance(c,dict) or set(c)!=KEYS:return ['schema']
    if any(not isinstance(c[k],str) for k in CODE+('decreases',)):return ['schema']
    if any(not isinstance(c[k],list) or any(not isinstance(x,str) for x in c[k]) for k in LISTS):return ['schema']
    failures=[]
    if arm=='P' and any(tok(c[k])!=tok(task['initial'][k]) for k in CODE):failures.append('executable_edit')
    exprs=[c['condition'],c['decreases']]+sum((c[k] for k in LISTS),[])
    if any(not e.strip() or any(x in e for x in (';','{','}','//','/*','*/',':=')) for e in exprs):failures.append('expression_injection')
    all_tokens=tok(' '.join(c[k] for k in CODE+('decreases',))+' '+' '.join(sum((c[k] for k in LISTS),[])))
    if set(all_tokens)&{'assume','expect','include','import','while','for','method','function','lemma','predicate','yield','modify','calc'}:
        failures.append('unsupported_construct')
    if '*' in tok(c['decreases']):failures.append('decreases_wildcard')
    # A multiplication in a decreases expression is legal; only wildcard is forbidden.
    if c['decreases'].strip()!='*' and 'decreases_wildcard' in failures:failures.remove('decreases_wildcard')
    return failures


def assemble(task,c):
    assertion=lambda xs:'\n'.join('assert ('+x+');' for x in xs)
    return task['header']+'\n{\n'+c['init']+'\n'+assertion(c['before_loop'])+'\nwhile ('+c['condition']+')\n'+''.join('invariant ('+x+')\n' for x in c['invariants'])+'decreases ('+c['decreases']+')\n{\n'+c['step']+'\n}\n'+assertion(c['after_loop'])+'\n'+c['finish']+'\n}\n'


def checked_verify(task,c,frozen,arm,verifier):
    findings=validate_candidate(task,c,arm)
    source=assemble(task,c) if not findings else None
    structure=None;verification=None
    if not findings:
        structure=inspect_source(source)
        findings+=compare_frozen(frozen,structure,editable_ids=['Solve'])
        if structure.get('status')=='ok' and {d['id'] for d in structure['declarations']}!={'Solve'}:findings.append('extra_declaration')
    if not findings:verification=verifier.verify(source,names=['Solve'],timeout=BUDGET['verifier_timeout']).to_dict()
    return dict(findings=findings,source=source,structure=structure,verification=verification)


def preflight_one(task,root):
    out=root/'preflight'/task['id'];out.mkdir(parents=True,exist_ok=False)
    verifier=Dafny(timeout=BUDGET['verifier_timeout'])
    ref=assemble(task,task['reference']);initial=assemble(task,task['initial'])
    frozen=inspect_source(ref)
    rr=verifier.verify(ref,names=['Solve']).to_dict() if frozen.get('status')=='ok' else {'status':'guard_failure'}
    ir=checked_verify(task,task['initial'],frozen,'J',verifier)
    (out/'reference.dfy').write_text(ref,encoding='utf-8');(out/'initial.dfy').write_text(initial,encoding='utf-8')
    result={'id':task['id'],'reference':rr,'initial':ir,'witness':None}
    if task['witness']:
        ws=assemble({'header':task['witness']['header']},task['witness']['candidate'])
        (out/'witness.dfy').write_text(ws,encoding='utf-8')
        result['witness']=verifier.verify(ws,names=['Solve']).to_dict()
    result['admitted']=(rr['status']=='verified' and not ir['findings'] and ir['verification']['status']=='verification_failed'
                         and (result['witness'] is None or result['witness']['status']=='verified'))
    save(out/'result.json',result)
    return task,result


def prepare(root):
    root.mkdir(parents=True,exist_ok=False)
    designed=make_tasks();save(root/'designed_tasks.json',designed)
    results=[]
    with ThreadPoolExecutor(max_workers=4) as ex:
        fs=[ex.submit(preflight_one,t,root) for t in designed]
        for f in as_completed(fs):
            t,r=f.result();results.append((t,r))
            print('PREFLIGHT',t['id'],r['admitted'],r['reference']['status'],
                  (r['initial']['verification'] or {}).get('status'),(r['witness'] or {}).get('status'),flush=True)
    admitted=[t for t,r in sorted(results,key=lambda x:x[0]['id']) if r['admitted']]
    save(root/'tasks.json',admitted)
    rng=random.Random(20261012);blocks=[(t['id'],rep) for t in admitted for rep in range(3)];rng.shuffle(blocks)
    jobs=[]
    for tid,rep in blocks:
        arms=['P','J'];rng.shuffle(arms)
        for arm in arms:jobs.append(dict(index=len(jobs),task_id=tid,replicate=rep,arm=arm))
    save(root/'jobs.json',jobs)
    sources=['research/edit_scope_20261012.py','research/EDIT_SCOPE_PROTOCOL_2026_10_12.md',
             'generation/public_benchmark/model.py','generation/public_benchmark/structure.py','generation/public_benchmark/structure_bridge.cs',
             'generation/public_benchmark/structure_bridge.ps1','generation/public_benchmark/runner.py',
             'generation/representation/verifier.py','repair/verifier.py']
    manifest={'stage':'development_exploratory','seed':20261012,'budget':BUDGET,'expected_sessions':len(jobs),'designed_states':len(designed),
              'admitted_states':len(admitted),'cohort_counts':dict(Counter(t['cohort'] for t in admitted)),
              'source_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},
              'tasks_sha256':hashlib.sha256((root/'tasks.json').read_bytes()).hexdigest(),
              'jobs_sha256':hashlib.sha256((root/'jobs.json').read_bytes()).hexdigest(),
              'verifier':Dafny(timeout=30).identity(),'model':{'requested':'gpt-6-astra','effort':'high','backend_identity':'not independently guaranteed'},
              'excluded_states':[{'id':t['id'],'reference':r['reference']['status'],'initial':(r['initial']['verification'] or {}).get('status'),'witness':(r['witness'] or {}).get('status')} for t,r in results if not r['admitted']]}
    save(root/'manifest.json',manifest);print('FROZEN',len(admitted),len(jobs),flush=True)


SYSTEM='''Repair the supplied single-loop Dafny program so that its entire fixed contract verifies. Return only an exact JSON object using the supplied slots. Do not call tools. No reference solution is provided. Never change the signature, requires, ensures, add assumptions, attributes, declarations or extra loops. Expressions in invariant/assertion/decreases slots must be pure expressions, not statements. Both proof and permitted implementation choices should aim at verification within the remaining budget. A verifier failure is not by itself a semantic counterexample.'''


def build_messages(task,current,feedback,history,arm,action):
    restriction=('init, condition, step and finish must retain exactly the original executable tokens. Only proof annotations and decreases may change.'
                 if arm=='P' else 'You may change init, condition, step and finish, or retain them. You may also change proof annotations and decreases.')
    payload={'description':task['description'],'fixed_header':task['header'],'original_slots':task['initial'],
             'current_slots':current,'current_source':assemble(task,current),'feedback':feedback,'edit_scope':restriction,
             'output_keys':sorted(KEYS),'slot_types':{'strings':list(CODE)+['decreases'],'expression_lists':list(LISTS)},
             'placement':'before_loop assertions after init; after_loop assertions before finish; no assertion slot within step in proof-only scope',
             'history':history,'remaining_model_calls':BUDGET['actions']-action+1}
    return [{'role':'system','content':SYSTEM},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]


def run_one(root,task,job,model):
    folder=root/'runs'/f"{job['index']:04d}_{job['task_id']}_{job['arm']}_{job['replicate']}"
    folder.mkdir(parents=True,exist_ok=False)
    pre=load(root/'preflight'/task['id']/'result.json')
    current=deepcopy(task['initial']);feedback=model_feedback(pre['initial'])
    history=[];verifier=Dafny(timeout=30)
    frozen=pre['initial']['structure'];start=time.monotonic()
    result={**job,'family':task['family'],'cohort':task['cohort'],'success':False,'stop_reason':'action_budget',
            'model_attempts':0,'model_processes_started':0,'model_responses_completed':0,'unknown_usage_attempts':0,
            'verifier_calls':0,'input_tokens':0,'output_tokens':0,'usage_complete':True,'rounds':[]}
    for action in range(1,BUDGET['actions']+1):
        rd=folder/f'round-{action:02d}';rd.mkdir()
        messages=build_messages(task,current,feedback,history,job['arm'],action)
        save(rd/'messages.json',messages)
        gen=model.generate(messages,rd/'model',timeout=BUDGET['model_timeout'],max_output_tokens=BUDGET['max_output_tokens'])
        result['model_attempts']+=1
        result['model_processes_started']+=int(bool(gen.get('executed')))
        result['model_responses_completed']+=int(bool(gen.get('executed')) and not gen.get('error'))
        row={'action':action,'generation':gen,'evaluation':None,'executable_changed':None};result['rounds'].append(row)
        known=all(type(gen.get(k)) is int for k in ('input_tokens','output_tokens'))
        if known:
            result['input_tokens']+=gen['input_tokens'];result['output_tokens']+=gen['output_tokens']
        else:
            result['usage_complete']=False;result['unknown_usage_attempts']+=1
        if gen.get('error') or not gen.get('executed'):
            result['stop_reason']='model_infrastructure_failure';save(rd/'round.json',row);break
        if not known or gen['output_tokens']>BUDGET['max_output_tokens'] or result['input_tokens']+result['output_tokens']>BUDGET['max_total_tokens']:
            result['stop_reason']='usage_or_token_threshold';save(rd/'round.json',row);break
        try:
            c=json.loads(gen['text'],object_pairs_hook=_unique_object)
            evaluation=checked_verify(task,c,frozen,job['arm'],verifier)
        except (ValueError,TypeError) as error:
            evaluation={'findings':['invalid_json_or_schema:'+str(error)],'source':None,'structure':None,'verification':None};c=None
        row['evaluation']=evaluation
        if evaluation['source']:(rd/'candidate.dfy').write_text(evaluation['source'],encoding='utf-8')
        if evaluation.get('verification') is not None:result['verifier_calls']+=1
        if infrastructure_failure(evaluation):
            result['stop_reason']='verification_infrastructure_failure';save(rd/'round.json',row);break
        if not evaluation['findings']:
            row['executable_changed']=any(tok(c[k])!=tok(task['initial'][k]) for k in CODE)
            current=c
            if evaluation['verification']['status']=='verified':
                result.update(success=True,successful_action=action,stop_reason='verified')
        feedback=model_feedback(evaluation)
        history.append({'response':gen['text'],'feedback':feedback})
        save(rd/'round.json',row)
        if result['success']:break
    result['seconds']=time.monotonic()-start
    result['artifacts']={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file() and p.name in {'round.json','candidate.dfy','messages.json','request.json','stdout.jsonl','stderr.txt'}}
    save(folder/'result.json',result)
    (folder/'result.sha256').write_text(hashlib.sha256((folder/'result.json').read_bytes()).hexdigest(),encoding='ascii')
    return result


def run(root,workers):
    manifest=load(root/'manifest.json')
    for p,h in manifest['source_hashes'].items():
        if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h:raise ValueError('frozen source changed: '+p)
    for name in ('tasks','jobs'):
        if hashlib.sha256((root/f'{name}.json').read_bytes()).hexdigest()!=manifest[name+'_sha256']:raise ValueError('roster drift')
    jobs=load(root/'jobs.json');tasks={t['id']:t for t in load(root/'tasks.json')}
    if (root/'runs').exists():raise FileExistsError('No implicit rerun/resume allowed')
    model=CodexModel(model='gpt-6-astra',effort='high',codex_home='C:/Users/16039/.codex',proxy='http://127.0.0.1:10808')
    save(root/'model_identity.json',model.identity())
    rows=[]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fs=[ex.submit(run_one,root,tasks[j['task_id']],j,model) for j in jobs]
        for f in as_completed(fs):
            r=f.result();rows.append(r)
            save(root/'progress.json',{'completed':len(rows),'expected':len(jobs),'successes':sum(x['success'] for x in rows),'model_attempts':sum(x['model_attempts'] for x in rows)})
            print('DONE',len(rows),'/',len(jobs),r['task_id'],r['arm'],r['replicate'],r['success'],r['stop_reason'],flush=True)
    analyze(root)


def analyze(root):
    rows=[]
    for f in sorted((root/'runs').glob('*/result.json')):
        r=load(f)
        if hashlib.sha256(f.read_bytes()).hexdigest()!=(f.parent/'result.sha256').read_text():raise ValueError('result drift')
        for p,h in r['artifacts'].items():
            if hashlib.sha256((f.parent/p).read_bytes()).hexdigest()!=h:raise ValueError('artifact drift')
        rows.append(r)
    jobs=load(root/'jobs.json');identity=lambda r:(r['task_id'],r['arm'],r['replicate'])
    if len(rows)!=len(jobs) or {identity(r) for r in rows}!={identity(j) for j in jobs}:raise ValueError('incomplete matrix')
    cohorts={};tables=[]
    for cohort in ('correct_body','bug_calibration'):
        rr=[r for r in rows if r['cohort']==cohort];arms={}
        for arm in ('P','J'):
            ss=[r for r in rr if r['arm']==arm]
            arms[arm]={'sessions':len(ss),'successes':sum(r['success'] for r in ss),'first_action_successes':sum(r.get('successful_action')==1 for r in ss),
                       'model_attempts':sum(r['model_attempts'] for r in ss),'verifier_calls':sum(r['verifier_calls'] for r in ss),
                       'input_tokens':sum(r['input_tokens'] for r in ss),'output_tokens':sum(r['output_tokens'] for r in ss),
                       'usage_complete':all(r['usage_complete'] for r in ss),
                       'unknown_usage_attempts':sum(r['unknown_usage_attempts'] for r in ss),
                       'model_processes_started':sum(r['model_processes_started'] for r in ss),
                       'model_responses_completed':sum(r['model_responses_completed'] for r in ss),
                       'stop_reasons':dict(Counter(r['stop_reason'] for r in ss)),
                       'sessions_with_executable_edit':sum(any(x['executable_changed'] for x in r['rounds']) for r in ss)}
        pairs=[]
        for tid in sorted({r['task_id'] for r in rr}):
            per={arm:[r for r in rr if r['task_id']==tid and r['arm']==arm] for arm in ('P','J')}
            pairs.append({'task_id':tid,'P_success':sum(r['success'] for r in per['P']),'J_success':sum(r['success'] for r in per['J']),
                          'repeats':len(per['P']),'P_calls':sum(r['model_attempts'] for r in per['P']),'J_calls':sum(r['model_attempts'] for r in per['J'])})
        cohorts[cohort]={'arms':arms,'task_pairs':pairs,'inference':'Exploratory authored states; no population superiority or equivalence claim'}
    summary={'expected':len(jobs),'completed':len(rows),'model_attempts':sum(r['model_attempts'] for r in rows),'cohorts':cohorts,'usage_complete':all(r['usage_complete'] for r in rows),
             'unknown_usage_attempts':sum(r['unknown_usage_attempts'] for r in rows),
             'model_processes_started':sum(r['model_processes_started'] for r in rows),
             'model_responses_completed':sum(r['model_responses_completed'] for r in rows),
             'limitations':['Authored developmental states, not independent natural failure distribution.','Joint search includes proof-only edits.','Calibration defects cannot establish novel routing benefit.','Paired prompt state but model RNG unpaired; three repeats are exploratory.','Requested model identity; unknown backend identity.']}
    save(root/'summary.json',summary)
    lines=['# 编辑范围开发实验结果','',f"完成 {len(rows)}/{len(jobs)} 个会话；模型调用尝试 {summary['model_attempts']} 次。",'']
    lines += [f"启动进程 {summary['model_processes_started']} 次；无错误响应 {summary['model_responses_completed']} 次；用量未知 {summary['unknown_usage_attempts']} 次。token 合计在用量不完整时仅为已知下界。",'']
    for cohort,data in cohorts.items():
        lines += ['## '+cohort,'','| 组 | 成功/会话 | 首轮成功 | 调用尝试 | 验证调用 | 主体发生改动的会话 |','|---|---:|---:|---:|---:|---:|']
        for arm,d in data['arms'].items():lines.append(f"| {arm} | {d['successes']}/{d['sessions']} | {d['first_action_successes']} | {d['model_attempts']} | {d['verifier_calls']} | {d['sessions_with_executable_edit']} |")
        lines+=['','| 任务 | P 成功 | J 成功 | 重复 | P 调用 | J 调用 |','|---|---:|---:|---:|---:|---:|']
        for d in data['task_pairs']:lines.append('| '+' | '.join(str(d[k]) for k in ('task_id','P_success','J_success','repeats','P_calls','J_calls'))+' |')
        lines+=['','停止原因：'+json.dumps({a:d['stop_reasons'] for a,d in data['arms'].items()},ensure_ascii=False),'']
    (root/'results.md').write_text('\n'.join(lines),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','run','analyze']);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--workers',type=int,default=8)
    a=parser.parse_args();out=a.output.resolve()
    if ROOT not in out.parents:raise ValueError('output must be within repository')
    if a.command=='prepare':prepare(out)
    elif a.command=='run':run(out,a.workers)
    else:analyze(out)
