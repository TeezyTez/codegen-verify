"""Separate protocol entry; historical generation/repair CLIs remain unchanged."""
import argparse
import importlib.metadata
from pathlib import Path
import platform
import sys

from repair.runner import write_json
from repair.task import digest
from . import PROTOCOL, REPRESENTATIONS, STRATEGIES
from .analyze import write_summary
from .config import load_config
from .models import Mock, OpenAIModel
from .preflight import inspect_run
from .runner import run, source_hashes
from .task import canonical, load_tasks
from .verifier import Dafny

HERE = Path(__file__).resolve().parent


def print_progress(event):
    stage = event['stage']
    if stage == 'model_call_started':
        print(f"  round {event['step']}: requesting model",flush=True)
    elif stage == 'model_response_received':
        print(f"  round {event['step']}: response {event.get('error') or 'received'}",flush=True)
    elif stage == 'verification':
        print(f"  {event['label']}: {event['status']}",flush=True)
    elif stage == 'candidate_rejected':
        print('  candidate rejected: body format or syntax profile',flush=True)
    elif stage == 'retry_wait':
        print(f"  retry waiting {event['seconds']:.1f}s ({event['category']})",flush=True)
    elif stage == 'run_finished':
        print(f"  stopped: {event['stop_reason']}; model calls={event['model_calls']}, verify calls={event['verifier_calls']}",flush=True)


