"""Synthetic CLI fixtures only; never count these as research generations."""
import json
from pathlib import Path
import subprocess

import pytest

from generation.public_benchmark.model import CodexModel, parse_codex_events


def events(*extra, usage=None):
    rows = [{'type':'thread.started','thread_id':'synthetic'}, {'type':'turn.started'}, *extra,
            {'type':'item.completed','item':{'id':'answer','type':'agent_message','text':'{"ready":true}'}},
            {'type':'turn.completed','usage':usage or {'input_tokens':100,'output_tokens':9,'cached_input_tokens':20}}]
    return '\n'.join(json.dumps(row) for row in rows)


def test_completed_generation_preserves_actual_usage_and_unknown_identity():
    result = parse_codex_events(events(), model='gpt-6-astra', effort='high')
    assert result['error'] is None
    assert result['text'] == '{"ready":true}'
    assert (result['input_tokens'],result['output_tokens']) == (100,9)
    assert result['usage']['cached_input_tokens'] == 20
    assert result['response_model'] is None
    assert result['identity_source'] == 'requested_cli_arguments; response_identity_unavailable'


@pytest.mark.parametrize('data,expected', [
    ('not json', 'malformed_jsonl'),
    ('[]', 'malformed_event'),
    (json.dumps({'type':'turn.started'}), 'missing_terminal_completion'),
    (events({'type':'item.started','item':{'type':'command_execution','command':'whoami'}}), 'tool_use_rejected'),
    (events({'type':'item.completed','item':{'id':'other','type':'agent_message','text':'extra'}}), 'multiple_final_messages'),
    (events({'type':'error','message':'Reconnecting...'}), 'transport_error'),
    (json.dumps({'type':'turn.failed','error':{'message':'quota'}}), 'turn_failed'),
    (events({'type':'session.configured','model':'different'}), 'identity_mismatch'),
    (events(usage={'input_tokens':-1,'output_tokens':4}), 'invalid_usage'),
])
def test_rejects_incomplete_or_untrusted_event_stream(data, expected):
    result = parse_codex_events(data, model='gpt-6-astra', effort='high')
    assert result['error'] == expected
    assert result['text'] == ''


def test_no_usage_does_not_become_zero():
    result = parse_codex_events(events().replace('"usage": {"input_tokens": 100, "output_tokens": 9, "cached_input_tokens": 20}', '"usage": null'), model='gpt-6-astra', effort='high')
    assert result['error'] == 'invalid_usage'
    assert result['input_tokens'] is None


def test_message_after_completion_is_not_accepted():
    rows = events().splitlines()
    rows[-2], rows[-1] = rows[-1], rows[-2]
    result = parse_codex_events('\n'.join(rows),model='gpt-6-astra',effort='high')
    assert result['error'] == 'event_after_terminal'


def test_final_item_model_metadata_is_checked():
    rows = [json.loads(row) for row in events().splitlines()]
    rows[-2]['item']['model'] = 'wrong-model'
    result = parse_codex_events('\n'.join(json.dumps(row) for row in rows),model='gpt-6-astra',effort='high')
    assert result['error'] == 'identity_mismatch'


def test_timeout_preserves_partial_output_and_never_retries(tmp_path, monkeypatch):
    launches = []
    class Process:
        pid = 999999
        returncode = -9
        calls = 0
        def __init__(self, *a, **k): launches.append(1)
        def kill(self): pass
        def communicate(self, *a, **k):
            self.calls += 1
            if self.calls == 1: raise subprocess.TimeoutExpired('synthetic',1)
            return '{"type":"turn.started"}', 'partial'
    monkeypatch.setattr(subprocess,'Popen',Process)
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: None)
    result = CodexModel(codex_home=tmp_path/'home').generate([{'role':'user','content':'x'}],tmp_path/'run',timeout=1)
    assert result['error'] == 'process_timeout' and result['executed']
    assert result['input_tokens'] is None and len(launches) == 1
    assert Path(result['raw_logs']['stderr']).read_text() == 'partial'


def test_adapter_persists_request_and_process_logs_without_credentials(tmp_path, monkeypatch):
    observed = {}
    class Process:
        pid = 999999
        returncode = 0
        def __init__(self, command, **kwargs): observed.update(command=command, **kwargs)
        def communicate(self, prompt=None, timeout=None):
            observed['prompt'] = prompt
            return events(), ''
    monkeypatch.setattr(subprocess, 'Popen', Process)
    model = CodexModel(codex_home=tmp_path/'existing-login', proxy='http://127.0.0.1:10808')
    target = tmp_path/'generation'
    result = model.generate([{'role':'system','content':'Do task.'},{'role':'user','content':'Input.'}], target)
    assert result['error'] is None and result['executed'] is True
    assert result['output_cap_enforced'] is False
    assert observed['env']['HTTPS_PROXY'] == 'http://127.0.0.1:10808'
    assert observed['env']['CODEX_HOME'] == str((tmp_path/'existing-login').resolve())
    assert '--ephemeral' in observed['command'] and '--ignore-user-config' in observed['command']
    assert 'features.shell_tool=false' in observed['command']
    assert 'model_providers.openai_batch.stream_max_retries=0' in observed['command']
    assert '--model' in observed['command'] and 'gpt-6-astra' in observed['command']
    request = json.loads((target/'request.json').read_text())
    assert request['output_cap_enforced'] is False
    assert len(result['request_sha256']) == 64
    assert Path(result['raw_logs']['stdout']).read_text() == events()
    assert json.loads((target/'result.json').read_text())['error'] is None
    with pytest.raises(FileExistsError):
        model.generate([{'role':'user','content':'Input.'}], target)


def test_nonzero_exit_is_infrastructure_failure_even_with_answer(tmp_path, monkeypatch):
    class Process:
        returncode = 7
        def __init__(self, *a, **k): pass
        def communicate(self, *a, **k): return events(), 'synthetic crash'
    monkeypatch.setattr(subprocess, 'Popen', Process)
    result = CodexModel(codex_home=tmp_path/'home').generate([{'role':'user','content':'x'}],tmp_path/'run')
    assert result['error'] == 'process_exit_nonzero'
    assert result['text'] == '' and result['failure_kind'] == 'infrastructure'


def test_launch_failure_is_saved_without_retry(tmp_path, monkeypatch):
    count = []
    def fail(*a, **k):
        count.append(1)
        raise FileNotFoundError('synthetic absent executable')
    monkeypatch.setattr(subprocess, 'Popen', fail)
    result = CodexModel(codex_home=tmp_path/'home').generate([{'role':'user','content':'x'}],tmp_path/'run')
    assert result['error'] == 'process_launch_failed' and result['executed'] is False
    assert len(count) == 1
    assert (tmp_path/'run'/'result.json').exists()
