"""Independent local audit of the public-scope campaign; no model calls."""
from pathlib import Path
import hashlib,json,sys
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from research.public_scope_20261012 import load,save,assemble


def audit(root):
    manifest=load(root/'manifest.json')
    for p,h in manifest['source_hashes'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
    for p,h in manifest['data_hashes'].items():assert hashlib.sha256((root/p).read_bytes()).hexdigest()==h,p
    tasks={t['id']:t for t in load(root/'tasks.json')};jobs=load(root/'jobs.json');rows={};edits=[];findings=Counter()
    for f in sorted(root.glob('runs/*/result.json')):
        r=load(f);key=(r['task_id'],r['arm'],r['replicate']);assert key not in rows
        assert hashlib.sha256(f.read_bytes()).hexdigest()==(f.parent/'result.sha256').read_text()
        for p,h in r['artifacts'].items():assert hashlib.sha256((f.parent/p).read_bytes()).hexdigest()==h,p
        assert len(r['rounds'])==r['model_attempts']<=3
        assert r['verifier_checks']==sum(bool((z.get('evaluation') or {}).get('verification')) for z in r['rounds'])
        accepted=False
        for z in r['rounds']:
            e=z.get('evaluation') or {};v=e.get('verification') or {}
            for item in e.get('findings',[]):findings[str(item if isinstance(item,str) else item.get('code'))]+=1
            if v:
                c=json.loads(z['generation']['text']);t=tasks[r['task_id']]
                assert assemble(t,c,r['arm'])==e['source']
                if r['arm']=='P':assert c['base_source'] is None
                assert not e['findings'] and e['structure']['status']=='ok'
                before={d['id']:d for d in t['frozen']['declarations']};after={d['id']:d for d in e['structure']['declarations']}
                assert set(before)==set(after)
                for name,d in before.items():
                    assert d['header_tokens']==after[name]['header_tokens']
                    assert d['contract_bindings']==after[name]['contract_bindings']
                    if name not in t['editable']:assert d['tokens']==after[name]['tokens']
                if v['status']=='verified':
                    assert v['executed'] and v['real_verifier'] and v['returncode']==0
                    assert all(outcome=='passed' for outcome in v['obligations'].values())
                    accepted=True
                if c['base_source'] is not None:
                    edits.append({'task_id':r['task_id'],'arm':r['arm'],'replicate':r['replicate'],'action':z['action'],'status':v['status'],'base_source':c['base_source']})
        assert accepted==r['success'];rows[key]=(r,f.parent)
    assert len(rows)==len(jobs) and set(rows)=={(j['task_id'],j['arm'],j['replicate']) for j in jobs}
    pairs=[]
    for tid in tasks:
        for rep in range(3):
            p,pdir=rows[tid,'P',rep];j,jdir=rows[tid,'J',rep]
            pm=load(pdir/'round-01/messages.json');jm=load(jdir/'round-01/messages.json');assert pm[0]==jm[0]
            pp=json.loads(pm[1]['content']);jp=json.loads(jm[1]['content']);assert pp.pop('edit_scope')!=jp.pop('edit_scope');assert pp==jp
            pairs.append({'task_id':tid,'replicate':rep,'P':p['success'],'J':j['success'],'P_stop':p['stop'],'J_stop':j['stop'],'P_actions':p['model_attempts'],'J_actions':j['model_attempts']})
    names=lambda ps:dict(Counter('both' if p['P'] and p['J'] else 'P_only' if p['P'] else 'J_only' if p['J'] else 'neither' for p in ps))
    clean=[p for p in pairs if 'infrastructure' not in p['P_stop'] and 'infrastructure' not in p['J_stop']]
    out={'audit_passed':True,'sessions':len(rows),'pairs_matching_except_scope':len(pairs),'paired_outcomes':names(pairs),'paired_outcomes_without_infrastructure':names(clean),'pairs':pairs,'replacement_bases':edits,'guard_findings':dict(findings),'sensitivity_note':'Infrastructure-excluded counts are descriptive; original denominator remains fixed.'}
    save(root/'independent_audit.json',out)
    print(json.dumps({k:v for k,v in out.items() if k not in ('pairs','replacement_bases')},ensure_ascii=False))


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
