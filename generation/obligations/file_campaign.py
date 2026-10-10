"""Frozen development campaign with one checked loader call per fresh solver.

The controller starts each isolated model context; this module never invents a
response or retries a used job. Saved CLI/session evidence remains auditable.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
import time

from generation.engine import run
from generation.representation.task import canonical, load_tasks
from generation.representation.verifier import Dafny, Verification
from generation.representation.analyze import summarize
from repair.runner import write_json
from repair.task import digest
from . import STRATEGIES
from .analyze import CohortAudit
from .common_failure import RepairPolicy, configuration as repair_config
from .handoff import FileQueue, PROTOCOL, bootstrap, collect, validate_response
from .runner import source_hashes

TASK_IDS=('cube_root','division_pair','first_argmax','merge_sorted','prefix_maxima',
          'reverse_copy','search_pipeline','triangular_sum')
PARENT='01a1101f-5176-7583-b055-fa5473f23b04'


class FileRepairPolicy(RepairPolicy):
    protocol=PROTOCOL
    system=RepairPolicy.system+('\nExpression profile: sequence concatenation and multiset(...) expressions are allowed. '
        'Sequence slicing with .. is unsupported. Initialized auxiliary sequence variables are allowed. '
        'Quantifiers are expressions only; no forall statements, proof blocks, or ghost variables.')

    def __init__(self,task,toolchain,batch_root=None,job=None):
        super().__init__(task,toolchain)
        self.batch_root=batch_root
        self.job=job

    def messages(self,*args,**kwargs):
        messages=super().messages(*args,**kwargs)
        messages[0]['content']=self.system
        return messages

    def begin_candidate(self,source,label):
        if self.batch_root is not None:check_not_halted(self.batch_root)
        return super().begin_candidate(source,label)

    def observe(self,source,evidence,label):
        result=super().observe(source,evidence,label)
        if self.batch_root is not None and label!='initial':
            record_transport(self.batch_root,self.job+'_'+label,
                             'error' if evidence.status=='tool_error' else 'ok',channel='verifier')
        return result


def configuration():
    c=repair_config()
    c.update(seed=20261008,replicates=3)
    c['budget'].update(model_seconds=600,task_seconds=2400)
    return c


def schedule(task_ids,replicates,seed):
    if set(task_ids)!=set(TASK_IDS) or len(task_ids)!=len(TASK_IDS):
        raise ValueError('exact frozen development task set required')
    if type(replicates) is not int or replicates<1:raise ValueError('invalid replicates')
    rng=random.Random(seed)
    blocks=[(t,r) for t in sorted(task_ids) for r in range(replicates)]
    rng.shuffle(blocks)
    jobs=[]
    for task_id,r in blocks:
        strategies=list(STRATEGIES);rng.shuffle(strategies)
        for strategy in strategies:
            jobs.append({'directory':f'{len(jobs):05}_{task_id}_{strategy}_{r}',
                'task_id':task_id,'replicate':r,'strategy':strategy,'representation':'contract'})
    return jobs


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def halt(root,reason,detail):
    root=Path(root)
    try:
        with (root/'halted.json').open('x',encoding='utf-8') as out:
            json.dump({'reason':reason,'detail':detail,'time_ns':time.time_ns()},out,indent=2)
    except FileExistsError:pass


def check_not_halted(root):
    if (Path(root)/'halted.json').exists():raise ValueError('campaign halted; preserve batch and investigate')


def record_transport(root,key,status,*,channel='transport'):
    if channel not in {'transport','verifier'}:raise ValueError('unknown infrastructure channel')
    root=Path(root);events=root/channel;events.mkdir(exist_ok=True)
    with (events/(key+'.json')).open('x',encoding='utf-8') as out:
        json.dump({'status':status,'time_ns':time.time_ns()},out)
    latest=sorted((read(p) for p in events.glob('*.json')),key=lambda x:x['time_ns'])[-3:]
    if len(latest)==3 and all(e['status']=='error' for e in latest):
        halt(root,'consecutive_'+channel+'_errors','Three consecutive '+channel+' infrastructure failures')


def check_active(root,*,toolchain=True):
    root=Path(root);check_not_halted(root)
    try:
        batch=read(root/'batch.json')
        if batch['source_hashes']!=source_hashes():raise ValueError('framework changed after freeze')
        frozen=read(root/'freeze.json')
        for name,expected in frozen.items():
            if digest((root/name).read_text(encoding='utf-8'))!=expected:raise ValueError('frozen campaign file changed: '+name)
        for task in batch['tasks'].values():
            if digest(Path(task['path']).read_text(encoding='utf-8'))!=task['task_sha256']:raise ValueError('task changed after freeze')
        if toolchain and Dafny(timeout=15).identity()!=batch['toolchain']:raise ValueError('toolchain changed after freeze')
    except Exception as exc:
        halt(root,'frozen_input_changed',str(exc));raise
    return batch


def prepare(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    tasks={t.meta['id']:t for t in load_tasks(Path(__file__).parent/'development_tasks')}
    c=configuration();jobs=schedule(list(tasks),c['replicates'],c['seed'])
    verifier=Dafny(timeout=15);toolchain=verifier.identity()
    if not toolchain['version'].startswith('4.11.'):raise ValueError('Dafny 4.11 required')
    admission=[];starts={};previews=[]
    for key,t in sorted(tasks.items()):
        t.check_frozen()
        seed=t.meta['mutants'][0]['bodies']
        positive=verifier.verify(t.assemble(t.meta['reference']),names=t.names)
        negative=verifier.verify(t.assemble(seed),names=t.names)
        admission.append({'task_id':key,'reference':positive.to_dict(),'initial_failure':negative.to_dict()})
        write_json(root/'admission.json',admission)
        if positive.status!='verified' or negative.status!='verification_failed':raise ValueError('admission failed: '+key)
        starts[key]={'bodies':seed,'evidence':negative.to_dict(),'task_sha256':t.file_hash,
                     'toolchain':toolchain,'source_sha256':digest(t.assemble(seed))}
    for j in jobs:
        task=tasks[j['task_id']];start=starts[j['task_id']]
        p=FileRepairPolicy(task,toolchain)
        p.observe(task.assemble(start['bodies']),Verification(**start['evidence']),'initial')
        m=p.messages(task,'contract',j['strategy'],start['bodies'])
        previews.append({**j,'messages':m,'messages_sha256':digest(canonical(m))})
    write_json(root/'starts.json',starts)
    write_json(root/'jobs.json',jobs)
    write_json(root/'initial_messages.json',previews)
    write_json(root/'batch.json',{'protocol':PROTOCOL,'config':c,'toolchain':toolchain,
        'source_hashes':source_hashes(),'parent_thread_id':PARENT,
        'expected_backend':{'model':'gpt-6-astra','effort':'high','parent_thread_id':PARENT},
        'tasks':{key:{'path':str(t.path),'task_sha256':t.file_hash,'asset_hashes':t.meta['asset_hashes']} for key,t in tasks.items()},
        'maximum_generation_requests':len(jobs)*c['budget']['model_calls'],
        'maximum_within_run_checks':len(jobs)*c['budget']['verifier_calls'],
        'separate_reference_checks':8,'separate_initial_checks':8,
        'limitations':FileQueue(root/'unused').identity(),
        'interpretation':'Exploratory authored common failures, 8 development tasks x4 conditions x3 repeats. One loader tool call, no further tools. No token/cost cap. No efficacy-dependent extension or early stopping.'})
    write_json(root/'freeze.json',{name:digest((root/name).read_text(encoding='utf-8'))
                                 for name in ['batch.json','jobs.json','starts.json','initial_messages.json','admission.json']})
    return len(jobs)


def execute_one(root,directory):
    root=Path(root);batch=check_active(root)
    matches=[j for j in read(root/'jobs.json') if j['directory']==directory]
    if len(matches)!=1:raise ValueError('unplanned job')
    j=matches[0]
    from generation.representation.task import Task
    t=Task.load(batch['tasks'][j['task_id']]['path'])
    if t.file_hash!=batch['tasks'][j['task_id']]['task_sha256']:raise ValueError('task changed after freeze')
    verifier=Dafny(timeout=15)
    if verifier.identity()!=batch['toolchain']:raise ValueError('toolchain changed after freeze')
    start=deepcopy(read(root/'starts.json')[j['task_id']]);start['evidence']=Verification(**start['evidence'])
    row=run(t,FileQueue(root/'queue'/directory,root),verifier,root/directory,
        config=batch['config'],strategy=j['strategy'],representation='contract',replicate=j['replicate'],
        policy=FileRepairPolicy(t,batch['toolchain'],root,directory),starting_point=start)
    print(directory,row['success'],row['stop_reason'],flush=True)
    return row


def pending(root):
    root=Path(root)
    check_active(root)
    for p in sorted((root/'queue').glob('*/*/request.json')):
        if any((p.parent/f).exists() for f in ['response.json','expired.json','assignment.json']):continue
        r=read(p)
        agent='fd_'+r['request_id'][:12]+'_'+p.parent.parent.name[:5]+'_'+p.parent.name
        # Assignment is persisted before dispatch. Controller must not retry a
        # successful spawn under a new identity or silently relabel its output.
        write_json(p.parent/'assignment.json',{'agent':'/root/'+agent,'request_id':r['request_id']})
        (p.parent/'bootstrap.txt').write_text(bootstrap(p.parent,r),encoding='utf-8')
        print(canonical({'agent':agent,'folder':str(p.parent),'bootstrap':bootstrap(p.parent,r)}))


def collect_pending(root,sessions):
    root=Path(root);batch=check_active(root)
    expected={read(p)['agent']:p.parent for p in (root/'queue').glob('*/*/assignment.json')
              if not (p.parent/'response.json').exists() and not (p.parent/'expired.json').exists()}
    for f in Path(sessions).glob('*.jsonl'):
        with f.open(encoding='utf-8') as stream:
            try:meta=json.loads(stream.readline())['payload']
            except (ValueError,KeyError):continue
        src=meta.get('source',{})
        spawn=src.get('subagent',{}).get('thread_spawn',{}) if isinstance(src,dict) else {}
        agent=spawn.get('agent_path')
        if agent not in expected or spawn.get('parent_thread_id')!=batch['parent_thread_id']:continue
        rows=[json.loads(line) for line in f.read_text(encoding='utf-8').splitlines()]
        if not any(r['type']=='event_msg' and r['payload'].get('type')=='task_complete' for r in rows):continue
        try:response=collect(expected[agent],f,agent,batch['parent_thread_id'],batch['expected_backend'])
        except Exception as exc:
            halt(root,'session_audit_failure',str(exc));raise
        print(agent,'collected',response['text_sha256'])


def audited_summary(root):
    root=Path(root);batch=read(root/'batch.json');base=CohortAudit()
    def audit_run(path,row,manifest):
        base(path,row,manifest)
        for p in path.glob('round_*.response.json'):
            response=read(p)
            if response.get('error'):continue
            folder=root/'queue'/path.name/p.name.split('.')[0].split('_')[1]
            request=read(folder/'request.json')
            if response!=read(folder/'response.json'):raise ValueError('response copy differs')
            validate_response(folder,request,response,batch['expected_backend'])
            if read(folder/'consumed.json')['request_id']!=request['request_id']:raise ValueError('consumption differs')
    result=summarize(root,protocol=PROTOCOL,check_row=audit_run)
    result['campaign_halted']=(root/'halted.json').exists()
    result['complete_matrix']=result['complete_matrix'] and not result['campaign_halted']
    write_json(root/'summary.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','run','pending','collect','summarize'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--job')
    parser.add_argument('--sessions',type=Path)
    args=parser.parse_args()
    if args.command=='prepare':print('prepared',prepare(args.output))
    elif args.command=='run':execute_one(args.output,args.job)
    elif args.command=='pending':pending(args.output)
    elif args.command=='collect':collect_pending(args.output,args.sessions)
    else:
        result=audited_summary(args.output)
        print('complete',result['complete_matrix'],'recorded',result['recorded_runs'])


if __name__=='__main__':main()
