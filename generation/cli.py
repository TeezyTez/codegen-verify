"""python -m generation.cli {validate,suite,template,analyze,estimate,audit}."""
import argparse
import json
from pathlib import Path

from repair.runner import Limits, write_json
from repair.task import digest
from repair.verifier import Dafny
from . import PROTOCOL
from .analyze import summarize
from .models import Provider, Replay
from .oracle import Oracle
from .runner import run, source_hashes
from .task import CONDITIONS, load_tasks
from .templates import Template


def validate(tasks, oracle, output):
    root = Path(output)
    root.mkdir(parents=True,exist_ok=False)
    rows = []
    for index,task in enumerate(tasks):
        folder = root / f'{index:03}'
        folder.mkdir()
        reference = task.assemble(task.meta['reference'])
        (folder/'reference.dfy').write_text(reference)
        (folder/'runtime_harness.dfy').write_text(task.harness())
        correct = oracle.check(task,reference,test_failed=True)
        mutants = []
        for i,mutant in enumerate(task.meta['mutants']):
            source = task.assemble(mutant['bodies'])
            (folder/f'mutant_{i:03}.dfy').write_text(source)
            evidence = oracle.check(task,source,test_failed=True)
            mutants.append(dict(id=mutant['id'],violation=mutant['violation'],source_sha256=digest(source),
                                evidence=evidence.to_dict(),detected=evidence.formal=='verification_failed'
                                and evidence.behavioral=='behavior_failed'))
        row = dict(task_id=task.meta['id'],task_sha256=digest(task.path.read_text()),
                   source_project=task.meta['source_project'],family=task.meta['family'],origin=task.meta['origin'],
                   review_status=task.meta.get('review_status','unknown'),
                   reference_sha256=digest(reference),reference=correct.to_dict(),mutants=mutants,
                   admitted=correct.status=='passed' and all(m['detected'] for m in mutants))
        rows.append(row)
        write_json(folder/'admission.json',row)
        print(task.meta['id'],'reference:',correct.status,'negative_controls:',[m['evidence']['behavioral'] for m in mutants],
              'admitted:',row['admitted'],flush=True)
    result = dict(protocol=PROTOCOL,oracle=oracle.identity(),source_hashes=source_hashes(),tasks=rows,
                  all_admitted=all(r['admitted'] for r in rows),
                  interpretation='Engineering admission, not independent human gold-spec validation.')
    write_json(root/'validation.json',result)
    return result


