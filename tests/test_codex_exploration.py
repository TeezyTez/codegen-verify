import json
import threading

import pytest


def test_queue_preserves_raw_response_and_unknown_usage(tmp_path):
    from generation.obligations.exploration import QueueModel, submit
    model = QueueModel(tmp_path)
    received = []
    worker = threading.Thread(target=lambda: received.append(model.generate([{'role':'user','content':'public'}],4096,2,17)))
    worker.start()
    import time
    deadline = time.monotonic()+2
    while not (tmp_path/'001/request.json').exists() and time.monotonic()<deadline:
        time.sleep(.01)
    request = json.loads((tmp_path/'001/request.json').read_text())
    raw = '  {"bodies":{"F":"return 1;"}}\n'
    submit(tmp_path/'001', request['request_id'], raw, 'solver-test')
    worker.join(3)
    assert received[0]['text'] == raw
    assert received[0]['input_tokens'] is None and received[0]['cost_usd'] is None
    with pytest.raises(FileExistsError):
        submit(tmp_path/'001', request['request_id'], raw, 'solver-test')


def test_queue_rejects_wrong_identity_and_timeout_is_unknown(tmp_path):
    from generation.obligations.exploration import QueueModel, submit
    result = QueueModel(tmp_path).generate([],4096,.02,17)
    assert result['error'] == 'timeout' and result['retryable'] is False
    assert result['cost_usd'] is None
    with pytest.raises(ValueError, match='identity'):
        submit(tmp_path/'001', 'wrong', '{}', 'solver-test')


def test_exploration_protocol_and_unenforced_caps():
    from generation.obligations.exploration import ExplorationPolicy, configuration
    from generation.obligations.config import validate_config
    c = configuration()
    b = ExplorationPolicy.validate_config(c)
    assert b.total_tokens is None and b.model_calls == 4 and b.verifier_calls == 5
    assert ExplorationPolicy.protocol != 'fixed_spec_obligation_v1'
    with pytest.raises(ValueError):
        validate_config(c)
