"""Audit actual factorial inputs/feedback isolation; no model or verifier calls.

python scripts/check_generation_factorial.py RUN_DIRECTORY [--output FILE]
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from generation.cli import audit
from generation.task import load_tasks
from repair.runner import write_json


def inspect(root, tasks_root='generation/tasks'):
    root=Path(root)
    checked=audit(root,load_tasks(tasks_root))
    semantic_inputs={}
    limits=set()
    model_configs=set()
    prompts=isolated=0
    for job in json.loads((root/'jobs.json').read_text()):
        folder=root/job['directory']
        manifest=json.loads((folder/'manifest.json').read_text())
        if job['condition']=='T':
            continue
        public=manifest['task']
        encoded=json.dumps(public,sort_keys=True)
        if job['task_id'] in semantic_inputs and semantic_inputs[job['task_id']]!=encoded:
            raise ValueError('different semantic input across conditions')
        semantic_inputs[job['task_id']]=encoded
        if set(public) != {'id','description','methods','rule','profile'}:
            raise ValueError('private task metadata leaked')
        limits.add(json.dumps(manifest['limits'],sort_keys=True))
        if manifest['model']['kind']=='live_model':
            model_configs.add(json.dumps(manifest['model'],sort_keys=True))
        initial=json.loads((folder/'initial_input.json').read_text())
        for path in sorted(folder.glob('prompt_*.json')):
            prompt=json.loads(path.read_text())
            if prompt['task']!=public:
                raise ValueError('target input drift')
            skeleton=job['condition'] in {'G10','G11'}
            if ('skeleton' in prompt)!=skeleton:
                raise ValueError('skeleton intervention mismatch')
            if job['condition'] in {'G00','G10'}:
                if prompt!=initial:
                    raise ValueError('independent prompt contains history or side-channel changes')
                isolated+=1
            elif not {'recent_actions','current_source'} <= prompt.keys():
                raise ValueError('feedback condition missing context')
            prompts+=1
    if len(limits)>1 or len(model_configs)>1:
        raise ValueError('unequal budgets or model settings')
    return {**checked,'tasks_with_equal_inputs':len(semantic_inputs),'prompts_checked':prompts,
            'fresh_no_feedback_prompts':isolated,'budget_versions':len(limits),
            'live_model_settings':len(model_configs),
            'interpretation':'Input/permission protocol audit only, not effect-size evidence.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--tasks',default='generation/tasks')
    parser.add_argument('--output')
    args=parser.parse_args()
    result=inspect(args.root,args.tasks)
    if args.output:
        write_json(args.output,result)
    print(json.dumps(result,indent=2))
