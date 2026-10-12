"""Build a readable draft and machine registries from the marked audit draft.

Local only. This does not perform human verification or run experiments.
"""
from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import re
import subprocess
import sys

P = Path(__file__).resolve().parent
ROOT = P.parents[1]
SKILLS = Path('C:/Users/16039/.codex/skills/scientific-writing')
CLAIM = re.compile(r'\[claim:(C\d{3,8})\]')
EVIDENCE = re.compile(r'\[evidence:((?:E\d{3,8})(?:\s*,\s*E\d{3,8})*)\]')
CITATION = re.compile(r'\[@(E\d{3,8})\]')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(name, data):
    (P / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def bare(line):
    return CITATION.sub('', EVIDENCE.sub('', CLAIM.sub('', line)))


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def main():
    audit = load(P / 'evidence/evidence_audit.json')
    lit = load(P / 'literature/citation_audit.json')['records']
    refs = {r['evidence_id']: r for r in lit}
    audit_path = P / 'manuscript.audit.md'
    text = audit_path.read_text(encoding='utf-8')
    # Use checked original metadata, not recalled author names or publication fields.
    for i, r in enumerate(lit, 64):
        c = f'C{i:03d}'
        authors = '; '.join(r['authors'])
        pub = 'SAIV, Springer, pp. 134–155' if r['evidence_id'] == 'E102' else f"arXiv:{r['arxiv_id']} ({r['arxiv_version_opened']})"
        line = f"[{i-63}] {authors}. ({r['year']}). *{r['title']}*. [{pub}]({r['url']}). BibTeX 键 `{r['bibkey']}`。[claim:{c}] [evidence:{r['evidence_id']}]"
        text = re.sub(r'^.*\[claim:' + c + r'\].*$', lambda _: line, text, flags=re.M)
    # Keep the audit count tied to the current extraction, including any new checks.
    n = audit['check_summary']
    text = re.sub(r'本次共进行了 \d+ 项工件一致性检查，\d+ 项一致',
                  f"本次共进行了 {n['checks']} 项工件一致性检查，{n['passed']} 项一致", text)
    audit_path.write_text(text, encoding='utf-8')

    drafting = {
        'date': '2026-10-12', 'language': 'zh-CN', 'requested_output': 'Chinese research draft',
        'user_language_confirmed': True, 'new_model_experiments_this_turn': 0,
        'new_verifier_experiments_this_turn': 0, 'external_queries': 'Public titles, IDs, metadata and papers only',
        'private_manuscript_or_logs_uploaded': False,
        'work_order': ['claim_evidence.md', 'outline.md', 'manuscript.audit.md', 'citation and consistency verification'],
        'ai_assistance': ['local artifact extraction', 'claim scope audit', 'drafting', 'public citation lookup', 'independent agent review'],
        'skills_used': ['scientific-writing', 'scientific-critical-thinking', 'ml-paper-writing', 'citation-management'],
        'human_verification': 'pending', 'submission_ready': False,
        'unresolved': ['human authors and affiliations', 'target venue', 'funding', 'conflicts', 'contributions', 'data release authorization', 'venue policy and required declarations'],
        'code_url': 'https://github.com/TeezyTez/codegen-verify',
        'raw_logs_publication_claimed': False,
    }
    save('drafting_record.json', drafting)
    local = [
        ('E001','report','Completed-subset artifact audit','papers/evidence-guided-codegen-20261012/evidence/evidence_audit.json','main; check_summary; evidence_files', 'restricted'),
        ('E002','registry','Frozen main campaign and framework snapshot','logs/public-codegen-20261009/main-v3/manifest.json','jobs.json; tasks.json; family_manifest.json; prelaunch-audit.json; framework_snapshot/', 'restricted'),
        ('E003','software','Declaration evidence ledger and C/D scheduling','generation/public_benchmark/policy.py','EvidenceLedger.begin/observe/target; prompt construction; matched to main frozen hashes', 'public'),
        ('E004','software','Trusted generation and verification runner','generation/public_benchmark/runner.py','candidate guard; full verifier acceptance; budget; audit fields', 'public'),
        ('E005','software','Fixed specification task packaging','generation/public_benchmark/task.py','PublicTask; implementation/helpers JSON; single target; public record', 'public'),
        ('E006','report','Development and canary audit','papers/evidence-guided-codegen-20261012/evidence/evidence_audit.json','development_v2; canary_v1; original paths and hashes in evidence_files', 'restricted'),
        ('E007','report','Authored evidence-semantics probes','logs/evidence-semantics-probe-20261009/plan.json','results.json; analysis.json; witnesses/; witness_anchor/; evidence_audit.json mechanism_probe and check_summary', 'restricted'),
        ('E008','dataset','Final admission and task-family manifest','logs/public-codegen-20261009/families-final/manifest.json','tasks; families; evidence_audit.json families_final and frozen prelaunch audits', 'restricted'),
        ('E009','registry','Frozen experiment protocol and execution amendments','logs/public-codegen-20261009/main-v3/protocol-frozen.md','read together with manifest.json and prelaunch-audit.json; final runner overrides earlier prose', 'restricted'),
        ('E010','software','Prespecified complete campaign analysis','research/analyze_main_public_20261009.py','full cohort requirement; family aggregation; primary contrasts and bootstrap', 'public'),
        ('E011','software','Code repository availability','README.md','repository URL; does not assert raw logs released', 'public'),
        ('E012','report','Drafting provenance and unresolved author declarations','papers/evidence-guided-codegen-20261012/drafting_record.json','all fields; author/human review pending', 'restricted'),
        ('E013','dataset','Pinned vericoding-benchmark source snapshot','research/data/large-scale-20261009/vericoding-snapshot.json','repository; commit; per-file bytes and hashes; main admitted representatives separately frozen', 'public'),
    ]
    sources = []
    machine_sources = []
    for eid, typ, title, path, locator, confidentiality in local:
        f = ROOT / path
        assert f.is_file(), f
        sources.append({'evidence_id':eid, 'source_type':typ, 'title':title, 'authors':[], 'year':2026,
                        'identifiers':{'doi':'','isbn':'','pmcid':'','pmid':'','url':drafting['code_url'] if eid=='E011' else ''},
                        'locator':f'{path} :: {locator}', 'confidentiality':confidentiality,
                        'verification':{'status':'unverified','source_opened':False,'verified_by':'','verified_on':''}})
        machine_sources.append({'evidence_id':eid,'path':path,'sha256_bytes':hashlib.sha256(f.read_bytes()).hexdigest(),
                                'machine_status':'local_source_read','human_status':'pending'})
    for r in lit:
        sources.append({'evidence_id':r['evidence_id'],'source_type':'conference_paper' if r['evidence_id']=='E102' else 'preprint',
                        'title':r['title'],'authors':r['authors'],'year':r['year'],
                        'identifiers':{'doi':r['doi'],'isbn':'','pmcid':'','pmid':'','url':r['url']},
                        'locator':r['locator'],'confidentiality':'public',
                        'verification':{'status':'unverified','source_opened':False,'verified_by':'','verified_on':''}})
        machine_sources.append({'evidence_id':r['evidence_id'],'machine_status':r['machine_verification'],
                                'human_status':'pending','detail':'literature/citation_audit.json'})
    save('source_manifest.json', {'schema_version':'1.0','sources':sources})
    save('machine_source_checks.json', {'note':'source_manifest.verification is reserved for accountable human checking; machine access is recorded here separately.', 'sources':machine_sources})

    rows = []
    section = 'front matter'
    readable = []
    for line in text.splitlines():
        if line.startswith('## '): section = line[3:]
        matches = CLAIM.findall(line)
        if matches:
            assert len(matches) == 1
            evid = [s.strip() for group in EVIDENCE.findall(line) for s in group.split(',')]
            assert evid and set(evid) <= {r['evidence_id'] for r in sources}
            cid = matches[0]
            num = int(cid[1:])
            kind = ('declaration' if num in (1,61,62,63) else 'factual' if num>=64 and num<=72 else
                    'interpretive' if num in (5,6,7,8,14,29,37,41,48,49,50,51,52,53,54,55,56,57,58,59,60) else
                    'result' if num in (3,4,30,31,32,33,34,35,36,38,39,40,42,43,44,45,46,47,73,74) else 'method')
            intent = 'exploratory' if kind=='interpretive' else 'descriptive' if kind=='result' else 'not_applicable'
            rows.append({'claim_id':cid,'section':section,'claim_kind':kind,
                         'claim_text_sha256':digest(' '.join(bare(line).split())), 'evidence_ids':';'.join(evid),
                         'verification_status':'human_review_pending','uncertainty':'high' if kind=='interpretive' else 'not_estimated' if kind=='result' else 'not_applicable',
                         'analysis_intent':intent})
            links = [] if section=='经核对的参考文献索引' else [f"[{int(e[1:])-100}]({refs[e]['url']})" for e in evid if e in refs]
            readable.append(bare(line).rstrip() + (' ' + ' '.join(links) if links else ''))
        else:
            readable.append(line)
    assert len({r['claim_id'] for r in rows}) == len(rows)
    with (P/'claim_evidence.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (P/'manuscript.md').write_text('\n'.join(readable)+'\n',encoding='utf-8')

    manifest = load(SKILLS/'assets/manuscript_manifest_template.json')
    manifest.update(document_id='evidence-guided-codegen-20261012',study_design='Incomplete controlled software experiment plus authored verification mechanism probes; descriptive and exploratory manuscript')
    manifest['registries'].update(claim_evidence='claim_evidence.csv',authorship_manifest='authorship.json')
    for k in ('ai_disclosure','code_availability','data_availability'):manifest['required_statements'][k]='draft'
    save('manuscript_manifest.json',manifest)
    authorship=load(SKILLS/'assets/authorship_template.json')
    authorship['authors']=[]
    authorship['ai_use'].update(used=True,tools=['Codex; installed research skills'],disclosed_in=['manuscript.audit.md C062'],human_verification_complete=False)
    ai_line=next(line for line in text.splitlines() if '[claim:C062]' in line)
    authorship['declarations']['ai_use'].update(status='draft',content_sha256=digest(' '.join(bare(ai_line).split())))
    save('authorship.json',authorship)
    save('reporting_coverage.json', {'schema_version':'1.0','guideline_id':'computational-draft-local-coverage',
        'disclaimer':'Local non-scoring coverage map, not a venue checklist or compliance certificate; venue remains unset.',
        'items':[{'topic':topic,'location':where,'status':status} for topic,where,status in [
            ('task boundaries and acceptance','C015–C029','reported'),('planned and completed sample sizes','C024–C036','reported'),
            ('selection and missingness','C030,C036,C055','reported'),('intervention activation','C040,C073','reported'),
            ('negative and historical findings','C047,C074','reported'),('statistical efficacy','C025,C036','not_estimated_in_incomplete_cohort'),
            ('model identity and resources','C026,C027,C058','limitations_reported'),('human review and authorship','C063','pending')]]})

    m=audit['main'];facts=[]
    values=[('planned_sessions',m['frozen_sessions'],'frozen_main','sessions'),('completed_sessions',m['completed_sessions'],'completed_main','sessions'),
            ('successes',m['totals']['successes'],'completed_main','sessions'),('first_action_successes',m['totals']['first_action_successes'],'completed_main','sessions'),
            ('repair_successes',m['totals']['repair_successes'],'completed_main','sessions'),('model_calls',m['totals']['model_calls'],'completed_main','calls'),
            ('verifier_calls',m['totals']['verifier_calls'],'completed_main','calls'),('task_families',m['distinct_completed_families'],'completed_main','families'),
            ('complete_families',len(m['complete_12_session_families']),'completed_main','families'),('opportunity_rounds',m['scheduler']['opportunity_rounds'],'completed_main','rounds'),
            ('recommendation_disagreements',m['scheduler']['counterfactual_disagreement_rounds'],'completed_main','rounds'),('probe_checks',audit['mechanism_probe']['verifier_calls'],'authored_probe','calls')]
    for section_name in ('摘要','阶段性结果'):
        for concept,value,analysis_set,unit in values:
            facts.append({'fact_id':f'N{len(facts)+1:03d}','concept':concept,'section':section_name,'value':value,'unit':unit,
                          'numerator':None,'denominator':None,'sample_size':None,'analysis_set':analysis_set,'evidence_ids':['E007' if analysis_set=='authored_probe' else 'E001']})
    for arm,d in m['arms'].items():
        facts.append({'fact_id':f'N{len(facts)+1:03d}','concept':'verified_success_rate','section':'阶段性结果','value':round(d['successes']/d['sessions']*100,2),'unit':'percent',
                      'numerator':d['successes'],'denominator':d['sessions'],'sample_size':d['sessions'],'analysis_set':f'completed_main_{arm}','evidence_ids':['E001']})
    save('consistency_manifest.json',{'schema_version':'1.0','numeric_facts':facts,
        'methods':[{'method_id':'M001','name':'Completed subset descriptive artifact audit','analysis_intent':'descriptive','protocol_status':'post_hoc','outcome_ids':['O001']}],
        'results':[{'result_id':'R001','method_id':'M001','outcome_id':'O001','analysis_intent':'descriptive','sample_size':m['completed_sessions'],'evidence_ids':['E001'],'reported_sections':['摘要','阶段性结果']}]})
    print(json.dumps({'claims':len(rows),'sources':len(sources),'literature_records':len(lit),'reader_draft':'manuscript.md','human_verification':'pending'},ensure_ascii=False))


if __name__=='__main__':main()
