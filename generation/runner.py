"""Same external oracle, two controlled interventions, no old repair-task gate."""
from dataclasses import asdict
import json
from pathlib import Path
import time

from repair.dependencies import regressions
from repair.runner import Limits, write_json
from repair.task import BoundaryError, digest
from . import PROTOCOL
from .models import SYSTEM
from .task import CONDITIONS


def source_hashes():
    root = Path(__file__).resolve().parents[1]
    paths = [*sorted((root/'generation').glob('*.py')),
             *(root/'repair'/n for n in ('runner.py','task.py','verifier.py','dependencies.py')),
             *(root/'project'/n for n in ('config.py','dafny_wrapper.py','llm_client.py'))]
    return {str(p.relative_to(root)):digest(p.read_text()) for p in paths}


def prompt_for(task, condition, current=None, history=()):
    prompt = {'task':task.public(),'tools':['read','generate','verify','stop'],
              'output_mode':'bodies' if condition in {'G10','G11'} else 'source',
              'feedback_policy':'full' if condition in {'G01','G11'} else 'none',
              'strategy':'Generate code satisfying the fixed input. Decide your own tool actions.'}
    if condition in {'G10','G11'}:
        prompt['skeleton'] = task.skeleton()
    if condition in {'G01','G11'}:
        prompt['current_source'] = current
        prompt['recent_actions'] = list(history[-3:])
    # No remaining-wall-time/status/previous candidate side channel for G00/G10.
    return prompt


