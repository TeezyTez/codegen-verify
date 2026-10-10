"""Read-only analysis of frozen completed campaigns or one completed trial."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path

from .results import paired_summary
from .task import canonical, digest

ACTION_THRESHOLDS=(1,2,4,8,12)
TOKEN_THRESHOLDS=(16000,32000,64000,128000,240000)


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _identity(row):
    return row['model'],row['task_id'],row['replicate'],row['arm']


def _trial(root):
    root=root.resolve()
    row=_read(root/'result.json'); manifest=_read(root/'manifest.json')
    if row.get('complete') is not True:
        raise ValueError('analysis requires completed trial records')
    if type(row.get('success')) is not bool:
        raise ValueError('trial success must be an explicit boolean')
    if digest(canonical(row))!=(root/'result.sha256').read_text().strip():
        raise ValueError('trial result digest differs')
    if row.get('manifest_sha256')!=digest(canonical(manifest)):
        raise ValueError('trial manifest digest differs')
    expected=(manifest['model'].get('model',manifest['model'].get('name','unknown')),
              manifest['task']['id'],manifest['replicate'],manifest['arm'])
    if _identity(row)!=expected:
        raise ValueError('trial identity differs from manifest')
    for relative,expected_hash in row.get('artifact_sha256',{}).items():
        path=(root/relative).resolve()
        if root not in path.parents or not path.is_file() or digest(path.read_text(encoding='utf-8'))!=expected_hash:
            raise ValueError('trial artifact digest differs')
    rounds=row.get('rounds',[])
    if len(rounds)!=row['model_calls'] or [r['action'] for r in rounds]!=list(range(1,len(rounds)+1)):
        raise ValueError('trial action trace differs from model-call count')
    if row['success'] and (type(row.get('successful_action')) is not int or not 1<=row['successful_action']<=len(rounds)):
        raise ValueError('successful trial lacks valid successful_action')
    return row,manifest


def _load(root):
    if not (root/'jobs.json').exists():
        row,manifest=_trial(root)
        return [row],{'kind':'single_trial','phase':'single_trial_unspecified','stage':'unspecified',
                      'family_mapping_source':'trial.result.json','exact_roster_verified':True,
                      'expected_identities':[_identity(row)],'manifest':manifest,'family_overrides':0}
    manifest=_read(root/'manifest.json'); jobs=_read(root/'jobs.json'); tasks=_read(root/'tasks.json')
    if manifest['jobs_sha256']!=digest(canonical(jobs)) or manifest['tasks_sha256']!=digest(canonical(tasks)):
        raise ValueError('campaign roster or frozen tasks digest differs')
    if manifest.get('family_manifest_sha256') is not None:
        if digest(canonical(_read(root/'family_manifest.json')))!=manifest['family_manifest_sha256']:
            raise ValueError('frozen family manifest digest differs')
    model=manifest['model'].get('model',manifest['model'].get('name','unknown'))
    expected=[(model,j['task_id'],j['replicate'],j['arm']) for j in jobs]
    directories=[j['directory'] for j in jobs]
    if (not jobs or len(set(expected))!=len(expected) or len(set(directories))!=len(directories)
            or len(jobs)!=manifest['expected_sessions'] or any(j['arm'] not in {'A','B','C','D'} for j in jobs)):
        raise ValueError('invalid or duplicate frozen job roster')
    if set(j['task_id'] for j in jobs)!=set(tasks):
        raise ValueError('frozen tasks and roster differ')
    actual_directories={p.name for p in (root/'runs').iterdir() if p.is_dir()}
    if actual_directories!=set(directories):
        raise ValueError('run directories do not exactly match roster')
    saved=_read(root/'results.json')
    actual=[_identity(row) for row in saved]
    if len(actual)!=len(expected) or len(set(actual))!=len(actual) or set(actual)!=set(expected):
        raise ValueError('aggregate results do not exactly match frozen roster')
    indexed={_identity(row):row for row in saved}
    rows=[]; overrides=0
    for job,key in zip(jobs,expected):
        folder=(root/'runs'/job['directory']).resolve()
        if folder.parent!=(root/'runs').resolve():
            raise ValueError('unsafe job directory')
        row,_=_trial(folder)
        if _identity(row)!=key or row!=indexed[key]:
            raise ValueError('per-trial result differs from roster or aggregate result')
        family=tasks[job['task_id']].get('family_id')
        if not isinstance(family,str) or not family.strip():
            raise ValueError('missing frozen family assignment')
        overrides+=int(row.get('family_id')!=family)
        row=deepcopy(row); row['family_id']=family
        rows.append(row)
    phase=manifest.get('phase','unspecified')
    splits={row.get('split') for row in tasks.values()}
    stage='development' if phase.startswith('development_') else 'test' if splits=={'test'} else 'unspecified'
    return rows,{'kind':'campaign','phase':phase,'stage':stage,'family_mapping_source':'campaign.tasks.json',
                 'exact_roster_verified':True,'expected_identities':expected,'manifest':manifest,'family_overrides':overrides}


def _rate(n,d):
    return n/d if d else None


def _known(value):
    return type(value) is int and value>=0


def _success_tokens(row):
    if not row['success']:
        return None
    subtotal=0
    for round_ in row['rounds'][:row['successful_action']]:
        generation=round_.get('generation',{})
        if not all(_known(generation.get(k)) for k in ('input_tokens','output_tokens')):
            return None
        subtotal+=generation['input_tokens']+generation['output_tokens']
    return subtotal


def _usage(rows):
    fields=defaultdict(lambda:{'reported_sum':0,'reported_calls':0})
    calls=[]; unknown=0
    for row in rows:
        for round_ in row['rounds']:
            generation=round_.get('generation',{})
            known=all(_known(generation.get(k)) for k in ('input_tokens','output_tokens'))
            unknown+=int(not known)
            raw=generation.get('usage')
            for key,value in (raw if isinstance(raw,dict) else {}).items():
                if _known(value):
                    fields[key]['reported_sum']+=value; fields[key]['reported_calls']+=1
            calls.append({'identity':list(_identity(row)),'action':round_['action'],
                          'input_tokens':generation.get('input_tokens'),'output_tokens':generation.get('output_tokens'),
                          'raw_usage':raw,'usage_source':generation.get('usage_source','unavailable')})
    return {'model_calls':len(calls),'unknown_usage_calls':unknown,
            'all_calls_have_reported_input_output':unknown==0,
            'reported_input_tokens':sum(c['input_tokens'] for c in calls if _known(c['input_tokens'])),
            'reported_output_tokens':sum(c['output_tokens'] for c in calls if _known(c['output_tokens'])),
            'raw_fields':dict(fields),'calls':calls,
            'note':'Reported subtotals only; missing usage is never imputed as zero. Cached/reasoning fields are not added again to input/output totals.'}


def _scheduler(rows):
    total=audited=opportunities=disagreements=opportunity_disagreements=0
    following=followed=missing_follow=0
    for row in rows:
        for round_ in row['rounds']:
            total+=1
            audit=round_.get('scheduler_audit')
            if isinstance(audit,dict) and isinstance(audit.get('open_editable_targets'),list):
                audited+=1
                opportunity=len(set(audit['open_editable_targets']))>=2
                disagree=(audit.get('structural_target') or {}).get('id')!=(audit.get('evidence_target') or {}).get('id')
                if audit.get('target_disagreement') is not disagree:
                    raise ValueError('scheduler disagreement flag contradicts recorded targets')
                opportunities+=int(opportunity); disagreements+=int(disagree)
                opportunity_disagreements+=int(opportunity and disagree)
            if row['arm']=='D' and round_.get('selected_target') is not None:
                if type(round_.get('target_followed')) is bool:
                    following+=1; followed+=int(round_['target_followed'])
                else: missing_follow+=1
    status='unavailable' if not audited else 'complete' if audited==total else 'partial'
    return ({'availability':status,'total_rounds':total,'audited_rounds':audited,'missing_rounds':total-audited,
             'opportunity_rounds':opportunities if audited else None,
             'counterfactual_disagreement_rounds':disagreements if audited else None,
             'opportunity_disagreement_rounds':opportunity_disagreements if audited else None,
             'opportunity_rate':_rate(opportunities,audited),
             'counterfactual_disagreement_rate':_rate(disagreements,audited),
             'opportunity_disagreement_rate':_rate(opportunity_disagreements,opportunities),
             'interpretation':'C and D recommendations evaluated on each same recorded state; this is not a counterfactual outcome estimate.'},
            {'availability':'unavailable' if not following else 'partial' if missing_follow else 'complete',
             'audited_targeted_rounds':following,'missing_targeted_rounds':missing_follow,
             'followed':followed if following else None,'rate':_rate(followed,following)})


def analyze(directory, *, bootstrap=10000, seed=20261009):
    """Validate stored evidence only. Never launches a model or verifier."""
    if type(bootstrap) is not int or bootstrap<2:
        raise ValueError('bootstrap must be at least two')
    root=Path(directory).resolve()
    rows,context=_load(root)
    arms={}
    for arm in 'ABCD':
        selected=[r for r in rows if r['arm']==arm]
        if not selected: continue
        successes=sum(bool(r['success']) for r in selected)
        eligible=[r for r in selected if r.get('research_eligible')]
        curves={str(t):{'successes':sum(r['success'] and r['successful_action']<=t for r in selected),
                       'denominator':len(selected)} for t in ACTION_THRESHOLDS}
        token_curves={}
        for threshold in TOKEN_THRESHOLDS:
            count=sum(r['success'] and _success_tokens(r) is not None and _success_tokens(r)<=threshold for r in selected)
            unknown=sum(r['success'] and _success_tokens(r) is None for r in selected)
            token_curves[str(threshold)]={'successes':count,'denominator':len(selected),
                'unknown_successes':unknown,'rate':_rate(count,len(selected))}
        for curve in curves.values(): curve['rate']=_rate(curve['successes'],curve['denominator'])
        arm_usage=_usage(selected)
        arm_usage.pop('calls')
        arm_scheduler,_=_scheduler(selected)
        arms[arm]={'sessions':len(selected),'families':len({r['family_id'] for r in selected}),
                   'successes':successes,'itt_success_rate':_rate(successes,len(selected)),
                   'research_eligible_sessions':len(eligible),
                   'research_eligible_success_rate':_rate(sum(bool(r['success']) for r in eligible),len(eligible)),
                   'usage':arm_usage,'scheduler':arm_scheduler,
                   'action_success_curve':curves,'token_success_curve':token_curves,
                   'stop_reasons':dict(Counter(r['stop_reason'] for r in selected)),
                   'model_calls':sum(r['model_calls'] for r in selected),
                   'verifier_calls':sum(r['verifier_calls'] for r in selected),
                   'session_seconds_sum':sum(r.get('seconds',0) for r in selected),
                   'verifier_seconds_sum':sum(r.get('verifier_seconds',0) for r in selected)}
    scheduler,following=_scheduler(rows)
    regressions=[r.get('ledger_metrics',{}).get('proof_regressions') for r in rows]
    known_regressions=[x for x in regressions if _known(x)]
    limitations=['这是冻结队列的已记录结果分析，不表示完整研究已经完成。',
                 '会话 ITT 分母包含该队列全部已完成任务；基础设施失败不免费重抽。',
                 '重复、四组及同题族任务并非独立样本；配对分析按冻结题族汇总。',
                 '验证通过仅表示固定形式规约下通过，不等于自然语言充分性或完整软件正确性。',
                 'Token 曲线使用成功前报告的累计 input+output；未知用量单列，缓存和推理字段不重复相加。',
                 '同状态 C/D 建议分歧仅是调度机制证据，不是反事实成功率或因果效果。']
    if context['stage']=='development': limitations.append('本队列属于开发阶段，所有比较均为描述性结果，不能作为正式确认性结论。')
    if scheduler['availability']!='complete': limitations.append('部分或全部旧记录缺少 scheduler_audit；调度机会与同状态分歧不可据此填零。')
    if any(not r.get('research_eligible') for r in rows): limitations.append('包含非研究合格记录；操作汇总与 research_eligible 配对统计分开报告。')
    paired=paired_summary(rows,expected_sessions=len(context['expected_identities']),
                          expected_identities=context['expected_identities'],bootstrap=bootstrap,seed=seed)
    return {'schema_version':1,'source_directory':str(root),'kind':context['kind'],'phase':context['phase'],
            'stage':context['stage'],'study_complete_claim':False,'exact_roster_verified':True,
            'recorded_sessions':len(rows),'expected_sessions':len(context['expected_identities']),
            'successes':sum(bool(r['success']) for r in rows),'task_count':len({r['task_id'] for r in rows}),
            'family_count':len({r['family_id'] for r in rows}),'model_count':len({r['model'] for r in rows}),
            'family_mapping_source':context['family_mapping_source'],'family_assignment_overrides':context['family_overrides'],
            'model_calls':sum(r['model_calls'] for r in rows),'verifier_calls':sum(r['verifier_calls'] for r in rows),
            'stop_reasons':dict(Counter(r['stop_reason'] for r in rows)),
            'arms':arms,'usage':_usage(rows),'scheduler':scheduler,'d_target_following':following,
            'proof_regressions':{'availability':'unavailable' if not known_regressions else 'complete' if len(known_regressions)==len(rows) else 'partial',
                                 'reported_total':sum(known_regressions) if known_regressions else None,
                                 'reporting_sessions':len(known_regressions)},
            'paired':paired,'limitations':limitations,
            'trials':[{'identity':list(_identity(r)),'task_id':r['task_id'],'family_id':r['family_id'],
                       'success':r['success'],'successful_action':r.get('successful_action'),
                       'tokens_to_success':_success_tokens(r),'research_eligible':r.get('research_eligible',False)} for r in rows]}


def render_markdown(summary):
    phase={'development':'开发阶段','test':'正式测试队列','unspecified':'阶段未指定'}[summary['stage']]
    lines=[f"# 代码生成队列分析：{summary['phase']}",'',
           f"{phase}；冻结名单已精确核对。共 {summary['recorded_sessions']} 个会话、{summary['task_count']} 道任务、"
           f"{summary['family_count']} 个题族。此报告不宣称完整研究完成。",'',
           '| 组 | 成功 / ITT 会话 | 成功率 | 模型调用 | 验证调用 |','|---|---:|---:|---:|---:|']
    for arm,row in summary['arms'].items():
        lines.append(f"| {arm} | {row['successes']} / {row['sessions']} | {row['itt_success_rate']:.1%} | {row['model_calls']} | {row['verifier_calls']} |")
    lines+=['','行动累计成功率（固定会话分母）：','',
            '| 组 | 1 | 2 | 4 | 8 | 12 |','|---|---:|---:|---:|---:|---:|']
    for arm,row in summary['arms'].items():
        lines.append('| '+arm+' | '+' | '.join(f"{row['action_success_curve'][str(t)]['rate']:.1%}" for t in ACTION_THRESHOLDS)+' |')
    lines+=['','Token 阈值累计成功率（实际 input+output；未知用量成功不计入已知阈值）：','',
            '| 组 | 16,000 | 32,000 | 64,000 | 128,000 | 240,000 |','|---|---:|---:|---:|---:|---:|']
    for arm,row in summary['arms'].items():
        lines.append('| '+arm+' | '+' | '.join(f"{row['token_success_curve'][str(t)]['rate']:.1%}" for t in TOKEN_THRESHOLDS)+' |')
    usage=summary['usage']; scheduler=summary['scheduler']; following=summary['d_target_following']
    lines+=['',f"已报告输入 {usage['reported_input_tokens']:,}、输出 {usage['reported_output_tokens']:,} token；"
            f"未知用量调用 {usage['unknown_usage_calls']}。停止原因：{json.dumps(summary['stop_reasons'],ensure_ascii=False)}。"]
    if scheduler['availability']=='unavailable':
        lines+=['','调度审计不可用：旧记录没有 scheduler_audit，不能将机会或分歧解释为零。']
    else:
        lines+=['',f"调度审计覆盖 {scheduler['audited_rounds']}/{scheduler['total_rounds']} 轮；"
                f"至少两个可编辑未闭合目标的机会 {scheduler['opportunity_rounds']} 轮，"
                f"同状态 C/D 建议分歧 {scheduler['counterfactual_disagreement_rounds']} 轮。"]
    lines += [f"D 目标遵循：{following['followed'] if following['followed'] is not None else '不可用'} / "
              f"{following['audited_targeted_rounds']} 个有记录目标轮次；证明回退累计："
              f"{summary['proof_regressions']['reported_total'] if summary['proof_regressions']['reported_total'] is not None else '不可用'}。",'',
              '配对题族比较（按模型分别报告；区间与方法见 summary.json）：','']
    for model,model_rows in summary['paired']['models'].items():
        for name in ('D-C','D-A'):
            contrast=model_rows['contrasts'][name]
            lo,hi=contrast['interval']
            lines.append(f"- {model}，{name}：{contrast['difference']:+.1%}；区间 [{lo:+.1%}, {hi:+.1%}]，{model_rows['families']} 个配对题族。")
    lines+=['','限制：','']+['- '+item for item in summary['limitations']]
    return '\n'.join(lines)+'\n'


def write_analysis(directory, output_dir, *, bootstrap=10000, seed=20261009):
    root=Path(directory).resolve(); output=Path(output_dir).resolve()
    if output==root or root in output.parents:
        raise ValueError('analysis output must be outside the read-only source directory')
    if output.exists(): raise FileExistsError('analysis output already exists')
    summary=analyze(root,bootstrap=bootstrap,seed=seed)
    output.mkdir(parents=True,exist_ok=False)
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2),encoding='utf-8')
    (output/'report.zh.md').write_text(render_markdown(summary),encoding='utf-8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--bootstrap',type=int,default=10000)
    args=parser.parse_args()
    result=write_analysis(args.directory,args.output,bootstrap=args.bootstrap)
    print(json.dumps({k:result[k] for k in ('phase','recorded_sessions','successes','family_count','exact_roster_verified')},ensure_ascii=False))