def admit(tasks, verifier, output):
    output = Path(output)
    output.mkdir(parents=True,exist_ok=False)
    rows = []
    for task in tasks:
        folder = output/task.meta['id']
        folder.mkdir()
        task.check_frozen()
        cases = [('reference',task.meta['reference'])]+[(m['id'],m['bodies']) for m in task.meta['mutants']]
        results = []
        for index,(name,bodies) in enumerate(cases):
            source = task.assemble(bodies)
            prefix = folder/f'{index:02}'
            prefix.with_suffix('.dfy').write_text(source)
            evidence = verifier.verify(source,names=task.names)
            task.check_frozen()
            write_json(prefix.with_suffix('.verification.json'),evidence.to_dict())
            results.append({'name':name,'source_sha256':digest(source),'status':evidence.status,
                            'real_verifier':evidence.real_verifier,'executed':evidence.executed})
        ok = (results[0]['status'] == 'verified' and all(r['status'] == 'verification_failed' for r in results[1:])
              and all(r['real_verifier'] and r['executed'] for r in results))
        rows.append({'task_id':task.meta['id'],'task_sha256':task.file_hash,'asset_hashes':task.meta['asset_hashes'],
                     'audit':task.meta['equivalence_audit'],'admitted':ok,'cases':results})
        print(task.meta['id'],[r['status'] for r in results], 'admitted=',ok,flush=True)
    result = {'protocol':PROTOCOL,'all_admitted':all(r['admitted'] for r in rows),'tasks':rows,
              'toolchain':verifier.identity(),'source_hashes':source_hashes(),
              'note':'Admission is not a human equivalence audit. Verification failure is not necessarily a semantic counterexample.'}
    write_json(output/'admission.json',result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['doctor','preflight','validate','run','matrix','summarize'])
    parser.add_argument('--tasks',type=Path,default=HERE/'tasks')
    parser.add_argument('--config',type=Path,default=HERE/'configs'/'demo.json')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--task-id')
    parser.add_argument('--strategy',choices=STRATEGIES,default='iterative_repair')
    parser.add_argument('--representation',choices=REPRESENTATIONS,default='natural')
    parser.add_argument('--replicate',type=int,default=0)
    parser.add_argument('--dafny')
    parser.add_argument('--allow-paid',action='store_true')
    parser.add_argument('--schema-only',action='store_true')
    parser.add_argument('--quiet',action='store_true',help='suppress per-round progress only; does not change model messages')
    args = parser.parse_args(argv)
    if args.command == 'summarize':
        if not args.output:
            parser.error('--output is required')
        report = write_summary(args.output)
        print('Recorded:',report['recorded_runs'],'complete matrix:',report['complete_matrix'])
        return 0
    config = load_config(args.config)
    verifier = Dafny(args.dafny,timeout=config['budget']['verification_seconds'])
    if args.command == 'doctor':
        identity = verifier.identity()
        report = {'python':platform.python_version(),'openai_sdk':importlib.metadata.version('openai'),
                  'dafny':identity,'tested_dafny_series':'4.11.0','api_called':False}
        if args.output:
            if args.output.exists():
                parser.error('output already exists')
            write_json(args.output,report)
        print(canonical(report))
        return 0 if identity['version'].startswith('4.11.') else 1
    tasks = load_tasks(args.tasks)
    if args.task_id:
        tasks = [t for t in tasks if t.meta['id'] == args.task_id]
        if not tasks:
            parser.error('unknown task ID')
    if args.command == 'validate' and args.schema_only:
        print('Schema/hashes/mapping coverage valid:',len(tasks),'semantic equivalence remains pending unless human-reviewed.')
        return 0
    if args.command == 'preflight':
        if not args.task_id:
            parser.error('preflight requires one --task-id')
        report = inspect_run(tasks[0],config,verifier,strategy=args.strategy,
                             representation=args.representation,replicate=args.replicate)
        if args.output:
            if args.output.exists():
                parser.error('output already exists')
            write_json(args.output,report)
        print(canonical(report))
        return 0 if report['ready_for_authorized_attempt'] else 2
    if not args.output or args.output.exists():
        parser.error('--output must be a new directory')
    if args.command == 'validate':
        return 0 if admit(tasks,verifier,args.output)['all_admitted'] else 2
    if config['model']['kind'] != 'mock' and not args.allow_paid:
        parser.error('live calls require explicit --allow-paid; no client was created')
    if args.command == 'run' and (not args.task_id or len(tasks) != 1):
        parser.error('run requires one --task-id')
    if args.command == 'run' and (args.strategy not in config['strategies'] or args.representation not in config['representations'] or not 0 <= args.replicate < config['replicates']):
        parser.error('selected run is absent from config')
    if config['model']['kind'] != 'mock':
        check_strategy = args.strategy if args.command == 'run' else config['strategies'][0]
        check_representation = args.representation if args.command == 'run' else config['representations'][0]
        check = inspect_run(tasks[0],config,verifier,strategy=check_strategy,representation=check_representation)
        if check['blockers']:
            parser.error('preflight: '+'; '.join(check['blockers']))
    args.output.mkdir(parents=True,exist_ok=False)
    write_json(args.output/'config.json',config)
    selections = ([(tasks[0],args.strategy,args.representation,args.replicate)] if args.command == 'run' else
                  [(t,s,r,n) for t in tasks for s in config['strategies'] for r in config['representations']
                   for n in range(config['replicates'])])
    jobs = [{'directory':f'{i:04}_{t.meta["id"]}_{s}_{r}_{n}','task_id':t.meta['id'],
             'strategy':s,'representation':r,'replicate':n} for i,(t,s,r,n) in enumerate(selections)]
    write_json(args.output/'jobs.json',jobs)
    # Admission precedes model construction; private references never enter messages.
    if not admit(tasks,verifier,args.output/'admission')['all_admitted']:
        write_summary(args.output)
        print('Admission failed; model calls NOT executed.',file=sys.stderr)
        return 2
    try:
        for job,(task,strategy,representation,replicate) in zip(jobs,selections):
            model = Mock(task) if config['model']['kind'] == 'mock' else OpenAIModel(config['model'],authorized=args.allow_paid)
            row = run(task,model,verifier,args.output/job['directory'],config=config,strategy=strategy,
                      representation=representation,replicate=replicate,
                      progress=None if args.quiet else print_progress)
            print(task.meta['id'],strategy,representation,replicate,row['stop_reason'],flush=True)
    finally:
        write_summary(args.output)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError,OSError) as exc:
        # Avoid printing SDK exceptions or credential-bearing request objects.
        print(f'Configuration/artifact error ({type(exc).__name__}): check inputs and output paths.',file=sys.stderr)
        raise SystemExit(2)
