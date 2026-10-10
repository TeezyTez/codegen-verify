"""Common failing start, full public feedback; separate exploratory repair protocol."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
import re

from generation.engine import run
from generation.representation.analyze import summarize
from generation.representation.task import canonical, load_tasks
from generation.representation.verifier import Dafny
from repair.runner import write_json
from repair.task import digest
from .analyze import CohortAudit
from .exploration import ExplorationPolicy, QueueModel, configuration as base_config
from .runner import source_hashes

PROTOCOL = 'common_failure_codex_repair_v1'
INSTRUCTION = ('Repair the supplied failing implementation to satisfy all fixed contracts. '
               'Return complete bodies. You may replace the implementation. If target is '
               'non-null, address it first while preserving other requirements. UNKNOWN '
               'means missing proof, not a counterexample. Do not change the contracts.')
WRAPPER = ('You are a model-only Dafny repair participant. Do not call tools, read files, '
           'browse, delegate, or consult other conversations. Use only the supplied input. '
           'Return only the requested JSON object in your final answer, without commentary.\n')
SEEDS = {
    'binary_lower_bound': {'LowerBound': 'var lo := 0;\nvar hi := |s|;\nwhile lo < hi\n  invariant 0 <= lo <= hi <= |s|\n  decreases hi - lo\n{\n  var mid := (lo + hi) / 2;\n  if s[mid] <= key { lo := mid + 1; } else { hi := mid; }\n}\np := lo;'},
    'integer_sqrt': {'IntegerSqrt': 'r := 1;\nwhile r * r < n\n  invariant r >= 0\n  invariant r * r <= n\n  decreases n - r\n{\n  r := r + 1;\n}'},
}


def configuration():
    c = base_config()
    c['seed'] = 20261007
    c['budget'].update(model_calls=3, verifier_calls=4, task_seconds=1200)
    return c


def public_output(text):
    # Paths and CSV logger destinations are incidental; preserve actual error prose.
    text = re.sub(r'[^\s\n]*representation-verify-[^\s\n]*?[/\\]program\.dfy', 'candidate.dfy', text)
    text = re.sub(r'[^\s\n]*representation-verify-[^\s\n]*?[/\\]results\.csv', 'results.csv', text)
    return text


class RepairPolicy(ExplorationPolicy):
    protocol = PROTOCOL
    feedback_policy = 'full_public_common_failure_v1'

    def __init__(self, task, toolchain):
        super().__init__(task,toolchain)
        self.task = task
        self.initial = None

    def observe(self, source, evidence, label):
        diagnostic = super().observe(source,evidence,label)
        self.history[-1] = {'candidate_source':source,'status':evidence.status,
            'diagnostic':diagnostic,'method_batches':deepcopy(evidence.obligations),
            'verifier_output':{'stdout':public_output(evidence.stdout),'stderr':public_output(evidence.stderr)}}
        if label == 'initial':
            self.initial = deepcopy(self.history[-1])
        return diagnostic

    def messages(self, task, representation, strategy, current=None, diagnostic=None):
        messages = super().messages(task,representation,strategy,current,diagnostic)
        content = json.loads(messages[1]['content'])
        if current is not None:
            content['current_bodies'] = task.core.extract(task.assemble(current))
        content['repair_instruction'] = INSTRUCTION
        content['target'] = content.get('target') if strategy == 'guided' else None
        if 'evidence_state' in content:
            content['evidence_state'].pop('identity',None)
        if strategy == 'independent_sampling':
            if self.initial is None:
                raise ValueError('common failure must be loaded before sampling')
            content['current_bodies'] = task.core.extract(self.initial['candidate_source'])
            content['history'] = [deepcopy(self.initial)]
        messages[1]['content'] = canonical(content)
        return messages


class RepairQueue(QueueModel):
    def dispatch(self,messages):
        return WRAPPER+'SYSTEM:\n'+messages[0]['content']+'\nUSER:\n'+messages[1]['content']

    def identity(self):
        return {**super().identity(),'adapter':'common_failure_collaboration_queue_v1',
                'wrapper_sha256':digest(WRAPPER),'protocol':PROTOCOL}


def execute(root, *, prepare_only=False):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=False)
    c=configuration(); verifier=Dafny(timeout=15); toolchain=verifier.identity()
    if not toolchain['version'].startswith('4.11.'):
        raise ValueError('Dafny 4.11 required')
    tasks={t.meta['id']:t for t in load_tasks(Path(__file__).resolve().parents[1]/'representation') if t.meta['id'] in SEEDS}
    if set(tasks) != set(SEEDS):
        raise ValueError('frozen task selection unavailable')
    starts={}; admission=[]
    for key,t in tasks.items():
        source=t.assemble(SEEDS[key])
        positive=verifier.verify(t.assemble(t.meta['reference']),names=t.names)
        negative=verifier.verify(source,names=t.names)
        admission.append({'task_id':key,'reference':positive.to_dict(),'initial_failure':negative.to_dict()})
        write_json(root/'admission.json',admission)
        if positive.status!='verified' or negative.status!='verification_failed':
            raise ValueError('reference/initial failure admission did not match')
        starts[key]={'bodies':deepcopy(SEEDS[key]),'evidence':negative,'task_sha256':t.file_hash,
                     'toolchain':toolchain,'source_sha256':digest(source)}
    rng=random.Random(c['seed']); order=sorted(tasks); rng.shuffle(order)
    jobs=[]; previews=[]
    for key in order:
        strategies=list(c['strategies']); rng.shuffle(strategies)
        for strategy in strategies:
            j={'directory':f'{len(jobs):03}_{key}_{strategy}','task_id':key,'strategy':strategy,'representation':'contract','replicate':0}
            jobs.append(j)
            p=RepairPolicy(tasks[key],toolchain)
            p.observe(tasks[key].assemble(SEEDS[key]),starts[key]['evidence'],'initial')
            messages=p.messages(tasks[key],'contract',strategy,SEEDS[key])
            previews.append({**j,'messages':messages,'messages_sha256':digest(canonical(messages)),
                             'dispatch_sha256':digest(RepairQueue(root/'unused').dispatch(messages))})
    write_json(root/'jobs.json',jobs); write_json(root/'initial_messages.json',previews)
    write_json(root/'batch.json',{'protocol':PROTOCOL,'config':c,'source_hashes':source_hashes(),
        'toolchain':toolchain,'seeds':SEEDS,'maximum_generation_requests':24,'maximum_repair_checks':32,
        'separate_initial_checks':2,'separate_reference_checks':2,'prepare_only':prepare_only,
        'tasks':{k:{'task_sha256':t.file_hash,'asset_hashes':t.meta['asset_hashes']} for k,t in tasks.items()},
        'limitations':RepairQueue(root/'unused').identity()})
    if prepare_only:
        return
    for j in jobs:
        t=tasks[j['task_id']]
        row=run(t,RepairQueue(root/'queue'/j['directory']),verifier,root/j['directory'],config=c,
                strategy=j['strategy'],representation='contract',policy=RepairPolicy(t,toolchain),
                starting_point=starts[j['task_id']])
        print(j['directory'],row['success'],row['stop_reason'],flush=True)
    result=summarize(root,protocol=PROTOCOL,check_row=CohortAudit())
    result['interpretation']='Exploratory repairs from authored shared failures. Not from-scratch generation, strict API budgets, or confirmation. First candidate means first repair; initial checks are separate.'
    write_json(root/'summary.json',result)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args()
    execute(args.output,prepare_only=args.prepare_only)
