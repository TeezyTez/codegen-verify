"""Audit local draft consistency; keep human-verification failures visible."""
from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json
import re
import subprocess
import sys

P = Path(__file__).resolve().parent
ROOT = P.parents[1]
SKILL = Path('C:/Users/16039/.codex/skills/scientific-writing/scripts')


def load(p): return json.loads(p.read_text(encoding='utf-8'))
def save(name,data): (P/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    text=(P/'manuscript.audit.md').read_text(encoding='utf-8')
    claims={re.search(r'\[claim:(C\d+)\]',s)[1]:s for s in text.splitlines() if '[claim:' in s}
    with (P/'claim_evidence.csv').open(encoding='utf-8',newline='') as f: rows=list(csv.DictReader(f))
    sources=load(P/'source_manifest.json')['sources']
    ev=load(P/'evidence/evidence_audit.json');m=ev['main']
    checks=[]
    def check(name,ok,detail=None):
        checks.append({'check':name,'passed':bool(ok),'detail':detail})
    check('claim registry and manuscript IDs',len(claims)==len(rows) and set(claims)=={r['claim_id'] for r in rows})
    for r in rows:
        s=claims[r['claim_id']]
        normalized=' '.join(re.sub(r'\[(?:claim:C\d+|evidence:E\d+(?:,E\d+)*|@E\d+)\]','',s).split())
        check(f"claim hash {r['claim_id']}",hashlib.sha256(normalized.encode()).hexdigest()==r['claim_text_sha256'])
        eids=re.search(r'\[evidence:([^\]]+)\]',s)[1].split(',')
        check(f"evidence binding {r['claim_id']}",set(eids)==set(r['evidence_ids'].split(';')) and set(eids)<={q['evidence_id'] for q in sources})
    for r in load(P/'machine_source_checks.json')['sources']:
        if 'path' in r:
            check(f"bound source bytes {r['evidence_id']}",hashlib.sha256((ROOT/r['path']).read_bytes()).hexdigest()==r['sha256_bytes'])
    for i,arm in enumerate('ABCD',31):
        s=m['arms'][arm]
        expected=[s['sessions'],s['successes'],s['first_action_successes'],s['repair_successes'],sum(s['failure_reasons'].values())]
        row=claims[f'C{i:03d}'].split('[claim:')[0]
        observed=[int(v.strip()) for v in row.split('|')[2:7]]
        check(f'manuscript numeric row {arm}',observed==expected,{'expected':expected,'observed':observed})
    t=m['totals']
    check('success partition',t['first_action_successes']+t['repair_successes']==t['successes']==412)
    check('completion partition',m['completed_sessions']+len(m['incomplete_directories'])+m['not_started_count']==m['frozen_sessions']==1392)
    check('action partition',t['model_calls']==460 and t['verifier_calls']==438)
    blocks=defaultdict(set)
    for s in m['sessions']:blocks[(s['task_id'],s['replicate'])].add(s['arm'])
    check('completed block pairing',len(blocks)==104 and all(v==set('ABCD') for v in blocks.values()))
    check('family repetition completeness',m['distinct_completed_families']==75 and len(m['complete_12_session_families'])==4)
    check('scheduler opportunity/disagreement',m['scheduler']['opportunity_rounds']==8 and m['scheduler']['counterfactual_disagreement_rounds']==4)
    check('D following denominator',m['d_target_following']['followed']==112 and m['d_target_following']['audited_targeted_rounds']==114 and m['d_target_following']['missing_targeted_rounds']==1 and m['arms']['D']['model_calls']==115)
    check('historical probe partition',ev['mechanism_probe']['phase_counts']==[60,4,2] and ev['mechanism_probe']['verifier_calls']==66)
    mismatch=ev['check_summary']['mismatches']
    check('only disclosed historical source drift',len(mismatch)==1 and mismatch[0]['check'].replace('\\','/')=='probe/current_source/generation/representation/verifier.py')
    for cid,needles in {
        'C003':['116','1392','416','412','103/104','104','75','4','460','8','5','2'],
        'C030':['1392','416','16','960'], 'C035':['416','412','374','38','4'],
        'C036':['99.04%','104','75','4','12'], 'C039':['460','412','25','1','22'],
        'C042':['64','62','60','2','66','12'], 'C043':['33','66','30'],
        'C073':['115','114','112','2','1'],
        'C074':[str(ev['check_summary']['checks']),str(ev['check_summary']['passed'])],
    }.items():
        check(f'key numeric claim tokens {cid}',all(n in claims[cid] for n in needles))
    lit=load(P/'literature/citation_audit.json')['records']
    bib=(P/'literature/references.bib').read_text(encoding='utf-8')
    keys=re.findall(r'@\w+\{([^,]+),',bib)
    check('nine unique bibliography keys',len(keys)==len(set(keys))==len(lit)==9)
    check('bibliography keys match checked metadata',set(keys)=={r['bibkey'] for r in lit})
    check('human verification not fabricated',all(s['verification']['status']=='unverified' and not s['verification']['verified_by'] for s in sources))
    check('submission ready remains false',load(P/'manuscript_manifest.json')['submission_ready'] is False)
    check('reader draft has no audit markers','[claim:' not in (P/'manuscript.md').read_text(encoding='utf-8') and '[evidence:' not in (P/'manuscript.md').read_text(encoding='utf-8'))

    tools=[('source_schema','validate_manifest.py',['source_manifest.json']),
           ('manuscript_schema','validate_manifest.py',['manuscript_manifest.json']),
           ('reference_syntax','check_references.py',['source_manifest.json']),
           ('numeric_consistency','check_consistency.py',['consistency_manifest.json']),
           ('claim_human_gate','audit_claims.py',['manuscript.audit.md','claim_evidence.csv','source_manifest.json'])]
    gate=[]
    (P/'validation').mkdir(exist_ok=True)
    for label,script,args in tools:
        result=subprocess.run([sys.executable,'-X','utf8',str(SKILL/script),*[str(P/a) for a in args]],capture_output=True,text=True,encoding='utf-8')
        try:report=json.loads(result.stdout)
        except ValueError:report={'stdout':result.stdout,'stderr':result.stderr}
        save(f'validation/{label}.json',report)
        errors=Counter(i.get('code') for i in report.get('issues',[]) if i.get('severity')=='error')
        gate.append({'tool':label,'exit_code':result.returncode,'error_codes':dict(errors),'report':f'validation/{label}.json'})
        if label=='claim_human_gate':
            allowed={'CLAIM_NOT_VERIFIED','UNVERIFIED_CLAIM_EVIDENCE','UNVERIFIED_CITATION_MARKER'}
            check('claim audit has only disclosed human-review failures',bool(errors) and set(errors)<=allowed and result.returncode!=0,dict(errors))
        else:
            check(f'skill validator {label}',result.returncode==0,dict(errors))
    report={'scope':'Mechanical binding, arithmetic and local consistency only; not scientific truth or accountable human review',
            'machine_checks':len(checks),'machine_passed':sum(c['passed'] for c in checks),'checks':checks,
            'skill_tool_reports':gate,'human_verification':'pending','submission_ready':False,
            'historical_source_mismatch':mismatch,'source_audit':ev['check_summary']}
    save('validation_report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('checks','skill_tool_reports','historical_source_mismatch','source_audit')},ensure_ascii=False))
    for c in checks:
        if not c['passed']:print(json.dumps(c,ensure_ascii=False))
    return 0 if all(c['passed'] for c in checks) else 1


if __name__=='__main__':raise SystemExit(main())
