"""Auditable, one-process Codex transport. This module never reads credentials."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlsplit


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def parse_codex_events(stdout, *, model, effort):
    """Fail closed; fixtures exercising this function are not model samples."""
    result = {'text':'', 'error':None, 'usage':None, 'input_tokens':None,
              'output_tokens':None, 'model':model, 'effort':effort,
              'response_model':None, 'response_effort':None,
              'identity_source':'requested_cli_arguments; response_identity_unavailable',
              'usage_source':'unknown', 'transport_events':[]}
    finals, terminals, starts = [], [], 0
    errors = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            errors.append('malformed_jsonl')
            continue
        if not isinstance(event, dict) or not isinstance(event.get('type'),str):
            errors.append('malformed_event')
            continue
        kind = event['type']
        if terminals:
            errors.append('event_after_terminal')
        metadata = [event]
        if isinstance(event.get('item'),dict):
            metadata.append(event['item'])
        for row in metadata:
            for key, expected, output in [('model',model,'response_model'),
                                          ('model_reasoning_effort',effort,'response_effort'),
                                          ('effort',effort,'response_effort')]:
                if row.get(key) is not None:
                    result[output] = row[key]
                    if row[key] != expected:
                        errors.append('identity_mismatch')
        if kind == 'turn.started':
            starts += 1
        elif kind == 'error':
            result['transport_events'].append(event)
            errors.append('transport_error')
        elif kind == 'turn.failed':
            result['transport_events'].append(event)
            errors.append('turn_failed')
        elif kind == 'turn.completed':
            terminals.append(event)
        elif kind in {'item.started','item.updated','item.completed'}:
            item = event.get('item')
            if not isinstance(item,dict) or not isinstance(item.get('type'),str):
                errors.append('malformed_event')
                continue
            item_type = item['type']
            if item_type not in {'agent_message','reasoning','todo_list','error'}:
                errors.append('tool_use_rejected')
            elif item_type == 'error':
                errors.append('transport_error')
            elif item_type == 'agent_message' and kind == 'item.completed':
                if not isinstance(item.get('text'),str):
                    errors.append('malformed_event')
                else:
                    finals.append(item['text'])
        elif kind not in {'thread.started','session.configured'}:
            errors.append('unsupported_event')
    if len(terminals) == 1:
        usage = terminals[0].get('usage')
        if (isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k] >= 0
                                          for k in ('input_tokens','output_tokens'))):
            result.update(usage=usage,input_tokens=usage['input_tokens'],
                          output_tokens=usage['output_tokens'],usage_source='codex_turn_completed')
        else:
            errors.append('invalid_usage')
    elif not terminals:
        errors.append('missing_terminal_completion')
    else:
        errors.append('multiple_terminal_completions')
    if not starts:
        errors.append('missing_turn_start')
    elif starts > 1:
        errors.append('multiple_turns')
    if len(finals) > 1:
        errors.append('multiple_final_messages')
    elif not finals or not finals[0].strip():
        errors.append('missing_final_message')
    if result['response_model'] is not None or result['response_effort'] is not None:
        result['identity_source'] = 'requested_cli_arguments; available_response_fields_checked'
    if errors:
        result['error'] = errors[0]
        result['errors'] = list(dict.fromkeys(errors))
    else:
        result['text'] = finals[0]
    return result


class CodexModel:
    kind = 'live'

    def __init__(self, model='gpt-6-astra', effort='high', codex_home=None, proxy=None):
        if not model or not effort:
            raise ValueError('explicit model and effort are required')
        if codex_home is None:
            codex_home = os.environ.get('CODEX_HOME')
        if not codex_home:
            raise ValueError('existing codex_home must be supplied')
        if proxy:
            parsed = urlsplit(proxy)
            if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('proxy must be an HTTP(S) endpoint without embedded credentials')
        self.model, self.effort = model, effort
        self.codex_home, self.proxy = str(Path(codex_home).resolve()), proxy
        self.executable = shutil.which('codex') or 'codex'

    def identity(self):
        return {'kind':'live','provider':'codex_cli_chatgpt','model':self.model,'effort':self.effort,
                'identity_source':'requested_cli_arguments','executable':self.executable,
                'codex_home':self.codex_home,'proxy':self.proxy,
                'context':'fresh_ephemeral_cli_process','message_encoding':'role_labeled_json_in_cli_prompt',
                'output_cap_enforced':False,'output_cap_support':'not exposed by installed CLI help or documented config',
                'provider_config_id':'openai_batch','provider_endpoint':'OpenAI default selected by existing login',
                'wrapper_retries':0,'provider_request_max_retries_requested':0,
                'provider_stream_max_retries_requested':0,'seed_supported':False,
                'response_identity_support':'checked when emitted; otherwise unavailable',
                'price_source':'unknown; ChatGPT account usage, no invented dollar cost'}

    def generate(self, messages, output_dir, timeout=900, max_output_tokens=16384):
        if not isinstance(messages,list) or not messages:
            raise ValueError('messages must be a nonempty role/content list')
        if any(not isinstance(m,dict) or m.get('role') not in {'system','developer','user','assistant'}
               or not isinstance(m.get('content'),str) for m in messages):
            raise ValueError('only explicit text messages are supported')
        if timeout <= 0 or type(max_output_tokens) is not int or max_output_tokens <= 0:
            raise ValueError('positive timeout and output budget required')
        root = Path(output_dir).resolve()
        root.mkdir(parents=True,exist_ok=False)
        work = root/'work'
        work.mkdir()
        # This is a disclosed serialization, not native API role injection.
        prompt = ('Complete the task in the following role-labeled message transcript. '
                  'Do not call tools or inspect files. Return only the final answer requested by the transcript.\n'
                  + _json(messages))
        command = [self.executable,'exec','--ignore-user-config','--strict-config','--ephemeral',
                   '--skip-git-repo-check','--sandbox','read-only','--json','--model',self.model,
                   '--cd',str(work)]
        overrides = {'model_reasoning_effort':self.effort,'model_provider':'openai_batch',
                     'web_search':'disabled','project_doc_max_bytes':0,
                     'log_dir':(root/'logs').as_posix(),'sqlite_home':(root/'state').as_posix(),
                     'model_providers.openai_batch.name':'OpenAI (batch, no retries)',
                     'model_providers.openai_batch.requires_openai_auth':True,
                     'model_providers.openai_batch.wire_api':'responses',
                     'model_providers.openai_batch.request_max_retries':0,
                     'model_providers.openai_batch.stream_max_retries':0}
        for feature in ('shell_tool','shell_snapshot','unified_exec','multi_agent','apps','plugins','memories','hooks'):
            overrides['features.'+feature] = False
        for key,value in overrides.items():
            command += ['-c',key+'='+json.dumps(value)]
        command += ['-']
        request = {'identity':self.identity(),'messages':messages,'prompt':prompt,'command':command,
                   'timeout_seconds':timeout,'max_output_tokens_requested':max_output_tokens,
                   'output_cap_enforced':False,'environment_overrides':{'CODEX_HOME':self.codex_home}}
        child_env = os.environ.copy()
        child_env['CODEX_HOME'] = self.codex_home
        if self.proxy:
            child_env['HTTPS_PROXY'] = self.proxy
            request['environment_overrides']['HTTPS_PROXY'] = self.proxy
        # Do not silently switch the requested existing-login route to environment credentials.
        for key in ('CODEX_API_KEY','OPENAI_API_KEY','CODEX_ACCESS_TOKEN','OPENAI_BASE_URL'):
            child_env.pop(key,None)
        request['environment_keys_removed'] = ['CODEX_API_KEY','OPENAI_API_KEY','CODEX_ACCESS_TOKEN','OPENAI_BASE_URL']
        request_hash = _digest(_json(request))
        request['request_sha256'] = request_hash
        request['command_sha256'] = _digest(_json(command))
        (root/'request.json').write_text(_json(request),encoding='utf-8')
        (root/'prompt.txt').write_text(prompt,encoding='utf-8')
        started = time.monotonic()
        stdout,stderr,process_error,exit_code,executed = '','',None,None,False
        try:
            process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',
                                       env=child_env,cwd=str(work))
            executed = True
            try:
                stdout,stderr = process.communicate(prompt,timeout=timeout)
            except subprocess.TimeoutExpired as timeout_exc:
                process_error = 'process_timeout'
                if os.name == 'nt':
                    try:
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
                    except (OSError,subprocess.TimeoutExpired):
                        process.kill()
                else:
                    process.kill()
                try:
                    stdout,stderr = process.communicate(timeout=15)
                except subprocess.TimeoutExpired as drain_exc:
                    def decoded(value):
                        return value.decode('utf-8',errors='replace') if isinstance(value,bytes) else value or ''
                    stdout = decoded(drain_exc.output or timeout_exc.output)
                    stderr = decoded(drain_exc.stderr or timeout_exc.stderr)
                    process_error = 'process_timeout_cleanup_incomplete'
            exit_code = process.returncode
            if exit_code != 0 and process_error is None:
                process_error = 'process_exit_nonzero'
        except OSError as exc:
            process_error = 'process_launch_failed' if not executed else 'process_io_failed'
            stderr = type(exc).__name__
        (root/'stdout.jsonl').write_text(stdout,encoding='utf-8')
        (root/'stderr.txt').write_text(stderr,encoding='utf-8')
        result = parse_codex_events(stdout,model=self.model,effort=self.effort)
        if process_error:
            result.update(text='',error=process_error)
        result.update(executed=executed,exit_code=exit_code,elapsed_seconds=time.monotonic()-started,
                      failure_kind='infrastructure' if result['error'] else None,
                      raw_logs={'stdout':str(root/'stdout.jsonl'),'stderr':str(root/'stderr.txt'),
                                'request':str(root/'request.json')},
                      request_sha256=request_hash,command_sha256=request['command_sha256'],
                      output_cap_enforced=False,max_output_tokens_requested=max_output_tokens,
                      output_budget_exceeded=(result['output_tokens'] > max_output_tokens
                                              if result['output_tokens'] is not None else None))
        (root/'result.json').write_text(_json(result),encoding='utf-8')
        return result