def audit(root,tasks):
    root = Path(root)
    summary = summarize(root)
    if summary['missing_planned_runs']:
        raise ValueError('incomplete suite')
    current = source_hashes()
    by_id = {t.meta['id']:t for t in tasks}
    checked = accepted = checks = 0
    for job in json.loads((root/'jobs.json').read_text()):
        folder = root/job['directory']
        result = json.loads((folder/'result.json').read_text())
        manifest = json.loads((folder/'manifest.json').read_text())
        task = by_id[job['task_id']]
        if manifest['source_hashes'] != current or manifest['task_sha256'] != digest(task.path.read_text()):
            raise ValueError('framework or task drift')
        for key in ('task_id','condition','replicate'):
            if result[key] != job[key]:
                raise ValueError('planned identity mismatch')
        events_path = folder/'events.jsonl'
        events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
        verifications = [e for e in events if 'evidence' in e]
        if len(verifications) != result['usage']['oracle_calls']:
            raise ValueError('oracle count mismatch')
        for key in ('verifier_calls','runtime_calls'):
            if sum(e['evidence'][key] for e in verifications) != result['usage'][key]:
                raise ValueError('subtool count mismatch')
        limits = manifest['limits']
        if result['usage']['model_calls'] > limits['model_calls'] or result['usage']['oracle_calls'] > limits['verifier_calls']:
            raise ValueError('call limit exceeded')
        if result['success']:
            source = (folder/'final.dfy').read_text()
            task.extract(source)
            if not verifications or verifications[-1]['stage'] != 'final_reverification':
                raise ValueError('no final recheck event')
            if verifications[-1]['source_sha256'] != digest(source) or verifications[-1]['evidence'] != result['final']:
                raise ValueError('final evidence mismatch')
            if result['usage']['accounted_tokens'] > limits['total_tokens'] or result['seconds'] >= limits['seconds']:
                raise ValueError('accepted outside budget')
            accepted += 1
        checked += 1
        checks += len(verifications)
    return dict(protocol=PROTOCOL,audited=checked,accepted=accepted,oracle_events=checks,
                note='Read-only artifact audit, not replacement for recorded fresh formal and runtime acceptance.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['validate','suite','template','analyze','estimate','audit'])
    parser.add_argument('--tasks',default='generation/tasks')
    parser.add_argument('--task-id')
    parser.add_argument('--output',required=True)
    parser.add_argument('--config',default='generation/configs/pilot.json')
    parser.add_argument('--model',choices=['replay','live'],default='replay')
    parser.add_argument('--allow-paid',action='store_true')
    parser.add_argument('--replicates',type=int)
    parser.add_argument('--dafny')
    args = parser.parse_args(argv)
    if args.command=='analyze':
        report = summarize(args.output)
        write_json(Path(args.output)/'summary.json',report)
        print(json.dumps(report,indent=2))
        return 0
    tasks = load_tasks(args.tasks)
    if args.task_id:
        tasks = [t for t in tasks if t.meta['id']==args.task_id]
        if not tasks:
            parser.error('task ID not found')
    if args.command=='audit':
        print(json.dumps(audit(args.output,tasks),indent=2))
        return 0
    config = json.loads(Path(args.config).read_text())
    if config.get('protocol') != PROTOCOL or set(config['conditions']) != set(CONDITIONS) or len(config['conditions']) != 4:
        parser.error('expected frozen generation protocol and four unique conditions')
    limits = Limits(**config['limits'])
    repeats = args.replicates if args.replicates is not None else config['replicates']
    if type(repeats) is not int or repeats < 1:
        parser.error('replicates must be positive')
    if args.command=='estimate':
        jobs = len(tasks)*len(CONDITIONS)*repeats
        report = dict(protocol=PROTOCOL,tasks=len(tasks),model_runs=jobs,template_runs=len(tasks),
                      max_model_calls=jobs*limits.model_calls,max_oracle_calls=jobs*limits.verifier_calls,
                      max_verifier_calls=jobs*limits.verifier_calls,max_runtime_calls=jobs*limits.verifier_calls,
                      token_ceiling=jobs*limits.total_tokens,prices=config['prices_usd_per_million'],
                      cost_usd=None,note='No API calls. Admission/template preparation costs additional and separately recorded.')
        write_json(args.output,report)
        print(json.dumps(report,indent=2))
        return 0
    if args.command=='suite' and args.model=='live' and not args.allow_paid:
        parser.error('live calls require explicit --allow-paid authorization')
    oracle = Oracle(Dafny(args.dafny))
    if args.command=='validate':
        return 0 if validate(tasks,oracle,args.output)['all_admitted'] else 1
    root = Path(args.output)
    root.mkdir(parents=True,exist_ok=False)
    write_json(root/'config.json',{**config,'effective_replicates':1 if args.command=='template' else repeats})
    # Every suite, including replay, admits tasks before a model client exists.
    if not validate(tasks,oracle,root/'admission')['all_admitted']:
        print('Admission failed; no generator/model invoked.')
        return 1
    conditions = ['T'] if args.command=='template' else config['conditions']
    reps = 1 if args.command=='template' else repeats
    jobs = [dict(task_id=t.meta['id'],condition=c,replicate=r,directory=f'{i:03}_{c}_{r}')
            for i,t in enumerate(tasks) for c in conditions for r in range(reps)]
    write_json(root/'jobs.json',jobs)
    task_map = {t.meta['id']:t for t in tasks}
    for job in jobs:
        task = task_map[job['task_id']]
        model = (Template(task) if job['condition']=='T' else Replay(task,job['condition']) if args.model=='replay'
                 else Provider(**{f'{k}_price':v for k,v in config['prices_usd_per_million'].items()}))
        result = run(task,model,oracle,root/job['directory'],condition=job['condition'],replicate=job['replicate'],limits=limits)
        print(task.meta['id'],job['condition'],job['replicate'],result['stop_reason'],flush=True)
    write_json(root/'summary.json',summarize(root))
    write_json(root/'audit.json',audit(root,tasks))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
