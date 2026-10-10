"""Read-only, complete-roster ITT analysis; never launches models or verifiers.

Run only after campaign completion: python -m research.analyze_main_public_20261009
CAMPAIGN --output NEW_EXTERNAL_DIRECTORY. Original result eligibility is retained.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path

from generation.public_benchmark import analyze as stored
from generation.public_benchmark.results import paired_summary
from generation.public_benchmark.task import canonical, digest

INFRA_REASONS = frozenset({'model_infrastructure_failure', 'unknown_model_usage',
    'structure_infrastructure_failure', 'verifier_infrastructure_failure',
    'runner_infrastructure_failure'})
ITT_NOTE = ('主分析按冻结协议保留完整派发名单，包括基础设施失败；仅在分析副本中设置 '
            'research_eligible=True 以复用族配对函数，不改原结果。这是协议口径落实，'
            '不是根据观察效果更改分析。原运行器不会因基础设施失败自动清除该字段；'
            '是否影响本轮分母另据实际记录报告。')


def _read(path):
    return json.loads(path.read_text(encoding='utf8'))


def _paired(rows, bootstrap, seed, *, first=False):
    copied = deepcopy(rows)
    for row in copied:
        row['research_eligible'] = True
        if first:
            row['success'] = row['success'] and row.get('successful_action') == 1
    result = paired_summary(copied, expected_sessions=len(copied),
        expected_identities=[stored._identity(r) for r in copied], bootstrap=bootstrap, seed=seed)
    result['analysis_population'] = 'all supplied frozen-roster sessions; eligibility override on copies only'
    return result


def _rates(rows):
    n = len(rows)
    success = sum(r['success'] for r in rows)
    first = sum(r['success'] and r.get('successful_action') == 1 for r in rows)
    return {'sessions': n, 'successes': success, 'final_rate': success/n if n else None,
            'first_action_successes': first, 'first_action_rate': first/n if n else None,
            'failure_stop_reasons': dict(Counter(r['stop_reason'] for r in rows if not r['success']))}


def _arm_summary(rows):
    result = {}
    for arm in 'ABCD':
        selected = [r for r in rows if r['arm'] == arm]
        rate = _rates(selected)
        n = len(selected)
        rate['action_success_curve'] = {str(t): sum(r['success'] and r['successful_action'] <= t
            for r in selected)/n if n else None for t in stored.ACTION_THRESHOLDS}
        rate['token_success_curve'] = {str(t): {
            'rate': sum(r['success'] and stored._success_tokens(r) is not None and
                        stored._success_tokens(r) <= t for r in selected)/n if n else None,
            'unknown_successes': sum(r['success'] and stored._success_tokens(r) is None for r in selected)}
            for t in stored.TOKEN_THRESHOLDS}
        rate.update(model_calls=sum(r['model_calls'] for r in selected),
                    verifier_calls=sum(r['verifier_calls'] for r in selected),
                    seconds=sum(r.get('seconds', 0) for r in selected))
        result[arm] = rate
    return result


def _prompt_equality(root, rows):
    jobs = _read(root/'jobs.json')
    index = {(j['task_id'], j['replicate'], j['arm']): j for j in jobs}
    by_key = {(r['task_id'], r['replicate'], r['arm']): r for r in rows}
    pairs = []
    for task, rep in sorted({(r['task_id'], r['replicate']) for r in rows}):
        messages = []
        for arm in 'CD':
            key = (task, rep, arm)
            relative = 'round-01/messages.json'
            hashes = {k.replace('\\', '/'): v for k, v in by_key[key].get('artifact_sha256', {}).items()}
            path = root/'runs'/index[key]['directory']/relative
            if relative not in hashes or not path.is_file():
                messages.append(None)
            else:
                if digest(path.read_text(encoding='utf8')) != hashes[relative]:
                    raise ValueError('first message artifact digest differs')
                messages.append(_read(path))
        equal = messages[0] == messages[1] if all(m is not None for m in messages) else None
        pairs.append({'task_id': task, 'replicate': rep, 'equal': equal})
    return {'pairs': pairs, 'equal_pairs': sum(p['equal'] is True for p in pairs),
            'unequal_pairs': sum(p['equal'] is False for p in pairs),
            'unavailable_pairs': sum(p['equal'] is None for p in pairs)}


def _helper_and_scheduler_cases(rows, tasks, strata):
    helpers, cases = [], []
    for row in rows:
        counts, opportunities, disagreements, missing = [], [], [], []
        editable = tasks[row['task_id']].get('editable_ids')
        for round_ in row['rounds']:
            declarations = (round_.get('ledger_after') or {}).get('declarations')
            count = None
            if isinstance(declarations, dict) and isinstance(editable, list):
                values = list(declarations.values())
                if all(type(d.get('editable')) is bool for d in values):
                    total = sum(d['editable'] for d in values)
                    if total >= len(editable):
                        count = total-len(editable)
            counts.append({'action': round_['action'], 'generated_helpers': count})
            audit = round_.get('scheduler_audit')
            if not isinstance(audit, dict) or not isinstance(audit.get('open_editable_targets'), list):
                missing.append(round_['action']); continue
            if len(set(audit['open_editable_targets'])) >= 2:
                opportunities.append(round_['action'])
            if audit.get('target_disagreement') is True:
                disagreements.append(round_['action'])
        known = [c['generated_helpers'] for c in counts if c['generated_helpers'] is not None]
        helpers.append({'identity': list(stored._identity(row)), 'task_id': row['task_id'],
                        'arm': row['arm'], 'reference_extra_helpers': strata[row['task_id']]['extra_helpers'],
                        'round_counts': counts, 'max_observed_generated_helpers': max(known) if known else None,
                        'last_round_generated_helpers': counts[-1]['generated_helpers'] if counts else None,
                        'unknown_rounds': sum(c['generated_helpers'] is None for c in counts)})
        if opportunities or disagreements or missing:
            cases.append({'identity': list(stored._identity(row)), 'success': row['success'],
                          'stop_reason': row['stop_reason'], 'opportunity_actions': opportunities,
                          'disagreement_actions': disagreements, 'missing_audit_actions': missing})
    return helpers, cases


def analyze_completed(directory, *, bootstrap=10000, seed=20261009):
    if type(bootstrap) is not int or bootstrap < 2:
        raise ValueError('bootstrap must be at least two')
    root = Path(directory).resolve()
    # This must run first: validates every completed result, artifact and exact roster.
    rows, context = stored._load(root)
    if context['kind'] != 'campaign' or context['stage'] != 'test':
        raise ValueError('requires a completed test campaign')
    tasks = _read(root/'tasks.json')
    groups = defaultdict(list)
    for row in rows:
        groups[row['family_id']].append(row)
    if len({r['model'] for r in rows}) != 1:
        raise ValueError('this frozen main analysis requires one model')
    for members in groups.values():
        if (len(members) != 12 or len({r['task_id'] for r in members}) != 1 or
            {(r['arm'], r['replicate']) for r in members} != {(a, r) for a in 'ABCD' for r in range(3)}):
            raise ValueError('requires one representative and all twelve sessions per family')
    audit = _read(root/'prelaunch-audit.json')
    manifest = context['manifest']
    if (digest(canonical(audit)) != manifest.get('prelaunch_audit_sha256') or
        any(audit.get(k) != manifest[k] for k in ('jobs_sha256', 'tasks_sha256')) or
        set(audit.get('ids', [])) != set(tasks) or audit.get('no_main_outcomes_exist') is not True or
        audit.get('test_family_count') != len(groups)):
        raise ValueError('prelaunch audit does not match the frozen campaign')
    strata = audit['structural_strata']
    if any(type(strata.get(t, {}).get('extra_helpers')) is not int or strata[t]['extra_helpers'] < 0 for t in tasks):
        raise ValueError('missing frozen prelaunch helper stratum')
    primary = _paired(rows, bootstrap, seed)
    if not primary['complete_matrix']:
        raise ValueError('primary ITT requires the complete matrix')
    sensitivity = {}
    for label, predicate in [
        ('complete_eligible_families', lambda r: r.get('research_eligible') is True),
        ('complete_infrastructure_free_families', lambda r: r['stop_reason'] not in INFRA_REASONS)]:
        included = sorted(f for f, members in groups.items() if all(predicate(r) for r in members))
        selected = [r for r in rows if r['family_id'] in included]
        sensitivity[label] = {'included_families': included, 'excluded_families': sorted(set(groups)-set(included)),
            'paired': _paired(selected, bootstrap, seed), 'interpretation': 'Secondary complete-family sensitivity; never delete individual repetitions.'}
    prompt = _prompt_equality(root, rows)
    helpers, cases = _helper_and_scheduler_cases(rows, tasks, strata)
    scheduler, following = stored._scheduler(rows)
    first = _paired(rows, bootstrap, seed, first=True)
    first['models'] = {model: {'families': data['families'],
        'arm_rates': {a: data['arm_rates'][a] for a in 'CD'}, 'D-C': data['contrasts']['D-C']}
        for model, data in first['models'].items()}
    compact = [{'identity': list(stored._identity(r)), 'task_id': r['task_id'], 'family_id': r['family_id'],
                'success': r['success'], 'successful_action': r.get('successful_action'),
                'research_eligible': r.get('research_eligible'), 'stop_reason': r['stop_reason']} for r in rows]
    exploratory_strata = {}
    for label, positive in [('reference_helpers_0', False), ('reference_helpers_ge1', True)]:
        selected = [r for r in rows if (strata[r['task_id']]['extra_helpers'] >= 1) == positive]
        exploratory_strata[label] = {'sessions': len(selected), 'families': len({r['family_id'] for r in selected}),
                                    'arms': _arm_summary(selected)}
    helper_comparison = {}
    for label, positive in [('reference_helpers_0', False), ('reference_helpers_ge1', True)]:
        selected = [r for r in helpers if (r['reference_extra_helpers'] >= 1) == positive]
        helper_comparison[label] = {}
        for arm in 'ABCD':
            members = [r for r in selected if r['arm'] == arm]
            helper_comparison[label][arm] = {
                'sessions': len(members),
                'unknown_sessions': sum(r['max_observed_generated_helpers'] is None for r in members),
                'observed_zero_helper_sessions': sum(r['max_observed_generated_helpers'] == 0 for r in members),
                'observed_helper_sessions': sum(r['max_observed_generated_helpers'] is not None and
                                                r['max_observed_generated_helpers'] >= 1 for r in members)}
    regressions = [r.get('ledger_metrics', {}).get('proof_regressions') for r in rows]
    known_regressions = [n for n in regressions if type(n) is int and n >= 0]
    return {'schema_version': 1, 'source_directory': str(root), 'phase': context['phase'],
        'exact_roster_verified': True, 'sessions_count': len(rows), 'family_count': len(groups),
        'study_complete_claim': False, 'primary_itt_note': ITT_NOTE, 'primary_itt': primary,
        'original_eligible_filter_would_exclude': sum(not r.get('research_eligible') for r in rows),
        'noneligible_failures': [r for r in compact if not r['research_eligible'] and not r['success']],
        'infrastructure_events': [r for r in compact if r['stop_reason'] in INFRA_REASONS],
        'infrastructure_reason_definition': sorted(INFRA_REASONS),
        'sensitivity_complete_eligible_families': sensitivity['complete_eligible_families'],
        'sensitivity_complete_infrastructure_free_families': sensitivity['complete_infrastructure_free_families'],
        'arms': _arm_summary(rows), 'usage': stored._usage(rows), 'sessions': compact,
        'task_arm_rates': {t: {a: _rates([r for r in rows if r['task_id'] == t and r['arm'] == a])
                              for a in 'ABCD'} for t in sorted(tasks)},
        'exploratory': {'interpretation': 'Strata and mechanisms are exploratory, not additional primary tests.',
            'strata_source': 'hash-bound prelaunch-audit.json structural_strata', 'strata': exploratory_strata,
            'first_action_cd': {'paired': first, 'prompt_equality': prompt,
                'noise_control_valid': prompt['unequal_pairs'] == 0 and prompt['unavailable_pairs'] == 0,
                'interpretation': 'When prompts match, first-action differences reflect sampling/transport variability, not adaptive scheduling.'},
            'scheduler': scheduler, 'd_target_following': following, 'scheduler_cases': cases,
            'generated_vs_reference_helpers': helpers,
            'helper_comparison_by_frozen_stratum_and_arm': helper_comparison,
            'proof_regressions': {'reporting_sessions': len(known_regressions),
                'reported_total': sum(known_regressions) if known_regressions else None,
                'availability': 'complete' if len(known_regressions) == len(rows) else 'partial' if known_regressions else 'unavailable'},
            'helper_interpretation': 'Observed editable declarations minus frozen editable targets; missing legal ledger is unknown. Helper use does not prove algorithmic necessity.'},
        'provenance': {'manifest_sha256': digest(canonical(manifest)), 'prelaunch_audit_sha256': digest(canonical(audit)),
                       'analysis_source_sha256': digest(Path(__file__).read_text(encoding='utf8'))},
        'limitations': ['单一请求模型身份；结果仅覆盖冻结准入代表及预算，不能推广为所有代码生成能力。',
            '输出 token 上限为事后拒绝，未知 usage 不填零；完整成本见逐调用 usage。',
            '敏感性分析按整族排除基础设施事件，可能存在选择偏差，不替代 ITT。',
            '首轮对照、参考 helper 分层与调度案例仅为探索性；缺少选择机会不能证明机制无效。',
            '参考额外 helper 数与生成声明数不同；生成 helper 的观察值不能证明解题必须使用这些声明。']}


def render_markdown(result):
    lines = ['# 冻结主队列 ITT 分析', '',
        f"完整核验 {result['sessions_count']} 会话、{result['family_count']} 题族。此报告不宣称完整研究完成。",
        '', result['primary_itt_note'], '',
        f"原 research_eligible 筛选会排除 {result['original_eligible_filter_would_exclude']} 条；"
        f"指定基础设施停止事件 {len(result['infrastructure_events'])} 条。", '',
        '| 组 | 最终成功 / ITT | 首轮成功率 |', '|---|---:|---:|']
    for arm, row in result['arms'].items():
        lines.append(f"| {arm} | {row['successes']}/{row['sessions']} ({row['final_rate']:.1%}) | {row['first_action_rate']:.1%} |")
    lines += ['', '预定主要族配对比较：', '']
    for model, data in result['primary_itt']['models'].items():
        for name in ('D-C', 'D-A'):
            value = data['contrasts'][name]; lo, hi = value['interval']
            lines.append(f"- {model} {name}：{value['difference']:+.1%}，区间 [{lo:+.1%}, {hi:+.1%}]；{value['method']}。")
    eligible = result['sensitivity_complete_eligible_families']
    clean = result['sensitivity_complete_infrastructure_free_families']
    control = result['exploratory']['first_action_cd']
    lines += ['', f"整族敏感性：全部 eligible 保留 {len(eligible['included_families'])} 族；"
              f"无指定基础设施事件保留 {len(clean['included_families'])} 族。超时预算失败不自动排除。",
              '', f"C/D 首轮提示一致 {control['prompt_equality']['equal_pairs']} 对，"
              f"不一致 {control['prompt_equality']['unequal_pairs']} 对，缺证据 {control['prompt_equality']['unavailable_pairs']} 对。",
              '', '参考 helper 分层、首轮噪声对照、生成 helper 数及调度案例均属探索性；详见 summary.json。', '',
              '限制：', ''] + ['- '+text for text in result['limitations']]
    return '\n'.join(lines)+'\n'


def write_analysis(directory, output_dir, *, bootstrap=10000, seed=20261009):
    root, output = Path(directory).resolve(), Path(output_dir).resolve()
    if output == root or root in output.parents:
        raise ValueError('analysis output must be outside the frozen campaign')
    if output.exists():
        raise FileExistsError('analysis output already exists')
    result = analyze_completed(root, bootstrap=bootstrap, seed=seed)
    output.mkdir(parents=True, exist_ok=False)
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    (output/'report.zh.md').write_text(render_markdown(result), encoding='utf8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = write_analysis(args.directory, args.output)
    print(json.dumps({k: result[k] for k in ('sessions_count', 'family_count', 'exact_roster_verified')}))
