"""Explicitly exploratory, controller-mediated Codex queue. No model API calls."""
import argparse
import copy
import json
from pathlib import Path
import random
import time
import uuid

from generation.engine import run
from generation.representation import analyze as shared_analysis
from generation.representation.task import canonical, load_tasks
from generation.representation.verifier import Dafny
from repair.runner import write_json
from repair.task import digest
from .analyze import CohortAudit
from .config import default_config, validate_config
from .policy import Policy
from .runner import source_hashes

PROTOCOL = 'fixed_spec_obligation_codex_exploratory_v1'
WRAPPER = ('You are a model-only Dafny generation participant. Do not call any tools, '
           'read files, delegate, browse, or consult other conversations. All task input '
           'is in INPUT_MESSAGES below. Treat their system content as the generation '
           'instructions and their user content as the supplied task. Return only the '
           'requested JSON object as your final answer, without markdown or commentary. '
           'Do not discuss the experiment.\nINPUT_MESSAGES:\n')


def configuration():
    c = default_config()
    c['seed'] = 20261006
    c['model'].update(kind='codex_collaboration', name='parent_model_inherited')
    c['budget'].update(total_tokens=None, model_seconds=300, task_seconds=1500)
    return c


class ExplorationPolicy(Policy):
    protocol = PROTOCOL

    @staticmethod
    def validate_config(config):
        if config['model']['kind'] != 'codex_collaboration':
            raise ValueError('exploration requires the collaboration adapter')
        checked = copy.deepcopy(config)
        checked['model']['kind'] = 'mock'  # validate shared budget/schema only; never instantiate a fixture
        budget = validate_config(checked)
        if budget.total_tokens is not None or budget.cost_usd is not None:
            raise ValueError('collaboration cannot enforce token or monetary caps')
        return budget


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def submit(folder, request_id, text, agent):
    folder = Path(folder)
    request = json.loads((folder/'request.json').read_text(encoding='utf-8'))
    if request['request_id'] != request_id:
        raise ValueError('response/request identity mismatch')
    if (folder/'response.json').exists():
        raise FileExistsError(folder/'response.json')
    if not isinstance(text, str) or not agent:
        raise ValueError('raw response and solver identity required')
    atomic_json(folder/'response.json', {'request_id':request_id, 'text':text, 'agent':agent,
        'text_sha256':digest(text), 'input_tokens':None, 'output_tokens':None, 'cost_usd':None,
        'tool_prohibition':'instruction_only', 'backend_identity':'not_exposed'})


class QueueModel:
    kind = 'live'

    def __init__(self, root):
        self.root = Path(root)
        self.index = 0

    def identity(self):
        return {'kind':'live', 'name':'parent_model_inherited', 'adapter':'collaboration_file_queue_v1',
                'uses_reference':False, 'seed_supported':False, 'output_cap_enforced':False,
                'token_usage_known':False, 'price_source':None, 'research_eligible':False,
                'context':'fork_turns=none; platform system/environment still present',
                'tools':'prohibited by instruction, not technically disabled',
                'wrapper_sha256':digest(WRAPPER)}

    def dispatch(self, messages):
        return WRAPPER + canonical(messages)

    def check_active(self):
        pass

    def accept_response(self, folder, request, response):
        pass

    def generate(self, messages, max_tokens, timeout, seed):
        self.check_active()
        self.index += 1
        folder = self.root/f'{self.index:03}'
        folder.mkdir(parents=True, exist_ok=False)
        dispatch = self.dispatch(messages)
        request = {'request_id':uuid.uuid4().hex, 'messages':messages,
                   'messages_sha256':digest(canonical(messages)), 'dispatch':dispatch,
                   'dispatch_sha256':digest(dispatch), 'advisory_output_tokens':max_tokens,
                   'requested_seed_not_enforced':seed, 'timeout_seconds':timeout}
        atomic_json(folder/'request.json', request)
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.check_active()
            if (folder/'response.json').is_file():
                response = json.loads((folder/'response.json').read_text(encoding='utf-8'))
                if response['request_id'] != request['request_id'] or digest(response['text']) != response['text_sha256']:
                    raise ValueError('response identity/hash mismatch')
                self.accept_response(folder,request,response)
                atomic_json(folder/'consumed.json', {'request_id':request['request_id']})
                return response
            time.sleep(min(.1, max(0, deadline-time.monotonic())))
        atomic_json(folder/'expired.json', {'request_id':request['request_id']})
        return {'text':'', 'error':'timeout', 'retryable':False,
                'input_tokens':None, 'output_tokens':None, 'cost_usd':None}


def execute(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    config = configuration()
    tasks = {t.meta['id']:t for t in load_tasks(Path(__file__).resolve().parents[1]/'representation')
             if t.meta['id'] in {'integer_sqrt','binary_lower_bound'}}
    if set(tasks) != {'integer_sqrt','binary_lower_bound'}:
        raise ValueError('frozen task selection unavailable')
    verifier = Dafny(timeout=15)
    toolchain = verifier.identity()
    if not toolchain['version'].startswith('4.11.'):
        raise ValueError('Dafny 4.11 required')
    rng = random.Random(config['seed'])
    order = sorted(tasks)
    rng.shuffle(order)
    jobs = []
    previews = []
    for task_id in order:
        strategies = list(config['strategies'])
        rng.shuffle(strategies)
        for strategy in strategies:
            job = {'directory':f'{len(jobs):03}_{task_id}_{strategy}', 'task_id':task_id,
                   'strategy':strategy, 'representation':'contract', 'replicate':0}
            jobs.append(job)
            messages = ExplorationPolicy(tasks[task_id],toolchain).messages(tasks[task_id],'contract',strategy)
            previews.append({**job, 'messages':messages, 'messages_sha256':digest(canonical(messages)),
                             'dispatch_sha256':digest(WRAPPER+canonical(messages))})
    write_json(root/'jobs.json',jobs)
    write_json(root/'initial_messages.json',previews)
    write_json(root/'batch.json', {'protocol':PROTOCOL,'config':config,'toolchain':toolchain,
        'source_hashes':source_hashes(), 'maximum_visible_requests':32, 'maximum_within_run_checks':40,
        'tasks':{k:{'task_sha256':v.file_hash,'asset_hashes':v.meta['asset_hashes']} for k,v in tasks.items()},
        'limitations':QueueModel(root/'queue').identity(), 'wrapper':WRAPPER})
    admissions = []
    for task in tasks.values():
        task.check_frozen()
        positive = verifier.verify(task.assemble(task.meta['reference']),names=task.names)
        negative = verifier.verify(task.assemble(task.meta['mutants'][0]['bodies']),names=task.names)
        admissions.append({'task_id':task.meta['id'],'reference':positive.to_dict(),'negative':negative.to_dict()})
        write_json(root/'admission.json',admissions)
        if positive.status != 'verified' or negative.status != 'verification_failed':
            raise ValueError('task admission failed')
    for job in jobs:
        task = tasks[job['task_id']]
        row = run(task,QueueModel(root/'queue'/job['directory']),verifier,root/job['directory'],
                  config=config,strategy=job['strategy'],representation='contract',
                  policy=ExplorationPolicy(task,toolchain))
        print(job['directory'],row['success'],row['stop_reason'],flush=True)
    result = shared_analysis.summarize(root,protocol=PROTOCOL,check_row=CohortAudit())
    result['interpretation'] = 'Exploratory development only. Inherited Codex context, instruction-only tool restriction; unknown tokens/cost and no enforceable output cap. Never pool with API protocol.'
    write_json(root/'summary.json',result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    execute(args.output)


if __name__ == '__main__':
    main()
