"""Public-program edit-scope development experiment, separate from prior snapshots."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from collections import Counter
import hashlib,json,random,re,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from research.edit_scope_20261012 import save,load,model_feedback,infrastructure_failure
from generation.public_benchmark.structure import inspect_source,compare_frozen,_tokens
from generation.public_benchmark.model import CodexModel
from generation.public_benchmark.runner import _unique_object
from generation.representation.verifier import Dafny

DATA=ROOT/'research/data/large-scale-20261009/dafnybench/DafnyBench/dataset/ground_truth'
BUDGET={'actions':3,'model_timeout':300,'verifier_timeout':45,'output_tokens':10000,'session_tokens':120000}


def strip_comments(s):
    # Preserve literal bytes; source comments (including source instructions) are not prompts.
    out=[];i=0
    while i<len(s):
        if s.startswith('//',i):
            end=s.find('\n',i);i=len(s) if end<0 else end
        elif s.startswith('/*',i):
            i+=2;depth=1;out.append(' ')
            while i<len(s) and depth:
                if s.startswith('/*',i):depth+=1;i+=2
                elif s.startswith('*/',i):depth-=1;i+=2
                else:
                    if s[i]=='\n':out.append('\n')
                    i+=1
            if depth:raise ValueError('unterminated comment')
        elif s[i]=='"':
            start=i;i+=1
            while i<len(s):
                if s[i]=='\\':i+=2
                elif s[i]=='"':i+=1;break
                else:i+=1
            out.append(s[start:i])
        else:out.append(s[i]);i+=1
    return ''.join(out)


def expression_ok(e):
    if not isinstance(e,str) or not e.strip() or any(x in e for x in ('\n','\r',';','//','/*','*/',':=','{:','"')):return False
    # Literal characters are outside this expression profile. Identifier primes
    # remain legal, but a quote starting a literal must not affect bracket balance.
    if "'" in re.sub(r"[A-Za-z_][A-Za-z0-9_']*",'',e):return False
    ts=set(_tokens(e))
    if ts & {'assume','expect','assert','invariant','decreases','requires','ensures','modifies','method','lemma','function','predicate','return','var','while','include','import','calc','by'}:return False
    stack=[];pairs={')':'(',']':'[','}':'{'}
    for c in e:
        if c in '([{':stack.append(c)
        elif c in ')]}':
            if not stack or stack.pop()!=pairs[c]:return False
    return not stack


def assemble(task,c,arm):
    if not isinstance(c,dict) or set(c)!={'base_source','annotations'}:raise ValueError('schema')
    base=c['base_source']
    if arm=='P' and base is not None:raise ValueError('P requires null base_source')
    if base is None:base=task['initial']
    if not isinstance(base,str) or not isinstance(c['annotations'],list):raise ValueError('schema')
    if set(_tokens(base)) & {'assert','invariant','decreases','lemma','calc'}:raise ValueError('proofs must use annotation slots; no new lemmas')
    lines=base.splitlines();insertions={}
    for a in c['annotations']:
        if not isinstance(a,dict) or set(a)!={'before_line','kind','expression'}:raise ValueError('annotation schema')
        n=a['before_line'];k=a['kind'];e=a['expression']
        if type(n) is not int or not 1<=n<=len(lines)+1 or k not in {'assert','invariant','decreases'} or not expression_ok(e):raise ValueError('annotation expression/location')
        if k=='decreases' and e.strip()=='*':raise ValueError('wildcard decreases')
        insertions.setdefault(n,[]).append(k+' ('+e+')'+(';' if k=='assert' else ''))
    out=[]
    for n,line in enumerate(lines+[''],1):out+=insertions.get(n,[])+[line]
    return '\n'.join(out)


def extract_task(raw):
    clean=normalized_public(raw);base=[];annotations=[]
    for line in clean.splitlines():
        line=line.strip()
        if not line:continue
        m=re.fullmatch(r'(invariant|assert|decreases)\s+(.+)',line)
        if m:
            e=m[2].rstrip(';').strip()
            if not expression_ok(e):raise ValueError('reference annotation outside expression profile')
            annotations.append({'before_line':len(base)+1,'kind':m[1],'expression':e})
        else:base.append(line)
    return {'initial':'\n'.join(base)+'\n','reference':{'base_source':None,'annotations':annotations}}


def normalized_public(raw):
    # Dafny 4.11 rejects deprecated trailing specification semicolons as warnings.
    # Removing this punctuation does not change the expression or executable body.
    return re.sub(r'(?m)^(\s*(?:requires|ensures|reads|modifies|invariant|decreases)\b[^\n]*?);\s*$',r'\1',strip_comments(raw))


def evaluate(task,c,arm):
    try:source=assemble(task,c,arm)
    except (ValueError,TypeError,KeyError) as e:return {'findings':[str(e)],'source':None,'structure':None,'verification':None}
    structure=inspect_source(source)
    findings=compare_frozen(task['frozen'],structure,editable_ids=task['editable'])
    if structure.get('status')=='ok' and {d['id'] for d in structure['declarations']}!={d['id'] for d in task['frozen']['declarations']}:findings.append('new_declaration')
    verification=None
    if not findings:verification=Dafny(timeout=45).verify(source,names=task['editable'],timeout=45).to_dict()
    return {'findings':findings,'source':source,'structure':structure,'verification':verification}


def screen_one(item,root):
    ident,path=item;out=root/'screen'/ident;out.mkdir(parents=True)
    raw=path.read_text(encoding='utf-8-sig');result={'id':ident,'path':str(path.relative_to(ROOT)),'raw_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'admitted':False}
    try:
        t=extract_task(raw);t.update(id=ident,source_file=result['path'],source_sha256=result['raw_sha256'])
        t['frozen']=inspect_source(t['initial'])
        if t['frozen'].get('status')!='ok':raise ValueError('initial_structure:'+t['frozen']['status'])
        t['editable']=[d['id'] for d in t['frozen']['declarations'] if d['ast_kind']=='Method']
        if not t['editable']:raise ValueError('no_methods')
        original_structure=inspect_source(normalized_public(raw))
        if original_structure.get('status')!='ok':raise ValueError('original_structure:'+original_structure['status'])
        differences=compare_frozen(t['frozen'],original_structure,t['editable'])
        if differences:raise ValueError('reference_contract_mismatch')
        # Interface feasibility certificate: restore public annotations through exactly the P interface.
        rr=evaluate(t,t['reference'],'P');ir=evaluate(t,{'base_source':None,'annotations':[]},'P')
        result.update(reference=rr,initial=ir)
        result['admitted']=not rr['findings'] and rr['verification']['status']=='verified' and not ir['findings'] and ir['verification']['status']=='verification_failed'
        if result['admitted']:save(out/'task.json',t)
    except ValueError as e:result['exclusion']=str(e)
    save(out/'result.json',result);print('SCREEN',ident,result['admitted'],result.get('exclusion',''),flush=True)
    return result


def screen(root):
    root.mkdir(parents=True,exist_ok=False);pool=[];scan_errors=[]
    forbidden={'lemma','class','module','type','datatype','include','import','assume','expect','calc'}
    for path in sorted(DATA.glob('*.dfy')):
        raw=path.read_text(encoding='utf-8-sig')
        try:clean=strip_comments(raw)
        except ValueError as e:
            scan_errors.append({'source':str(path.relative_to(ROOT)),'reason':str(e)});continue
        ts=list(_tokens(clean))
        if set(ts)&forbidden or '{:' in clean or len(clean)>12000 or len(clean.splitlines())>220:continue
        if ts.count('while')<2 or ts.count('ensures')<2:continue
        # Pre-model structural ranking. It is not a measured difficulty or correctness score.
        pool.append((ts.count('while'),ts.count('forall')+ts.count('exists'),len(ts),path))
    save(root/'scan_errors.json',scan_errors)
    pool=sorted(pool,key=lambda x:(-x[0],-x[1],-x[2],x[3].name))[:32]
    save(root/'screen_roster.json',[{'id':f'B{i:02d}','source':str(p.relative_to(ROOT)),'loops':a,'quantifiers':b,'tokens':c} for i,(a,b,c,p) in enumerate(pool,1)])
    with ThreadPoolExecutor(max_workers=4) as ex:
        results=list(ex.map(lambda item:screen_one(item,root),[(f'B{i:02d}',p) for i,(_,_,_,p) in enumerate(pool,1)]))
    save(root/'screen_summary.json',{'screened':len(results),'admitted':[r['id'] for r in results if r['admitted']],'results':results})


SYSTEM='Repair the public Dafny program under its fixed contracts. Return only JSON with keys base_source and annotations. Never call tools. A failed proof is not a semantic counterexample. All declarations and contracts and function/predicate definitions are fixed; no new declarations, assumptions, attributes, lemmas, calc or external dependencies. Verification checks every declaration. Proofs must be supplied in annotation slots only. No reference annotations are provided.'


def messages(task,c,feedback,history,arm,action):
    base=task['initial'] if c['base_source'] is None else c['base_source']
    payload={'original_source':task['initial'],'current_candidate':c,'current_base_numbered':'\n'.join(f'{i}: {s}' for i,s in enumerate(base.splitlines(),1)),
             'feedback':feedback,'history':history,'remaining_calls':4-action,
             'edit_scope':'base_source MUST be null: keep original executable source.' if arm=='P' else 'base_source may be null to keep original, or a full replacement base program editing method bodies only.',
             'schema':{'base_source':'null or string','annotations':[{'before_line':'1-based line in chosen base_source, before which annotation is inserted','kind':'invariant | assert | decreases','expression':'one pure expression without newline, semicolon, comments, attributes or assignment'}]},
             'rules':'Use null when retaining original source. Every round is a complete candidate, not a delta. Multiple entries at one line are inserted in listed order. Loop invariants/decreases go before the loop opening brace. Assertions may go inside loops. Set and multiset expressions are allowed. Do not embed proof annotations in base_source. Do not change functions or predicates, signatures or contracts. No ghost-variable additions are possible under P. Model selection is exploratory; do not infer which arm should win.'}
    return [{'role':'system','content':SYSTEM},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]


def freeze(root,ids):
    tasks=[load(root/'screen'/ident/'task.json') for ident in ids]
    save(root/'tasks.json',tasks)
    blocks=[(t['id'],rep) for t in tasks for rep in range(3)];rng=random.Random(20261013);rng.shuffle(blocks);jobs=[]
    for tid,rep in blocks:
        arms=['P','J'];rng.shuffle(arms)
        for arm in arms:jobs.append({'index':len(jobs),'task_id':tid,'replicate':rep,'arm':arm})
    save(root/'jobs.json',jobs)
    paths=['research/public_scope_20261012.py','research/PUBLIC_SCOPE_PROTOCOL_2026_10_12.md','research/edit_scope_20261012.py','generation/public_benchmark/model.py','generation/public_benchmark/runner.py','generation/public_benchmark/structure.py','generation/public_benchmark/structure_bridge.cs','generation/public_benchmark/structure_bridge.ps1','generation/representation/verifier.py','repair/verifier.py']
    save(root/'manifest.json',{'stage':'public_complexity_development','budget':BUDGET,'sessions':len(jobs),'source_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},'data_hashes':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in ('tasks.json','jobs.json')},'verifier':Dafny(timeout=45).identity()})
    preview=[]
    for t in tasks:
        feedback=model_feedback(load(root/'screen'/t['id']/'result.json')['initial'])
        for arm in ('P','J'):preview.append({'id':t['id'],'arm':arm,'messages':messages(t,{'base_source':None,'annotations':[]},feedback,[],arm,1)})
    save(root/'payload_preview.json',preview);print('FROZEN',len(tasks),len(jobs))


def run_one(root,t,job,model):
    out=root/'runs'/f"{job['index']:04d}_{t['id']}_{job['arm']}_{job['replicate']}";out.mkdir(parents=True,exist_ok=False)
    c={'base_source':None,'annotations':[]};history=[];feedback=model_feedback(load(root/'screen'/t['id']/'result.json')['initial'])
    r={**job,'success':False,'stop':'action_budget','model_attempts':0,'processes_started':0,'responses_without_error':0,'unknown_usage':0,'input_tokens':0,'output_tokens':0,'verifier_checks':0,'rounds':[]};start=time.monotonic()
    for action in range(1,4):
        rd=out/f'round-{action:02d}';ms=messages(t,c,feedback,history,job['arm'],action);save(rd/'messages.json',ms)
        g=model.generate(ms,rd/'model',timeout=300,max_output_tokens=10000)
        r['model_attempts']+=1;r['processes_started']+=int(bool(g.get('executed')))
        r['responses_without_error']+=int(bool(g.get('executed')) and not g.get('error'))
        known=all(type(g.get(k)) is int for k in ('input_tokens','output_tokens'))
        if known:
            for k in ('input_tokens','output_tokens'):r[k]+=g[k]
        else:r['unknown_usage']+=1
        row={'action':action,'generation':g,'evaluation':None};r['rounds'].append(row)
        if g.get('error') or not g.get('executed'):r['stop']='model_infrastructure_failure';save(rd/'round.json',row);break
        if not known or g['output_tokens']>10000 or r['input_tokens']+r['output_tokens']>120000:r['stop']='token_threshold';save(rd/'round.json',row);break
        try:
            proposed=json.loads(g['text'],object_pairs_hook=_unique_object);e=evaluate(t,proposed,job['arm'])
        except (ValueError,TypeError) as err:e={'findings':['json:'+str(err)],'source':None,'verification':None,'structure':None}
        row['evaluation']=e
        if e.get('source'):(rd/'candidate.dfy').write_text(e['source'],encoding='utf-8')
        if e.get('verification') is not None:r['verifier_checks']+=1
        if infrastructure_failure(e):r['stop']='verification_infrastructure_failure';save(rd/'round.json',row);break
        if e.get('verification') is not None:
            c=proposed
            if e['verification']['status']=='verified':r.update(success=True,successful_action=action,stop='verified')
        feedback=model_feedback(e);history.append({'response':g['text'],'feedback':feedback});save(rd/'round.json',row)
        if r['success']:break
    r['seconds']=time.monotonic()-start;r['artifacts']={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
    save(out/'result.json',r);(out/'result.sha256').write_text(hashlib.sha256((out/'result.json').read_bytes()).hexdigest());return r


def run(root):
    m=load(root/'manifest.json')
    for p,h in m['source_hashes'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
    for p,h in m['data_hashes'].items():assert hashlib.sha256((root/p).read_bytes()).hexdigest()==h,p
    if (root/'runs').exists():raise ValueError('no implicit retries/resume')
    tasks={t['id']:t for t in load(root/'tasks.json')};jobs=load(root/'jobs.json')
    model=CodexModel(model='gpt-6-astra',effort='high',codex_home='C:/Users/16039/.codex',proxy='http://127.0.0.1:10808');save(root/'model_identity.json',model.identity());rows=[]
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures=[ex.submit(run_one,root,tasks[j['task_id']],j,model) for j in jobs]
        for f in as_completed(futures):
            r=f.result();rows.append(r);save(root/'progress.json',{'completed':len(rows),'expected':len(jobs),'successes':sum(r['success'] for r in rows)})
            print('DONE',len(rows),'/',len(jobs),r['task_id'],r['arm'],r['replicate'],r['success'],r['stop'],flush=True)
    analyze(root)


def analyze(root):
    rows=[]
    for f in sorted(root.glob('runs/*/result.json')):
        assert hashlib.sha256(f.read_bytes()).hexdigest()==(f.parent/'result.sha256').read_text()
        r=load(f)
        for p,h in r['artifacts'].items():assert hashlib.sha256((f.parent/p).read_bytes()).hexdigest()==h,p
        rows.append(r)
    jobs=load(root/'jobs.json');key=lambda r:(r['task_id'],r['arm'],r['replicate'])
    assert len(rows)==len(jobs) and {key(r) for r in rows}=={key(j) for j in jobs}
    arms={}
    for arm in ('P','J'):
        rr=[r for r in rows if r['arm']==arm]
        arms[arm]={'sessions':len(rr),'successes':sum(r['success'] for r in rr),'first_action':sum(r.get('successful_action')==1 for r in rr),'stops':dict(Counter(r['stop'] for r in rr)),**{k:sum(r[k] for r in rr) for k in ('model_attempts','processes_started','responses_without_error','unknown_usage','input_tokens','output_tokens','verifier_checks')}}
    pairs=[]
    for tid in sorted({r['task_id'] for r in rows}):
        for rep in range(3):
            p=next(r for r in rows if key(r)==(tid,'P',rep));j=next(r for r in rows if key(r)==(tid,'J',rep))
            pairs.append({'task_id':tid,'replicate':rep,'P':p['success'],'J':j['success'],'P_stop':p['stop'],'J_stop':j['stop']})
    result={'completed':len(rows),'arms':arms,'pairs':pairs,'interpretation':'Exploratory public annotation deletion, not natural development failures; no population inference.'}
    save(root/'summary.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['screen','freeze','run','analyze']);p.add_argument('--output',type=Path,required=True);p.add_argument('--ids',nargs='*');a=p.parse_args();root=a.output.resolve()
    if ROOT not in root.parents:raise ValueError('output outside repo')
    if a.command=='screen':screen(root)
    elif a.command=='freeze':freeze(root,a.ids)
    elif a.command=='run':run(root)
    else:analyze(root)
