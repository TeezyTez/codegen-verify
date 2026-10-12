"""Post-run integrity and descriptive analysis; never launches model calls."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from research.edit_scope_20261012 import load,save,tok,CODE,validate_candidate


def audit(root):
    manifest=load(root/'manifest.json')
    for name,h in manifest['source_hashes'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h,name
    for name in ('jobs','tasks'):
        assert hashlib.sha256((root/f'{name}.json').read_bytes()).hexdigest()==manifest[name+'_sha256']
    tasks={t['id']:t for t in load(root/'tasks.json')}
    jobs=load(root/'jobs.json');rows={};edits=[];findings=Counter();pairs=[]
    for f in sorted(root.glob('runs/*/result.json')):
        r=load(f);key=(r['task_id'],r['arm'],r['replicate'])
        assert key not in rows
        assert hashlib.sha256(f.read_bytes()).hexdigest()==(f.parent/'result.sha256').read_text()
        for name,h in r['artifacts'].items():
            assert hashlib.sha256((f.parent/name).read_bytes()).hexdigest()==h,name
        assert r['model_attempts']==len(r['rounds'])<=3
        assert r['verifier_calls']==sum(z.get('evaluation') is not None and z['evaluation'].get('verification') is not None for z in r['rounds'])
        assert r['success']==any((z.get('evaluation') or {}).get('verification',{}).get('status')=='verified' for z in r['rounds'] if (z.get('evaluation') or {}).get('verification'))
        for z in r['rounds']:
            e=z.get('evaluation') or {};findings.update(e.get('findings',[]))
            if e.get('verification',{}):
                c=json.loads(z['generation']['text'])
                assert not validate_candidate(tasks[r['task_id']],c,r['arm'])
                changed={k:{'before':tasks[r['task_id']]['initial'][k],'after':c[k]} for k in CODE if tok(c[k])!=tok(tasks[r['task_id']]['initial'][k])}
                if r['arm']=='P':assert not changed
                if changed:edits.append({'task_id':r['task_id'],'arm':r['arm'],'replicate':r['replicate'],'cohort':r['cohort'],'action':z['action'],'changes':changed,'status':e['verification']['status']})
        rows[key]=(r,f.parent)
    assert set(rows)=={(j['task_id'],j['arm'],j['replicate']) for j in jobs}
    for tid in tasks:
        for rep in range(3):
            p,pdir=rows[tid,'P',rep];j,jdir=rows[tid,'J',rep]
            pm=load(pdir/'round-01/messages.json');jm=load(jdir/'round-01/messages.json')
            assert pm[0]==jm[0]
            pp=json.loads(pm[1]['content']);jp=json.loads(jm[1]['content'])
            assert pp.pop('edit_scope')!=jp.pop('edit_scope')
            assert pp==jp,(tid,rep)
            pairs.append({'task_id':tid,'family':tasks[tid]['family'],'replicate':rep,'cohort':p['cohort'],
                          'P_success':p['success'],'J_success':j['success'],
                          'P_stop':p['stop_reason'],'J_stop':j['stop_reason'],
                          'P_attempts':p['model_attempts'],'J_attempts':j['model_attempts']})
    cohorts={}
    for cohort in ('correct_body','bug_calibration'):
        pp=[p for p in pairs if p['cohort']==cohort]
        complete=[p for p in pp if 'infrastructure_failure' not in p['P_stop'] and 'infrastructure_failure' not in p['J_stop']]
        def outcomes(items):
            return dict(Counter('both' if p['P_success'] and p['J_success'] else 'P_only' if p['P_success'] else 'J_only' if p['J_success'] else 'neither' for p in items))
        cohorts[cohort]={'all_pairs':outcomes(pp),'pairs_without_infrastructure_failure':outcomes(complete),
                         'infrastructure_affected_pairs':len(pp)-len(complete),
                         'warning':'Infrastructure-excluded view is a post-hoc sensitivity description, not a replacement denominator.'}
    result={'audit_passed':True,'sessions':len(rows),'paired_initial_inputs_equal_except_scope':len(pairs),
            'cohorts':cohorts,'pairs':pairs,'executable_edits':edits,'guard_findings':dict(findings),
            'family_mapping':{k:v['family'] for k,v in tasks.items()}}
    save(root/'independent_audit.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('pairs','executable_edits','family_mapping')},ensure_ascii=False))


if __name__=='__main__':
    audit(Path(sys.argv[1]).resolve())
