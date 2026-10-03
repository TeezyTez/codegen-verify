"""Challenge data checks; no model API requests."""
import json
from pathlib import Path
import shutil

import pytest

from generation.representation import REPRESENTATIONS
from generation.representation.config import load_config
from generation.representation.runner import messages_for
from generation.representation.task import load_tasks
from generation.representation.verifier import Dafny

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'generation/representation/challenge_tasks'


def test_challenge_manifest_and_budget():
    tasks = load_tasks(DATA)
    assert {t.meta['id'] for t in tasks} == {'binary_lower_bound', 'integer_sqrt', 'sequence_reverse'}
    config = load_config(ROOT / 'generation/representation/configs/deepseek-challenge.json')
    assert len(tasks) * config['replicates'] == 9
    assert config['budget']['model_calls'] == 4
    for task in tasks:
        assert task.meta['origin'] == 'synthetic_demo'
        assert task.meta['split'] == 'dev'
        assert task.meta['equivalence_audit']['status'] == 'pending'
        for representation in REPRESENTATIONS:
            message = messages_for(task, representation, 'iterative_repair')[1]['content']
            public = json.loads(message)['task']
            assert public == task.public(representation)
            assert set(public) == {'task_id', 'signatures', 'shared_definitions', 'requirements'}
            assert 'reference' not in public and 'ensures' not in message


@pytest.mark.parametrize('task_id', ['binary_lower_bound', 'integer_sqrt', 'sequence_reverse'])
def test_challenge_real_admission(task_id):
    verifier = Dafny(timeout=15)
    if not (shutil.which(verifier.path) or Path(verifier.path).is_file()):
        pytest.skip('Dafny unavailable: real verification NOT executed')
    task = next(t for t in load_tasks(DATA) if t.meta['id'] == task_id)
    good = verifier.verify(task.assemble(task.meta['reference']), names=task.names)
    bad = verifier.verify(task.assemble(task.meta['mutants'][0]['bodies']), names=task.names)
    assert good.real_verifier and good.status == 'verified'
    assert bad.real_verifier and bad.status == 'verification_failed'
    task.check_frozen()
