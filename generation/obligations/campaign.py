"""Offline campaign plans and task-paired descriptive analysis. Never calls a model."""
import argparse
import copy
import json
import math
from pathlib import Path
import random
from statistics import mean

from repair.runner import write_json
from repair.task import digest
from generation.representation.task import canonical, load_tasks
from . import PROTOCOL, STRATEGIES
from .analyze import summarize
from .config import load_config, validate_config
from .runner import source_hashes


def plan(tasks, config, schedule_seed=20261006):
    config = copy.deepcopy(config)
    budget = validate_config(config)
    tasks = sorted(tasks, key=lambda t: t.meta['id'])
    ids = [t.meta['id'] for t in tasks]
    if not tasks or len(set(ids)) != len(ids):
        raise ValueError('empty or duplicate tasks')
    if set(config['strategies']) != set(STRATEGIES) or config['representations'] != ['contract']:
        raise ValueError('campaign requires all four contract conditions')
    rng = random.Random(schedule_seed)
    blocks = [(t.meta['id'], r) for t in tasks for r in range(config['replicates'])]
    rng.shuffle(blocks)
    jobs = []
    for task_id, replicate in blocks:
        strategies = list(STRATEGIES)
        rng.shuffle(strategies)
        for strategy in strategies:
            jobs.append({'directory': f'{len(jobs):05}_{task_id}_{strategy}_{replicate}',
                         'task_id': task_id, 'replicate': replicate,
                         'strategy': strategy, 'representation': 'contract'})
    frozen = []
    for task in tasks:
        task.check_frozen()
        frozen.append({'task_id': task.meta['id'], 'path': str(task.path.resolve()),
                       'task_sha256': task.file_hash, 'asset_hashes': copy.deepcopy(task.meta['asset_hashes']),
                       'family': task.meta['family'], 'split': task.meta['split']})
    return {'protocol': PROTOCOL, 'artifact': 'campaign_plan_v1', 'execution_status': 'plan_only',
            'api_called': False, 'schedule_seed': schedule_seed, 'jobs': jobs, 'tasks': frozen,
            'config': config, 'config_sha256': digest(canonical(config)), 'source_hashes': source_hashes(),
            'maximum_model_calls': len(jobs)*budget.model_calls,
            'maximum_verifier_calls': len(jobs)*budget.verifier_calls,
            'maximum_cost_usd': None if budget.cost_usd is None else len(jobs)*budget.cost_usd,
            'cost_note': 'Local reservation ceiling only; not a provider billing guarantee.',
            'execution_note': 'Schedule only. The legacy matrix CLI does not consume this plan. '
                              'Freeze the live adapter/toolchain and add a durable executor before live use.'}


def paired(summary, clusters=None, draws=10000, seed=20261006):
    if summary.get('protocol') != PROTOCOL or summary.get('complete_matrix') is not True:
        raise ValueError('complete audited obligation matrix required')
    if type(draws) is not int or draws < 100:
        raise ValueError('at least 100 bootstrap draws required')
    rows = summary['conditions']
    if len(rows) != 4 or {r['strategy'] for r in rows} != set(STRATEGIES):
        raise ValueError('exactly one cohort with four conditions required')
    if len({(r['is_mock'],r['audit_status'],r['representation'],r['config_sha256']) for r in rows}) != 1:
        raise ValueError('mixed cohorts cannot be paired')
    groups = {r['strategy']: r['by_task'] for r in rows}
    tasks = sorted(groups['baseline'])
    if not tasks or any(set(g) != set(tasks) for g in groups.values()):
        raise ValueError('unmatched tasks')
    replicas = None
    for group in groups.values():
        for row in group.values():
            ids = sorted(row['replicate_ids'])
            p = row['success_fraction']
            if (not ids or len(ids) != len(set(ids)) or row['runs'] != len(ids) or
                    type(p) not in (float,int) or not math.isfinite(p) or not 0 <= p <= 1):
                raise ValueError('invalid repeat counts or success rate')
            if replicas is not None and replicas != ids:
                raise ValueError('unbalanced replicate IDs')
            replicas = ids
    clusters = {t: t for t in tasks} if clusters is None else clusters
    if set(clusters) != set(tasks) or any(not isinstance(v,str) or not v for v in clusters.values()):
        raise ValueError('cluster mapping must cover every task exactly')
    members = {}
    for task in tasks:
        members.setdefault(clusters[task], []).append(task)
    cluster_ids = sorted(members)
    contrasts = {}
    for left, right in [('guided','baseline'), ('state','baseline'), ('guided','state'), ('guided','independent_sampling')]:
        delta = {t: groups[left][t]['success_fraction']-groups[right][t]['success_fraction'] for t in tasks}
        rng = random.Random(seed)
        samples = []
        for _ in range(draws):
            picked = rng.choices(cluster_ids, k=len(cluster_ids))
            values = [delta[t] for cluster in picked for t in members[cluster]]
            samples.append(mean(values))
        samples.sort()
        contrasts[left+'-'+right] = {'difference': mean(delta.values()),
            'ci95': [samples[int(.025*(draws-1))], samples[int(.975*(draws-1))]], 'per_task': delta}
    return {'protocol': PROTOCOL, 'analysis': 'paired_cluster_percentile_bootstrap_v1',
            'primary_contrast': 'guided-baseline', 'confirmatory': False, 'is_mock': rows[0]['is_mock'],
            'task_count': len(tasks), 'cluster_count': len(members), 'replicates_per_task': len(replicas),
            'clusters': clusters, 'draws': draws, 'seed': seed, 'contrasts': contrasts,
            'interpretation': 'Descriptive intervals, no adjusted hypothesis tests. Repeats are not independent tasks. '
                              'Mock results do not measure model efficacy. A frozen holdout and analysis plan '
                              'are additionally required for confirmation; small-cluster intervals can be unstable.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--tasks', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seed', type=int, default=20261006)
    a = sub.add_parser('analyze')
    a.add_argument('--runs', type=Path, required=True)
    a.add_argument('--output', type=Path, required=True)
    a.add_argument('--clusters', type=Path)
    a.add_argument('--draws', type=int, default=10000)
    a.add_argument('--seed', type=int, default=20261006)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.command == 'plan':
        result = plan(load_tasks(args.tasks), load_config(args.config), args.seed)
    else:
        manifest = args.runs/'jobs.json'
        if not manifest.is_file():
            raise ValueError('campaign analysis requires the expected jobs.json manifest')
        jobs = json.loads(manifest.read_text(encoding='utf-8'))
        if not isinstance(jobs, list) or not jobs:
            raise ValueError('jobs.json must contain a nonempty expected job list')
        audited = summarize(args.runs)
        if audited['planned_runs'] != audited['recorded_runs']:
            raise ValueError('expected and recorded job counts differ')
        mapping = json.loads(args.clusters.read_text(encoding='utf-8')) if args.clusters else None
        result = paired(audited, mapping, args.draws, args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output/('campaign.json' if args.command == 'plan' else 'paired.json'), result)
    print('Saved offline', args.command, 'to', args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
