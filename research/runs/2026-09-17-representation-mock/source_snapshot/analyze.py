"""Descriptive statistics only. Repeats are grouped by task, never independent tasks."""
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from statistics import mean

from repair.runner import write_json
from repair.task import digest
from . import PROTOCOL
from .task import canonical


def summarize(root):
    root = Path(root)
    jobs = json.loads((root/'jobs.json').read_text()) if (root/'jobs.json').exists() else None
    paths = [root/'result.json'] if (root/'result.json').exists() else sorted(root.glob('*/result.json'))
    groups, seen, versions = defaultdict(list), set(), set()
    for path in paths:
        row = json.loads(path.read_text())
        manifest = json.loads((path.parent/'manifest.json').read_text())
        if row.get('protocol') != PROTOCOL or manifest.get('protocol') != PROTOCOL:
            raise ValueError('foreign protocol; legacy runs cannot be pooled')
        for key in ('run_id','task_id','strategy','representation','replicate'):
            if row[key] != manifest[key]:
                raise ValueError('result/manifest identity mismatch')
        if digest(canonical(manifest['config'])) != manifest['config_sha256']:
            raise ValueError('configuration hash mismatch')
        versions.add(canonical(manifest['source_hashes']))
        key = (row['task_id'],row['strategy'],row['representation'],row['replicate'],row['is_mock'])
        if key in seen:
            raise ValueError('duplicate task/condition/replicate')
        seen.add(key)
        if jobs is not None:
            planned = next((j for j in jobs if j['directory'] == path.parent.name), None)
            if planned is None or any(row[k] != planned[k] for k in ('task_id','strategy','representation','replicate')):
                raise ValueError('unplanned or mismatched result')
        if row['success']:
            if not row['completed'] or row['final_verification']['status'] != 'verified' or not row['final_verification']['real_verifier']:
                raise ValueError('success without complete real verification')
            if digest((path.parent/'final.dfy').read_text()) != row['final_sha256']:
                raise ValueError('final artifact hash mismatch')
            final = json.loads((path.parent/'final.verification.json').read_text())
            if final != row['final_verification']:
                raise ValueError('final evidence mismatch')
        # Also check exact persisted prompts, not just a claimed hash.
        for p in path.parent.glob('round_*.messages.json'):
            packet = json.loads(p.read_text())
            if digest(canonical(packet['messages'])) != packet['sha256']:
                raise ValueError('prompt hash mismatch')
        group = (row['is_mock'],row['audit_status'],row['strategy'],row['representation'],
                 manifest['config_sha256'])
        groups[group].append(row)
    if len(versions) > 1:
        raise ValueError('mixed framework versions; summarize in separate output directories')
    missing = [j for j in jobs or [] if not (root/j['directory']/'result.json').exists()]
    result = {'protocol':PROTOCOL,'planned_runs':len(jobs) if jobs is not None else len(paths),
              'recorded_runs':len(paths),'missing_runs':missing,'conditions':[],
              'interpretation':'Descriptive only; task repeats are correlated. Mock outcomes are fixture diagnostics, not model evidence.'}
    for (mock,audit,strategy,representation,config_hash),rows in sorted(groups.items()):
        by_task = defaultdict(list)
        for row in rows:
            by_task[row['task_id']].append(row)
        costs = [r['usage']['cost_usd'] for r in rows]
        task_rates = {t:{'runs':len(rs),'replicate_ids':sorted(r['replicate'] for r in rs),
                         'successes':sum(r['success'] for r in rs),
                         'success_fraction':mean(r['success'] for r in rs)} for t,rs in by_task.items()}
        counts = Counter()
        for row in rows:
            counts.update(row['failures'])
        summary = {'is_mock':mock,'audit_status':audit,'strategy':strategy,'representation':representation,
                   'config_sha256':config_hash,'unique_tasks':len(by_task),'recorded_runs':len(rows),
                   'completed_runs':sum(r['completed'] for r in rows),
                   'replicate_ids':sorted({r['replicate'] for r in rows}),
                   'successes':sum(r['success'] for r in rows),
                   'first_candidate_rate':mean(r['first_candidate_verified'] for r in rows),
                   'budget_success_rate_recorded':mean(r['success'] for r in rows),
                   'task_macro_success_rate':mean(r['success_fraction'] for r in task_rates.values()),
                   'real_verifier_runs':sum(r['real_verifier_executed'] for r in rows),
                   'failure_events':dict(counts),'stop_reasons':dict(Counter(r['stop_reason'] for r in rows)),
                   'seconds':sum(r['seconds'] for r in rows),
                   'cost_usd':sum(costs) if all(c is not None for c in costs) else None,
                   'by_task':task_rates}
        for key in ('model_calls','model_retry_calls','verifier_calls','unknown_usage_calls'):
            summary[key] = sum(r['usage'][key] for r in rows)
        for key in ('input_tokens','output_tokens'):
            summary[key] = None if mock or summary['unknown_usage_calls'] else sum(r['usage'][key] for r in rows)
        result['conditions'].append(summary)
    result['incomplete_runs'] = sum(s['recorded_runs']-s['completed_runs'] for s in result['conditions'])
    result['complete_matrix'] = not missing and result['incomplete_runs'] == 0
    return result


def write_summary(root):
    root = Path(root)
    summary = summarize(root)
    write_json(root/'summary.json',summary)
    fields = ['is_mock','audit_status','strategy','representation','unique_tasks','recorded_runs',
              'completed_runs','replicate_ids','first_candidate_rate','budget_success_rate_recorded',
              'model_calls','model_retry_calls','verifier_calls','real_verifier_runs','seconds',
              'input_tokens','output_tokens','cost_usd','failure_events','stop_reasons']
    with (root/'summary.csv').open('w',newline='') as handle:
        writer = csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader()
        for row in summary['conditions']:
            writer.writerow({k:canonical(row[k]) if isinstance(row[k],(dict,list)) else row[k] for k in fields})
    lines = ['# Representation experiment results','',
             'Descriptive statistics only. Mock repair success is not model capability evidence.',
             'Pending equivalence audits do not establish semantic equivalence. Repeats are not independent tasks.',
             f"Planned: {summary['planned_runs']}; recorded: {summary['recorded_runs']}; missing: {len(summary['missing_runs'])}; incomplete: {summary['incomplete_runs']}.",'',
             '| Mock | Audit | Strategy | View | Tasks | Runs | First full pass | Budget success | Model calls | Verify calls |',
             '|---|---|---|---|---:|---:|---:|---:|---:|---:|']
    for s in summary['conditions']:
        lines.append(f"| {s['is_mock']} | {s['audit_status']} | {s['strategy']} | {s['representation']} | {s['unique_tasks']} | {s['recorded_runs']} | {s['first_candidate_rate']:.1%} | {s['budget_success_rate_recorded']:.1%} | {s['model_calls']} | {s['verifier_calls']} |")
    lines += ['', 'Rates use recorded runs only; missing runs are exposed above, not silently dropped. Do not infer effects from an incomplete matrix.',
              'See summary.json for per-task repeat counts, failure event types, tool executions, tokens, costs and time.']
    (root/'summary.md').write_text('\n'.join(lines)+'\n')
    return summary
