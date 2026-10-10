"""Shared body-only executor. Policies supply inputs, never acceptance decisions."""
from collections import Counter
import copy
import json
from pathlib import Path
import subprocess
import time
import uuid

from repair.runner import write_json
from repair.task import BoundaryError, digest
from generation.representation.task import canonical


def run(task, model, verifier, output, *, config, strategy, representation, replicate=0, progress=None, policy,
        starting_point=None):
    config = copy.deepcopy(config)
    budget = policy.validate_config(config)
    if strategy not in config['strategies'] or representation not in config['representations']:
        raise ValueError('condition is absent from config')
    if type(replicate) is not int or not 0 <= replicate < config['replicates']:
        raise ValueError('invalid replicate')
    if model.kind not in {'mock','live'}:
        raise ValueError('unknown model kind')
    if (model.kind == 'mock') != (config['model']['kind'] == 'mock'):
        raise ValueError('model/config mismatch')
    task.check_frozen()
    output = Path(output)
    output.mkdir(parents=True,exist_ok=False)
    run_id = uuid.uuid4().hex
    try:
        revision = subprocess.run(['git','rev-parse','HEAD'],cwd=Path(__file__).parents[1],
                                  capture_output=True,text=True,timeout=3).stdout.strip() or None
    except (OSError,subprocess.TimeoutExpired):
        revision = None
    model_identity, toolchain = model.identity(), verifier.identity()
    start = copy.deepcopy(starting_point)
    initial_source = None
    if start is not None:
        initial_source = task.assemble(start['bodies'])
        evidence = start['evidence']
        if (start['task_sha256'] != task.file_hash or start['toolchain'] != toolchain or
                start['source_sha256'] != digest(initial_source) or
                evidence.status != 'verification_failed' or not evidence.real_verifier or not evidence.executed):
            raise ValueError('invalid or mismatched failing starting point')
    manifest = {'protocol':policy.protocol,'run_id':run_id,'task_id':task.meta['id'],
                'strategy':strategy,'representation':representation,'replicate':replicate,
                'seed':config['seed']+replicate,'model':model_identity,'toolchain':toolchain,
                'config':config,'config_sha256':digest(canonical(config)),
                'task_sha256':task.file_hash,'asset_hashes':task.meta['asset_hashes'],
                'task_path':str(task.path),'source_hashes':policy.source_hashes(),'git_revision':revision,
                'system_prompt_sha256':digest(policy.system),'feedback_policy':policy.feedback_policy,
                'audit':task.meta['equivalence_audit'],
                'token_policy':'UTF-8 message bytes + 256 framing + output cap reservation, provider usage when known; not a billing guarantee'}
    if start is not None:
        manifest['starting_point'] = {'source_sha256':digest(initial_source),
            'evidence_sha256':digest(canonical(start['evidence'].to_dict())),
            'verification_accounting':'shared preverified failure; outside the remaining repair budget'}
    write_json(output/'manifest.json',manifest)
    started = time.monotonic()
    usage = {'model_calls':0,'model_retry_calls':0,'verifier_calls':0,'input_tokens':0,
             'output_tokens':0,'accounted_tokens':0,'unknown_usage_calls':0,'cost_usd':0.0,
             'reserved_cost_usd':0.0,'model_seconds':0.0,'verification_seconds':0.0}
    result = {'protocol':policy.protocol,'run_id':run_id,'task_id':task.meta['id'],
              'task_family':task.meta['family'],'source':task.meta['source_project'],
              'origin':task.meta['origin'],'strategy':strategy,'representation':representation,
              'replicate':replicate,'is_mock':model.kind == 'mock','audit_status':task.meta['equivalence_audit']['status'],
              'real_verifier_executed':False,'success':False,'first_candidate_verified':False,
              'candidate_count':0,'stop_reason':'model_budget_exhausted','status':'not_run',
              'usage':usage,'failures':{},'completed':False}
    current, diagnostic, previous_model_error = None, None, False
    failures = Counter()

    def remaining():
        return budget.task_seconds-(time.monotonic()-started)

    def event(stage, **data):
        packet = {'stage':stage,'elapsed':time.monotonic()-started,**data}
        with (output/'events.jsonl').open('a',encoding='utf-8') as f:
            f.write(canonical(packet)+'\n')
        if progress is not None:
            try:
                progress(packet)
            except Exception:
                pass  # an optional display sink must not change the experiment

    def checkpoint():
        result['seconds'] = time.monotonic()-started
        result['failures'] = dict(failures)
        snapshot = policy.snapshot()
        if snapshot is not None:
            result['evidence_metrics'] = snapshot['metrics']
            result['state_sha256'] = digest(canonical(snapshot))
            write_json(output/'state.json', snapshot)
        write_json(output/'result.json',result)

    def verify(source, label):
        task.check_frozen()
        if remaining() <= 0 or usage['verifier_calls'] >= budget.verifier_calls:
            raise RuntimeError('verification_budget_exhausted')
        usage['verifier_calls'] += 1
        policy.begin_candidate(source,label)
        checkpoint()
        before = time.monotonic()
        evidence = verifier.verify(source,names=task.names,timeout=min(remaining(),budget.verification_seconds))
        usage['verification_seconds'] += time.monotonic()-before
        result['real_verifier_executed'] |= bool(evidence.real_verifier and evidence.executed)
        write_json(output/(label+'.verification.json'),evidence.to_dict())
        (output/(label+'.stdout.txt')).write_text(evidence.stdout,encoding='utf-8')
        (output/(label+'.stderr.txt')).write_text(evidence.stderr,encoding='utf-8')
        task.check_frozen()
        if digest(canonical(config)) != manifest['config_sha256']:
            raise BoundaryError('frozen_configuration_changed')
        event('verification',label=label,source_sha256=digest(source),status=evidence.status,
              real_verifier=evidence.real_verifier,executed=evidence.executed)
        policy.observe(source,evidence,label)
        return evidence

    checkpoint()
    try:
        if start is not None:
            current = copy.deepcopy(start['bodies'])
            (output/'initial.dfy').write_text(initial_source,encoding='utf-8')
            write_json(output/'initial.verification.json',start['evidence'].to_dict())
            diagnostic = policy.observe(initial_source,start['evidence'],'initial')
            event('starting_point_loaded',source_sha256=digest(initial_source))
            checkpoint()
        calls = 1 if strategy == 'single_shot' else budget.model_calls
        for step in range(1,calls+1):
            task.check_frozen()
            if remaining() <= 0:
                result['stop_reason'] = 'task_timeout'
                break
            # Iterative/sampling reserve one extra full check of the persisted winner.
            required_checks = 1 if strategy == 'single_shot' else 2
            if budget.verifier_calls-usage['verifier_calls'] < required_checks:
                result['stop_reason'] = 'verification_budget_exhausted'
                break
            messages = policy.messages(task,representation,strategy,current,diagnostic)
            reservation_input = len(canonical(messages).encode())+256
            reserve = reservation_input+budget.output_tokens
            if budget.total_tokens is not None and usage['accounted_tokens']+reserve > budget.total_tokens:
                result['stop_reason'] = 'token_budget_exhausted'
                break
            prices = config['model']['input_usd_per_million'],config['model']['output_usd_per_million']
            reserve_cost = ((reservation_input*prices[0]+budget.output_tokens*prices[1])/1e6
                            if all(p is not None for p in prices) else 0.0)
            if budget.cost_usd is not None and usage['reserved_cost_usd']+reserve_cost > budget.cost_usd:
                result['stop_reason'] = 'cost_budget_exhausted'
                break
            label = f'round_{step:03}'
            write_json(output/(label+'.messages.json'),{'messages':messages,'sha256':digest(canonical(messages))})
            usage['model_calls'] += 1
            usage['model_retry_calls'] += int(previous_model_error)
            usage['accounted_tokens'] += reserve
            usage['reserved_cost_usd'] += reserve_cost
            previous_cost = usage['cost_usd']
            usage['unknown_usage_calls'] += 1
            if model.kind == 'live':
                usage['cost_usd'] = None  # a request interrupted in flight may still be billed
            event('model_call_started',step=step,messages_sha256=digest(canonical(messages)))
            checkpoint()  # interrupted calls are charged/reserved, never silently forgotten
            before = time.monotonic()
            try:
                response = model.generate(messages,budget.output_tokens,min(remaining(),budget.model_seconds),
                                          config['seed']+replicate+step-1)
                if not isinstance(response,dict) or not isinstance(response.get('text'),str):
                    raise ValueError('invalid provider response')
            except Exception as exc:
                response = {'text':'','error':'model_exception','error_type':type(exc).__name__,
                            'input_tokens':None,'output_tokens':None,'cost_usd':None}
            usage['model_seconds'] += time.monotonic()-before
            write_json(output/(label+'.response.json'),response)
            event('model_response_received',step=step,error=response.get('error'),
                  finish_reason=response.get('finish_reason'))
            inp,out = response.get('input_tokens'),response.get('output_tokens')
            measured = type(inp) is int and type(out) is int and inp >= 0 and out >= 0
            if measured:
                usage['input_tokens'] += inp
                usage['output_tokens'] += out
                usage['accounted_tokens'] += inp+out-reserve
                usage['unknown_usage_calls'] -= 1
            cost = response.get('cost_usd')
            if cost is not None:
                usage['reserved_cost_usd'] += cost-reserve_cost
            usage['cost_usd'] = previous_cost+cost if cost is not None and previous_cost is not None else None
            if remaining() <= 0 or (budget.total_tokens is not None and usage['accounted_tokens'] > budget.total_tokens) or (budget.cost_usd is not None and usage['reserved_cost_usd'] > budget.cost_usd):
                result['stop_reason'] = 'budget_exhausted_after_call'
                break
            previous_model_error = bool(response.get('error'))
            if previous_model_error:
                reason = response['error']
                failures[reason] += 1
                result['status'] = reason
                if step == 1 and policy.snapshot() is not None:
                    result['first_attempt_failed'] = True
                diagnostic = {'status':'model_error','category':reason,'additional_spec_disclosure':False}
                policy.reject(diagnostic)
                event('model_error',category=reason)
                checkpoint()
                if reason == 'authentication':
                    result['stop_reason'] = 'authentication'
                    break
                if model.kind == 'live' and response.get('retryable') is False:
                    result['stop_reason'] = reason
                    break
                if model.kind == 'live' and step < calls and reason in {'rate_limit','timeout','connection','server_error'}:
                    delay = response.get('retry_after_seconds')
                    if type(delay) not in {int,float} or delay < 0:
                        delay = min(2**step,8)
                    if delay >= remaining() or delay > 60:
                        result['stop_reason'] = 'provider_retry_delay_exceeds_budget'
                        break
                    event('retry_wait',seconds=delay,category=reason)
                    time.sleep(delay)  # charged to the same task deadline; SDK retries remain off
                continue
            result['candidate_count'] += 1
            try:
                action = json.loads(response['text'])
                if not isinstance(action,dict) or set(action) != {'bodies'}:
                    raise BoundaryError('body-only JSON required')
                source = task.assemble(action['bodies'])
                bodies = action['bodies']
            except (ValueError,TypeError,BoundaryError,RecursionError):
                result['status'] = 'invalid_candidate'
                failures['invalid_candidate'] += 1
                if step == 1 and policy.snapshot() is not None:
                    result['first_attempt_failed'] = True
                diagnostic = {'status':'invalid_candidate','category':'body_format_or_profile',
                              'property_satisfaction':'unknown','additional_spec_disclosure':False}
                policy.reject(diagnostic)
                # Preserve the last valid implementation, not an injected string.
                write_json(output/(label+'.diagnostic.json'),diagnostic)
                event('candidate_rejected',step=step,status='invalid_candidate')
                checkpoint()
                continue
            current = bodies
            write_json(output/(label+'.bodies.json'),bodies)
            (output/(label+'.dfy')).write_text(source,encoding='utf-8')
            if strategy == 'single_shot':
                (output/'final.dfy').write_text(source,encoding='utf-8')
                source = (output/'final.dfy').read_text(encoding='utf-8')
                task.layout(source)
                evidence = verify(source,'final')
            else:
                evidence = verify(source,label)
            result['status'] = evidence.status
            if policy.snapshot() is not None and step == 1:
                result['first_attempt_failed'] = evidence.status != 'verified'
            diagnostic = policy.diagnostic(task,source,evidence)
            write_json(output/(label+'.diagnostic.json'),diagnostic)
            if evidence.status != 'verified':
                failures[evidence.status] += 1
                checkpoint()
                continue
            if strategy != 'single_shot':
                (output/'final.dfy').write_text(source,encoding='utf-8')
                source = (output/'final.dfy').read_text(encoding='utf-8')
                task.layout(source)
                evidence = verify(source,'final')
            result['status'] = evidence.status
            result['final_sha256'] = digest(source)
            result['final_verification'] = evidence.to_dict()
            task.check_frozen()
            if (output/'final.dfy').read_text(encoding='utf-8') != source:
                raise BoundaryError('final_artifact_changed')
            result['success'] = (evidence.status == 'verified' and evidence.real_verifier
                                 and evidence.executed and remaining() > 0)
            result['first_candidate_verified'] = result['candidate_count'] == 1 and result['success']
            result['stop_reason'] = 'verified' if result['success'] else 'final_verification_not_accepted'
            if not result['success']:
                failures[result['stop_reason']] += 1
            break
        if strategy == 'single_shot' and not result['success'] and result['stop_reason'] == 'model_budget_exhausted':
            result['stop_reason'] = 'single_shot_complete'
        if remaining() <= 0:
            result['success'] = False
            result['stop_reason'] = 'task_timeout'
        result['completed'] = True
    except KeyboardInterrupt:
        result['stop_reason'] = 'interrupted'
        event('interrupted')
        raise
    except (BoundaryError,RuntimeError,OSError) as exc:
        result['success'] = False
        result['status'] = 'tool_error'
        result['stop_reason'] = str(exc) if isinstance(exc,(BoundaryError,RuntimeError)) else type(exc).__name__
        result['completed'] = True
        failures['tool_error'] += 1
        event('run_error',error_type=type(exc).__name__)
    finally:
        checkpoint()
        event('run_finished',success=result['success'],stop_reason=result['stop_reason'],
              model_calls=usage['model_calls'],verifier_calls=usage['verifier_calls'])
    return result
