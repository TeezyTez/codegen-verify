"""Do not pool replay, templates, or old repair-protocol observations."""
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import mean

from repair.analyze import cluster_interval
from repair.task import digest
from . import PROTOCOL


def summarize(root):
    root = Path(root)
    if (root/'SUPERSEDED.md').exists():
        raise ValueError('superseded run must not be analyzed as current')
    groups = defaultdict(list)
    rows,seen,versions = [],set(),set()
    for path in sorted(root.glob('*/result.json')):
        row = json.loads(path.read_text())
        if row.get('protocol') != PROTOCOL:
            raise ValueError('foreign result protocol')
        key = (row['task_id'],row['condition'],row['replicate'],row['model_kind'])
        if key in seen:
            raise ValueError('duplicate run identity')
        seen.add(key)
        manifest = json.loads((path.parent/'manifest.json').read_text())
        versions.add(json.dumps(manifest['source_hashes'],sort_keys=True))
        if row['success']:
            if digest((path.parent/'final.dfy').read_text()) != row['final_sha256']:
                raise ValueError('final artifact hash mismatch')
            if row['final']['status'] != 'passed':
                raise ValueError('success without final acceptance')
        groups[(row['model_kind'],row['condition'],row['split'])].append(row)
        rows.append(row)
    if len(versions)>1:
        raise ValueError('mixed framework versions')
    output = dict(protocol=PROTOCOL,live_research=[],scripted_diagnostics=[],deterministic_baseline=[],
                  missing_planned_runs=[],paired_live=[],total_completed=len(rows))
    if (root/'jobs.json').exists():
        jobs = json.loads((root/'jobs.json').read_text())
        output['planned_runs'] = len(jobs)
        output['missing_planned_runs'] = [j for j in jobs if not (root/j['directory']/'result.json').exists()]
        expected = {j['directory'] for j in jobs}
        if any(p.parent.name not in expected for p in root.glob('*/result.json')):
            raise ValueError('unplanned result directory')
    for (kind,condition,split),values in groups.items():
        by_source,by_family = defaultdict(list),defaultdict(list)
        for row in values:
            by_source[row['source_project']].append(row)
            by_family[row['family']].append(row)
        counts = lambda xs: dict(runs=len(xs),accepted=sum(r['success'] for r in xs))
        costs = [r['usage']['cost_usd'] for r in values]
        summary = dict(condition=condition,split=split,**counts(values),
                       supported=sum(r['supported'] for r in values),observed_rate=mean(r['success'] for r in values),
                       source_macro_rate=mean(mean(r['success'] for r in v) for v in by_source.values()),
                       source_cluster_ci95=cluster_interval(values) if kind=='live_model' else None,
                       by_source={k:counts(v) for k,v in by_source.items()},
                       by_family={k:counts(v) for k,v in by_family.items()},
                       stop_reasons=dict(Counter(r['stop_reason'] for r in values)),
                       seconds_all_runs=sum(r['seconds'] for r in values),
                       cost_usd=sum(costs) if all(c is not None for c in costs) else None,
                       boundary_rejections=sum(r['boundary_rejections'] for r in values),
                       regressions=sum(r['regressions'] for r in values),
                       lost_observability=sum(r['lost_observability'] for r in values),
                       mean_generated_body_lines=mean(r['generated_body_lines'] for r in values),
                       first_candidate_passed=sum(r['first_candidate_passed'] is True for r in values),
                       last_evidence={key:dict(Counter(r[key] for r in values)) for key in ('structure','formal','behavioral')})
        for key in ('model_calls','action_calls','oracle_calls','verifier_calls','runtime_calls','unknown_usage_calls'):
            summary[key] = sum(r['usage'][key] for r in values)
        for key in ('input_tokens','output_tokens'):
            summary[key] = sum(r['usage'][key] for r in values) if kind=='live_model' else None
        destination = {'live_model':'live_research','scripted_replay':'scripted_diagnostics',
                       'deterministic_template':'deterministic_baseline'}[kind]
        output[destination].append(summary)
    live = defaultdict(dict)
    for row in rows:
        if row['model_kind']=='live_model':
            live[(row['task_id'],row['replicate'],row['split'])][row['condition']] = row
    for left,right in (('G11','G01'),('G11','G10'),('G01','G00'),('G10','G00')):
        paired = [dict(source_project=g[left]['source_project'],success=int(g[left]['success'])-int(g[right]['success']))
                  for g in live.values() if left in g and right in g]
        if paired:
            by_source = defaultdict(list)
            for row in paired:
                by_source[row['source_project']].append(row['success'])
            output['paired_live'].append(dict(left=left,right=right,matched=len(paired),
                unmatched=sum((left in g) != (right in g) for g in live.values()),
                task_run_difference=mean(r['success'] for r in paired),
                source_macro_difference=mean(mean(v) for v in by_source.values()),
                source_macro_ci95=cluster_interval(paired)))
    complete = [g for g in live.values() if {'G00','G01','G10','G11'} <= g.keys()]
    output['interaction_live'] = (dict(matched=len(complete),difference_in_differences=mean(
        int(g['G11']['success'])-int(g['G01']['success'])-int(g['G10']['success'])+int(g['G00']['success'])
        for g in complete)) if complete else None)
    output['interpretation'] = 'Replay tests infrastructure only. Templates are genuine executions on their stated support, not LLM evidence. Resolve missing runs before inference.'
    return output
