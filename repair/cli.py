"""python -m repair.cli {validate,run,suite,analyze,estimate}."""
import argparse
import json
from pathlib import Path

from .analyze import summarize
from .models import Provider, Replay
from .runner import CONDITIONS, Limits, run, write_json
from .task import Task, digest, validate_splits
from .verifier import Dafny


def load_tasks(root):
    tasks = [Task.load(p) for p in sorted(Path(root).rglob('task.json'))]
    if not tasks:
        raise ValueError("no tasks found")
    if len({t.meta['id'] for t in tasks}) != len(tasks):
        raise ValueError("duplicate task ID")
    validate_splits(tasks)
    return tasks


def validate(tasks, verifier, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for task in tasks:
        original = (task.path.parent / "original.dfy").read_text()
        reference = task.apply(task.original, json.loads((task.path.parent / 'reference.json').read_text()))
        task.check_final(reference)
        before = verifier.verify(original)
        broken = verifier.verify(task.original)
        fixed = verifier.verify(reference)
        row = {"task_id": task.meta['id'], "provenance": task.meta,
               "original_sha256": digest(original), "broken_sha256": digest(task.original),
               "reference_sha256": digest(reference), "original": before.to_dict(),
               "broken": broken.to_dict(), "reference": fixed.to_dict(),
               "admitted": before.status == 'passed' and broken.status == 'verification_failed' and fixed.status == 'passed'}
        rows.append(row)
        print(task.meta['id'], before.status, broken.status, fixed.status, flush=True)
    report = {"verifier": verifier.version(), "tasks": rows, "all_admitted": all(r['admitted'] for r in rows)}
    write_json(output / 'validation.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['validate', 'run', 'suite', 'analyze', 'estimate'])
    parser.add_argument('--tasks', default='repair/tasks')
    parser.add_argument('--task')
    parser.add_argument('--output', required=True)
    parser.add_argument('--config', default='repair/configs/pilot.json')
    parser.add_argument('--condition', choices=CONDITIONS, default='dependency')
    parser.add_argument('--model', choices=['replay', 'live'], default='replay')
    parser.add_argument('--allow-paid', action='store_true', help='explicitly authorize model calls on the selected public/local tasks')
    parser.add_argument('--replicates', type=int)
    parser.add_argument('--dafny')
    args = parser.parse_args(argv)
    if args.command == 'analyze':
        report = summarize(args.output)
        write_json(Path(args.output) / 'summary.json', report)
        print(json.dumps(report, indent=2))
        return 0
    config = json.loads(Path(args.config).read_text())
    limits = Limits(**config['limits'])
    tasks = [Task.load(args.task)] if args.task else load_tasks(args.tasks)
    repeats = args.replicates if args.replicates is not None else config['replicates']
    if repeats < 1:
        parser.error('replicates must be positive')
    if args.command == 'estimate':
        n = len(tasks) * len(config['conditions']) * repeats
        estimate = {"jobs": n, "max_model_calls": n * limits.model_calls,
                    "max_verifier_calls": n * limits.verifier_calls,
                    "token_ceiling": n * limits.total_tokens,
                    "cost_usd": None, "price_formula": "input_tokens * input_USD_per_M / 1e6 + output_tokens * output_USD_per_M / 1e6",
                    "note": "Supply current provider prices in config; no price is invented. No model calls made."}
        write_json(args.output, estimate)
        print(json.dumps(estimate, indent=2))
        return 0
    verifier = Dafny(args.dafny)
    if args.command == 'validate':
        return 0 if validate(tasks, verifier, args.output)['all_admitted'] else 1
    if args.model == 'live' and not args.allow_paid:
        parser.error('live model calls require --allow-paid; replay runs need no credentials')
    conditions = config['conditions'] if args.command == 'suite' else [args.condition]
    repeats = repeats if args.command == 'suite' else 1
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / 'config.json', config)
    if args.model == 'live':
        # Admission is framework-controlled, before even constructing a client.
        if not validate(tasks, verifier, root / 'admission')['all_admitted']:
            print('Task admission failed; no model calls were made.')
            return 1
    jobs = [{"task_id": t.meta['id'], "condition": c, "replicate": r,
             "directory": f"{i:03d}_{c}_{r}"}
            for i,t in enumerate(tasks) for c in conditions for r in range(repeats)]
    write_json(root / 'jobs.json', jobs)
    task_map = {t.meta['id']: t for t in tasks}
    for job in jobs:
        task = task_map[job['task_id']]
        model = (Replay(json.loads((task.path.parent / 'replay.json').read_text())) if args.model == 'replay'
                 else Provider(**{f'{k}_price':v for k,v in config['prices_usd_per_million'].items()}))
        report = run(task, model, verifier, root / job['directory'], condition=job['condition'],
                     limits=limits, replicate=job['replicate'])
        print(task.meta['id'], job['condition'], job['replicate'], report['stop_reason'], flush=True)
    write_json(root / 'summary.json', summarize(root))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
