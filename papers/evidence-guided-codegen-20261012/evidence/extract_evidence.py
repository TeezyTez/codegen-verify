"""Read stored evidence only; never invoke a model/verifier or full-matrix analysis.

Run from any directory: <repo>/.venv/Scripts/python.exe -B <this file>.
Writes only evidence_audit.json and audit.md next to this script. Bytecode disabled.
Hashes prove local consistency, not independent provenance or human review.
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import json
import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
from generation.public_benchmark import analyze as stored
from generation.public_benchmark.task import canonical, digest
from research.analyze_main_public_20261009 import _helper_and_scheduler_cases

INDEX = {}
CHECKS = []
def register(p):
    p = p.resolve()
    blob = p.read_bytes()
    INDEX[p.relative_to(ROOT).as_posix()] = {'bytes': len(blob), 'sha256_bytes': hashlib.sha256(blob).hexdigest()}
    return blob

def read(p):
    return json.loads(register(p).decode('utf8'))

def text_hash(p):
    register(p)
    return digest(p.read_text(encoding='utf8'))

def check(label, actual, expected, fatal=True):
    ok = actual == expected
    CHECKS.append({'check': label, 'passed': ok, 'actual': actual, 'expected': expected})
    if fatal and not ok:
        raise ValueError('Evidence consistency check failed: '+label)
    return ok

def rates(rows):
    return {'sessions':len(rows), 'successes':sum(r['success'] for r in rows),
        'first_action_successes':sum(r['success'] and r['successful_action']==1 for r in rows),
        'repair_successes':sum(r['success'] and r['successful_action']>1 for r in rows),
        'model_calls':sum(r['model_calls'] for r in rows),
        'verifier_calls':sum(r['verifier_calls'] for r in rows),
        'failure_reasons':dict(Counter(r['stop_reason'] for r in rows if not r['success']))}

def campaign(name, main=False):
    root=ROOT/'logs/public-codegen-20261009'/name
    manifest=read(root/'manifest.json'); jobs=read(root/'jobs.json'); tasks=read(root/'tasks.json')
    for field, data in [('jobs',jobs),('tasks',tasks)]:
        check(name+'/'+field, digest(canonical(data)), manifest[field+'_sha256'])
    if manifest.get('family_manifest_sha256'):
        check(name+'/family_manifest',digest(canonical(read(root/'family_manifest.json'))),manifest['family_manifest_sha256'])
    check(name+'/roster_count',len(jobs),manifest['expected_sessions'])
    check(name+'/roster_unique_directories',len({j['directory'] for j in jobs}),len(jobs))
    check(name+'/roster_unique_identities',len({(j['task_id'],j['arm'],j['replicate']) for j in jobs}),len(jobs))
    check(name+'/roster_tasks',sorted({j['task_id'] for j in jobs}),sorted(tasks))
    actual={p.name for p in (root/'runs').iterdir() if p.is_dir()}
    check(name+'/unrostered_directories',sorted(actual-{j['directory'] for j in jobs}),[])
    rows=[]; sessions=[]; incomplete=[]; not_started=[]
    for job in jobs:
        folder=root/'runs'/job['directory']
        if not folder.exists(): not_started.append(job); continue
        if not (folder/'result.json').exists():
            incomplete.append({**job,'round_directories':len(list(folder.glob('round-*'))),
                'manifest_exists':(folder/'manifest.json').exists()})
            continue
        row, trial_manifest=stored._trial(folder)
        check(name+'/'+job['directory']+'/identity', list(stored._identity(row)),
              [manifest['model']['model'],job['task_id'],job['replicate'],job['arm']])
        for f in ['result.json','manifest.json','result.sha256']:
            register(folder/f)
        for relative in row.get('artifact_sha256',{}): register(folder/relative)
        row=dict(row); row['family_id']=tasks[row['task_id']]['family_id']; rows.append(row)
        sessions.append({**job,'family_id':row['family_id'],'success':row['success'],
            'successful_action':row.get('successful_action'),'stop_reason':row['stop_reason'],
            'research_eligible':row.get('research_eligible'),
            'result_path':(folder/'result.json').relative_to(ROOT).as_posix(),
            'result_sha256_canonical':digest(canonical(row))})
    if (root/'results.json').exists():
        aggregate=read(root/'results.json')
        check(name+'/aggregate_results_match',digest(canonical(sorted(aggregate,key=stored._identity))),digest(canonical(sorted(rows,key=stored._identity))))
    groups=defaultdict(list)
    for row in rows: groups[row['family_id']].append(row)
    full=[f for f,rs in groups.items() if len(rs)==12 and {(r['arm'],r['replicate']) for r in rs}=={(a,i) for a in 'ABCD' for i in range(3)}]
    blocks=defaultdict(list)
    for row in rows: blocks[(row['task_id'],row['replicate'])].append(row['arm'])
    complete_blocks=sum(len(arms)==4 and set(arms)==set('ABCD') for arms in blocks.values())
    arm_rosters={a:sorted((r['task_id'],r['replicate']) for r in rows if r['arm']==a) for a in 'ABCD'}
    roster_equal=all(arm_rosters[a]==arm_rosters['A'] for a in 'BCD')
    check(name+'/four_arm_block_count_consistent',complete_blocks==len(blocks),roster_equal)
    if main:
        check('main/completed_task_replicate_blocks_four_arm_complete',complete_blocks,len(blocks))
        check('main/completed_arm_rosters_equal',roster_equal,True)
    source=lambda ts: dict(Counter(tasks[t]['record']['source'] for t in ts))
    result={'interpretation':'completed-subset descriptive only' if main else 'development only; do not pool with main',
        'frozen_sessions':len(jobs),'run_directories':len(actual),'completed_sessions':len(rows),
        'incomplete_directories':incomplete,'not_started_count':len(not_started),'not_started_jobs':not_started,
        'distinct_completed_tasks':len({r['task_id'] for r in rows}),
        'distinct_completed_families':len(groups),'complete_12_session_families':full,
        'family_count_basis':'campaign frozen tasks.json family_id; not remapped to later families-final',
        'completed_task_replicate_blocks':len(blocks),
        'complete4armblocks':complete_blocks,'roster_equal':roster_equal,
        'completed_task_replicate_block_details':[{'task_id':t,'replicate':rep,'arms':sorted(arms)} for (t,rep),arms in sorted(blocks.items())],
        'pairing_interpretation':'Four-arm pairing is assessed at task x replicate; this differs from all three repetitions per family. Completed-subset pairing does not establish full frozen-matrix completion.',
        'family_session_count_histogram':dict(Counter(len(rs) for rs in groups.values())),
        'totals':rates(rows),'arms':{a:rates([r for r in rows if r['arm']==a]) for a in 'ABCD'},
        'source_counts_frozen_distinct_tasks':source(tasks),
        'source_counts_completed_distinct_tasks':source({r['task_id'] for r in rows}),
        'source_counts_completed_sessions':dict(Counter(tasks[r['task_id']]['record']['source'] for r in rows)),
        'sessions':sessions}
    if main:
        audit=read(root/'prelaunch-audit.json'); snapshot=read(root/'snapshot_manifest.json')
        family_manifest=read(root/'family_manifest.json')
        check('main/frozen_splits',sorted({t['split'] for t in tasks.values()}),['test'])
        for tid,t in tasks.items():
            check('main/family_assignment/'+tid,{'family_id':t['family_id'],'split':t['split']},family_manifest['tasks'][tid])
            check('main/frozen_12_sessions/'+tid,sorted((j['arm'],j['replicate']) for j in jobs if j['task_id']==tid),sorted((a,i) for a in 'ABCD' for i in range(3)))
        check('main/prelaunch_hash',digest(canonical(audit)),manifest['prelaunch_audit_sha256'])
        check('main/snapshot_receipt_hash',digest(canonical(snapshot)),manifest['framework_snapshot_sha256'])
        for key in ['jobs_sha256','tasks_sha256','framework_snapshot_sha256']: check('main/audit/'+key,audit[key],manifest[key])
        check('main/prelaunch_ids',sorted(audit['ids']),sorted(tasks))
        check('main/no_outcomes_at_prelaunch',audit['no_main_outcomes_exist'],True)
        check('main/prelaunch_family_count',audit['test_family_count'],len({t['family_id'] for t in tasks.values()}))
        check('main/snapshot_source_inventory',snapshot['source_hashes'],manifest['source_hashes'])
        check('main/snapshot_artifact_inventory',snapshot['artifact_hashes'],manifest['artifact_hashes'])
        for path, expected in manifest['source_hashes'].items():
            frozen=root/'framework_snapshot'/path
            check('main/frozen_source/'+path,text_hash(frozen),expected)
            check('main/frozen_source_bytes/'+path,INDEX[frozen.relative_to(ROOT).as_posix()]['sha256_bytes'],snapshot['source_byte_sha256'][path])
            check('main/current_source/'+path,text_hash(ROOT/path),expected,False)
        for path, expected in manifest['artifact_hashes'].items():
            check('main/frozen_binary/'+path,hashlib.sha256(register(root/'framework_snapshot'/path)).hexdigest(),expected)
            check('main/current_binary/'+path,hashlib.sha256(register(ROOT/path)).hexdigest(),expected,False)
        for path,expected in audit['artifact_raw_sha256'].items():
            check('main/prelaunch_artifact/'+path,hashlib.sha256(register(ROOT/path)).hexdigest(),expected)
        for tid,t in tasks.items():
            check('main/task_record/'+tid,digest(canonical(t['record'])),t['task']['record_sha256'])
        scheduler,following=stored._scheduler(rows)
        helpers,_=_helper_and_scheduler_cases(rows,tasks,audit['structural_strata'])
        events=[]; closed_losses=[]; following_exceptions=[]
        for row in rows:
            previous={}
            for rr in row['rounds']:
                if row['arm']=='D' and rr.get('selected_target') is not None and rr.get('target_followed') is not True:
                    following_exceptions.append({'identity':list(stored._identity(row)),'action':rr['action'],
                        'selected_target':rr.get('selected_target'),'target_followed':rr.get('target_followed'),
                        'changed_declarations':rr.get('changed_declarations'),'stop_reason':row['stop_reason']})
                s=rr.get('scheduler_audit') or {}
                if len(set(s.get('open_editable_targets',[])))>=2 or s.get('target_disagreement'):
                    events.append({'identity':list(stored._identity(row)),'action':rr['action'],
                        'scheduler_audit':s,'selected_target':rr.get('selected_target'),'target_followed':rr.get('target_followed'),
                        'final_success':row['success'],'successful_action':row.get('successful_action')})
                current=(rr.get('ledger_after') or {}).get('declarations',{})
                for ident,v in previous.items():
                    if v.get('status')=='closed' and ident in current and current[ident].get('status')!='closed':
                        closed_losses.append({'identity':list(stored._identity(row)),'action':rr['action'],'declaration':ident,
                            'after_status':current[ident].get('status'),'after_local_outcome':current[ident].get('local_outcome')})
                previous=current
        result.update(scheduler=scheduler,d_target_following=following,d_target_following_exceptions=following_exceptions,scheduler_events=events,
            reference_helpers={'definition':'frozen prelaunch structural_strata.extra_helpers: reference declaration IDs absent from frozen skeleton declarations; not generated output',
                'frozen_task_histogram':dict(Counter(v['extra_helpers'] for v in audit['structural_strata'].values()))},
            generated_helpers={'definition':'editable declarations in recorded legal ledger_after minus frozen editable_ids; unavailable is unknown; maximum over known rounds',
                'sessions':helpers,'max_observed_histogram':dict(Counter(str(h['max_observed_generated_helpers']) for h in helpers))},
            proof_regressions={'runner_metric_total':sum(r['ledger_metrics']['proof_regressions'] for r in rows),
                'reporting_sessions':len(rows),'definition':'runner records previously closed declaration with later local failure; narrower than all closed-to-nonclosed transitions',
                'consecutive_ledger_closed_to_nonclosed_events':closed_losses})
    return result

def probe():
    root=ROOT/'logs/evidence-semantics-probe-20261009'
    plan=read(root/'plan.json'); rows=read(root/'results.json'); by=defaultdict(list)
    check('probe/plan_model_requests',plan['model_requests'],0)
    check('probe/jobs',len(rows),len(plan['jobs']))
    check('probe/script',text_hash(root/'probe.py'),plan['script_sha256'])
    for path, expected in plan['source_hashes'].items(): check('probe/current_source/'+path,text_hash(ROOT/path),expected,False)
    individual=sorted(root.glob('[0-9][0-9][0-9]_*.json'))
    check('probe/individual_records',digest(canonical([read(p) for p in individual])),digest(canonical(rows)))
    for row,job in zip(rows,plan['jobs']):
        check('probe/job/'+str(job),row['job'],job)
        check('probe/source/'+row['case']['id'],text_hash(root/(row['case']['id']+'.dfy')),row['case']['source_sha256'])
        by[row['case']['id']].append(row)
    witnesses=read(root/'witnesses/results.json'); anchor=read(root/'witness_anchor/results.json')
    wp=read(root/'witnesses/plan.json'); ap=read(root/'witness_anchor/plan.json')
    for data,label in [(wp,'witnesses'),(ap,'witness_anchor')]: check('probe/'+label+'/model_calls',data['model_calls'],0)
    for row in witnesses: check('probe/witness_record/'+row['id']+str(row['replicate']),digest(canonical(read(root/'witnesses'/f"{row['id']}_{row['replicate']}.json"))),digest(canonical(row)))
    for row in anchor: check('probe/anchor_record/'+str(row['replicate']),digest(canonical(read(root/'witness_anchor'/f"copy_{row['replicate']}.json"))),digest(canonical(row)))
    check('probe/witness_script',text_hash(root/'witness.py'),wp['script_sha256'])
    check('probe/anchor_script',text_hash(root/'witness_anchor.py'),ap['script_sha256'])
    for c in wp['cases']: check('probe/witness_source/'+c['id'],text_hash(root/'witnesses'/(c['id']+'.dfy')),c['source_sha256'])
    check('probe/anchor_source',text_hash(root/'witness_anchor/copy.dfy'),ap['source_sha256'])
    allrows=rows+witnesses+anchor
    for i,row in enumerate(allrows):
        check('probe/real_executed/'+str(i),[row['evidence']['real_verifier'],row['evidence']['executed']],[True,True])
    ambiguity=[]
    for family in ['count','copy']:
        good,bad,hgood,hbad=[by[family+'_'+s][0] for s in ['bug0_hint0','bug1_hint0','bug0_hint1','bug1_hint1']]
        ambiguity.append({'family':family,'parsed_diagnostics_equal':good['evidence']['diagnostics']==bad['evidence']['diagnostics'],
            'unhinted_statuses':[good['evidence']['status'],bad['evidence']['status']],
            'hinted_statuses':[hgood['evidence']['status'],hbad['evidence']['status']],
            'bad_unhinted_categories':bad['coarse_diagnostics'],'bad_hinted_categories':hbad['coarse_diagnostics'],
            'evidence_case_ids':[r['case']['id'] for r in [good,bad,hgood,hbad]]})
    closures=[]
    for ident,pair in sorted(by.items()):
        row=pair[0]
        if row['case']['family']=='modular_chain': graph=row['case']['authored_call_graph']
        elif ident=='search_10': graph={'LowerBound':[],'Locate':['LowerBound']}
        else: continue
        batches=row['evidence']['obligations']
        def passed(n):return batches.get(n+' (correctness)')=='passed' and batches.get(n+' (well-formedness)','passed')=='passed'
        for name in graph:
            todo=[name];seen=set();blocked=[]
            while todo:
                node=todo.pop()
                if node in seen:continue
                seen.add(node)
                if not passed(node):blocked.append(node)
                todo.extend(graph[node])
            closures.append({'case':ident,'method':name,'local_passed':passed(name),'authored_dependency_blockers':sorted(blocked)})
    stable=sum(all(pair[0]['evidence'][f]==pair[1]['evidence'][f] for f in ['status','obligations','diagnostics']) for pair in by.values())
    result={'interpretation':'authored mechanism diagnostics, not model-generated policy/effect experiment',
        'verifier_calls':len(allrows),'phase_counts':[len(rows),len(witnesses),len(anchor)],
        'model_requests_recorded':0,'model_zero_basis':'all three plans declare zero; scripts inspected and records contain verifier evidence only; not proof of all external activity',
        'status_counts':dict(Counter(r['evidence']['status'] for r in allrows)),
        'variants_initial':len(by),'stable_two_repeat_variants':stable,
        'ambiguity_and_error_migration':ambiguity,'closure_annotations':closures,
        'local_passed_with_unclosed_dependency_count':sum(r['local_passed'] and bool(r['authored_dependency_blockers']) for r in closures),
        'limitations':['Authored acyclic graph, not general inferred VC dependency graph.',
            'Two repeats assess local replay stability, not independent task replication.',
            'Posthoc witness/anchor diagnostics do not count as solutions to original task contracts.',
            'Current production-source differences are reported without rerunning historical scripts.']}
    final=read(root/'final_audit.json')
    check('probe/final_count',result['verifier_calls'],final['real_verifier_calls'])
    check('probe/final_statuses',result['status_counts'],final['statuses'])
    return result

def main():
    register(Path(__file__))
    for name in ['generation/public_benchmark/analyze.py','research/analyze_main_public_20261009.py']: register(ROOT/name)
    result={'schema_version':1,'extracted_utc':datetime.now(timezone.utc).isoformat(),
        'scope':'read-only local audit; no new experiments; no human review claimed; full-matrix analyzer not invoked',
        'main':campaign('main-v3',True),'development_v2':campaign('development-v2'),
        'canary_v1':campaign('canary-v1'),'mechanism_probe':probe()}
    fm=read(ROOT/'logs/public-codegen-20261009/families-final/manifest.json')
    fams={v['family_id']:v['split'] for v in fm['tasks'].values()}
    result['families_final']={'admitted_tasks':len(fm['tasks']),'families':len(fams),
        'family_split_counts':dict(Counter(fams.values())),
        'task_split_counts':dict(Counter(v['split'] for v in fm['tasks'].values())),
        'test_representatives':len(fm['test_representatives']),
        'no_generation_outcomes_used_recorded':fm['no_generation_outcomes_used']}
    for key in ['development_v2','canary_v1']:
        cohort=result[key]
        ids={row['task_id'] for row in cohort['sessions']}
        missing=sorted(ids-set(fm['tasks']))
        check(key+'/final_family_mapping_available',missing,[])
        cohort['distinct_completed_families_under_final_mapping']=len({fm['tasks'][tid]['family_id'] for tid in ids})
        cohort['final_family_mapping_source']='logs/public-codegen-20261009/families-final/manifest.json; supplementary remapping only; frozen count retained'
    result['checks']=CHECKS
    result['check_summary']={'checks':len(CHECKS),'passed':sum(c['passed'] for c in CHECKS),
        'mismatches':[c for c in CHECKS if not c['passed']]}
    result['evidence_files']=INDEX
    result['limitations']=['416 completed sessions are a completion-conditioned subset of 1392 frozen sessions, not full ITT.',
        'The completed subset contains 104 task x replicate blocks, all with A/B/C/D, and equal arm task-replicate rosters. Four-arm pairing is intact at that level; only 4 of the 75 observed families have all three repetitions (12 sessions). This does not support claiming the full preregistered family matrix is complete.',
        'Runs, arms and repeats share tasks/families; session counts are not independent sample sizes.',
        'Incomplete directories prove started artifacts exist, not that a process is currently running.',
        'Frozen source requested model identity is not independently observed backend identity.',
        'Verification success pertains to admitted fixed formal contracts, not general functional correctness.',
        'Scheduler same-state recommendations do not identify counterfactual outcome or causal benefit.',
        'File hashes verify local consistency, not independent authenticity or manual review.']
    (OUT/'evidence_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    m=result['main']; s=m['scheduler']; p=result['mechanism_probe']
    lines=['# 本地证据审计（2026-10-12）','',
        '仅重新读取已有工件；没有模型调用或验证器实验，没有运行要求完整主矩阵的分析入口。此为自动一致性核验，不是人工复核。','',
        f"主矩阵冻结 {m['frozen_sessions']} 会话；现有 {m['run_directories']} 个目录，其中完成 {m['completed_sessions']}、无终结 result {len(m['incomplete_directories'])}、未建目录 {m['not_started_count']}。无 result 不等于后台仍在运行。",
        f"已完成子集：{m['totals']['successes']} 成功，{m['totals']['model_calls']} 模型调用，{m['distinct_completed_tasks']} 题/{m['distinct_completed_families']} 族。共有 {m['completed_task_replicate_blocks']} 个任务×重复块，其中 {m['complete4armblocks']} 个四组齐全，各组任务×重复名单相同（{m['roster_equal']}）；因此这个层面的四组配对完整。仅 {len(m['complete_12_session_families'])} 族具备四组各三次的完整12会话，题族重复覆盖尚不完整。此完成子集可作明确标注的配对描述，但不能冒充完整冻结矩阵 ITT 或预定主检验。",'',
        '| 组 | 完成 | 首轮成功 | 修复后成功 | 最终成功 | 模型调用 |','|---|---:|---:|---:|---:|---:|']
    for a,v in m['arms'].items(): lines.append(f"| {a} | {v['sessions']} | {v['first_action_successes']} | {v['repair_successes']} | {v['successes']} | {v['model_calls']} |")
    lines += ['',f"失败原因：{m['totals']['failure_reasons']}。所有完成结果通过现有 analyze._trial 核对 result、manifest、artifact 哈希和 action 轨迹；冻结 roster、tasks、family、prelaunch、framework snapshot 另行校验。",'',
        f"调度审计 {s['audited_rounds']}/{s['total_rounds']} 轮；多候选机会 {s['opportunity_rounds']} 轮，同状态建议分歧 {s['counterfactual_disagreement_rounds']} 轮。逐轮来源及真实 selected_target 见 JSON scheduler_events。机会来自 DT0023 四组和 DA0087 的 B 组；全部分歧来自 DT0023。D 实际遇到的分歧仅一轮，不能支持总体有效性。",
        f"D target-following：{m['d_target_following']}。参考额外 helper 和实际生成 helper 使用不同定义，详见 JSON。runner closed 回退计数 {m['proof_regressions']['runner_metric_total']}，逐轮更宽口径 closed→nonclosed 事件 {len(m['proof_regressions']['consecutive_ledger_closed_to_nonclosed_events'])}。",'',
        f"开发 development-v2：{result['development_v2']['totals']['successes']}/{result['development_v2']['completed_sessions']}；canary-v1：{result['canary_v1']['totals']['successes']}/{result['canary_v1']['completed_sessions']}。不可与主矩阵合并。最终去重族清单：{result['families_final']}。",'',
        f"开发集题族数量按当时冻结 tasks.json 为 {result['development_v2']['distinct_completed_families']}；若仅为解释而套用 families-final 映射，则为 {result['development_v2']['distinct_completed_families_under_final_mapping']}。保留两种口径及来源，不静默替换历史分母。",'',
        f"旧机制诊断工件复算：{p['verifier_calls']} 次验证（{p['phase_counts']}），记录模型请求0；{p['status_counts']}；初始30变体两次重复，{p['stable_two_repeat_variants']} 变体的解析状态/义务/诊断一致。count、copy 两组反例支持诊断本身不能区分实现错误与证明缺口，并显示加提示后后置条件报错可迁移到 invariant；{p['local_passed_with_unclosed_dependency_count']} 个局部通过批次在人工编写的依赖图上仍有失败依赖。这些是存在性机制例证，不是方法效果或发生率估计。",'',
        '全部来源路径、文件 SHA-256、逐条核对结果、分母和局限均在 evidence_audit.json。SHA-256 只证明本地工件一致性；不能证明外部真实性或人工复核。', '',
        f"检查 {len(CHECKS)} 项，通过 {sum(c['passed'] for c in CHECKS)}；非致命历史/当前源码差异 {sum(not c['passed'] for c in CHECKS)} 项（详见 check_summary）。",'',
        '复现：从项目根执行 `.venv/Scripts/python.exe -B papers/evidence-guided-codegen-20261012/evidence/extract_evidence.py`。输出仅写本证据目录。']
    (OUT/'audit.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps({'main':m['totals'],'completed':m['completed_sessions'],'families':m['distinct_completed_families'],
        'full_families':len(m['complete_12_session_families']),'scheduler':s,'following':m['d_target_following'],
        'helpers':m['generated_helpers']['max_observed_histogram'],'checks':result['check_summary'],
        'evidence_files':len(INDEX)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