def run(task, model, oracle, output, *, condition='G11', replicate=0, limits=None):
    if condition not in (*CONDITIONS,'T'):
        raise ValueError('unknown generation condition')
    limits = limits or Limits()
    output = Path(output)
    output.mkdir(parents=True,exist_ok=False)
    started = time.monotonic()
    usage = dict(model_calls=0,action_calls=0,oracle_calls=0,verifier_calls=0,runtime_calls=0,
                 input_tokens=0,output_tokens=0,accounted_tokens=0,unknown_usage_calls=0,cost_usd=0.0)
    result = dict(protocol=PROTOCOL,task_id=task.meta['id'],source_project=task.meta['source_project'],
                  family=task.meta['family'],split=task.meta['split'],origin=task.meta['origin'],
                  condition=condition,replicate=replicate,model_kind=model.kind,
                  research_eligible=model.kind=='live_model',success=False,supported=True,
                  stop_reason='model_budget_exhausted',usage=usage,boundary_rejections=0,
                  regressions=0,lost_observability=0,first_candidate_passed=None,
                  structure='not_run',formal='not_run',behavioral='not_run')
    manifest = dict(protocol=PROTOCOL,task_sha256=digest(task.path.read_text()),task=task.public(),
                    source_project=task.meta['source_project'],family=task.meta['family'],
                    limits=asdict(limits),condition=condition,replicate=replicate,
                    model=model.identity(),oracle=oracle.identity(),source_hashes=source_hashes(),
                    system_prompt=SYSTEM,initial_state='no implementation supplied',
                    token_policy='UTF-8 system+prompt bytes + 256 overhead + output cap reservation; actual usage when known')
    write_json(output/'manifest.json',manifest)
    write_json(output/'initial_input.json',prompt_for(task,condition))
    current, previous, history = None, {}, []
    seen = set()
    candidate_count = 0

    def remaining():
        return limits.seconds - (time.monotonic()-started)

    def event(stage, **data):
        with (output/'events.jsonl').open('a') as handle:
            handle.write(json.dumps(dict(stage=stage,elapsed=time.monotonic()-started,**data))+'\n')

    def check(source, phase):
        if usage['oracle_calls'] >= limits.verifier_calls or remaining() <= 0:
            raise RuntimeError('oracle_budget_exhausted')
        usage['oracle_calls'] += 1
        evidence = oracle.check(task,source,timeout=remaining())
        usage['verifier_calls'] += evidence.verifier_calls
        usage['runtime_calls'] += evidence.runtime_calls
        event(phase,source_sha256=digest(source),evidence=evidence.to_dict())
        return evidence

    try:
        max_actions = 1 if model.kind=='deterministic_template' else limits.model_calls
        for step in range(1,max_actions+1):
            if remaining() <= 0:
                result['stop_reason'] = 'wall_budget_exhausted'
                break
            if usage['oracle_calls'] >= limits.verifier_calls-1:
                result['stop_reason'] = 'reserved_final_oracle_budget'
                break
            prompt = prompt_for(task,condition,current,history)
            text = json.dumps(prompt,ensure_ascii=False)
            reserve = len((SYSTEM+text).encode())+256+limits.output_tokens
            is_template = model.kind=='deterministic_template'
            if not is_template and usage['accounted_tokens']+reserve > limits.total_tokens:
                result['stop_reason'] = 'token_budget_exhausted'
                break
            usage['action_calls'] += 1
            usage['model_calls'] += int(not is_template)
            write_json(output/f'prompt_{step:03}.json',prompt)
            try:
                response = model.generate(text,limits.output_tokens,remaining())
                if not isinstance(response,dict) or not isinstance(response.get('text'),str):
                    raise ValueError('invalid model response')
                inp,out = response.get('input_tokens'),response.get('output_tokens')
                measured = type(inp) is int and type(out) is int and inp >= 0 and out >= 0
                usage['input_tokens'] += inp if measured else 0
                usage['output_tokens'] += out if measured else 0
                usage['accounted_tokens'] += inp+out if measured else reserve
                usage['unknown_usage_calls'] += int(not measured)
                cost = response.get('cost_usd')
                usage['cost_usd'] = usage['cost_usd']+cost if usage['cost_usd'] is not None and cost is not None else None
                write_json(output/f'response_{step:03}.json',response)
            except Exception as exc:
                usage['accounted_tokens'] += reserve
                usage['unknown_usage_calls'] += 1
                usage['cost_usd'] = None
                event('model_error',step=step,error_type=type(exc).__name__)
                history.append({'error':'model_error','error_type':type(exc).__name__})
                continue
            if remaining() <= 0 or usage['accounted_tokens'] > limits.total_tokens:
                result['stop_reason'] = 'budget_exhausted_after_call'
                break
            try:
                action = json.loads(response['text'])
                if not isinstance(action,dict):
                    raise BoundaryError('action must be an object')
                kind = action.get('action')
                if kind in {'stop','unsupported'}:
                    result['supported'] = kind != 'unsupported'
                    result['stop_reason'] = kind
                    break
                if kind == 'read':
                    event('read',step=step)
                    continue  # whole public task is already in every prompt
                if kind == 'verify':
                    if current is not None and condition in {'G01','G11'}:
                        feedback = check(current,'requested_verification')
                        history.append({'action':'verify','evidence':feedback.to_dict()})
                    elif current is not None:
                        check(current,'requested_verification')  # deliberately withheld
                    else:
                        event('verify_without_candidate',step=step)
                    continue
                candidate_count += 1
                source = task.candidate(action,condition)
            except (ValueError,TypeError,BoundaryError) as exc:
                result['boundary_rejections'] += 1
                result['structure'] = 'failed'
                if candidate_count == 1:
                    result['first_candidate_passed'] = False
                history.append({'action':'rejected','reason':str(exc)})
                event('boundary_rejected',step=step,reason=str(exc))
                continue
            if digest(source) in seen:
                event('duplicate_candidate',step=step)
                history.append({'action':'duplicate'})
                continue
            seen.add(digest(source))
            (output/f'candidate_{step:03}.dfy').write_text(source)
            evidence = check(source,'candidate_check')
            for key in ('structure','formal','behavioral'):
                result[key] = getattr(evidence,key)
            if candidate_count == 1:
                result['first_candidate_passed'] = evidence.status=='passed'
            batches = evidence.details.get('formal',{}).get('obligations',{})
            delta = regressions(previous,batches)
            result['regressions'] += len(delta['confirmed'])
            result['lost_observability'] += len(delta['lost_observability'])
            history.append({'action':'generate','evidence':evidence.to_dict(),'regression':delta})
            event('candidate_decision',step=step,status=evidence.status,regression=delta)
            if evidence.status == 'passed':
                path = output/'final.dfy'
                path.write_text(source)
                final_source = path.read_text()
                task.extract(final_source)
                final = check(final_source,'final_reverification')
                result['final'] = final.to_dict()
                result['final_sha256'] = digest(final_source)
                result['success'] = final.status=='passed' and remaining()>0
                result['stop_reason'] = 'accepted' if result['success'] else 'final_reverification_failed'
                for key in ('structure','formal','behavioral'):
                    result[key] = getattr(final,key)
                current = final_source
                break
            # A common rollback policy for feedback-enabled conditions. No
            # failed state or diagnostic enters an independent prompt.
            if condition in {'G01','G11'} and not delta['confirmed'] and not delta['lost_observability']:
                current,previous = source,batches
            elif condition not in {'G01','G11'}:
                current = source  # only available to explicit check, never the next prompt
        if remaining() <= 0:
            result['success'] = False
            result['stop_reason'] = 'wall_budget_exhausted'
    except (RuntimeError,BoundaryError) as exc:
        result['stop_reason'] = str(exc)
        event('run_stopped',reason=str(exc))
    finally:
        result['seconds'] = time.monotonic()-started
        result['candidate_count'] = candidate_count
        result['generated_body_lines'] = (sum(len(v.splitlines()) for v in task.extract(current).values())
                                          if current is not None else 0)
        write_json(output/'result.json',result)
    return result
