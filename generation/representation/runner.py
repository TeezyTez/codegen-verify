"""One body-only loop for all representations/strategies, never the legacy full-spec prompt."""
from pathlib import Path
import time

from repair.task import digest
from . import PROTOCOL, REPRESENTATIONS, STRATEGIES
from .config import validate_config
from .models import SYSTEM
from .task import canonical
from .verifier import feedback


def source_hashes():
    root = Path(__file__).resolve().parents[1]
    paths = [root/'engine.py',*sorted(Path(__file__).parent.glob('*.py')),root/'task.py',
             root.parent/'repair'/'task.py',root.parent/'repair'/'verifier.py',
             root.parent/'repair'/'runner.py',root.parent/'project'/'config.py',
             root.parent/'project'/'dafny_wrapper.py']
    return {str(p.relative_to(root.parent)):digest(p.read_text(encoding='utf-8')) for p in paths}


def messages_for(task, representation, strategy, current=None, diagnostic=None):
    if strategy not in STRATEGIES or representation not in REPRESENTATIONS:
        raise ValueError('unknown experimental condition')
    content = {'task':task.public(representation),
               'feedback_policy':'controlled_v1' if strategy == 'iterative_repair' else 'none'}
    if strategy == 'iterative_repair' and diagnostic is not None:
        content['current_bodies'] = current
        content['diagnostic'] = diagnostic
    return [{'role':'system','content':SYSTEM},{'role':'user','content':canonical(content)}]


class Policy:
    protocol = PROTOCOL
    system = SYSTEM
    feedback_policy = 'controlled_v1'
    validate_config = staticmethod(validate_config)
    source_hashes = staticmethod(source_hashes)
    messages = staticmethod(messages_for)
    diagnostic = staticmethod(feedback)

    def observe(self, source, evidence, label):
        pass

    def begin_candidate(self, source, label):
        pass

    def reject(self, diagnostic):
        pass

    def snapshot(self):
        return None


def run(task, model, verifier, output, *, config, strategy, representation, replicate=0, progress=None):
    from generation.engine import run as execute
    return execute(task, model, verifier, output, config=config, strategy=strategy,
                   representation=representation, replicate=replicate, progress=progress, policy=Policy())
